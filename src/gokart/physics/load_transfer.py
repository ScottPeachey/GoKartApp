"""Quasi-static axle load transfer for 4-wheel grip modelling."""

from __future__ import annotations

import math
from dataclasses import dataclass

from gokart.physics.constants import GRAVITY_MPS2


@dataclass(frozen=True)
class AxleLoads:
    front_normal_n: float
    rear_normal_n: float


@dataclass(frozen=True)
class WheelLoads:
    fl_normal_n: float
    fr_normal_n: float
    rl_normal_n: float
    rr_normal_n: float

    @property
    def front_normal_n(self) -> float:
        return self.fl_normal_n + self.fr_normal_n

    @property
    def rear_normal_n(self) -> float:
        return self.rl_normal_n + self.rr_normal_n

    def as_axle_loads(self) -> AxleLoads:
        return AxleLoads(
            front_normal_n=self.front_normal_n,
            rear_normal_n=self.rear_normal_n,
        )


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


def wheel_normal_loads_n(
    *,
    mass_kg: float,
    wheelbase_m: float,
    cg_longitudinal_m: float,
    cg_height_m: float,
    front_track_m: float,
    rear_track_m: float,
    long_accel_mps2: float = 0.0,
    lat_accel_mps2: float = 0.0,
    gradient_rad: float = 0.0,
) -> WheelLoads:
    """Split axle loads across left/right wheels with roll transfer."""
    axle = axle_normal_loads_n(
        mass_kg=mass_kg,
        wheelbase_m=wheelbase_m,
        cg_longitudinal_m=cg_longitudinal_m,
        cg_height_m=cg_height_m,
        long_accel_mps2=long_accel_mps2,
        lat_accel_mps2=0.0,
        gradient_rad=gradient_rad,
    )
    front_half = axle.front_normal_n * 0.5
    rear_half = axle.rear_normal_n * 0.5

    if abs(lat_accel_mps2) <= 1e-9 or cg_height_m <= 0.0:
        return WheelLoads(
            fl_normal_n=front_half,
            fr_normal_n=front_half,
            rl_normal_n=rear_half,
            rr_normal_n=rear_half,
        )

    front_track = max(front_track_m, 0.1)
    rear_track = max(rear_track_m, 0.1)
    front_roll = mass_kg * abs(lat_accel_mps2) * cg_height_m / front_track
    rear_roll = mass_kg * abs(lat_accel_mps2) * cg_height_m / rear_track
    front_roll = min(front_roll, front_half * 0.42)
    rear_roll = min(rear_roll, rear_half * 0.42)

    # Positive lateral accel (left turn) transfers load to the right-side wheels.
    if lat_accel_mps2 > 0.0:
        return WheelLoads(
            fl_normal_n=max(0.0, front_half - front_roll),
            fr_normal_n=front_half + front_roll,
            rl_normal_n=max(0.0, rear_half - rear_roll),
            rr_normal_n=rear_half + rear_roll,
        )
    return WheelLoads(
        fl_normal_n=front_half + front_roll,
        fr_normal_n=max(0.0, front_half - front_roll),
        rl_normal_n=rear_half + rear_roll,
        rr_normal_n=max(0.0, rear_half - rear_roll),
    )
