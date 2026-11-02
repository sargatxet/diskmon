"""Tests de la configuración TOML."""

from __future__ import annotations

from diskmon.config import Config, Thresholds, load_config


def test_defaults():
    cfg = Config()
    assert cfg.use_sudo == "auto"
    assert cfg.fail_on == "warning"
    assert cfg.thresholds.temp_warn_hdd == 50


def test_load_toml(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
db_path = "~/diskmon-test.db"
use_sudo = "never"
exclude = ["sdz"]
fail_on = "critical"

[thresholds]
temp_warn_hdd = 45
realloc_crit = 5
""",
        encoding="utf-8",
    )
    cfg = load_config(str(path))
    assert cfg.db_path == "~/diskmon-test.db"
    assert cfg.use_sudo == "never"
    assert cfg.exclude == ["sdz"]
    assert cfg.fail_on == "critical"
    assert cfg.thresholds.temp_warn_hdd == 45
    assert cfg.thresholds.realloc_crit == 5


def test_unknown_keys_are_ignored(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('desconocido = 1\n[thresholds]\nfoo = 2\n', encoding="utf-8")
    cfg = load_config(str(path))
    assert isinstance(cfg.thresholds, Thresholds)


def test_missing_file_returns_defaults(tmp_path):
    cfg = load_config(str(tmp_path / "no-existe.toml"))
    assert cfg.db_path == Config().db_path


def test_exclude_matching():
    cfg = Config(exclude=["sdz", "USB-123"])
    assert cfg.is_excluded("sdz", "/dev/sdz")
    assert cfg.is_excluded("sda", "/dev/sda", serial="USB-123")
    assert not cfg.is_excluded("sda", "/dev/sda", serial="OTRO")
