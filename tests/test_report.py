"""Tests de presentación de informes."""

from __future__ import annotations

import json

from diskmon.report import (
    human_bytes,
    human_hours,
    pad,
    render_history,
    render_json,
    render_text,
    visible_len,
)


def test_render_json_schema(scan_result):
    data = json.loads(render_json(scan_result))
    assert data["schema"] == "diskmon/1"
    assert data["hostname"] == "test-host"
    assert data["summary"]["disks"] == 2
    assert len(data["disks"]) == 2
    sda = next(d for d in data["disks"] if d["device"] == "sda")
    assert sda["kind"] == "SSD"
    assert sda["score"] == 100
    assert sda["verdict"] == "SANA"
    assert sda["metrics"]["temperature_c"] == 35
    assert isinstance(sda["issues"], list)


def test_render_text_contains_summary_and_detail(scan_result):
    text = render_text(scan_result, color=False)
    assert "RESUMEN" in text
    assert "DETALLE" in text
    assert "sda" in text and "sdb" in text
    assert "TEST SSD 1TB" not in text  # el modelo del fixture no se usa en el informe
    assert "Sin incidencias detectadas." in text
    assert "AVISO" in text
    assert "Recomendación" in text


def test_render_text_verbose_shows_info(scan_result):
    from diskmon.models import HealthIssue

    scan_result.reports[0].issues.append(
        HealthIssue(severity="info", code="demo", message="Detalle informativo")
    )
    assert "Detalle informativo" not in render_text(scan_result, color=False, verbose=False)
    assert "Detalle informativo" in render_text(scan_result, color=False, verbose=True)


def test_render_text_color_has_ansi(scan_result):
    text = render_text(scan_result, color=True)
    assert "\x1b[" in text


def test_render_history_empty():
    assert "Sin registros históricos" in render_history([])


def test_render_history_rows(scan_result):
    rows = [
        {
            "scanned_at": "2026-01-01T10:00:00+01:00",
            "device": "sda",
            "score": 100,
            "grade": "Excelente",
            "verdict": "SANA",
            "temperature_c": 35,
            "power_on_hours": 100,
            "wear_percent": 5,
        }
    ]
    text = render_history(rows)
    assert "HISTÓRICO" in text
    assert "sda" in text
    assert "100" in text


def test_human_bytes():
    assert human_bytes(None) == "—"
    assert human_bytes(0) == "0 B"
    assert human_bytes(1_000_000_000_000) == "1,0 TB"
    assert human_bytes(500_000_000_000) == "500,0 GB"


def test_human_hours():
    assert human_hours(None) == "—"
    assert human_hours(1000) == "1.000 h"
    assert human_hours(100) == "100 h"


def test_pad_and_visible_len_ignore_ansi():
    colored = "\x1b[32mOK\x1b[0m"
    assert visible_len(colored) == 2
    assert pad(colored, 4) == colored + "  "


def test_unknown_smart_shows_reason_not_no_issues(scan_result):
    from diskmon.models import HealthIssue

    scan_result.reports[0].disk.smart.available = False
    scan_result.reports[0].disk.smart.error = "Permission denied"
    scan_result.reports[0].alert_level = "unknown"
    scan_result.reports[0].score = None
    scan_result.reports[0].grade = "Desconocido"
    scan_result.reports[0].verdict = "DESCONOCIDO"
    scan_result.reports[0].issues = [
        HealthIssue(
            severity="info",
            code="smart_unavailable",
            message="Permission denied",
            category="availability",
        )
    ]
    text = render_text(scan_result, color=False)
    assert "Permission denied" in text
    assert "SIN DATOS" in text
    assert "Errores SMART: —" in text
