"""Append-only configuration change audit log."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class AuditEntry:
    timestamp: str
    actor: str
    entity_type: str
    entity_id: str
    from_hash: str | None
    to_hash: str | None
    diff_summary: str
    validation_ok: bool
    validation_messages: str


class AuditLog:
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
                CREATE TABLE IF NOT EXISTS config_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    from_hash TEXT,
                    to_hash TEXT,
                    diff_summary TEXT NOT NULL,
                    validation_ok INTEGER NOT NULL,
                    validation_messages TEXT NOT NULL
                )
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

    def is_hash_referenced(self, content_hash: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM session_config_refs WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
            return row is not None

    def record(
        self,
        *,
        actor: str,
        entity_type: str,
        entity_id: str,
        from_hash: str | None,
        to_hash: str | None,
        diff_summary: str,
        validation_ok: bool,
        validation_messages: list[str],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO config_audit (
                    timestamp, actor, entity_type, entity_id,
                    from_hash, to_hash, diff_summary, validation_ok, validation_messages
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(UTC).isoformat(),
                    actor,
                    entity_type,
                    entity_id,
                    from_hash,
                    to_hash,
                    diff_summary,
                    int(validation_ok),
                    json.dumps(validation_messages),
                ),
            )
            conn.commit()

    def list_entries(self, limit: int = 100) -> list[AuditEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM config_audit ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            AuditEntry(
                timestamp=row["timestamp"],
                actor=row["actor"],
                entity_type=row["entity_type"],
                entity_id=row["entity_id"],
                from_hash=row["from_hash"],
                to_hash=row["to_hash"],
                diff_summary=row["diff_summary"],
                validation_ok=bool(row["validation_ok"]),
                validation_messages=row["validation_messages"],
            )
            for row in rows
        ]
