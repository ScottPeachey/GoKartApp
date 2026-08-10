"""Tyre friction-circle tests."""

from __future__ import annotations

import math

import pytest

from gokart.physics.steering import MAX_STEER_ANGLE_DEG, steering_angle_rad
from gokart.physics.tyres import (
    cornering_speed_limit_mps,
    lateral_force_from_steering_n,
    saturate_traction_friction_circle,
    saturate_traction_force,
)


def test_friction_circle_reduces_longitudinal_grip_when_turning() -> None:
    mass = 150.0
    grip = 1.1
    steer = steering_angle_rad(1.0)
    lateral = lateral_force_from_steering_n(12.0, steer, wheelbase_m=1.1, mass_kg=mass)
    straight = saturate_traction_force(500.0, mass, grip)
    turning = saturate_traction_friction_circle(500.0, lateral, mass, grip)
    assert abs(lateral) > 0.0
    assert turning.traction_force_n < straight.traction_force_n


def test_cornering_speed_limit_matches_bicycle_model() -> None:
    grip = 1.1
    wheelbase = 1.1
    steer = math.radians(MAX_STEER_ANGLE_DEG)
    limit = cornering_speed_limit_mps(steer, wheelbase, grip)
    assert limit is not None
    lat_accel = limit * limit * math.tan(steer) / wheelbase
    assert lat_accel == pytest.approx(grip * 9.80665, rel=1e-3)
