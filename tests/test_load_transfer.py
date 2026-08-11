"""Load transfer and per-axle grip tests."""

from __future__ import annotations

import math

import pytest

from gokart.physics.load_transfer import axle_normal_loads_n
from gokart.physics.steering import steering_angle_rad
from gokart.physics.tyres import (
    lateral_force_from_steering_n,
    saturate_axle_forces,
    saturate_traction_friction_circle,
)


def test_acceleration_transfers_load_to_rear() -> None:
    static = axle_normal_loads_n(
        mass_kg=200.0,
        wheelbase_m=1.04,
        cg_longitudinal_m=0.52,
        cg_height_m=0.28,
    )
    accel = axle_normal_loads_n(
        mass_kg=200.0,
        wheelbase_m=1.04,
        cg_longitudinal_m=0.52,
        cg_height_m=0.28,
        long_accel_mps2=4.0,
    )
    assert accel.rear_normal_n > static.rear_normal_n
    assert accel.front_normal_n < static.front_normal_n


def test_braking_transfers_load_to_front() -> None:
    static = axle_normal_loads_n(
        mass_kg=200.0,
        wheelbase_m=1.04,
        cg_longitudinal_m=0.52,
        cg_height_m=0.28,
    )
    braking = axle_normal_loads_n(
        mass_kg=200.0,
        wheelbase_m=1.04,
        cg_longitudinal_m=0.52,
        cg_height_m=0.28,
        long_accel_mps2=-5.0,
    )
    assert braking.front_normal_n > static.front_normal_n
    assert braking.rear_normal_n < static.rear_normal_n


def test_rear_drive_is_limited_by_rear_grip_only() -> None:
    loads = axle_normal_loads_n(
        mass_kg=193.0,
        wheelbase_m=1.04,
        cg_longitudinal_m=0.52,
        cg_height_m=0.28,
    )
    straight = saturate_axle_forces(
        drive_force_requested_n=2000.0,
        brake_force_n=0.0,
        lateral_force_n=0.0,
        axle_loads=loads,
        front_grip_coefficient=1.1,
        rear_grip_coefficient=0.8,
    )
    assert straight.traction_force_n == pytest.approx(loads.rear_normal_n * 0.8, rel=0.01)


def test_front_steering_reduces_available_rear_drive() -> None:
    mass = 193.0
    wheelbase = 1.04
    grip = 1.1
    steer = steering_angle_rad(1.0)
    lateral = lateral_force_from_steering_n(10.0, steer, wheelbase, mass)
    loads = axle_normal_loads_n(
        mass_kg=mass,
        wheelbase_m=wheelbase,
        cg_longitudinal_m=0.52,
        cg_height_m=0.28,
    )
    straight = saturate_axle_forces(
        1500.0,
        0.0,
        0.0,
        loads,
        grip,
        grip,
    )
    turning = saturate_axle_forces(
        1500.0,
        0.0,
        lateral,
        loads,
        grip,
        grip,
    )
    legacy = saturate_traction_friction_circle(1500.0, lateral, mass, grip)
    assert abs(turning.front_lateral_n) > 0.0
    assert turning.rear_longitudinal_n > 0.0
    assert turning.rear_longitudinal_n <= loads.rear_normal_n * grip + 1.0
    assert legacy.traction_force_n < straight.traction_force_n
