"""Vehicle configuration schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from gokart.config.schemas.limits import VehicleLimits


class ComponentRef(BaseModel):
    component_id: str
    content_hash: str = Field(min_length=64, max_length=64)


class DrivetrainConfig(BaseModel):
    motor_sprocket_teeth: int = Field(gt=0)
    axle_sprocket_teeth: int = Field(gt=0)
    chain_efficiency: float = Field(default=0.97, gt=0, le=1)
    axle_efficiency: float = Field(default=0.98, gt=0, le=1)


class VehicleConfig(BaseModel):
    name: str
    version: str
    powertrain_type: Literal["ev", "ice"] = "ev"
    dry_mass_kg: float = Field(gt=0)
    battery_mass_kg: float = Field(ge=0)
    driver_mass_kg: float = Field(gt=0)
    max_vehicle_mass_kg: float = Field(gt=0)
    wheelbase_m: float = Field(gt=0)
    front_track_m: float = Field(gt=0)
    rear_track_m: float = Field(gt=0)
    cg_height_m: float = Field(gt=0)
    cg_longitudinal_m: float = Field(gt=0)
    drag_coefficient: float = Field(ge=0)
    frontal_area_m2: float = Field(gt=0)
    rolling_resistance_coefficient: float = Field(gt=0)
    wheel_radius_m: float = Field(gt=0)
    motor: ComponentRef | None = None
    motor_controller: ComponentRef | None = None
    battery: ComponentRef | None = None
    bms: ComponentRef | None = None
    engine: ComponentRef | None = None
    clutch: ComponentRef | None = None
    front_tyre: ComponentRef | None = None
    rear_tyre: ComponentRef | None = None
    wheel: ComponentRef | None = None
    brake: ComponentRef | None = None
    dcdc: ComponentRef | None = None
    contactor: ComponentRef | None = None
    drivetrain: DrivetrainConfig
    limits: VehicleLimits

    @model_validator(mode="after")
    def validate_powertrain_refs(self) -> VehicleConfig:
        if self.powertrain_type == "ev":
            missing = [
                name
                for name, ref in (
                    ("motor", self.motor),
                    ("motor_controller", self.motor_controller),
                    ("battery", self.battery),
                    ("bms", self.bms),
                )
                if ref is None
            ]
            if missing:
                raise ValueError(f"EV vehicle requires: {', '.join(missing)}")
        else:
            if self.engine is None or self.clutch is None:
                raise ValueError("ICE vehicle requires engine and clutch")
        return self
