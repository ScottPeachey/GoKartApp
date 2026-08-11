"""Track import and geometry tests."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from gokart.track.elevation import apply_elevations
from gokart.track.geometry import (
    KART_LENGTH_MAX_M,
    KART_LENGTH_MIN_M,
    XYPoint,
    build_track_points,
    close_polyline,
    compute_target_length_m,
    offset_boundaries,
    polyline_length,
    resample_polyline,
    scale_polyline,
)
from gokart.track.importer import TrackImportError, import_geojson_track
from gokart.track.projection import latlon_to_local_m, local_m_to_latlon
from gokart.track.store import load_track, save_track

FIXTURES = Path(__file__).parent / "fixtures"
HAIRPIN = FIXTURES / "test-hairpin.geojson"


def test_projection_round_trip() -> None:
    ref_lat, ref_lon = 43.738, 7.427
    lat, lon = 43.739, 7.428
    x, y = latlon_to_local_m(lat, lon, ref_lat=ref_lat, ref_lon=ref_lon)
    lat2, lon2 = local_m_to_latlon(x, y, ref_lat=ref_lat, ref_lon=ref_lon)
    assert lat2 == pytest.approx(lat, abs=1e-6)
    assert lon2 == pytest.approx(lon, abs=1e-6)


def test_compute_target_length_maps_f1_band() -> None:
    assert compute_target_length_m(3300.0) == pytest.approx(KART_LENGTH_MIN_M)
    assert compute_target_length_m(7000.0) == pytest.approx(KART_LENGTH_MAX_M)
    mid = compute_target_length_m(5150.0)
    assert KART_LENGTH_MIN_M < mid < KART_LENGTH_MAX_M


def test_close_polyline_closes_open_loop() -> None:
    points = [XYPoint(0, 0), XYPoint(10, 0), XYPoint(10, 10), XYPoint(0, 10)]
    closed = close_polyline(points)
    assert math.hypot(closed[0].x - closed[-1].x, closed[0].y - closed[-1].y) < 1.0


def test_resample_polyline_spacing() -> None:
    points = [XYPoint(0, 0), XYPoint(100, 0)]
    resampled = resample_polyline(points, spacing_m=10.0)
    assert len(resampled) == 11
    assert resampled[-1].x == pytest.approx(100.0)


def test_scale_polyline_changes_length() -> None:
    points = [XYPoint(0, 0), XYPoint(100, 0), XYPoint(100, 100)]
    scaled = scale_polyline(points, 0.5)
    assert polyline_length(scaled) == pytest.approx(polyline_length(points) * 0.5)


def test_offset_boundaries_inside_shorter_on_hairpin() -> None:
    # Semicircle arc: inside offset is clearly shorter than outside.
    radius = 50.0
    points = [
        XYPoint(radius * math.cos(angle), radius * math.sin(angle))
        for angle in [math.pi, math.pi * 0.75, math.pi * 0.5, math.pi * 0.25, 0.0]
    ]
    closed = close_polyline(points)
    inner, outer = offset_boundaries(closed, width_m=10.0)
    inner_len = polyline_length([XYPoint(p.x, p.y) for p in inner])
    outer_len = polyline_length([XYPoint(p.x, p.y) for p in outer])
    center_len = polyline_length(closed)
    assert inner_len < center_len < outer_len


def test_apply_elevations_scales_height() -> None:
    points = [XYPoint(0, 0), XYPoint(10, 0), XYPoint(20, 0)]
    elevated = apply_elevations(points, [100.0, 110.0, 120.0], scale=0.5)
    assert elevated[0].z == pytest.approx(0.0)
    assert elevated[-1].z == pytest.approx(10.0)


def test_build_track_points_has_arc_length_and_gradient() -> None:
    points = [XYPoint(0, 0, 0), XYPoint(10, 0, 0), XYPoint(20, 0, 0)]
    track_points = build_track_points(points)
    assert track_points[-1].s == pytest.approx(20.0)
    points_sloped = [XYPoint(0, 0, 0), XYPoint(10, 0, 1), XYPoint(20, 0, 2)]
    sloped = build_track_points(points_sloped)
    assert sloped[-1].gradient_rad > 0.0


def test_import_geojson_track_without_elevation(tmp_path: Path) -> None:
    track = import_geojson_track(
        HAIRPIN,
        track_id="test-hairpin",
        target_length_m=1200.0,
        width_m=10.0,
        fetch_elevation=False,
    )
    assert track.id == "test-hairpin"
    assert track.name == "Test Hairpin"
    assert track.target_length_m == pytest.approx(1200.0)
    assert track.length_m == pytest.approx(1200.0, rel=0.05)
    assert len(track.centerline) >= 100
    assert len(track.inner_boundary) == len(track.centerline)
    assert len(track.outer_boundary) == len(track.centerline)
    assert track.bbox.x_max > track.bbox.x_min
    assert track.start_finish.s_m == 0.0


def test_import_geojson_track_auto_length(tmp_path: Path) -> None:
    track = import_geojson_track(HAIRPIN, fetch_elevation=False)
    assert KART_LENGTH_MIN_M <= track.target_length_m <= KART_LENGTH_MAX_M


def test_import_geojson_track_closed_loop_continuity() -> None:
    track = import_geojson_track(HAIRPIN, fetch_elevation=False)
    first = track.centerline[0]
    last = track.centerline[-1]
    assert math.hypot(first.x - last.x, first.y - last.y) < 2.0


def test_save_and_load_track(tmp_path: Path) -> None:
    track = import_geojson_track(
        HAIRPIN,
        track_id="roundtrip",
        fetch_elevation=False,
    )
    path = save_track(track, root=tmp_path, allow_overwrite=True)
    assert path.exists()
    loaded = load_track("roundtrip", root=tmp_path)
    assert loaded.id == track.id
    assert loaded.length_m == pytest.approx(track.length_m)


def test_import_rejects_invalid_geojson(tmp_path: Path) -> None:
    bad = tmp_path / "bad.geojson"
    bad.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    with pytest.raises(TrackImportError):
        import_geojson_track(bad, fetch_elevation=False)
