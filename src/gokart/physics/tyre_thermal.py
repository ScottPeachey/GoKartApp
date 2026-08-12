"""Per-axle tyre temperature and wear affecting effective grip."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from gokart.config.schemas.components import Tyre


@dataclass(frozen=True)
class TyreThermalParams:
    optimal_temp_c: float
    temp_window_c: float
    heating_rate: float
    cooling_rate: float
    wear_rate: float
    grip_falloff_per_wear: float
    max_wear: float
    ambient_temp_c: float = 25.0

    @classmethod
    def from_tyre(cls, tyre: Tyre, *, ambient_temp_c: float = 25.0) -> TyreThermalParams:
        return cls(
            optimal_temp_c=tyre.optimal_temp_c,
            temp_window_c=tyre.temp_window_c,
            heating_rate=tyre.heating_rate,
            cooling_rate=tyre.cooling_rate,
            wear_rate=tyre.wear_rate,
            grip_falloff_per_wear=tyre.grip_falloff_per_wear,
            max_wear=tyre.max_wear,
            ambient_temp_c=ambient_temp_c,
        )


@dataclass
class AxleTyreState:
    temperature_c: float = 25.0
    wear: float = 0.0


@dataclass
class TyreThermalState:
    front: AxleTyreState = field(default_factory=AxleTyreState)
    rear: AxleTyreState = field(default_factory=AxleTyreState)

    @classmethod
    def initial(cls, ambient_temp_c: float = 25.0) -> TyreThermalState:
        return cls(
            front=AxleTyreState(temperature_c=ambient_temp_c),
            rear=AxleTyreState(temperature_c=ambient_temp_c),
        )


@dataclass(frozen=True)
class TyreThermalOutputs:
    front_temp_c: float
    rear_temp_c: float
    front_wear: float
    rear_wear: float
    front_grip_multiplier: float
    rear_grip_multiplier: float


def temperature_grip_multiplier(
    temperature_c: float,
    *,
    optimal_temp_c: float,
    temp_window_c: float,
) -> float:
    if temp_window_c <= 0.0:
        return 1.0
    delta = abs(temperature_c - optimal_temp_c) / temp_window_c
    return max(0.55, 1.0 - 0.45 * delta * delta)


def wear_grip_multiplier(
    wear: float,
    *,
    max_wear: float,
    grip_falloff_per_wear: float,
) -> float:
    if max_wear <= 0.0:
        return 1.0
    ratio = min(1.0, max(0.0, wear / max_wear))
    return max(0.55, 1.0 - grip_falloff_per_wear * ratio)


def axle_grip_multiplier(state: AxleTyreState, params: TyreThermalParams) -> float:
    temp_factor = temperature_grip_multiplier(
        state.temperature_c,
        optimal_temp_c=params.optimal_temp_c,
        temp_window_c=params.temp_window_c,
    )
    wear_factor = wear_grip_multiplier(
        state.wear,
        max_wear=params.max_wear,
        grip_falloff_per_wear=params.grip_falloff_per_wear,
    )
    return temp_factor * wear_factor


def step_axle_tyre(
    state: AxleTyreState,
    params: TyreThermalParams,
    *,
    slip_usage: float,
    normal_load_n: float,
    speed_mps: float,
    dt: float,
) -> AxleTyreState:
    slip = max(0.0, min(1.5, slip_usage))
    normal = max(normal_load_n, 0.0)
    speed = max(speed_mps, 0.0)
    slip_power = slip * slip * normal * speed if speed > 0.2 else 0.0
    heat_in = slip_power * params.heating_rate
    airflow = 1.0 + min(speed, 25.0) / 12.0
    temp_delta = state.temperature_c - params.ambient_temp_c
    overtemp = max(0.0, state.temperature_c - params.optimal_temp_c - 12.0)
    cool_boost = 1.0 + overtemp * 0.03
    cool = temp_delta * params.cooling_rate * airflow * cool_boost
    temperature_c = state.temperature_c + (heat_in - cool) * dt
    wear_delta = slip * params.wear_rate * normal * speed * dt if speed > 0.2 else 0.0
    wear = min(params.max_wear, state.wear + wear_delta)
    return AxleTyreState(temperature_c=temperature_c, wear=wear)


def axle_slip_usage(
    *,
    longitudinal_n: float,
    lateral_n: float,
    normal_load_n: float,
    grip_coefficient: float,
) -> float:
    grip_limit = max(normal_load_n * grip_coefficient, 1e-6)
    used = math.hypot(longitudinal_n, lateral_n)
    return used / grip_limit


def step_tyre_thermal(
    state: TyreThermalState,
    front_params: TyreThermalParams,
    rear_params: TyreThermalParams,
    *,
    front_longitudinal_n: float,
    front_lateral_n: float,
    rear_longitudinal_n: float,
    rear_lateral_n: float,
    front_normal_n: float,
    rear_normal_n: float,
    front_grip_coefficient: float,
    rear_grip_coefficient: float,
    speed_mps: float,
    dt: float,
) -> tuple[TyreThermalState, TyreThermalOutputs]:
    front_slip = axle_slip_usage(
        longitudinal_n=front_longitudinal_n,
        lateral_n=front_lateral_n,
        normal_load_n=front_normal_n,
        grip_coefficient=front_grip_coefficient,
    )
    rear_slip = axle_slip_usage(
        longitudinal_n=rear_longitudinal_n,
        lateral_n=rear_lateral_n,
        normal_load_n=rear_normal_n,
        grip_coefficient=rear_grip_coefficient,
    )
    front = step_axle_tyre(
        state.front,
        front_params,
        slip_usage=front_slip,
        normal_load_n=front_normal_n,
        speed_mps=speed_mps,
        dt=dt,
    )
    rear = step_axle_tyre(
        state.rear,
        rear_params,
        slip_usage=rear_slip,
        normal_load_n=rear_normal_n,
        speed_mps=speed_mps,
        dt=dt,
    )
    new_state = TyreThermalState(front=front, rear=rear)
    return new_state, TyreThermalOutputs(
        front_temp_c=front.temperature_c,
        rear_temp_c=rear.temperature_c,
        front_wear=front.wear,
        rear_wear=rear.wear,
        front_grip_multiplier=axle_grip_multiplier(front, front_params),
        rear_grip_multiplier=axle_grip_multiplier(rear, rear_params),
    )
