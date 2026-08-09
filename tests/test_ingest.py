"""Test firmware telemetry ingest from JSON lines."""

from __future__ import annotations

from pathlib import Path

from gokart.telemetry.ingest import ingest_file
from gokart.telemetry.storage import TelemetryStore


def test_ingest_file_creates_session(tmp_path: Path) -> None:
    log = tmp_path / "firmware.jsonl"
    log.write_text(
        "\n".join(
            [
                '{"time_s":0.0,"speed_mps":0.0,"throttle":0.0,"brake":0.0,"soc":1.0,"power_w":0.0}',
                '{"time_s":0.1,"speed_mps":1.2,"throttle":0.5,"brake":0.0,"soc":0.99,"power_w":120.0}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    store = TelemetryStore(tmp_path / "sessions.sqlite")
    session_id = ingest_file(log, store=store)
    session = store.get_session(session_id)
    assert session is not None
    samples = store.load_samples(session_id)
    assert len(samples) == 2
    assert samples[-1]["speed_mps"] == 1.2
