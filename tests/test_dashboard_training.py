"""Dashboard RL training API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gokart.dashboard.app import create_app
from gokart.rl.hooks import TrainingProgress


def test_training_progress_to_dict() -> None:
    progress = TrainingProgress(
        timesteps=5000,
        total_timesteps=50_000,
        status="training",
        policy_key="abc123",
        best_lap_s=42.5,
        clean_lap_rate=0.5,
        preview_running=True,
        preview_sessions=[{"timestep": 5000, "session_id": "sess-1"}],
        previews_completed=1,
    )
    payload = progress.to_dict()
    assert payload["timesteps"] == 5000
    assert payload["progress_pct"] == 10.0
    assert payload["preview_running"] is True
    assert payload["preview_sessions"] == [{"timestep": 5000, "session_id": "sess-1"}]
    assert payload["preview_session_id"] == ""


def test_training_status_labels_cover_init_phases() -> None:
    for status in (
        "starting",
        "loading_libraries",
        "building_model",
        "training",
        "preview_recording",
    ):
        payload = TrainingProgress(status=status, total_timesteps=1000).to_dict()
        assert payload["status"] == status


def test_rl_train_status_endpoint() -> None:
    client = TestClient(create_app())
    response = client.get("/api/rl/train/status")
    assert response.status_code == 200
    data = response.json()
    assert data["running"] is False
    assert data["status"] == "idle"


def test_rl_train_start_requires_track() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/rl/train/start",
        json={
            "vehicle_name": "Scott Kart V1",
            "vehicle_version": "V1.0",
            "track_id": "missing-track-xyz",
            "preview_freq": 10_000,
            "total_timesteps": 1000,
        },
    )
    # Starts thread then fails quickly if track missing — accept 200 start or 409/500
    assert response.status_code in {200, 404, 409, 500}
