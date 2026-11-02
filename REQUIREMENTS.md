# REQUIREMENTS — DiskMon

| Campo | Valor |
|---|---|
| Producto | DiskMon — monitor de salud de discos |
| Versión documentada | 1.0.0 |
| Estado | Estable |
| Alcance | Linux nativo con systemd |
| Público | Administradores de sistemas y usuarios técnicos |

## 1. Propósito

DiskMon debe detectar los discos físicos de un equipo Linux, leer sus datos
SMART (ATA/SATA y NVMe), determinar su estado de salud de forma explicable,
guardar la evolución histórica y permitir la consulta mediante CLI, JSON y un
dashboard web local.

El sistema debe ser conservador: si no puede leer SMART, debe indicar
`Desconocido` en lugar de asumir que el disco está sano.

## 2. Alcance

### 2.1 Soportado

- Linux nativo con systemd.
- Debian 11 (bullseye) o superior.
- Ubuntu 22.04 LTS o superior.
- Linux Mint 21 o superior.
- Python ≥ 3.9.
- `util-linux` ≥ 2.36 con `lsblk -J`.
- `smartmontools` ≥ 7.2 con `smartctl -j`.
- Discos ATA/SATA, NVMe, USB con puente SMART y particiones LUKS/LVM/RAID
  básicas visibles por `lsblk`.

### 2.2 Fuera de alcance

- Windows, WSL y macOS.
- Distribuciones anteriores a las mínimas indicadas.
- Notificaciones push/email/webhook.
- Autenticación del dashboard.
- RAID por hardware con controladoras propietarias.
- Monitorización remota multi-host.
- Retención/purga automática del histórico (ver `TODO.md`).

## 3. Requisitos funcionales

### FR-01 — Descubrimiento de discos

El sistema debe enumerar discos físicos con `lsblk` y obtener nombre, ruta,
modelo, serie, tamaño, rotación, transporte y particiones. Debe excluir por
defecto dispositivos de 0 bytes (lectores sin medio) y entradas que no son discos
(por ejemplo, unidades DVD/rom).
Debe permitir incluir dispositivos vacíos mediante configuración.

**Aceptación:** `diskmon scan` muestra los discos del equipo; `lsblk.json` de
los fixtures produce `sda` y `sdb`, excluyendo lectores de 0 B y el DVD.

### FR-02 — Lectura SMART

El sistema debe leer SMART con `smartctl -a -j`, soportando ATA/SATA y NVMe.
Debe reintentar con `-d nvme` para NVMe y con `-d sat`/variantes USB cuando sea
necesario. Debe usar `sudo -n` si está disponible, sin solicitar contraseña de
forma interactiva, y reportar un error claro si no hay permisos.

**Aceptación:** en un equipo con `sudo -n` funciona sin intervención; sin
permisos, la salud es `Desconocido` y el mensaje explica cómo configurarlo.

### FR-03 — Puntuación de salud

El sistema debe calcular una puntuación de 0 a 100 a partir de penalizaciones
explicables y asignar una nota:

| Puntuación | Nota |
|---|---|
| 90–100 | Excelente |
| 75–89 | Buena |
| 55–74 | Precaución |
| 35–54 | Degradada |
| 0–34 | Crítica |

El veredicto debe ser `SANA`, `VIGILAR`, `EN RIESGO` o `FALLANDO`. Un fallo
crítico no debe mostrar `Excelente` aunque la puntuación sea alta.

**Aceptación:** los tests de `grade_for`, `_verdict_for` y los casos sintéticos de
fallo verifican la tabla y los topes de coherencia.

### FR-04 — Incidencias explicables

Cada penalización debe generar una incidencia con severidad
(`critical`/`warning`/`info`), código estable, mensaje, penalización y categoría.
Debe cubrir, como mínimo: estado SMART, sectores reasignados/pendientes/no
corregibles, errores CRC y timeouts, reintentos de giro, eventos de reasignación,
temperatura, horas de uso, desgaste, reserva, auto-tests y logs de error.

**Aceptación:** `diskmon scan -v` muestra las incidencias y el JSON incluye
`issues` con esos campos.

### FR-05 — Capacidad de sistemas de ficheros

El sistema debe calcular el uso de las particiones montadas con `statvfs` y
avisar a partir del 90 % (aviso) y 95 % (crítico), sin restar puntos de salud
del hardware.

**Aceptación:** una partición al 96 % genera `filesystem_full`, mantiene la
puntuación del disco y marca el estado global como aviso.

### FR-06 — Histórico

El sistema debe guardar por defecto cada análisis en SQLite (`WAL`) con fecha,
equipo, disco, serie, modelo, tipo, puntuación, nota, veredicto, temperatura,
horas, desgaste, incidencias y métricas. Debe poder desactivarse con `--no-save`
y consultarse por disco, serie y límite.

**Aceptación:** `diskmon history --device sda` y `/api/history?device=sda`
devuelven los registros más recientes primero.

### FR-07 — Dashboard web

El sistema debe ofrecer un dashboard local sin dependencias ni CDN, con resumen
por disco, incidencias, métricas y gráfica de evolución. Debe exponer una API
JSON y escuchar en `127.0.0.1` por defecto.

**Aceptación:** `diskmon serve` responde en `/`, `/api/scan`, `/api/history`,
`/api/devices` y `/api/health`; un 404 devuelve JSON.

### FR-08 — CLI

El sistema debe ofrecer los subcomandos `scan`, `watch`, `history`, `serve`,
`selftest`, `config` y `doctor`, con ayuda y opciones coherentes. Sin subcomando,
debe ejecutarse `scan`.

**Aceptación:** `diskmon version`, `diskmon --help` y los tests de CLI pasan.

### FR-09 — Salida JSON

El sistema debe emitir JSON estable con esquema `diskmon/1` para `scan` y
`doctor` con esquema `diskmon-doctor/1`. `watch --json` debe emitir NDJSON (una
línea por pasada) sin texto adicional.

**Aceptación:** el JSON del README valida y los tests comprueban claves y tipos.

### FR-10 — Códigos de salida

- `0`: sin problemas según `--fail-on`.
- `1`: hay avisos, o salud desconocida con `--fail-on warning`.
- `2`: hay un problema crítico o falló la recolección de discos.

`doctor` usa `0` (compatible), `1` (avisos) y `2` (requisitos incumplidos).

**Aceptación:** los tests de CLI cubren `warning`, `critical` y `unknown`.

### FR-11 — Auto-test SMART

El sistema debe poder lanzar auto-tests `short`, `long`, `conveyance` y
`offline` sobre un dispositivo concreto e indicar cómo consultar el progreso.

**Aceptación:** `diskmon selftest --device sdb --kind short` valida el
dispositivo y ejecuta `smartctl -t`; un dispositivo inexistente devuelve `2`.

### FR-12 — Comprobación de entorno

El sistema debe validar distro y versión, Python, parser TOML, `lsblk`,
`smartctl`, acceso SMART, detección y lectura de discos, systemd y ruta del
histórico, con estados `OK`/`AVISO`/`FALLO`.

**Aceptación:** `diskmon doctor` devuelve `0` en el entorno probado y detecta
versiones mínimas y herramientas ausentes en tests.

### FR-13 — Configuración

El sistema debe cargar configuración TOML desde `~/.config/diskmon/config.toml`,
`DISKMON_CONFIG` o `--config`, con valores por defecto si no existe. Debe
permitir ajustar rutas, sudo, exclusiones, umbrales, dashboard y política de
guardado.

**Aceptación:** los tests de configuración cubren valores por defecto, TOML,
claves desconocidas y exclusiones.

### FR-14 — Integración con systemd

El repositorio debe incluir un servicio `oneshot`, un timer periódico y un
servicio opcional para el dashboard, instalables como unidades de usuario.

**Aceptación:** `make install-systemd` copia las unidades y `systemctl --user`
las reconoce; el timer ejecuta `diskmon scan`.

## 4. Requisitos no funcionales

### NFR-01 — Portabilidad dentro del alcance

Debe funcionar en Debian 11+, Ubuntu 22.04+ y Mint 21+ sin compilación. En
Python 3.9/3.10 puede requerir `tomli` solo para TOML; en 3.11+ no debe tener
dependencias externas.

### NFR-02 — Seguridad

- No debe ejecutar `sudo` interactivo en modo automático.
- El dashboard debe escuchar en localhost por defecto y no cargar recursos
  externos.
- No debe modificar discos salvo la orden explícita `selftest`.
- No debe almacenar secretos ni contenido de los discos.

### NFR-03 — Robustez

Un fallo de SMART, `lsblk`, permisos o SQLite no debe provocar un traceback
visible: debe degradar a salud `Desconocido` o a un mensaje de error claro y
código de salida adecuado.

### NFR-04 — Rendimiento

Un análisis típico debe completarse en segundos (depende de `smartctl`). El
dashboard debe cachear el último escaneo (`web_cache_seconds`, 30 s por defecto)
para no golpear los discos en cada refresco.

### NFR-05 — Concurrencia

El histórico debe usar SQLite en modo WAL y soportar lecturas del dashboard
mientras el timer escribe.

### NFR-06 — Mantenibilidad

Código modular, tipado, con dataclasses y tests. Las reglas de salud deben ser
explicables y configurables; no se permiten umbrales mágicos sin documentar.

### NFR-07 — Usabilidad

Mensajes en español, salida legible con color opcional, tabla resumen, detalle
por disco y recomendaciones ante problemas.

### NFR-08 — Compatibilidad de sintaxis

El código debe poder parsearse con Python 3.9 (comprobado en CI local con
`ast.parse(feature_version=(3, 9))`).

### NFR-09 — Observabilidad

La CLI debe devolver códigos de salida útiles y mensajes a `stderr` para errores,
manteniendo `stdout` limpio cuando se usa `--json`.

### NFR-10 — Documentación

Debe existir documentación de usuario (`README`), requisitos, cambios, trabajo
pendiente y guía para agentes (`AGENTS`), actualizada con cada release.

## 5. Dependencias externas

| Dependencia | Mínimo | Uso | Obligatoria |
|---|---|---|---|
| Linux | — | `/dev`, `statvfs`, systemd | Sí |
| Python | 3.9 | Runtime | Sí |
| util-linux | 2.36 | `lsblk -J` | Sí |
| smartmontools | 7.2 | `smartctl -j` | Sí |
| systemd | — | Timer/dashboard | Para integración systemd |
| tomli | 2.0 | TOML en Python < 3.11 | Solo < 3.11 |
| pytest | 8 | Tests | Solo desarrollo |
| pyflakes | — | Análisis estático | Solo desarrollo |

## 6. Datos y almacenamiento

- Ruta por defecto: `~/.local/share/diskmon/history.db`.
- Tablas: `scans` y `disk_reports`, con índices por dispositivo/serie y fecha.
- Se guarda el informe completo en JSON además de columnas consultables.
- No se guarda contenido de ficheros ni rutas de usuario más allá del punto de
  montaje.
- La retención automática aún no está implementada; el crecimiento es bajo
  (unas pocas filas por disco y análisis).

## 7. Criterios de aceptación globales

1. `python3 -m pytest -q` pasa toda la suite.
2. `pyflakes diskmon tests` no reporta problemas.
3. `python3 -m compileall -q diskmon tests` termina correctamente.
4. `./bin/diskmon doctor` devuelve `0` en Mint 22.x / Ubuntu 24.x con
   `smartmontools` y `sudo -n`.
5. `./bin/diskmon scan --no-save` analiza los discos reales sin errores.
6. `./bin/diskmon serve` sirve el dashboard y la API en localhost.
7. La instalación (`make install`, `pipx install .` o wheel) expone `diskmon`.
8. El repositorio no contiene artefactos (`__pycache__`, `*.egg-info`, `*.db`).

## 8. Supuestos

- El usuario tiene permisos para instalar paquetes o usar `sudo`.
- El firmware del disco expone atributos SMART estándar o identificables.
- La máquina no está en un contenedor sin acceso a `/dev` ni en una VM sin
  SMART; en esos casos el comportamiento esperado es `Desconocido`.
- La fecha y zona horaria del sistema son correctas para el histórico.
