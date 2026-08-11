"""Lap timing and track projection tests."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from gokart.sim.engine import run_simulation
from gokart.sim.runtime import RuntimeControls
from gokart.sim.scenarios import Scenario
from gokart.track.importer import import_geojson_track
from gokart.track.lap import (
    LapTimer,
    detect_sf_crossing,
    project_xy_to_track,
    segments_intersect,
    spawn_pose_on_track,
)
from gokart.track.model import TrackPoint
from gokart.track.queries import start_finish_segment

FIXTURES = Path(__file__).parent / "fixtures"
HAIRPIN = FIXTURES / "test-hairpin.geojson"


@pytest.fixture
def hairpin_track():
    return import_geojson_track(HAIRPIN, track_id="test-hairpin", fetch_elevation=False)


def test_project_xy_to_track_on_segment_midpoint() -> None:
    centerline = [
        TrackPoint(x=0, y=0, s=0, gradient_rad=0.01),
        TrackPoint(x=10, y=0, s=10, gradient_rad=0.02),
        TrackPoint(x=20, y=0, s=20, gradient_rad=0.03),
    ]
    projection = project_xy_to_track(centerline, 5.0, 1.0)
    assert projection.s_m == pytest.approx(5.0)
    assert projection.lateral_m == pytest.approx(1.0)
    assert projection.gradient_rad == pytest.approx(0.015)


def test_segments_intersect_crossing_lines() -> None:
    assert segments_intersect(0, 0, 10, 10, 0, 10, 10, 0)
    assert not segments_intersect(0, 0, 1, 0, 5, 5, 6, 5)


def test_detect_sf_crossing_requires_forward_motion(hairpin_track) -> None:
    sf = start_finish_segment(
        hairpin_track.centerline,
        hairpin_track.start_finish.s_m,
        hairpin_track.width_m,
    )
    x, y, _ = spawn_pose_on_track(hairpin_track)
    forward = (
        math.cos(sf["heading_rad"]),
        math.sin(sf["heading_rad"]),
    )
    prev_x = x - forward[0] * 2.0
    prev_y = y - forward[1] * 2.0
    assert detect_sf_crossing(
        prev_x,
        prev_y,
        x,
        y,
        sf,
        hairpin_track.direction,
        min_speed_mps=1.0,
        speed_mps=5.0,
    )
    assert not detect_sf_crossing(
        x,
        y,
        prev_x,
        prev_y,
        sf,
        hairpin_track.direction,
        min_speed_mps=1.0,
        speed_mps=5.0,
    )


def test_lap_timer_records_completed_lap(hairpin_track) -> None:
    timer = LapTimer(hairpin_track, min_arm_distance_m=0.0)
    x, y, heading = spawn_pose_on_track(hairpin_track)
    forward = (math.cos(heading), math.sin(heading))

    timer.update(0.0, x - forward[0] * 2.0, y - forward[1] * 2.0, 0.0)
    timer.update(0.6, x + forward[0] * 2.0, y + forward[1] * 2.0, 5.0)
    assert timer.state.lap_number == 1
    assert not timer.completed_laps

    timer._lap_start_time_s = 0.6
    timer._on_sf_cross(2.0)

    assert timer.completed_laps
    assert timer.completed_laps[0].lap_number == 1
    assert timer.completed_laps[0].lap_time_s == pytest.approx(1.4, abs=0.05)
    assert timer.state.lap_number == 2


def test_run_simulation_spawns_on_track(hairpin_track) -> None:
    root = Path(__file__).resolve().parents[1]
    scenario = Scenario(name="spawn_check", duration_s=0.05, auto_boot=False)
    result = run_simulation(
        "Scott Kart V1",
        "V1.0",
        scenario,
        data_root_path=root / "data",
        track=hairpin_track,
        keep_records=True,
    )
    spawn_x, spawn_y, _ = spawn_pose_on_track(hairpin_track)
    first = result.records[0].values
    assert first["position_x_m"] == pytest.approx(spawn_x, abs=0.01)
    assert first["position_y_m"] == pytest.approx(spawn_y, abs=0.01)
    assert "track_s_m" in first
    assert first["lap_number"] == pytest.approx(1.0)


def test_run_simulation_records_track_channels(hairpin_track) -> None:
    root = Path(__file__).resolve().parents[1]
    controls = RuntimeControls(free_mode=True, manual=True)
    controls.power_on_request = True
    scenario = Scenario(name="track_channels", duration_s=1e9, auto_boot=False)

    def on_tick(tick) -> None:
        if tick.time_s < 3.0:
            controls.brake = 1.0
            controls.arm_request = True
        elif tick.time_s < 6.0:
            controls.brake = 0.0
            controls.throttle = 0.8
        else:
            controls.stop_requested = True

    result = run_simulation(
        "Scott Kart V1",
        "V1.0",
        scenario,
        data_root_path=root / "data",
        controls=controls,
        on_tick=on_tick,
        track=hairpin_track,
    )
    driving = [record for record in result.records if record.values.get("safety_state") == "DRIVING"]
    assert driving
    sample = driving[-1].values
    assert sample["track_s_m"] >= 0.0
    assert "lap_time_s" in sample
