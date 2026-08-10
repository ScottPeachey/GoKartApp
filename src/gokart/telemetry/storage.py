"""SQLite telemetry session storage."""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gokart.telemetry.channels import CHANNEL_NAMES, validate_sample_row


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    started_at: str
    ended_at: str | None
    source: str
    vehicle_name: str
    vehicle_version: str
    config_hash: str
    calibration_hash: str | None
    firmware_version: str
    driver_profile: str
    drive_mode: str
    scenario_name: str | None
    start_soc: float | None
    end_soc: float | None
    sample_count: int
    notes: str | None


class TelemetryStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or Path("telemetry/sessions.sqlite")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    source TEXT NOT NULL,
                    vehicle_name TEXT NOT NULL,
                    vehicle_version TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    calibration_hash TEXT,
                    firmware_version TEXT NOT NULL,
                    driver_profile TEXT NOT NULL,
                    drive_mode TEXT NOT NULL,
                    scenario_name TEXT,
                    start_soc REAL,
                    end_soc REAL,
                    sample_count INTEGER NOT NULL DEFAULT 0,
                    notes TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS samples (
                    session_id TEXT NOT NULL,
                    sample_index INTEGER NOT NULL,
                    time_s REAL NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (session_id, sample_index),
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sessions_config_hash
                ON sessions(config_hash)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_config_refs (
                    content_hash TEXT PRIMARY KEY
                )
                """
            )
            conn.commit()

    def register_config_hash(self, config_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO session_config_refs (content_hash) VALUES (?)",
                (config_hash,),
            )
            conn.commit()

    def create_session(
        self,
        *,
        session_id: str,
        started_at: str,
        source: str,
        vehicle_name: str,
        vehicle_version: str,
        config_hash: str,
        calibration_hash: str | None,
        firmware_version: str,
        driver_profile: str,
        drive_mode: str,
        scenario_name: str | None,
        start_soc: float | None,
        notes: str | None = None,
    ) -> None:
        self.register_config_hash(config_hash)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    id, started_at, source, vehicle_name, vehicle_version,
                    config_hash, calibration_hash, firmware_version,
                    driver_profile, drive_mode, scenario_name, start_soc, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    started_at,
                    source,
                    vehicle_name,
                    vehicle_version,
                    config_hash,
                    calibration_hash,
                    firmware_version,
                    driver_profile,
                    drive_mode,
                    scenario_name,
                    start_soc,
                    notes,
                ),
            )
            conn.commit()

    def append_samples(self, session_id: str, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        with self._connect() as conn:
            current = conn.execute(
                "SELECT sample_count FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if current is None:
                raise KeyError(f"Unknown session: {session_id}")
            start_index = int(current["sample_count"])
            conn.executemany(
                """
                INSERT INTO samples (session_id, sample_index, time_s, payload)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        session_id,
                        start_index + offset,
                        float(row["time_s"]),
                        json.dumps(validate_sample_row(row), sort_keys=True),
                    )
                    for offset, row in enumerate(rows)
                ],
            )
            conn.execute(
                "UPDATE sessions SET sample_count = sample_count + ? WHERE id = ?",
                (len(rows), session_id),
            )
            conn.commit()
            return len(rows)

    def close_session(
        self,
        session_id: str,
        *,
        ended_at: str,
        end_soc: float | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET ended_at = ?, end_soc = ? WHERE id = ?",
                (ended_at, end_soc, session_id),
            )
            conn.commit()

    def get_session(self, session_id: str) -> SessionInfo | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_info(row)

    def list_sessions(
        self,
        *,
        config_hash: str | None = None,
        vehicle_name: str | None = None,
        limit: int = 100,
    ) -> list[SessionInfo]:
        query = "SELECT * FROM sessions"
        clauses: list[str] = []
        params: list[Any] = []
        if config_hash is not None:
            clauses.append("config_hash = ?")
            params.append(config_hash)
        if vehicle_name is not None:
            clauses.append("vehicle_name = ?")
            params.append(vehicle_name)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_info(row) for row in rows]

    def load_samples(self, session_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [session_id]
        if limit is not None:
            query = """
                SELECT payload FROM samples
                WHERE session_id = ?
                ORDER BY sample_index DESC
                LIMIT ?
            """
            params.append(limit)
            with self._connect() as conn:
                rows = conn.execute(query, params).fetchall()
            samples = [json.loads(row["payload"]) for row in reversed(rows)]
            return samples

        query = """
            SELECT payload FROM samples
            WHERE session_id = ?
            ORDER BY sample_index
        """
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def export_csv(self, session_id: str, path: Path) -> None:
        samples = self.load_samples(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(CHANNEL_NAMES))
            writer.writeheader()
            for sample in samples:
                writer.writerow({name: sample.get(name, "") for name in CHANNEL_NAMES})

    @staticmethod
    def _row_to_info(row: sqlite3.Row) -> SessionInfo:
        return SessionInfo(
            session_id=row["id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            source=row["source"],
            vehicle_name=row["vehicle_name"],
            vehicle_version=row["vehicle_version"],
            config_hash=row["config_hash"],
            calibration_hash=row["calibration_hash"],
            firmware_version=row["firmware_version"],
            driver_profile=row["driver_profile"],
            drive_mode=row["drive_mode"],
            scenario_name=row["scenario_name"],
            start_soc=row["start_soc"],
            end_soc=row["end_soc"],
            sample_count=int(row["sample_count"]),
            notes=row["notes"],
        )
