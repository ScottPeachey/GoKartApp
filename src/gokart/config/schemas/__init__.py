"""Configuration schema exports."""

from gokart.config.schemas.calibration import CalibrationSet
from gokart.config.schemas.components import (
    COMPONENT_TYPE_MAP,
    BatteryPack,
    Bms,
    Brake,
    ComponentBase,
    ComponentRecord,
    Contactor,
    DcDcConverter,
    Motor,
    MotorController,
    Sensor,
    SocCurvePoint,
    TorqueMapPoint,
    Tyre,
    Wheel,
)
from gokart.config.schemas.limits import (
    DriveModeLimits,
    DriverProfileLimits,
    HardwareLimits,
    LimitLayer,
    VehicleLimits,
)
from gokart.config.schemas.modes import DriveMode, DriverProfile
from gokart.config.schemas.vehicle import ComponentRef, DrivetrainConfig, VehicleConfig

__all__ = [
    "COMPONENT_TYPE_MAP",
    "BatteryPack",
    "Bms",
    "Brake",
    "CalibrationSet",
    "ComponentBase",
    "ComponentRecord",
    "ComponentRef",
    "Contactor",
    "DcDcConverter",
    "DriveMode",
    "DriveModeLimits",
    "DrivetrainConfig",
    "DriverProfile",
    "DriverProfileLimits",
    "HardwareLimits",
    "LimitLayer",
    "Motor",
    "MotorController",
    "Sensor",
    "SocCurvePoint",
    "TorqueMapPoint",
    "Tyre",
    "VehicleConfig",
    "VehicleLimits",
    "Wheel",
]
