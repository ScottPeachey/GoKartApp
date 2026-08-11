"""Track query helper tests."""

from __future__ import annotations

import math

import pytest

from gokart.track.model import TrackPoint
from gokart.track.queries import (
    interpolate_centerline_at_s,
    nearest_centerline_point,
    start_finish_segment,
)


def test_interpolate_centerline_at_s() -> None:
    centerline = [
        TrackPoint(x=0, y=0, s=0),
        TrackPoint(x=10, y=0, s=10),
        TrackPoint(x=20, y=0, s=20),
    ]
    x, y, heading = interpolate_centerline_at_s(centerline, 5)
    assert x == pytest.approx(5.0)
    assert y == pytest.approx(0.0)
    assert heading == pytest.approx(0.0)


def test_start_finish_segment_is_perpendicular() -> None:
    centerline = [
        TrackPoint(x=0, y=0, s=0),
        TrackPoint(x=10, y=0, s=10),
        TrackPoint(x=10, y=10, s=20),
    ]
    segment = start_finish_segment(centerline, 5, width_m=8)
    dx = segment["x2"] - segment["x1"]
    dy = segment["y2"] - segment["y1"]
    assert math.hypot(dx, dy) == pytest.approx(8.0)


def test_nearest_centerline_point() -> None:
    centerline = [
        TrackPoint(x=0, y=0, s=0),
        TrackPoint(x=10, y=0, s=10),
        TrackPoint(x=20, y=0, s=20),
    ]
    point, dist = nearest_centerline_point(centerline, 12, 1)
    assert point.s == pytest.approx(10)
    assert dist == pytest.approx(5)
