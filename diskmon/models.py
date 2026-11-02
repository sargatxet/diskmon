"""Modelos de datos de diskmon.

Todas las estructuras son serializables a JSON mediante ``to_dict`` para que
puedan usarse desde la CLI, el dashboard web y el histórico SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def utcnow_iso() -> str:
    """Fecha/hora actual en ISO-8601 con zona horaria local."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class Partition:
    """Partición (o volumen) de un disco."""

    name: str
    path: str
    size_bytes: int = 0
    fstype: Optional[str] = None
    mountpoint: Optional[str] = None
    used_bytes: Optional[int] = None
    free_bytes: Optional[int] = None
    use_percent: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "fstype": self.fstype,
            "mountpoint": self.mountpoint,
            "used_bytes": self.used_bytes,
            "free_bytes": self.free_bytes,
            "use_percent": None if self.use_percent is None else round(self.use_percent, 1),
        }


@dataclass
class SmartAttribute:
    """Atributo SMART de un disco ATA/SATA."""

    id: int
    name: str
    value: Optional[int] = None
    worst: Optional[int] = None
    threshold: Optional[int] = None
    raw: Optional[int] = None
    raw_string: str = ""
    when_failed: str = ""

    @property
    def failed(self) -> bool:
        return bool(self.when_failed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "value": self.value,
            "worst": self.worst,
            "threshold": self.threshold,
            "raw": self.raw,
            "raw_string": self.raw_string,
            "when_failed": self.when_failed,
        }


@dataclass
class SelfTestEntry:
    """Entrada del registro de auto-tests SMART."""

    type: str = ""
    status: str = ""
    passed: Optional[bool] = None
    lifetime_hours: Optional[int] = None
    error_code: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "status": self.status,
            "passed": self.passed,
            "lifetime_hours": self.lifetime_hours,
            "error_code": self.error_code,
        }


@dataclass
class SmartInfo:
    """Datos SMART normalizados, independientes del protocolo (ATA/NVMe)."""

    available: bool = False
    error: Optional[str] = None
    protocol: Optional[str] = None
    smart_passed: Optional[bool] = None
    temperature_c: Optional[float] = None
    power_on_hours: Optional[int] = None
    power_cycles: Optional[int] = None
    error_log_count: int = 0
    self_tests: list[SelfTestEntry] = field(default_factory=list)
    attributes: dict[int, SmartAttribute] = field(default_factory=dict)
    nvme: dict[str, Any] = field(default_factory=dict)
    exit_status: int = 0
    #: Avisos devueltos por smartctl (p. ej. atributos desconocidos).
    messages: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ utils
    def attr(self, attr_id: int) -> Optional[SmartAttribute]:
        return self.attributes.get(attr_id)

    def raw(self, attr_id: int) -> Optional[int]:
        a = self.attributes.get(attr_id)
        return None if a is None else a.raw

    def value(self, attr_id: int) -> Optional[int]:
        a = self.attributes.get(attr_id)
        return None if a is None else a.value

    def attr_by_name(self, *names: str) -> Optional[SmartAttribute]:
        wanted = {n.lower() for n in names}
        for a in self.attributes.values():
            if a.name.lower() in wanted:
                return a
        return None

    @property
    def failed_self_tests(self) -> list[SelfTestEntry]:
        return [t for t in self.self_tests if t.passed is False]

    @property
    def last_self_test(self) -> Optional[SelfTestEntry]:
        return self.self_tests[0] if self.self_tests else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "error": self.error,
            "protocol": self.protocol,
            "smart_passed": self.smart_passed,
            "temperature_c": self.temperature_c,
            "power_on_hours": self.power_on_hours,
            "power_cycles": self.power_cycles,
            "error_log_count": self.error_log_count,
            "self_tests": [t.to_dict() for t in self.self_tests],
            "attributes": {str(k): v.to_dict() for k, v in sorted(self.attributes.items())},
            "nvme": dict(self.nvme),
            "exit_status": self.exit_status,
            "messages": list(self.messages),
        }


@dataclass
class DiskInfo:
    """Disco físico detectado en el sistema."""

    name: str
    path: str
    model: str = ""
    serial: str = ""
    size_bytes: int = 0
    rotational: Optional[bool] = None
    transport: Optional[str] = None
    partitions: list[Partition] = field(default_factory=list)
    smart: SmartInfo = field(default_factory=SmartInfo)

    @property
    def kind(self) -> str:
        if self.transport == "nvme" or self.name.startswith("nvme"):
            return "NVMe"
        if self.rotational is False:
            return "SSD"
        if self.rotational is True:
            return "HDD"
        return "Desconocido"

    @property
    def capacity_gb(self) -> float:
        return self.size_bytes / 1e9

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "model": self.model,
            "serial": self.serial,
            "size_bytes": self.size_bytes,
            "kind": self.kind,
            "transport": self.transport,
            "partitions": [p.to_dict() for p in self.partitions],
            "smart": self.smart.to_dict(),
        }


@dataclass
class HealthIssue:
    """Hallazgo del análisis de salud."""

    severity: str  # critical | warning | info
    code: str
    message: str
    penalty: int = 0
    category: str = "smart"  # smart | wear | temperature | capacity | availability

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "penalty": self.penalty,
            "category": self.category,
        }


@dataclass
class HealthReport:
    """Resultado del análisis de un disco."""

    disk: DiskInfo
    score: Optional[int] = None
    grade: str = "Desconocido"
    verdict: str = "DESCONOCIDO"
    alert_level: str = "unknown"  # ok | warning | critical | unknown
    issues: list[HealthIssue] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    scanned_at: str = field(default_factory=utcnow_iso)

    @property
    def critical_issues(self) -> list[HealthIssue]:
        return [i for i in self.issues if i.severity == "critical"]

    @property
    def warning_issues(self) -> list[HealthIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def has_problems(self) -> bool:
        return bool(self.critical_issues or self.warning_issues)

    def sorted_issues(self) -> list[HealthIssue]:
        return sorted(self.issues, key=lambda i: (SEVERITY_ORDER.get(i.severity, 9), i.code))

    def to_dict(self) -> dict[str, Any]:
        return {
            "device": self.disk.name,
            "path": self.disk.path,
            "model": self.disk.model,
            "serial": self.disk.serial,
            "kind": self.disk.kind,
            "size_bytes": self.disk.size_bytes,
            "capacity_gb": round(self.disk.capacity_gb, 1),
            "transport": self.disk.transport,
            "partitions": [p.to_dict() for p in self.disk.partitions],
            "score": self.score,
            "grade": self.grade,
            "verdict": self.verdict,
            "alert_level": self.alert_level,
            "issues": [i.to_dict() for i in self.sorted_issues()],
            "metrics": self.metrics,
            "smart_available": self.disk.smart.available,
            "scanned_at": self.scanned_at,
        }


@dataclass
class ScanResult:
    """Conjunto de informes de una pasada de monitorización."""

    reports: list[HealthReport] = field(default_factory=list)
    hostname: str = ""
    started_at: str = field(default_factory=utcnow_iso)
    errors: list[str] = field(default_factory=list)

    @property
    def worst_alert(self) -> str:
        levels = [r.alert_level for r in self.reports]
        if "critical" in levels:
            return "critical"
        if "warning" in levels:
            return "warning"
        if levels and all(level == "ok" for level in levels):
            return "ok"
        return "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "diskmon/1",
            "hostname": self.hostname,
            "started_at": self.started_at,
            "worst_alert": self.worst_alert,
            "summary": {
                "disks": len(self.reports),
                "ok": sum(1 for r in self.reports if r.alert_level == "ok"),
                "warning": sum(1 for r in self.reports if r.alert_level == "warning"),
                "critical": sum(1 for r in self.reports if r.alert_level == "critical"),
                "unknown": sum(1 for r in self.reports if r.alert_level == "unknown"),
            },
            "disks": [r.to_dict() for r in self.reports],
            "errors": list(self.errors),
        }
