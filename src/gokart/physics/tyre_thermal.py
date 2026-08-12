"""Per-wheel tyre temperature and wear affecting effective grip."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from gokart.config.schemas.components import Tyre
from gokart.physics.tyres import WheelTyreOutputs


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
class WheelTyreState:
    temperature_c: float = 25.0
    wear: float = 0.0


@dataclass
class AxleTyreState:
    temperature_c: float = 25.0
    wear: float = 0.0


@dataclass
class TyreThermalState:
    fl: WheelTyreState = field(default_factory=WheelTyreState)
    fr: WheelTyreState = field(default_factory=WheelTyreState)
    rl: WheelTyreState = field(default_factory=WheelTyreState)
    rr: WheelTyreState = field(default_factory=WheelTyreState)

    @classmethod
    def initial(cls, ambient_temp_c: float = 25.0) -> TyreThermalState:
        return cls(
            fl=WheelTyreState(temperature_c=ambient_temp_c),
            fr=WheelTyreState(temperature_c=ambient_temp_c),
            rl=WheelTyreState(temperature_c=ambient_temp_c),
            rr=WheelTyreState(temperature_c=ambient_temp_c),
        )

    @property
    def front(self) -> AxleTyreState:
        return AxleTyreState(
            temperature_c=(self.fl.temperature_c + self.fr.temperature_c) * 0.5,
            wear=(self.fl.wear + self.fr.wear) * 0.5,
        )

    @property
    def rear(self) -> AxleTyreState:
        return AxleTyreState(
            temperature_c=(self.rl.temperature_c + self.rr.temperature_c) * 0.5,
            wear=(self.rl.wear + self.rr.wear) * 0.5,
        )


@dataclass(frozen=True)
class TyreThermalOutputs:
    fl_temp_c: float
    fr_temp_c: float
    rl_temp_c: float
    rr_temp_c: float
    fl_wear: float
    fr_wear: float
    rl_wear: float
    rr_wear: float
    fl_grip_multiplier: float
    fr_grip_multiplier: float
    rl_grip_multiplier: float
    rr_grip_multiplier: float
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


def wheel_grip_multiplier(state: WheelTyreState, params: TyreThermalParams) -> float:
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


def step_wheel_tyre(
    state: WheelTyreState,
    params: TyreThermalParams,
    *,
    slip_usage: float,
    normal_load_n: float,
    speed_mps: float,
    dt: float,
) -> WheelTyreState:
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
    return WheelTyreState(temperature_c=temperature_c, wear=wear)


def wheel_slip_usage(
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
    tyre_out: WheelTyreOutputs,
    front_grip_coefficient: float,
    rear_grip_coefficient: float,
    speed_mps: float,
    dt: float,
) -> tuple[TyreThermalState, TyreThermalOutputs]:
    loads = tyre_out.wheel_loads
    wheels = (
        ("fl", state.fl, front_params, tyre_out.fl_longitudinal_n, tyre_out.fl_lateral_n, loads.fl_normal_n),
        ("fr", state.fr, front_params, tyre_out.fr_longitudinal_n, tyre_out.fr_lateral_n, loads.fr_normal_n),
        ("rl", state.rl, rear_params, tyre_out.rl_longitudinal_n, tyre_out.rl_lateral_n, loads.rl_normal_n),
        ("rr", state.rr, rear_params, tyre_out.rr_longitudinal_n, tyre_out.rr_lateral_n, loads.rr_normal_n),
    )
    updated: dict[str, WheelTyreState] = {}
    grip_multipliers: dict[str, float] = {}
    for key, wheel_state, params, long_n, lat_n, normal_n in wheels:
        grip_base = front_grip_coefficient if key in {"fl", "fr"} else rear_grip_coefficient
        slip = wheel_slip_usage(
            longitudinal_n=long_n,
            lateral_n=lat_n,
            normal_load_n=normal_n,
            grip_coefficient=grip_base,
        )
        new_wheel = step_wheel_tyre(
            wheel_state,
            params,
            slip_usage=slip,
            normal_load_n=normal_n,
            speed_mps=speed_mps,
            dt=dt,
        )
        updated[key] = new_wheel
        grip_multipliers[key] = wheel_grip_multiplier(new_wheel, params)

    new_state = TyreThermalState(
        fl=updated["fl"],
        fr=updated["fr"],
        rl=updated["rl"],
        rr=updated["rr"],
    )
    front_grip = (grip_multipliers["fl"] + grip_multipliers["fr"]) * 0.5
    rear_grip = (grip_multipliers["rl"] + grip_multipliers["rr"]) * 0.5
    return new_state, TyreThermalOutputs(
        fl_temp_c=updated["fl"].temperature_c,
        fr_temp_c=updated["fr"].temperature_c,
        rl_temp_c=updated["rl"].temperature_c,
        rr_temp_c=updated["rr"].temperature_c,
        fl_wear=updated["fl"].wear,
        fr_wear=updated["fr"].wear,
        rl_wear=updated["rl"].wear,
        rr_wear=updated["rr"].wear,
        fl_grip_multiplier=grip_multipliers["fl"],
        fr_grip_multiplier=grip_multipliers["fr"],
        rl_grip_multiplier=grip_multipliers["rl"],
        rr_grip_multiplier=grip_multipliers["rr"],
        front_temp_c=new_state.front.temperature_c,
        rear_temp_c=new_state.rear.temperature_c,
        front_wear=new_state.front.wear,
        rear_wear=new_state.rear.wear,
        front_grip_multiplier=front_grip,
        rear_grip_multiplier=rear_grip,
    )
