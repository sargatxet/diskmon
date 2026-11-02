"""Utilidades compartidas por los tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from diskmon.collect.smart import parse_smart_json
from diskmon.models import DiskInfo, Partition, ScanResult
from diskmon.analysis import analyze_disk

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def make_disk(
    fixture: str,
    name: str = "sda",
    rotational: bool = False,
    transport: str = "sata",
    size_bytes: int = 1_000_000_000_000,
    partitions: list[Partition] | None = None,
) -> DiskInfo:
    return DiskInfo(
        name=name,
        path=f"/dev/{name}",
        model="Disco de prueba",
        serial="TEST-0001",
        size_bytes=size_bytes,
        rotational=rotational,
        transport=transport,
        partitions=partitions or [],
        smart=parse_smart_json(load_fixture(fixture)),
    )


@pytest.fixture
def ssd() -> DiskInfo:
    return make_disk("smart_sata_ssd.json", name="sda", rotational=False)


@pytest.fixture
def hdd() -> DiskInfo:
    return make_disk("smart_sata_hdd.json", name="sdb", rotational=True)


@pytest.fixture
def scan_result(ssd, hdd) -> ScanResult:
    return ScanResult(
        hostname="test-host",
        reports=[analyze_disk(ssd), analyze_disk(hdd)],
    )
