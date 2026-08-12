"""Control pipeline types and step function."""

from __future__ import annotations

from dataclasses import dataclass

from gokart.config.schemas.modes import DriveMode
from gokart.limits.resolver import EffectiveLimits
from gokart.safety.state_machine import SafetyOutputs

__all__ = [
    "ControlInputs",
    "ControlOutputs",
    "ControlParams",
    "ControlState",
    "SafetyOutputs",
    "control_step",
]


@dataclass(frozen=True)
class ControlInputs:
    throttle: float
    brake: float
    speed_mps: float
    motor_rpm: float
    pack_voltage_v: float
    mass_kg: float
    grip_coefficient: float
    gradient_rad: float
    rear_traction_limit_n: float | None = None


@dataclass
class ControlState:
    filtered_throttle: float = 0.0
    traction_scale: float = 1.0


@dataclass(frozen=True)
class ControlParams:
    mode: DriveMode
    motor_peak_torque_nm: float
    wheel_radius_m: float
    gear_ratio: float
    drivetrain_efficiency: float
    motor_efficiency: float = 0.9


@dataclass(frozen=True)
class ControlOutputs:
    motor_torque_request_nm: float
    regen_torque_request_nm: float
    mechanical_brake: float
    filtered_throttle: float
    traction_limited: bool


def _apply_throttle_curve(throttle: float, curve: str) -> float:
    t = max(0.0, min(1.0, throttle))
    if curve == "progressive":
        return t * t
    if curve == "aggressive":
        return t**0.5
    return t


def _traction_scale_threshold(policy: str) -> float:
    return {
        "off": 0.0,
        "gentle": 0.85,
        "moderate": 0.92,
        "aggressive": 0.98,
    }.get(policy, 0.92)


def _estimate_motor_current(
    torque_nm: float,
    motor_rpm: float,
    voltage_v: float,
    efficiency: float,
) -> float:
    from gokart.units import rpm_to_rads

    omega = rpm_to_rads(max(motor_rpm, 1.0))
    mechanical = abs(torque_nm) * omega
    electrical = mechanical / max(efficiency, 0.05)
    if voltage_v <= 1.0:
        return 0.0
    return electrical / voltage_v


def control_step(
    inputs: ControlInputs,
    limits: EffectiveLimits,
    safety: SafetyOutputs,
    state: ControlState,
    params: ControlParams,
    dt: float,
) -> tuple[ControlOutputs, ControlState]:
    throttle = max(0.0, min(1.0, inputs.throttle))
    brake = max(0.0, min(1.0, inputs.brake))

    if params.mode.throttle_ramp_per_s is None:
        filtered = throttle
    else:
        delta = params.mode.throttle_ramp_per_s * dt
        throttle_delta = throttle - state.filtered_throttle
        filtered = state.filtered_throttle + max(-delta, min(throttle_delta, delta))

    shaped = _apply_throttle_curve(filtered, params.mode.throttle_curve)
    traction_limited = False
    traction_scale = 1.0

    if not safety.torque_permitted:
        return (
            ControlOutputs(
                motor_torque_request_nm=0.0,
                regen_torque_request_nm=0.0,
                mechanical_brake=brake,
                filtered_throttle=0.0,
                traction_limited=False,
            ),
            ControlState(filtered_throttle=0.0, traction_scale=1.0),
        )

    motor_torque = shaped * params.motor_peak_torque_nm

    if params.mode.traction_limiter != "off" and inputs.speed_mps >= 0:
        from gokart.physics.tyres import max_traction_force_n

        wheel_torque = motor_torque * params.gear_ratio * params.drivetrain_efficiency
        force_req = wheel_torque / params.wheel_radius_m if params.wheel_radius_m > 0 else 0.0
        force_avail = inputs.rear_traction_limit_n
        if force_avail is None:
            force_avail = max_traction_force_n(
                inputs.mass_kg,
                inputs.grip_coefficient,
                inputs.gradient_rad,
            )
        threshold = _traction_scale_threshold(params.mode.traction_limiter)
        if force_avail > 0 and force_req > force_avail * threshold:
            traction_scale = (force_avail * threshold) / force_req
            motor_torque *= traction_scale
            traction_limited = True

    governor_brake = 0.0
    if inputs.speed_mps > 0 and limits.max_speed_mps > 0:
        if inputs.speed_mps >= limits.max_speed_mps:
            motor_torque = 0.0
            overspeed_mps = inputs.speed_mps - limits.max_speed_mps
            governor_brake = min(1.0, 0.2 + overspeed_mps * 0.35)
        else:
            taper_start = limits.max_speed_mps * 0.85
            if inputs.speed_mps > taper_start:
                span = limits.max_speed_mps - taper_start
                if span > 0:
                    taper = max(0.0, (limits.max_speed_mps - inputs.speed_mps) / span)
                    motor_torque *= taper

    motor_torque = min(motor_torque, params.motor_peak_torque_nm)
    if limits.max_power_w > 0 and inputs.pack_voltage_v > 1.0:
        from gokart.units import rpm_to_rads

        omega = rpm_to_rads(max(inputs.motor_rpm, 1.0))
        if omega > 0:
            power_limited_torque = limits.max_power_w / omega
            motor_torque = min(motor_torque, power_limited_torque)

    est_current = _estimate_motor_current(
        motor_torque, inputs.motor_rpm, inputs.pack_voltage_v, params.motor_efficiency
    )
    if limits.max_motor_current_a > 0 and est_current > limits.max_motor_current_a:
        motor_torque *= limits.max_motor_current_a / est_current

    regen_torque = 0.0
    mechanical_brake = max(brake, governor_brake)
    if safety.regen_permitted and mechanical_brake > 0:
        regen_torque = mechanical_brake * params.motor_peak_torque_nm * params.mode.regen_strength
        if limits.max_regen_current_a > 0 and inputs.pack_voltage_v > 1.0:
            from gokart.units import rpm_to_rads

            omega = rpm_to_rads(max(inputs.motor_rpm, 1.0))
            if omega > 0:
                max_regen_torque = (
                    limits.max_regen_current_a
                    * inputs.pack_voltage_v
                    * params.motor_efficiency
                    / omega
                )
                regen_torque = min(regen_torque, max_regen_torque)
        motor_torque -= regen_torque

    new_state = ControlState(filtered_throttle=filtered, traction_scale=traction_scale)
    return (
        ControlOutputs(
            motor_torque_request_nm=motor_torque,
            regen_torque_request_nm=regen_torque,
            mechanical_brake=mechanical_brake,
            filtered_throttle=filtered,
            traction_limited=traction_limited,
        ),
        new_state,
    )
