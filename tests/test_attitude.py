"""Attitude estimation tests."""

from __future__ import annotations

import math

import pytest

from gokart.physics.attitude import load_transfer_long_accel_mps2, vehicle_attitude_deg


def test_load_transfer_accel_zero_when_stationary_braking() -> None:
    assert load_transfer_long_accel_mps2(0.0, -8.0) == 0.0
    assert load_transfer_long_accel_mps2(2.0, -4.0) == pytest.approx(-4.0)


def test_braking_adds_nose_down_pitch() -> None:
    pitch, roll = vehicle_attitude_deg(
        gradient_rad=0.0,
        long_accel_mps2=-4.0,
        lat_accel_mps2=0.0,
        wheelbase_m=1.04,
        cg_height_m=0.28,
        speed_mps=5.0,
    )
    assert pitch < 0.0
    assert roll == pytest.approx(0.0)


def test_road_gradient_and_lateral_roll() -> None:
    pitch, roll = vehicle_attitude_deg(
        gradient_rad=math.radians(5.0),
        long_accel_mps2=0.0,
        lat_accel_mps2=2.0,
        wheelbase_m=1.04,
        cg_height_m=0.28,
        speed_mps=10.0,
    )
    assert pitch == pytest.approx(5.0, abs=0.1)
    assert roll > 0.0
