"""Tests de la CLI (sin tocar discos reales)."""

from __future__ import annotations

import json

import diskmon.cli as cli
from diskmon.analysis import analyze_disk
from diskmon.models import ScanResult


def _fake_scan_factory(disk):
    report = analyze_disk(disk)

    def fake_scan(config, only=None):
        return ScanResult(hostname="test-host", reports=[report])

    return fake_scan


def test_scan_json_exit_zero(ssd, monkeypatch, capsys):
    monkeypatch.setattr(cli, "scan", _fake_scan_factory(ssd))
    code = cli.main(["scan", "--json", "--no-save"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["disks"][0]["device"] == "sda"


def test_scan_warning_exit_one(hdd, monkeypatch, capsys):
    monkeypatch.setattr(cli, "scan", _fake_scan_factory(hdd))
    code = cli.main(["scan", "--json", "--no-save"])
    assert code == 1
    capsys.readouterr()


def test_fail_on_critical_ignores_warning(hdd, monkeypatch, capsys):
    monkeypatch.setattr(cli, "scan", _fake_scan_factory(hdd))
    code = cli.main(["scan", "--json", "--no-save", "--fail-on", "critical"])
    assert code == 0
    capsys.readouterr()


def test_critical_exit_two(ssd, monkeypatch, capsys):
    ssd.smart.smart_passed = False
    monkeypatch.setattr(cli, "scan", _fake_scan_factory(ssd))
    code = cli.main(["scan", "--json", "--no-save"])
    assert code == 2
    capsys.readouterr()


def test_default_subcommand_is_scan(ssd, monkeypatch, capsys):
    monkeypatch.setattr(cli, "scan", _fake_scan_factory(ssd))
    code = cli.main(["--json", "--no-save"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["schema"] == "diskmon/1"


def test_version_command(capsys):
    code = cli.main(["version"])
    assert code == 0
    assert "diskmon" in capsys.readouterr().out


def test_history_command_empty(tmp_path, capsys):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'db_path = "{tmp_path / "h.db"}"\n', encoding="utf-8")
    code = cli.main(["history", "--config", str(cfg), "--json"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["rows"] == []


def test_unknown_health_fails_when_warning_level(ssd, monkeypatch, capsys):
    ssd.smart.available = False
    ssd.smart.error = "sin permisos"
    monkeypatch.setattr(cli, "scan", _fake_scan_factory(ssd))
    code = cli.main(["scan", "--json", "--no-save", "--fail-on", "warning"])
    assert code == 1
    capsys.readouterr()


def test_unknown_health_ok_when_critical_level(ssd, monkeypatch, capsys):
    ssd.smart.available = False
    monkeypatch.setattr(cli, "scan", _fake_scan_factory(ssd))
    code = cli.main(["scan", "--json", "--no-save", "--fail-on", "critical"])
    assert code == 0
    capsys.readouterr()
