"""Drive mode and driver profile schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from gokart.config.schemas.limits import DriveModeLimits, DriverProfileLimits


class DriveMode(BaseModel):
    name: str
    limits: DriveModeLimits = Field(default_factory=DriveModeLimits)
    throttle_curve: Literal["linear", "progressive", "aggressive"] = "linear"
    throttle_ramp_per_s: float | None = Field(default=2.0, gt=0)
    traction_limiter: Literal["off", "gentle", "moderate", "aggressive"] = "moderate"
    regen_strength: float = Field(default=0.5, ge=0, le=1)


class DriverProfile(BaseModel):
    name: str
    pin_hash: str | None = None
    limits: DriverProfileLimits = Field(default_factory=DriverProfileLimits)
