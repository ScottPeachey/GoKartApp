"""Phase 3 safety state machine and fault detection tests."""

from __future__ import annotations

import random

import pytest

from gokart.config.schemas.limits import (
    DriveModeLimits,
    DriverProfileLimits,
    HardwareLimits,
    VehicleLimits,
)
from gokart.config.schemas.modes import DriveMode
from gokart.control.pipeline import ControlInputs, ControlParams, ControlState, control_step
from gokart.limits.resolver import DeratingFactors, EffectiveLimits, resolve_limits
from gokart.safety.faults import (
    FAULT_REGISTRY,
    SafetyConfig,
    SensorInputs,
    detect_faults,
)
from gokart.safety.state_machine import SafetyInputs, SafetyOutputs, SafetyTimers, safety_step
from gokart.safety.types import ContactorCommand, FaultId, FaultSeverity, SafetyState


def _advance_to_driving(config: SafetyConfig | None = None) -> tuple[SafetyState, SafetyOutputs]:
    config = config or SafetyConfig(self_test_duration_s=0.05, precharge_timeout_s=0.1)
    state = SafetyState.OFF
    timers = SafetyTimers()
    latched: set[FaultId] = set()
    outputs = SafetyOutputs(
        torque_permitted=False,
        regen_permitted=False,
        contactor_command=ContactorCommand.OPEN,
        derating=DeratingFactors(),
        active_faults=(),
        display_message_code=0,
        safety_state=SafetyState.OFF,
    )
    steps = [
        SafetyInputs(power_on_request=True),
        *[SafetyInputs() for _ in range(int(config.self_test_duration_s / 0.01) + 2)],
        SafetyInputs(arm_request=True, brake_pressed=True, driver_authenticated=True),
        *[
            SafetyInputs(throttle=0.0, brake_pressed=True)
            for _ in range(int(config.precharge_timeout_s / 0.01) + 1)
        ],
        SafetyInputs(throttle=0.2, brake_pressed=False),
        SafetyInputs(throttle=0.2, brake_pressed=False),
    ]
    for inputs in steps:
        state, outputs, timers, latched = safety_step(
            state, inputs, config, timers, latched_faults=latched, dt=0.01
        )
    return state, outputs


def test_happy_path_off_to_driving() -> None:
    state, outputs = _advance_to_driving()
    assert state == SafetyState.DRIVING
    assert outputs.torque_permitted
    assert outputs.contactor_command == ContactorCommand.CLOSE


@pytest.mark.parametrize(
    ("mutator", "expected_fault"),
    [
        (lambda s: SensorInputs(throttle_adc=50), FaultId.THROTTLE_OUT_OF_RANGE),
        (lambda s: SensorInputs(brake_adc=5000), FaultId.BRAKE_SENSOR_FAULT),
        (
            lambda s: SensorInputs(throttle=0.8, brake=0.8),
            FaultId.THROTTLE_BRAKE_SIMULTANEOUS,
        ),
        (lambda s: SensorInputs(wheel_speed_valid=False), FaultId.WHEEL_SPEED_FAULT),
        (lambda s: SensorInputs(can_vesc_alive=False), FaultId.CAN_TIMEOUT),
        (lambda s: SensorInputs(vesc_fault_active=True), FaultId.VESC_FAULT),
        (lambda s: SensorInputs(bms_fault_active=True), FaultId.BMS_FAULT),
        (lambda s: SensorInputs(pack_voltage_v=70.0), FaultId.PACK_OVERVOLTAGE),
        (lambda s: SensorInputs(pack_voltage_v=30.0), FaultId.PACK_UNDERVOLTAGE),
        (lambda s: SensorInputs(max_cell_voltage_v=4.0), FaultId.CELL_OVERVOLTAGE),
        (lambda s: SensorInputs(min_cell_voltage_v=2.0), FaultId.CELL_UNDERVOLTAGE),
        (lambda s: SensorInputs(motor_temp_c=130.0), FaultId.MOTOR_OVERTEMP),
        (lambda s: SensorInputs(motor_temp_c=110.0), FaultId.MOTOR_OVERTEMP_DERATE),
        (lambda s: SensorInputs(controller_temp_c=90.0), FaultId.CONTROLLER_OVERTEMP),
        (lambda s: SensorInputs(battery_temp_c=65.0), FaultId.BATTERY_OVERTEMP),
        (lambda s: SensorInputs(battery_temp_c=55.0), FaultId.BATTERY_OVERTEMP_DERATE),
        (lambda s: SensorInputs(speed_mps=25.0), FaultId.OVERSPEED),
        (lambda s: SensorInputs(watchdog_reset_detected=True), FaultId.WATCHDOG_RESET),
    ],
)
def test_detect_faults_signal_level(mutator, expected_fault) -> None:
    config = SafetyConfig()
    sensors = mutator(SensorInputs())
    faults = detect_faults(sensors, config)
    assert expected_fault in faults
    assert FAULT_REGISTRY[expected_fault].severity in {
        FaultSeverity.DERATE,
        FaultSeverity.FAULT,
        FaultSeverity.CRITICAL,
    }


def test_can_timeout_after_silence() -> None:
    config = SafetyConfig(can_timeout_s=0.5)
    sensors = SensorInputs(can_silence_s=0.6)
    assert FaultId.CAN_TIMEOUT in detect_faults(sensors, config)


def test_overspeed_uses_margin_above_configured_limit() -> None:
    config = SafetyConfig(max_speed_mps=12.5, overspeed_margin_mps=0.5)
    below = detect_faults(SensorInputs(speed_mps=12.7), config)
    above = detect_faults(SensorInputs(speed_mps=13.1), config)
    assert FaultId.OVERSPEED not in below
    assert FaultId.OVERSPEED in above


def test_precharge_failure_critical_shutdown() -> None:
    config = SafetyConfig(self_test_duration_s=0.05, precharge_timeout_s=1.0)
    state = SafetyState.READY
    timers = SafetyTimers()
    state, outputs, timers, _ = safety_step(
        state,
        SafetyInputs(arm_request=True, brake_pressed=True, driver_authenticated=True),
        config,
        timers,
        dt=0.01,
    )
    assert state == SafetyState.ARMED
    state, outputs, timers, _ = safety_step(
        state,
        SafetyInputs(precharge_feedback_ok=False, brake_pressed=True),
        config,
        timers,
        dt=0.01,
    )
    assert state == SafetyState.SAFE_SHUTDOWN
    assert FaultId.PRECHARGE_FAILURE in outputs.active_faults


def test_recoverable_fault_requires_ack() -> None:
    config = SafetyConfig()
    state = SafetyState.DRIVING
    timers = SafetyTimers()
    faults = {FaultId.THROTTLE_BRAKE_SIMULTANEOUS}
    state, outputs, timers, latched = safety_step(
        state,
        SafetyInputs(detected_faults=faults, throttle=0.8, brake_pressed=False),
        config,
        timers,
        dt=0.01,
    )
    assert state == SafetyState.FAULT
    assert not outputs.torque_permitted
    state, outputs, timers, latched = safety_step(
        state,
        SafetyInputs(detected_faults=set(), fault_ack_request=True),
        config,
        timers,
        latched_faults=latched,
        dt=0.01,
    )
    assert state == SafetyState.READY


def test_recover_from_safe_shutdown_after_critical_clears() -> None:
    config = SafetyConfig()
    state = SafetyState.SAFE_SHUTDOWN
    timers = SafetyTimers(shutdown_elapsed_s=0.1)
    latched = {FaultId.PACK_OVERVOLTAGE}
    state, outputs, timers, latched = safety_step(
        state,
        SafetyInputs(
            detected_faults=set(),
            fault_ack_request=True,
            power_cycle_event=True,
        ),
        config,
        timers,
        latched_faults=latched,
        dt=0.01,
    )
    assert state == SafetyState.OFF
    assert not latched


def test_latched_critical_persists_until_power_cycle() -> None:
    config = SafetyConfig()
    state = SafetyState.DRIVING
    timers = SafetyTimers()
    faults = {FaultId.BATTERY_OVERTEMP}
    state, _, timers, latched = safety_step(
        state,
        SafetyInputs(detected_faults=faults),
        config,
        timers,
        dt=0.01,
    )
    assert state == SafetyState.SAFE_SHUTDOWN
    assert FaultId.BATTERY_OVERTEMP in latched
    state, outputs, timers, latched = safety_step(
        SafetyState.OFF,
        SafetyInputs(detected_faults=set(), power_cycle_event=True),
        config,
        timers,
        latched_faults=latched,
        dt=0.01,
    )
    assert not latched


def test_torque_only_permitted_in_driving() -> None:
    config = SafetyConfig(self_test_duration_s=0.02, precharge_timeout_s=0.05)
    state = SafetyState.OFF
    timers = SafetyTimers()
    latched: set[FaultId] = set()
    rng = random.Random(42)
    for _ in range(200):
        inputs = SafetyInputs(
            power_on_request=rng.random() > 0.7,
            arm_request=rng.random() > 0.8,
            brake_pressed=rng.random() > 0.5,
            throttle=rng.random(),
            detected_faults=set(),
        )
        state, outputs, timers, latched = safety_step(
            state, inputs, config, timers, latched_faults=latched, dt=0.01
        )
        if state != SafetyState.DRIVING:
            assert not outputs.torque_permitted


def test_chill_traction_limit_vs_raw_off() -> None:
    limits = EffectiveLimits(
        max_speed_mps=20.0,
        max_motor_current_a=150.0,
        max_battery_current_a=150.0,
        max_regen_current_a=50.0,
        max_power_w=5000.0,
        max_motor_rpm=6000.0,
        max_accel_mps2=5.0,
        max_decel_mps2=10.0,
        max_gradient_rad=0.2,
    )
    chill_mode = DriveMode(name="Chill", traction_limiter="aggressive", throttle_ramp_per_s=1.0)
    raw_mode = DriveMode(name="RAW", traction_limiter="off", throttle_ramp_per_s=None)
    params_chill = ControlParams(
        mode=chill_mode,
        motor_peak_torque_nm=18.0,
        wheel_radius_m=0.127,
        gear_ratio=52 / 12,
        drivetrain_efficiency=0.95,
    )
    params_raw = ControlParams(
        mode=raw_mode,
        motor_peak_torque_nm=18.0,
        wheel_radius_m=0.127,
        gear_ratio=52 / 12,
        drivetrain_efficiency=0.95,
    )
    safety = SafetyOutputs(
        torque_permitted=True,
        regen_permitted=True,
        contactor_command=ContactorCommand.CLOSE,
        derating=DeratingFactors(),
        active_faults=(),
        display_message_code=0,
        safety_state=SafetyState.DRIVING,
    )
    inputs = ControlInputs(
        throttle=1.0,
        brake=0.0,
        speed_mps=0.0,
        motor_rpm=0.0,
        pack_voltage_v=48.0,
        mass_kg=193.0,
        grip_coefficient=0.2,
        gradient_rad=0.0,
    )
    chill_out = None
    raw_out = None
    state = ControlState()
    for _ in range(200):
        chill_out, state = control_step(inputs, limits, safety, state, params_chill, 0.01)
    state = ControlState()
    for _ in range(1):
        raw_out, state = control_step(inputs, limits, safety, state, params_raw, 0.01)
    assert chill_out is not None
    assert raw_out is not None
    assert chill_out.traction_limited
    assert not raw_out.traction_limited


def test_junior_profile_caps_track_mode() -> None:
    hardware = HardwareLimits(
        max_speed_mps=30.0,
        max_motor_current_a=200.0,
        max_battery_current_a=200.0,
        max_regen_current_a=80.0,
        max_power_w=10000.0,
        max_motor_rpm=8000.0,
        max_accel_mps2=8.0,
        max_decel_mps2=12.0,
        max_gradient_rad=0.3,
    )
    vehicle = VehicleLimits(max_speed_mps=25.0)
    track = DriveModeLimits(max_speed_mps=None)
    junior = DriverProfileLimits(max_speed_mps=8.33)
    owner = DriverProfileLimits(max_speed_mps=None)
    track_limits = resolve_limits(hardware, vehicle, track, junior)
    owner_limits = resolve_limits(hardware, vehicle, track, owner)
    assert track_limits.max_speed_mps == pytest.approx(8.33)
    assert owner_limits.max_speed_mps == pytest.approx(25.0)
