"""Bicycle-model steering kinematics for free-drive simulation."""

from __future__ import annotations

import math
from dataclasses import dataclass

MAX_STEER_ANGLE_DEG = 28.0


@dataclass(frozen=True)
class SteeringOutputs:
    heading_rad: float
    position_x_m: float
    position_y_m: float
    steering_angle_rad: float
    yaw_rate_rad_s: float


def steering_angle_rad(steering_input: float) -> float:
    """Map normalized steering input (-1..1) to front wheel angle."""
    clamped = max(-1.0, min(1.0, steering_input))
    return math.radians(MAX_STEER_ANGLE_DEG) * clamped


def step_steering(
    *,
    heading_rad: float,
    position_x_m: float,
    position_y_m: float,
    speed_mps: float,
    steering_input: float,
    wheelbase_m: float,
    dt: float,
) -> SteeringOutputs:
    """Advance heading and planar position from normalized steering input (-1..1)."""
    steer_rad = steering_angle_rad(steering_input)
    yaw_rate = 0.0
    if speed_mps > 0.05 and wheelbase_m > 0.0:
        yaw_rate = (speed_mps / wheelbase_m) * math.tan(steer_rad)
        heading_rad += yaw_rate * dt
    position_x_m += speed_mps * math.cos(heading_rad) * dt
    position_y_m += speed_mps * math.sin(heading_rad) * dt
    return SteeringOutputs(
        heading_rad=heading_rad,
        position_x_m=position_x_m,
        position_y_m=position_y_m,
        steering_angle_rad=steer_rad,
        yaw_rate_rad_s=yaw_rate,
    )
