"""Rule-based autonomous driver tests."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from gokart.driver.agent import DriverConfig, RuleBasedDriver
from gokart.driver.racing_line import build_racing_line, point_at_s
from gokart.driver.speed_profile import build_speed_profile
from gokart.driver.track_progress import advance_track_progress
from gokart.track.importer import import_geojson_track

FIXTURES = Path(__file__).parent / "fixtures"
HAIRPIN = FIXTURES / "test-hairpin.geojson"


@pytest.fixture
def hairpin_track():
    return import_geojson_track(HAIRPIN, track_id="test-hairpin", fetch_elevation=False)


def test_racing_line_stays_inside_track(hairpin_track) -> None:
    line = build_racing_line(hairpin_track)
    assert len(line) == len(hairpin_track.centerline)
    half_width = hairpin_track.width_m * 0.45
    for point, center in zip(line, hairpin_track.centerline, strict=True):
        dist = ((point.x - center.x) ** 2 + (point.y - center.y) ** 2) ** 0.5
        assert dist <= half_width + 0.05


def test_speed_profile_respects_mode_cap(hairpin_track) -> None:
    line = build_racing_line(hairpin_track)
    profile = build_speed_profile(
        line,
        grip_coefficient=1.1,
        max_speed_mps=12.5,
        aggression=1.0,
    )
    speeds = [profile.target_speed_mps(s, hairpin_track.length_m) for s, _ in profile.samples]
    assert max(speeds) <= 12.5 + 1e-6
    assert min(speeds) >= 0.0


def test_pure_pursuit_outputs_are_bounded(hairpin_track) -> None:
    driver = RuleBasedDriver(
        hairpin_track,
        DriverConfig(
            grip_coefficient=1.1,
            max_speed_mps=12.5,
            wheelbase_m=1.04,
            aggression=1.0,
        ),
    )
    start = point_at_s(driver.racing_line, 0.0, hairpin_track.length_m)
    outputs = driver.step(
        x=start.x,
        y=start.y,
        heading_rad=0.0,
        speed_mps=5.0,
        soc=0.9,
    )
    assert 0.0 <= outputs.throttle <= 1.0
    assert 0.0 <= outputs.brake <= 1.0
    assert -1.0 <= outputs.steering <= 1.0
    assert outputs.target_speed_mps >= 0.0


def test_track_progress_advances_forward(hairpin_track) -> None:
    x, y, heading = hairpin_track.centerline[0].x, hairpin_track.centerline[0].y, 0.0
    s_prev = None
    for _ in range(200):
        s_prev, lateral, _ = advance_track_progress(
            hairpin_track,
            x=x,
            y=y,
            speed_mps=8.0,
            heading_rad=heading,
            prev_s_m=s_prev,
            dt=0.01,
        )
        x += math.cos(heading) * 0.08
        y += math.sin(heading) * 0.08
    assert s_prev is not None
    assert s_prev > 5.0
    assert abs(lateral) < hairpin_track.width_m


def test_project_to_line_returns_arc_length(hairpin_track) -> None:
    from gokart.driver.racing_line import project_to_line

    line = build_racing_line(hairpin_track)
    point = line[len(line) // 3]
    s_m, lateral = project_to_line(line, point.x, point.y)
    assert s_m == pytest.approx(point.s, abs=2.0)
    assert abs(lateral) < 0.5


def test_auto_drive_steering_and_battery_temp_bounded(hairpin_track) -> None:
    from gokart.sim.engine import run_simulation
    from gokart.sim.runtime import RuntimeControls
    from gokart.sim.scenarios import Scenario

    controls = RuntimeControls(auto_drive=True, target_laps=99, aggression=1.0)
    scenario = Scenario(
        name="auto_drive_thermal",
        duration_s=1e9,
        mode_name="default",
        profile_name="owner",
        auto_boot=True,
    )
    max_steer = 0.0
    max_batt = 25.0
    steer_samples = 0
    faults: set[str] = set()

    def on_tick(tick) -> None:
        nonlocal max_steer, max_batt, steer_samples
        values = tick.values
        if values.get("safety_state") == "DRIVING":
            max_steer = max(max_steer, abs(float(values.get("steering", 0.0))))
            max_batt = max(max_batt, float(values.get("battery_temp_c", 25.0)))
            if abs(float(values.get("steering", 0.0))) > 0.05:
                steer_samples += 1
            active = values.get("active_faults", "")
            if active:
                faults.update(str(active).split(","))
        if tick.time_s >= 30.0:
            controls.stop_requested = True

    run_simulation(
        "Scott Kart V1",
        "V1.0",
        scenario,
        controls=controls,
        track=hairpin_track,
        speedup=0.0,
        keep_records=False,
        on_tick=on_tick,
    )
    assert max_steer > 0.12
    assert steer_samples > 20
    assert max_batt < 55.0
    assert "BATTERY_OVERTEMP" not in faults


def test_auto_drive_reaches_driving_on_hairpin(hairpin_track) -> None:
    from gokart.sim.engine import run_simulation
    from gokart.sim.runtime import RuntimeControls
    from gokart.sim.scenarios import Scenario

    controls = RuntimeControls(
        auto_drive=True,
        target_laps=1,
        aggression=0.95,
    )
    scenario = Scenario(
        name="auto_drive_test",
        duration_s=1e9,
        mode_name="default",
        profile_name="owner",
        auto_boot=True,
    )
    seen_driving = False

    def on_tick(tick) -> None:
        nonlocal seen_driving
        if tick.values.get("safety_state") == "DRIVING":
            seen_driving = True
            controls.stop_requested = True

    run_simulation(
        "Scott Kart V1",
        "V1.0",
        scenario,
        controls=controls,
        track=hairpin_track,
        speedup=0.0,
        keep_records=False,
        on_tick=on_tick,
    )
    assert seen_driving
