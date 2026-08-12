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
    lateral_m: float,
    line: list[RacingLinePoint],
    profile: SpeedProfile,
    track_length_m: float,
    wheelbase_m: float,
    lookahead_base_m: float = 3.5,
    lookahead_gain: float = 0.28,
    speed_kp_throttle: float = 0.055,
    speed_kp_brake: float = 0.18,
    max_throttle: float = 0.72,
    soc: float = 1.0,
    aggression: float = 1.0,
    battery_temp_c: float = 25.0,
    battery_derate_c: float = 50.0,
    battery_fault_c: float = 60.0,
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

    warn_c = battery_derate_c - 12.0
    if battery_temp_c > warn_c:
        hot_span = max(battery_fault_c - warn_c, 1.0)
        hot_fraction = (battery_temp_c - warn_c) / hot_span
        target_speed *= max(0.35, 1.0 - hot_fraction * 0.9)

    curvature = abs(_curvature_at_s(line, s_m, track_length_m))
    lookahead = lookahead_base_m + lookahead_gain * max(speed_mps, 0.0)
    lookahead *= max(0.5, 1.0 - min(curvature * 50.0, 0.5))
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

    # Cross-track correction so the kart turns when projected s is stable but offset.
    if wheelbase_m > 0.0:
        steer_rad += math.atan2(0.5 * lateral_m, max(speed_mps, 1.2) + 0.8)

    max_steer_rad = math.radians(MAX_STEER_ANGLE_DEG)
    steering = max(-1.0, min(1.0, steer_rad / max_steer_rad))

    throttle_cap = max_throttle
    if battery_temp_c >= battery_derate_c - 2.0:
        throttle_cap = min(throttle_cap, 0.2)
    elif battery_temp_c > warn_c:
        throttle_cap = min(throttle_cap, 0.5)

    speed_error = target_speed - speed_mps
    throttle = 0.0
    brake = 0.0
    if speed_error > 0.2:
        throttle = max(0.0, min(throttle_cap, speed_kp_throttle * speed_error))
    elif speed_error < -0.35:
        brake = max(0.0, min(1.0, speed_kp_brake * abs(speed_error)))

    if battery_temp_c >= battery_derate_c:
        hot_span = max(battery_fault_c - battery_derate_c, 1.0)
        thermal_scale = max(0.1, 1.0 - (battery_temp_c - battery_derate_c) / hot_span)
        throttle *= thermal_scale

    return PursuitOutputs(
        throttle=throttle,
        brake=brake,
        steering=steering,
        target_speed_mps=target_speed,
    )


def _curvature_at_s(line: list[RacingLinePoint], s_m: float, track_length_m: float) -> float:
    point = point_at_s(line, s_m, track_length_m)
    return point.curvature
