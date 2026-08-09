"""Tests for limit resolver."""

import pytest

from gokart.config.schemas.limits import (
    DriveModeLimits,
    DriverProfileLimits,
    HardwareLimits,
    VehicleLimits,
)
from gokart.limits.resolver import DeratingFactors, resolve_limits
from gokart.units import kmh_to_mps


def test_resolve_minimum_across_layers() -> None:
    hardware = HardwareLimits(
        max_speed_mps=kmh_to_mps(60.0),
        max_motor_current_a=150.0,
        max_battery_current_a=150.0,
        max_regen_current_a=40.0,
        max_power_w=5000.0,
        max_motor_rpm=6000.0,
        max_accel_mps2=8.0,
        max_decel_mps2=10.0,
        max_gradient_rad=0.2,
    )
    vehicle = VehicleLimits(
        max_speed_mps=kmh_to_mps(45.0),
        max_motor_current_a=140.0,
        max_battery_current_a=140.0,
        max_regen_current_a=35.0,
        max_power_w=4500.0,
        max_motor_rpm=5500.0,
        max_accel_mps2=7.0,
        max_decel_mps2=9.0,
        max_gradient_rad=0.15,
    )
    mode = DriveModeLimits(max_speed_mps=kmh_to_mps(30.0))
    profile = DriverProfileLimits(max_speed_mps=kmh_to_mps(25.0))

    effective = resolve_limits(hardware, vehicle, mode, profile)

    assert effective.max_speed_mps == pytest.approx(kmh_to_mps(25.0))
    assert effective.max_motor_current_a == 140.0
    assert effective.max_battery_current_a == 140.0


def test_junior_profile_caps_raw_mode_speed() -> None:
    hardware = HardwareLimits(
        max_speed_mps=kmh_to_mps(60.0),
        max_motor_current_a=180.0,
        max_battery_current_a=180.0,
        max_regen_current_a=50.0,
        max_power_w=10000.0,
        max_motor_rpm=7000.0,
        max_accel_mps2=10.0,
        max_decel_mps2=12.0,
        max_gradient_rad=0.25,
    )
    vehicle = VehicleLimits(
        max_speed_mps=kmh_to_mps(60.0),
        max_motor_current_a=180.0,
        max_battery_current_a=180.0,
        max_regen_current_a=50.0,
        max_power_w=10000.0,
        max_motor_rpm=7000.0,
        max_accel_mps2=10.0,
        max_decel_mps2=12.0,
        max_gradient_rad=0.25,
    )
    raw_mode = DriveModeLimits()  # unrestricted at mode layer
    junior = DriverProfileLimits(max_speed_mps=kmh_to_mps(25.0))

    effective = resolve_limits(hardware, vehicle, raw_mode, junior)
    assert effective.max_speed_mps == pytest.approx(kmh_to_mps(25.0))


def test_derating_reduces_limits() -> None:
    base = HardwareLimits(
        max_speed_mps=20.0,
        max_motor_current_a=100.0,
        max_battery_current_a=100.0,
        max_regen_current_a=30.0,
        max_power_w=4000.0,
        max_motor_rpm=5000.0,
        max_accel_mps2=6.0,
        max_decel_mps2=8.0,
        max_gradient_rad=0.1,
    )
    effective = resolve_limits(
        base,
        base,
        base,
        base,
        derating=DeratingFactors(motor_current=0.5, speed=0.8),
    )
    assert effective.max_motor_current_a == 50.0
    assert effective.max_speed_mps == 16.0
