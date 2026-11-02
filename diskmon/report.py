"""Presentación de resultados: texto con color, JSON e histórico."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Iterable, Optional

from .config import Thresholds
from .models import HealthReport, ScanResult

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

COLORS = {
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "red": "\x1b[31m",
    "cyan": "\x1b[36m",
    "dim": "\x1b[2m",
    "bold": "\x1b[1m",
    "reset": "\x1b[0m",
}

ALERT_COLOR = {
    "ok": "green",
    "warning": "yellow",
    "critical": "red",
    "unknown": "dim",
}

SEVERITY_LABEL = {
    "critical": "CRÍTICO",
    "warning": "AVISO",
    "info": "INFO",
}


def color_enabled(no_color: bool = False) -> bool:
    if no_color or os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


class Painter:
    """Aplica color ANSI de forma opcional."""

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def __call__(self, text: str, color: Optional[str] = None, bold: bool = False) -> str:
        if not self.enabled:
            return text
        prefix = ""
        if bold:
            prefix += COLORS["bold"]
        if color:
            prefix += COLORS[color]
        return f"{prefix}{text}{COLORS['reset']}" if prefix else text


def visible_len(text: str) -> int:
    return len(ANSI_RE.sub("", text))


def pad(text: str, width: int, align: str = "left") -> str:
    diff = max(0, width - visible_len(text))
    if align == "right":
        return " " * diff + text
    return text + " " * diff


def human_bytes(num: Optional[int]) -> str:
    if num is None:
        return "—"
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1000 or unit == "PB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}".replace(".", ",")
        value /= 1000.0
    return f"{value:.1f} PB"


def human_hours(hours: Optional[int]) -> str:
    if hours is None:
        return "—"
    text = f"{hours:,} h".replace(",", ".")
    if hours >= 24 * 365:
        years = f"{hours / (24 * 365):.1f}".replace(".", ",")
        text += f" ({years} años)"
    return text


def _fmt(value: Any) -> str:
    return "—" if value is None else str(value)


def _score_bar(score: Optional[int], width: int = 10) -> str:
    if score is None:
        return "░" * width
    filled = int(round(score / 100 * width))
    return "█" * filled + "░" * (width - filled)


def _status_text(report: HealthReport, paint: Painter) -> str:
    color = ALERT_COLOR.get(report.alert_level, "dim")
    label = report.verdict
    if report.score is not None:
        label += f" ({report.score})"
    return paint(label, color, bold=report.alert_level == "critical")


def _table(rows: list[list[str]], headers: list[str], aligns: list[str]) -> str:
    widths = [visible_len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], visible_len(cell))
    lines = []
    header = "  ".join(pad(h, widths[i]) for i, h in enumerate(headers))
    lines.append(header)
    lines.append("  ".join("─" * w for w in widths))
    for row in rows:
        lines.append("  ".join(pad(cell, widths[i], aligns[i]) for i, cell in enumerate(row)))
    return "\n".join(lines)


def _partition_summary(report: HealthReport) -> str:
    parts = []
    for p in report.disk.partitions:
        label = p.mountpoint or p.name
        detail = f"{label}"
        if p.fstype:
            detail += f" ({p.fstype})"
        if p.use_percent is not None:
            detail += f" {p.use_percent:.0f}%"
        parts.append(detail)
    return " · ".join(parts) if parts else "sin particiones montadas"


def _temp_colored(report: HealthReport, t: Thresholds, paint: Painter) -> str:
    temp = report.metrics.get("temperature_c")
    if temp is None:
        return "—"
    warn, crit = t.for_kind(report.disk.kind)
    color = "red" if temp >= crit else ("yellow" if temp >= warn else None)
    return paint(f"{temp:.0f} ºC", color)


def render_text(
    result: ScanResult,
    thresholds: Optional[Thresholds] = None,
    color: bool = False,
    verbose: bool = False,
    show_details: bool = True,
) -> str:
    """Genera la salida legible del escaneo."""
    t = thresholds or Thresholds()
    paint = Painter(color)
    out: list[str] = []

    title = paint("DiskMon", "cyan", bold=True) + " — monitor de salud de discos"
    out.append(title)
    out.append(paint(f"Host: {result.hostname} · {result.started_at}", "dim"))
    out.append("")

    if not result.reports:
        out.append(paint("No se han detectado discos analizables.", "yellow"))
        for err in result.errors:
            out.append(f"  · {err}")
        return "\n".join(out)

    # ------------------------------------------------------------- resumen
    out.append(paint("RESUMEN", bold=True))
    rows = []
    for report in result.reports:
        usage = "—"
        mounted = [p for p in report.disk.partitions if p.use_percent is not None]
        if mounted:
            usage = f"{max(p.use_percent for p in mounted):.0f}%"
        rows.append(
            [
                report.disk.name,
                report.disk.kind,
                report.disk.model or "—",
                human_bytes(report.disk.size_bytes),
                _temp_colored(report, t, paint),
                human_hours(report.metrics.get("power_on_hours")),
                usage,
                _score_bar(report.score),
                _status_text(report, paint),
            ]
        )
    headers = ["Disco", "Tipo", "Modelo", "Capacidad", "Temp", "Horas", "Uso", "Salud", "Estado"]
    aligns = ["left", "left", "left", "right", "right", "right", "right", "left", "left"]
    out.append(_table(rows, headers, aligns))
    out.append("")

    # -------------------------------------------------------------- detalle
    if show_details:
        out.append(paint("DETALLE", bold=True))
        for report in result.reports:
            out.extend(_render_disk_detail(report, t, paint, verbose))
            out.append("")

    if result.errors:
        out.append(paint("AVISOS DE RECOLECCIÓN", bold=True))
        for err in result.errors:
            out.append(f"  · {err}")
        out.append("")

    worst = result.worst_alert
    if worst == "critical":
        out.append(paint("⚠ Hay discos en estado crítico. Haz copia de seguridad cuanto antes.", "red", bold=True))
    elif worst == "warning":
        out.append(paint("⚠ Hay discos que requieren atención. Revisa los avisos.", "yellow", bold=True))
    elif worst == "unknown":
        out.append(paint("ℹ No se pudo determinar la salud de algún disco.", "dim"))
    return "\n".join(out)


def _render_disk_detail(
    report: HealthReport, t: Thresholds, paint: Painter, verbose: bool
) -> list[str]:
    disk = report.disk
    color = ALERT_COLOR.get(report.alert_level, "dim")
    lines: list[str] = []
    heading = f"{disk.name} · {disk.model or 'Modelo desconocido'}"
    lines.append(paint(f"┌─ {heading} " + "─" * max(0, 58 - visible_len(heading)), color))
    score = "—/100" if report.score is None else f"{report.score}/100"
    status = f"{report.grade} · {report.verdict}"
    lines.append(
        "│ "
        + paint(f"Salud: {score}  [{_score_bar(report.score)}]  {status}", color, bold=True)
    )
    lines.append(
        "│ "
        + f"Tipo: {disk.kind} · {human_bytes(disk.size_bytes)} · "
        + f"{(disk.transport or 'bus desconocido').upper()} · serie {disk.serial or '—'}"
    )
    lines.append(
        "│ "
        + f"Temperatura: {_temp_colored(report, t, paint)} · "
        + f"Horas: {human_hours(report.metrics.get('power_on_hours'))} · "
        + f"Ciclos: {_fmt(report.metrics.get('power_cycles'))} · "
        + f"Errores SMART: {_fmt(report.metrics.get('error_log_count')) if disk.smart.available else '—'}"
    )
    if disk.smart.available:
        passed = disk.smart.smart_passed
        smart_text = "superada" if passed else ("FALLIDA" if passed is False else "desconocida")
        smart_color = "green" if passed else ("red" if passed is False else "dim")
        last_test = report.metrics.get("last_self_test")
        wear = report.metrics.get("wear_percent")
        spare = report.metrics.get("spare_percent")
        extra = []
        if wear is not None:
            extra.append(f"desgaste {wear}%")
        if spare is not None:
            extra.append(f"reserva {spare}%")
        if report.metrics.get("tbw") is not None:
            extra.append(f"escrito {report.metrics['tbw']} TB")
        if last_test:
            extra.append(f"último test: {last_test}")
        line = "│ Salud SMART: " + paint(smart_text, smart_color)
        if extra:
            line += " · " + " · ".join(extra)
        lines.append(line)
    else:
        lines.append("│ Salud SMART: " + paint("no disponible", "yellow"))

    if disk.partitions:
        lines.append("│ Particiones: " + _partition_summary(report))

    shown = report.sorted_issues()
    if not verbose:
        # Los avisos de disponibilidad (sin SMART) son imprescindibles aunque
        # sean de nivel informativo; el resto de "info" solo en modo -v.
        shown = [i for i in shown if i.severity != "info" or i.category == "availability"]
    if shown:
        lines.append("│")
        for issue in shown:
            if issue.category == "availability":
                label, sev_color = "SIN DATOS", "yellow"
            else:
                label = SEVERITY_LABEL[issue.severity]
                sev_color = {"critical": "red", "warning": "yellow", "info": "dim"}[issue.severity]
            lines.append(f"│ {paint(f'[{label}]', sev_color)} {issue.message}")
    else:
        lines.append("│ " + paint("Sin incidencias detectadas.", "green"))

    if report.critical_issues:
        lines.append(
            "│ "
            + paint(
                "Recomendación: copia de seguridad inmediata y planifica la sustitución.",
                "red",
            )
        )
    elif report.warning_issues:
        lines.append(
            "│ " + paint("Recomendación: refuerza las copias y revisa el disco periódicamente.", "yellow")
        )
    lines.append(paint("└" + "─" * 60, color))
    return lines


def render_json(result: ScanResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


def render_history(rows: Iterable[dict[str, Any]], color: bool = False) -> str:
    """Tabla del histórico de un disco."""
    paint = Painter(color)
    rows = list(rows)
    if not rows:
        return "Sin registros históricos. Ejecuta 'diskmon scan' para empezar a guardar."
    table_rows = []
    for row in rows:
        score = "—" if row.get("score") is None else str(row["score"])
        temp = "—" if row.get("temperature_c") is None else f"{row['temperature_c']:.0f} ºC"
        table_rows.append(
            [
                str(row.get("scanned_at") or ""),
                str(row.get("device") or ""),
                score,
                str(row.get("grade") or ""),
                str(row.get("verdict") or ""),
                temp,
                _fmt(row.get("power_on_hours")),
                _fmt(row.get("wear_percent")),
            ]
        )
    headers = ["Fecha", "Disco", "Puntos", "Nota", "Estado", "Temp", "Horas", "Desgaste%"]
    aligns = ["left", "left", "right", "left", "left", "right", "right", "right"]
    title = paint("HISTÓRICO", bold=True)
    return title + "\n" + _table(table_rows, headers, aligns)
