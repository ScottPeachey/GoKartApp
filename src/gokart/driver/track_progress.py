"""Monotonic arc-length tracking along a track centerline."""

from __future__ import annotations

import math

from gokart.track.lap import project_xy_to_track
from gokart.track.model import Track


def advance_track_progress(
    track: Track,
    *,
    x: float,
    y: float,
    speed_mps: float,
    heading_rad: float,
    prev_s_m: float | None,
    dt: float,
) -> tuple[float, float, float]:
    """Return monotonic lap s, lateral offset, and local path heading."""
    projection = project_xy_to_track(track.centerline, x, y)
    raw_s = projection.s_m
    lateral_m = projection.lateral_m
    track_len = track.length_m
    if track_len <= 0.0 or prev_s_m is None:
        return raw_s, lateral_m, projection.heading_rad

    delta = _shortest_delta(raw_s, prev_s_m, track_len)
    aligned = math.cos(heading_rad - projection.heading_rad)
    if speed_mps > 0.8:
        min_forward = speed_mps * dt * 0.4
        if delta < -2.0 or (aligned > 0.15 and delta < min_forward * 0.3):
            delta = max(min_forward, speed_mps * dt)
    elif speed_mps > 0.15 and aligned > 0.4 and delta < 0.0:
        delta = speed_mps * dt

    s_m = prev_s_m + delta
    if s_m >= track_len:
        s_m -= track_len
    elif s_m < 0.0:
        s_m += track_len
    return s_m, lateral_m, projection.heading_rad


def _shortest_delta(raw_s: float, prev_s: float, track_len: float) -> float:
    delta = raw_s - prev_s
    while delta > track_len * 0.5:
        delta -= track_len
    while delta < -track_len * 0.5:
        delta += track_len
    return delta
