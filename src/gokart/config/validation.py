"""Cross-component and limit-hierarchy validation."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from gokart.config.schemas import (
    BatteryPack,
    Bms,
    Clutch,
    ComponentBase,
    DriveMode,
    DriverProfile,
    Engine,
    HardwareLimits,
    LimitLayer,
    Motor,
    MotorController,
    VehicleConfig,
)
from gokart.config.store import (
    ConfigStoreError,
    load_component,
    verify_component_ref,
)
from gokart.units import rpm_to_rads

LIMIT_FIELDS = (
    "max_speed_mps",
    "max_motor_current_a",
    "max_battery_current_a",
    "max_regen_current_a",
    "max_power_w",
    "max_motor_rpm",
    "max_accel_mps2",
    "max_decel_mps2",
    "max_gradient_rad",
)


@dataclass
class Violation:
    field: str
    constraint: str
    limiting_layer: str
    limiting_value: Any
    message: str


@dataclass
class ValidationResult:
    ok: bool
    violations: list[Violation] = field(default_factory=list)

    def add(
        self,
        *,
        field_name: str,
        constraint: str,
        limiting_layer: str,
        limiting_value: Any,
        message: str,
    ) -> None:
        self.violations.append(
            Violation(
                field=field_name,
                constraint=constraint,
                limiting_layer=limiting_layer,
                limiting_value=limiting_value,
                message=message,
            )
        )
        self.ok = False


def _layer_value(layer: LimitLayer, field_name: str) -> float | None:
    return getattr(layer, field_name)


def _check_layer_le(
    result: ValidationResult,
    *,
    child: LimitLayer,
    parent: LimitLayer,
    child_name: str,
    parent_name: str,
) -> None:
    for field_name in LIMIT_FIELDS:
        child_value = _layer_value(child, field_name)
        parent_value = _layer_value(parent, field_name)
        if child_value is None or parent_value is None:
            continue
        if child_value > parent_value:
            result.add(
                field_name=field_name,
                constraint=f"{child_name} <= {parent_name}",
                limiting_layer=parent_name,
                limiting_value=parent_value,
                message=(
                    f"{child_name} {field_name} ({child_value}) exceeds "
                    f"{parent_name} limit ({parent_value})"
                ),
            )


def aggregate_hardware_limits(*layers: HardwareLimits) -> HardwareLimits:
    aggregated: dict[str, float | None] = {}
    for field_name in LIMIT_FIELDS:
        values = [
            getattr(layer, field_name) for layer in layers if getattr(layer, field_name) is not None
        ]
        aggregated[field_name] = min(values) if values else None

    max_voltage_values = [
        layer.max_voltage_v for layer in layers if layer.max_voltage_v is not None
    ]
    min_voltage_values = [
        layer.min_voltage_v for layer in layers if layer.min_voltage_v is not None
    ]
    max_temp_values = [layer.max_temp_c for layer in layers if layer.max_temp_c is not None]

    aggregated["max_voltage_v"] = min(max_voltage_values) if max_voltage_values else None
    aggregated["min_voltage_v"] = max(min_voltage_values) if min_voltage_values else None
    aggregated["max_temp_c"] = min(max_temp_values) if max_temp_values else None
    return HardwareLimits(**aggregated)


def hardware_limits_from_components(
    motor: Motor,
    controller: MotorController,
    battery: BatteryPack,
    bms: Bms,
) -> HardwareLimits:
    motor_hw = motor.hardware_limits
    motor_limits = motor.hardware_limits.model_copy(
        update={
            "max_motor_current_a": motor_hw.max_motor_current_a or motor.peak_current_a,
            "max_motor_rpm": motor.hardware_limits.max_motor_rpm or motor.max_rpm,
            "max_power_w": motor.hardware_limits.max_power_w or motor.peak_power_w,
            "max_temp_c": motor.hardware_limits.max_temp_c or motor.max_temp_c,
        }
    )
    controller_limits = controller.hardware_limits.model_copy(
        update={
            "max_motor_current_a": controller.hardware_limits.max_motor_current_a
            or controller.peak_motor_current_a,
            "max_battery_current_a": controller.hardware_limits.max_battery_current_a
            or controller.peak_battery_current_a,
            "max_motor_rpm": controller.hardware_limits.max_motor_rpm or controller.max_rpm,
            "max_regen_current_a": controller.hardware_limits.max_regen_current_a
            or controller.max_regen_current_a,
            "max_voltage_v": controller.hardware_limits.max_voltage_v or controller.max_voltage_v,
            "max_temp_c": controller.hardware_limits.max_temp_c or controller.max_temp_c,
        }
    )
    battery_limits = battery.hardware_limits.model_copy(
        update={
            "max_battery_current_a": battery.hardware_limits.max_battery_current_a
            or battery.peak_discharge_current_a,
            "max_regen_current_a": battery.hardware_limits.max_regen_current_a
            or battery.max_regen_current_a,
            "max_power_w": battery.hardware_limits.max_power_w
            or battery.nominal_voltage_v * battery.peak_discharge_current_a,
            "max_voltage_v": battery.hardware_limits.max_voltage_v or battery.max_voltage_v,
            "min_voltage_v": battery.hardware_limits.min_voltage_v or battery.min_voltage_v,
            "max_temp_c": battery.hardware_limits.max_temp_c or battery.max_cell_temp_c,
        }
    )
    bms_limits = bms.hardware_limits.model_copy(
        update={
            "max_battery_current_a": bms.hardware_limits.max_battery_current_a
            or bms.max_discharge_current_a,
            "max_regen_current_a": bms.hardware_limits.max_regen_current_a
            or bms.max_charge_current_a,
            "max_voltage_v": bms.hardware_limits.max_voltage_v or bms.max_pack_voltage_v,
            "min_voltage_v": bms.hardware_limits.min_voltage_v or bms.min_pack_voltage_v,
            "max_temp_c": bms.hardware_limits.max_temp_c or bms.max_temp_c,
        }
    )
    return aggregate_hardware_limits(motor_limits, controller_limits, battery_limits, bms_limits)


def hardware_limits_from_engine(engine: Engine, clutch: Clutch) -> HardwareLimits:
    engine_limits = engine.hardware_limits.model_copy(
        update={
            "max_motor_rpm": engine.hardware_limits.max_motor_rpm or engine.max_rpm,
            "max_power_w": engine.hardware_limits.max_power_w or engine.peak_power_w,
            "max_temp_c": engine.hardware_limits.max_temp_c or engine.max_temp_c,
            "max_motor_current_a": engine.hardware_limits.max_motor_current_a or 150.0,
            "max_battery_current_a": engine.hardware_limits.max_battery_current_a or 150.0,
            "max_regen_current_a": engine.hardware_limits.max_regen_current_a or 0.0,
        }
    )
    clutch_limits = clutch.hardware_limits.model_copy(
        update={
            "max_power_w": clutch.hardware_limits.max_power_w
            or engine.peak_power_w,
        }
    )
    return aggregate_hardware_limits(engine_limits, clutch_limits)


def validate_intra_component(component: ComponentBase) -> ValidationResult:
    """Layer 2: intra-component sanity (pydantic handles most; extra checks here)."""
    result = ValidationResult(ok=True)
    if isinstance(component, Motor) and component.torque_map:
        for point in component.torque_map:
            if point.rpm > component.max_rpm:
                result.add(
                    field_name="torque_map.rpm",
                    constraint="map rpm <= motor.max_rpm",
                    limiting_layer="motor",
                    limiting_value=component.max_rpm,
                    message=f"Torque map RPM {point.rpm} exceeds motor max_rpm {component.max_rpm}",
                )
    if isinstance(component, Engine) and component.torque_map:
        for point in component.torque_map:
            if point.rpm > component.max_rpm:
                result.add(
                    field_name="torque_map.rpm",
                    constraint="map rpm <= engine.max_rpm",
                    limiting_layer="engine",
                    limiting_value=component.max_rpm,
                    message=f"Torque map RPM {point.rpm} exceeds engine max_rpm {component.max_rpm}",
                )
    return result


def validate_cross_component(
    vehicle: VehicleConfig,
    motor: Motor,
    controller: MotorController,
    battery: BatteryPack,
    bms: Bms,
) -> ValidationResult:
    """Layer 3: cross-component compatibility."""
    result = ValidationResult(ok=True)

    if battery.max_voltage_v > controller.max_voltage_v:
        result.add(
            field_name="battery.max_voltage_v",
            constraint="battery.max_voltage_v <= controller.max_voltage_v",
            limiting_layer="motor_controller",
            limiting_value=controller.max_voltage_v,
            message=(
                f"Battery max voltage {battery.max_voltage_v} V exceeds controller "
                f"limit {controller.max_voltage_v} V"
            ),
        )

    if bms.max_discharge_current_a > controller.peak_battery_current_a:
        result.add(
            field_name="bms.max_discharge_current_a",
            constraint="bms discharge <= controller peak battery current",
            limiting_layer="motor_controller",
            limiting_value=controller.peak_battery_current_a,
            message=(
                f"BMS discharge limit {bms.max_discharge_current_a} A exceeds controller "
                f"peak battery current {controller.peak_battery_current_a} A"
            ),
        )

    gear_ratio = vehicle.drivetrain.axle_sprocket_teeth / vehicle.drivetrain.motor_sprocket_teeth
    kinematic_max_speed_mps = (
        motor.max_rpm * vehicle.wheel_radius_m * 2.0 * math.pi / (60.0 * gear_ratio)
    )
    vehicle_max = vehicle.limits.max_speed_mps
    if vehicle_max is not None and vehicle_max > kinematic_max_speed_mps * 1.05:
        result.add(
            field_name="limits.max_speed_mps",
            constraint="vehicle max speed <= kinematic max from motor RPM and gearing",
            limiting_layer="motor+drivetrain",
            limiting_value=round(kinematic_max_speed_mps, 3),
            message=(
                f"Vehicle max speed {vehicle.limits.max_speed_mps} m/s exceeds kinematic "
                f"limit {kinematic_max_speed_mps:.2f} m/s from motor RPM and gearing"
            ),
        )

    if vehicle.limits.max_motor_rpm is not None and vehicle.limits.max_motor_rpm > motor.max_rpm:
        result.add(
            field_name="limits.max_motor_rpm",
            constraint="vehicle max_motor_rpm <= motor.max_rpm",
            limiting_layer="motor",
            limiting_value=motor.max_rpm,
            message=(
                f"Vehicle max_motor_rpm {vehicle.limits.max_motor_rpm} exceeds "
                f"motor max_rpm {motor.max_rpm}"
            ),
        )

    _ = rpm_to_rads(motor.max_rpm)  # ensure conversion helper stays wired for future use
    return result


def validate_cross_component_ice(
    vehicle: VehicleConfig,
    engine: Engine,
    clutch: Clutch,
) -> ValidationResult:
    """Layer 3: cross-component compatibility for ICE vehicles."""
    result = ValidationResult(ok=True)
    gear_ratio = vehicle.drivetrain.axle_sprocket_teeth / vehicle.drivetrain.motor_sprocket_teeth
    kinematic_max_speed_mps = (
        engine.max_rpm * vehicle.wheel_radius_m * 2.0 * math.pi / (60.0 * gear_ratio)
    )
    vehicle_max = vehicle.limits.max_speed_mps
    if vehicle_max is not None and vehicle_max > kinematic_max_speed_mps * 1.05:
        result.add(
            field_name="limits.max_speed_mps",
            constraint="vehicle max speed <= kinematic max from engine RPM and gearing",
            limiting_layer="engine+drivetrain",
            limiting_value=round(kinematic_max_speed_mps, 3),
            message=(
                f"Vehicle max speed {vehicle.limits.max_speed_mps} m/s exceeds kinematic "
                f"limit {kinematic_max_speed_mps:.2f} m/s from engine RPM and gearing"
            ),
        )

    if vehicle.limits.max_motor_rpm is not None and vehicle.limits.max_motor_rpm > engine.max_rpm:
        result.add(
            field_name="limits.max_motor_rpm",
            constraint="vehicle max_motor_rpm <= engine.max_rpm",
            limiting_layer="engine",
            limiting_value=engine.max_rpm,
            message=(
                f"Vehicle max_motor_rpm {vehicle.limits.max_motor_rpm} exceeds "
                f"engine max_rpm {engine.max_rpm}"
            ),
        )

    if clutch.max_torque_nm < engine.peak_torque_nm * 0.5:
        result.add(
            field_name="clutch.max_torque_nm",
            constraint="clutch should handle a meaningful fraction of engine peak torque",
            limiting_layer="clutch",
            limiting_value=clutch.max_torque_nm,
            message=(
                f"Clutch max torque {clutch.max_torque_nm} Nm is low relative to engine "
                f"peak {engine.peak_torque_nm} Nm"
            ),
        )
    return result


def validate_limit_hierarchy(
    *,
    hardware: HardwareLimits,
    vehicle: VehicleConfig,
    mode: DriveMode | None = None,
    profile: DriverProfile | None = None,
) -> ValidationResult:
    """Layer 4: limit hierarchy."""
    result = ValidationResult(ok=True)
    _check_layer_le(
        result,
        child=vehicle.limits,
        parent=hardware,
        child_name="vehicle",
        parent_name="hardware",
    )
    if mode is not None:
        _check_layer_le(
            result,
            child=mode.limits,
            parent=vehicle.limits,
            child_name="drive_mode",
            parent_name="vehicle",
        )
    if profile is not None:
        _check_layer_le(
            result,
            child=profile.limits,
            parent=vehicle.limits,
            child_name="driver_profile",
            parent_name="vehicle",
        )
    return result


def validate_vehicle_config(
    vehicle: VehicleConfig,
    *,
    data_root: Any | None = None,
    mode: DriveMode | None = None,
    profile: DriverProfile | None = None,
) -> ValidationResult:
    """Run all validation layers for a vehicle configuration."""
    result = ValidationResult(ok=True)

    if vehicle.powertrain_type == "ice":
        refs = [
            ("engine", vehicle.engine, "engine"),
            ("clutch", vehicle.clutch, "clutch"),
        ]
    else:
        refs = [
            ("motor", vehicle.motor, "motor"),
            ("motor_controller", vehicle.motor_controller, "motor_controller"),
            ("battery", vehicle.battery, "battery"),
            ("bms", vehicle.bms, "bms"),
        ]

    components: dict[str, ComponentBase] = {}
    for label, ref, component_type in refs:
        if ref is None:
            result.add(
                field_name=f"{label}.component_id",
                constraint=f"{label} ref required",
                limiting_layer="vehicle",
                limiting_value=None,
                message=f"Missing required {label} reference for {vehicle.powertrain_type} vehicle",
            )
            continue
        try:
            component = load_component(component_type, ref.component_id, root=data_root)
        except ConfigStoreError as exc:
            result.add(
                field_name=f"{label}.component_id",
                constraint="component must exist",
                limiting_layer="store",
                limiting_value=ref.component_id,
                message=str(exc),
            )
            continue
        if not verify_component_ref(ref.component_id, ref.content_hash, component):
            result.add(
                field_name=f"{label}.content_hash",
                constraint="content_hash must match component file",
                limiting_layer=label,
                limiting_value=ref.content_hash,
                message=(
                    f"Component hash mismatch for {ref.component_id}; "
                    "recompute hash from the component file"
                ),
            )
        components[label] = component
        intra = validate_intra_component(component)
        if not intra.ok:
            result.violations.extend(intra.violations)
            result.ok = False

    required_count = 2 if vehicle.powertrain_type == "ice" else 4
    if len(components) < required_count:
        return result

    if vehicle.powertrain_type == "ice":
        engine = components["engine"]
        clutch = components["clutch"]
        assert isinstance(engine, Engine)
        assert isinstance(clutch, Clutch)
        hardware = hardware_limits_from_engine(engine, clutch)
        cross = validate_cross_component_ice(vehicle, engine, clutch)
    else:
        motor = components["motor"]
        controller = components["motor_controller"]
        battery = components["battery"]
        bms = components["bms"]
        assert isinstance(motor, Motor)
        assert isinstance(controller, MotorController)
        assert isinstance(battery, BatteryPack)
        assert isinstance(bms, Bms)
        hardware = hardware_limits_from_components(motor, controller, battery, bms)
        cross = validate_cross_component(vehicle, motor, controller, battery, bms)

    for sub_result in (
        cross,
        validate_limit_hierarchy(hardware=hardware, vehicle=vehicle, mode=mode, profile=profile),
    ):
        if not sub_result.ok:
            result.violations.extend(sub_result.violations)
            result.ok = False

    return result
