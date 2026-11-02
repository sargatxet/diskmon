"""Histórico de análisis en SQLite.

Permite seguir la evolución de la salud de cada disco (temperatura, horas,
sectores reasignados, puntuación) y alimenta las gráficas del dashboard.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .models import ScanResult

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS scans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at  TEXT NOT NULL,
    hostname    TEXT,
    worst_alert TEXT
);

CREATE TABLE IF NOT EXISTS disk_reports (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id        INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    scanned_at     TEXT NOT NULL,
    device         TEXT NOT NULL,
    serial         TEXT,
    model          TEXT,
    kind           TEXT,
    score          INTEGER,
    grade          TEXT,
    verdict        TEXT,
    alert_level    TEXT,
    temperature_c  REAL,
    power_on_hours INTEGER,
    wear_percent   INTEGER,
    issues_json    TEXT,
    metrics_json   TEXT,
    report_json    TEXT
);

CREATE INDEX IF NOT EXISTS idx_reports_device ON disk_reports(device, scanned_at);
CREATE INDEX IF NOT EXISTS idx_reports_serial ON disk_reports(serial, scanned_at);
"""


class History:
    """Acceso al histórico local de diskmon."""

    def __init__(self, db_path: str | Path):
        self.path = Path(db_path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def save_scan(self, result: ScanResult) -> int:
        """Guarda una pasada completa. Devuelve el id del escaneo."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO scans (scanned_at, hostname, worst_alert) VALUES (?, ?, ?)",
                (result.started_at, result.hostname, result.worst_alert),
            )
            scan_id = int(cur.lastrowid)
            for report in result.reports:
                data = report.to_dict()
                conn.execute(
                    """
                    INSERT INTO disk_reports (
                        scan_id, scanned_at, device, serial, model, kind, score,
                        grade, verdict, alert_level, temperature_c, power_on_hours,
                        wear_percent, issues_json, metrics_json, report_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scan_id,
                        report.scanned_at,
                        report.disk.name,
                        report.disk.serial,
                        report.disk.model,
                        report.disk.kind,
                        report.score,
                        report.grade,
                        report.verdict,
                        report.alert_level,
                        report.metrics.get("temperature_c"),
                        report.metrics.get("power_on_hours"),
                        report.metrics.get("wear_percent"),
                        json.dumps(data["issues"], ensure_ascii=False),
                        json.dumps(data["metrics"], ensure_ascii=False),
                        json.dumps(data, ensure_ascii=False),
                    ),
                )
        return scan_id

    def query(
        self,
        device: Optional[str] = None,
        serial: Optional[str] = None,
        limit: int = 100,
        since: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Devuelve informes históricos, del más reciente al más antiguo."""
        limit = max(1, min(int(limit), 5000))
        where, params = [], []
        if device:
            where.append("device = ?")
            params.append(device)
        if serial:
            where.append("serial = ?")
            params.append(serial)
        if since:
            where.append("scanned_at >= ?")
            params.append(since)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"""
            SELECT id, scan_id, scanned_at, device, serial, model, kind, score,
                   grade, verdict, alert_level, temperature_c, power_on_hours,
                   wear_percent, issues_json, metrics_json
            FROM disk_reports {clause}
            ORDER BY scanned_at DESC, id DESC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (*params, limit)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["issues"] = json.loads(item.pop("issues_json") or "[]")
            item["metrics"] = json.loads(item.pop("metrics_json") or "{}")
            result.append(item)
        return result

    def devices(self) -> list[dict[str, Any]]:
        """Lista de discos vistos, con su último informe."""
        sql = """
            SELECT r.device, r.serial, r.model, r.kind, r.score, r.grade,
                   r.verdict, r.alert_level, r.scanned_at
            FROM disk_reports r
            JOIN (
                SELECT device, MAX(id) AS max_id FROM disk_reports GROUP BY device
            ) last ON r.id = last.max_id
            ORDER BY r.device
        """
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql).fetchall()]

    def latest(self, device: str) -> Optional[dict[str, Any]]:
        rows = self.query(device=device, limit=1)
        return rows[0] if rows else None

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            scans = conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
            reports = conn.execute("SELECT COUNT(*) FROM disk_reports").fetchone()[0]
            last = conn.execute("SELECT MAX(scanned_at) FROM scans").fetchone()[0]
        return {"scans": scans, "reports": reports, "last_scan": last, "db_path": str(self.path)}


def save_scan(result: ScanResult, db_path: str | Path) -> int:
    """Atajo para guardar un escaneo."""
    return History(db_path).save_scan(result)


__all__ = ["History", "save_scan"]
