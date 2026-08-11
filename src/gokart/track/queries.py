"""Track geometry queries for rendering and lap timing."""

from __future__ import annotations

import math

from gokart.track.model import TrackPoint


def interpolate_centerline_at_s(
    centerline: list[TrackPoint],
    s_m: float,
) -> tuple[float, float, float]:
    """Return x, y, and heading_rad at arc length s_m along the centerline."""
    if not centerline:
        return 0.0, 0.0, 0.0
    if s_m <= centerline[0].s:
        return _point_heading(centerline, 0)
    last = centerline[-1]
    if s_m >= last.s:
        return _point_heading(centerline, len(centerline) - 1)

    for index in range(1, len(centerline)):
        prev = centerline[index - 1]
        curr = centerline[index]
        if curr.s >= s_m:
            span = curr.s - prev.s
            if span <= 1e-9:
                return curr.x, curr.y, _heading_between(prev, curr)
            ratio = (s_m - prev.s) / span
            x = prev.x + (curr.x - prev.x) * ratio
            y = prev.y + (curr.y - prev.y) * ratio
            heading = _heading_between(prev, curr)
            return x, y, heading
    return last.x, last.y, _heading_between(centerline[-2], last)


def start_finish_segment(
    centerline: list[TrackPoint],
    s_m: float,
    width_m: float,
) -> dict[str, float]:
    """Perpendicular start/finish line segment across the track at s_m."""
    x, y, heading = interpolate_centerline_at_s(centerline, s_m)
    half = width_m / 2.0
    nx = -math.sin(heading)
    ny = math.cos(heading)
    return {
        "x1": x - nx * half,
        "y1": y - ny * half,
        "x2": x + nx * half,
        "y2": y + ny * half,
        "heading_rad": heading,
    }


def nearest_centerline_point(
    centerline: list[TrackPoint],
    x: float,
    y: float,
) -> tuple[TrackPoint, float]:
    """Return the nearest centerline point and squared distance."""
    if not centerline:
        raise ValueError("centerline must not be empty")

    best = centerline[0]
    best_dist = _point_distance_sq(best, x, y)
    for point in centerline[1:]:
        dist = _point_distance_sq(point, x, y)
        if dist < best_dist:
            best = point
            best_dist = dist
    return best, best_dist


def _point_heading(centerline: list[TrackPoint], index: int) -> tuple[float, float, float]:
    point = centerline[index]
    if index <= 0:
        heading = _heading_between(centerline[0], centerline[1])
    elif index >= len(centerline) - 1:
        heading = _heading_between(centerline[-2], centerline[-1])
    else:
        heading = _heading_between(centerline[index - 1], centerline[index + 1])
    return point.x, point.y, heading


def _heading_between(start: TrackPoint, end: TrackPoint) -> float:
    return math.atan2(end.y - start.y, end.x - start.x)


def _point_distance_sq(point: TrackPoint, x: float, y: float) -> float:
    dx = point.x - x
    dy = point.y - y
    return dx * dx + dy * dy
