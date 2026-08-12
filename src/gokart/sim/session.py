"""Steppable track-racing simulation session for RL and interactive control."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from gokart.config.schemas.modes import DriveMode, DriverProfile
from gokart.config.store import data_root, load_component, load_drive_mode, load_driver_profile
from gokart.config.validation import hardware_limits_from_components, validate_vehicle_config
from gokart.control.pipeline import (
    ControlInputs,
    ControlParams,
    ControlState,
    SafetyOutputs,
    control_step,
)
from gokart.driver.agent import DriverConfig, RuleBasedDriver
from gokart.driver.racing_line import spawn_on_racing_line
from gokart.limits.resolver import DeratingFactors, resolve_limits
from gokart.physics.attitude import vehicle_attitude_deg
from gokart.physics.drivetrain import motor_rpm_from_speed, speed_from_motor_rpm
from gokart.physics.steering import steering_angle_rad
from gokart.physics.tyres import lateral_accel_from_bicycle_mps2
from gokart.physics.vehicle import (
    VehicleModel,
    VehicleState,
    VehicleStepInputs,
    load_validated_vehicle_model,
)
from gokart.safety.faults import DetectionState, SafetyConfig, SensorInputs, detect_faults
from gokart.safety.state_machine import SafetyInputs, SafetyTimers, safety_step
from gokart.safety.types import ContactorCommand, FaultId, SafetyState
from gokart.sim.engine import (
    DEFAULT_DT_S,
    SimTickRecord,
    SimulationResult,
    _adc_from_pedal,
    _build_safety_config,
    _build_sensor_inputs,
    _contactor_feedback,
    _resolve_sim_limits,
    _sync_injected_temps,
)
from gokart.sim.fault_injection import FaultInjector
from gokart.sim.runtime import RuntimeControls
from gokart.sim.scenarios import Scenario
from gokart.sim.track_context import TrackSimulationContext
from gokart.track.model import Track


class ControlSource(str, Enum):
    MANUAL = "manual"
    AUTO = "auto"
    RL = "rl"
    SCENARIO = "scenario"


@dataclass
class StepResult:
    tick: SimTickRecord
    safety_state: SafetyState
    terminated: bool = False
    truncated: bool = False
    info: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionConfig:
    vehicle_name: str
    vehicle_version: str
    track: Track
    mode_name: str = "default"
    profile_name: str = "owner"
    scenario: Scenario | None = None
    control_source: ControlSource = ControlSource.RL
    target_laps: int = 3
    aggression: float = 1.0
    auto_boot: bool = True
    dt_s: float = DEFAULT_DT_S
    max_steps: int = 50_000
    free_mode: bool = False


@dataclass
class _SessionState:
    step_index: int = 0
    time_s: float = 0.0
    safety_state: SafetyState = SafetyState.OFF
    safety_timers: SafetyTimers = field(default_factory=SafetyTimers)
    latched_faults: set[FaultId] = field(default_factory=set)
    detection_state: DetectionState = field(default_factory=DetectionState)
    control_state: ControlState = field(default_factory=ControlState)
    vehicle_state: VehicleState | None = None
    auto_arm_sent: bool = False
    prev_synthetic_brake_hold: bool = False
    prev_safety_state: SafetyState = SafetyState.OFF
    safety_outputs: SafetyOutputs = field(
        default_factory=lambda: SafetyOutputs(
            torque_permitted=False,
            regen_permitted=False,
            contactor_command=ContactorCommand.OPEN,
            derating=DeratingFactors(),
            active_faults=(),
            display_message_code=0,
            safety_state=SafetyState.OFF,
        )
    )
    limits: Any = None
    last_tick: SimTickRecord | None = None
    prev_track_s_m: float = 0.0


class SimulationSession:
    """Single-tick simulation session for RL training and evaluation."""

    def __init__(self, config: SessionConfig, *, data_root_path=None) -> None:
        self.config = config
        self.root = data_root_path or data_root()
        self.scenario = config.scenario or Scenario(
            name="rl_session",
            duration_s=1e9,
            mode_name=config.mode_name,
            profile_name=config.profile_name,
            auto_boot=config.auto_boot,
        )
        self.vehicle_model = load_validated_vehicle_model(
            config.vehicle_name,
            config.vehicle_version,
            data_root=self.root,
        )
        self.mode = load_drive_mode(self.scenario.mode_name, root=self.root)
        self.profile = load_driver_profile(self.scenario.profile_name, root=self.root)
        if config.control_source in {
            ControlSource.MANUAL,
            ControlSource.RL,
            ControlSource.AUTO,
        }:
            self.mode = self.mode.model_copy(update={"throttle_ramp_per_s": None})

        validation = validate_vehicle_config(
            self.vehicle_model.config,
            data_root=self.root,
            mode=self.mode,
            profile=self.profile,
        )
        if not validation.ok:
            raise ValueError("; ".join(v.message for v in validation.violations))

        self.base_limits = _resolve_sim_limits(
            self.vehicle_model, self.mode, self.profile, self.root
        )
        self.safety_config = _build_safety_config(
            self.vehicle_model, self.base_limits, self.root
        )
        battery = load_component(
            "battery", self.vehicle_model.config.battery.component_id, root=self.root
        )
        self.series_cells = battery.series_cells
        self.track_context = TrackSimulationContext(config.track)
        self.auto_driver: RuleBasedDriver | None = None
        if config.control_source == ControlSource.AUTO:
            self.auto_driver = RuleBasedDriver(
                config.track,
                DriverConfig(
                    grip_coefficient=self.vehicle_model.grip_coefficient,
                    max_speed_mps=self.base_limits.max_speed_mps,
                    wheelbase_m=self.vehicle_model.config.wheelbase_m,
                    aggression=config.aggression,
                    battery_temp_derate_c=self.safety_config.battery_temp_derate_c,
                    battery_temp_fault_c=self.safety_config.battery_temp_fault_c,
                ),
            )
        self.control_params = ControlParams(
            mode=self.mode,
            motor_peak_torque_nm=self.vehicle_model.motor_params.peak_torque_nm,
            wheel_radius_m=self.vehicle_model.config.wheel_radius_m,
            gear_ratio=self.vehicle_model.drivetrain_params.gear_ratio,
            drivetrain_efficiency=self.vehicle_model.drivetrain_params.total_efficiency,
        )
        self.injector = FaultInjector.from_scenario_data(self.scenario.injections)
        self.state = _SessionState()
        self._pending_rl_action: tuple[float, float, float] | None = None
        self._manual_controls = RuntimeControls()

    def reset(self) -> StepResult:
        self.state = _SessionState()
        vehicle_state = self.vehicle_model.initial_state()
        spawn_x, spawn_y, spawn_heading = spawn_on_racing_line(self.config.track)
        vehicle_state.position_x_m = spawn_x
        vehicle_state.position_y_m = spawn_y
        vehicle_state.heading_rad = spawn_heading
        self.state.vehicle_state = vehicle_state
        self.state.limits = self.base_limits
        self.track_context.lap_timer.reset()
        if self.auto_driver is not None:
            self.auto_driver.reset_progress()
        self._pending_rl_action = None
        return self.step(action=None)

    def set_manual_controls(self, controls: RuntimeControls) -> None:
        self._manual_controls = controls

    def step(
        self,
        *,
        action: tuple[float, float, float] | None = None,
    ) -> StepResult:
        if self.state.vehicle_state is None:
            return self.reset()
        if action is not None:
            self._pending_rl_action = action

        ctx = self.state
        dt_s = self.config.dt_s
        step = ctx.step_index
        time_s = step * dt_s
        ctx.time_s = time_s
        vehicle_state = ctx.vehicle_state
        assert vehicle_state is not None

        safety_state = ctx.safety_state
        safety_timers = ctx.safety_timers
        safety_outputs = ctx.safety_outputs
        safety_config = self.safety_config
        precharging = (
            safety_state == SafetyState.ARMED
            and safety_timers.precharge_elapsed_s < safety_config.precharge_timeout_s
        )

        throttle, brake, steering = self._resolve_controls(
            safety_state=safety_state,
            precharging=precharging,
            vehicle_state=vehicle_state,
            dt_s=dt_s,
        )

        env = self.scenario.environment
        env = self.track_context.environment_at(
            vehicle_state.position_x_m,
            vehicle_state.position_y_m,
            env,
        )

        power_on = False
        if (
            self.config.control_source == ControlSource.MANUAL
            and self._manual_controls.power_on_request
            and safety_state == SafetyState.OFF
        ):
            power_on = True
        elif self.scenario.auto_boot and safety_state == SafetyState.OFF and step == 0:
            power_on = True

        arm_request = bool(self._manual_controls.arm_request)
        disarm_request = bool(self._manual_controls.disarm_request)
        synthetic_brake_hold = False
        if (
            self.scenario.auto_boot
            and not self.config.free_mode
            and safety_state == SafetyState.READY
            and not ctx.auto_arm_sent
        ):
            arm_request = True
            synthetic_brake_hold = True
            ctx.auto_arm_sent = True
        if precharging:
            synthetic_brake_hold = True

        manual_mode = self.config.control_source == ControlSource.MANUAL
        auto_drive = self.config.control_source == ControlSource.AUTO
        if synthetic_brake_hold:
            safety_brake_pressed = True
        elif manual_mode and safety_state == SafetyState.DRIVING:
            safety_brake_pressed = False
        elif auto_drive and safety_state == SafetyState.DRIVING:
            safety_brake_pressed = brake > 0.1
        else:
            safety_brake_pressed = brake > 0.1

        fault_ack = bool(self._manual_controls.fault_ack_request)
        power_cycle_event = bool(self._manual_controls.power_cycle_request)
        if manual_mode and fault_ack:
            power_cycle_event = True
            if safety_state == SafetyState.OFF:
                power_on = True
        if auto_drive and fault_ack:
            power_cycle_event = True

        detect_throttle = 0.0 if synthetic_brake_hold else throttle
        detect_brake = 1.0 if synthetic_brake_hold else brake

        motor_rpm = motor_rpm_from_speed(self.vehicle_model.drivetrain_params, vehicle_state.speed_mps)
        closed, _open_fb = _contactor_feedback(safety_state, safety_outputs.contactor_command)
        sensors = _build_sensor_inputs(
            throttle=detect_throttle,
            brake=detect_brake,
            vehicle_state=vehicle_state,
            motor_rpm=motor_rpm,
            drivetrain=self.vehicle_model.drivetrain_params,
            contactor_closed=closed,
            series_cells=self.series_cells,
            battery_params=self.vehicle_model.battery_params,
        )
        sensors = self.injector.apply(time_s, sensors)
        _sync_injected_temps(vehicle_state, sensors)

        if (
            step == 0
            or synthetic_brake_hold
            or (ctx.prev_synthetic_brake_hold and not synthetic_brake_hold)
        ):
            ctx.detection_state.previous_throttle_adc = sensors.throttle_adc

        detected = detect_faults(
            sensors,
            safety_config,
            detection_state=ctx.detection_state,
            dt=self.dt_s,
        )
        if manual_mode or self.config.control_source == ControlSource.RL:
            detected.discard(FaultId.THROTTLE_BRAKE_SIMULTANEOUS)
            detected.discard(FaultId.THROTTLE_IMPLAUSIBLE)
        ctx.detection_state.previous_throttle_adc = sensors.throttle_adc
        ctx.prev_synthetic_brake_hold = synthetic_brake_hold

        safety_state, safety_outputs, safety_timers, latched_faults = safety_step(
            safety_state,
            SafetyInputs(
                power_on_request=power_on,
                arm_request=arm_request,
                disarm_request=disarm_request,
                fault_ack_request=fault_ack,
                power_cycle_event=power_cycle_event,
                driver_authenticated=True,
                brake_pressed=safety_brake_pressed,
                throttle=detect_throttle if synthetic_brake_hold else throttle,
                detected_faults=detected,
                precharge_feedback_ok=sensors.precharge_feedback_ok,
                contactor_feedback_closed=sensors.contactor_feedback_closed,
                contactor_feedback_open=not sensors.contactor_feedback_closed,
            ),
            safety_config,
            safety_timers,
            latched_faults=ctx.latched_faults,
            dt=dt_s,
        )
        ctx.safety_state = safety_state
        ctx.safety_outputs = safety_outputs
        ctx.safety_timers = safety_timers
        ctx.latched_faults = latched_faults

        fault_active_states = {SafetyState.FAULT, SafetyState.SAFE_SHUTDOWN}
        if safety_state in fault_active_states:
            throttle = 0.0
            if ctx.prev_safety_state not in fault_active_states:
                ctx.control_state = ControlState()

        limits = _resolve_sim_limits(
            self.vehicle_model,
            self.control_params.mode,
            self.profile,
            self.root,
            derating=safety_outputs.derating,
        )
        ctx.limits = limits

        control_out, control_state = control_step(
            ControlInputs(
                throttle=throttle,
                brake=brake,
                speed_mps=vehicle_state.speed_mps,
                motor_rpm=motor_rpm,
                pack_voltage_v=vehicle_state.pack_voltage_v,
                mass_kg=self.vehicle_model.mass_kg,
                grip_coefficient=self.vehicle_model.grip_coefficient * env.surface_mu_scale,
                gradient_rad=env.gradient_rad,
                rear_traction_limit_n=self.vehicle_model.rear_traction_limit_n(
                    speed_mps=vehicle_state.speed_mps,
                    steering=steering,
                    gradient_rad=env.gradient_rad,
                    surface_mu_scale=env.surface_mu_scale,
                ),
            ),
            limits,
            safety_outputs,
            ctx.control_state,
            self.control_params,
            dt_s,
        )
        ctx.control_state = control_state

        if safety_outputs.contactor_command != ContactorCommand.CLOSE:
            control_out = type(control_out)(
                motor_torque_request_nm=0.0,
                regen_torque_request_nm=0.0,
                mechanical_brake=control_out.mechanical_brake,
                filtered_throttle=control_out.filtered_throttle,
                traction_limited=False,
            )

        vehicle_state, physics_out = self.vehicle_model.step(
            vehicle_state,
            VehicleStepInputs(
                motor_torque_request_nm=control_out.motor_torque_request_nm,
                regen_torque_request_nm=control_out.regen_torque_request_nm,
                mechanical_brake=control_out.mechanical_brake,
                environment=env,
                steering=steering,
            ),
            dt_s,
        )
        ctx.vehicle_state = vehicle_state

        track_values = self.track_context.tick(
            time_s,
            physics_out.position_x_m,
            physics_out.position_y_m,
            physics_out.speed_mps,
        )

        lat_accel = lateral_accel_from_bicycle_mps2(
            physics_out.speed_mps,
            steering_angle_rad(steering),
            self.vehicle_model.config.wheelbase_m,
        )
        pitch_deg, roll_deg = vehicle_attitude_deg(
            gradient_rad=env.gradient_rad,
            long_accel_mps2=physics_out.acceleration_mps2,
            lat_accel_mps2=lat_accel,
            wheelbase_m=self.vehicle_model.config.wheelbase_m,
            cg_height_m=self.vehicle_model.config.cg_height_m,
            speed_mps=vehicle_state.speed_mps,
        )

        tick = SimTickRecord(
            time_s=time_s,
            values={
                "position_m": physics_out.position_m,
                "speed_mps": physics_out.speed_mps,
                "acceleration_mps2": physics_out.acceleration_mps2,
                "throttle": throttle,
                "brake": brake,
                "steering": steering,
                "steering_angle_deg": physics_out.steering_angle_deg,
                "heading_deg": physics_out.heading_deg,
                "elevation_m": track_values.get("elevation_m", 0.0),
                "pitch_deg": pitch_deg,
                "roll_deg": roll_deg,
                "position_x_m": physics_out.position_x_m,
                "position_y_m": physics_out.position_y_m,
                **{k: v for k, v in track_values.items() if k != "elevation_m"},
                "motor_rpm": physics_out.motor_rpm,
                "motor_torque_nm": physics_out.motor_torque_nm,
                "motor_current_a": physics_out.motor_current_a,
                "battery_current_a": physics_out.battery_current_a,
                "pack_voltage_v": physics_out.pack_voltage_v,
                "soc": physics_out.soc,
                "power_w": physics_out.power_w,
                "traction_force_n": physics_out.traction_force_n,
                "motor_temp_c": physics_out.motor_temp_c,
                "battery_temp_c": physics_out.battery_temp_c,
                "traction_limited": float(control_out.traction_limited),
                "filtered_throttle": control_out.filtered_throttle,
                "drive_mode": self.control_params.mode.name,
                "safety_state": safety_state.value,
                "contactor_command": safety_outputs.contactor_command.value,
                "torque_permitted": float(safety_outputs.torque_permitted),
                "active_faults": ",".join(f.value for f in safety_outputs.active_faults),
                "derating_factor": safety_outputs.derating.power,
                "max_speed_mps": limits.max_speed_mps,
            },
        )
        ctx.last_tick = tick
        ctx.step_index += 1
        ctx.prev_safety_state = safety_state

        track_s = float(track_values.get("track_s_m", ctx.prev_track_s_m))
        delta_s = track_s - ctx.prev_track_s_m
        if delta_s < -self.config.track.length_m * 0.5:
            delta_s += self.config.track.length_m
        ctx.prev_track_s_m = track_s

        terminated = False
        truncated = False
        if safety_state == SafetyState.SAFE_SHUTDOWN:
            terminated = True
        elif safety_state == SafetyState.FAULT and self._has_blocking_fault(safety_outputs):
            terminated = True
        elif (
            self.config.target_laps > 0
            and len(self.track_context.completed_laps) >= self.config.target_laps
        ):
            terminated = True
        elif ctx.step_index >= self.config.max_steps:
            truncated = True

        info = {
            "delta_track_s_m": delta_s,
            "track_s_m": track_s,
            "lateral_offset_m": float(track_values.get("track_lateral_m", 0.0)),
            "off_track": float(
                abs(float(track_values.get("track_lateral_m", 0.0)))
                > self.config.track.width_m * 0.5
            ),
            "track_width_m": self.config.track.width_m,
            "lap_number": float(track_values.get("lap_number", 0.0)),
            "lap_time_s": float(track_values.get("lap_time_s", 0.0)),
            "completed_laps": len(self.track_context.completed_laps),
            "battery_temp_derate_c": self.safety_config.battery_temp_derate_c,
            "battery_temp_fault_c": self.safety_config.battery_temp_fault_c,
        }
        return StepResult(
            tick=tick,
            safety_state=safety_state,
            terminated=terminated,
            truncated=truncated,
            info=info,
        )

    def run_until(
        self,
        *,
        on_tick=None,
        stop_requested: callable | None = None,
        max_steps: int | None = None,
        action_fn: callable | None = None,
    ) -> SimulationResult:
        records: list[SimTickRecord] = []
        limit = max_steps or self.config.max_steps
        if self.state.step_index == 0 and self.state.last_tick is None:
            result = self.reset()
            records.append(result.tick)
            if on_tick:
                on_tick(result.tick)

        while self.state.step_index < limit:
            if stop_requested and stop_requested():
                break
            action = action_fn() if action_fn else None
            step_result = self.step(action=action)
            records.append(step_result.tick)
            if on_tick:
                on_tick(step_result.tick)
            if step_result.terminated or step_result.truncated:
                break

        assert self.state.vehicle_state is not None
        return SimulationResult(
            records=records,
            final_state=self.state.vehicle_state,
            completed_laps=self.track_context.completed_laps,
        )

    def _resolve_controls(
        self,
        *,
        safety_state: SafetyState,
        precharging: bool,
        vehicle_state: VehicleState,
        dt_s: float,
    ) -> tuple[float, float, float]:
        source = self.config.control_source
        if source == ControlSource.AUTO and self.auto_driver is not None:
            battery_soc = vehicle_state.battery.soc if vehicle_state.battery else 1.0
            battery_temp = (
                vehicle_state.battery_thermal.temperature_c
                if vehicle_state.battery_thermal is not None
                else 25.0
            )
            if safety_state in {SafetyState.DRIVING, SafetyState.ARMED} and not precharging:
                driver_out = self.auto_driver.step(
                    x=vehicle_state.position_x_m,
                    y=vehicle_state.position_y_m,
                    heading_rad=vehicle_state.heading_rad,
                    speed_mps=vehicle_state.speed_mps,
                    soc=battery_soc,
                    battery_temp_c=battery_temp,
                    dt=dt_s,
                )
                return driver_out.throttle, driver_out.brake, driver_out.steering
            return 0.0, 1.0 if precharging else 0.0, 0.0

        if source == ControlSource.MANUAL:
            return (
                self._manual_controls.throttle,
                self._manual_controls.brake,
                self._manual_controls.steering,
            )

        if source == ControlSource.RL:
            if safety_state in {SafetyState.DRIVING, SafetyState.ARMED} and not precharging:
                if self._pending_rl_action is not None:
                    throttle, brake, steering = self._pending_rl_action
                    self._pending_rl_action = None
                    return (
                        max(0.0, min(1.0, throttle)),
                        max(0.0, min(1.0, brake)),
                        max(-1.0, min(1.0, steering)),
                    )
            return 0.0, 1.0 if precharging else 0.0, 0.0

        throttle, brake = self.scenario.driver_inputs_at(self.state.time_s)
        return throttle, brake, 0.0

    @staticmethod
    def _has_blocking_fault(outputs: SafetyOutputs) -> bool:
        from gokart.safety.faults import FAULT_REGISTRY
        from gokart.safety.types import FaultSeverity

        for fault in outputs.active_faults:
            severity = FAULT_REGISTRY[fault].severity
            if severity in {FaultSeverity.FAULT, FaultSeverity.CRITICAL}:
                return True
        return False
