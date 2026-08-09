"""Mechanical and regenerative braking."""

from __future__ import annotations

from dataclasses import dataclass

from gokart.config.schemas.components import Brake


@dataclass(frozen=True)
class BrakeParams:
    max_brake_torque_nm: float
    max_regen_fraction: float
    wheel_radius_m: float

    @classmethod
    def from_component(cls, brake: Brake, wheel_radius_m: float) -> BrakeParams:
        return cls(
            max_brake_torque_nm=brake.max_brake_torque_nm,
            max_regen_fraction=brake.max_regen_fraction,
            wheel_radius_m=wheel_radius_m,
        )


@dataclass(frozen=True)
class BrakeOutputs:
    mechanical_force_n: float
    regen_torque_request_nm: float
    mechanical_torque_nm: float


def step_brakes(
    brake_input: float,
    regen_torque_request_nm: float,
    params: BrakeParams,
) -> BrakeOutputs:
    brake = max(0.0, min(1.0, brake_input))
    total_brake_torque = params.max_brake_torque_nm * brake
    regen_torque = max(
        0.0,
        min(regen_torque_request_nm, total_brake_torque * params.max_regen_fraction),
    )
    mechanical_torque = max(0.0, total_brake_torque - regen_torque)
    if params.wheel_radius_m > 0:
        mechanical_force = mechanical_torque / params.wheel_radius_m
    else:
        mechanical_force = 0.0
    return BrakeOutputs(
        mechanical_force_n=mechanical_force,
        regen_torque_request_nm=regen_torque,
        mechanical_torque_nm=mechanical_torque,
    )
