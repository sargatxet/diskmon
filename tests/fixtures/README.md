# Fixtures SMART

Datos sintéticos basados en el esquema JSON de `smartctl -a -j`
(smartmontools 7.x) y `lsblk -J`. No contienen seriales, WWN, modelos,
firmware, fechas ni métricas de uso de equipos reales: los identificadores son
`TEST-*` y los contadores son ficticios.

- `smart_sata_ssd.json`: SSD SATA genérico de 1 TB.
- `smart_sata_hdd.json`: HDD SATA genérico de 500 GB con un evento de
  reasignación histórico.
- `lsblk.json`: inventario genérico con dos discos, dos lectores de tarjetas
  vacíos y una unidad DVD.

Los fixtures conservan el esquema y los nombres de atributos SMART para que los
tests validen el parser sin depender del hardware donde se ejecutan.
