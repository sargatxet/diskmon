# TODO — trabajo pendiente

Estado: **v1.0.0 publicada**. Prioridades: **P1** antes de desplegar en más
equipos, **P2** siguiente iteración, **P3** mejoras opcionales.

## P1 — Validación y despliegue

- [ ] Probar `doctor`, `scan` y el timer en máquinas reales con **Debian 11**,
      **Ubuntu 22.04** y **Linux Mint 21** (Python 3.9/3.10 + `tomli`).
- [ ] Añadir CI con matriz Debian/Ubuntu/Mint (versiones mínimas y LTS
      actuales) y Python 3.9–3.13; ejecutar `pytest`, `pyflakes` y comprobación
      de sintaxis 3.9.
- [ ] Documentar y automatizar una regla `sudoers` mínima para `smartctl`
      (`-a -j`, `-t`, `-l`) y validarla en `doctor`.
- [ ] Añadir un instalador/`make` que detecte `python3-tomli` en Debian 11 y
      Ubuntu 22.04 y avise si falta.
- [ ] Verificar el comportamiento en discos NVMe reales (no solo sintéticos) y
      en discos USB con puente SAT.

## P2 — Operación y monitorización

- [ ] Notificaciones ante salud crítica: correo, webhook o `notify-send`.
- [ ] Retención y purga configurable del histórico (`history_days`), con
      comando `diskmon prune`.
- [ ] `selftest --wait`: lanzar un auto-test y esperar su finalización con
      timeout, actualizando la salud al terminar.
- [ ] Exportador Prometheus / endpoint de métricas para integrar con
      monitorización existente.
- [ ] Alertas por cambio de estado (sano → aviso → crítico) en `watch`.
- [ ] Añadir `--quiet` y formato de salida para integración con cron.
- [ ] Documentar backup/restauración del histórico SQLite.

## P2 — Cobertura de hardware

- [ ] Soporte de RAID por hardware mediante `smartctl -d megaraid,N` y
      detección de controladoras.
- [ ] Mejorar el emparejamiento SMART ↔ `lsblk` cuando el modelo/serie no está
      disponible en `lsblk`.
- [ ] Soportar múltiples namespaces NVMe y dispositivos `md`/`dm` con etiquetas
      claras.
- [ ] Refinar el uso de capacidad en btrfs/ZFS con subvolúmenes y cuotas.

## P3 — Producto y mantenimiento

- [ ] Internacionalización de la CLI/dashboard (español/inglés) y fallback ASCII
      para terminales sin UTF-8.
- [ ] Empaquetado `.deb` y publicación en un repositorio APT propio.
- [ ] Automatizar releases desde CI: wheel/sdist adjuntos, `SHA256SUMS` y notas
      generadas desde `CHANGELOG.md` (el tag y el archivo fuente ya se publican
      a mano en cada release).
- [ ] Añadir capturas y ejemplo real al README.
- [ ] Revisar periódicamente los umbrales SMART por familia de discos.
- [ ] Evaluar autenticación básica opcional para el dashboard si se expone más
      allá de localhost.

## Completado en v1.0.0

- [x] Detección de discos y particiones con `lsblk`.
- [x] Lectura SMART ATA/SATA/NVMe con `sudo -n` y reintentos.
- [x] Puntuación de salud, notas, veredictos e incidencias explicables.
- [x] Histórico SQLite y dashboard local.
- [x] CLI (`scan`, `watch`, `history`, `serve`, `selftest`, `config`, `doctor`).
- [x] Salida JSON y códigos de salida para automatización.
- [x] Configuración TOML y umbrales.
- [x] Unidades systemd de usuario.
- [x] 63 tests, fixtures SMART reales y licencia MIT.
- [x] Tag `v1.0.0` y release en GitHub con archivo fuente descargable, para
      instalar sin clonar el repositorio.
