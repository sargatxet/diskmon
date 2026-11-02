"""Descubrimiento de discos y particiones usando ``lsblk``."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Optional

from ..models import DiskInfo, Partition

LSBLK_COLUMNS = "NAME,PATH,TYPE,SIZE,ROTA,TRAN,MODEL,SERIAL,FSTYPE,MOUNTPOINTS,PTTYPE"
LSBLK_COLUMNS_LEGACY = "NAME,PATH,TYPE,SIZE,ROTA,TRAN,MODEL,SERIAL,FSTYPE,MOUNTPOINT,PTTYPE"


class CollectorError(RuntimeError):
    """Error al ejecutar una herramienta del sistema."""


def _run_lsblk() -> dict[str, Any]:
    if shutil.which("lsblk") is None:
        raise CollectorError("No se encontró 'lsblk'. Instala util-linux.")
    last_error = ""
    for columns in (LSBLK_COLUMNS, LSBLK_COLUMNS_LEGACY):
        cmd = ["lsblk", "-J", "-b", "-o", columns]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if proc.returncode == 0:
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError as exc:
                last_error = f"JSON inválido de lsblk: {exc}"
                continue
        last_error = (proc.stderr or proc.stdout).strip()
    raise CollectorError(f"lsblk falló: {last_error}")


def _mountpoint(node: dict[str, Any]) -> Optional[str]:
    mps = node.get("mountpoints")
    if isinstance(mps, list):
        for mp in mps:
            if mp:
                return str(mp)
    mp = node.get("mountpoint")
    return str(mp) if mp else None


def _usage(mountpoint: Optional[str]) -> tuple[Optional[int], Optional[int], Optional[float]]:
    """Uso real del sistema de ficheros montado (sin depender de psutil)."""
    if not mountpoint:
        return None, None, None
    try:
        st = os.statvfs(mountpoint)
    except OSError:
        return None, None, None
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    used = total - st.f_bfree * st.f_frsize
    # df calcula el porcentaje sobre el espacio visible (usado + disponible).
    denom = used + free
    percent = (used / denom * 100.0) if denom else 0.0
    return used, free, percent


def _partitions(node: dict[str, Any]) -> list[Partition]:
    result: list[Partition] = []
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        fstype = child.get("fstype")
        mp = _mountpoint(child)
        if fstype or mp:
            used, free, percent = _usage(mp)
            result.append(
                Partition(
                    name=str(child.get("name", "")),
                    path=str(child.get("path") or f"/dev/{child.get('name', '')}"),
                    size_bytes=int(child.get("size") or 0),
                    fstype=fstype,
                    mountpoint=mp,
                    used_bytes=used,
                    free_bytes=free,
                    use_percent=percent,
                )
            )
        # Soporta LUKS/LVM/RAID anidados.
        result.extend(_partitions(child))
    return result


def parse_lsblk(data: dict[str, Any], include_empty: bool = False) -> list[DiskInfo]:
    """Convierte la salida JSON de lsblk en ``DiskInfo`` (sin SMART)."""
    disks: list[DiskInfo] = []
    for node in data.get("blockdevices") or []:
        if node.get("type") != "disk":
            continue
        size = int(node.get("size") or 0)
        if size <= 0 and not include_empty:
            # Lectores de tarjetas / dispositivos sin medio insertado.
            continue
        name = str(node.get("name", ""))
        disks.append(
            DiskInfo(
                name=name,
                path=str(node.get("path") or f"/dev/{name}"),
                model=str(node.get("model") or "").strip(),
                serial=str(node.get("serial") or "").strip(),
                size_bytes=size,
                rotational=node.get("rota"),
                transport=node.get("tran"),
                partitions=_partitions(node),
            )
        )
    return disks


def collect_disks(include_empty: bool = False) -> list[DiskInfo]:
    """Detecta los discos físicos del sistema."""
    return parse_lsblk(_run_lsblk(), include_empty=include_empty)
