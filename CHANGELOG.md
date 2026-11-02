# Changelog

Todos los cambios relevantes de este proyecto se documentan en este fichero.

El formato está basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el versionado sigue [Semantic Versioning](https://semver.org/lang/es/).

## [Unreleased]

### Added

- Nada todavía.

### Changed

- Nada todavía.

### Fixed

- Nada todavía.

## [1.0.0] - 2026-11-02

Primera versión estable de DiskMon, un monitor de salud de discos para Linux
nativo basado en SMART.

### Added

- Detección de discos físicos y particiones con `lsblk -J`; se excluyen por
  defecto dispositivos de 0 bytes y se soportan particiones anidadas
  (LUKS/LVM/RAID básico).
- Lectura SMART de discos ATA/SATA y NVMe mediante `smartctl -a -j`, con
  reintentos `-d sat`, `-d nvme` y variantes para puentes USB, y uso opcional de
  `sudo -n`.
- Motor de salud explicable con puntuación 0–100, nota
  (Excelente/Buena/Precaución/Degradada/Crítica) y veredicto
  (SANA/VIGILAR/EN RIESGO/FALLANDO).
- Reglas para sectores reasignados, pendientes y no corregibles, errores CRC,
  timeouts, reintentos de giro, temperatura, horas de uso, desgaste de
  SSD/NVMe, bloques de reserva, auto-tests y logs de error SMART.
- Avisos de capacidad de sistemas de ficheros sin penalizar la salud del
  hardware.
- Histórico SQLite con WAL y consulta por disco, serie o límite.
- CLI con subcomandos `scan`, `watch`, `history`, `serve`, `selftest`, `config`
  y `doctor`.
- Salida JSON estable (`diskmon/1`) y NDJSON para `watch`.
- Códigos de salida para cron/systemd (`0` correcto, `1` avisos, `2` crítico o
  error de recolección).
- Dashboard web local sin dependencias externas, con tarjetas por disco,
  incidencias y gráfica de evolución.
- Comando `doctor` para validar distro, Python, TOML, `lsblk`, `smartctl`,
  permisos SMART, systemd y ruta del histórico.
- Configuración TOML con umbrales ajustables; `tomllib` en Python ≥ 3.11 y
  `tomli` en Python 3.9/3.10.
- Unidades systemd de usuario para análisis periódico y dashboard.
- Soporte oficial de Debian 11+, Ubuntu 22.04+ y Linux Mint 21+; probado en
  Linux Mint 22.x / Ubuntu 24.x.
- Suite de 63 tests con fixtures SMART reales y casos sintéticos de fallo.
- Licencia MIT completa.
- Release `v1.0.0` en GitHub con archivo fuente descargable (`.tar.gz`/`.zip`):
  permite usar DiskMon sin clonar el repositorio; el proceso está documentado
  en el README.

### Security

- El dashboard escucha en `127.0.0.1` por defecto y no carga recursos externos.
- La integración con `sudo` usa `sudo -n` y la regla `sudoers` recomendada se
  limita a operaciones SMART de lectura y auto-tests.

### Known limitations

- Sin soporte para Windows, WSL, macOS ni versiones anteriores a las indicadas.
- Sin notificaciones, autenticación web ni soporte específico de RAID hardware.
- SMART puede no estar disponible en VMs, contenedores o algunos puentes USB.
