"""Motor torque-speed model with optional efficiency map."""

from __future__ import annotations

from dataclasses import dataclass

from gokart.config.schemas.components import Motor, TorqueMapPoint
from gokart.units import rpm_to_rads


@dataclass(frozen=True)
class MotorParams:
    peak_torque_nm: float
    continuous_torque_nm: float
    peak_power_w: float
    continuous_power_w: float
    peak_current_a: float
    max_rpm: float
    nominal_voltage_v: float
    default_efficiency: float = 0.9
    torque_map: tuple[TorqueMapPoint, ...] = ()

    @classmethod
    def from_component(cls, motor: Motor) -> MotorParams:
        return cls(
            peak_torque_nm=motor.peak_torque_nm,
            continuous_torque_nm=motor.continuous_torque_nm,
            peak_power_w=motor.peak_power_w,
            continuous_power_w=motor.continuous_power_w,
            peak_current_a=motor.peak_current_a,
            max_rpm=motor.max_rpm,
            nominal_voltage_v=motor.nominal_voltage_v,
            torque_map=tuple(motor.torque_map),
        )


@dataclass
class MotorState:
    temperature_c: float = 25.0


@dataclass(frozen=True)
class MotorInputs:
    torque_request_nm: float
    motor_rpm: float
    pack_voltage_v: float


@dataclass(frozen=True)
class MotorOutputs:
    torque_nm: float
    motor_current_a: float
    electrical_power_w: float
    mechanical_power_w: float
    efficiency: float
    heat_w: float


def _interpolate_map(rpm: float, points: tuple[TorqueMapPoint, ...]) -> tuple[float, float]:
    if not points:
        raise ValueError("torque map is empty")
    if rpm <= points[0].rpm:
        return points[0].torque_nm, points[0].efficiency
    if rpm >= points[-1].rpm:
        return points[-1].torque_nm, points[-1].efficiency
    for left, right in zip(points, points[1:], strict=False):
        if left.rpm <= rpm <= right.rpm:
            span = right.rpm - left.rpm
            if span <= 0:
                return right.torque_nm, right.efficiency
            ratio = (rpm - left.rpm) / span
            torque = left.torque_nm + ratio * (right.torque_nm - left.torque_nm)
            efficiency = left.efficiency + ratio * (right.efficiency - left.efficiency)
            return torque, efficiency
    return points[-1].torque_nm, points[-1].efficiency


def available_torque_nm(params: MotorParams, motor_rpm: float, pack_voltage_v: float) -> float:
    """Maximum torque the motor can deliver at the current speed and voltage."""
    rpm = max(0.0, min(motor_rpm, params.max_rpm))
    voltage_scale = (
        max(0.0, min(1.0, pack_voltage_v / params.nominal_voltage_v))
        if params.nominal_voltage_v > 0
        else 0.0
    )

    if params.torque_map:
        map_torque, _ = _interpolate_map(rpm, params.torque_map)
        base_torque = min(map_torque, params.peak_torque_nm)
    else:
        base_torque = params.peak_torque_nm

    omega = rpm_to_rads(rpm)
    if omega > 1e-3:
        power_limited_torque = params.peak_power_w / omega
        base_torque = min(base_torque, power_limited_torque)

    return base_torque * voltage_scale


def step_motor(
    state: MotorState,
    inputs: MotorInputs,
    params: MotorParams,
    dt: float,
) -> tuple[MotorState, MotorOutputs]:
    """Apply torque request subject to motor envelope; compute electrical load."""
    _ = dt
    avail = available_torque_nm(params, inputs.motor_rpm, inputs.pack_voltage_v)
    torque = max(-avail, min(inputs.torque_request_nm, avail))
    rpm = max(0.0, inputs.motor_rpm)
    omega = rpm_to_rads(rpm)

    if params.torque_map and rpm > 0:
        _, efficiency = _interpolate_map(rpm, params.torque_map)
    else:
        efficiency = params.default_efficiency

    mechanical_power = torque * omega
    if mechanical_power >= 0:
        electrical_power = mechanical_power / max(efficiency, 0.05)
    else:
        electrical_power = mechanical_power * efficiency

    if inputs.pack_voltage_v > 1.0:
        motor_current = electrical_power / inputs.pack_voltage_v
    else:
        motor_current = 0.0

    motor_current = max(-params.peak_current_a, min(motor_current, params.peak_current_a))
    heat = abs(electrical_power) - abs(mechanical_power)
    heat = max(0.0, heat)

    return state, MotorOutputs(
        torque_nm=torque,
        motor_current_a=motor_current,
        electrical_power_w=electrical_power,
        mechanical_power_w=mechanical_power,
        efficiency=efficiency,
        heat_w=heat,
    )
