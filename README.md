# DiskMon — monitor de salud de discos para Linux

Herramienta en Python para **Linux nativo** (Debian 11+, Ubuntu 22.04+, Linux
Mint 21+) que analiza los discos físicos usando **SMART** (ATA/SATA y NVMe),
calcula una **puntuación de salud de 0 a 100** y explica los motivos. Incluye
CLI, histórico SQLite, dashboard web local y auto-tests SMART.

**Estado:** v1.0.0. Probado en Linux Mint 22.x / Ubuntu 24.x con
smartmontools 7.x.

## Características

- Detección automática de discos y particiones con `lsblk` (SSD, HDD, NVMe, USB).
- Lectura SMART vía `smartctl -a -j` con reintentos (`-d sat`, `-d nvme`,
  puentes USB) y uso opcional de `sudo -n`.
- Análisis explicable: sectores reasignados, pendientes, no corregibles,
  errores CRC, timeouts, reintentos de giro, temperatura, horas de uso,
  desgaste de SSD/NVMe, bloques de reserva, auto-tests y logs de error.
- Puntuación 0–100, nota (Excelente/Buena/Precaución/Degradada/Crítica) y
  veredicto (SANA/VIGILAR/EN RIESGO/FALLANDO).
- Histórico en SQLite con evolución de puntuación, temperatura y desgaste.
- Dashboard web local sin dependencias externas ni CDN.
- Salida JSON para integrarse con otros sistemas y códigos de salida para cron.
- Auto-test SMART (`short`, `long`, `conveyance`, `offline`).
- Tests automatizados con datos SMART reales y casos de fallo sintéticos.

## Documentación

| Documento | Contenido |
|---|---|
| [REQUIREMENTS.md](REQUIREMENTS.md) | Alcance, requisitos funcionales/no funcionales y criterios de aceptación |
| [AGENTS.md](AGENTS.md) | Guía para agentes y colaboradores: arquitectura, convenciones y tests |
| [CHANGELOG.md](CHANGELOG.md) | Historial de versiones |
| [TODO.md](TODO.md) | Trabajo pendiente y hoja de ruta |
| [LICENSE](LICENSE) | Licencia MIT |

## Instalación

Requisitos: Python ≥ 3.9, `util-linux` ≥ 2.36, `smartmontools` ≥ 7.2 y systemd.

```bash
sudo apt install smartmontools util-linux
# Solo en Python 3.9/3.10 si quieres usar configuración TOML:
sudo apt install python3-tomli
```

Comprueba la máquina destino antes de nada:

```bash
./bin/diskmon doctor
```

Uso directo sin instalar nada:

```bash
./bin/diskmon scan
```

Instalación como comando del usuario (enlace simbólico):

```bash
make install          # crea ~/.local/bin/diskmon
# asegúrate de que ~/.local/bin está en PATH
```

Alternativa empaquetada:

```bash
pipx install .        # o: python3 -m pip install --user .
```

### Descargar sin clonar el repositorio

Cada versión se publica como *release* de GitHub con el archivo fuente
comprimido que genera el propio GitHub, así que no necesitas `git` ni clonar
nada:

```bash
# Desde la página de releases, o directamente (ajusta la versión):
curl -LO https://github.com/sargatxet/diskmon/archive/refs/tags/v1.0.0.tar.gz
tar xzf v1.0.0.tar.gz
cd diskmon-1.0.0

./bin/diskmon doctor          # valida el entorno
./bin/diskmon scan            # análisis real
make install                  # opcional: enlace en ~/.local/bin/diskmon
```

La misma release ofrece el archivo en `.zip`. El contenido es el árbol de
fuentes completo: lanzador `bin/diskmon`, unidades `systemd/`,
`config.example.toml`, tests y documentación. No incluye binarios ni
dependencias de Python instaladas, así que siguen aplicando los requisitos de
arriba; el código descargado corresponde exactamente al tag `v1.0.0`.

## Permisos para leer SMART

SMART necesita acceso a los dispositivos de bloque. Opciones:

1. **Ejecutar con sudo** (pide contraseña cada vez).
2. **sudoers NOPASSWD solo para smartctl** (recomendado para monitorización):

   ```bash
   sudo visudo -f /etc/sudoers.d/diskmon
   ```

   ```sudoers
   # Permite a tu usuario leer SMART sin contraseña (solo lectura)
   tu_usuario ALL=(root) NOPASSWD: /usr/sbin/smartctl -a -j *, /usr/sbin/smartctl -t * *, /usr/sbin/smartctl -l * *
   ```

   DiskMon detecta `sudo -n` automáticamente. Si no está disponible, avisa y
   muestra los discos con salud "Desconocido".

3. Ejecutar el monitor como root (por ejemplo, un servicio systemd de sistema).

`use_sudo` en la configuración acepta `auto` (por defecto), `always` o `never`.

## Uso

```bash
diskmon                       # equivale a: diskmon scan
diskmon scan                  # análisis único
diskmon scan --json           # salida JSON
diskmon scan --device sdb     # solo un disco
diskmon scan -v               # incluye avisos informativos
diskmon watch --interval 300  # monitorización continua (5 min)
diskmon history --device sda --limit 20
diskmon serve                 # dashboard en http://127.0.0.1:8765
diskmon selftest --device sdb --kind short
diskmon config                # configuración efectiva en JSON
diskmon doctor                # comprueba requisitos del entorno
```

### Códigos de salida (`scan`/`watch`)

| Código | Significado |
|--------|-------------|
| 0 | Sin problemas según `--fail-on` |
| 1 | Hay avisos (o el disco baja de la puntuación esperada) |
| 2 | Hay un problema crítico, o falló la recolección de discos |

`--fail-on {none,warning,critical}` (por defecto `warning`) controla el nivel
que provoca fallo. Ejemplo para cron: `diskmon scan --fail-on critical`.

### JSON

```json
{
  "schema": "diskmon/1",
  "hostname": "mi-equipo",
  "started_at": "2026-01-01T00:00:00+00:00",
  "worst_alert": "ok",
  "summary": {"disks": 2, "ok": 2, "warning": 0, "critical": 0, "unknown": 0},
  "disks": [
    {
      "device": "sda",
      "kind": "SSD",
      "score": 100,
      "grade": "Excelente",
      "verdict": "SANA",
      "alert_level": "ok",
      "metrics": {"temperature_c": 35, "power_on_hours": 1000, "wear_percent": 5},
      "issues": []
    }
  ],
  "errors": []
}
```

## Puntuación de salud

Se parte de 100 puntos y se restan penalizaciones por cada hallazgo. La nota se
calcula sobre la puntuación, con topes de coherencia: un fallo crítico impide
mostrar "Excelente" aunque la puntuación sea alta.

| Nota | Puntos | Veredicto |
|------|--------|-----------|
| Excelente | 90–100 | SANA |
| Buena | 75–89 | SANA (VIGILAR si hay avisos) |
| Precaución | 55–74 | VIGILAR / EN RIESGO |
| Degradada | 35–54 | EN RIESGO / FALLANDO |
| Crítica | 0–34 | FALLANDO |

Ejemplos de penalizaciones: SMART fallido (−60), sectores pendientes (−30),
reasignados graves (−35), desgaste ≥95 % (−30), errores de medio NVMe (−40),
temperatura crítica (−20), errores CRC (−4 a −15, suele ser cable/puerto).

Los avisos de **capacidad** de las particiones (≥90 % aviso, ≥95 % crítico) se
muestran y marcan el estado como VIGILAR, pero **no restan puntos de salud del
disco**: son un problema de espacio, no del hardware.

## Configuración

Copia `config.example.toml` a `~/.config/diskmon/config.toml` y ajusta:

```toml
db_path = "~/.local/share/diskmon/history.db"
use_sudo = "auto"          # auto | always | never
include_empty = false       # lectores de tarjetas sin medio
exclude = ["sdz"]           # discos a ignorar
fail_on = "warning"         # none | warning | critical
save_history = true
web_port = 8765

[thresholds]
temp_warn_hdd = 50
temp_crit_hdd = 58
temp_warn_ssd = 65
temp_crit_ssd = 75
temp_warn_nvme = 70
temp_crit_nvme = 80
hdd_hours_warn = 40000
hdd_hours_crit = 60000
realloc_warn = 1
realloc_crit = 10
wear_warn = 80
wear_crit = 95
fs_warn = 90
fs_crit = 95
```

También puedes usar `--config RUTA` o la variable `DISKMON_CONFIG`.

## Histórico y dashboard

Cada `scan` guarda por defecto una entrada en SQLite (desactívalo con
`--no-save`). El dashboard muestra tarjetas por disco, incidencias y una gráfica
de evolución de la puntuación:

```bash
diskmon serve --host 127.0.0.1 --port 8765
```

Rutas de la API: `/api/scan`, `/api/history?device=sda`, `/api/devices`,
`/api/health`. El dashboard escucha solo en localhost por defecto; no lo expongas
a Internet sin poner un proxy con autenticación.

## Monitorización periódica con systemd

```bash
make install-systemd
systemctl --user enable --now diskmon.timer
systemctl --user list-timers diskmon.timer
journalctl --user -u diskmon.service -n 50
```

`make install-systemd` instala el comando y copia las unidades en
`~/.config/systemd/user/`, pero no activa nada automáticamente. También puedes
copiarlas a mano:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/diskmon.service systemd/diskmon.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now diskmon.timer
```

El timer analiza cada 6 horas y guarda el histórico. El servicio web opcional:

```bash
cp systemd/diskmon-web.service ~/.config/systemd/user/
systemctl --user enable --now diskmon-web.service
```

## Alcance soportado

DiskMon está pensado para **Linux nativo con systemd**. Quedan fuera de alcance
Windows, WSL, macOS y distribuciones anteriores a las indicadas.

| Distribución | Versión mínima | Entorno de referencia |
|---|---|---|
| Debian | 11 (bullseye) | Python 3.9, smartctl 7.2, util-linux 2.36 |
| Ubuntu | 22.04 LTS | Python 3.10, smartctl 7.2, util-linux 2.37 |
| Linux Mint | 21 | Basada en Ubuntu 22.04 |
| Probado | Mint 22.x / Ubuntu 24.x | Python 3.11+, smartctl 7.x, util-linux 2.3x |

Requisitos funcionales:

- **Python ≥ 3.9**. En 3.9/3.10 se usa `tomli` para leer TOML (dependencia
  declarada con pip/pipx, o `python3-tomli` en Debian/Ubuntu). En 3.11+ se usa
  `tomllib` y no hay dependencias externas.
- **smartmontools ≥ 7.2** con salida JSON (`smartctl -j`).
- **util-linux ≥ 2.36** con `lsblk -J`. Debian 11 no tiene la columna
  `MOUNTPOINTS`, por lo que se usa `MOUNTPOINT` como alternativa.
- **systemd** para el timer y el servicio del dashboard.
- Permisos para SMART: root, `sudo -n` o reglas sudoers/udev equivalentes.

No se garantiza soporte en otras distribuciones, aunque la CLI debería funcionar
en cualquier Linux moderno con esas herramientas. En máquinas virtuales,
contenedores o RAID por hardware puede no haber SMART accesible; en ese caso se
muestra "Desconocido" y el uso de sistemas de ficheros sí se sigue midiendo.

## Limitaciones

- SMART puede no estar disponible tras algunos puentes USB/SATA; en ese caso la
  salud aparece como "Desconocido" (no se inventa una puntuación).
- Los atributos SMART son específicos de cada fabricante. DiskMon usa los
  identificadores y nombres estándar; los atributos desconocidos se conservan en
  el JSON pero no se interpretan.
- Los discos virtuales, RAID por hardware y algunos NVMe con controladoras
  propietarias pueden requerir opciones adicionales de `smartctl`.
- La estimación de desgaste de SSD es aproximada y depende de lo que exponga el
  firmware.
- Ante cualquier aviso crítico, **haz copia de seguridad antes de sustituir**.

## Desarrollo

```bash
python3 -m pytest              # tests
python3 -m pytest -v           # detallado
pyflakes diskmon tests         # análisis estático
./bin/diskmon doctor           # comprobar entorno
./bin/diskmon scan --no-save   # prueba real
```

Estructura:

```
diskmon/
  collect/blockdev.py   lsblk y uso de sistemas de ficheros
  collect/smart.py      smartctl, sudo, parser ATA/NVMe
  analysis.py           reglas y puntuación de salud
  doctor.py             comprobación de requisitos del entorno
  history.py            SQLite
  report.py             salida de texto/JSON
  web.py                dashboard y API
  cli.py                argumentos y comandos
tests/                  pruebas con fixtures SMART reales
systemd/                unidades de usuario
bin/diskmon             lanzador sin instalación
config.example.toml     configuración de ejemplo
```

## Licencia

MIT. Consulta [LICENSE](LICENSE) para el texto completo.
