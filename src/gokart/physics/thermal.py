"""Single thermal-mass component model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThermalParams:
    thermal_capacity_j_per_k: float
    thermal_resistance_k_per_w: float
    ambient_temp_c: float = 25.0


@dataclass
class ThermalState:
    temperature_c: float = 25.0


@dataclass(frozen=True)
class ThermalInputs:
    heat_w: float


@dataclass(frozen=True)
class ThermalOutputs:
    temperature_c: float
    heat_loss_w: float


def step_thermal(
    state: ThermalState,
    inputs: ThermalInputs,
    params: ThermalParams,
    dt: float,
    *,
    cooling_scale: float = 1.0,
) -> tuple[ThermalState, ThermalOutputs]:
    if params.thermal_capacity_j_per_k <= 0 or params.thermal_resistance_k_per_w <= 0:
        return state, ThermalOutputs(temperature_c=state.temperature_c, heat_loss_w=0.0)

    effective_r = params.thermal_resistance_k_per_w / max(cooling_scale, 0.1)
    heat_loss = (state.temperature_c - params.ambient_temp_c) / effective_r
    dT = (inputs.heat_w - heat_loss) * dt / params.thermal_capacity_j_per_k
    new_temp = state.temperature_c + dT
    new_state = ThermalState(temperature_c=new_temp)
    return new_state, ThermalOutputs(temperature_c=new_temp, heat_loss_w=heat_loss)
