"""Quasi-static axle load transfer for 4-wheel grip modelling."""

from __future__ import annotations

import math
from dataclasses import dataclass

from gokart.physics.constants import GRAVITY_MPS2


@dataclass(frozen=True)
class AxleLoads:
    front_normal_n: float
    rear_normal_n: float


def axle_normal_loads_n(
    *,
    mass_kg: float,
    wheelbase_m: float,
    cg_longitudinal_m: float,
    cg_height_m: float,
    long_accel_mps2: float = 0.0,
    lat_accel_mps2: float = 0.0,
    gradient_rad: float = 0.0,
) -> AxleLoads:
    """Return front and rear axle normal loads including static and dynamic transfer."""
    if wheelbase_m <= 0.0 or mass_kg <= 0.0:
        return AxleLoads(front_normal_n=0.0, rear_normal_n=0.0)

    weight_n = mass_kg * GRAVITY_MPS2 * math.cos(gradient_rad)
    cg_from_front = max(0.0, min(cg_longitudinal_m, wheelbase_m))
    front_static = weight_n * (wheelbase_m - cg_from_front) / wheelbase_m
    rear_static = weight_n * cg_from_front / wheelbase_m

    long_transfer = mass_kg * long_accel_mps2 * cg_height_m / wheelbase_m
    front = front_static - long_transfer
    rear = rear_static + long_transfer

    if abs(lat_accel_mps2) > 1e-9 and cg_height_m > 0.0:
        lat_transfer = mass_kg * abs(lat_accel_mps2) * cg_height_m / wheelbase_m
        max_shift = min(front_static, rear_static) * 0.45
        lat_transfer = min(lat_transfer, max_shift)
        if lat_accel_mps2 > 0.0:
            front -= lat_transfer
            rear += lat_transfer
        else:
            front += lat_transfer
            rear -= lat_transfer

    return AxleLoads(
        front_normal_n=max(0.0, front),
        rear_normal_n=max(0.0, rear),
    )
