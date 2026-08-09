"""Tests for configuration validation."""

from pathlib import Path

import pytest

from gokart.config.schemas import DriveMode, LimitLayer, Motor
from gokart.config.schemas.limits import HardwareLimits
from gokart.config.store import load_drive_mode, load_driver_profile, load_vehicle
from gokart.config.validation import (
    validate_intra_component,
    validate_limit_hierarchy,
    validate_vehicle_config,
)
from gokart.limits.resolver import resolve_limits
from gokart.units import kmh_to_mps


def test_intra_component_rejects_invalid_peak_current() -> None:
    with pytest.raises(ValueError, match="peak_current_a"):
        Motor(
            id="bad",
            manufacturer="T",
            model="M",
            nominal_voltage_v=48.0,
            max_voltage_v=60.0,
            continuous_current_a=100.0,
            peak_current_a=50.0,
            continuous_power_w=2000.0,
            peak_power_w=3000.0,
            max_rpm=5000.0,
            continuous_torque_nm=8.0,
            peak_torque_nm=12.0,
            hardware_limits=HardwareLimits(),
        )


def test_intra_component_map_rpm_reject() -> None:
    motor = Motor(
        id="bad_map",
        manufacturer="T",
        model="M",
        nominal_voltage_v=48.0,
        max_voltage_v=60.0,
        continuous_current_a=50.0,
        peak_current_a=100.0,
        continuous_power_w=2000.0,
        peak_power_w=4000.0,
        max_rpm=5000.0,
        continuous_torque_nm=8.0,
        peak_torque_nm=12.0,
        torque_map=[{"rpm": 6000.0, "torque_nm": 10.0, "efficiency": 0.9}],
        hardware_limits=HardwareLimits(),
    )
    result = validate_intra_component(motor)
    assert not result.ok
    assert result.violations[0].limiting_layer == "motor"


def test_hierarchy_violation_reports_vehicle_layer() -> None:
    hardware = HardwareLimits(max_speed_mps=kmh_to_mps(40.0))
    from gokart.config.schemas.vehicle import ComponentRef, DrivetrainConfig, VehicleConfig

    vehicle = VehicleConfig(
        name="X",
        version="V1",
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
        limits=LimitLayer(max_speed_mps=kmh_to_mps(50.0)),
    )
    result = validate_limit_hierarchy(hardware=hardware, vehicle=vehicle)
    assert not result.ok
    assert result.violations[0].limiting_layer == "hardware"


def test_seed_v1_vehicle_validates() -> None:
    root = Path(__file__).resolve().parents[1]
    vehicle = load_vehicle("Scott Kart V1", "V1.0", root=root / "data")
    result = validate_vehicle_config(vehicle, data_root=root / "data")
    assert result.ok, [v.message for v in result.violations]


def test_mode_above_vehicle_limit_rejected() -> None:
    root = Path(__file__).resolve().parents[1]
    vehicle = load_vehicle("Scott Kart V1", "V1.0", root=root / "data")
    bad_mode = DriveMode(
        name="TooFast",
        limits=LimitLayer(max_speed_mps=kmh_to_mps(999.0)),
    )
    result = validate_vehicle_config(vehicle, data_root=root / "data", mode=bad_mode)
    assert not result.ok
    assert any(v.limiting_layer == "vehicle" for v in result.violations)


def test_junior_raw_runtime_speed_cap() -> None:
    root = Path(__file__).resolve().parents[1]
    vehicle = load_vehicle("Scott Kart V2", "V2.0", root=root / "data")
    raw = load_drive_mode("RAW", root=root / "data")
    junior = load_driver_profile("Junior", root=root / "data")
    result = validate_vehicle_config(vehicle, data_root=root / "data", mode=raw, profile=junior)
    assert result.ok

    from gokart.config.store import load_component
    from gokart.config.validation import hardware_limits_from_components

    motor = load_component("motor", vehicle.motor.component_id, root=root / "data")
    controller = load_component(
        "motor_controller", vehicle.motor_controller.component_id, root=root / "data"
    )
    battery = load_component("battery", vehicle.battery.component_id, root=root / "data")
    bms = load_component("bms", vehicle.bms.component_id, root=root / "data")
    hardware = hardware_limits_from_components(motor, controller, battery, bms)

    effective = resolve_limits(hardware, vehicle.limits, raw.limits, junior.limits)
    assert effective.max_speed_mps == pytest.approx(junior.limits.max_speed_mps)
