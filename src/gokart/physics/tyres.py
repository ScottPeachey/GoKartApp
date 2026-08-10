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
    lateral_force_n: float = 0.0
    longitudinal_grip_limit_n: float = 0.0


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
        longitudinal_grip_limit_n=limit,
    )


def lateral_force_from_steering_n(
    speed_mps: float,
    steer_rad: float,
    wheelbase_m: float,
    mass_kg: float,
) -> float:
    """Lateral force demand from bicycle-model cornering at the given speed."""
    if wheelbase_m <= 0.0 or abs(steer_rad) < 1e-6:
        return 0.0
    lat_accel = speed_mps * speed_mps * math.tan(steer_rad) / wheelbase_m
    return mass_kg * lat_accel


def max_lateral_accel_mps2(grip_coefficient: float, gradient_rad: float = 0.0) -> float:
    return grip_coefficient * GRAVITY_MPS2 * math.cos(gradient_rad)


def cornering_speed_limit_mps(
    steer_rad: float,
    wheelbase_m: float,
    grip_coefficient: float,
    gradient_rad: float = 0.0,
) -> float | None:
    """Maximum speed before lateral grip is exceeded for a given steer angle."""
    if wheelbase_m <= 0.0 or abs(steer_rad) < 1e-6:
        return None
    max_lat = max_lateral_accel_mps2(grip_coefficient, gradient_rad)
    if max_lat <= 0.0:
        return 0.0
    return math.sqrt(max_lat * wheelbase_m / math.tan(abs(steer_rad)))


def saturate_traction_friction_circle(
    requested_force_n: float,
    lateral_force_n: float,
    mass_kg: float,
    grip_coefficient: float,
    gradient_rad: float = 0.0,
) -> TyreOutputs:
    """Limit longitudinal force using a 2-D friction circle with lateral demand."""
    normal = normal_load_n(mass_kg, gradient_rad)
    max_total = normal * grip_coefficient
    lat = min(abs(lateral_force_n), max_total)
    long_available = math.sqrt(max(0.0, max_total * max_total - lat * lat))
    traction = max(-long_available, min(requested_force_n, long_available))
    return TyreOutputs(
        traction_force_n=traction,
        traction_force_requested_n=requested_force_n,
        normal_load_n=normal,
        lateral_force_n=lateral_force_n,
        longitudinal_grip_limit_n=long_available,
    )
