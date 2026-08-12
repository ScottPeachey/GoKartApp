"""Racing line generation from track centerline."""

from __future__ import annotations

import math
from dataclasses import dataclass

from gokart.track.model import Track, TrackPoint
from gokart.track.queries import interpolate_centerline_at_s


@dataclass(frozen=True)
class RacingLinePoint:
    x: float
    y: float
    s: float
    curvature: float
    gradient_rad: float


def build_racing_line(track: Track, *, apex_offset_m: float = 0.85) -> list[RacingLinePoint]:
    """Build a curvature-smoothed racing line inside the track corridor."""
    if not track.centerline:
        return []

    direction_sign = 1.0 if track.direction == "clockwise" else -1.0
    line: list[RacingLinePoint] = []
    for index, point in enumerate(track.centerline):
        heading = _heading_at(track.centerline, index)
        curvature = abs(point.curvature)
        blend = min(1.0, curvature * 60.0)
        offset = direction_sign * apex_offset_m * blend
        nx = -math.sin(heading)
        ny = math.cos(heading)
        half_width = track.width_m * 0.45
        offset = max(-half_width, min(half_width, offset))
        line.append(
            RacingLinePoint(
                x=point.x + nx * offset,
                y=point.y + ny * offset,
                s=point.s,
                curvature=point.curvature,
                gradient_rad=point.gradient_rad,
            )
        )
    return line


def point_at_s(line: list[RacingLinePoint], s_m: float, track_length_m: float) -> RacingLinePoint:
    """Interpolate a racing-line point at arc length s (wraps on closed loop)."""
    if not line:
        return RacingLinePoint(0.0, 0.0, 0.0, 0.0, 0.0)
    if track_length_m <= 0.0:
        return line[0]

    s_wrapped = s_m % track_length_m
    if s_wrapped < line[0].s:
        return line[0]
    for index in range(1, len(line)):
        prev = line[index - 1]
        curr = line[index]
        if curr.s >= s_wrapped:
            span = curr.s - prev.s
            if span <= 1e-9:
                return curr
            ratio = (s_wrapped - prev.s) / span
            return RacingLinePoint(
                x=prev.x + (curr.x - prev.x) * ratio,
                y=prev.y + (curr.y - prev.y) * ratio,
                s=s_wrapped,
                curvature=prev.curvature + (curr.curvature - prev.curvature) * ratio,
                gradient_rad=prev.gradient_rad + (curr.gradient_rad - prev.gradient_rad) * ratio,
            )
    return line[-1]


def project_to_line(line: list[RacingLinePoint], x: float, y: float) -> tuple[float, float]:
    """Return arc length and lateral offset on the racing line."""
    if not line:
        return 0.0, 0.0
    if len(line) == 1:
        return line[0].s, math.hypot(x - line[0].x, y - line[0].y)

    best_dist_sq = float("inf")
    best_s = line[0].s
    best_lateral = 0.0
    for index in range(1, len(line)):
        prev = line[index - 1]
        curr = line[index]
        dx = curr.x - prev.x
        dy = curr.y - prev.y
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq <= 1e-12:
            continue
        t = ((x - prev.x) * dx + (y - prev.y) * dy) / seg_len_sq
        t = max(0.0, min(1.0, t))
        proj_x = prev.x + dx * t
        proj_y = prev.y + dy * t
        dist_sq = (x - proj_x) ** 2 + (y - proj_y) ** 2
        if dist_sq >= best_dist_sq:
            continue
        heading = math.atan2(dy, dx)
        lateral = (x - proj_x) * (-math.sin(heading)) + (y - proj_y) * math.cos(heading)
        best_dist_sq = dist_sq
        best_s = prev.s + (curr.s - prev.s) * t
        best_lateral = lateral
    return best_s, best_lateral


def _heading_at(centerline: list[TrackPoint], index: int) -> float:
    if index <= 0:
        return _heading_between(centerline[0], centerline[1])
    if index >= len(centerline) - 1:
        return _heading_between(centerline[-2], centerline[-1])
    return _heading_between(centerline[index - 1], centerline[index + 1])


def _heading_between(start: TrackPoint, end: TrackPoint) -> float:
    return math.atan2(end.y - start.y, end.x - start.x)


def spawn_on_racing_line(track: Track) -> tuple[float, float, float]:
    """Spawn pose on the racing line at start/finish."""
    line = build_racing_line(track)
    if line:
        point = point_at_s(line, track.start_finish.s_m, track.length_m)
        _, _, heading = interpolate_centerline_at_s(track.centerline, track.start_finish.s_m)
        return point.x, point.y, heading
    return interpolate_centerline_at_s(track.centerline, track.start_finish.s_m)
