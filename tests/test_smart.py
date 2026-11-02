"""Tests del colector SMART y del parser de smartctl."""

from __future__ import annotations

import copy

from diskmon.collect.smart import parse_smart_json

from conftest import load_fixture


def test_parse_sata_ssd():
    info = parse_smart_json(load_fixture("smart_sata_ssd.json"))
    assert info.available is True
    assert info.smart_passed is True
    assert info.protocol == "ATA"
    assert info.temperature_c == 35
    assert info.power_on_hours == 1000
    assert info.power_cycles == 100
    assert info.error_log_count == 0
    assert info.exit_status == 0
    assert info.attr(5).name == "Reallocated_Sector_Ct"
    assert info.raw(5) == 0
    assert info.attr_by_name("Media_Wearout_Indicator").value == 100


def test_parse_sata_hdd():
    info = parse_smart_json(load_fixture("smart_sata_hdd.json"))
    assert info.available is True
    assert info.temperature_c == 30
    assert info.power_on_hours == 2000
    assert info.raw(196) == 3  # Reallocated_Event_Count
    assert info.raw(199) == 0  # UDMA_CRC_Error_Count
    assert info.attr(194).raw_string.startswith("30")


def test_parse_exit_status_bits():
    data = copy.deepcopy(load_fixture("smart_sata_ssd.json"))
    data["smartctl"]["exit_status"] = 0x88
    info = parse_smart_json(data)
    assert info.exit_status == 0x88


def test_parse_self_test_failure():
    data = copy.deepcopy(load_fixture("smart_sata_hdd.json"))
    data["ata_smart_self_test_log"] = {
        "standard": {
            "revision": 1,
            "count": 1,
            "table": [
                {
                    "type": {"value": 1, "string": "Short offline"},
                    "status": {"value": 7, "string": "Completed: read failure", "passed": False},
                    "lifetime_hours": 25000,
                    "error_code": 12,
                }
            ],
        }
    }
    info = parse_smart_json(data)
    assert len(info.self_tests) == 1
    assert info.self_tests[0].passed is False
    assert info.last_self_test.status == "Completed: read failure"
    assert len(info.failed_self_tests) == 1


def test_parse_self_test_in_progress_not_failed():
    data = copy.deepcopy(load_fixture("smart_sata_hdd.json"))
    data["ata_smart_self_test_log"] = {
        "standard": {
            "table": [
                {
                    "type": {"string": "Short offline"},
                    "status": {"string": "Self-test routine in progress", "remaining_percent": 40},
                }
            ]
        }
    }
    info = parse_smart_json(data)
    assert info.self_tests[0].passed is None
    assert info.failed_self_tests == []


def test_parse_nvme():
    data = {
        "device": {"name": "/dev/nvme0n1", "protocol": "NVMe"},
        "smartctl": {"exit_status": 0},
        "smart_support": {"available": True, "enabled": True},
        "smart_status": {"passed": True},
        "nvme_smart_health_information_log": {
            "critical_warning": 0,
            "temperature": 313,  # Kelvin en algunos smartctl
            "available_spare": 100,
            "available_spare_threshold": 10,
            "percentage_used": 12,
            "media_errors": 0,
            "num_err_log_entries": 2,
            "unsafe_shutdowns": 4,
            "power_on_hours": 1200,
            "data_units_written": 2_000_000,
        },
    }
    info = parse_smart_json(data)
    assert info.available is True
    assert info.protocol == "NVMe"
    assert info.temperature_c == 39.9
    assert info.nvme["percentage_used"] == 12
    assert info.nvme["tbw"] == 1.0
    assert info.error_log_count == 2


def test_smart_not_supported():
    data = {
        "device": {"name": "/dev/sdc", "protocol": "ATA"},
        "smartctl": {"exit_status": 0, "messages": [{"string": "SMART support is: Unavailable"}]},
        "smart_support": {"available": False, "enabled": False},
    }
    info = parse_smart_json(data)
    assert info.available is False
    assert "no soporta SMART" in (info.error or "")


def test_temperature_fallback_airflow_attribute():
    data = copy.deepcopy(load_fixture("smart_sata_hdd.json"))
    data.pop("temperature", None)
    data["ata_smart_attributes"]["table"] = [
        row for row in data["ata_smart_attributes"]["table"] if row["id"] != 194
    ]
    data["ata_smart_attributes"]["table"].append(
        {
            "id": 190,
            "name": "Airflow_Temperature_Cel",
            "value": 65,
            "worst": 60,
            "thresh": 45,
            "when_failed": "",
            "flags": {"value": 0, "string": ""},
            "raw": {"value": 35, "string": "35 (Min/Max 20/40)"},
        }
    )
    info = parse_smart_json(data)
    assert info.temperature_c == 35


def test_last_selftest_status_without_log_table():
    data = copy.deepcopy(load_fixture("smart_sata_ssd.json"))
    data.pop("ata_smart_self_test_log", None)
    data["ata_smart_data"]["self_test"] = {
        "status": {"value": 0, "string": "Completed without error", "passed": True}
    }
    info = parse_smart_json(data)
    assert len(info.self_tests) == 1
    assert info.self_tests[0].passed is True
