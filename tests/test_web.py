"""Tests del dashboard web (cache y API, sin abrir puertos)."""

from __future__ import annotations

from diskmon.analysis import analyze_disk
from diskmon.config import Config
from diskmon.models import ScanResult
from diskmon.web import ScanCache


def test_scan_cache(ssd, monkeypatch):
    calls = []

    def fake_scan(config):
        calls.append(1)
        return ScanResult(hostname="test-host", reports=[analyze_disk(ssd)])

    monkeypatch.setattr("diskmon.web.scan", fake_scan)
    cache = ScanCache(ttl=60)
    first = cache.get(Config())
    second = cache.get(Config())
    assert first["hostname"] == "test-host"
    assert first == second
    assert len(calls) == 1

    cache.get(Config(), force=True)
    assert len(calls) == 2


def test_scan_cache_save_uses_history(ssd, monkeypatch, tmp_path):
    def fake_scan(config):
        return ScanResult(hostname="test-host", reports=[analyze_disk(ssd)])

    monkeypatch.setattr("diskmon.web.scan", fake_scan)
    cfg = Config(db_path=str(tmp_path / "web.db"))
    cache = ScanCache(ttl=60)
    cache.get(cfg, save=True)
    from diskmon.history import History

    assert History(cfg.db_file).stats()["reports"] == 1
