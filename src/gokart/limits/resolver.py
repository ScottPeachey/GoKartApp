"""Effective limit resolver — runtime min() across hierarchy layers."""

from __future__ import annotations

from dataclasses import dataclass

from gokart.config.schemas.limits import (
    DriveModeLimits,
    DriverProfileLimits,
    HardwareLimits,
    LimitLayer,
    VehicleLimits,
)

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


@dataclass(frozen=True)
class DeratingFactors:
    speed: float = 1.0
    motor_current: float = 1.0
    battery_current: float = 1.0
    regen_current: float = 1.0
    power: float = 1.0
    motor_rpm: float = 1.0
    accel: float = 1.0
    decel: float = 1.0
    gradient: float = 1.0


@dataclass(frozen=True)
class EffectiveLimits:
    max_speed_mps: float
    max_motor_current_a: float
    max_battery_current_a: float
    max_regen_current_a: float
    max_power_w: float
    max_motor_rpm: float
    max_accel_mps2: float
    max_decel_mps2: float
    max_gradient_rad: float


_FIELD_DERATING_MAP = {
    "max_speed_mps": "speed",
    "max_motor_current_a": "motor_current",
    "max_battery_current_a": "battery_current",
    "max_regen_current_a": "regen_current",
    "max_power_w": "power",
    "max_motor_rpm": "motor_rpm",
    "max_accel_mps2": "accel",
    "max_decel_mps2": "decel",
    "max_gradient_rad": "gradient",
}


def _min_layer_value(layers: list[LimitLayer], field_name: str) -> float | None:
    values = [
        getattr(layer, field_name) for layer in layers if getattr(layer, field_name) is not None
    ]
    return min(values) if values else None


def resolve_limits(
    hardware: HardwareLimits,
    vehicle: VehicleLimits,
    mode: DriveModeLimits,
    profile: DriverProfileLimits,
    derating: DeratingFactors | None = None,
) -> EffectiveLimits:
    """Resolve effective limits as element-wise minimum across layers × derating."""
    factors = derating or DeratingFactors()
    layers: list[LimitLayer] = [hardware, vehicle, mode, profile]
    resolved: dict[str, float] = {}

    for field_name in LIMIT_FIELDS:
        base = _min_layer_value(layers, field_name)
        if base is None:
            raise ValueError(f"No limit defined for required field: {field_name}")
        derate_attr = _FIELD_DERATING_MAP[field_name]
        factor = min(getattr(factors, derate_attr), 1.0)
        resolved[field_name] = base * factor

    return EffectiveLimits(**resolved)
