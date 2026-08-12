"""Pure pursuit steering and longitudinal speed control."""

from __future__ import annotations

import math
from dataclasses import dataclass

from gokart.driver.racing_line import RacingLinePoint, point_at_s
from gokart.driver.speed_profile import SpeedProfile
from gokart.physics.steering import MAX_STEER_ANGLE_DEG


@dataclass(frozen=True)
class PursuitOutputs:
    throttle: float
    brake: float
    steering: float
    target_speed_mps: float


def pure_pursuit_step(
    *,
    x: float,
    y: float,
    heading_rad: float,
    speed_mps: float,
    s_m: float,
    line: list[RacingLinePoint],
    profile: SpeedProfile,
    track_length_m: float,
    wheelbase_m: float,
    lookahead_base_m: float = 4.0,
    lookahead_gain: float = 0.35,
    speed_kp_throttle: float = 0.12,
    speed_kp_brake: float = 0.18,
    soc: float = 1.0,
    aggression: float = 1.0,
) -> PursuitOutputs:
    """Compute driver inputs for one control tick."""
    target_speed = profile.target_speed_mps(s_m, track_length_m)
    if aggression < 0.95 and soc < 0.25:
        target_speed *= 0.75
    elif aggression < 0.95 and soc < 0.4:
        target_speed *= 0.9

    # Lift-and-coast on straights for endurance-style aggression.
    if aggression < 0.9 and abs(_curvature_at_s(line, s_m, track_length_m)) < 0.01:
        target_speed *= 0.92

    lookahead = lookahead_base_m + lookahead_gain * max(speed_mps, 0.0)
    goal = point_at_s(line, s_m + lookahead, track_length_m)
    dx = goal.x - x
    dy = goal.y - y
    local_x = math.cos(-heading_rad) * dx - math.sin(-heading_rad) * dy
    local_y = math.sin(-heading_rad) * dx + math.cos(-heading_rad) * dy
    alpha = math.atan2(local_y, local_x)
    if wheelbase_m > 0.0 and lookahead > 0.5:
        steer_rad = math.atan2(2.0 * wheelbase_m * math.sin(alpha), lookahead)
    else:
        steer_rad = 0.0
    max_steer_rad = math.radians(MAX_STEER_ANGLE_DEG)
    steering = max(-1.0, min(1.0, steer_rad / max_steer_rad))

    speed_error = target_speed - speed_mps
    throttle = 0.0
    brake = 0.0
    if speed_error > 0.15:
        throttle = max(0.0, min(1.0, speed_kp_throttle * speed_error))
    elif speed_error < -0.2:
        brake = max(0.0, min(1.0, speed_kp_brake * abs(speed_error)))

    return PursuitOutputs(
        throttle=throttle,
        brake=brake,
        steering=steering,
        target_speed_mps=target_speed,
    )


def _curvature_at_s(line: list[RacingLinePoint], s_m: float, track_length_m: float) -> float:
    point = point_at_s(line, s_m, track_length_m)
    return point.curvature
