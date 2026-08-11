"""Track geometry: resampling, curvature, boundaries, scaling."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from gokart.track.model import BoundaryPoint, TrackBBox, TrackPoint

KART_LENGTH_MIN_M = 1000.0
KART_LENGTH_MAX_M = 1600.0
F1_LENGTH_MIN_M = 3300.0
F1_LENGTH_MAX_M = 7000.0
DEFAULT_RESAMPLE_SPACING_M = 1.0


@dataclass(frozen=True)
class XYPoint:
    x: float
    y: float
    z: float = 0.0


def compute_target_length_m(source_length_m: float) -> float:
    """Map an F1 circuit length onto the kart track band (1000–1600 m)."""
    if source_length_m <= 0:
        raise ValueError("source_length_m must be positive")
    span = F1_LENGTH_MAX_M - F1_LENGTH_MIN_M
    if span <= 0:
        return KART_LENGTH_MIN_M
    ratio = (source_length_m - F1_LENGTH_MIN_M) / span
    ratio = max(0.0, min(1.0, ratio))
    return KART_LENGTH_MIN_M + ratio * (KART_LENGTH_MAX_M - KART_LENGTH_MIN_M)


def polyline_length(points: list[XYPoint]) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(points)):
        dx = points[i].x - points[i - 1].x
        dy = points[i].y - points[i - 1].y
        dz = points[i].z - points[i - 1].z
        total += math.sqrt(dx * dx + dy * dy + dz * dz)
    return total


def _dedupe_consecutive(points: list[XYPoint], *, tol: float = 1e-6) -> list[XYPoint]:
    if not points:
        return []
    out = [points[0]]
    for point in points[1:]:
        prev = out[-1]
        if (
            abs(point.x - prev.x) > tol
            or abs(point.y - prev.y) > tol
            or abs(point.z - prev.z) > tol
        ):
            out.append(point)
    return out


def close_polyline(points: list[XYPoint], *, tol: float = 1.0) -> list[XYPoint]:
    """Ensure the polyline is closed (first point repeated at end if needed)."""
    if len(points) < 2:
        return points
    deduped = _dedupe_consecutive(points)
    if len(deduped) < 2:
        return deduped
    first = deduped[0]
    last = deduped[-1]
    if math.hypot(first.x - last.x, first.y - last.y) > tol:
        deduped.append(XYPoint(first.x, first.y, first.z))
    return deduped


def scale_polyline(points: list[XYPoint], scale: float) -> list[XYPoint]:
    return [XYPoint(p.x * scale, p.y * scale, p.z * scale) for p in points]


def resample_polyline(
    points: list[XYPoint],
    spacing_m: float = DEFAULT_RESAMPLE_SPACING_M,
) -> list[XYPoint]:
    """Resample a polyline to approximately uniform arc-length spacing."""
    if len(points) < 2:
        return list(points)
    if spacing_m <= 0:
        raise ValueError("spacing_m must be positive")

    xs = np.array([p.x for p in points], dtype=float)
    ys = np.array([p.y for p in points], dtype=float)
    zs = np.array([p.z for p in points], dtype=float)
    seg = np.sqrt(np.diff(xs) ** 2 + np.diff(ys) ** 2 + np.diff(zs) ** 2)
    cumulative = np.concatenate(([0.0], np.cumsum(seg)))
    total = cumulative[-1]
    if total <= spacing_m:
        return list(points)

    sample_s = np.arange(0.0, total, spacing_m)
    if sample_s.size == 0 or sample_s[-1] < total - 1e-6:
        sample_s = np.append(sample_s, total)

    sx = np.interp(sample_s, cumulative, xs)
    sy = np.interp(sample_s, cumulative, ys)
    sz = np.interp(sample_s, cumulative, zs)
    return [XYPoint(float(x), float(y), float(z)) for x, y, z in zip(sx, sy, sz, strict=True)]


def compute_curvature_profile(points: list[XYPoint]) -> list[float]:
    """Signed curvature (1/m) from a polyline using three-point Menger formula."""
    n = len(points)
    if n < 3:
        return [0.0] * n

    curvatures: list[float] = [0.0] * n
    for i in range(1, n - 1):
        p0 = points[i - 1]
        p1 = points[i]
        p2 = points[i + 1]
        ax, ay = p1.x - p0.x, p1.y - p0.y
        bx, by = p2.x - p1.x, p2.y - p1.y
        cx, cy = p2.x - p0.x, p2.y - p0.y
        cross = ax * by - ay * bx
        a_len = math.hypot(ax, ay)
        b_len = math.hypot(bx, by)
        c_len = math.hypot(cx, cy)
        denom = a_len * b_len * c_len
        if denom > 1e-9:
            curvatures[i] = 2.0 * cross / denom
    curvatures[0] = curvatures[1]
    curvatures[-1] = curvatures[-2]
    return curvatures


def compute_arc_lengths(points: list[XYPoint]) -> list[float]:
    if not points:
        return []
    s_values = [0.0]
    for i in range(1, len(points)):
        dx = points[i].x - points[i - 1].x
        dy = points[i].y - points[i - 1].y
        dz = points[i].z - points[i - 1].z
        s_values.append(s_values[-1] + math.sqrt(dx * dx + dy * dy + dz * dz))
    return s_values


def compute_gradient_profile(points: list[XYPoint], arc_lengths: list[float]) -> list[float]:
    """Gradient angle (radians) from elevation change along arc length."""
    n = len(points)
    if n < 2:
        return [0.0] * n

    gradients: list[float] = [0.0] * n
    for i in range(1, n):
        ds = arc_lengths[i] - arc_lengths[i - 1]
        if ds > 1e-9:
            dz = points[i].z - points[i - 1].z
            gradients[i] = math.atan2(dz, ds)
    gradients[0] = gradients[1]
    return gradients


def offset_boundaries(
    points: list[XYPoint],
    width_m: float,
) -> tuple[list[BoundaryPoint], list[BoundaryPoint]]:
    """Offset centerline by half width along normals (inside shorter on corners)."""
    if len(points) < 2:
        return [], []
    if width_m <= 0:
        raise ValueError("width_m must be positive")

    half = width_m / 2.0
    inner: list[BoundaryPoint] = []
    outer: list[BoundaryPoint] = []
    n = len(points)

    for i in range(n):
        if i == 0:
            dx = points[1].x - points[0].x
            dy = points[1].y - points[0].y
        elif i == n - 1:
            dx = points[i].x - points[i - 1].x
            dy = points[i].y - points[i - 1].y
        else:
            dx = points[i + 1].x - points[i - 1].x
            dy = points[i + 1].y - points[i - 1].y
        length = math.hypot(dx, dy)
        if length < 1e-9:
            nx, ny = 0.0, 1.0
        else:
            nx, ny = -dy / length, dx / length
        px, py = points[i].x, points[i].y
        inner.append(BoundaryPoint(x=px - nx * half, y=py - ny * half))
        outer.append(BoundaryPoint(x=px + nx * half, y=py + ny * half))
    return inner, outer


def compute_bbox(
    points: list[XYPoint],
    inner: list[BoundaryPoint],
    outer: list[BoundaryPoint],
) -> TrackBBox:
    xs = [p.x for p in points] + [p.x for p in inner] + [p.x for p in outer]
    ys = [p.y for p in points] + [p.y for p in inner] + [p.y for p in outer]
    if not xs:
        return TrackBBox(x_min=0.0, y_min=0.0, x_max=0.0, y_max=0.0)
    return TrackBBox(x_min=min(xs), y_min=min(ys), x_max=max(xs), y_max=max(ys))


def build_track_points(points: list[XYPoint]) -> list[TrackPoint]:
    arc_lengths = compute_arc_lengths(points)
    curvatures = compute_curvature_profile(points)
    gradients = compute_gradient_profile(points, arc_lengths)
    return [
        TrackPoint(
            x=point.x,
            y=point.y,
            z=point.z,
            s=s,
            curvature=curvature,
            gradient_rad=gradient,
        )
        for point, s, curvature, gradient in zip(
            points, arc_lengths, curvatures, gradients, strict=True
        )
    ]
