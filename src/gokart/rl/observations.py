"""Driving-focused observation vector for circuit RL."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from gokart.track.model import Track
from gokart.track.queries import interpolate_centerline_at_s

CURVATURE_LOOKAHEAD_M = (10.0, 25.0, 45.0, 70.0, 100.0)
HEADING_LOOKAHEAD_M = 25.0
OBS_DIM = 16


def build_observation(
    *,
    tick_values: dict[str, Any],
    step_info: dict[str, Any],
    track: Track,
    target_laps: int = 1,
    max_steps: int = 1,
    step_index: int = 0,
) -> np.ndarray:
    speed = float(tick_values.get("speed_mps", 0.0))
    max_speed = max(float(tick_values.get("max_speed_mps", 12.5)), 0.1)
    heading_deg = float(tick_values.get("heading_deg", 0.0))
    track_s = float(step_info.get("track_s_m", 0.0))
    lateral = float(step_info.get("lateral_offset_m", 0.0))
    half_width = max(track.width_m * 0.5, 0.1)
    heading_error = float(step_info.get("heading_error_deg", 0.0))
    length_m = max(track.length_m, 1.0)

    ahead_heading = interpolate_centerline_at_s(track.centerline, track_s + HEADING_LOOKAHEAD_M)[2]
    ahead_error = _angle_wrap(heading_deg - math.degrees(ahead_heading))

    curvature_samples = [
        _curvature_at_s(track, track_s + distance) for distance in CURVATURE_LOOKAHEAD_M
    ]

    obs = np.array(
        [
            speed / max_speed,
            math.sin(math.radians(heading_error)),
            math.cos(math.radians(heading_error)),
            lateral / half_width,
            float(step_info.get("off_track", 0.0)),
            (track_s % length_m) / length_m,
            math.sin(math.radians(ahead_error)),
            math.cos(math.radians(ahead_error)),
            float(tick_values.get("throttle", 0.0)),
            float(tick_values.get("brake", 0.0)),
            float(tick_values.get("steering", 0.0)),
            *curvature_samples,
        ],
        dtype=np.float32,
    )
    if obs.shape[0] != OBS_DIM:
        raise ValueError(f"expected observation dim {OBS_DIM}, got {obs.shape[0]}")
    return obs


def _curvature_at_s(track: Track, s_m: float) -> float:
    centerline = track.centerline
    if not centerline or track.length_m <= 0:
        return 0.0
    s_wrapped = s_m % track.length_m
    if s_wrapped <= centerline[0].s:
        return float(centerline[0].curvature) * 100.0
    for index in range(1, len(centerline)):
        prev = centerline[index - 1]
        curr = centerline[index]
        if curr.s >= s_wrapped:
            span = curr.s - prev.s
            if span <= 1e-9:
                return float(curr.curvature) * 100.0
            ratio = (s_wrapped - prev.s) / span
            curvature = prev.curvature + (curr.curvature - prev.curvature) * ratio
            return float(curvature) * 100.0
    return float(centerline[-1].curvature) * 100.0


def _angle_wrap(deg: float) -> float:
    while deg > 180.0:
        deg -= 360.0
    while deg < -180.0:
        deg += 360.0
    return deg
