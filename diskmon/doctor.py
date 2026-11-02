"""Comprobación del entorno para saber si DiskMon puede funcionar.

``diskmon doctor`` valida sistema operativo, Python, utilidades del sistema,
permisos SMART, systemd y la base de datos. No guarda histórico ni modifica
discos: solo lee versiones y, como mucho, SMART del primer disco.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import __version__
from .collect import collect_disks
from .collect.smart import SmartInfo, collect_smart, sudo_available
from .config import Config
from .report import Painter, pad

MIN_PYTHON = (3, 9)
MIN_UTIL_LINUX = (2, 36)  # Debian 11; MOUNTPOINTS requiere 2.37
MIN_SMARTCTL = (7, 2)  # Debian 11 / Ubuntu 22.04 / Mint 21

STATUS_LABEL = {"ok": "OK", "warn": "AVISO", "fail": "FALLO"}
STATUS_ORDER = {"fail": 0, "warn": 1, "ok": 2}
STATUS_COLOR = {"ok": "green", "warn": "yellow", "fail": "red"}


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail
    detail: str
    hint: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "hint": self.hint,
        }


def _run(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _parse_version(text: str) -> Optional[tuple[int, int]]:
    match = re.search(r"(\d+)\.(\d+)", text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


#: Versiones mínimas soportadas oficialmente.
MIN_DISTROS = {
    "debian": (11, 0),
    "ubuntu": (22, 4),
    "linuxmint": (21, 0),
}


def _os_release() -> dict[str, str]:
    release = Path("/etc/os-release")
    info: dict[str, str] = {}
    if release.is_file():
        for line in release.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                info[key.strip()] = value.strip().strip('"')
    return info


def _version_tuple(text: str, width: int = 2) -> tuple[int, ...]:
    parts = [int(p) for p in re.findall(r"\d+", text)[:width]]
    return tuple(parts + [0] * (width - len(parts)))


def _check_os() -> Check:
    if not sys.platform.startswith("linux"):
        return Check(
            "Sistema operativo",
            "fail",
            f"{platform.system()} no soportado",
            "DiskMon solo funciona en Linux nativo.",
        )
    info = _os_release()
    pretty = info.get("PRETTY_NAME") or platform.platform()
    if "microsoft" in platform.release().lower():
        return Check(
            "Sistema operativo",
            "warn",
            f"{pretty} (WSL detectado, fuera de alcance)",
            "DiskMon está pensado para Linux nativo; en WSL SMART suele no estar disponible.",
        )
    distro = info.get("ID", "").lower()
    version_id = info.get("VERSION_ID", "")
    if not version_id:
        return Check(
            "Sistema operativo",
            "warn",
            f"{pretty} (versión no determinada)",
            "Soporte oficial: Debian ≥ 11, Ubuntu ≥ 22.04, Linux Mint ≥ 21.",
        )
    version = _version_tuple(version_id)
    minimum = MIN_DISTROS.get(distro)
    if minimum is None:
        return Check(
            "Sistema operativo",
            "warn",
            f"{pretty} (distribución no verificada)",
            "Soporte oficial: Debian ≥ 11, Ubuntu ≥ 22.04, Linux Mint ≥ 21.",
        )
    if version < minimum:
        return Check(
            "Sistema operativo",
            "warn",
            f"{pretty} (anterior al mínimo soportado)",
            "Soporte oficial: Debian ≥ 11, Ubuntu ≥ 22.04, Linux Mint ≥ 21.",
        )
    return Check(
        "Sistema operativo",
        "ok",
        f"{pretty} (kernel {platform.release()})",
    )


def _check_python() -> Check:
    version = platform.python_version()
    if sys.version_info < MIN_PYTHON:
        return Check(
            "Python",
            "fail",
            f"{version} (se requiere >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})",
            "Actualiza Python o usa una versión más reciente de la distro.",
        )
    return Check("Python", "ok", f"{version} (mínimo {MIN_PYTHON[0]}.{MIN_PYTHON[1]})")


def _check_toml(config: Config) -> Check:
    from . import config as config_module

    parser = (
        getattr(config_module.tomllib, "__name__", "tomllib")
        if config_module.tomllib is not None
        else "no disponible"
    )
    config_path = Path(
        os.path.expanduser(
            os.environ.get("DISKMON_CONFIG") or "~/.config/diskmon/config.toml"
        )
    )
    if config_module.tomllib is None and config_path.is_file():
        return Check(
            "Configuración TOML",
            "fail",
            f"{config_path} existe pero no hay parser TOML",
            "Instala python3-tomli o usa Python 3.11+.",
        )
    if config_module.tomllib is None:
        return Check(
            "Configuración TOML",
            "warn",
            "sin parser TOML; se usarán valores por defecto",
            "Instala python3-tomli si quieres usar config.toml.",
        )
    return Check("Configuración TOML", "ok", f"{parser} disponible")


def _check_lsblk() -> Check:
    path = shutil.which("lsblk")
    if not path:
        return Check(
            "lsblk",
            "fail",
            "no encontrado",
            "Instala util-linux (sudo apt install util-linux).",
        )
    try:
        version_out = _run([path, "--version"]).stdout.strip()
        version = _parse_version(version_out)
        proc = _run([path, "-J", "-b", "-o", "NAME,TYPE,SIZE"])
        proc.check_returncode()
        import json

        data = json.loads(proc.stdout)
        disks = [
            d
            for d in data.get("blockdevices", [])
            if d.get("type") == "disk" and int(d.get("size") or 0) > 0
        ]
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return Check("lsblk", "fail", f"error: {exc}", "Comprueba util-linux.")
    detail = f"{version_out} · {len(disks)} discos detectados"
    if version and version < MIN_UTIL_LINUX:
        return Check(
            "lsblk",
            "warn",
            detail,
            f"Se recomienda util-linux >= {MIN_UTIL_LINUX[0]}.{MIN_UTIL_LINUX[1]}.",
        )
    return Check("lsblk", "ok", detail)


def _check_smartctl() -> Check:
    path = shutil.which("smartctl")
    if not path:
        return Check(
            "smartctl",
            "fail",
            "no encontrado",
            "Instala smartmontools (sudo apt install smartmontools).",
        )
    try:
        version_out = _run([path, "--version"]).stdout.splitlines()[0].strip()
        help_out = _run([path, "--help"]).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return Check("smartctl", "fail", f"error: {exc}", "Reinstala smartmontools.")
    version = _parse_version(version_out)
    supports_json = "-j" in help_out or "--json" in help_out
    if not supports_json:
        return Check(
            "smartctl",
            "fail",
            f"{version_out} sin soporte JSON",
            "Actualiza smartmontools a >= 7.0.",
        )
    if version and version < MIN_SMARTCTL:
        return Check(
            "smartctl",
            "warn",
            f"{version_out} (se recomienda >= {MIN_SMARTCTL[0]}.{MIN_SMARTCTL[1]})",
            "La salida JSON puede estar incompleta.",
        )
    return Check("smartctl", "ok", f"{version_out} · salida JSON disponible")


def _check_access() -> Check:
    if os.geteuid() == 0:
        return Check("Acceso SMART", "ok", "ejecutando como root")
    if sudo_available():
        return Check("Acceso SMART", "ok", "sudo -n disponible")
    return Check(
        "Acceso SMART",
        "warn",
        "ni root ni sudo -n",
        "Configura sudoers NOPASSWD para smartctl o ejecuta como root.",
    )


def _check_disks() -> Check:
    try:
        disks = collect_disks(include_empty=False)
    except Exception as exc:  # CollectorError y errores de lsblk
        return Check("Discos", "fail", str(exc), "Revisa el estado de lsblk.")
    if not disks:
        return Check("Discos", "warn", "no se detectaron discos analizables")
    names = ", ".join(d.name for d in disks)
    return Check("Discos", "ok", f"{len(disks)} discos: {names}")


def _check_smart_read(config: Config) -> Check:
    if not shutil.which("smartctl"):
        return Check("Lectura SMART", "warn", "omitida: falta smartctl")
    try:
        disks = collect_disks(include_empty=False)
    except Exception:
        return Check("Lectura SMART", "warn", "omitida: falló lsblk")
    if not disks:
        return Check("Lectura SMART", "warn", "omitida: no hay discos")
    disk = disks[0]
    last_info: Optional[SmartInfo] = None
    for candidate in disks[:3]:
        info = collect_smart(candidate, config)
        if info.available:
            temp = "—" if info.temperature_c is None else f"{info.temperature_c:.0f} ºC"
            return Check(
                "Lectura SMART",
                "ok",
                f"{candidate.name}: SMART {'superada' if info.smart_passed else 'no superada'} · {temp}",
            )
        last_info = info
    return Check(
        "Lectura SMART",
        "warn",
        f"{disk.name}: {last_info.error if last_info else 'sin datos'}",
        "Revisa permisos de SMART o el puente USB/SATA.",
    )


def _check_systemd() -> Check:
    path = shutil.which("systemctl")
    if not path:
        return Check(
            "systemd",
            "warn",
            "systemctl no encontrado",
            "La CLI funciona, pero las unidades de systemd no.",
        )
    try:
        proc = _run([path, "--user", "show-environment"])
    except (OSError, subprocess.SubprocessError) as exc:
        return Check("systemd", "warn", f"error: {exc}")
    if proc.returncode != 0:
        return Check(
            "systemd",
            "warn",
            "sesión de usuario systemd no disponible",
            "El timer de usuario necesita systemd --user.",
        )
    return Check("systemd", "ok", "systemd de usuario disponible")


def _check_database(config: Config) -> Check:
    parent = config.db_file.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return Check("Histórico", "fail", f"no se puede crear {parent}: {exc}")
    if not os.access(parent, os.W_OK):
        return Check(
            "Histórico",
            "fail",
            f"sin permiso de escritura en {parent}",
            "Ajusta db_path en config.toml.",
        )
    return Check("Histórico", "ok", str(config.db_file))


def run_checks(config: Optional[Config] = None) -> list[Check]:
    """Ejecuta todas las comprobaciones del entorno."""
    cfg = config or Config()
    return [
        _check_os(),
        _check_python(),
        _check_toml(cfg),
        _check_lsblk(),
        _check_smartctl(),
        _check_access(),
        _check_disks(),
        _check_smart_read(cfg),
        _check_systemd(),
        _check_database(cfg),
    ]


def exit_code(checks: list[Check]) -> int:
    if any(c.status == "fail" for c in checks):
        return 2
    if any(c.status == "warn" for c in checks):
        return 1
    return 0


def render(checks: list[Check], color: bool = False) -> str:
    paint = Painter(color)
    lines = [paint(f"DiskMon {__version__} — comprobación del entorno", "cyan", bold=True)]
    width = max(len(c.name) for c in checks) if checks else 10
    for check in sorted(checks, key=lambda c: STATUS_ORDER.get(c.status, 9)):
        label = STATUS_LABEL[check.status]
        prefix = paint(f"[{label}]", STATUS_COLOR[check.status], bold=True)
        lines.append(f"{pad(prefix, 16)} {check.name:<{width}}  {check.detail}")
        if check.hint and check.status != "ok":
            lines.append(" " * 18 + paint(f"→ {check.hint}", "dim"))
    code = exit_code(checks)
    if code == 0:
        lines.append("")
        lines.append(paint("Entorno compatible con DiskMon.", "green", bold=True))
    elif code == 1:
        lines.append("")
        lines.append(paint("Entorno funcional con avisos; revisa las sugerencias.", "yellow", bold=True))
    else:
        lines.append("")
        lines.append(paint("Hay requisitos que impiden un funcionamiento fiable.", "red", bold=True))
    return "\n".join(lines)


def json_output(checks: list[Check]) -> str:
    import json

    return json.dumps(
        {
            "schema": "diskmon-doctor/1",
            "version": __version__,
            "status": "fail" if exit_code(checks) == 2 else ("warn" if exit_code(checks) == 1 else "ok"),
            "checks": [c.to_dict() for c in checks],
        },
        ensure_ascii=False,
        indent=2,
    )


__all__ = ["Check", "run_checks", "render", "json_output", "exit_code"]
