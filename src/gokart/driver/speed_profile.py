"""Target speed profile along a racing line."""

from __future__ import annotations

import math
from dataclasses import dataclass

from gokart.driver.racing_line import RacingLinePoint
from gokart.physics.tyres import GRAVITY_MPS2

DEFAULT_MAX_ACCEL_MPS2 = 4.5
DEFAULT_MAX_BRAKE_MPS2 = 8.0


@dataclass(frozen=True)
class SpeedProfile:
    samples: tuple[tuple[float, float], ...]

    def target_speed_mps(self, s_m: float, track_length_m: float) -> float:
        if not self.samples or track_length_m <= 0.0:
            return 0.0
        s_wrapped = s_m % track_length_m
        for index in range(1, len(self.samples)):
            prev_s, prev_v = self.samples[index - 1]
            curr_s, curr_v = self.samples[index]
            if curr_s >= s_wrapped:
                span = curr_s - prev_s
                if span <= 1e-9:
                    return curr_v
                ratio = (s_wrapped - prev_s) / span
                return prev_v + (curr_v - prev_v) * ratio
        return self.samples[-1][1]


def build_speed_profile(
    line: list[RacingLinePoint],
    *,
    grip_coefficient: float,
    max_speed_mps: float,
    aggression: float = 1.0,
    max_accel_mps2: float = DEFAULT_MAX_ACCEL_MPS2,
    max_brake_mps2: float = DEFAULT_MAX_BRAKE_MPS2,
) -> SpeedProfile:
    """Build a curvature-limited speed profile with accel/brake passes."""
    if not line:
        return SpeedProfile(())

    grip_usage = 0.78 + 0.22 * max(0.0, min(1.0, aggression))
    lateral_g = grip_coefficient * GRAVITY_MPS2 * grip_usage
    mode_cap = max_speed_mps if max_speed_mps > 0.0 else 25.0

    speeds: list[float] = []
    for point in line:
        curvature = abs(point.curvature)
        if curvature < 1e-5:
            corner_speed = mode_cap
        else:
            corner_speed = math.sqrt(max(0.0, lateral_g / curvature))
        speeds.append(min(mode_cap, corner_speed))

    ds: list[float] = [0.0]
    for index in range(1, len(line)):
        dx = line[index].x - line[index - 1].x
        dy = line[index].y - line[index - 1].y
        ds.append(math.hypot(dx, dy))

    for index in range(len(speeds) - 2, -1, -1):
        step = max(ds[index + 1], 0.5)
        v_next = speeds[index + 1]
        v_brake = math.sqrt(max(0.0, v_next * v_next + 2.0 * max_brake_mps2 * step))
        speeds[index] = min(speeds[index], v_brake)

    for index in range(1, len(speeds)):
        step = max(ds[index], 0.5)
        v_prev = speeds[index - 1]
        v_accel = math.sqrt(max(0.0, v_prev * v_prev + 2.0 * max_accel_mps2 * step))
        speeds[index] = min(speeds[index], v_accel)

    samples = tuple((line[index].s, speeds[index]) for index in range(len(line)))
    return SpeedProfile(samples=samples)
