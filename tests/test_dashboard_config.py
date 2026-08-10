"""Dashboard configuration API tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gokart.config.store import data_root, load_vehicle
from gokart.dashboard.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    data = Path(__file__).resolve().parents[1] / "data"
    target = tmp_path / "data"
    shutil.copytree(data, target)
    monkeypatch.chdir(tmp_path)
    return TestClient(create_app())


def test_vehicle_list_includes_detail(client: TestClient) -> None:
    response = client.get("/api/config/vehicles")
    assert response.status_code == 200
    vehicles = response.json()
    assert vehicles[0]["detail"]["slots"]["motor"]["component_id"] == "v1_motor_5kw"


def test_vehicle_detail_endpoint(client: TestClient) -> None:
    response = client.get("/api/config/vehicles/Scott%20Kart%20V1/V1.0/detail")
    assert response.status_code == 200
    payload = response.json()
    assert payload["slots"]["motor"]["component_id"] == "v1_motor_5kw"
    assert payload["suggested_next_version"] == "V1.1"


def test_vehicle_detail_query_endpoint(client: TestClient) -> None:
    response = client.get(
        "/api/config/vehicle-detail",
        params={"vehicle_name": "Scott Kart V1", "vehicle_version": "V1.0"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["slots"]["battery"]["component_id"] == "v1_pack_48v_40ah"
    assert payload["drivetrain"]["motor_sprocket_teeth"] == 12


def test_vehicle_detail_post_endpoint(client: TestClient) -> None:
    response = client.post(
        "/api/config/vehicle-detail",
        json={"vehicle_name": "Scott Kart V1", "vehicle_version": "V1.0"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["slots"]["motor"]["component_id"] == "v1_motor_5kw"


def test_data_root_falls_back_to_bundled_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    root = data_root()
    assert (root / "vehicles").is_dir()
    assert load_vehicle("Scott Kart V1", "V1.0", root=root).name == "Scott Kart V1"


def test_list_motors(client: TestClient) -> None:
    response = client.get("/api/config/components/motor")
    assert response.status_code == 200
    motors = response.json()
    assert any(item["id"] == "v1_motor_5kw" for item in motors)


def test_component_detail_and_save(client: TestClient) -> None:
    detail = client.get("/api/config/components/motor/v1_motor_5kw")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["id"] == "v1_motor_5kw"

    template = client.get("/api/config/components/motor/template")
    assert template.status_code == 200
    new_data = template.json()
    new_data["id"] = "test_motor_dashboard"
    new_data["peak_power_w"] = 5200.0

    response = client.post(
        "/api/config/components/save",
        json={"data": new_data, "allow_overwrite": False},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "test_motor_dashboard"

    saved = client.get("/api/config/components/motor/test_motor_dashboard")
    assert saved.status_code == 200
    assert saved.json()["peak_power_w"] == 5200.0


def test_sim_reset(client: TestClient) -> None:
    response = client.post("/api/sim/reset")
    assert response.status_code == 200
    assert response.json()["status"] == "reset"


def test_save_vehicle_version(client: TestClient) -> None:
    detail = client.get("/api/config/vehicles/Scott%20Kart%20V1/V1.0/detail").json()
    response = client.post(
        "/api/config/vehicles/save",
        json={
            "base_name": "Scott Kart V1",
            "base_version": "V1.0",
            "new_version": "V1.1",
            "slots": {slot: detail["slots"][slot]["component_id"] for slot in detail["slots"]},
            "drivetrain": {
                **detail["drivetrain"],
                "motor_sprocket_teeth": 13,
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["version"] == "V1.1"


def test_effective_limits_endpoint(client: TestClient) -> None:
    response = client.get(
        "/api/config/effective-limits",
        params={
            "vehicle_name": "Scott Kart V1",
            "vehicle_version": "V1.0",
            "mode": "chill",
            "profile": "owner",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["max_speed_kmh"] == pytest.approx(20.0, abs=0.2)
    assert payload["binding_layer"] == "mode"


def test_drive_mode_detail_and_save(client: TestClient) -> None:
    detail = client.get("/api/config/modes/chill")
    assert detail.status_code == 200
    data = detail.json()
    data["limits"]["max_speed_mps"] = 6.944444444444445
    save = client.post(
        "/api/config/modes/save",
        json={"data": data, "allow_overwrite": True},
    )
    assert save.status_code == 200
    updated = client.get("/api/config/modes/chill").json()
    assert updated["limits"]["max_speed_mps"] == pytest.approx(6.944444444444445)
