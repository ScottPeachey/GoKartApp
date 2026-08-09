"""Tests for configuration store."""

from pathlib import Path

import pytest

from gokart.config.hashing import content_hash
from gokart.config.schemas import HardwareLimits, LimitLayer, Motor
from gokart.config.schemas.vehicle import ComponentRef, DrivetrainConfig, VehicleConfig
from gokart.config.store import (
    ImmutableConfigError,
    load_component,
    save_component,
    save_vehicle,
    verify_component_ref,
)


def _sample_motor() -> Motor:
    return Motor(
        id="test_motor",
        manufacturer="Test",
        model="M1",
        nominal_voltage_v=48.0,
        max_voltage_v=60.0,
        continuous_current_a=50.0,
        peak_current_a=100.0,
        continuous_power_w=2000.0,
        peak_power_w=4000.0,
        max_rpm=5000.0,
        continuous_torque_nm=8.0,
        peak_torque_nm=12.0,
        hardware_limits=HardwareLimits(max_motor_current_a=100.0, max_motor_rpm=5000.0),
    )


def test_component_round_trip(tmp_path: Path) -> None:
    motor = _sample_motor()
    digest = save_component(motor, root=tmp_path)
    loaded = load_component("motor", "test_motor", root=tmp_path)
    assert loaded == motor
    assert digest == content_hash(motor.model_dump(mode="json"))


def test_refuse_overwrite(tmp_path: Path) -> None:
    motor = _sample_motor()
    save_component(motor, root=tmp_path)
    with pytest.raises(ImmutableConfigError):
        save_component(motor, root=tmp_path)


def test_verify_component_ref(tmp_path: Path) -> None:
    motor = _sample_motor()
    save_component(motor, root=tmp_path)
    loaded = load_component("motor", "test_motor", root=tmp_path)
    digest = content_hash(loaded.model_dump(mode="json"))
    assert verify_component_ref("test_motor", digest, loaded)
    assert not verify_component_ref("test_motor", "0" * 64, loaded)


def test_vehicle_save_requires_new_version(tmp_path: Path) -> None:
    vehicle = VehicleConfig(
        name="Test Kart",
        version="V1.0",
        dry_mass_kg=80.0,
        battery_mass_kg=20.0,
        driver_mass_kg=75.0,
        max_vehicle_mass_kg=200.0,
        wheelbase_m=1.0,
        front_track_m=0.9,
        rear_track_m=0.9,
        cg_height_m=0.3,
        cg_longitudinal_m=0.5,
        drag_coefficient=0.8,
        frontal_area_m2=0.6,
        rolling_resistance_coefficient=0.015,
        wheel_radius_m=0.127,
        motor=ComponentRef(component_id="m", content_hash="a" * 64),
        motor_controller=ComponentRef(component_id="c", content_hash="b" * 64),
        battery=ComponentRef(component_id="b", content_hash="c" * 64),
        bms=ComponentRef(component_id="bms", content_hash="d" * 64),
        drivetrain=DrivetrainConfig(motor_sprocket_teeth=12, axle_sprocket_teeth=52),
        limits=LimitLayer(
            max_speed_mps=10.0,
            max_motor_current_a=100.0,
            max_battery_current_a=100.0,
        ),
    )
    save_vehicle(vehicle, root=tmp_path)
    with pytest.raises(ImmutableConfigError):
        save_vehicle(vehicle, root=tmp_path)
