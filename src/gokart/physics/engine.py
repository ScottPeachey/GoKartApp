"""Four-stroke ICE torque map and RPM dynamics."""

from __future__ import annotations

from dataclasses import dataclass

from gokart.config.schemas.components import Engine, TorqueMapPoint
from gokart.physics.clutch import ClutchOutputs, ClutchParams, step_clutch
from gokart.physics.drivetrain import DrivetrainParams, motor_rpm_from_speed
from gokart.physics.motor import _interpolate_map
from gokart.units import rpm_to_rads


@dataclass(frozen=True)
class EngineParams:
    idle_rpm: float
    redline_rpm: float
    peak_torque_nm: float
    peak_power_w: float
    max_rpm: float
    engine_braking_nm: float
    default_efficiency: float = 0.35
    torque_map: tuple[TorqueMapPoint, ...] = ()

    @classmethod
    def from_component(cls, engine: Engine) -> EngineParams:
        return cls(
            idle_rpm=engine.idle_rpm,
            redline_rpm=engine.redline_rpm,
            peak_torque_nm=engine.peak_torque_nm,
            peak_power_w=engine.peak_power_w,
            max_rpm=engine.max_rpm,
            engine_braking_nm=engine.engine_braking_nm,
            torque_map=tuple(engine.torque_map),
        )


@dataclass
class EngineState:
    rpm: float = 0.0


@dataclass(frozen=True)
class EngineInputs:
    throttle: float
    torque_request_nm: float
    speed_mps: float


@dataclass(frozen=True)
class IcePowertrainOutputs:
    engine_rpm: float
    engine_torque_nm: float
    wheel_torque_nm: float
    clutch_locked: bool
    clutch_engagement_fraction: float
    heat_w: float
    efficiency: float


def _wide_open_torque_nm(params: EngineParams, rpm: float) -> float:
    rpm_clamped = max(0.0, min(rpm, params.max_rpm))
    if rpm_clamped >= params.redline_rpm:
        return 0.0
    if params.torque_map:
        map_torque, _ = _interpolate_map(rpm_clamped, params.torque_map)
        base_torque = min(map_torque, params.peak_torque_nm)
    else:
        base_torque = params.peak_torque_nm
    omega = rpm_to_rads(rpm_clamped)
    if omega > 1e-3:
        power_limited = params.peak_power_w / omega
        base_torque = min(base_torque, power_limited)
    return max(0.0, base_torque)


def available_engine_torque_nm(
    params: EngineParams,
    rpm: float,
    throttle: float,
) -> float:
    throttle_clamped = max(0.0, min(1.0, throttle))
    if throttle_clamped <= 0.02:
        return -params.engine_braking_nm
    return _wide_open_torque_nm(params, rpm) * throttle_clamped


def step_ice_powertrain(
    state: EngineState,
    inputs: EngineInputs,
    engine_params: EngineParams,
    clutch_params: ClutchParams,
    drivetrain_params: DrivetrainParams,
    dt: float,
) -> tuple[EngineState, IcePowertrainOutputs]:
    """Advance engine RPM with centrifugal clutch and return wheel torque."""
    throttle = max(0.0, min(1.0, inputs.throttle))
    coupled_rpm = motor_rpm_from_speed(drivetrain_params, inputs.speed_mps)
    engine_rpm = max(state.rpm, engine_params.idle_rpm * 0.5)

    commanded_torque = available_engine_torque_nm(engine_params, engine_rpm, throttle)
    if inputs.torque_request_nm >= 0:
        commanded_torque = min(commanded_torque, inputs.torque_request_nm)
    else:
        commanded_torque = max(commanded_torque, inputs.torque_request_nm)

    clutch_out = step_clutch(commanded_torque, engine_rpm, clutch_params)

    if clutch_out.locked:
        engine_rpm = max(coupled_rpm, engine_params.idle_rpm)
    else:
        target_rpm = engine_params.idle_rpm + throttle * (
            engine_params.redline_rpm - engine_params.idle_rpm
        )
        if throttle > 0.02:
            engine_rpm += (target_rpm - engine_rpm) * min(1.0, dt * 12.0)
        else:
            engine_rpm += (engine_params.idle_rpm - engine_rpm) * min(1.0, dt * 6.0)

    engine_rpm = max(0.0, min(engine_rpm, engine_params.max_rpm))
    if engine_rpm >= engine_params.redline_rpm:
        commanded_torque = 0.0
        clutch_out = step_clutch(0.0, engine_rpm, clutch_params)

    if engine_params.torque_map and engine_rpm > 0:
        _, efficiency = _interpolate_map(engine_rpm, engine_params.torque_map)
    else:
        efficiency = engine_params.default_efficiency

    omega = rpm_to_rads(engine_rpm)
    mechanical_power = clutch_out.transmitted_torque_nm * omega
    heat = max(0.0, abs(commanded_torque * omega) * (1.0 - efficiency))

    wheel_torque = clutch_out.transmitted_torque_nm * drivetrain_params.gear_ratio
    wheel_torque *= drivetrain_params.total_efficiency

    new_state = EngineState(rpm=engine_rpm)
    return new_state, IcePowertrainOutputs(
        engine_rpm=engine_rpm,
        engine_torque_nm=clutch_out.transmitted_torque_nm,
        wheel_torque_nm=wheel_torque,
        clutch_locked=clutch_out.locked,
        clutch_engagement_fraction=clutch_out.engagement_fraction,
        heat_w=heat,
        efficiency=efficiency,
    )
