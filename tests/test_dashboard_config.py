"""Dashboard configuration API tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gokart.dashboard.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    data = Path(__file__).resolve().parents[1] / "data"
    target = tmp_path / "data"
    shutil.copytree(data, target)
    monkeypatch.chdir(tmp_path)
    return TestClient(create_app())


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


def test_list_motors(client: TestClient) -> None:
    response = client.get("/api/config/components/motor")
    assert response.status_code == 200
    motors = response.json()
    assert any(item["id"] == "v1_motor_5kw" for item in motors)


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
