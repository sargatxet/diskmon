"""Orquestación de la recolección de datos de discos."""

from __future__ import annotations

import socket
from typing import Optional

from ..config import Config
from ..models import DiskInfo, ScanResult
from .blockdev import CollectorError, collect_disks
from .smart import collect_smart


def discover_disks(
    config: Optional[Config] = None, only: Optional[str] = None
) -> tuple[list[DiskInfo], list[str]]:
    """Detecta discos, aplica filtros y adjunta los datos SMART."""
    cfg = config or Config()
    errors: list[str] = []
    try:
        disks = collect_disks(include_empty=cfg.include_empty)
    except CollectorError as exc:
        return [], [str(exc)]

    selected: list[DiskInfo] = []
    for disk in disks:
        if cfg.is_excluded(disk.name, disk.path, disk.serial):
            continue
        if only and only not in {disk.name, disk.path}:
            continue
        disk.smart = collect_smart(disk, cfg)
        if disk.smart.error and not disk.smart.available:
            errors.append(f"{disk.name}: {disk.smart.error}")
        selected.append(disk)
    return selected, errors


def scan(config: Optional[Config] = None, only: Optional[str] = None) -> ScanResult:
    """Realiza una pasada completa de monitorización (sin análisis)."""
    cfg = config or Config()
    result = ScanResult(hostname=socket.gethostname())
    disks, errors = discover_disks(cfg, only=only)
    result.errors.extend(errors)
    # El análisis se aplica en diskmon.analysis.analyze_scan para mantener
    # separada la recolección de la lógica de salud.
    from ..analysis import analyze_disk  # import local: evita ciclo

    result.reports = [analyze_disk(disk, cfg.thresholds) for disk in disks]
    return result
