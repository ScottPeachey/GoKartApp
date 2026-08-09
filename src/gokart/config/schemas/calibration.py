"""Sensor calibration set schema — stored separately from vehicle configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ThrottleCalibration(BaseModel):
    min_adc: int = Field(ge=0)
    max_adc: int = Field(ge=0)
    deadband: float = Field(default=0.02, ge=0, le=0.2)


class BrakeCalibration(BaseModel):
    min_adc: int = Field(ge=0)
    max_adc: int = Field(ge=0)
    deadband: float = Field(default=0.02, ge=0, le=0.2)


class WheelSpeedCalibration(BaseModel):
    pulses_per_revolution: float = Field(gt=0)
    wheel_radius_m: float = Field(gt=0)


class CalibrationSet(BaseModel):
    name: str
    version: str
    throttle: ThrottleCalibration
    brake: BrakeCalibration
    wheel_speed: WheelSpeedCalibration
    voltage_scale: float = Field(default=1.0, gt=0)
    current_scale: float = Field(default=1.0, gt=0)
    temperature_offset_c: float = Field(default=0.0)
    steering_centre_adc: int | None = Field(default=None, ge=0)
