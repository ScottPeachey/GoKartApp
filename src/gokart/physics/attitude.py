"""Vehicle attitude from road gradient and quasi-static load transfer."""

from __future__ import annotations

import math

from gokart.physics.constants import GRAVITY_MPS2


def load_transfer_long_accel_mps2(
    speed_mps: float,
    long_accel_mps2: float,
) -> float:
    """Longitudinal acceleration used for pitch/load transfer (zero when held at rest)."""
    if speed_mps <= 0.0 and long_accel_mps2 < 0.0:
        return 0.0
    return long_accel_mps2


def vehicle_attitude_deg(
    *,
    gradient_rad: float = 0.0,
    long_accel_mps2: float = 0.0,
    lat_accel_mps2: float = 0.0,
    wheelbase_m: float,
    cg_height_m: float,
    speed_mps: float = 0.0,
) -> tuple[float, float]:
    """Return pitch and roll in degrees (pitch + = nose up, roll + = left side up)."""
    effective_long = load_transfer_long_accel_mps2(speed_mps, long_accel_mps2)
    dynamic_pitch = 0.0
    if wheelbase_m > 0.0 and cg_height_m > 0.0 and GRAVITY_MPS2 > 0.0:
        dynamic_pitch = math.atan(
            effective_long * cg_height_m / (GRAVITY_MPS2 * wheelbase_m),
        )
    pitch_rad = gradient_rad + dynamic_pitch
    roll_rad = math.atan(lat_accel_mps2 / GRAVITY_MPS2) if GRAVITY_MPS2 > 0.0 else 0.0
    return math.degrees(pitch_rad), math.degrees(roll_rad)
