"""Shared limit-layer models used by vehicle, drive modes, and driver profiles."""

from pydantic import BaseModel, Field


class LimitLayer(BaseModel):
    """Numeric limits at one hierarchy layer. None means unrestricted at this layer."""

    max_speed_mps: float | None = Field(default=None, gt=0)
    max_motor_current_a: float | None = Field(default=None, gt=0)
    max_battery_current_a: float | None = Field(default=None, gt=0)
    max_regen_current_a: float | None = Field(default=None, ge=0)
    max_power_w: float | None = Field(default=None, gt=0)
    max_motor_rpm: float | None = Field(default=None, gt=0)
    max_accel_mps2: float | None = Field(default=None, gt=0)
    max_decel_mps2: float | None = Field(default=None, gt=0)
    max_gradient_rad: float | None = Field(default=None, ge=0)


class HardwareLimits(LimitLayer):
    """Hardware absolute limits aggregated from installed components."""

    max_voltage_v: float | None = Field(default=None, gt=0)
    min_voltage_v: float | None = Field(default=None, ge=0)
    max_temp_c: float | None = Field(default=None)


VehicleLimits = LimitLayer
DriveModeLimits = LimitLayer
DriverProfileLimits = LimitLayer
