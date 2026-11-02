"""DiskMon: monitor de salud de discos basado en SMART."""

__version__ = "1.0.0"

from .analysis import analyze_disk, analyze_scan  # noqa: F401
from .config import Config, load_config  # noqa: F401
from .models import DiskInfo, HealthReport, ScanResult  # noqa: F401

__all__ = [
    "__version__",
    "Config",
    "load_config",
    "DiskInfo",
    "HealthReport",
    "ScanResult",
    "analyze_disk",
    "analyze_scan",
]
