"""Observation vector construction for RL policies."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from gokart.track.lap import project_xy_to_track
from gokart.track.model import Track

CURVATURE_LOOKAHEAD_M = (8.0, 16.0, 24.0, 32.0, 40.0)
OBS_DIM = 25


def build_observation(
    *,
    tick_values: dict[str, Any],
    step_info: dict[str, Any],
    track: Track,
    target_laps: int,
    max_steps: int,
    step_index: int,
) -> np.ndarray:
    speed = float(tick_values.get("speed_mps", 0.0))
    max_speed = max(float(tick_values.get("max_speed_mps", 12.5)), 0.1)
    heading_deg = float(tick_values.get("heading_deg", 0.0))
    track_s = float(step_info.get("track_s_m", 0.0))
    lateral = float(step_info.get("lateral_offset_m", 0.0))
    half_width = max(track.width_m * 0.5, 0.1)
    if "heading_error_deg" in step_info:
        heading_error = float(step_info["heading_error_deg"])
    else:
        projection = project_xy_to_track(
            track.centerline,
            float(tick_values.get("position_x_m", 0.0)),
            float(tick_values.get("position_y_m", 0.0)),
            around_s_m=track_s,
            window_m=40.0,
            length_m=track.length_m,
        )
        heading_error = _angle_wrap(heading_deg - math.degrees(projection.heading_rad))

    curvature_samples = [
        _curvature_at_s(track, track_s + distance) for distance in CURVATURE_LOOKAHEAD_M
    ]

    battery_temp = float(tick_values.get("battery_temp_c", 25.0))
    motor_temp = float(tick_values.get("motor_temp_c", 25.0))
    battery_derate = float(step_info.get("battery_temp_derate_c", 50.0))
    battery_fault = float(step_info.get("battery_temp_fault_c", 60.0))
    soc = float(tick_values.get("soc", 1.0))
    derating = float(tick_values.get("derating_factor", 1.0))
    torque_permitted = float(tick_values.get("torque_permitted", 0.0))

    active_faults = str(tick_values.get("active_faults", ""))
    blocking = 1.0 if _has_blocking(active_faults) else 0.0
    derate_fault = 1.0 if "DERATE" in active_faults else 0.0

    laps_remaining = max(target_laps - int(step_info.get("completed_laps", 0)), 0)
    elapsed_ratio = min(step_index / max(max_steps, 1), 1.0)

    obs = np.array(
        [
            speed / max_speed,
            math.sin(math.radians(heading_error)),
            math.cos(math.radians(heading_error)),
            lateral / half_width,
            soc,
            battery_temp / battery_fault,
            (battery_derate - battery_temp) / max(battery_fault - battery_derate, 1.0),
            motor_temp / battery_fault,
            (battery_derate - motor_temp) / max(battery_fault - battery_derate, 1.0),
            (max_speed - speed) / max_speed,
            derating,
            torque_permitted,
            blocking,
            derate_fault,
            laps_remaining / max(target_laps, 1),
            elapsed_ratio,
            float(step_info.get("off_track", 0.0)),
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


def _has_blocking(active_faults: str) -> bool:
    from gokart.safety.faults import FAULT_REGISTRY
    from gokart.safety.types import FaultId, FaultSeverity

    for part in active_faults.split(","):
        name = part.strip()
        if not name:
            continue
        try:
            fault_id = FaultId(name)
        except ValueError:
            continue
        if FAULT_REGISTRY[fault_id].severity in {FaultSeverity.FAULT, FaultSeverity.CRITICAL}:
            return True
    return False
