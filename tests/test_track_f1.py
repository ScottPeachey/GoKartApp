"""F1 batch import tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from gokart.track.f1 import import_f1_circuits, list_f1_circuit_filenames


def test_list_f1_circuit_filenames() -> None:
    names = list_f1_circuit_filenames()
    assert len(names) >= 35
    assert "mc-1929.geojson" in names


def test_import_f1_circuits_from_fixture(tmp_path: Path) -> None:
    fixture = Path(__file__).resolve().parent / "fixtures" / "test-hairpin.geojson"
    payload = json.loads(fixture.read_text(encoding="utf-8"))

    def fake_list() -> list[str]:
        return ["test-hairpin.geojson"]

    def fake_download(filename: str, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / filename
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    data_root = tmp_path / "data"
    with patch("gokart.track.f1.list_f1_circuit_filenames", fake_list):
        with patch("gokart.track.f1.download_f1_geojson", fake_download):
            results = import_f1_circuits(
                fetch_elevation=False,
                allow_overwrite=True,
                cache_dir=tmp_path / "cache",
                root=data_root,
            )
    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].track_id == "test-hairpin"
    assert (data_root / "tracks" / "test-hairpin.json").exists()
