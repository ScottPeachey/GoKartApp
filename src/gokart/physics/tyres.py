"""Longitudinal tyre grip and force saturation."""

from __future__ import annotations

import math
from dataclasses import dataclass

from gokart.physics.constants import GRAVITY_MPS2


@dataclass(frozen=True)
class TyreParams:
    grip_coefficient: float
    wheel_radius_m: float


@dataclass(frozen=True)
class TyreOutputs:
    traction_force_n: float
    traction_force_requested_n: float
    normal_load_n: float


def normal_load_n(mass_kg: float, gradient_rad: float = 0.0) -> float:
    return mass_kg * GRAVITY_MPS2 * math.cos(gradient_rad)


def max_traction_force_n(
    mass_kg: float,
    grip_coefficient: float,
    gradient_rad: float = 0.0,
) -> float:
    return normal_load_n(mass_kg, gradient_rad) * grip_coefficient


def saturate_traction_force(
    requested_force_n: float,
    mass_kg: float,
    grip_coefficient: float,
    gradient_rad: float = 0.0,
) -> TyreOutputs:
    """Clip requested longitudinal force to tyre friction limit."""
    limit = max_traction_force_n(mass_kg, grip_coefficient, gradient_rad)
    traction = max(-limit, min(requested_force_n, limit))
    return TyreOutputs(
        traction_force_n=traction,
        traction_force_requested_n=requested_force_n,
        normal_load_n=normal_load_n(mass_kg, gradient_rad),
    )
