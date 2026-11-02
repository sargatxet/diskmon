"""Recolección de datos SMART mediante ``smartctl -j`` (ATA/SATA/NVMe).

El acceso a SMART requiere privilegios. diskmon intenta ``sudo -n`` cuando está
disponible (sin pedir contraseña) y, si no, ejecuta smartctl directamente para
poder informar de un error claro al usuario.
"""

from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
from typing import Any, Optional

from ..config import Config
from ..models import DiskInfo, SelfTestEntry, SmartAttribute, SmartInfo


class SmartError(RuntimeError):
    """Error irrecuperable al consultar SMART."""


@functools.lru_cache(maxsize=1)
def sudo_available() -> bool:
    """True si ``sudo -n true`` funciona sin pedir contraseña."""
    if os.geteuid() == 0:
        return True
    if shutil.which("sudo") is None:
        return False
    try:
        proc = subprocess.run(
            ["sudo", "-n", "true"], capture_output=True, text=True, timeout=10
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _sudo_prefix(config: Config) -> list[str]:
    if os.geteuid() == 0 or config.use_sudo == "never":
        return []
    if config.use_sudo == "always":
        return ["sudo", "-n"]
    if sudo_available():
        return ["sudo", "-n"]
    return []


def _device_variants(disk: DiskInfo) -> list[list[str]]:
    variants: list[list[str]] = []
    if disk.kind == "NVMe":
        variants.append(["-d", "nvme"])
    variants.append([])
    if disk.transport == "usb":
        variants.extend([["-d", "sat"], ["-d", "usbjmicron"], ["-d", "usbsunplus"]])
    seen: set[tuple[str, ...]] = set()
    unique = []
    for v in variants:
        key = tuple(v)
        if key not in seen:
            seen.add(key)
            unique.append(v)
    return unique


def _run(cmd: list[str], timeout: int = 45) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise SmartError(f"Ejecutable no encontrado: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SmartError(f"Tiempo de espera agotado ejecutando: {' '.join(cmd)}") from exc


def _messages(data: dict[str, Any]) -> list[str]:
    msgs = []
    for item in (data.get("smartctl") or {}).get("messages") or []:
        if isinstance(item, dict) and item.get("string"):
            msgs.append(str(item["string"]))
        elif isinstance(item, str):
            msgs.append(item)
    return msgs


def _parse_temperature(data: dict[str, Any], attrs: dict[int, SmartAttribute]) -> Optional[float]:
    temp = (data.get("temperature") or {}).get("current")
    if temp is None:
        for attr_id in (194, 190):  # Temperature_Celsius / Airflow_Temperature_Cel
            attr = attrs.get(attr_id)
            if attr is None:
                continue
            # Algunos fabricantes empaquetan mín/máx en el valor raw; el primer
            # número de raw_string es la temperatura actual ("30 (Min/Max 9/56)").
            match = re.search(r"-?\d+(?:\.\d+)?", attr.raw_string or "")
            if match:
                temp = match.group(0)
            elif attr.raw is not None:
                temp = attr.raw
            if temp is not None:
                break
    if temp is None:
        temp = (data.get("nvme_smart_health_information_log") or {}).get("temperature")
    if temp is None:
        return None
    try:
        value = float(temp)
    except (TypeError, ValueError):
        return None
    # Algunos smartctl antiguos devuelven Kelvin para NVMe.
    if value > 200:
        value -= 273.15
    return round(value, 1)


def _parse_attributes(data: dict[str, Any]) -> dict[int, SmartAttribute]:
    table = (data.get("ata_smart_attributes") or {}).get("table") or []
    attrs: dict[int, SmartAttribute] = {}
    for row in table:
        try:
            attr_id = int(row["id"])
        except (KeyError, TypeError, ValueError):
            continue
        raw = row.get("raw") or {}
        raw_value = raw.get("value")
        try:
            raw_int = int(raw_value) if raw_value is not None else None
        except (TypeError, ValueError):
            raw_int = None
        attrs[attr_id] = SmartAttribute(
            id=attr_id,
            name=str(row.get("name") or f"attr_{attr_id}"),
            value=row.get("value"),
            worst=row.get("worst"),
            threshold=row.get("thresh"),
            raw=raw_int,
            raw_string=str(raw.get("string") or ""),
            when_failed=str(row.get("when_failed") or ""),
        )
    return attrs


def _parse_self_tests(data: dict[str, Any]) -> list[SelfTestEntry]:
    rows: list[dict[str, Any]] = []
    ata = ((data.get("ata_smart_self_test_log") or {}).get("standard") or {}).get("table")
    if isinstance(ata, list):
        rows.extend(ata)
    nvme = (data.get("nvme_self_test_log") or {}).get("table")
    if isinstance(nvme, list):
        rows.extend(nvme)

    entries: list[SelfTestEntry] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        status_obj = row.get("status") if isinstance(row.get("status"), dict) else {}
        status_text = str(status_obj.get("string") or row.get("status") or "")
        passed = status_obj.get("passed")
        if passed is None:
            low = status_text.lower()
            if "completed without error" in low or "completed successfully" in low:
                passed = True
            elif "failed" in low or "failure" in low or "error" in low:
                passed = False
        type_obj = row.get("type")
        type_text = (
            str(type_obj.get("string"))
            if isinstance(type_obj, dict) and type_obj.get("string")
            else str(type_obj or row.get("test_type") or "")
        )
        entries.append(
            SelfTestEntry(
                type=type_text,
                status=status_text,
                passed=passed,
                lifetime_hours=row.get("lifetime_hours"),
                error_code=row.get("error_code"),
            )
        )
    return entries


def _parse_nvme(data: dict[str, Any]) -> dict[str, Any]:
    log = data.get("nvme_smart_health_information_log") or {}
    if not isinstance(log, dict):
        return {}
    result: dict[str, Any] = {}
    for key in (
        "critical_warning",
        "available_spare",
        "available_spare_threshold",
        "percentage_used",
        "media_errors",
        "num_err_log_entries",
        "unsafe_shutdowns",
        "power_cycles",
        "power_on_hours",
        "data_units_read",
        "data_units_written",
        "host_reads",
        "host_writes",
        "controller_busy_time",
        "warning_temp_time",
        "critical_comp_time",
    ):
        if key in log:
            result[key] = log[key]
    if "data_units_written" in result:
        # 1 unidad de datos NVMe = 512 000 bytes.
        result["tbw"] = round(result["data_units_written"] * 512_000 / 1e12, 1)
    if "data_units_read" in result:
        result["tbr"] = round(result["data_units_read"] * 512_000 / 1e12, 1)
    return result


def parse_smart_json(data: dict[str, Any]) -> SmartInfo:
    """Normaliza la salida JSON de smartctl a ``SmartInfo``."""
    attrs = _parse_attributes(data)
    nvme = _parse_nvme(data)
    support = data.get("smart_support") or {}
    smart_available = support.get("available")
    has_payload = bool(attrs or nvme or data.get("smart_status"))
    available = bool(has_payload and smart_available is not False)

    messages = _messages(data)
    error: Optional[str] = None
    if not available:
        error = "El dispositivo no soporta SMART"
        if smart_available is False and messages:
            error += f" ({messages[0]})"

    power_on_hours = (data.get("power_on_time") or {}).get("hours")
    if power_on_hours is None and 9 in attrs:
        power_on_hours = attrs[9].raw
    power_cycles = data.get("power_cycle_count")
    if power_cycles is None and 12 in attrs:
        power_cycles = attrs[12].raw

    error_log = (data.get("ata_smart_error_log") or {}).get("summary") or {}
    error_log_count = int(error_log.get("count") or 0)
    if not error_log_count:
        error_log_count = int(nvme.get("num_err_log_entries") or 0)

    self_tests = _parse_self_tests(data)
    if not self_tests:
        # Si el registro está vacío, smartctl aún informa del último estado.
        status = ((data.get("ata_smart_data") or {}).get("self_test") or {}).get("status") or {}
        if isinstance(status, dict) and (status.get("passed") is not None or status.get("string")):
            self_tests.append(
                SelfTestEntry(
                    type="",
                    status=str(status.get("string") or ""),
                    passed=status.get("passed"),
                )
            )

    return SmartInfo(
        available=available,
        error=error,
        protocol=(data.get("device") or {}).get("protocol"),
        smart_passed=(data.get("smart_status") or {}).get("passed"),
        temperature_c=_parse_temperature(data, attrs),
        power_on_hours=power_on_hours,
        power_cycles=power_cycles,
        error_log_count=error_log_count,
        self_tests=self_tests,
        attributes=attrs,
        nvme=nvme,
        exit_status=int((data.get("smartctl") or {}).get("exit_status") or 0),
        messages=messages,
    )


def _attempt_commands(disk: DiskInfo, config: Config) -> list[list[str]]:
    smartctl = shutil.which(config.smartctl) or config.smartctl
    prefixes: list[list[str]] = []
    prefix = _sudo_prefix(config)
    if prefix:
        prefixes.append(prefix)
    if config.use_sudo != "always":
        prefixes.append([])
    commands = []
    for variant in _device_variants(disk):
        for pre in prefixes:
            commands.append([*pre, smartctl, "-a", "-j", *variant, disk.path])
    return commands


def collect_smart(disk: DiskInfo, config: Optional[Config] = None) -> SmartInfo:
    """Consulta SMART de un disco, probando variantes de acceso."""
    cfg = config or Config()
    if shutil.which(cfg.smartctl) is None and not os.path.exists(cfg.smartctl):
        return SmartInfo(
            available=False,
            error="smartctl no está instalado (sudo apt install smartmontools)",
        )

    errors: list[str] = []
    for cmd in _attempt_commands(disk, cfg):
        try:
            proc = _run(cmd)
        except SmartError as exc:
            errors.append(str(exc))
            continue
        stdout = proc.stdout.strip()
        if not stdout:
            detail = (proc.stderr or "").strip()
            if detail:
                errors.append(detail.splitlines()[-1])
            continue
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            errors.append((proc.stderr or "salida JSON inválida").strip().splitlines()[-1])
            continue
        if not isinstance(data, dict) or not (
            data.get("device") or data.get("model_name") or data.get("smart_status")
        ):
            detail = " | ".join(_messages(data)) or (proc.stderr or "").strip()
            if detail:
                errors.append(detail.splitlines()[-1])
            continue
        info = parse_smart_json(data)
        if not info.available:
            info.error = info.error or "SMART no disponible"
        return info

    unique_errors = list(dict.fromkeys(e for e in errors if e))
    detail = unique_errors[-1] if unique_errors else "sin detalles"
    if "permission" in detail.lower() or "denied" in detail.lower():
        detail += (
            ". Ejecuta con sudo o configura sudoers NOPASSWD para smartctl "
            "(ver README)."
        )
    return SmartInfo(available=False, error=f"No se pudo leer SMART: {detail}")


def run_self_test(disk: DiskInfo, kind: str = "short", config: Optional[Config] = None) -> str:
    """Lanza un auto-test SMART (short/long/conveyance). Devuelve la salida."""
    cfg = config or Config()
    if kind not in {"short", "long", "conveyance", "offline"}:
        raise ValueError(f"Tipo de test no válido: {kind}")
    smartctl = shutil.which(cfg.smartctl) or cfg.smartctl
    cmd = [*_sudo_prefix(cfg), smartctl, "-t", kind, disk.path]
    proc = _run(cmd, timeout=30)
    output = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        raise SmartError(output or f"smartctl terminó con código {proc.returncode}")
    return output
