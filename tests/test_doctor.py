"""Tests de la comprobación de entorno (`diskmon doctor`)."""

from __future__ import annotations

import json
import shutil

from diskmon.config import Config
from diskmon.doctor import Check, _check_smartctl, exit_code, json_output, render, run_checks


def test_exit_codes():
    assert exit_code([Check("a", "ok", "")]) == 0
    assert exit_code([Check("a", "ok", ""), Check("b", "warn", "")]) == 1
    assert exit_code([Check("a", "warn", ""), Check("b", "fail", "")]) == 2


def test_render_and_json():
    checks = [Check("Python", "ok", "3.12"), Check("smartctl", "fail", "no encontrado", "instala")]
    text = render(checks)
    assert "FALLO" in text
    assert "Python" in text
    assert "instala" in text
    data = json.loads(json_output(checks))
    assert data["schema"] == "diskmon-doctor/1"
    assert data["status"] == "fail"
    assert len(data["checks"]) == 2


def test_run_checks_contains_core_checks(tmp_path):
    config = Config(db_path=str(tmp_path / "doctor.db"))
    checks = run_checks(config)
    names = {c.name for c in checks}
    assert {
        "Sistema operativo",
        "Python",
        "Configuración TOML",
        "lsblk",
        "smartctl",
        "Acceso SMART",
        "Discos",
        "Lectura SMART",
        "systemd",
        "Histórico",
    } <= names
    assert all(c.status in {"ok", "warn", "fail"} for c in checks)


def test_missing_smartctl(monkeypatch):
    real_which = shutil.which

    def fake_which(name: str):
        return None if name == "smartctl" else real_which(name)

    monkeypatch.setattr("diskmon.doctor.shutil.which", fake_which)
    check = _check_smartctl()
    assert check.status == "fail"
    assert "smartmontools" in check.hint


def test_old_distro_is_warned(monkeypatch):
    from diskmon.doctor import _check_os

    monkeypatch.setattr(
        "diskmon.doctor._os_release",
        lambda: {
            "ID": "debian",
            "VERSION_ID": "10",
            "PRETTY_NAME": "Debian GNU/Linux 10 (buster)",
        },
    )
    monkeypatch.setattr("diskmon.doctor.platform.release", lambda: "6.1.0-generic")
    check = _check_os()
    assert check.status == "warn"
    assert "anterior" in check.detail


def test_supported_distro_is_ok(monkeypatch):
    from diskmon.doctor import _check_os

    monkeypatch.setattr(
        "diskmon.doctor._os_release",
        lambda: {
            "ID": "debian",
            "VERSION_ID": "11",
            "PRETTY_NAME": "Debian GNU/Linux 11 (bullseye)",
        },
    )
    monkeypatch.setattr("diskmon.doctor.platform.release", lambda: "6.1.0-generic")
    check = _check_os()
    assert check.status == "ok"
