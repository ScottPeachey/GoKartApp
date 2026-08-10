"""Effective limit resolution for the dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gokart.config.store import (
    load_component,
    load_drive_mode,
    load_driver_profile,
    load_vehicle,
)
from gokart.config.validation import hardware_limits_from_components
from gokart.limits.resolver import resolve_limits
from gokart.units import mps_to_kmh


def _kmh(value: float | None) -> float | None:
    return mps_to_kmh(value) if value is not None else None


def compute_effective_limits(
    *,
    vehicle_name: str,
    vehicle_version: str,
    mode_name: str,
    profile_name: str,
    root: Path,
) -> dict[str, Any]:
    vehicle = load_vehicle(vehicle_name, vehicle_version, root=root)
    mode = load_drive_mode(mode_name, root=root)
    profile = load_driver_profile(profile_name, root=root)
    motor = load_component("motor", vehicle.motor.component_id, root=root)
    controller = load_component("motor_controller", vehicle.motor_controller.component_id, root=root)
    battery = load_component("battery", vehicle.battery.component_id, root=root)
    bms = load_component("bms", vehicle.bms.component_id, root=root)
    hardware = hardware_limits_from_components(motor, controller, battery, bms)
    limits = resolve_limits(hardware, vehicle.limits, mode.limits, profile.limits)

    layer_speeds = {
        "hardware": hardware.max_speed_mps,
        "vehicle": vehicle.limits.max_speed_mps,
        "mode": mode.limits.max_speed_mps,
        "profile": profile.limits.max_speed_mps,
    }
    binding = None
    for layer, speed in layer_speeds.items():
        if speed is None:
            continue
        if binding is None or speed < layer_speeds[binding]:
            binding = layer
    binding_kmh = _kmh(layer_speeds[binding]) if binding is not None else None

    return {
        "max_speed_mps": limits.max_speed_mps,
        "max_speed_kmh": mps_to_kmh(limits.max_speed_mps),
        "max_power_w": limits.max_power_w,
        "max_accel_mps2": limits.max_accel_mps2,
        "binding_layer": binding,
        "binding_speed_kmh": binding_kmh,
        "drive_mode": mode.name,
        "driver_profile": profile.name,
        "layers": {
            "hardware": {"max_speed_kmh": _kmh(hardware.max_speed_mps)},
            "vehicle": {"max_speed_kmh": _kmh(vehicle.limits.max_speed_mps)},
            "mode": {"max_speed_kmh": _kmh(mode.limits.max_speed_mps), "name": mode.name},
            "profile": {
                "max_speed_kmh": _kmh(profile.limits.max_speed_mps),
                "name": profile.name,
            },
        },
    }
