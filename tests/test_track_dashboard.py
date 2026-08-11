"""Dashboard track API tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gokart.dashboard.app import create_app
from gokart.track.importer import import_geojson_track
from gokart.track.store import save_track


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    data = Path(__file__).resolve().parents[1] / "data"
    target = tmp_path / "data"
    shutil.copytree(data, target)
    fixture = Path(__file__).resolve().parent / "fixtures" / "test-hairpin.geojson"
    track = import_geojson_track(fixture, track_id="test-hairpin", fetch_elevation=False)
    save_track(track, root=target, allow_overwrite=True)
    monkeypatch.chdir(tmp_path)
    return TestClient(create_app())


def test_tracks_list_api(client: TestClient) -> None:
    response = client.get("/api/tracks")
    assert response.status_code == 200
    tracks = response.json()
    assert any(item["id"] == "test-hairpin" for item in tracks)


def test_track_detail_api(client: TestClient) -> None:
    response = client.get("/api/tracks/test-hairpin")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "test-hairpin"
    assert payload["centerline"]
    assert payload["start_finish_line"]["x1"] is not None


def test_save_start_finish_api(client: TestClient) -> None:
    response = client.post(
        "/api/tracks/test-hairpin/start-finish",
        json={"s_m": 42.0},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["start_finish"]["s_m"] == pytest.approx(42.0)

    detail = client.get("/api/tracks/test-hairpin")
    assert detail.json()["start_finish"]["s_m"] == pytest.approx(42.0)


def test_track_detail_not_found(client: TestClient) -> None:
    response = client.get("/api/tracks/missing-track")
    assert response.status_code == 404
