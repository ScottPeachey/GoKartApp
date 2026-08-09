"""Ingest firmware telemetry JSON lines into the session store."""

from __future__ import annotations

import json
import time
from pathlib import Path

from gokart.config.hashing import content_hash
from gokart.telemetry.channels import validate_sample_row
from gokart.telemetry.recorder import SessionMetadata, SessionRecorder
from gokart.telemetry.storage import TelemetryStore


def ingest_serial(
    port: str,
    *,
    baud: int = 115200,
    duration_s: float | None = None,
    store: TelemetryStore | None = None,
    vehicle_name: str = "Scott Kart V1",
    vehicle_version: str = "V1.0",
    driver_profile: str = "Owner",
    drive_mode: str = "Default",
    scenario_name: str = "firmware_mock",
) -> str:
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError("pyserial is required: uv add --dev pyserial") from exc

    telemetry_store = store or TelemetryStore()
    recorder = SessionRecorder(
        SessionMetadata(
            vehicle_name=vehicle_name,
            vehicle_version=vehicle_version,
            config_hash=content_hash({"vehicle": vehicle_name, "version": vehicle_version}),
            driver_profile=driver_profile,
            drive_mode=drive_mode,
            scenario_name=scenario_name,
            firmware_version="phase6-mock",
        ),
        store=telemetry_store,
        log_every_n=1,
    )

    deadline = time.monotonic() + duration_s if duration_s is not None else None
    last_soc = None
    with serial.Serial(port, baudrate=baud, timeout=1.0) as device:
        while deadline is None or time.monotonic() < deadline:
            raw = device.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            recorder.record_tick(validate_sample_row(payload))
            last_soc = payload.get("soc")

    recorder.close(end_soc=last_soc)
    return recorder.session_id


def ingest_file(path: Path, *, store: TelemetryStore | None = None) -> str:
    telemetry_store = store or TelemetryStore()
    recorder = SessionRecorder(
        SessionMetadata(
            vehicle_name="Scott Kart V1",
            vehicle_version="V1.0",
            config_hash="firmware",
            driver_profile="Owner",
            drive_mode="Default",
            scenario_name="firmware_import",
            firmware_version="phase6-mock",
        ),
        store=telemetry_store,
        log_every_n=1,
    )
    last_soc = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("{"):
            continue
        payload = json.loads(line)
        recorder.record_tick(validate_sample_row(payload))
        last_soc = payload.get("soc")
    recorder.close(end_soc=last_soc)
    return recorder.session_id
