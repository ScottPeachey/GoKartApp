"""Tests for ICE engine, clutch, and Torini vehicles."""

from __future__ import annotations

from pathlib import Path

import pytest

from gokart.config.schemas import Clutch, Engine, HardwareLimits, TorqueMapPoint
from gokart.config.schemas.vehicle import ComponentRef, DrivetrainConfig, VehicleConfig
from gokart.config.store import load_component, load_vehicle
from gokart.config.validation import validate_vehicle_config
from gokart.physics.clutch import ClutchParams, engagement_fraction, step_clutch
from gokart.physics.drivetrain import DrivetrainParams
from gokart.physics.engine import (
    EngineInputs,
    EngineParams,
    EngineState,
    available_engine_torque_nm,
    step_ice_powertrain,
)
from gokart.physics.vehicle import VehicleModel, VehicleStepInputs, load_validated_vehicle_model
from gokart.physics.vehicle import Environment
from gokart.safety.faults import SafetyConfig, SensorInputs, detect_faults
from gokart.safety.types import FaultId
from gokart.sim.engine import _build_safety_config, thermal_tick_values
from gokart.sim.engine import run_simulation
from gokart.sim.scenarios import DriverInputPoint, Scenario


@pytest.fixture
def data_root() -> Path:
    return Path(__file__).resolve().parents[1] / "data"


def test_engine_torque_idle_braking_and_redline() -> None:
    params = EngineParams(
        idle_rpm=1800.0,
        redline_rpm=6100.0,
        peak_torque_nm=15.0,
        peak_power_w=7400.0,
        max_rpm=6100.0,
        engine_braking_nm=10.0,
        torque_map=(
            TorqueMapPoint(rpm=1800.0, torque_nm=4.0, efficiency=0.25),
            TorqueMapPoint(rpm=3400.0, torque_nm=15.0, efficiency=0.42),
            TorqueMapPoint(rpm=6100.0, torque_nm=0.0, efficiency=0.2),
        ),
    )
    assert available_engine_torque_nm(params, 3000.0, 0.0) == pytest.approx(-10.0)
    assert available_engine_torque_nm(params, 3400.0, 1.0) == pytest.approx(15.0)
    assert available_engine_torque_nm(params, 6200.0, 1.0) == pytest.approx(0.0)


def test_clutch_engagement_fraction() -> None:
    params = ClutchParams(engagement_rpm=2200.0, lock_rpm=2800.0, max_torque_nm=25.0)
    assert engagement_fraction(2000.0, params) == 0.0
    assert engagement_fraction(2500.0, params) == pytest.approx(0.5)
    assert engagement_fraction(3000.0, params) == 1.0


def test_clutch_transmits_torque_when_locked() -> None:
    params = ClutchParams(engagement_rpm=2200.0, lock_rpm=2800.0, max_torque_nm=25.0)
    out = step_clutch(15.0, 3000.0, params, coupled_rpm=2920.0)
    assert out.locked
    assert out.transmitted_torque_nm == pytest.approx(15.0)


def test_clutch_transmits_full_torque_when_engaged_at_speed() -> None:
    params = ClutchParams(engagement_rpm=2200.0, lock_rpm=2800.0, max_torque_nm=25.0)
    out = step_clutch(15.0, 5600.0, params, coupled_rpm=2400.0)
    assert not out.locked
    assert out.transmitted_torque_nm == pytest.approx(15.0)


def test_clutch_slips_at_launch_not_axle_locked() -> None:
    params = ClutchParams(engagement_rpm=2200.0, lock_rpm=2800.0, max_torque_nm=25.0)
    out = step_clutch(15.0, 3200.0, params, coupled_rpm=0.0)
    assert not out.locked
    assert out.transmitted_torque_nm == pytest.approx(15.0)
    assert out.slip_rpm == pytest.approx(3200.0)


def test_clutch_unlocked_below_engagement() -> None:
    params = ClutchParams(engagement_rpm=2200.0, lock_rpm=2800.0, max_torque_nm=25.0)
    out = step_clutch(15.0, 1800.0, params)
    assert not out.locked
    assert out.transmitted_torque_nm == 0.0


def test_clutch_transmits_near_lock_with_small_slip() -> None:
    """Near lock RPM, small engine/axle slip must not collapse to the 8% capacity floor."""
    params = ClutchParams(engagement_rpm=3500.0, lock_rpm=5200.0, max_torque_nm=30.0)
    out = step_clutch(11.4, 5193.0, params, coupled_rpm=5150.0)
    assert not out.locked
    assert out.transmitted_torque_nm == pytest.approx(11.4)


def test_ice_powertrain_revs_and_moves(data_root: Path) -> None:
    model = load_validated_vehicle_model("Torini Clubmaxx 210", "V1.0", data_root=data_root)
    state = model.initial_state()
    dt = 0.01
    for _ in range(1500):
        state, out = model.step(
            state,
            VehicleStepInputs(
                motor_torque_request_nm=20.0,
                regen_torque_request_nm=0.0,
                mechanical_brake=0.0,
                environment=Environment(),
                throttle=1.0,
            ),
            dt,
        )
    assert out.position_m > 1.0
    assert out.engine_rpm >= 1800.0


def test_ice_launch_accelerates_smoothly(data_root: Path) -> None:
    """No rev-limiter cycle: engine rpm should not oscillate wildly at launch."""
    model = load_validated_vehicle_model("Torini Clubmaxx 210", "V1.0", data_root=data_root)
    state = model.initial_state()
    dt = 0.01
    rpms: list[float] = []
    speeds: list[float] = []
    for _ in range(800):
        state, out = model.step(
            state,
            VehicleStepInputs(
                motor_torque_request_nm=20.0,
                regen_torque_request_nm=0.0,
                mechanical_brake=0.0,
                environment=Environment(),
                throttle=1.0,
            ),
            dt,
        )
        rpms.append(out.engine_rpm)
        speeds.append(out.speed_mps)

    rpm_swings = sum(
        1
        for left, right in zip(rpms[1:], rpms[:-1], strict=False)
        if (right - left) > 400.0 and left > 2500.0
    )
    assert rpm_swings < 5, f"engine rpm oscillated {rpm_swings} times during launch"
    assert speeds[-1] > speeds[0] + 0.5
    assert max(speeds) > 2.0


def test_ice_rpm_follows_wheel_speed_under_corner_scrub(data_root: Path) -> None:
    """When corner scrub slows the kart, engaged-clutch engine RPM should drop with the axle."""
    from gokart.physics.drivetrain import motor_rpm_from_speed

    model = load_validated_vehicle_model("Rotax 125", "V1.0", data_root=data_root)
    state = model.initial_state()
    dt = 0.01
    for _ in range(2500):
        state, out = model.step(
            state,
            VehicleStepInputs(
                motor_torque_request_nm=20.0,
                regen_torque_request_nm=0.0,
                mechanical_brake=0.0,
                environment=Environment(),
                throttle=1.0,
            ),
            dt,
        )

    straight_rpm = out.engine_rpm
    straight_speed = out.speed_mps
    for _ in range(1500):
        state, out = model.step(
            state,
            VehicleStepInputs(
                motor_torque_request_nm=20.0,
                regen_torque_request_nm=0.0,
                mechanical_brake=0.0,
                environment=Environment(),
                throttle=1.0,
                steering=0.35,
            ),
            dt,
        )

    coupled = motor_rpm_from_speed(model.drivetrain_params, out.speed_mps)
    assert model.clutch_params is not None
    crawl_slip = 150.0
    crawl_floor = model.clutch_params.engagement_rpm * 0.35
    if coupled >= crawl_floor:
        expected_rpm = coupled
    else:
        expected_rpm = max(coupled, model.clutch_params.engagement_rpm + crawl_slip)
    assert out.speed_mps < straight_speed * 0.5
    assert out.engine_rpm < straight_rpm * 0.5
    assert out.engine_rpm == pytest.approx(expected_rpm, rel=0.08, abs=350.0)


def test_torini_vehicles_validate(data_root: Path) -> None:
    for name in ("Torini Clubmaxx 210", "Torini Supermaxx 250"):
        vehicle = load_vehicle(name, "V1.0", root=data_root)
        result = validate_vehicle_config(vehicle, data_root=data_root)
        assert result.ok, [v.message for v in result.violations]


def test_rotax_125_validates_with_restrictor_default(data_root: Path) -> None:
    vehicle = load_vehicle("Rotax 125", "V1.0", root=data_root)
    result = validate_vehicle_config(vehicle, data_root=data_root)
    assert result.ok, [v.message for v in result.violations]
    assert vehicle.engine is not None
    assert vehicle.engine.component_id == "rotax_125_max_evo_r235"


def test_rotax_restrictor_is_weaker_than_unrestricted(data_root: Path) -> None:
    restricted = load_component("engine", "rotax_125_max_evo_r235", root=data_root)
    unrestricted = load_component("engine", "rotax_125_max_evo", root=data_root)
    assert restricted.peak_torque_nm < unrestricted.peak_torque_nm
    assert restricted.peak_power_w < unrestricted.peak_power_w


def test_rotax_125_moves(data_root: Path) -> None:
    model = load_validated_vehicle_model("Rotax 125", "V1.0", data_root=data_root)
    state = model.initial_state()
    dt = 0.01
    for _ in range(1500):
        state, out = model.step(
            state,
            VehicleStepInputs(
                motor_torque_request_nm=20.0,
                regen_torque_request_nm=0.0,
                mechanical_brake=0.0,
                environment=Environment(),
                throttle=1.0,
            ),
            dt,
        )
    assert out.position_m > 1.0
    assert out.engine_rpm >= 1600.0


def test_ice_vehicle_missing_engine_rejected() -> None:
    with pytest.raises(ValueError, match="engine and clutch"):
        VehicleConfig(
            name="Bad ICE",
            version="V1.0",
            powertrain_type="ice",
            dry_mass_kg=75.0,
            battery_mass_kg=0.0,
            driver_mass_kg=80.0,
            max_vehicle_mass_kg=155.0,
            wheelbase_m=1.0,
            front_track_m=0.9,
            rear_track_m=0.95,
            cg_height_m=0.28,
            cg_longitudinal_m=0.52,
            drag_coefficient=0.85,
            frontal_area_m2=0.65,
            rolling_resistance_coefficient=0.015,
            wheel_radius_m=0.127,
            clutch=ComponentRef(component_id="noram_tc_gel19219", content_hash="a" * 64),
            drivetrain=DrivetrainConfig(motor_sprocket_teeth=19, axle_sprocket_teeth=32),
            limits=HardwareLimits(max_speed_mps=14.0),
        )


def test_ice_auto_boot_reaches_driving(data_root: Path) -> None:
    scenario = Scenario(
        name="ice_boot",
        duration_s=2.0,
        inputs=[DriverInputPoint(time_s=0.0, throttle=1.0, brake=0.0)],
        auto_boot=True,
    )
    result = run_simulation(
        "Torini Clubmaxx 210",
        "V1.0",
        scenario,
        data_root_path=data_root,
        dt_s=0.01,
    )
    driving_ticks = [r for r in result.records if r.values.get("safety_state") == "DRIVING"]
    assert driving_ticks
    assert not any("PRECHARGE_FAILURE" in (r.values.get("active_faults") or "") for r in result.records)


def test_scott_kart_v1_ev_regression(data_root: Path) -> None:
    result = validate_vehicle_config(
        load_vehicle("Scott Kart V1", "V1.0", root=data_root),
        data_root=data_root,
    )
    assert result.ok
    model = load_validated_vehicle_model("Scott Kart V1", "V1.0", data_root=data_root)
    assert not model.is_ice


def test_ice_engine_overtemp_uses_engine_faults_only() -> None:
    config = SafetyConfig(
        ice_powertrain=True,
        engine_temp_fault_c=120.0,
        engine_temp_derate_c=100.0,
    )
    assert FaultId.ENGINE_OVERTEMP in detect_faults(
        SensorInputs(engine_temp_c=125.0),
        config,
    )
    assert FaultId.ENGINE_OVERTEMP_DERATE in detect_faults(
        SensorInputs(engine_temp_c=105.0),
        config,
    )
    faults = detect_faults(SensorInputs(engine_temp_c=125.0, motor_temp_c=200.0), config)
    assert FaultId.MOTOR_OVERTEMP not in faults
    assert FaultId.CONTROLLER_OVERTEMP not in faults


def test_ice_safety_config_uses_engine_thresholds(data_root: Path) -> None:
    model = load_validated_vehicle_model("Torini Clubmaxx 210", "V1.0", data_root=data_root)
    limits = model.config.limits
    safety = _build_safety_config(model, limits, data_root)
    assert safety.ice_powertrain
    assert safety.engine_temp_fault_c == pytest.approx(120.0)
    assert safety.engine_temp_derate_c == pytest.approx(100.0)


def test_ice_thermal_tick_values_exclude_controller_channels() -> None:
    config = SafetyConfig(
        ice_powertrain=True,
        engine_temp_fault_c=120.0,
        engine_temp_derate_c=100.0,
    )
    values = thermal_tick_values(
        is_ice=True,
        powertrain_type="ice",
        safety_config=config,
        motor_temp_c=88.0,
        engine_temp_c=88.0,
        battery_temp_c=30.0,
    )
    assert values["powertrain_type"] == "ice"
    assert values["engine_temp_c"] == pytest.approx(88.0)
    assert values["engine_temp_fault_c"] == pytest.approx(120.0)
    assert "controller_temp_c" not in values
    assert "motor_temp_c" not in values
