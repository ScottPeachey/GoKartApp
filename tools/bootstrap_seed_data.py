#!/usr/bin/env python3
"""Generate seed component, vehicle, mode, and profile data with correct content hashes."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from gokart.config.hashing import content_hash
from gokart.config.schemas import (
    BatteryPack,
    Bms,
    Brake,
    Contactor,
    DcDcConverter,
    DriveMode,
    DriverProfile,
    HardwareLimits,
    LimitLayer,
    Motor,
    MotorController,
    SocCurvePoint,
    Tyre,
    VehicleConfig,
    Wheel,
)
from gokart.config.schemas.vehicle import ComponentRef, DrivetrainConfig
from gokart.config.store import (
    save_component,
    save_drive_mode,
    save_driver_profile,
    save_vehicle,
)
from gokart.units import kmh_to_mps


def _ref(component) -> ComponentRef:
    digest = content_hash(component.model_dump(mode="json"))
    return ComponentRef(component_id=component.id, content_hash=digest)


def build_v1_components() -> dict[str, object]:
    motor = Motor(
        id="v1_motor_5kw",
        manufacturer="Generic",
        model="BLDC 48V 5kW",
        date_added=date(2026, 1, 1),
        nominal_voltage_v=48.0,
        max_voltage_v=60.0,
        continuous_current_a=80.0,
        peak_current_a=150.0,
        continuous_power_w=3500.0,
        peak_power_w=5000.0,
        max_rpm=6000.0,
        continuous_torque_nm=12.0,
        peak_torque_nm=18.0,
        hardware_limits=HardwareLimits(
            max_motor_current_a=150.0,
            max_motor_rpm=6000.0,
            max_power_w=5000.0,
            max_temp_c=120.0,
        ),
    )
    controller = MotorController(
        id="v1_vesc_150a",
        manufacturer="VESC",
        model="75/300",
        date_added=date(2026, 1, 1),
        nominal_voltage_v=48.0,
        max_voltage_v=60.0,
        continuous_battery_current_a=100.0,
        peak_battery_current_a=150.0,
        continuous_motor_current_a=120.0,
        peak_motor_current_a=150.0,
        max_rpm=6000.0,
        max_regen_current_a=60.0,
        hardware_limits=HardwareLimits(
            max_motor_current_a=150.0,
            max_battery_current_a=150.0,
            max_motor_rpm=6000.0,
            max_regen_current_a=60.0,
            max_voltage_v=60.0,
            max_temp_c=85.0,
        ),
    )
    battery = BatteryPack(
        id="v1_pack_48v_40ah",
        manufacturer="Generic",
        model="LiFePO4 48V 40Ah",
        chemistry="lifepo4",
        date_added=date(2026, 1, 1),
        nominal_voltage_v=51.2,
        max_voltage_v=58.4,
        min_voltage_v=40.0,
        series_cells=16,
        parallel_cells=1,
        capacity_ah=40.0,
        energy_wh=2048.0,
        internal_resistance_ohm=0.015,
        continuous_discharge_current_a=80.0,
        peak_discharge_current_a=150.0,
        max_charge_current_a=40.0,
        max_regen_current_a=40.0,
        ocv_curve=[
            SocCurvePoint(soc=0.0, value=40.0),
            SocCurvePoint(soc=0.5, value=51.2),
            SocCurvePoint(soc=1.0, value=58.4),
        ],
        hardware_limits=HardwareLimits(
            max_battery_current_a=150.0,
            max_regen_current_a=40.0,
            max_power_w=7500.0,
            max_voltage_v=58.4,
            min_voltage_v=40.0,
            max_temp_c=60.0,
        ),
    )
    bms = Bms(
        id="v1_bms_150a",
        manufacturer="Generic",
        model="16S 150A BMS",
        date_added=date(2026, 1, 1),
        max_discharge_current_a=150.0,
        max_charge_current_a=40.0,
        max_pack_voltage_v=58.4,
        min_pack_voltage_v=40.0,
        hardware_limits=HardwareLimits(
            max_battery_current_a=150.0,
            max_regen_current_a=40.0,
            max_voltage_v=58.4,
            min_voltage_v=40.0,
            max_temp_c=60.0,
        ),
    )
    tyre = Tyre(
        id="v1_tyre_10x4",
        manufacturer="Generic",
        model="10x4.5-5",
        diameter_m=0.254,
        width_m=0.114,
        rolling_resistance_coefficient=0.015,
        dry_grip_coefficient=1.1,
        max_speed_mps=kmh_to_mps(80.0),
        max_load_kg=120.0,
        hardware_limits=HardwareLimits(max_speed_mps=kmh_to_mps(80.0)),
    )
    wheel = Wheel(
        id="v1_wheel_10in",
        manufacturer="Generic",
        model="10 inch kart wheel",
        diameter_m=0.254,
        circumference_m=0.798,
        mass_kg=2.5,
    )
    brake = Brake(
        id="v1_hydraulic_disc",
        manufacturer="Generic",
        model="Hydraulic disc",
        max_brake_torque_nm=400.0,
    )
    dcdc = DcDcConverter(
        id="v1_dcdc_12v",
        manufacturer="Generic",
        model="48-60V to 12V 10A",
        input_min_voltage_v=36.0,
        input_max_voltage_v=72.0,
        output_voltage_v=12.0,
        max_output_power_w=120.0,
    )
    contactor = Contactor(
        id="v1_contactor_200a",
        manufacturer="Generic",
        model="200A HV contactor",
        max_continuous_current_a=200.0,
        precharge_resistance_ohm=100.0,
    )
    return {
        "motor": motor,
        "controller": controller,
        "battery": battery,
        "bms": bms,
        "tyre": tyre,
        "wheel": wheel,
        "brake": brake,
        "dcdc": dcdc,
        "contactor": contactor,
    }


def build_v2_components() -> dict[str, object]:
    motor = Motor(
        id="v2_motor_10kw",
        manufacturer="Generic",
        model="BLDC 72V 10kW",
        date_added=date(2026, 1, 1),
        nominal_voltage_v=72.0,
        max_voltage_v=84.0,
        continuous_current_a=100.0,
        peak_current_a=180.0,
        continuous_power_w=6000.0,
        peak_power_w=10000.0,
        max_rpm=7000.0,
        continuous_torque_nm=14.0,
        peak_torque_nm=22.0,
        hardware_limits=HardwareLimits(
            max_motor_current_a=180.0,
            max_motor_rpm=7000.0,
            max_power_w=10000.0,
            max_temp_c=120.0,
        ),
    )
    controller = MotorController(
        id="v2_vesc_180a",
        manufacturer="VESC",
        model="100/400",
        date_added=date(2026, 1, 1),
        nominal_voltage_v=72.0,
        max_voltage_v=84.0,
        continuous_battery_current_a=120.0,
        peak_battery_current_a=180.0,
        continuous_motor_current_a=150.0,
        peak_motor_current_a=180.0,
        max_rpm=7000.0,
        max_regen_current_a=80.0,
        hardware_limits=HardwareLimits(
            max_motor_current_a=180.0,
            max_battery_current_a=180.0,
            max_motor_rpm=7000.0,
            max_regen_current_a=80.0,
            max_voltage_v=84.0,
            max_temp_c=85.0,
        ),
    )
    battery = BatteryPack(
        id="v2_pack_72v_50ah",
        manufacturer="Generic",
        model="NMC 72V 50Ah",
        chemistry="nmc",
        date_added=date(2026, 1, 1),
        nominal_voltage_v=75.6,
        max_voltage_v=84.0,
        min_voltage_v=60.0,
        series_cells=20,
        parallel_cells=1,
        capacity_ah=50.0,
        energy_wh=3780.0,
        internal_resistance_ohm=0.012,
        continuous_discharge_current_a=100.0,
        peak_discharge_current_a=180.0,
        max_charge_current_a=50.0,
        max_regen_current_a=50.0,
        hardware_limits=HardwareLimits(
            max_battery_current_a=180.0,
            max_regen_current_a=50.0,
            max_power_w=12000.0,
            max_voltage_v=84.0,
            min_voltage_v=60.0,
            max_temp_c=55.0,
        ),
    )
    bms = Bms(
        id="v2_bms_180a",
        manufacturer="Generic",
        model="20S 180A BMS",
        date_added=date(2026, 1, 1),
        max_discharge_current_a=180.0,
        max_charge_current_a=50.0,
        max_pack_voltage_v=84.0,
        min_pack_voltage_v=60.0,
        hardware_limits=HardwareLimits(
            max_battery_current_a=180.0,
            max_regen_current_a=50.0,
            max_voltage_v=84.0,
            min_voltage_v=60.0,
            max_temp_c=55.0,
        ),
    )
    return {
        "motor": motor,
        "controller": controller,
        "battery": battery,
        "bms": bms,
        "tyre": build_v1_components()["tyre"],
        "wheel": build_v1_components()["wheel"],
        "brake": build_v1_components()["brake"],
        "dcdc": build_v1_components()["dcdc"],
        "contactor": build_v1_components()["contactor"],
    }


def vehicle_limits_v1() -> LimitLayer:
    return LimitLayer(
        max_speed_mps=kmh_to_mps(45.0),
        max_motor_current_a=150.0,
        max_battery_current_a=150.0,
        max_regen_current_a=40.0,
        max_power_w=5000.0,
        max_motor_rpm=6000.0,
        max_accel_mps2=8.0,
        max_decel_mps2=10.0,
        max_gradient_rad=0.2,
    )


def vehicle_limits_v2() -> LimitLayer:
    return LimitLayer(
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


def build_vehicle(
    name: str,
    version: str,
    components: dict,
    limits: LimitLayer,
    drivetrain: DrivetrainConfig,
) -> VehicleConfig:
    return VehicleConfig(
        name=name,
        version=version,
        dry_mass_kg=85.0,
        battery_mass_kg=28.0,
        driver_mass_kg=80.0,
        max_vehicle_mass_kg=220.0,
        wheelbase_m=1.04,
        front_track_m=0.9,
        rear_track_m=0.95,
        cg_height_m=0.28,
        cg_longitudinal_m=0.52,
        drag_coefficient=0.85,
        frontal_area_m2=0.65,
        rolling_resistance_coefficient=0.015,
        wheel_radius_m=0.127,
        motor=_ref(components["motor"]),
        motor_controller=_ref(components["controller"]),
        battery=_ref(components["battery"]),
        bms=_ref(components["bms"]),
        front_tyre=_ref(components["tyre"]),
        rear_tyre=_ref(components["tyre"]),
        wheel=_ref(components["wheel"]),
        brake=_ref(components["brake"]),
        dcdc=_ref(components["dcdc"]),
        contactor=_ref(components["contactor"]),
        drivetrain=drivetrain,
        limits=limits,
    )


def build_modes() -> list[DriveMode]:
    return [
        DriveMode(
            name="Chill",
            limits=LimitLayer(max_speed_mps=kmh_to_mps(20.0)),
            throttle_curve="progressive",
            throttle_ramp_per_s=0.8,
            traction_limiter="aggressive",
            regen_strength=0.3,
        ),
        DriveMode(
            name="Default",
            limits=LimitLayer(max_speed_mps=kmh_to_mps(30.0)),
            throttle_curve="progressive",
            throttle_ramp_per_s=2.0,
            traction_limiter="moderate",
            regen_strength=0.5,
        ),
        DriveMode(
            name="Track",
            limits=LimitLayer(),
            throttle_curve="linear",
            throttle_ramp_per_s=5.0,
            traction_limiter="moderate",
            regen_strength=0.6,
        ),
        DriveMode(
            name="Drift",
            limits=LimitLayer(max_speed_mps=kmh_to_mps(35.0)),
            throttle_curve="aggressive",
            throttle_ramp_per_s=6.0,
            traction_limiter="off",
            regen_strength=0.2,
        ),
        DriveMode(
            name="RAW",
            limits=LimitLayer(),
            throttle_curve="linear",
            throttle_ramp_per_s=None,
            traction_limiter="off",
            regen_strength=1.0,
        ),
    ]


def build_profiles() -> list[DriverProfile]:
    return [
        DriverProfile(
            name="Owner",
            limits=LimitLayer(),
        ),
        DriverProfile(
            name="Junior",
            limits=LimitLayer(max_speed_mps=kmh_to_mps(25.0)),
        ),
    ]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    data = root / "data"

    for _key, component in build_v1_components().items():
        if hasattr(component, "component_type"):
            save_component(component, root=data, allow_overwrite=True)

    v2 = build_v2_components()
    for key in ("motor", "controller", "battery", "bms"):
        save_component(v2[key], root=data, allow_overwrite=True)

    v1 = build_v1_components()
    save_vehicle(
        build_vehicle(
            "Scott Kart V1",
            "V1.0",
            v1,
            vehicle_limits_v1(),
            DrivetrainConfig(motor_sprocket_teeth=12, axle_sprocket_teeth=52),
        ),
        root=data,
        allow_overwrite=True,
    )
    save_vehicle(
        build_vehicle(
            "Scott Kart V2",
            "V2.0",
            v2,
            vehicle_limits_v2(),
            DrivetrainConfig(motor_sprocket_teeth=14, axle_sprocket_teeth=56),
        ),
        root=data,
        allow_overwrite=True,
    )

    for mode in build_modes():
        save_drive_mode(mode, root=data, allow_overwrite=True)
    for profile in build_profiles():
        save_driver_profile(profile, root=data, allow_overwrite=True)

    print("Seed data written to", data)


if __name__ == "__main__":
    main()
