"""Fixed-timestep simulation engine."""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gokart.config.schemas.modes import DriveMode, DriverProfile
from gokart.config.schemas.vehicle import VehicleConfig
from gokart.config.store import data_root, load_component, load_drive_mode, load_driver_profile
from gokart.config.validation import hardware_limits_from_components, validate_vehicle_config
from gokart.control.pipeline import (
    ControlInputs,
    ControlParams,
    ControlState,
    SafetyOutputs,
    control_step,
)
from gokart.limits.resolver import resolve_limits
from gokart.physics.drivetrain import motor_rpm_from_speed, speed_from_motor_rpm
from gokart.physics.vehicle import (
    VehicleModel,
    VehicleState,
    VehicleStepInputs,
    load_validated_vehicle_model,
)
from gokart.safety.faults import DetectionState, SafetyConfig, SensorInputs, detect_faults
from gokart.safety.state_machine import SafetyInputs, SafetyTimers, safety_step
from gokart.safety.types import ContactorCommand, FaultId, SafetyState
from gokart.sim.clock import SimClock
from gokart.sim.fault_injection import FaultInjector
from gokart.sim.runtime import RuntimeControls
from gokart.sim.scenarios import Scenario
from gokart.telemetry.channels import CHANNEL_NAMES
from gokart.telemetry.recorder import SessionRecorder

DEFAULT_DT_S = 0.01

if TYPE_CHECKING:
    from gokart.analysis.overlays import CalibrationOverlay


@dataclass
class SimTickRecord:
    time_s: float
    values: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        return {"time_s": self.time_s, **self.values}


@dataclass
class SimulationResult:
    records: list[SimTickRecord]
    final_state: VehicleState


def _adc_from_pedal(value: float) -> int:
    return int(100 + max(0.0, min(1.0, value)) * 3800)


def _build_safety_config(
    vehicle_model: VehicleModel,
    limits,
    data_root_path: Path,
) -> SafetyConfig:
    config = vehicle_model.config
    battery = load_component("battery", config.battery.component_id, root=data_root_path)
    bms = load_component("bms", config.bms.component_id, root=data_root_path)
    return SafetyConfig(
        pack_voltage_max_v=battery.max_voltage_v,
        pack_voltage_min_v=battery.min_voltage_v,
        cell_voltage_max_v=(
            bms.max_cell_voltage_v or (battery.max_voltage_v / battery.series_cells)
        ),
        cell_voltage_min_v=(
            bms.min_cell_voltage_v or (battery.min_voltage_v / battery.series_cells)
        ),
        max_speed_mps=limits.max_speed_mps if limits.max_speed_mps > 0 else 20.0,
        battery_temp_fault_c=bms.max_temp_c,
        battery_temp_derate_c=max(25.0, bms.max_temp_c - 10.0),
    )


def _resolve_sim_limits(
    vehicle_model: VehicleModel,
    mode: DriveMode,
    profile: DriverProfile,
    data_root_path: Path,
    *,
    derating=None,
):
    config = vehicle_model.config
    motor = load_component("motor", config.motor.component_id, root=data_root_path)
    controller = load_component(
        "motor_controller",
        config.motor_controller.component_id,
        root=data_root_path,
    )
    battery = load_component("battery", config.battery.component_id, root=data_root_path)
    bms = load_component("bms", config.bms.component_id, root=data_root_path)
    hardware = hardware_limits_from_components(motor, controller, battery, bms)
    return resolve_limits(hardware, config.limits, mode.limits, profile.limits, derating)


def _contactor_feedback(safety_state: SafetyState, command: ContactorCommand) -> tuple[bool, bool]:
    if command == ContactorCommand.CLOSE and safety_state in {
        SafetyState.ARMED,
        SafetyState.DRIVING,
    }:
        return True, False
    return False, True


def _build_sensor_inputs(
    *,
    throttle: float,
    brake: float,
    vehicle_state: VehicleState,
    motor_rpm: float,
    drivetrain,
    contactor_closed: bool,
    series_cells: int,
    battery_params,
) -> SensorInputs:
    assert vehicle_state.motor_thermal is not None
    assert vehicle_state.battery_thermal is not None
    assert vehicle_state.battery is not None
    from gokart.physics.battery import _interp_curve

    implied_speed = speed_from_motor_rpm(drivetrain, motor_rpm)
    ocv_v = _interp_curve(
        vehicle_state.battery.soc,
        battery_params.ocv_curve,
        battery_params.nominal_voltage_v,
    )
    cell_v = ocv_v / max(series_cells, 1)
    return SensorInputs(
        throttle_adc=_adc_from_pedal(throttle),
        brake_adc=_adc_from_pedal(brake),
        throttle=throttle,
        brake=brake,
        speed_mps=vehicle_state.speed_mps,
        motor_rpm=motor_rpm,
        implied_speed_mps=implied_speed,
        pack_voltage_v=vehicle_state.pack_voltage_v,
        min_cell_voltage_v=cell_v,
        max_cell_voltage_v=cell_v,
        motor_temp_c=vehicle_state.motor_thermal.temperature_c,
        controller_temp_c=vehicle_state.motor_thermal.temperature_c,
        battery_temp_c=vehicle_state.battery_thermal.temperature_c,
        contactor_feedback_closed=contactor_closed,
        precharge_feedback_ok=True,
    )


def _sync_injected_temps(vehicle_state: VehicleState, sensors: SensorInputs) -> None:
    assert vehicle_state.motor_thermal is not None
    assert vehicle_state.battery_thermal is not None
    vehicle_state.motor_thermal.temperature_c = sensors.motor_temp_c
    vehicle_state.battery_thermal.temperature_c = sensors.battery_temp_c


def run_simulation(
    vehicle_name: str,
    vehicle_version: str,
    scenario: Scenario,
    *,
    data_root_path: Path | None = None,
    dt_s: float = DEFAULT_DT_S,
    speedup: float = 0.0,
    initial_speed_mps: float = 0.0,
    controls: RuntimeControls | None = None,
    on_tick: Callable[[SimTickRecord], None] | None = None,
    recorder: SessionRecorder | None = None,
    overlay: CalibrationOverlay | None = None,
    vehicle_config: VehicleConfig | None = None,
    keep_records: bool = True,
) -> SimulationResult:
    root = data_root_path or data_root()
    if vehicle_config is not None:
        validation = validate_vehicle_config(vehicle_config, data_root=root)
        if not validation.ok:
            raise ValueError("; ".join(v.message for v in validation.violations))
        vehicle_model = VehicleModel.from_config(vehicle_config, data_root=root)
    else:
        vehicle_model = load_validated_vehicle_model(vehicle_name, vehicle_version, data_root=root)
    if overlay is not None:
        from gokart.analysis.overlays import apply_overlay

        apply_overlay(vehicle_model, overlay)
    mode = load_drive_mode(scenario.mode_name, root=root)
    profile = load_driver_profile(scenario.profile_name, root=root)
    manual_mode = bool(controls and (controls.manual or controls.free_mode))
    free_mode = bool(controls and controls.free_mode)
    if manual_mode:
        mode = mode.model_copy(update={"throttle_ramp_per_s": None})

    validation = validate_vehicle_config(
        vehicle_model.config,
        data_root=root,
        mode=mode,
        profile=profile,
    )
    if not validation.ok:
        raise ValueError(
            "; ".join(v.message for v in validation.violations),
        )

    base_limits = _resolve_sim_limits(vehicle_model, mode, profile, root)
    safety_config = _build_safety_config(vehicle_model, base_limits, root)
    battery = load_component("battery", vehicle_model.config.battery.component_id, root=root)
    series_cells = battery.series_cells
    control_state = ControlState()
    vehicle_state = vehicle_model.initial_state()
    vehicle_state.speed_mps = initial_speed_mps

    control_params = ControlParams(
        mode=mode,
        motor_peak_torque_nm=vehicle_model.motor_params.peak_torque_nm,
        wheel_radius_m=vehicle_model.config.wheel_radius_m,
        gear_ratio=vehicle_model.drivetrain_params.gear_ratio,
        drivetrain_efficiency=vehicle_model.drivetrain_params.total_efficiency,
    )

    clock = SimClock(speedup=speedup)
    if speedup > 0:
        clock.start()

    records: list[SimTickRecord] = []
    retain_records = keep_records and recorder is None
    if controls and (controls.manual or controls.free_mode):
        steps = 10_000_000
    else:
        steps = int(scenario.duration_s / dt_s)
    injector = FaultInjector.from_scenario_data(scenario.injections)

    safety_state = SafetyState.OFF
    safety_timers = SafetyTimers()
    latched_faults: set = set()
    detection_state = DetectionState()
    auto_arm_sent = False
    from gokart.limits.resolver import DeratingFactors

    safety_outputs = SafetyOutputs(
        torque_permitted=False,
        regen_permitted=False,
        contactor_command=ContactorCommand.OPEN,
        derating=DeratingFactors(),
        active_faults=(),
        display_message_code=0,
        safety_state=SafetyState.OFF,
    )
    limits = base_limits
    prev_synthetic_brake_hold = False

    for step in range(steps):
        if controls and controls.stop_requested:
            break
        time_s = step * dt_s
        if manual_mode:
            throttle = controls.throttle  # type: ignore[union-attr]
            brake = controls.brake  # type: ignore[union-attr]
            steering = controls.steering  # type: ignore[union-attr]
        else:
            throttle, brake = scenario.driver_inputs_at(time_s)
            steering = 0.0
        env = scenario.environment

        power_on = False
        if controls and controls.power_on_request and manual_mode and safety_state == SafetyState.OFF:
            power_on = True
        elif scenario.auto_boot and safety_state == SafetyState.OFF and step == 0:
            power_on = True
        arm_request = bool(controls and controls.arm_request)
        disarm_request = bool(controls and controls.disarm_request)
        synthetic_brake_hold = False
        if scenario.auto_boot and not free_mode and safety_state == SafetyState.READY and not auto_arm_sent:
            arm_request = True
            synthetic_brake_hold = True
            auto_arm_sent = True
        precharging = (
            safety_state == SafetyState.ARMED
            and safety_timers.precharge_elapsed_s < safety_config.precharge_timeout_s
        )
        if precharging:
            synthetic_brake_hold = True

        if synthetic_brake_hold:
            safety_brake_pressed = True
        elif manual_mode and safety_state == SafetyState.DRIVING:
            safety_brake_pressed = False
        elif manual_mode:
            safety_brake_pressed = brake > 0.1
        else:
            safety_brake_pressed = brake > 0.1

        power_cycle_event = bool(controls and controls.power_cycle_request)
        fault_ack = bool(controls and controls.fault_ack_request)
        if manual_mode and fault_ack:
            power_cycle_event = True
            if safety_state == SafetyState.OFF:
                power_on = True

        detect_throttle = 0.0 if synthetic_brake_hold else throttle
        detect_brake = 1.0 if synthetic_brake_hold else brake

        motor_rpm = motor_rpm_from_speed(vehicle_model.drivetrain_params, vehicle_state.speed_mps)
        closed, _open_fb = _contactor_feedback(safety_state, safety_outputs.contactor_command)
        sensors = _build_sensor_inputs(
            throttle=detect_throttle,
            brake=detect_brake,
            vehicle_state=vehicle_state,
            motor_rpm=motor_rpm,
            drivetrain=vehicle_model.drivetrain_params,
            contactor_closed=closed,
            series_cells=series_cells,
            battery_params=vehicle_model.battery_params,
        )
        sensors = injector.apply(time_s, sensors)
        _sync_injected_temps(vehicle_state, sensors)

        if (
            step == 0
            or synthetic_brake_hold
            or (prev_synthetic_brake_hold and not synthetic_brake_hold)
        ):
            detection_state.previous_throttle_adc = sensors.throttle_adc

        detected = detect_faults(sensors, safety_config, detection_state=detection_state)
        if manual_mode:
            detected.discard(FaultId.THROTTLE_BRAKE_SIMULTANEOUS)
            detected.discard(FaultId.THROTTLE_IMPLAUSIBLE)
        detection_state.previous_throttle_adc = sensors.throttle_adc
        prev_synthetic_brake_hold = synthetic_brake_hold

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
            latched_faults=latched_faults,
            dt=dt_s,
        )

        if safety_state == SafetyState.READY:
            new_mode = scenario.mode_at(time_s)
            if new_mode and new_mode != control_params.mode.name:
                if vehicle_state.speed_mps <= safety_config.mode_change_max_speed_mps:
                    mode = load_drive_mode(new_mode, root=root)
                    control_params = ControlParams(
                        mode=mode,
                        motor_peak_torque_nm=vehicle_model.motor_params.peak_torque_nm,
                        wheel_radius_m=vehicle_model.config.wheel_radius_m,
                        gear_ratio=vehicle_model.drivetrain_params.gear_ratio,
                        drivetrain_efficiency=vehicle_model.drivetrain_params.total_efficiency,
                    )
            new_profile = scenario.profile_at(time_s)
            if new_profile and new_profile != profile.name:
                profile = load_driver_profile(new_profile, root=root)

        limits = _resolve_sim_limits(
            vehicle_model, control_params.mode, profile, root, derating=safety_outputs.derating
        )

        control_out, control_state = control_step(
            ControlInputs(
                throttle=throttle,
                brake=brake,
                speed_mps=vehicle_state.speed_mps,
                motor_rpm=motor_rpm,
                pack_voltage_v=vehicle_state.pack_voltage_v,
                mass_kg=vehicle_model.mass_kg,
                grip_coefficient=vehicle_model.grip_coefficient * env.surface_mu_scale,
                gradient_rad=env.gradient_rad,
            ),
            limits,
            safety_outputs,
            control_state,
            control_params,
            dt_s,
        )

        if safety_outputs.contactor_command != ContactorCommand.CLOSE:
            control_out = type(control_out)(
                motor_torque_request_nm=0.0,
                regen_torque_request_nm=0.0,
                mechanical_brake=control_out.mechanical_brake,
                filtered_throttle=control_out.filtered_throttle,
                traction_limited=False,
            )

        vehicle_state, physics_out = vehicle_model.step(
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
                "position_x_m": physics_out.position_x_m,
                "position_y_m": physics_out.position_y_m,
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
                "drive_mode": control_params.mode.name,
                "safety_state": safety_state.value,
                "contactor_command": safety_outputs.contactor_command.value,
                "torque_permitted": float(safety_outputs.torque_permitted),
                "active_faults": ",".join(f.value for f in safety_outputs.active_faults),
                "derating_factor": safety_outputs.derating.power,
            },
        )
        if retain_records:
            records.append(tick)
        if on_tick is not None:
            on_tick(tick)
        if recorder is not None:
            recorder.record_tick(tick.to_row())

        if speedup > 0:
            clock.tick(dt_s)

    return SimulationResult(records=records, final_state=vehicle_state)


def write_csv(path: Path, records: list[SimTickRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(CHANNEL_NAMES)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_row())
