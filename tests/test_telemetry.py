"""Phase 4 telemetry storage, bus, and dashboard tests."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gokart.dashboard.app import create_app
from gokart.sim.engine import run_simulation
from gokart.sim.scenarios import standing_start_30s
from gokart.telemetry.bus import TelemetryBus
from gokart.telemetry.channels import CHANNEL_NAMES, channel_schema
from gokart.telemetry.recorder import SessionMetadata, SessionRecorder
from gokart.telemetry.storage import TelemetryStore


@pytest.fixture
def temp_store(tmp_path: Path) -> TelemetryStore:
    return TelemetryStore(tmp_path / "sessions.sqlite")


def test_recorder_writes_metadata_and_samples(temp_store: TelemetryStore) -> None:
    recorder = SessionRecorder(
        SessionMetadata(
            vehicle_name="Scott Kart V1",
            vehicle_version="V1.0",
            config_hash="abc123",
            driver_profile="Owner",
            drive_mode="Default",
            scenario_name="standing_start_30s",
        ),
        store=temp_store,
        log_every_n=1,
    )
    for index in range(5):
        recorder.record_tick({"time_s": float(index), "speed_mps": float(index)})
    recorder.close(end_soc=0.9)
    session = temp_store.get_session(recorder.session_id)
    assert session is not None
    assert session.sample_count == 5
    assert session.vehicle_name == "Scott Kart V1"
    assert session.config_hash == "abc123"
    assert session.end_soc == pytest.approx(0.9)


def test_recorder_stores_episode_reward(temp_store: TelemetryStore) -> None:
    recorder = SessionRecorder(
        SessionMetadata(
            vehicle_name="Scott Kart V1",
            vehicle_version="V1.0",
            config_hash="abc123",
            driver_profile="Owner",
            drive_mode="Default",
            scenario_name="rl_episode_1000_1",
        ),
        store=temp_store,
        log_every_n=1,
    )
    recorder.record_tick({"time_s": 0.0, "speed_mps": 1.0})
    recorder.close(end_soc=0.9, episode_reward=-12.34)
    session = temp_store.get_session(recorder.session_id)
    assert session is not None
    assert session.episode_reward == pytest.approx(-12.34)
    listed = temp_store.list_sessions()
    assert listed[0].episode_reward == pytest.approx(-12.34)


def test_csv_export_matches_sqlite(temp_store: TelemetryStore, tmp_path: Path) -> None:
    recorder = SessionRecorder(
        SessionMetadata(
            vehicle_name="Scott Kart V1",
            vehicle_version="V1.0",
            config_hash="hash1",
            driver_profile="Owner",
            drive_mode="Default",
        ),
        store=temp_store,
        log_every_n=1,
    )
    rows = [
        {"time_s": 0.0, "speed_mps": 1.0, "drive_mode": "Default"},
        {"time_s": 0.01, "speed_mps": 2.0, "drive_mode": "Default"},
    ]
    for row in rows:
        recorder.record_tick(row)
    recorder.close(end_soc=0.8)
    csv_path = tmp_path / "session.csv"
    temp_store.export_csv(recorder.session_id, csv_path)
    sqlite_rows = temp_store.load_samples(recorder.session_id)
    assert len(sqlite_rows) == 2
    csv_text = csv_path.read_text(encoding="utf-8").strip().splitlines()
    assert csv_text[0] == ",".join(CHANNEL_NAMES)
    assert float(csv_text[1].split(",")[CHANNEL_NAMES.index("speed_mps")]) == pytest.approx(1.0)


def test_load_samples_limit_returns_latest_rows(temp_store: TelemetryStore) -> None:
    recorder = SessionRecorder(
        SessionMetadata(
            vehicle_name="Scott Kart V1",
            vehicle_version="V1.0",
            config_hash="limit-test",
            driver_profile="Owner",
            drive_mode="Default",
        ),
        store=temp_store,
        log_every_n=1,
    )
    for index in range(5):
        recorder.record_tick({"time_s": float(index), "speed_mps": float(index)})
    recorder.close(end_soc=1.0)

    latest = temp_store.load_samples(recorder.session_id, limit=2)
    assert len(latest) == 2
    assert latest[0]["speed_mps"] == pytest.approx(3.0)
    assert latest[1]["speed_mps"] == pytest.approx(4.0)


def test_load_samples_from_start_returns_earliest_rows(temp_store: TelemetryStore) -> None:
    recorder = SessionRecorder(
        SessionMetadata(
            vehicle_name="Scott Kart V1",
            vehicle_version="V1.0",
            config_hash="from-start-test",
            driver_profile="Owner",
            drive_mode="Default",
        ),
        store=temp_store,
        log_every_n=1,
    )
    for index in range(5):
        recorder.record_tick({"time_s": float(index), "speed_mps": float(index)})
    recorder.close(end_soc=1.0)

    earliest = temp_store.load_samples(recorder.session_id, limit=2, from_start=True)
    assert len(earliest) == 2
    assert earliest[0]["speed_mps"] == pytest.approx(0.0)
    assert earliest[1]["speed_mps"] == pytest.approx(1.0)


def test_delete_session_removes_samples_and_metadata(temp_store: TelemetryStore) -> None:
    recorder = SessionRecorder(
        SessionMetadata(
            vehicle_name="Scott Kart V1",
            vehicle_version="V1.0",
            config_hash="delete-test",
            driver_profile="Owner",
            drive_mode="Default",
        ),
        store=temp_store,
        log_every_n=1,
    )
    recorder.record_tick({"time_s": 0.0, "speed_mps": 1.0})
    recorder.close(end_soc=1.0)

    assert temp_store.delete_session(recorder.session_id) is True
    assert temp_store.get_session(recorder.session_id) is None
    assert temp_store.load_samples(recorder.session_id) == []


def test_delete_sessions_removes_multiple(temp_store: TelemetryStore) -> None:
    ids = []
    for index in range(3):
        recorder = SessionRecorder(
            SessionMetadata(
                vehicle_name="Scott Kart V1",
                vehicle_version="V1.0",
                config_hash=f"bulk-delete-{index}",
                driver_profile="Owner",
                drive_mode="Default",
            ),
            store=temp_store,
            log_every_n=1,
        )
        recorder.record_tick({"time_s": float(index), "speed_mps": 1.0})
        recorder.close(end_soc=1.0)
        ids.append(recorder.session_id)

    deleted = temp_store.delete_sessions(ids)
    assert deleted == ids
    for session_id in ids:
        assert temp_store.get_session(session_id) is None
        assert temp_store.load_samples(session_id) == []


def test_bus_overflow_does_not_block_producer() -> None:
    bus = TelemetryBus()
    sub_id = bus.subscribe(name="slow", maxsize=2)
    start = time.perf_counter()
    for index in range(500):
        bus.publish({"time_s": float(index)})
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5
    assert bus.dropped_count(sub_id) > 0


def test_session_query_filters_by_config_hash(temp_store: TelemetryStore) -> None:
    for config_hash in ("hash-a", "hash-b"):
        recorder = SessionRecorder(
            SessionMetadata(
                vehicle_name="Scott Kart V1",
                vehicle_version="V1.0",
                config_hash=config_hash,
                driver_profile="Owner",
                drive_mode="Default",
            ),
            store=temp_store,
            log_every_n=1,
        )
        recorder.record_tick({"time_s": 0.0, "speed_mps": 0.0})
        recorder.close(end_soc=1.0)
    filtered = temp_store.list_sessions(config_hash="hash-a")
    assert len(filtered) == 1
    assert filtered[0].config_hash == "hash-a"


def test_websocket_streams_schema_conformant_json(temp_store: TelemetryStore) -> None:
    bus = TelemetryBus()
    app = create_app(bus=bus, store=temp_store)
    client = TestClient(app)

    schema = client.get("/api/channels").json()
    assert schema == channel_schema()

    with client.websocket_connect("/ws/live") as websocket:
        bus.publish({"time_s": 0.0, "speed_mps": 5.0, "drive_mode": "Default"})
        message = websocket.receive_json()
        assert message["type"] == "sample"
        assert message["channels"] == channel_schema()
        assert message["data"]["speed_mps"] == pytest.approx(5.0)
        assert message["speed_kmh"] == pytest.approx(18.0)


def test_sim_run_with_recorder_integration(temp_store: TelemetryStore) -> None:
    root = Path(__file__).resolve().parents[1]
    bus = TelemetryBus()
    recorder = SessionRecorder(
        SessionMetadata(
            vehicle_name="Scott Kart V1",
            vehicle_version="V1.0",
            config_hash="integration",
            driver_profile="Owner",
            drive_mode="Default",
            scenario_name="standing_start_30s",
        ),
        store=temp_store,
        bus=bus,
        log_every_n=5,
    )
    sub_id = bus.subscribe(maxsize=16)
    run_simulation(
        "Scott Kart V1",
        "V1.0",
        standing_start_30s(),
        data_root_path=root / "data",
        recorder=recorder,
    )
    recorder.close(end_soc=0.5)
    session = temp_store.get_session(recorder.session_id)
    assert session is not None
    assert session.sample_count > 0
    assert bus.poll(sub_id) is not None
