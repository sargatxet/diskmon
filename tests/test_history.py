"""Tests del histórico SQLite."""

from __future__ import annotations

from diskmon.analysis import analyze_disk
from diskmon.history import History


def test_save_and_query(scan_result, tmp_path):
    db = tmp_path / "history.db"
    history = History(db)
    scan_id = history.save_scan(scan_result)
    assert scan_id >= 1

    rows = history.query(limit=10)
    assert len(rows) == 2
    assert {r["device"] for r in rows} == {"sda", "sdb"}
    assert all(isinstance(r["issues"], list) for r in rows)
    assert all(isinstance(r["metrics"], dict) for r in rows)

    sda_rows = history.query(device="sda")
    assert len(sda_rows) == 1
    assert sda_rows[0]["serial"] == "TEST-0001"
    assert sda_rows[0]["score"] == 100

    latest = history.latest("sdb")
    assert latest is not None
    assert latest["alert_level"] == "warning"


def test_devices_and_stats(scan_result, tmp_path):
    history = History(tmp_path / "history.db")
    history.save_scan(scan_result)
    devices = history.devices()
    assert [d["device"] for d in devices] == ["sda", "sdb"]
    stats = history.stats()
    assert stats["scans"] == 1
    assert stats["reports"] == 2
    assert stats["last_scan"] == scan_result.started_at


def test_limit_and_order(ssd, tmp_path):
    from diskmon.models import ScanResult

    history = History(tmp_path / "history.db")
    for score_disk in (ssd, ssd):
        result = ScanResult(hostname="h", reports=[analyze_disk(score_disk)])
        history.save_scan(result)
    rows = history.query(limit=1)
    assert len(rows) == 1


def test_query_unknown_device(scan_result, tmp_path):
    history = History(tmp_path / "history.db")
    history.save_scan(scan_result)
    assert history.query(device="sdz") == []
