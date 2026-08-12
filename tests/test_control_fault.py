"""Control behaviour during safety faults."""

from __future__ import annotations

import pytest

from gokart.config.schemas.modes import DriveMode
from gokart.control.pipeline import ControlInputs, ControlParams, ControlState, control_step
from gokart.limits.resolver import DeratingFactors, EffectiveLimits
from gokart.safety.state_machine import SafetyOutputs
from gokart.safety.types import ContactorCommand, SafetyState


def _limits() -> EffectiveLimits:
    return EffectiveLimits(
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


def _params() -> ControlParams:
    return ControlParams(
        mode=DriveMode(name="default", throttle_ramp_per_s=2.0),
        motor_peak_torque_nm=18.0,
        wheel_radius_m=0.127,
        gear_ratio=52 / 12,
        drivetrain_efficiency=0.95,
    )


def test_fault_cuts_torque_regen_and_throttle_filter() -> None:
    safety = SafetyOutputs(
        torque_permitted=False,
        regen_permitted=False,
        contactor_command=ContactorCommand.OPEN,
        derating=DeratingFactors(),
        active_faults=(),
        display_message_code=0,
        safety_state=SafetyState.FAULT,
    )
    state = ControlState(filtered_throttle=0.85)
    outputs, new_state = control_step(
        ControlInputs(
            throttle=1.0,
            brake=0.6,
            speed_mps=8.0,
            motor_rpm=1200.0,
            pack_voltage_v=48.0,
            mass_kg=193.0,
            grip_coefficient=1.1,
            gradient_rad=0.0,
        ),
        _limits(),
        safety,
        state,
        _params(),
        0.01,
    )
    assert outputs.motor_torque_request_nm == 0.0
    assert outputs.regen_torque_request_nm == 0.0
    assert outputs.mechanical_brake == pytest.approx(0.6)
    assert outputs.filtered_throttle == 0.0
    assert new_state.filtered_throttle == 0.0
