"""Vehicle physics composition."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

from gokart.config.schemas.components import BatteryPack, Brake, DcDcConverter, Engine, Motor, Tyre
from gokart.config.schemas.components import Clutch as ClutchComponent
from gokart.config.schemas.vehicle import VehicleConfig
from gokart.config.store import load_component
from gokart.config.validation import validate_vehicle_config
from gokart.physics.accessories import AccessoryParams, step_accessories
from gokart.physics.aero import aero_drag_force_n, gradient_force_n, rolling_resistance_force_n
from gokart.physics.attitude import load_transfer_long_accel_mps2
from gokart.physics.battery import BatteryInputs, BatteryParams, BatteryState, step_battery
from gokart.physics.brakes import BrakeParams, step_brakes
from gokart.physics.constants import GRAVITY_MPS2
from gokart.physics.drivetrain import (
    DrivetrainParams,
    motor_rpm_from_speed,
    step_drivetrain,
    wheel_torque_to_traction_force,
)
from gokart.physics.clutch import ClutchParams
from gokart.physics.engine import (
    EngineInputs,
    EngineParams,
    EngineState,
    available_engine_torque_nm,
    step_ice_powertrain,
)
from gokart.physics.motor import MotorInputs, MotorParams, MotorState, step_motor
from gokart.physics.thermal import (
    ThermalInputs,
    ThermalParams,
    ThermalState,
    ram_air_cooling_scale,
    engine_ram_air_cooling_scale,
    step_thermal,
)
from gokart.physics.load_transfer import wheel_normal_loads_n
from gokart.physics.steering import step_steering, steering_angle_rad
from gokart.physics.tyre_thermal import (
    TyreThermalParams,
    TyreThermalState,
    wheel_grip_multiplier,
    step_tyre_thermal,
)
from gokart.physics.tyres import (
    apply_cornering_speed_bleed,
    cornering_scrub_force_n,
    lateral_accel_from_bicycle_mps2,
    lateral_force_from_steering_n,
    saturate_wheel_forces,
)
from gokart.units import rpm_to_rads


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
    engine: EngineState | None = None
    battery: BatteryState | None = None
    motor_thermal: ThermalState | None = None
    battery_thermal: ThermalState | None = None
    tyre_thermal: TyreThermalState | None = None
    pack_voltage_v: float = 48.0

    def __post_init__(self) -> None:
        if self.motor is None:
            self.motor = MotorState()
        if self.engine is None:
            self.engine = EngineState()
        if self.battery is None:
            self.battery = BatteryState()
        if self.motor_thermal is None:
            self.motor_thermal = ThermalState()
        if self.battery_thermal is None:
            self.battery_thermal = ThermalState()
        if self.tyre_thermal is None:
            self.tyre_thermal = TyreThermalState()


@dataclass(frozen=True)
class VehicleStepInputs:
    motor_torque_request_nm: float
    regen_torque_request_nm: float
    mechanical_brake: float
    environment: Environment
    steering: float = 0.0
    max_speed_mps: float | None = None
    throttle: float = 0.0


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
    front_normal_n: float
    rear_normal_n: float
    front_lateral_n: float
    rear_traction_n: float
    normal_fl_n: float
    normal_fr_n: float
    normal_rl_n: float
    normal_rr_n: float
    lateral_fl_n: float
    lateral_fr_n: float
    longitudinal_fl_n: float
    longitudinal_fr_n: float
    longitudinal_rl_n: float
    longitudinal_rr_n: float
    tyre_temp_front_c: float
    tyre_temp_rear_c: float
    tyre_temp_fl_c: float
    tyre_temp_fr_c: float
    tyre_temp_rl_c: float
    tyre_temp_rr_c: float
    tyre_wear_front: float
    tyre_wear_rear: float
    tyre_wear_fl: float
    tyre_wear_fr: float
    tyre_wear_rl: float
    tyre_wear_rr: float
    grip_front_effective: float
    grip_rear_effective: float
    grip_fl_effective: float
    grip_fr_effective: float
    grip_rl_effective: float
    grip_rr_effective: float
    motor_temp_c: float
    battery_temp_c: float
    power_w: float
    accessory_power_w: float
    brown_out_risk: bool
    engine_rpm: float = 0.0
    engine_temp_c: float = 25.0
    clutch_locked: bool = False


@dataclass
class VehicleModel:
    config: VehicleConfig
    mass_kg: float
    powertrain_type: str
    motor_params: MotorParams | None
    battery_params: BatteryParams | None
    engine_params: EngineParams | None
    clutch_params: ClutchParams | None
    drivetrain_params: DrivetrainParams
    brake_params: BrakeParams
    accessory_params: AccessoryParams | None
    front_grip_coefficient: float
    rear_grip_coefficient: float
    drag_coefficient: float
    frontal_area_m2: float
    rolling_resistance_coefficient: float
    motor_thermal_params: ThermalParams
    battery_thermal_params: ThermalParams
    front_tyre_thermal_params: TyreThermalParams
    rear_tyre_thermal_params: TyreThermalParams
    nominal_voltage_v: float
    motor_efficiency_scale: float = 1.0

    @property
    def is_ice(self) -> bool:
        return self.powertrain_type == "ice"

    @property
    def peak_torque_nm(self) -> float:
        if self.engine_params is not None:
            return self.engine_params.peak_torque_nm
        assert self.motor_params is not None
        return self.motor_params.peak_torque_nm

    def available_drive_torque_nm(self, rpm: float, throttle: float, pack_voltage_v: float) -> float:
        if self.engine_params is not None:
            return available_engine_torque_nm(self.engine_params, rpm, throttle)
        assert self.motor_params is not None
        from gokart.physics.motor import available_torque_nm

        return available_torque_nm(self.motor_params, rpm, pack_voltage_v) * max(0.0, throttle)

    @classmethod
    def from_config(cls, config: VehicleConfig, data_root: Path | None = None) -> VehicleModel:
        root = data_root
        motor_params: MotorParams | None = None
        battery_params: BatteryParams | None = None
        engine_params: EngineParams | None = None
        clutch_params: ClutchParams | None = None
        nominal_voltage_v = 12.0

        if config.powertrain_type == "ice":
            assert config.engine is not None and config.clutch is not None
            engine = load_component("engine", config.engine.component_id, root=root)
            clutch = load_component("clutch", config.clutch.component_id, root=root)
            assert isinstance(engine, Engine)
            assert isinstance(clutch, ClutchComponent)
            engine_params = EngineParams.from_component(engine)
            clutch_params = ClutchParams.from_component(clutch)
        else:
            assert config.motor is not None and config.battery is not None
            motor = load_component("motor", config.motor.component_id, root=root)
            battery = load_component("battery", config.battery.component_id, root=root)
            assert isinstance(motor, Motor)
            assert isinstance(battery, BatteryPack)
            motor_params = MotorParams.from_component(motor)
            battery_params = BatteryParams.from_component(battery)
            nominal_voltage_v = battery.nominal_voltage_v

        brake = None
        if config.brake:
            brake = load_component("brake", config.brake.component_id, root=root)
        front_tyre = None
        rear_tyre = None
        if config.front_tyre:
            front_tyre = load_component("tyre", config.front_tyre.component_id, root=root)
        if config.rear_tyre:
            rear_tyre = load_component("tyre", config.rear_tyre.component_id, root=root)
        if front_tyre is None and rear_tyre is not None:
            front_tyre = rear_tyre
        if rear_tyre is None and front_tyre is not None:
            rear_tyre = front_tyre

        if brake is None:
            from gokart.config.schemas.components import Brake as BrakeModel

            brake = BrakeModel(
                id="default_brake",
                manufacturer="default",
                model="default",
                max_brake_torque_nm=400.0,
            )
        assert isinstance(brake, Brake)

        dcdc = None
        if config.dcdc:
            dcdc = load_component("dcdc", config.dcdc.component_id, root=root)

        front_grip = 1.0
        rear_grip = 1.0
        default_tyre = Tyre(
            id="default_tyre",
            manufacturer="default",
            model="default",
            diameter_m=0.254,
            width_m=0.114,
            rolling_resistance_coefficient=0.015,
            dry_grip_coefficient=1.1,
            max_speed_mps=22.0,
            max_load_kg=120.0,
        )
        if isinstance(front_tyre, Tyre):
            front_grip = front_tyre.dry_grip_coefficient
        else:
            front_tyre = default_tyre
        if isinstance(rear_tyre, Tyre):
            rear_grip = rear_tyre.dry_grip_coefficient
        else:
            rear_tyre = default_tyre

        front_tyre_thermal = TyreThermalParams.from_tyre(front_tyre)
        rear_tyre_thermal = TyreThermalParams.from_tyre(rear_tyre)

        accessory_params = None
        if isinstance(dcdc, DcDcConverter):
            accessory_params = AccessoryParams.from_component(dcdc)

        mass = config.dry_mass_kg + config.battery_mass_kg + config.driver_mass_kg
        drivetrain = DrivetrainParams.from_config(config.drivetrain, config.wheel_radius_m)

        if config.powertrain_type == "ice":
            motor_thermal_params = ThermalParams(
                thermal_capacity_j_per_k=15_000.0,
                thermal_resistance_k_per_w=0.11,
            )
        else:
            motor_thermal_params = ThermalParams(
                thermal_capacity_j_per_k=500.0,
                thermal_resistance_k_per_w=0.5,
            )

        return cls(
            config=config,
            mass_kg=mass,
            powertrain_type=config.powertrain_type,
            motor_params=motor_params,
            battery_params=battery_params,
            engine_params=engine_params,
            clutch_params=clutch_params,
            drivetrain_params=drivetrain,
            brake_params=BrakeParams.from_component(brake, config.wheel_radius_m),
            accessory_params=accessory_params,
            front_grip_coefficient=front_grip,
            rear_grip_coefficient=rear_grip,
            drag_coefficient=config.drag_coefficient,
            frontal_area_m2=config.frontal_area_m2,
            rolling_resistance_coefficient=config.rolling_resistance_coefficient,
            motor_thermal_params=motor_thermal_params,
            battery_thermal_params=ThermalParams(
                thermal_capacity_j_per_k=8000.0,
                thermal_resistance_k_per_w=0.28,
            ),
            front_tyre_thermal_params=front_tyre_thermal,
            rear_tyre_thermal_params=rear_tyre_thermal,
            nominal_voltage_v=nominal_voltage_v,
        )

    def initial_state(self) -> VehicleState:
        idle_rpm = self.engine_params.idle_rpm if self.engine_params else 0.0
        return VehicleState(
            pack_voltage_v=self.nominal_voltage_v,
            engine=EngineState(rpm=idle_rpm),
            tyre_thermal=TyreThermalState.initial(
                self.front_tyre_thermal_params.ambient_temp_c,
            ),
        )

    @property
    def grip_coefficient(self) -> float:
        """Average axle grip — kept for control-layer compatibility."""
        return (self.front_grip_coefficient + self.rear_grip_coefficient) / 2.0

    def rear_traction_limit_n(
        self,
        *,
        speed_mps: float,
        steering: float,
        gradient_rad: float,
        surface_mu_scale: float = 1.0,
        long_accel_mps2: float = 0.0,
    ) -> float:
        lat_accel = lateral_accel_from_bicycle_mps2(
            speed_mps,
            steering_angle_rad(steering),
            self.config.wheelbase_m,
        )
        loads = wheel_normal_loads_n(
            mass_kg=self.mass_kg,
            wheelbase_m=self.config.wheelbase_m,
            cg_longitudinal_m=self.config.cg_longitudinal_m,
            cg_height_m=self.config.cg_height_m,
            front_track_m=self.config.front_track_m,
            rear_track_m=self.config.rear_track_m,
            long_accel_mps2=long_accel_mps2,
            lat_accel_mps2=lat_accel,
            gradient_rad=gradient_rad,
        )
        from gokart.physics.tyres import max_traction_force_at_rear

        return max_traction_force_at_rear(
            loads.as_axle_loads(),
            self.rear_grip_coefficient * surface_mu_scale,
        )

    def step(
        self,
        state: VehicleState,
        inputs: VehicleStepInputs,
        dt: float,
    ) -> tuple[VehicleState, VehicleStepOutputs]:
        if self.is_ice:
            return self._step_ice(state, inputs, dt)
        return self._step_ev(state, inputs, dt)

    def _step_ev(
        self,
        state: VehicleState,
        inputs: VehicleStepInputs,
        dt: float,
    ) -> tuple[VehicleState, VehicleStepOutputs]:
        assert state.motor is not None
        assert state.battery is not None
        assert state.motor_thermal is not None
        assert state.battery_thermal is not None
        assert self.motor_params is not None
        assert self.battery_params is not None

        env = inputs.environment
        surface_mu = env.surface_mu_scale
        assert state.tyre_thermal is not None
        front_params = replace(
            self.front_tyre_thermal_params,
            ambient_temp_c=env.ambient_temp_c,
        )
        rear_params = replace(
            self.rear_tyre_thermal_params,
            ambient_temp_c=env.ambient_temp_c,
        )
        front_grip_base = self.front_grip_coefficient * surface_mu
        rear_grip_base = self.rear_grip_coefficient * surface_mu
        grip_fl = front_grip_base * wheel_grip_multiplier(state.tyre_thermal.fl, front_params)
        grip_fr = front_grip_base * wheel_grip_multiplier(state.tyre_thermal.fr, front_params)
        grip_rl = rear_grip_base * wheel_grip_multiplier(state.tyre_thermal.rl, rear_params)
        grip_rr = rear_grip_base * wheel_grip_multiplier(state.tyre_thermal.rr, rear_params)
        front_grip = (grip_fl + grip_fr) * 0.5
        rear_grip = (grip_rl + grip_rr) * 0.5
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
        lat_accel = lateral_accel_from_bicycle_mps2(
            state.speed_mps,
            steer_rad,
            self.config.wheelbase_m,
        )
        wheel_loads = wheel_normal_loads_n(
            mass_kg=self.mass_kg,
            wheelbase_m=self.config.wheelbase_m,
            cg_longitudinal_m=self.config.cg_longitudinal_m,
            cg_height_m=self.config.cg_height_m,
            front_track_m=self.config.front_track_m,
            rear_track_m=self.config.rear_track_m,
            long_accel_mps2=0.0,
            lat_accel_mps2=lat_accel,
            gradient_rad=env.gradient_rad,
        )
        lateral_force = lateral_force_from_steering_n(
            state.speed_mps,
            steer_rad,
            self.config.wheelbase_m,
            self.mass_kg,
        )

        brake_out = step_brakes(
            inputs.mechanical_brake,
            inputs.regen_torque_request_nm,
            self.brake_params,
        )

        tyre_out = saturate_wheel_forces(
            force_req,
            brake_out.mechanical_force_n,
            lateral_force,
            wheel_loads,
            grip_fl,
            grip_fr,
            grip_rl,
            grip_rr,
        )

        f_aero = aero_drag_force_n(state.speed_mps, self.drag_coefficient, self.frontal_area_m2)
        f_roll = rolling_resistance_force_n(
            self.mass_kg,
            self.rolling_resistance_coefficient,
            env.gradient_rad,
            GRAVITY_MPS2,
        )
        f_grad = gradient_force_n(self.mass_kg, env.gradient_rad, GRAVITY_MPS2)
        f_scrub = cornering_scrub_force_n(
            lateral_force,
            self.mass_kg,
            front_grip,
            env.gradient_rad,
        )
        f_net = (
            tyre_out.traction_force_n
            + tyre_out.front_longitudinal_n
            - f_aero
            - f_roll
            - f_grad
            - f_scrub
        )
        accel = f_net / self.mass_kg if self.mass_kg > 0 else 0.0
        load_accel = load_transfer_long_accel_mps2(state.speed_mps, accel)

        wheel_loads = wheel_normal_loads_n(
            mass_kg=self.mass_kg,
            wheelbase_m=self.config.wheelbase_m,
            cg_longitudinal_m=self.config.cg_longitudinal_m,
            cg_height_m=self.config.cg_height_m,
            front_track_m=self.config.front_track_m,
            rear_track_m=self.config.rear_track_m,
            long_accel_mps2=load_accel,
            lat_accel_mps2=lat_accel,
            gradient_rad=env.gradient_rad,
        )
        tyre_out = saturate_wheel_forces(
            force_req,
            brake_out.mechanical_force_n,
            lateral_force,
            wheel_loads,
            grip_fl,
            grip_fr,
            grip_rl,
            grip_rr,
        )
        f_net = (
            tyre_out.traction_force_n
            + tyre_out.front_longitudinal_n
            - f_aero
            - f_roll
            - f_grad
            - f_scrub
        )
        accel = f_net / self.mass_kg if self.mass_kg > 0 else 0.0

        new_speed = max(0.0, state.speed_mps + accel * dt)
        new_speed = apply_cornering_speed_bleed(
            new_speed,
            steer_rad,
            self.config.wheelbase_m,
            front_grip,
            env.gradient_rad,
            dt,
            mass_kg=self.mass_kg,
            front_normal_n=wheel_loads.front_normal_n,
        )
        if inputs.max_speed_mps is not None and inputs.max_speed_mps > 0.0:
            new_speed = min(new_speed, inputs.max_speed_mps)
        achieved_accel = (new_speed - state.speed_mps) / dt if dt > 0.0 else 0.0
        new_position = state.position_m + new_speed * dt

        tyre_thermal_state, thermal_out = step_tyre_thermal(
            state.tyre_thermal,
            front_params,
            rear_params,
            tyre_out=tyre_out,
            front_grip_coefficient=front_grip_base,
            rear_grip_coefficient=rear_grip_base,
            speed_mps=new_speed,
            dt=dt,
        )

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

        ram_air = ram_air_cooling_scale(new_speed)
        motor_thermal, motor_thermal_out = step_thermal(
            state.motor_thermal,
            ThermalInputs(heat_w=motor_out.heat_w),
            replace(self.motor_thermal_params, ambient_temp_c=env.ambient_temp_c),
            dt,
            cooling_scale=ram_air,
        )
        battery_thermal, battery_thermal_out = step_thermal(
            state.battery_thermal,
            ThermalInputs(heat_w=battery_out.heat_w),
            replace(self.battery_thermal_params, ambient_temp_c=env.ambient_temp_c),
            dt,
            cooling_scale=ram_air,
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
            tyre_thermal=tyre_thermal_state,
            pack_voltage_v=battery_out.pack_voltage_v,
        )

        return new_state, VehicleStepOutputs(
            position_m=new_position,
            position_x_m=steering_out.position_x_m,
            position_y_m=steering_out.position_y_m,
            heading_deg=math.degrees(steering_out.heading_rad),
            steering_angle_deg=math.degrees(steering_out.steering_angle_rad),
            speed_mps=new_speed,
            acceleration_mps2=achieved_accel,
            motor_rpm=drivetrain_out.motor_rpm,
            motor_torque_nm=motor_out.torque_nm,
            motor_current_a=motor_out.motor_current_a,
            battery_current_a=battery_out.current_a,
            pack_voltage_v=battery_out.pack_voltage_v,
            soc=battery_state.soc,
            traction_force_n=tyre_out.traction_force_n,
            front_normal_n=tyre_out.front_normal_n,
            rear_normal_n=tyre_out.rear_normal_n,
            front_lateral_n=tyre_out.front_lateral_n,
            rear_traction_n=tyre_out.rear_longitudinal_n,
            normal_fl_n=wheel_loads.fl_normal_n,
            normal_fr_n=wheel_loads.fr_normal_n,
            normal_rl_n=wheel_loads.rl_normal_n,
            normal_rr_n=wheel_loads.rr_normal_n,
            lateral_fl_n=tyre_out.fl_lateral_n,
            lateral_fr_n=tyre_out.fr_lateral_n,
            longitudinal_fl_n=tyre_out.fl_longitudinal_n,
            longitudinal_fr_n=tyre_out.fr_longitudinal_n,
            longitudinal_rl_n=tyre_out.rl_longitudinal_n,
            longitudinal_rr_n=tyre_out.rr_longitudinal_n,
            tyre_temp_front_c=thermal_out.front_temp_c,
            tyre_temp_rear_c=thermal_out.rear_temp_c,
            tyre_temp_fl_c=thermal_out.fl_temp_c,
            tyre_temp_fr_c=thermal_out.fr_temp_c,
            tyre_temp_rl_c=thermal_out.rl_temp_c,
            tyre_temp_rr_c=thermal_out.rr_temp_c,
            tyre_wear_front=thermal_out.front_wear,
            tyre_wear_rear=thermal_out.rear_wear,
            tyre_wear_fl=thermal_out.fl_wear,
            tyre_wear_fr=thermal_out.fr_wear,
            tyre_wear_rl=thermal_out.rl_wear,
            tyre_wear_rr=thermal_out.rr_wear,
            grip_front_effective=front_grip,
            grip_rear_effective=rear_grip,
            grip_fl_effective=grip_fl,
            grip_fr_effective=grip_fr,
            grip_rl_effective=grip_rl,
            grip_rr_effective=grip_rr,
            motor_temp_c=motor_thermal_out.temperature_c,
            battery_temp_c=battery_thermal_out.temperature_c,
            power_w=battery_out.power_w,
            accessory_power_w=accessory_power,
            brown_out_risk=accessory.brown_out_risk if accessory else False,
        )

    def _step_ice(
        self,
        state: VehicleState,
        inputs: VehicleStepInputs,
        dt: float,
    ) -> tuple[VehicleState, VehicleStepOutputs]:
        assert state.engine is not None
        assert state.motor_thermal is not None
        assert self.engine_params is not None
        assert self.clutch_params is not None

        env = inputs.environment
        surface_mu = env.surface_mu_scale
        assert state.tyre_thermal is not None
        front_params = replace(
            self.front_tyre_thermal_params,
            ambient_temp_c=env.ambient_temp_c,
        )
        rear_params = replace(
            self.rear_tyre_thermal_params,
            ambient_temp_c=env.ambient_temp_c,
        )
        front_grip_base = self.front_grip_coefficient * surface_mu
        rear_grip_base = self.rear_grip_coefficient * surface_mu
        grip_fl = front_grip_base * wheel_grip_multiplier(state.tyre_thermal.fl, front_params)
        grip_fr = front_grip_base * wheel_grip_multiplier(state.tyre_thermal.fr, front_params)
        grip_rl = rear_grip_base * wheel_grip_multiplier(state.tyre_thermal.rl, rear_params)
        grip_rr = rear_grip_base * wheel_grip_multiplier(state.tyre_thermal.rr, rear_params)
        front_grip = (grip_fl + grip_fr) * 0.5
        rear_grip = (grip_rl + grip_rr) * 0.5

        engine_state, ice_out = step_ice_powertrain(
            state.engine,
            EngineInputs(
                throttle=inputs.throttle,
                torque_request_nm=inputs.motor_torque_request_nm,
                speed_mps=state.speed_mps,
            ),
            self.engine_params,
            self.clutch_params,
            self.drivetrain_params,
            dt,
        )
        force_req = wheel_torque_to_traction_force(
            ice_out.wheel_torque_nm,
            self.drivetrain_params.wheel_radius_m,
        )
        steer_rad = steering_angle_rad(inputs.steering)
        lat_accel = lateral_accel_from_bicycle_mps2(
            state.speed_mps,
            steer_rad,
            self.config.wheelbase_m,
        )
        wheel_loads = wheel_normal_loads_n(
            mass_kg=self.mass_kg,
            wheelbase_m=self.config.wheelbase_m,
            cg_longitudinal_m=self.config.cg_longitudinal_m,
            cg_height_m=self.config.cg_height_m,
            front_track_m=self.config.front_track_m,
            rear_track_m=self.config.rear_track_m,
            long_accel_mps2=0.0,
            lat_accel_mps2=lat_accel,
            gradient_rad=env.gradient_rad,
        )
        lateral_force = lateral_force_from_steering_n(
            state.speed_mps,
            steer_rad,
            self.config.wheelbase_m,
            self.mass_kg,
        )

        brake_out = step_brakes(
            inputs.mechanical_brake,
            0.0,
            self.brake_params,
        )

        tyre_out = saturate_wheel_forces(
            force_req,
            brake_out.mechanical_force_n,
            lateral_force,
            wheel_loads,
            grip_fl,
            grip_fr,
            grip_rl,
            grip_rr,
        )

        f_aero = aero_drag_force_n(state.speed_mps, self.drag_coefficient, self.frontal_area_m2)
        f_roll = rolling_resistance_force_n(
            self.mass_kg,
            self.rolling_resistance_coefficient,
            env.gradient_rad,
            GRAVITY_MPS2,
        )
        f_grad = gradient_force_n(self.mass_kg, env.gradient_rad, GRAVITY_MPS2)
        f_scrub = cornering_scrub_force_n(
            lateral_force,
            self.mass_kg,
            front_grip,
            env.gradient_rad,
        )
        f_net = (
            tyre_out.traction_force_n
            + tyre_out.front_longitudinal_n
            - f_aero
            - f_roll
            - f_grad
            - f_scrub
        )
        accel = f_net / self.mass_kg if self.mass_kg > 0 else 0.0
        load_accel = load_transfer_long_accel_mps2(state.speed_mps, accel)

        wheel_loads = wheel_normal_loads_n(
            mass_kg=self.mass_kg,
            wheelbase_m=self.config.wheelbase_m,
            cg_longitudinal_m=self.config.cg_longitudinal_m,
            cg_height_m=self.config.cg_height_m,
            front_track_m=self.config.front_track_m,
            rear_track_m=self.config.rear_track_m,
            long_accel_mps2=load_accel,
            lat_accel_mps2=lat_accel,
            gradient_rad=env.gradient_rad,
        )
        tyre_out = saturate_wheel_forces(
            force_req,
            brake_out.mechanical_force_n,
            lateral_force,
            wheel_loads,
            grip_fl,
            grip_fr,
            grip_rl,
            grip_rr,
        )
        f_net = (
            tyre_out.traction_force_n
            + tyre_out.front_longitudinal_n
            - f_aero
            - f_roll
            - f_grad
            - f_scrub
        )
        accel = f_net / self.mass_kg if self.mass_kg > 0 else 0.0

        new_speed = max(0.0, state.speed_mps + accel * dt)
        new_speed = apply_cornering_speed_bleed(
            new_speed,
            steer_rad,
            self.config.wheelbase_m,
            front_grip,
            env.gradient_rad,
            dt,
            mass_kg=self.mass_kg,
            front_normal_n=wheel_loads.front_normal_n,
        )
        if inputs.max_speed_mps is not None and inputs.max_speed_mps > 0.0:
            new_speed = min(new_speed, inputs.max_speed_mps)
        achieved_accel = (new_speed - state.speed_mps) / dt if dt > 0.0 else 0.0
        new_position = state.position_m + new_speed * dt

        tyre_thermal_state, thermal_out = step_tyre_thermal(
            state.tyre_thermal,
            front_params,
            rear_params,
            tyre_out=tyre_out,
            front_grip_coefficient=front_grip_base,
            rear_grip_coefficient=rear_grip_base,
            speed_mps=new_speed,
            dt=dt,
        )

        steering_out = step_steering(
            heading_rad=state.heading_rad,
            position_x_m=state.position_x_m,
            position_y_m=state.position_y_m,
            speed_mps=new_speed,
            steering_input=inputs.steering,
            wheelbase_m=self.config.wheelbase_m,
            dt=dt,
        )

        ram_air = engine_ram_air_cooling_scale(new_speed)
        motor_thermal, motor_thermal_out = step_thermal(
            state.motor_thermal,
            ThermalInputs(heat_w=ice_out.heat_w),
            replace(self.motor_thermal_params, ambient_temp_c=env.ambient_temp_c),
            dt,
            cooling_scale=ram_air,
        )

        new_state = VehicleState(
            position_m=new_position,
            position_x_m=steering_out.position_x_m,
            position_y_m=steering_out.position_y_m,
            heading_rad=steering_out.heading_rad,
            speed_mps=new_speed,
            engine=engine_state,
            motor_thermal=motor_thermal,
            battery_thermal=state.battery_thermal,
            tyre_thermal=tyre_thermal_state,
            pack_voltage_v=state.pack_voltage_v,
        )

        mechanical_power = ice_out.engine_torque_nm * rpm_to_rads(ice_out.engine_rpm)
        return new_state, VehicleStepOutputs(
            position_m=new_position,
            position_x_m=steering_out.position_x_m,
            position_y_m=steering_out.position_y_m,
            heading_deg=math.degrees(steering_out.heading_rad),
            steering_angle_deg=math.degrees(steering_out.steering_angle_rad),
            speed_mps=new_speed,
            acceleration_mps2=achieved_accel,
            motor_rpm=ice_out.engine_rpm,
            motor_torque_nm=ice_out.engine_torque_nm,
            motor_current_a=0.0,
            battery_current_a=0.0,
            pack_voltage_v=state.pack_voltage_v,
            soc=1.0,
            traction_force_n=tyre_out.traction_force_n,
            front_normal_n=tyre_out.front_normal_n,
            rear_normal_n=tyre_out.rear_normal_n,
            front_lateral_n=tyre_out.front_lateral_n,
            rear_traction_n=tyre_out.rear_longitudinal_n,
            normal_fl_n=wheel_loads.fl_normal_n,
            normal_fr_n=wheel_loads.fr_normal_n,
            normal_rl_n=wheel_loads.rl_normal_n,
            normal_rr_n=wheel_loads.rr_normal_n,
            lateral_fl_n=tyre_out.fl_lateral_n,
            lateral_fr_n=tyre_out.fr_lateral_n,
            longitudinal_fl_n=tyre_out.fl_longitudinal_n,
            longitudinal_fr_n=tyre_out.fr_longitudinal_n,
            longitudinal_rl_n=tyre_out.rl_longitudinal_n,
            longitudinal_rr_n=tyre_out.rr_longitudinal_n,
            tyre_temp_front_c=thermal_out.front_temp_c,
            tyre_temp_rear_c=thermal_out.rear_temp_c,
            tyre_temp_fl_c=thermal_out.fl_temp_c,
            tyre_temp_fr_c=thermal_out.fr_temp_c,
            tyre_temp_rl_c=thermal_out.rl_temp_c,
            tyre_temp_rr_c=thermal_out.rr_temp_c,
            tyre_wear_front=thermal_out.front_wear,
            tyre_wear_rear=thermal_out.rear_wear,
            tyre_wear_fl=thermal_out.fl_wear,
            tyre_wear_fr=thermal_out.fr_wear,
            tyre_wear_rl=thermal_out.rl_wear,
            tyre_wear_rr=thermal_out.rr_wear,
            grip_front_effective=front_grip,
            grip_rear_effective=rear_grip,
            grip_fl_effective=grip_fl,
            grip_fr_effective=grip_fr,
            grip_rl_effective=grip_rl,
            grip_rr_effective=grip_rr,
            motor_temp_c=motor_thermal_out.temperature_c,
            battery_temp_c=env.ambient_temp_c,
            power_w=mechanical_power,
            accessory_power_w=0.0,
            brown_out_risk=False,
            engine_rpm=ice_out.engine_rpm,
            engine_temp_c=motor_thermal_out.temperature_c,
            clutch_locked=ice_out.clutch_locked,
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
