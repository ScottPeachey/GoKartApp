"""Phase 2 physics and simulation tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from gokart.config.schemas.components import BatteryPack, TorqueMapPoint
from gokart.config.schemas.limits import HardwareLimits
from gokart.config.schemas.modes import DriveMode
from gokart.control.pipeline import (
    ControlInputs,
    ControlParams,
    ControlState,
    control_step,
)
from gokart.limits.resolver import DeratingFactors, EffectiveLimits
from gokart.physics.aero import aero_drag_force_n, rolling_resistance_force_n
from gokart.physics.battery import BatteryInputs, BatteryParams, BatteryState, step_battery
from gokart.physics.drivetrain import DrivetrainParams, motor_rpm_from_speed, speed_from_motor_rpm
from gokart.physics.motor import (
    MotorParams,
    available_torque_nm,
)
from gokart.physics.tyres import max_traction_force_n
from gokart.physics.vehicle import Environment, VehicleModel, VehicleStepInputs
from gokart.safety.state_machine import SafetyOutputs
from gokart.sim.engine import run_simulation
from gokart.sim.runtime import RuntimeControls
from gokart.sim.scenarios import Scenario, standing_start_30s
from gokart.units import kmh_to_mps, mps_to_kmh


def _motor_params() -> MotorParams:
    return MotorParams(
        peak_torque_nm=18.0,
        continuous_torque_nm=12.0,
        peak_power_w=5000.0,
        continuous_power_w=3500.0,
        peak_current_a=150.0,
        max_rpm=6000.0,
        nominal_voltage_v=48.0,
        torque_map=(
            TorqueMapPoint(rpm=0.0, torque_nm=18.0, efficiency=0.85),
            TorqueMapPoint(rpm=3000.0, torque_nm=16.0, efficiency=0.9),
            TorqueMapPoint(rpm=6000.0, torque_nm=8.0, efficiency=0.88),
        ),
    )


def test_motor_map_interpolation() -> None:
    params = _motor_params()
    assert available_torque_nm(params, 1500.0, 48.0) == pytest.approx(17.0, rel=0.01)
    assert available_torque_nm(params, 6000.0, 48.0) <= params.peak_torque_nm


def test_kinematic_consistency() -> None:
    params = DrivetrainParams(
        gear_ratio=52 / 12,
        chain_efficiency=0.97,
        axle_efficiency=0.98,
        wheel_radius_m=0.127,
    )
    speed = 10.0
    rpm = motor_rpm_from_speed(params, speed)
    assert speed_from_motor_rpm(params, rpm) == pytest.approx(speed, rel=1e-6)


def test_battery_sags_and_soc_decreases() -> None:
    battery = BatteryPack(
        id="b",
        manufacturer="t",
        model="m",
        nominal_voltage_v=48.0,
        max_voltage_v=58.0,
        min_voltage_v=40.0,
        series_cells=16,
        parallel_cells=1,
        capacity_ah=40.0,
        energy_wh=1920.0,
        internal_resistance_ohm=0.02,
        continuous_discharge_current_a=80.0,
        peak_discharge_current_a=150.0,
        max_charge_current_a=40.0,
        max_regen_current_a=40.0,
        hardware_limits=HardwareLimits(),
    )
    params = BatteryParams.from_component(battery)
    state = BatteryState(soc=0.8)
    state, out = step_battery(state, BatteryInputs(current_a=100.0), params, dt=1.0)
    assert out.pack_voltage_v < out.open_circuit_voltage_v
    assert state.soc < 0.8


def test_coast_down_decelerates() -> None:
    root = Path(__file__).resolve().parents[1]
    scenario = Scenario(
        name="coast",
        duration_s=60.0,
        inputs=[],
    )
    result = run_simulation(
        "Scott Kart V1",
        "V1.0",
        scenario,
        data_root_path=root / "data",
        initial_speed_mps=12.0,
    )
    assert result.records[0].values["speed_mps"] < 12.0
    assert result.records[-1].values["speed_mps"] == pytest.approx(0.0, abs=1.0)


def test_standing_start_reaches_plausible_top_speed() -> None:
    root = Path(__file__).resolve().parents[1]
    result = run_simulation(
        "Scott Kart V1",
        "V1.0",
        standing_start_30s(),
        data_root_path=root / "data",
    )
    max_speed_kmh = mps_to_kmh(max(r.values["speed_mps"] for r in result.records))
    assert max_speed_kmh == pytest.approx(30.0, abs=1.0)
    assert max_speed_kmh <= 45.0


def test_currents_within_vehicle_limits() -> None:
    root = Path(__file__).resolve().parents[1]
    result = run_simulation(
        "Scott Kart V1",
        "V1.0",
        standing_start_30s(),
        data_root_path=root / "data",
    )
    for record in result.records:
        assert record.values["motor_current_a"] <= 150.0 + 1e-6
        assert record.values["battery_current_a"] <= 150.0 + 1e-6


def test_deterministic_accelerated_simulation() -> None:
    root = Path(__file__).resolve().parents[1]
    kwargs = dict(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        scenario=standing_start_30s(),
        data_root_path=root / "data",
        speedup=0.0,
    )
    first = run_simulation(**kwargs)
    second = run_simulation(**kwargs)
    assert len(first.records) == len(second.records)
    for a, b in zip(first.records, second.records, strict=True):
        assert a.values["speed_mps"] == b.values["speed_mps"]
        assert a.values["soc"] == b.values["soc"]


def test_energy_conservation_discharge() -> None:
    root = Path(__file__).resolve().parents[1]
    result = run_simulation(
        "Scott Kart V1",
        "V1.0",
        standing_start_30s(),
        data_root_path=root / "data",
    )
    final_speed = result.records[-1].values["speed_mps"]
    delta_ke_j = 0.5 * 193.0 * final_speed**2
    energy_discharged_j = sum(record.values["power_w"] * 0.01 for record in result.records)
    assert energy_discharged_j >= delta_ke_j * 0.5


def test_traction_limiter_caps_force_on_low_mu() -> None:
    mode = DriveMode(name="Chill", traction_limiter="aggressive")
    limits = EffectiveLimits(
        max_speed_mps=50.0,
        max_motor_current_a=150.0,
        max_battery_current_a=150.0,
        max_regen_current_a=40.0,
        max_power_w=5000.0,
        max_motor_rpm=6000.0,
        max_accel_mps2=8.0,
        max_decel_mps2=10.0,
        max_gradient_rad=0.2,
    )
    params = ControlParams(
        mode=mode,
        motor_peak_torque_nm=18.0,
        wheel_radius_m=0.127,
        gear_ratio=52 / 12,
        drivetrain_efficiency=0.95,
    )
    outputs = None
    state = ControlState()
    for _ in range(200):
        outputs, state = control_step(
            ControlInputs(
                throttle=1.0,
                brake=0.0,
                speed_mps=0.0,
                motor_rpm=0.0,
                pack_voltage_v=48.0,
                mass_kg=193.0,
                grip_coefficient=0.2,
                gradient_rad=0.0,
            ),
            limits,
            SafetyOutputs(
                torque_permitted=True,
                regen_permitted=True,
                contactor_command=__import__(
                    "gokart.safety.types", fromlist=["ContactorCommand"]
                ).ContactorCommand.CLOSE,
                derating=DeratingFactors(),
                active_faults=(),
                display_message_code=0,
                safety_state=__import__(
                    "gokart.safety.types", fromlist=["SafetyState"]
                ).SafetyState.DRIVING,
            ),
            state,
            params,
            dt=0.01,
        )
    assert outputs is not None
    force_avail = max_traction_force_n(193.0, 0.2)
    wheel_torque = (
        outputs.motor_torque_request_nm * params.gear_ratio * params.drivetrain_efficiency
    )
    assert wheel_torque / params.wheel_radius_m <= force_avail * 0.98 + 1e-6
    assert outputs.traction_limited


def test_analytic_top_speed_approximation() -> None:
    mass = 193.0
    cd = 0.85
    area = 0.65
    crr = 0.015
    motor_peak_force = 18.0 * (52 / 12) * 0.95 / 0.127

    def net_force(v: float) -> float:
        return (
            motor_peak_force
            - aero_drag_force_n(v, cd, area)
            - rolling_resistance_force_n(mass, crr)
        )

    v = 0.0
    for _ in range(10_000):
        if net_force(v) <= 0:
            break
        v += 0.01
    root = Path(__file__).resolve().parents[1]
    result = run_simulation(
        "Scott Kart V1",
        "V1.0",
        standing_start_30s(),
        data_root_path=root / "data",
    )
    sim_top = max(r.values["speed_mps"] for r in result.records)
    assert sim_top == pytest.approx(min(v, kmh_to_mps(30.0)), rel=0.15)


def test_vehicle_step_kinematic_motor_rpm() -> None:
    root = Path(__file__).resolve().parents[1]
    model = VehicleModel.from_config(
        __import__("gokart.config.store", fromlist=["load_vehicle"]).load_vehicle(
            "Scott Kart V1", "V1.0", root=root / "data"
        ),
        data_root=root / "data",
    )
    state = model.initial_state()
    state.speed_mps = 8.0
    state, out = model.step(
        state,
        VehicleStepInputs(
            motor_torque_request_nm=5.0,
            regen_torque_request_nm=0.0,
            mechanical_brake=0.0,
            environment=Environment(),
        ),
        dt=0.01,
    )
    expected_rpm = motor_rpm_from_speed(model.drivetrain_params, 8.0)
    assert out.motor_rpm == pytest.approx(expected_rpm, rel=1e-6)


def test_manual_mode_coast_then_reaccelerates() -> None:
    root = Path(__file__).resolve().parents[1]
    controls = RuntimeControls(manual=True)
    scenario = Scenario(name="manual", duration_s=1e9, auto_boot=True)
    driving_seen = False
    speed_after_coast = 0.0

    def on_tick(tick) -> None:
        nonlocal driving_seen, speed_after_coast
        t = tick.time_s
        if t < 3.0:
            controls.throttle = 0.8
            controls.brake = 0.0
        elif t < 5.0:
            controls.throttle = 0.0
            controls.brake = 0.0
        elif t < 5.5:
            speed_after_coast = tick.values["speed_mps"]
            controls.throttle = 0.0
            controls.brake = 0.0
        elif t < 10.0:
            controls.throttle = 0.8
            controls.brake = 0.0
        else:
            controls.stop_requested = True

        if tick.values["safety_state"] == "DRIVING":
            driving_seen = True
        if driving_seen and t >= 3.0:
            assert tick.values["safety_state"] == "DRIVING"
            assert tick.values["torque_permitted"] == 1.0

    result = run_simulation(
        "Scott Kart V1",
        "V1.0",
        scenario,
        data_root_path=root / "data",
        controls=controls,
        on_tick=on_tick,
    )
    max_speed_after_reaccel = max(
        r.values["speed_mps"] for r in result.records if r.time_s >= 5.5
    )
    assert driving_seen
    assert max_speed_after_reaccel > speed_after_coast + 0.5


def test_steering_turns_at_speed() -> None:
    from gokart.physics.steering import step_steering

    out = step_steering(
        heading_rad=0.0,
        position_x_m=0.0,
        position_y_m=0.0,
        speed_mps=10.0,
        steering_input=1.0,
        wheelbase_m=1.1,
        dt=0.1,
    )
    assert out.heading_rad > 0.0
    assert out.position_y_m > 0.0
    assert out.steering_angle_rad == pytest.approx(0.488692, rel=1e-3)


def test_free_mode_records_steering_in_session() -> None:
    root = Path(__file__).resolve().parents[1]
    controls = RuntimeControls(free_mode=True, manual=True)
    controls.power_on_request = True
    scenario = Scenario(name="free_drive", duration_s=1e9, auto_boot=False)

    def on_tick(tick) -> None:
        t = tick.time_s
        if t < 3.0:
            controls.brake = 1.0
            controls.arm_request = True
        elif t < 7.0:
            controls.brake = 0.0
            controls.throttle = 0.8
            controls.steering = 0.8
        else:
            controls.stop_requested = True

    result = run_simulation(
        "Scott Kart V1",
        "V1.0",
        scenario,
        data_root_path=root / "data",
        controls=controls,
        on_tick=on_tick,
    )
    late = [r for r in result.records if r.time_s >= 5.0]
    assert any(abs(r.values["steering_angle_deg"]) > 1.0 for r in late)
    assert any(abs(r.values["position_y_m"]) > 0.5 for r in late)


def test_cornering_reduces_speed_vs_straight() -> None:
    root = Path(__file__).resolve().parents[1]
    scenario = Scenario(name="cornering", duration_s=1e9, auto_boot=True)

    def run_with_steering(steering: float) -> float:
        controls = RuntimeControls(manual=True)
        peak = 0.0

        def on_tick(tick) -> None:
            nonlocal peak
            t = tick.time_s
            if t < 8.0:
                controls.throttle = 1.0
                controls.brake = 0.0
                controls.steering = steering
            else:
                controls.stop_requested = True
            if tick.values["safety_state"] == "DRIVING" and t >= 4.0:
                peak = max(peak, tick.values["speed_mps"])

        run_simulation(
            "Scott Kart V1",
            "V1.0",
            scenario,
            data_root_path=root / "data",
            controls=controls,
            on_tick=on_tick,
        )
        return peak

    straight_peak = run_with_steering(0.0)
    turning_peak = run_with_steering(1.0)
    assert straight_peak > 5.0
    assert turning_peak < straight_peak * 0.85


def test_manual_mode_brake_does_not_disarm() -> None:
    root = Path(__file__).resolve().parents[1]
    controls = RuntimeControls(manual=True)
    scenario = Scenario(name="manual", duration_s=1e9, auto_boot=True)
    driving_seen = False

    def on_tick(tick) -> None:
        nonlocal driving_seen
        t = tick.time_s
        if t < 3.0:
            controls.throttle = 0.8
            controls.brake = 0.0
        elif t < 6.0:
            controls.throttle = 0.0
            controls.brake = 0.15
        else:
            controls.stop_requested = True

        if tick.values["safety_state"] == "DRIVING":
            driving_seen = True
        if driving_seen and t >= 3.0:
            assert tick.values["safety_state"] == "DRIVING"

    run_simulation(
        "Scott Kart V1",
        "V1.0",
        scenario,
        data_root_path=root / "data",
        controls=controls,
        on_tick=on_tick,
    )
    assert driving_seen
