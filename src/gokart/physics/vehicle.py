"""Vehicle physics composition."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

from gokart.config.schemas.components import BatteryPack, Brake, DcDcConverter, Motor, Tyre
from gokart.config.schemas.vehicle import VehicleConfig
from gokart.config.store import load_component
from gokart.config.validation import validate_vehicle_config
from gokart.physics.accessories import AccessoryParams, step_accessories
from gokart.physics.aero import aero_drag_force_n, gradient_force_n, rolling_resistance_force_n
from gokart.physics.battery import BatteryInputs, BatteryParams, BatteryState, step_battery
from gokart.physics.brakes import BrakeParams, step_brakes
from gokart.physics.constants import GRAVITY_MPS2
from gokart.physics.drivetrain import (
    DrivetrainParams,
    motor_rpm_from_speed,
    step_drivetrain,
    wheel_torque_to_traction_force,
)
from gokart.physics.motor import MotorInputs, MotorParams, MotorState, step_motor
from gokart.physics.thermal import ThermalInputs, ThermalParams, ThermalState, step_thermal
from gokart.physics.steering import step_steering, steering_angle_rad
from gokart.physics.tyres import (
    apply_cornering_speed_bleed,
    cornering_scrub_force_n,
    cornering_speed_limit_mps,
    lateral_force_from_steering_n,
    saturate_traction_friction_circle,
)


@dataclass(frozen=True)
class Environment:
    gradient_rad: float = 0.0
    ambient_temp_c: float = 25.0
    surface_mu_scale: float = 1.0


@dataclass
class VehicleState:
    position_m: float = 0.0
    position_x_m: float = 0.0
    position_y_m: float = 0.0
    heading_rad: float = 0.0
    speed_mps: float = 0.0
    motor: MotorState | None = None
    battery: BatteryState | None = None
    motor_thermal: ThermalState | None = None
    battery_thermal: ThermalState | None = None
    pack_voltage_v: float = 48.0

    def __post_init__(self) -> None:
        if self.motor is None:
            self.motor = MotorState()
        if self.battery is None:
            self.battery = BatteryState()
        if self.motor_thermal is None:
            self.motor_thermal = ThermalState()
        if self.battery_thermal is None:
            self.battery_thermal = ThermalState()


@dataclass(frozen=True)
class VehicleStepInputs:
    motor_torque_request_nm: float
    regen_torque_request_nm: float
    mechanical_brake: float
    environment: Environment
    steering: float = 0.0


@dataclass(frozen=True)
class VehicleStepOutputs:
    position_m: float
    position_x_m: float
    position_y_m: float
    heading_deg: float
    steering_angle_deg: float
    speed_mps: float
    acceleration_mps2: float
    motor_rpm: float
    motor_torque_nm: float
    motor_current_a: float
    battery_current_a: float
    pack_voltage_v: float
    soc: float
    traction_force_n: float
    motor_temp_c: float
    battery_temp_c: float
    power_w: float
    accessory_power_w: float
    brown_out_risk: bool


@dataclass
class VehicleModel:
    config: VehicleConfig
    mass_kg: float
    motor_params: MotorParams
    battery_params: BatteryParams
    drivetrain_params: DrivetrainParams
    brake_params: BrakeParams
    accessory_params: AccessoryParams | None
    grip_coefficient: float
    drag_coefficient: float
    frontal_area_m2: float
    rolling_resistance_coefficient: float
    motor_thermal_params: ThermalParams
    battery_thermal_params: ThermalParams
    nominal_voltage_v: float
    motor_efficiency_scale: float = 1.0

    @classmethod
    def from_config(cls, config: VehicleConfig, data_root: Path | None = None) -> VehicleModel:
        root = data_root
        motor = load_component("motor", config.motor.component_id, root=root)
        battery = load_component("battery", config.battery.component_id, root=root)
        assert isinstance(motor, Motor)
        assert isinstance(battery, BatteryPack)

        brake = None
        if config.brake:
            brake = load_component("brake", config.brake.component_id, root=root)
        tyre = None
        if config.front_tyre:
            tyre = load_component("tyre", config.front_tyre.component_id, root=root)
        dcdc = None
        if config.dcdc:
            dcdc = load_component("dcdc", config.dcdc.component_id, root=root)

        if brake is None:
            from gokart.config.schemas.components import Brake as BrakeModel

            brake = BrakeModel(
                id="default_brake",
                manufacturer="default",
                model="default",
                max_brake_torque_nm=400.0,
            )
        assert isinstance(brake, Brake)

        grip = 1.0
        if isinstance(tyre, Tyre):
            grip = tyre.dry_grip_coefficient

        accessory_params = None
        if isinstance(dcdc, DcDcConverter):
            accessory_params = AccessoryParams.from_component(dcdc)

        mass = config.dry_mass_kg + config.battery_mass_kg + config.driver_mass_kg
        drivetrain = DrivetrainParams.from_config(config.drivetrain, config.wheel_radius_m)

        return cls(
            config=config,
            mass_kg=mass,
            motor_params=MotorParams.from_component(motor),
            battery_params=BatteryParams.from_component(battery),
            drivetrain_params=drivetrain,
            brake_params=BrakeParams.from_component(brake, config.wheel_radius_m),
            accessory_params=accessory_params,
            grip_coefficient=grip,
            drag_coefficient=config.drag_coefficient,
            frontal_area_m2=config.frontal_area_m2,
            rolling_resistance_coefficient=config.rolling_resistance_coefficient,
            motor_thermal_params=ThermalParams(
                thermal_capacity_j_per_k=500.0,
                thermal_resistance_k_per_w=0.5,
            ),
            battery_thermal_params=ThermalParams(
                thermal_capacity_j_per_k=5000.0,
                thermal_resistance_k_per_w=0.2,
            ),
            nominal_voltage_v=battery.nominal_voltage_v,
        )

    def initial_state(self) -> VehicleState:
        return VehicleState(pack_voltage_v=self.nominal_voltage_v)

    def step(
        self,
        state: VehicleState,
        inputs: VehicleStepInputs,
        dt: float,
    ) -> tuple[VehicleState, VehicleStepOutputs]:
        assert state.motor is not None
        assert state.battery is not None
        assert state.motor_thermal is not None
        assert state.battery_thermal is not None

        env = inputs.environment
        grip = self.grip_coefficient * env.surface_mu_scale
        motor_rpm = motor_rpm_from_speed(self.drivetrain_params, state.speed_mps)

        motor_state, motor_out = step_motor(
            state.motor,
            MotorInputs(
                torque_request_nm=inputs.motor_torque_request_nm,
                motor_rpm=motor_rpm,
                pack_voltage_v=state.pack_voltage_v,
            ),
            self.motor_params,
            dt,
        )
        if self.motor_efficiency_scale != 1.0 and motor_out.motor_current_a != 0:
            scale = max(self.motor_efficiency_scale, 0.05)
            adjusted_current = motor_out.motor_current_a / scale
            motor_out = type(motor_out)(
                torque_nm=motor_out.torque_nm,
                motor_current_a=adjusted_current,
                electrical_power_w=adjusted_current * state.pack_voltage_v,
                mechanical_power_w=motor_out.mechanical_power_w,
                efficiency=min(1.0, motor_out.efficiency * scale),
                heat_w=motor_out.heat_w,
            )
        drivetrain_out = step_drivetrain(
            motor_out.torque_nm,
            state.speed_mps,
            self.drivetrain_params,
        )
        force_req = wheel_torque_to_traction_force(
            drivetrain_out.wheel_torque_nm,
            self.drivetrain_params.wheel_radius_m,
        )
        steer_rad = steering_angle_rad(inputs.steering)
        lateral_force = lateral_force_from_steering_n(
            state.speed_mps,
            steer_rad,
            self.config.wheelbase_m,
            self.mass_kg,
        )
        tyre_out = saturate_traction_friction_circle(
            force_req,
            lateral_force,
            self.mass_kg,
            grip,
            env.gradient_rad,
        )

        brake_out = step_brakes(
            inputs.mechanical_brake,
            inputs.regen_torque_request_nm,
            self.brake_params,
        )

        f_aero = aero_drag_force_n(state.speed_mps, self.drag_coefficient, self.frontal_area_m2)
        f_roll = rolling_resistance_force_n(
            self.mass_kg,
            self.rolling_resistance_coefficient,
            env.gradient_rad,
            GRAVITY_MPS2,
        )
        f_grad = gradient_force_n(self.mass_kg, env.gradient_rad, GRAVITY_MPS2)
        f_scrub = cornering_scrub_force_n(lateral_force, self.mass_kg, grip, env.gradient_rad)
        f_net = (
            tyre_out.traction_force_n
            - f_aero
            - f_roll
            - f_grad
            - f_scrub
            - brake_out.mechanical_force_n
        )
        accel = f_net / self.mass_kg if self.mass_kg > 0 else 0.0

        new_speed = max(0.0, state.speed_mps + accel * dt)
        new_speed = apply_cornering_speed_bleed(
            new_speed,
            steer_rad,
            self.config.wheelbase_m,
            grip,
            env.gradient_rad,
            dt,
        )
        new_position = state.position_m + new_speed * dt

        steering_out = step_steering(
            heading_rad=state.heading_rad,
            position_x_m=state.position_x_m,
            position_y_m=state.position_y_m,
            speed_mps=new_speed,
            steering_input=inputs.steering,
            wheelbase_m=self.config.wheelbase_m,
            dt=dt,
        )

        if self.accessory_params:
            accessory = step_accessories(state.pack_voltage_v, self.accessory_params)
        else:
            accessory = None
        accessory_power = accessory.hv_power_w if accessory else 0.0
        battery_current = motor_out.motor_current_a
        if state.pack_voltage_v > 1.0:
            battery_current += accessory_power / state.pack_voltage_v

        battery_state, battery_out = step_battery(
            state.battery,
            BatteryInputs(current_a=battery_current),
            self.battery_params,
            dt,
        )

        motor_thermal, motor_thermal_out = step_thermal(
            state.motor_thermal,
            ThermalInputs(heat_w=motor_out.heat_w),
            replace(self.motor_thermal_params, ambient_temp_c=env.ambient_temp_c),
            dt,
        )
        battery_thermal, battery_thermal_out = step_thermal(
            state.battery_thermal,
            ThermalInputs(heat_w=battery_out.heat_w),
            replace(self.battery_thermal_params, ambient_temp_c=env.ambient_temp_c),
            dt,
        )

        new_state = VehicleState(
            position_m=new_position,
            position_x_m=steering_out.position_x_m,
            position_y_m=steering_out.position_y_m,
            heading_rad=steering_out.heading_rad,
            speed_mps=new_speed,
            motor=motor_state,
            battery=battery_state,
            motor_thermal=motor_thermal,
            battery_thermal=battery_thermal,
            pack_voltage_v=battery_out.pack_voltage_v,
        )

        return new_state, VehicleStepOutputs(
            position_m=new_position,
            position_x_m=steering_out.position_x_m,
            position_y_m=steering_out.position_y_m,
            heading_deg=math.degrees(steering_out.heading_rad),
            steering_angle_deg=math.degrees(steering_out.steering_angle_rad),
            speed_mps=new_speed,
            acceleration_mps2=accel,
            motor_rpm=drivetrain_out.motor_rpm,
            motor_torque_nm=motor_out.torque_nm,
            motor_current_a=motor_out.motor_current_a,
            battery_current_a=battery_out.current_a,
            pack_voltage_v=battery_out.pack_voltage_v,
            soc=battery_state.soc,
            traction_force_n=tyre_out.traction_force_n,
            motor_temp_c=motor_thermal_out.temperature_c,
            battery_temp_c=battery_thermal_out.temperature_c,
            power_w=battery_out.power_w,
            accessory_power_w=accessory_power,
            brown_out_risk=accessory.brown_out_risk if accessory else False,
        )


def load_validated_vehicle_model(
    name: str,
    version: str,
    data_root: Path | None = None,
) -> VehicleModel:
    from gokart.config.store import load_vehicle

    config = load_vehicle(name, version, root=data_root)
    result = validate_vehicle_config(config, data_root=data_root)
    if not result.ok:
        messages = "; ".join(v.message for v in result.violations)
        raise ValueError(f"Invalid vehicle configuration: {messages}")
    return VehicleModel.from_config(config, data_root=data_root)
