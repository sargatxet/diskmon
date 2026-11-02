"""Motor de análisis de salud de discos.

El resultado es una puntuación de 0 a 100 y una lista de hallazgos explicables.
Las reglas son deliberadamente conservadoras: cualquier indicio de fallo real
(sectores reasignados, pendientes, errores SMART, desgaste extremo) resta puntos
y se muestra con su motivo, de forma que el usuario pueda actuar.
"""

from __future__ import annotations

from typing import Optional

from .config import Thresholds
from .models import DiskInfo, HealthIssue, HealthReport, ScanResult

#: Penalizaciones máximas por tipo de hallazgo (evita que un solo atributo
#: enmascare el resto, pero mantiene la puntuación acotada a 0..100).
GRADE_TABLE = (
    (90, "Excelente"),
    (75, "Buena"),
    (55, "Precaución"),
    (35, "Degradada"),
    (0, "Crítica"),
)


def grade_for(score: int) -> str:
    for minimum, name in GRADE_TABLE:
        if score >= minimum:
            return name
    return "Crítica"


def _verdict_for(score: int, has_critical: bool, has_warning: bool = False) -> str:
    if has_critical:
        return "FALLANDO" if score < 55 else "EN RIESGO"
    if has_warning:
        if score >= 55:
            return "VIGILAR"
        return "EN RIESGO" if score >= 35 else "FALLANDO"
    if score >= 75:
        return "SANA"
    if score >= 55:
        return "VIGILAR"
    if score >= 35:
        return "EN RIESGO"
    return "FALLANDO"


def _decode_critical_warning(value: int) -> str:
    bits = {
        0x01: "espacio de reserva agotado",
        0x02: "temperatura fuera de rango",
        0x04: "fiabilidad degradada",
        0x08: "medio de solo lectura",
        0x10: "fallo de respaldo de memoria volátil",
        0x20: "fallo de memoria persistente",
    }
    labels = [text for bit, text in bits.items() if value & bit]
    return ", ".join(labels) if labels else f"código {value}"


def _wear_percent(disk: DiskInfo) -> Optional[int]:
    """Vida consumida estimada (%) a partir de atributos ATA o NVMe."""
    smart = disk.smart
    candidates: list[int] = []
    nvme_used = smart.nvme.get("percentage_used")
    if isinstance(nvme_used, (int, float)):
        candidates.append(int(nvme_used))
    for attr_id in (202, 231, 233, 177):
        attr = smart.attr(attr_id)
        if attr is None or attr.value is None:
            continue
        if attr_id == 202:  # Percentage_Used: mayor es peor
            candidates.append(int(attr.value))
        else:  # indicadores de vida restante: menor es peor
            candidates.append(max(0, 100 - int(attr.value)))
    # Algunos fabricantes usan nombres no estándar para el desgaste.
    for attr in smart.attributes.values():
        if attr.value is None:
            continue
        name = attr.name.lower()
        if "percentage_used" in name:
            candidates.append(int(attr.value))
        elif any(
            token in name
            for token in ("remaining_lifetime", "ssd_life_left", "media_wearout", "wear_leveling")
        ):
            candidates.append(max(0, 100 - int(attr.value)))
    return max(candidates) if candidates else None


def _spare_percent(disk: DiskInfo) -> Optional[int]:
    smart = disk.smart
    spare = smart.nvme.get("available_spare")
    if isinstance(spare, (int, float)):
        return int(spare)
    attr = smart.attr(180)  # Unused_Rsvd_Blk_Cnt_Tot
    if attr is not None and attr.value is not None:
        return int(attr.value)
    return None


def analyze_disk(disk: DiskInfo, thresholds: Optional[Thresholds] = None) -> HealthReport:
    """Analiza un disco y devuelve su informe de salud."""
    t = thresholds or Thresholds()
    smart = disk.smart
    issues: list[HealthIssue] = []

    def add(
        severity: str,
        code: str,
        message: str,
        penalty: int = 0,
        category: str = "smart",
    ) -> None:
        issues.append(
            HealthIssue(
                severity=severity,
                code=code,
                message=message,
                penalty=penalty,
                category=category,
            )
        )

    # ---------------------------------------------------------- disponibilidad
    if not smart.available:
        add(
            "info",
            "smart_unavailable",
            smart.error or "No se pudieron leer los datos SMART de este disco",
            category="availability",
        )

    # ------------------------------------------------------------ estado global
    if smart.smart_passed is False:
        add("critical", "smart_status_failed", "SMART indica fallo inminente del disco", 60)

    # Bits de estado de smartctl (ver manual, sección EXIT STATUS).
    ex = smart.exit_status
    attr_failed = any(a.failed for a in smart.attributes.values())
    if ex & 0x08 and smart.smart_passed is not False:
        add("critical", "smartctl_failing", "smartctl marca el disco como fallando", 30)
    if ex & 0x10 and not attr_failed:
        add(
            "critical",
            "attr_below_threshold",
            "Un atributo SMART prefail está en o por debajo de su umbral",
            20,
        )
    if ex & 0x20 and not attr_failed:
        add(
            "warning",
            "attr_past_threshold",
            "Un atributo SMART ha superado su umbral en algún momento",
            10,
        )
    if ex & 0x40 and smart.error_log_count == 0:
        add("warning", "error_log_present", "El registro de errores SMART contiene entradas", 5)
    if ex & 0x80 and not smart.failed_self_tests:
        add("warning", "selftest_log_error", "El registro de auto-tests contiene errores", 15)
    if ex & 0x04:
        add(
            "warning",
            "smart_partial",
            "Algunos comandos SMART fallaron; los datos pueden estar incompletos",
            5,
            category="availability",
        )

    # ------------------------------------------------------- atributos críticos
    for attr in smart.attributes.values():
        if not attr.when_failed:
            continue
        failing_now = "now" in attr.when_failed.lower()
        add(
            "critical" if failing_now else "warning",
            "attr_failing",
            f"Atributo SMART {attr.name} marcado como fallando ({attr.when_failed})",
            30 if failing_now else 10,
        )

    realloc = smart.raw(5)  # Reallocated_Sector_Ct
    pending = smart.raw(197)  # Current_Pending_Sector
    offline = smart.raw(198)  # Offline_Uncorrectable
    reported = smart.raw(187)  # Reported_Uncorrect
    crc = smart.raw(199)  # UDMA_CRC_Error_Count
    timeouts = smart.raw(188)  # Command_Timeout
    spin_retry = smart.raw(10)  # Spin_Retry_Count
    realloc_events = smart.raw(196)  # Reallocated_Event_Count
    g_sense = smart.raw(191)  # G-Sense_Error_Rate
    program_fail = smart.raw(175)  # Program_Fail_Count_Chip
    load_cycles = smart.raw(193)  # Load_Cycle_Count

    if realloc is not None and realloc > 0:
        if realloc >= t.realloc_crit:
            add(
                "critical",
                "reallocated_sectors",
                f"{realloc} sectores reasignados (umbral crítico {t.realloc_crit}); "
                "la superficie del disco está deteriorándose",
                35,
            )
        elif realloc >= t.realloc_warn:
            add(
                "warning",
                "reallocated_sectors",
                f"{realloc} sectores reasignados; vigila su evolución",
                min(20, 5 + realloc * 2),
            )

    if pending is not None and pending > 0:
        severity = "critical" if pending >= t.pending_crit else "warning"
        add(
            severity,
            "pending_sectors",
            f"{pending} sectores pendientes de reasignación; posible pérdida de datos",
            30 if severity == "critical" else 15,
        )

    if offline is not None and offline > 0:
        add(
            "critical" if offline >= t.offline_uncorrectable_crit else "warning",
            "offline_uncorrectable",
            f"{offline} sectores no corregibles detectados en análisis offline",
            25 if offline >= t.offline_uncorrectable_crit else 12,
        )

    if reported is not None and reported > 0:
        add(
            "warning",
            "reported_uncorrect",
            f"{reported} errores no corregidos reportados por el disco",
            min(20, 5 + reported),
        )

    if crc is not None and crc > 0:
        add(
            "warning",
            "udma_crc_errors",
            f"{crc} errores CRC de transmisión; revisa cable/puerto SATA "
            "(no implica necesariamente fallo del disco)",
            min(15, 4 + crc),
        )

    if timeouts is not None and timeouts > 0:
        add(
            "warning",
            "command_timeouts",
            f"{timeouts} timeouts de comandos; posible problema de cableado o alimentación",
            10,
        )

    if spin_retry is not None and spin_retry > 0:
        add(
            "critical",
            "spin_retry",
            f"{spin_retry} reintentos de arranque del motor; el disco puede no girar",
            25,
        )

    if realloc_events is not None and realloc_events > 0:
        add(
            "warning",
            "reallocated_events",
            f"{realloc_events} eventos de reasignación de sectores",
            10,
        )

    if g_sense is not None and g_sense > 0:
        add(
            "warning" if g_sense >= 10 else "info",
            "g_sense_errors",
            f"{g_sense} errores por golpes/vibración (G-Sense)",
            5 if g_sense >= 10 else 0,
        )

    if program_fail is not None and program_fail > 0:
        add(
            "warning",
            "program_fail",
            f"{program_fail} fallos de programación en celdas NAND",
            10,
            category="wear",
        )

    if load_cycles is not None and load_cycles > 600_000:
        add(
            "warning",
            "load_cycles",
            f"{load_cycles} ciclos de carga del cabezal; valor elevado para un HDD",
            10,
            category="wear",
        )

    # --------------------------------------------------------------- desgaste
    wear = _wear_percent(disk)
    if wear is not None:
        if wear >= t.wear_crit:
            add(
                "critical",
                "wear_exhausted",
                f"Vida útil del SSD prácticamente agotada ({wear}% consumido)",
                30,
                category="wear",
            )
        elif wear >= t.wear_warn:
            add(
                "warning",
                "wear_high",
                f"Desgaste elevado del SSD ({wear}% de vida consumida)",
                20,
                category="wear",
            )
        elif wear >= 60:
            add(
                "info",
                "wear_moderate",
                f"Desgaste moderado del SSD ({wear}% de vida consumida)",
                0,
                category="wear",
            )

    spare = _spare_percent(disk)
    if spare is not None:
        if smart.nvme.get("available_spare") is not None:
            nvme_threshold = smart.nvme.get("available_spare_threshold")
            limit = int(nvme_threshold) if isinstance(nvme_threshold, (int, float)) else t.spare_warn
        else:
            limit = t.spare_warn
        if spare < limit:
            add(
                "critical",
                "spare_exhausted",
                f"Bloques de reserva por debajo del umbral ({spare}% disponible)",
                35,
                category="wear",
            )
        elif spare < limit + 10:
            add(
                "warning",
                "spare_low",
                f"Bloques de reserva bajos ({spare}% disponible)",
                15,
                category="wear",
            )

    # ------------------------------------------------------------ temperatura
    if smart.temperature_c is not None:
        temp = smart.temperature_c
        warn, crit = t.for_kind(disk.kind)
        if temp >= crit:
            add(
                "critical",
                "temperature_high",
                f"Temperatura crítica: {temp:.0f} ºC (límite {crit:.0f} ºC)",
                20,
                category="temperature",
            )
        elif temp >= warn:
            add(
                "warning",
                "temperature_warm",
                f"Temperatura alta: {temp:.0f} ºC (aviso a partir de {warn:.0f} ºC)",
                8,
                category="temperature",
            )

    # ---------------------------------------------------------- horas de uso
    if smart.power_on_hours is not None:
        hours = smart.power_on_hours
        if disk.kind == "HDD":
            if hours >= t.hdd_hours_crit:
                add(
                    "warning",
                    "power_on_hours",
                    f"{hours:,} horas de funcionamiento; disco muy veterano",
                    10,
                    category="wear",
                )
            elif hours >= t.hdd_hours_warn:
                add(
                    "info",
                    "power_on_hours",
                    f"{hours:,} horas de funcionamiento; vigila la tendencia",
                    0,
                    category="wear",
                )
        elif hours >= t.ssd_hours_warn:
            add(
                "info",
                "power_on_hours",
                f"{hours:,} horas de funcionamiento del SSD",
                0,
                category="wear",
            )

    # ------------------------------------------------------- errores y tests
    if smart.error_log_count > 0:
        add(
            "warning",
            "error_log_entries",
            f"{smart.error_log_count} errores registrados en el log SMART",
            min(10, 2 + smart.error_log_count * 2),
        )

    last_test = smart.last_self_test
    if last_test is not None:
        if last_test.passed is False:
            add(
                "critical",
                "selftest_failed",
                f"El último auto-test falló ({last_test.status})",
                25,
            )
        elif smart.failed_self_tests:
            add(
                "warning",
                "selftest_failed_history",
                f"{len(smart.failed_self_tests)} auto-tests fallidos en el historial",
                15,
            )
        elif last_test.passed is True:
            add(
                "info",
                "selftest_ok",
                f"Último auto-test superado ({last_test.type or 'SMART'})",
                0,
            )

    # ------------------------------------------------------------------ NVMe
    nvme = smart.nvme
    if nvme:
        critical_warning = nvme.get("critical_warning")
        if isinstance(critical_warning, int) and critical_warning:
            add(
                "critical",
                "nvme_critical_warning",
                "NVMe reporta aviso crítico: " + _decode_critical_warning(critical_warning),
                50,
            )
        media_errors = nvme.get("media_errors")
        if isinstance(media_errors, int) and media_errors > 0:
            add(
                "critical",
                "nvme_media_errors",
                f"{media_errors} errores de medio (media errors) en el NVMe",
                40,
            )
        unsafe = nvme.get("unsafe_shutdowns")
        if isinstance(unsafe, int) and unsafe > 0:
            add(
                "info",
                "nvme_unsafe_shutdowns",
                f"{unsafe} apagados inseguros registrados",
                0,
            )

    # ------------------------------------------------------- capacidad de FS
    for part in disk.partitions:
        if part.use_percent is None:
            continue
        if part.use_percent >= t.fs_crit:
            add(
                "warning",
                "filesystem_full",
                f"{part.mountpoint or part.name} al {part.use_percent:.0f}% de capacidad",
                0,
                category="capacity",
            )
        elif part.use_percent >= t.fs_warn:
            add(
                "info",
                "filesystem_high",
                f"{part.mountpoint or part.name} al {part.use_percent:.0f}% de capacidad",
                0,
                category="capacity",
            )

    # ------------------------------------------------------------- puntuación
    total_penalty = min(100, sum(max(0, i.penalty) for i in issues))
    score = max(0, 100 - total_penalty)
    has_critical = any(i.severity == "critical" for i in issues)
    has_warning = any(i.severity == "warning" for i in issues)

    if not smart.available:
        grade = "Desconocido"
        verdict = "DESCONOCIDO"
        score_value: Optional[int] = None
        alert = "warning" if has_warning else "unknown"
    else:
        grade = grade_for(score)
        if has_critical and score >= 75:
            grade = "Precaución"
        elif has_warning and score >= 90:
            # Una puntuación alta con avisos no debe etiquetarse como Excelente.
            grade = "Buena"
        verdict = _verdict_for(score, has_critical, has_warning)
        score_value = score
        if has_critical or score < 35:
            alert = "critical"
        elif has_warning or score < 75:
            alert = "warning"
        else:
            alert = "ok"

    metrics = {
        "temperature_c": smart.temperature_c,
        "power_on_hours": smart.power_on_hours,
        "power_cycles": smart.power_cycles,
        "error_log_count": smart.error_log_count,
        "smart_passed": smart.smart_passed,
        "reallocated_sectors": realloc,
        "pending_sectors": pending,
        "offline_uncorrectable": offline,
        "udma_crc_errors": crc,
        "wear_percent": wear,
        "spare_percent": spare,
        "media_errors": nvme.get("media_errors"),
        "tbw": nvme.get("tbw"),
        "last_self_test": last_test.status if last_test else None,
    }
    return HealthReport(
        disk=disk,
        score=score_value,
        grade=grade,
        verdict=verdict,
        alert_level=alert,
        issues=issues,
        metrics=metrics,
    )


def analyze_scan(result: ScanResult, thresholds: Optional[Thresholds] = None) -> ScanResult:
    """Aplica el análisis a todos los discos de un ``ScanResult``."""
    result.reports = [analyze_disk(report.disk, thresholds) for report in result.reports]
    return result
