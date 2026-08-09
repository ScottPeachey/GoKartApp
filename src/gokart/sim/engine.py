"""Fixed-timestep simulation engine."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gokart.config.schemas.modes import DriveMode, DriverProfile
from gokart.config.store import data_root, load_drive_mode, load_driver_profile
from gokart.config.validation import hardware_limits_from_components, validate_vehicle_config
from gokart.control.pipeline import (
    ControlInputs,
    ControlParams,
    ControlState,
    SafetyOutputs,
    control_step,
)
from gokart.limits.resolver import resolve_limits
from gokart.physics.drivetrain import motor_rpm_from_speed
from gokart.physics.vehicle import (
    VehicleModel,
    VehicleState,
    VehicleStepInputs,
    load_validated_vehicle_model,
)
from gokart.sim.clock import SimClock
from gokart.sim.scenarios import Scenario
from gokart.telemetry.channels import CHANNEL_NAMES

DEFAULT_DT_S = 0.01


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


def _resolve_sim_limits(
    vehicle_model: VehicleModel,
    mode: DriveMode,
    profile: DriverProfile,
    data_root_path: Path,
):
    from gokart.config.store import load_component

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
    return resolve_limits(hardware, config.limits, mode.limits, profile.limits)


def run_simulation(
    vehicle_name: str,
    vehicle_version: str,
    scenario: Scenario,
    *,
    data_root_path: Path | None = None,
    dt_s: float = DEFAULT_DT_S,
    speedup: float = 0.0,
    initial_speed_mps: float = 0.0,
) -> SimulationResult:
    root = data_root_path or data_root()
    vehicle_model = load_validated_vehicle_model(vehicle_name, vehicle_version, data_root=root)
    mode = load_drive_mode(scenario.mode_name, root=root)
    profile = load_driver_profile(scenario.profile_name, root=root)

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

    limits = _resolve_sim_limits(vehicle_model, mode, profile, root)
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
    steps = int(scenario.duration_s / dt_s)
    safety = SafetyOutputs()

    for step in range(steps):
        time_s = step * dt_s
        throttle, brake = scenario.driver_inputs_at(time_s)
        env = scenario.environment

        motor_rpm = motor_rpm_from_speed(vehicle_model.drivetrain_params, vehicle_state.speed_mps)
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
            safety,
            control_state,
            control_params,
            dt_s,
        )

        vehicle_state, physics_out = vehicle_model.step(
            vehicle_state,
            VehicleStepInputs(
                motor_torque_request_nm=control_out.motor_torque_request_nm,
                regen_torque_request_nm=control_out.regen_torque_request_nm,
                mechanical_brake=control_out.mechanical_brake,
                environment=env,
            ),
            dt_s,
        )

        records.append(
            SimTickRecord(
                time_s=time_s,
                values={
                    "position_m": physics_out.position_m,
                    "speed_mps": physics_out.speed_mps,
                    "acceleration_mps2": physics_out.acceleration_mps2,
                    "throttle": throttle,
                    "brake": brake,
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
                },
            )
        )

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
