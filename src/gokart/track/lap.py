"""Track projection and lap timing."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from gokart.track.model import Track, TrackPoint
from gokart.track.queries import interpolate_centerline_at_s, start_finish_segment


@dataclass(frozen=True)
class TrackProjection:
    s_m: float
    lateral_m: float
    heading_rad: float
    gradient_rad: float
    curvature: float


@dataclass(frozen=True)
class CompletedLap:
    lap_number: int
    lap_time_s: float
    completed_at_time_s: float


@dataclass
class LapTimerState:
    lap_number: int = 1
    lap_time_s: float = 0.0
    last_lap_time_s: float = 0.0
    best_lap_time_s: float = 0.0
    has_best_lap: bool = False


@dataclass
class LapTimer:
    track: Track
    min_speed_mps: float = 2.0
    min_arm_distance_m: float = 25.0
    state: LapTimerState = field(default_factory=LapTimerState)
    completed_laps: list[CompletedLap] = field(default_factory=list)
    _prev_x: float | None = None
    _prev_y: float | None = None
    _armed: bool = False
    _distance_since_start: float = 0.0
    _lap_start_time_s: float = 0.0

    def __post_init__(self) -> None:
        width = self.track.start_finish.width_m or self.track.width_m
        self._sf = start_finish_segment(
            self.track.centerline,
            self.track.start_finish.s_m,
            width,
        )

    def reset(self, *, time_s: float = 0.0) -> None:
        self.state = LapTimerState()
        self.completed_laps.clear()
        self._prev_x = None
        self._prev_y = None
        self._armed = False
        self._distance_since_start = 0.0
        self._lap_start_time_s = time_s

    def update(self, time_s: float, x: float, y: float, speed_mps: float) -> dict[str, float]:
        if self._prev_x is not None:
            step_dist = math.hypot(x - self._prev_x, y - self._prev_y)
            if not self._armed:
                self._distance_since_start += step_dist
                if self._distance_since_start >= self.min_arm_distance_m:
                    self._armed = True
                    self._lap_start_time_s = time_s
            elif detect_sf_crossing(
                self._prev_x,
                self._prev_y,
                x,
                y,
                self._sf,
                self.track.direction,
                min_speed_mps=self.min_speed_mps,
                speed_mps=speed_mps,
            ):
                self._on_sf_cross(time_s)

        self._prev_x = x
        self._prev_y = y
        if self._armed:
            self.state.lap_time_s = max(0.0, time_s - self._lap_start_time_s)
        return self.telemetry()

    def telemetry(self) -> dict[str, float]:
        return {
            "lap_number": float(self.state.lap_number),
            "lap_time_s": self.state.lap_time_s,
            "last_lap_time_s": self.state.last_lap_time_s,
            "best_lap_time_s": self.state.best_lap_time_s if self.state.has_best_lap else 0.0,
        }

    def _on_sf_cross(self, time_s: float) -> None:
        lap_time = max(0.0, time_s - self._lap_start_time_s)
        if self.state.lap_number >= 1 and lap_time > 0.5:
            self.state.last_lap_time_s = lap_time
            if not self.state.has_best_lap or lap_time < self.state.best_lap_time_s:
                self.state.best_lap_time_s = lap_time
                self.state.has_best_lap = True
            self.completed_laps.append(
                CompletedLap(
                    lap_number=self.state.lap_number,
                    lap_time_s=lap_time,
                    completed_at_time_s=time_s,
                )
            )
            self.state.lap_number += 1
        self._lap_start_time_s = time_s
        self.state.lap_time_s = 0.0


def project_xy_to_track(centerline: list[TrackPoint], x: float, y: float) -> TrackProjection:
    """Project world coordinates onto the nearest centerline segment."""
    if not centerline:
        return TrackProjection(0.0, 0.0, 0.0, 0.0, 0.0)
    if len(centerline) == 1:
        point = centerline[0]
        return TrackProjection(
            s_m=point.s,
            lateral_m=0.0,
            heading_rad=0.0,
            gradient_rad=point.gradient_rad,
            curvature=point.curvature,
        )

    best_dist_sq = float("inf")
    best_s = centerline[0].s
    best_lateral = 0.0
    best_heading = 0.0
    best_gradient = centerline[0].gradient_rad
    best_curvature = centerline[0].curvature

    for index in range(1, len(centerline)):
        prev = centerline[index - 1]
        curr = centerline[index]
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
        best_heading = heading
        best_gradient = prev.gradient_rad + (curr.gradient_rad - prev.gradient_rad) * t
        best_curvature = prev.curvature + (curr.curvature - prev.curvature) * t

    return TrackProjection(
        s_m=best_s,
        lateral_m=best_lateral,
        heading_rad=best_heading,
        gradient_rad=best_gradient,
        curvature=best_curvature,
    )


def segments_intersect(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    x3: float,
    y3: float,
) -> bool:
    """Return True when two 2D segments intersect."""
    def orient(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
        return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)

    o1 = orient(x0, y0, x1, y1, x2, y2)
    o2 = orient(x0, y0, x1, y1, x3, y3)
    o3 = orient(x2, y2, x3, y3, x0, y0)
    o4 = orient(x2, y2, x3, y3, x1, y1)

    if o1 * o2 < 0 and o3 * o4 < 0:
        return True

    def on_segment(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> bool:
        return (
            min(ax, bx) - 1e-9 <= cx <= max(ax, bx) + 1e-9
            and min(ay, by) - 1e-9 <= cy <= max(ay, by) + 1e-9
        )

    if abs(o1) < 1e-9 and on_segment(x0, y0, x1, y1, x2, y2):
        return True
    if abs(o2) < 1e-9 and on_segment(x0, y0, x1, y1, x3, y3):
        return True
    if abs(o3) < 1e-9 and on_segment(x2, y2, x3, y3, x0, y0):
        return True
    if abs(o4) < 1e-9 and on_segment(x2, y2, x3, y3, x1, y1):
        return True
    return False


def detect_sf_crossing(
    prev_x: float,
    prev_y: float,
    curr_x: float,
    curr_y: float,
    sf_segment: dict[str, float],
    direction: str,
    *,
    min_speed_mps: float,
    speed_mps: float,
) -> bool:
    if speed_mps < min_speed_mps:
        return False
    if not segments_intersect(
        prev_x,
        prev_y,
        curr_x,
        curr_y,
        sf_segment["x1"],
        sf_segment["y1"],
        sf_segment["x2"],
        sf_segment["y2"],
    ):
        return False
    heading = sf_segment["heading_rad"]
    forward = (math.cos(heading), math.sin(heading))
    if direction == "counterclockwise":
        forward = (-forward[0], -forward[1])
    motion = (curr_x - prev_x, curr_y - prev_y)
    return motion[0] * forward[0] + motion[1] * forward[1] > 0.0


def spawn_pose_on_track(track: Track) -> tuple[float, float, float]:
    """Return x, y, heading_rad at the configured start/finish position."""
    return interpolate_centerline_at_s(track.centerline, track.start_finish.s_m)
