"""Carga de configuración de diskmon (TOML opcional).

Orden de precedencia: valores por defecto < fichero de configuración < CLI.
Si no existe fichero de configuración se usan los valores por defecto.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Optional

try:  # Python >= 3.11
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9/3.10
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]


DEFAULT_CONFIG_PATH = "~/.config/diskmon/config.toml"
DEFAULT_DB_PATH = "~/.local/share/diskmon/history.db"


@dataclass
class Thresholds:
    """Umbrales del motor de análisis. Todos son configurables."""

    # Temperatura (ºC)
    temp_warn_hdd: float = 50.0
    temp_crit_hdd: float = 58.0
    temp_warn_ssd: float = 65.0
    temp_crit_ssd: float = 75.0
    temp_warn_nvme: float = 70.0
    temp_crit_nvme: float = 80.0

    # Horas de encendido
    hdd_hours_warn: int = 40_000
    hdd_hours_crit: int = 60_000
    ssd_hours_warn: int = 50_000

    # Sectores
    realloc_warn: int = 1
    realloc_crit: int = 10
    pending_crit: int = 1
    offline_uncorrectable_crit: int = 1

    # Desgaste de SSD/NVMe (% de vida consumida)
    wear_warn: int = 80
    wear_crit: int = 95

    # Bloques de reserva disponibles (%)
    spare_warn: int = 20

    # Uso de sistemas de ficheros (%)
    fs_warn: float = 90.0
    fs_crit: float = 95.0

    def for_kind(self, kind: str) -> tuple[float, float]:
        """Devuelve (aviso, crítico) de temperatura para el tipo de disco."""
        if kind == "NVMe":
            return self.temp_warn_nvme, self.temp_crit_nvme
        if kind == "HDD":
            return self.temp_warn_hdd, self.temp_crit_hdd
        return self.temp_warn_ssd, self.temp_crit_ssd

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Thresholds":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Config:
    """Configuración global de diskmon."""

    db_path: str = DEFAULT_DB_PATH
    smartctl: str = "smartctl"
    use_sudo: str = "auto"  # auto | always | never
    include_empty: bool = False
    exclude: list[str] = field(default_factory=list)
    alert_score: int = 75
    fail_on: str = "warning"  # none | warning | critical
    save_history: bool = True
    history_limit: int = 100
    web_host: str = "127.0.0.1"
    web_port: int = 8765
    web_cache_seconds: int = 30
    thresholds: Thresholds = field(default_factory=Thresholds)

    @property
    def db_file(self) -> Path:
        return Path(os.path.expanduser(self.db_path))

    def is_excluded(self, disk_name: str, path: str, serial: str = "") -> bool:
        tokens = {disk_name, path, serial, os.path.basename(path)}
        return any(pattern in tokens for pattern in self.exclude)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        cfg = cls()
        for f in fields(cls):
            if f.name == "thresholds":
                continue
            if f.name in data:
                setattr(cfg, f.name, data[f.name])
        if isinstance(data.get("thresholds"), dict):
            cfg.thresholds = Thresholds.from_dict(data["thresholds"])
        return cfg


def load_config(path: Optional[str] = None) -> Config:
    """Carga la configuración desde TOML.

    ``path`` puede ser una ruta explícita (--config), la variable de entorno
    ``DISKMON_CONFIG`` o la ruta por defecto. Si el fichero no existe se
    devuelve la configuración por defecto sin error.
    """
    candidate = path or os.environ.get("DISKMON_CONFIG") or DEFAULT_CONFIG_PATH
    cfg_path = Path(os.path.expanduser(candidate))
    if not cfg_path.is_file():
        return Config()
    if tomllib is None:  # pragma: no cover
        raise RuntimeError(
            "Para leer configuración TOML se requiere Python 3.11+ o el paquete 'tomli' "
            "(en Debian/Ubuntu: sudo apt install python3-tomli)"
        )
    with cfg_path.open("rb") as fh:
        data = tomllib.load(fh)
    return Config.from_dict(data)
