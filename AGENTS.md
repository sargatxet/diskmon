# AGENTS.md — guía para agentes y colaboradores

Este documento describe cómo trabajar en **DiskMon** sin romper su alcance, sus
convenciones ni la seguridad del sistema donde se ejecuta. Está dirigido a
agentes de código y a personas que se incorporen al proyecto.

## 1. Propósito

DiskMon es un monitor de salud de discos para **Linux nativo** que:

1. descubre discos físicos y particiones con `lsblk`;
2. lee SMART de discos ATA/SATA y NVMe con `smartctl`;
3. calcula una puntuación de salud explicable de 0 a 100;
4. guarda histórico en SQLite y ofrece CLI, JSON y dashboard web local;
5. permite lanzar auto-tests SMART y comprobar el entorno con `doctor`.

## 2. Alcance soportado

- **Sistema:** Linux nativo con systemd. **No** se soportan Windows, WSL ni macOS.
- **Mínimos:** Debian 11, Ubuntu 22.04 LTS, Linux Mint 21.
- **Probado:** Linux Mint 22.x / Ubuntu 24.x.
- **Python:** ≥ 3.9. En 3.9/3.10 se usa `tomli` solo para leer TOML; en 3.11+ no
  hay dependencias externas.
- **Herramientas:** `util-linux` ≥ 2.36 (`lsblk -J`) y `smartmontools` ≥ 7.2
  (`smartctl -j`).
- **Fuera de alcance:** notificaciones, autenticación del dashboard, RAID por
  hardware, Windows/WSL/macOS y versiones antiguas de las distros indicadas.

Antes de cambiar compatibilidad, actualiza `REQUIREMENTS.md`, `README.md` y
`diskmon/doctor.py`.

## 3. Puesta en marcha rápida

```bash
cd "$(git rev-parse --show-toplevel)"

./bin/diskmon doctor          # valida el entorno (no modifica discos)
./bin/diskmon scan            # análisis real; guarda histórico por defecto
./bin/diskmon scan --no-save --no-color
./bin/diskmon serve           # dashboard en http://127.0.0.1:8765
python3 -m pytest             # suite completa
pyflakes diskmon tests        # análisis estático (opcional)
```

En tests y pruebas manuales usa siempre configuración temporal para no contaminar
el histórico del usuario:

```bash
cat > /tmp/diskmon-test.toml <<'EOF'
db_path = "/tmp/diskmon-test.db"
fail_on = "critical"
EOF
./bin/diskmon scan --config /tmp/diskmon-test.toml --no-save
```

## 4. Mapa del código

```
diskmon/
  cli.py                 argparse, subcomandos y códigos de salida
  config.py              TOML, umbrales y valores por defecto
  models.py              dataclasses serializables (DiskInfo, SmartInfo, HealthReport)
  collect/
    blockdev.py          lsblk, particiones y uso statvfs
    smart.py             smartctl, sudo, parser ATA/NVMe
  analysis.py            reglas, penalizaciones, nota y veredicto
  report.py              salida de texto con color, tablas y JSON
  history.py             SQLite (WAL) e histórico
  web.py                 dashboard y API HTTP con biblioteca estándar
  doctor.py              comprobación de requisitos del entorno
tests/                   pytest; fixtures SMART reales y casos sintéticos
systemd/                 unidades de usuario (servicio, timer y web)
```

## 5. Flujo de datos

```
lsblk -J ──► collect_disks() ──► DiskInfo
smartctl -a -j ──► collect_smart() ──► SmartInfo
                                  │
                                  ▼
                         analysis.analyze_disk()
                                  │
                                  ▼
                         HealthReport / ScanResult
                          │        │         │
                       report   history    web/API
```

- `collect` solo obtiene datos; **no** decide salud.
- `analysis` es la única capa que puntúa y genera `HealthIssue`.
- `report`, `history` y `web` consumen `HealthReport`/`ScanResult`.

## 6. Convenciones de código

- **Idioma:** documentación, mensajes de usuario y nombres de comandos en
  español; identificadores de código, docstrings técnicos y nombres de tablas en
  inglés.
- **Tipado:** anotaciones de tipo y `from __future__ import annotations`.
- **Datos:** dataclasses en `models.py`; añade `to_dict()` si el dato debe
  aparecer en JSON o en el histórico.
- **Sin dependencias nuevas en Python 3.11+.** Si una dependencia es inevitable,
  justifícala en `REQUIREMENTS.md` y añade el marcador de versión en
  `pyproject.toml`.
- **Sin red.** El dashboard es local y no debe cargar CDN, fuentes ni scripts
  externos.
- **Errores:** no ocultes fallos de SMART. Si no hay datos, usa salud
  `Desconocido`; no inventes una puntuación.
- **Salida:** mantén el esquema JSON `diskmon/1` y los códigos de salida
  documentados. Cambiar el esquema requiere actualizar `REQUIREMENTS.md`,
  `CHANGELOG.md` y tests.
- **Formato:** líneas ≤ 100 caracteres cuando sea razonable; sin formateadores
  obligatorios, pero evita ruido en el diff.

## 7. Cómo añadir una regla SMART

1. Añade la regla en `analysis.py` dentro de `analyze_disk()`.
2. Usa `add(severity, code, message, penalty, category)` con un `code` estable en
   `snake_case`.
3. Justifica la penalización y actualiza los umbrales en `config.Thresholds` si
   debe ser configurable; documenta el umbral en `config.example.toml`.
4. Añade un test en `tests/test_analysis.py` con un disco sano y otro con el
   atributo modificado. No dependas del hardware real.
5. Si la regla afecta a la nota/veredicto, revisa los topes de coherencia y los
   tests de `grade_for`/`_verdict_for`.
6. Actualiza `README.md` (tabla de penalizaciones) y `CHANGELOG.md`.

## 8. Tests y calidad

```bash
python3 -m pytest -q
python3 -m pytest -v
pyflakes diskmon tests
python3 -m compileall -q diskmon tests
```

Comprobación de sintaxis compatible con Python 3.9:

```bash
python3 - <<'EOF'
import ast, pathlib
for p in list(pathlib.Path("diskmon").rglob("*.py")) + list(pathlib.Path("tests").rglob("*.py")):
    ast.parse(p.read_text(), filename=str(p), feature_version=(3, 9))
print("sintaxis 3.9 OK")
EOF
```

Reglas para tests:

- Usa `tmp_path` para bases de datos y configuración.
- No escribas en `~/.local/share/diskmon/` desde tests.
- No lances `smartctl -t` (auto-tests) en CI ni en tests automáticos.
- `tests/test_doctor.py` puede leer el entorno real; no debe requerir SMART
  disponible, solo validar que las comprobaciones devuelven estados válidos.
- Los fixtures de `tests/fixtures/` son datos reales anonimizados de discos; no
  los sustituyas por mocks si la prueba necesita el esquema real de smartctl.

## 9. Operaciones seguras

- **SMART requiere privilegios.** `sudo -n` se usa si está disponible; no añadas
  `sudo` interactivo a comandos automáticos.
- **No modifiques discos** desde `scan`, `doctor` ni el dashboard. La única
  operación que escribe en un disco es `selftest` (orden explícita del usuario).
- **No expongas el dashboard** en `0.0.0.0` sin proxy y autenticación. Por
  defecto escucha en `127.0.0.1`.
- **No incluyas secretos** (contraseñas, tokens, seriales de clientes) en tests,
  fixtures, logs ni documentación.
- Si cambias la regla `sudoers` recomendada, limita el acceso a lectura SMART y
  a auto-tests; nunca a un shell genérico.

## 10. Documentación y release

Todo cambio relevante debe actualizar, según corresponda:

- `README.md`: uso visible para el usuario.
- `REQUIREMENTS.md`: alcance, requisitos y criterios de aceptación.
- `CHANGELOG.md`: entrada en `[Unreleased]` o versión nueva.
- `TODO.md`: marcar completado o añadir trabajo pendiente.
- `AGENTS.md`: convenciones o arquitectura si cambian.
- `pyproject.toml`: versión y metadatos si hay release.

Checklist de release:

1. `python3 -m pytest -q` en verde.
2. `pyflakes diskmon tests` sin avisos.
3. `./bin/diskmon doctor` sin fallos en una máquina objetivo.
4. `./bin/diskmon scan --no-save` y `./bin/diskmon serve` comprobados.
5. `CHANGELOG.md` con fecha y versión.
6. `pyproject.toml` y `diskmon/__init__.py` con la misma versión.
7. Commit de release y tag anotado `vX.Y.Z`.
8. Publicar la release en GitHub sobre ese tag: GitHub genera el `.tar.gz` y el
   `.zip` del código fuente, que es el artefacto de descarga sin clonar.

## 11. Git

- Repositorio único, rama principal `main`.
- Commits pequeños y atómicos; mensajes en imperativo y con prefijo:
  `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.
- No commitear `__pycache__/`, `.pytest_cache/`, `*.egg-info/`, bases de datos
  `*.db*` ni configuraciones locales. Ya están en `.gitignore`.
- Antes de commitear: `git status`, `git diff --check` y los tests.

## 12. Limitaciones conocidas

- SMART puede no estar disponible en puentes USB/SATA, VMs, contenedores o RAID
  por hardware; se muestra `Desconocido`.
- Los atributos SMART son específicos de cada fabricante; los desconocidos se
  conservan en el JSON pero no se interpretan.
- El desgaste de SSD es una estimación basada en lo que exponga el firmware.
- El uso de sistemas de ficheros con subvolúmenes (btrfs/ZFS) puede no reflejar
  cuotas internas.
- El dashboard no tiene autenticación; está pensado para localhost.

Ante cualquier aviso crítico, la recomendación al usuario es siempre hacer copia
de seguridad antes de sustituir un disco.
