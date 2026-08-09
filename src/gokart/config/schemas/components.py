"""Component record schemas — each carries hardware absolute limits."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from gokart.config.schemas.limits import HardwareLimits


class ComponentBase(BaseModel):
    id: str
    manufacturer: str
    model: str
    part_number: str | None = None
    datasheet_path: str | None = None
    source: str | None = None
    price: float | None = Field(default=None, ge=0)
    date_added: date | None = None
    notes: str | None = None


class TorqueMapPoint(BaseModel):
    rpm: float = Field(ge=0)
    torque_nm: float = Field(ge=0)
    efficiency: float = Field(gt=0, le=1)


class SocCurvePoint(BaseModel):
    soc: float = Field(ge=0, le=1)
    value: float = Field(gt=0)


class Motor(ComponentBase):
    component_type: Literal["motor"] = "motor"
    nominal_voltage_v: float = Field(gt=0)
    max_voltage_v: float = Field(gt=0)
    continuous_current_a: float = Field(gt=0)
    peak_current_a: float = Field(gt=0)
    continuous_power_w: float = Field(gt=0)
    peak_power_w: float = Field(gt=0)
    phase_resistance_ohm: float | None = Field(default=None, gt=0)
    kv_rpm_per_v: float | None = Field(default=None, gt=0)
    pole_count: int | None = Field(default=None, gt=0)
    max_rpm: float = Field(gt=0)
    continuous_torque_nm: float = Field(gt=0)
    peak_torque_nm: float = Field(gt=0)
    mass_kg: float | None = Field(default=None, gt=0)
    max_temp_c: float = Field(default=120.0)
    torque_map: list[TorqueMapPoint] = Field(default_factory=list)
    hardware_limits: HardwareLimits

    @model_validator(mode="after")
    def validate_currents_and_voltage(self) -> Motor:
        if self.peak_current_a < self.continuous_current_a:
            raise ValueError("peak_current_a must be >= continuous_current_a")
        if self.max_voltage_v < self.nominal_voltage_v:
            raise ValueError("max_voltage_v must be >= nominal_voltage_v")
        if self.peak_torque_nm < self.continuous_torque_nm:
            raise ValueError("peak_torque_nm must be >= continuous_torque_nm")
        return self


class MotorController(ComponentBase):
    component_type: Literal["motor_controller"] = "motor_controller"
    firmware_version: str | None = None
    nominal_voltage_v: float = Field(gt=0)
    max_voltage_v: float = Field(gt=0)
    continuous_battery_current_a: float = Field(gt=0)
    peak_battery_current_a: float = Field(gt=0)
    continuous_motor_current_a: float = Field(gt=0)
    peak_motor_current_a: float = Field(gt=0)
    max_rpm: float = Field(gt=0)
    max_temp_c: float = Field(default=85.0)
    max_regen_current_a: float = Field(ge=0)
    efficiency: float = Field(default=0.95, gt=0, le=1)
    hardware_limits: HardwareLimits

    @model_validator(mode="after")
    def validate_peaks(self) -> MotorController:
        if self.peak_battery_current_a < self.continuous_battery_current_a:
            raise ValueError("peak_battery_current_a must be >= continuous_battery_current_a")
        if self.peak_motor_current_a < self.continuous_motor_current_a:
            raise ValueError("peak_motor_current_a must be >= continuous_motor_current_a")
        if self.max_voltage_v < self.nominal_voltage_v:
            raise ValueError("max_voltage_v must be >= nominal_voltage_v")
        return self


class BatteryPack(ComponentBase):
    component_type: Literal["battery"] = "battery"
    chemistry: Literal["lifepo4", "nmc", "other"] = "lifepo4"
    nominal_voltage_v: float = Field(gt=0)
    max_voltage_v: float = Field(gt=0)
    min_voltage_v: float = Field(gt=0)
    series_cells: int = Field(gt=0)
    parallel_cells: int = Field(gt=0)
    capacity_ah: float = Field(gt=0)
    energy_wh: float = Field(gt=0)
    internal_resistance_ohm: float = Field(gt=0)
    continuous_discharge_current_a: float = Field(gt=0)
    peak_discharge_current_a: float = Field(gt=0)
    max_charge_current_a: float = Field(gt=0)
    max_regen_current_a: float = Field(ge=0)
    max_cell_temp_c: float = Field(default=60.0)
    min_cell_temp_c: float = Field(default=-10.0)
    thermal_capacity_j_per_k: float | None = Field(default=None, gt=0)
    thermal_resistance_k_per_w: float | None = Field(default=None, gt=0)
    ocv_curve: list[SocCurvePoint] = Field(default_factory=list)
    resistance_curve: list[SocCurvePoint] = Field(default_factory=list)
    hardware_limits: HardwareLimits

    @model_validator(mode="after")
    def validate_battery(self) -> BatteryPack:
        if self.max_voltage_v < self.nominal_voltage_v:
            raise ValueError("max_voltage_v must be >= nominal_voltage_v")
        if self.nominal_voltage_v < self.min_voltage_v:
            raise ValueError("nominal_voltage_v must be >= min_voltage_v")
        if self.peak_discharge_current_a < self.continuous_discharge_current_a:
            raise ValueError("peak_discharge_current_a must be >= continuous_discharge_current_a")
        return self

    @field_validator("ocv_curve", "resistance_curve", mode="after")
    @classmethod
    def sort_soc_curves(cls, curve: list[SocCurvePoint]) -> list[SocCurvePoint]:
        return sorted(curve, key=lambda p: p.soc)


class Bms(ComponentBase):
    component_type: Literal["bms"] = "bms"
    max_discharge_current_a: float = Field(gt=0)
    max_charge_current_a: float = Field(gt=0)
    max_pack_voltage_v: float = Field(gt=0)
    min_pack_voltage_v: float = Field(gt=0)
    max_cell_voltage_v: float | None = Field(default=None, gt=0)
    min_cell_voltage_v: float | None = Field(default=None, gt=0)
    max_temp_c: float = Field(default=60.0)
    hardware_limits: HardwareLimits

    @model_validator(mode="after")
    def validate_bms_voltage(self) -> Bms:
        if self.max_pack_voltage_v < self.min_pack_voltage_v:
            raise ValueError("max_pack_voltage_v must be >= min_pack_voltage_v")
        return self


class Tyre(ComponentBase):
    component_type: Literal["tyre"] = "tyre"
    diameter_m: float = Field(gt=0)
    width_m: float = Field(gt=0)
    rim_diameter_m: float | None = Field(default=None, gt=0)
    mass_kg: float | None = Field(default=None, gt=0)
    rolling_resistance_coefficient: float = Field(gt=0)
    dry_grip_coefficient: float = Field(gt=0)
    wet_grip_coefficient: float | None = Field(default=None, gt=0)
    max_speed_mps: float = Field(gt=0)
    max_load_kg: float = Field(gt=0)
    hardware_limits: HardwareLimits = Field(default_factory=HardwareLimits)


class Wheel(ComponentBase):
    component_type: Literal["wheel"] = "wheel"
    diameter_m: float = Field(gt=0)
    circumference_m: float = Field(gt=0)
    mass_kg: float | None = Field(default=None, gt=0)
    hardware_limits: HardwareLimits = Field(default_factory=HardwareLimits)


class Brake(ComponentBase):
    component_type: Literal["brake"] = "brake"
    brake_type: Literal["disc", "drum", "other"] = "disc"
    disc_diameter_m: float | None = Field(default=None, gt=0)
    max_brake_torque_nm: float = Field(gt=0)
    front_distribution: float = Field(default=0.6, gt=0, lt=1)
    max_regen_fraction: float = Field(default=0.3, ge=0, le=1)
    hardware_limits: HardwareLimits = Field(default_factory=HardwareLimits)


class DcDcConverter(ComponentBase):
    component_type: Literal["dcdc"] = "dcdc"
    input_min_voltage_v: float = Field(gt=0)
    input_max_voltage_v: float = Field(gt=0)
    output_voltage_v: float = Field(gt=0)
    max_output_power_w: float = Field(gt=0)
    efficiency: float = Field(default=0.9, gt=0, le=1)
    hardware_limits: HardwareLimits = Field(default_factory=HardwareLimits)


class Contactor(ComponentBase):
    component_type: Literal["contactor"] = "contactor"
    max_continuous_current_a: float = Field(gt=0)
    precharge_resistance_ohm: float | None = Field(default=None, gt=0)
    hardware_limits: HardwareLimits = Field(default_factory=HardwareLimits)


class Sensor(ComponentBase):
    component_type: Literal["sensor"] = "sensor"
    sensor_type: Literal[
        "throttle", "brake", "wheel_speed", "temperature", "voltage", "current", "other"
    ]
    hardware_limits: HardwareLimits = Field(default_factory=HardwareLimits)


ComponentRecord = (
    Motor
    | MotorController
    | BatteryPack
    | Bms
    | Tyre
    | Wheel
    | Brake
    | DcDcConverter
    | Contactor
    | Sensor
)

COMPONENT_TYPE_MAP: dict[str, type[ComponentBase]] = {
    "motor": Motor,
    "motor_controller": MotorController,
    "battery": BatteryPack,
    "bms": Bms,
    "tyre": Tyre,
    "wheel": Wheel,
    "brake": Brake,
    "dcdc": DcDcConverter,
    "contactor": Contactor,
    "sensor": Sensor,
}
