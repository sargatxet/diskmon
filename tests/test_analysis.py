"""Tests del motor de análisis de salud."""

from __future__ import annotations

from diskmon.analysis import analyze_disk, grade_for
from diskmon.config import Thresholds
from diskmon.models import Partition, SmartAttribute

from conftest import make_disk


def test_grade_table():
    assert grade_for(100) == "Excelente"
    assert grade_for(90) == "Excelente"
    assert grade_for(89) == "Buena"
    assert grade_for(75) == "Buena"
    assert grade_for(74) == "Precaución"
    assert grade_for(55) == "Precaución"
    assert grade_for(54) == "Degradada"
    assert grade_for(35) == "Degradada"
    assert grade_for(34) == "Crítica"


def test_healthy_ssd(ssd):
    report = analyze_disk(ssd)
    assert report.score == 100
    assert report.grade == "Excelente"
    assert report.verdict == "SANA"
    assert report.alert_level == "ok"
    assert report.metrics["wear_percent"] == 5
    assert report.critical_issues == []


def test_healthy_hdd_has_minor_warning(hdd):
    report = analyze_disk(hdd)
    # Reallocated_Event_Count = 3 pero 0 sectores reasignados actualmente.
    assert report.score == 90
    assert report.grade == "Buena"
    assert report.verdict == "VIGILAR"
    assert report.alert_level == "warning"
    assert any(i.code == "reallocated_events" for i in report.warning_issues)


def test_pending_and_reallocated_sectors_are_critical(ssd):
    ssd.smart.attributes[197] = SmartAttribute(
        id=197, name="Current_Pending_Sector", value=100, worst=100, threshold=0, raw=8
    )
    ssd.smart.attributes[5] = SmartAttribute(
        id=5, name="Reallocated_Sector_Ct", value=50, worst=50, threshold=5, raw=12
    )
    report = analyze_disk(ssd)
    codes = {i.code for i in report.critical_issues}
    assert "pending_sectors" in codes
    assert "reallocated_sectors" in codes
    assert report.score is not None and report.score <= 35
    assert report.alert_level == "critical"
    assert report.verdict in {"EN RIESGO", "FALLANDO"}


def test_smart_status_failed_is_critical(ssd):
    ssd.smart.smart_passed = False
    report = analyze_disk(ssd)
    assert report.score == 40
    assert report.grade == "Degradada"
    assert report.verdict == "FALLANDO"
    assert any(i.code == "smart_status_failed" for i in report.critical_issues)


def test_high_temperature_warning(ssd):
    thresholds = Thresholds(temp_warn_ssd=30, temp_crit_ssd=40)
    report = analyze_disk(ssd, thresholds)
    assert report.metrics["temperature_c"] == 35
    assert report.alert_level == "warning"
    assert any(i.code == "temperature_warm" for i in report.warning_issues)
    assert report.score == 92


def test_wear_exhausted(ssd):
    ssd.smart.attributes[233] = SmartAttribute(
        id=233, name="Media_Wearout_Indicator", value=3, worst=3, threshold=5, raw=97
    )
    report = analyze_disk(ssd)
    assert report.metrics["wear_percent"] == 97
    assert any(i.code == "wear_exhausted" for i in report.critical_issues)
    assert report.alert_level == "critical"


def test_nvme_health():
    data = {
        "device": {"name": "/dev/nvme0n1", "protocol": "NVMe"},
        "smartctl": {"exit_status": 0},
        "smart_support": {"available": True},
        "smart_status": {"passed": True},
        "nvme_smart_health_information_log": {
            "critical_warning": 0,
            "temperature": 45,
            "available_spare": 5,
            "available_spare_threshold": 10,
            "percentage_used": 95,
            "media_errors": 2,
            "num_err_log_entries": 3,
            "power_on_hours": 5000,
        },
    }
    from diskmon.collect.smart import parse_smart_json

    disk = make_disk("smart_sata_ssd.json", name="nvme0n1", transport="nvme")
    disk.smart = parse_smart_json(data)
    report = analyze_disk(disk)
    codes = {i.code for i in report.critical_issues}
    assert {"spare_exhausted", "wear_exhausted", "nvme_media_errors"} <= codes
    assert report.alert_level == "critical"


def test_filesystem_capacity_is_reported_without_penalty(ssd):
    ssd.partitions = [
        Partition(name="sda2", path="/dev/sda2", size_bytes=1000, fstype="ext4",
                  mountpoint="/", used_bytes=960, free_bytes=40, use_percent=96.0)
    ]
    report = analyze_disk(ssd)
    assert report.score == 100
    assert report.alert_level == "warning"
    assert any(i.code == "filesystem_full" for i in report.warning_issues)
    assert report.verdict == "VIGILAR"


def test_smart_unavailable_gives_unknown(ssd):
    ssd.smart.available = False
    ssd.smart.error = "sin permisos"
    report = analyze_disk(ssd)
    assert report.score is None
    assert report.grade == "Desconocido"
    assert report.verdict == "DESCONOCIDO"
    assert report.alert_level == "unknown"
    assert any(i.code == "smart_unavailable" for i in report.issues)


def test_crc_errors_do_not_claim_disk_failure(ssd):
    ssd.smart.attributes[199] = SmartAttribute(
        id=199, name="UDMA_CRC_Error_Count", value=200, worst=200, threshold=0, raw=5
    )
    report = analyze_disk(ssd)
    issue = next(i for i in report.warning_issues if i.code == "udma_crc_errors")
    assert "cable" in issue.message.lower()
    assert report.alert_level == "warning"


def test_critical_grade_capped_even_with_high_score(ssd):
    # Un fallo de auto-test (-25) deja la puntuación en 75, pero no debe
    # mostrarse como "Buena".
    from diskmon.models import SelfTestEntry

    ssd.smart.self_tests = [
        SelfTestEntry(type="Short offline", status="Completed: read failure", passed=False)
    ]
    report = analyze_disk(ssd)
    assert report.score == 75
    assert report.grade == "Precaución"
    assert report.verdict == "EN RIESGO"
    assert report.alert_level == "critical"


def test_attribute_failing_now_is_critical(ssd):
    ssd.smart.attributes[5].when_failed = "FAILING_NOW"
    report = analyze_disk(ssd)
    assert any(i.code == "attr_failing" for i in report.critical_issues)
    assert report.alert_level == "critical"


def test_low_ata_spare_uses_configured_threshold(ssd):
    from diskmon.models import SmartAttribute

    ssd.smart.attributes[180] = SmartAttribute(
        id=180, name="Unused_Rsvd_Blk_Cnt_Tot", value=25, worst=25, threshold=0, raw=25
    )
    report = analyze_disk(ssd, Thresholds(spare_warn=20))
    assert any(i.code == "spare_low" for i in report.warning_issues)


def test_wear_detected_by_attribute_name(ssd):
    from diskmon.models import SmartAttribute

    ssd.smart.attributes[999] = SmartAttribute(
        id=999, name="Remaining_Lifetime_Perc", value=10, worst=10, threshold=0, raw=10
    )
    report = analyze_disk(ssd)
    assert report.metrics["wear_percent"] == 90
    assert any(i.code == "wear_high" for i in report.warning_issues)
