"""Session recorder — lifecycle wrapper around storage and optional live bus."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gokart.telemetry.bus import TelemetryBus
from gokart.telemetry.channels import validate_sample_row
from gokart.telemetry.storage import TelemetryStore

FIRMWARE_VERSION_SIM = "sim-0.1.0"
DEFAULT_LOG_EVERY_N = 2


@dataclass(frozen=True)
class SessionMetadata:
    vehicle_name: str
    vehicle_version: str
    config_hash: str
    driver_profile: str
    drive_mode: str
    scenario_name: str | None = None
    track_id: str | None = None
    calibration_hash: str | None = None
    source: str = "sim"
    firmware_version: str = FIRMWARE_VERSION_SIM
    notes: str | None = None


class SessionRecorder:
    def __init__(
        self,
        metadata: SessionMetadata,
        *,
        store: TelemetryStore | None = None,
        bus: TelemetryBus | None = None,
        start_soc: float | None = None,
        log_every_n: int = DEFAULT_LOG_EVERY_N,
    ) -> None:
        self.metadata = metadata
        self.store = store or TelemetryStore()
        self.bus = bus
        self.log_every_n = max(1, log_every_n)
        self.session_id = str(uuid.uuid4())
        self._started_at = datetime.now(UTC).isoformat()
        self._buffer: list[dict[str, Any]] = []
        self._tick_index = 0
        self._closed = False
        self.store.create_session(
            session_id=self.session_id,
            started_at=self._started_at,
            source=metadata.source,
            vehicle_name=metadata.vehicle_name,
            vehicle_version=metadata.vehicle_version,
            config_hash=metadata.config_hash,
            calibration_hash=metadata.calibration_hash,
            firmware_version=metadata.firmware_version,
            driver_profile=metadata.driver_profile,
            drive_mode=metadata.drive_mode,
            scenario_name=metadata.scenario_name,
            start_soc=start_soc,
            notes=metadata.notes,
            track_id=metadata.track_id,
        )

    @property
    def started_at(self) -> str:
        return self._started_at

    def record_tick(self, row: dict[str, Any]) -> None:
        if self._closed:
            return
        self._tick_index += 1
        sample = validate_sample_row(row)
        if self.bus is not None:
            self.bus.publish(sample)
        if self._tick_index % self.log_every_n != 0:
            return
        self._buffer.append(sample)
        if len(self._buffer) >= 50:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        self.store.append_samples(self.session_id, self._buffer)
        self._buffer.clear()

    def close(self, *, end_soc: float | None) -> None:
        if self._closed:
            return
        self.flush()
        self.store.close_session(
            self.session_id,
            ended_at=datetime.now(UTC).isoformat(),
            end_soc=end_soc,
        )
        self._closed = True

    def export_csv(self, path: Path) -> None:
        self.flush()
        self.store.export_csv(self.session_id, path)
