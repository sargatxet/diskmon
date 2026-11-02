"""Tests del descubrimiento de discos con lsblk."""

from __future__ import annotations

from diskmon.collect.blockdev import parse_lsblk

from conftest import load_fixture


def test_parse_real_lsblk():
    disks = parse_lsblk(load_fixture("lsblk.json"))
    names = [d.name for d in disks]
    # Los lectores de tarjetas de 0 B y el DVD se excluyen por defecto.
    assert names == ["sda", "sdb"]
    sda, sdb = disks
    assert sda.rotational is False
    assert sda.transport == "sata"
    assert sda.size_bytes == 1_000_000_000_000
    assert sda.kind == "SSD"
    assert [p.name for p in sda.partitions] == ["sda1", "sda2"]
    assert {p.mountpoint for p in sda.partitions} == {"/boot/efi", "/"}
    assert sdb.rotational is True
    assert sdb.kind == "HDD"
    assert sdb.partitions[0].mountpoint == "/mnt/data"


def test_include_empty_devices():
    disks = parse_lsblk(load_fixture("lsblk.json"), include_empty=True)
    assert len(disks) > 2
    assert any(d.size_bytes == 0 for d in disks)


def test_partition_usage_is_read_for_mounted_fs():
    disks = parse_lsblk(load_fixture("lsblk.json"))
    root = next(p for p in disks[0].partitions if p.mountpoint == "/")
    # En el sistema de ejecución de los tests / está montado y tiene uso.
    assert root.used_bytes is not None
    assert root.use_percent is not None
    assert 0 <= root.use_percent <= 100
