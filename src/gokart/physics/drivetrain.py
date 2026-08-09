"""Drivetrain kinematics and torque transmission."""

from __future__ import annotations

from dataclasses import dataclass

from gokart.config.schemas.vehicle import DrivetrainConfig
from gokart.units import rads_to_rpm, rpm_to_rads


@dataclass(frozen=True)
class DrivetrainParams:
    gear_ratio: float
    chain_efficiency: float
    axle_efficiency: float
    wheel_radius_m: float

    @classmethod
    def from_config(cls, drivetrain: DrivetrainConfig, wheel_radius_m: float) -> DrivetrainParams:
        return cls(
            gear_ratio=drivetrain.axle_sprocket_teeth / drivetrain.motor_sprocket_teeth,
            chain_efficiency=drivetrain.chain_efficiency,
            axle_efficiency=drivetrain.axle_efficiency,
            wheel_radius_m=wheel_radius_m,
        )

    @property
    def total_efficiency(self) -> float:
        return self.chain_efficiency * self.axle_efficiency


@dataclass(frozen=True)
class DrivetrainOutputs:
    wheel_torque_nm: float
    motor_rpm: float
    wheel_rpm: float


def motor_rpm_from_speed(params: DrivetrainParams, speed_mps: float) -> float:
    """Rigid coupling: motor RPM implied by vehicle speed."""
    omega_wheel = speed_mps / params.wheel_radius_m if params.wheel_radius_m > 0 else 0.0
    omega_motor = omega_wheel * params.gear_ratio
    return rads_to_rpm(omega_motor)


def speed_from_motor_rpm(params: DrivetrainParams, motor_rpm: float) -> float:
    omega_motor = rpm_to_rads(motor_rpm)
    omega_wheel = omega_motor / params.gear_ratio
    return omega_wheel * params.wheel_radius_m


def motor_torque_to_wheel(motor_torque_nm: float, params: DrivetrainParams) -> float:
    return motor_torque_nm * params.gear_ratio * params.total_efficiency


def wheel_torque_to_motor(wheel_torque_nm: float, params: DrivetrainParams) -> float:
    denom = params.gear_ratio * params.total_efficiency
    if denom <= 0:
        return 0.0
    return wheel_torque_nm / denom


def wheel_torque_to_traction_force(wheel_torque_nm: float, wheel_radius_m: float) -> float:
    if wheel_radius_m <= 0:
        return 0.0
    return wheel_torque_nm / wheel_radius_m


def step_drivetrain(
    motor_torque_nm: float,
    speed_mps: float,
    params: DrivetrainParams,
) -> DrivetrainOutputs:
    wheel_torque = motor_torque_to_wheel(motor_torque_nm, params)
    motor_rpm = motor_rpm_from_speed(params, speed_mps)
    wheel_rpm = rads_to_rpm(speed_mps / params.wheel_radius_m) if params.wheel_radius_m > 0 else 0.0
    return DrivetrainOutputs(
        wheel_torque_nm=wheel_torque,
        motor_rpm=motor_rpm,
        wheel_rpm=wheel_rpm,
    )
