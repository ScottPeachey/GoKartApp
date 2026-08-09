#!/usr/bin/env python3
# ruff: noqa: E501
"""Generate cross-language golden test vectors from the Python reference."""

from __future__ import annotations

import json
import random
import struct
from dataclasses import asdict
from pathlib import Path

from gokart.control.pipeline import ControlInputs, ControlParams, ControlState, control_step
from gokart.limits.resolver import DeratingFactors, EffectiveLimits, resolve_limits
from gokart.safety.faults import DetectionState, SafetyConfig, SensorInputs, detect_faults
from gokart.safety.state_machine import SafetyInputs, SafetyTimers, safety_step
from gokart.safety.types import FaultId, SafetyState

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "shared" / "golden"
GENERATED_HEADER = ROOT / "firmware" / "core_c" / "tests" / "golden_data.h"

FAULT_ID_TO_INT = {fault: index for index, fault in enumerate(FaultId)}
SAFETY_STATE_TO_INT = {state: index for index, state in enumerate(SafetyState)}


def to_f32(value: float) -> float:
  return struct.unpack("f", struct.pack("f", value))[0]


def fault_set_to_mask(faults: set[FaultId]) -> int:
    mask = 0
    for fault in faults:
        mask |= 1 << FAULT_ID_TO_INT[fault]
    return mask


def mask_to_fault_set(mask: int) -> set[FaultId]:
    faults: set[FaultId] = set()
    for fault in FaultId:
        if mask & (1 << FAULT_ID_TO_INT[fault]):
            faults.add(fault)
    return faults


def _layer(
    *,
    speed: float = 25.0,
    motor_a: float = 150.0,
    battery_a: float = 120.0,
    regen_a: float = 40.0,
    power_w: float = 8000.0,
    rpm: float = 6000.0,
    accel: float = 6.0,
    decel: float = 8.0,
    gradient: float = 0.2,
) -> dict[str, float]:
    return {
        "max_speed_mps": speed,
        "max_motor_current_a": motor_a,
        "max_battery_current_a": battery_a,
        "max_regen_current_a": regen_a,
        "max_power_w": power_w,
        "max_motor_rpm": rpm,
        "max_accel_mps2": accel,
        "max_decel_mps2": decel,
        "max_gradient_rad": gradient,
    }


def generate_limits_cases(seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    cases: list[dict] = []
    base_hw = _layer(speed=30.0, motor_a=200.0, battery_a=180.0)
    base_vehicle = _layer(speed=25.0, motor_a=150.0, battery_a=120.0)
    base_mode = _layer(speed=22.0, motor_a=120.0, battery_a=100.0)
    base_profile = _layer(speed=20.0, motor_a=100.0, battery_a=80.0)

    for derate_speed in (1.0, 0.5, 0.25):
        for _ in range(20):
            hw = {k: v * rng.uniform(0.8, 1.2) for k, v in base_hw.items()}
            vehicle = {k: v * rng.uniform(0.8, 1.0) for k, v in base_vehicle.items()}
            mode = {k: v * rng.uniform(0.7, 1.0) for k, v in base_mode.items()}
            profile = {k: v * rng.uniform(0.6, 1.0) for k, v in base_profile.items()}
            derating = {
                "speed": derate_speed,
                "motor_current": 1.0,
                "battery_current": 1.0,
                "regen_current": 1.0,
                "power": 1.0,
                "motor_rpm": 1.0,
                "accel": 1.0,
                "decel": 1.0,
                "gradient": 1.0,
            }
            from gokart.config.schemas.limits import (
                DriveModeLimits,
                DriverProfileLimits,
                HardwareLimits,
                VehicleLimits,
            )

            result = resolve_limits(
                HardwareLimits(**hw),
                VehicleLimits(**vehicle),
                DriveModeLimits(**mode),
                DriverProfileLimits(**profile),
                DeratingFactors(**derating),
            )
            expected = {key: to_f32(value) for key, value in asdict(result).items()}
            cases.append(
                {
                    "hardware": hw,
                    "vehicle": vehicle,
                    "mode": mode,
                    "profile": profile,
                    "derating": derating,
                    "expected": expected,
                }
            )
    return cases


def generate_safety_cases() -> list[dict]:
    config = SafetyConfig()
    cases: list[dict] = []

    sequences = [
        (SafetyState.OFF, {"power_on_request": True}),
        (SafetyState.BOOT, {}),
        (SafetyState.SELF_TEST, {}),
        (SafetyState.SELF_TEST, {}),
        (SafetyState.READY, {"arm_request": True, "brake_pressed": True}),
        (SafetyState.ARMED, {}),
        (SafetyState.ARMED, {}),
        (SafetyState.ARMED, {"throttle": 0.5}),
    ]

    state = SafetyState.OFF
    timers = SafetyTimers()
    latched: set[FaultId] = set()
    for _index, (_expected_state, input_overrides) in enumerate(sequences):
        inputs = SafetyInputs(**input_overrides)
        next_state, outputs, timers, latched = safety_step(
            state, inputs, config, timers, latched_faults=latched, dt=0.01
        )
        cases.append(
            {
                "state": SAFETY_STATE_TO_INT[state],
                "inputs": {
                    "power_on_request": inputs.power_on_request,
                    "arm_request": inputs.arm_request,
                    "disarm_request": inputs.disarm_request,
                    "fault_ack_request": inputs.fault_ack_request,
                    "power_cycle_event": inputs.power_cycle_event,
                    "driver_authenticated": inputs.driver_authenticated,
                    "brake_pressed": inputs.brake_pressed,
                    "throttle": inputs.throttle,
                    "detected_faults": fault_set_to_mask(inputs.detected_faults),
                    "precharge_feedback_ok": inputs.precharge_feedback_ok,
                },
                "config": asdict(config),
                "timers": asdict(timers),
                "latched_faults": fault_set_to_mask(latched),
                "dt": 0.01,
                "expected": {
                    "state": SAFETY_STATE_TO_INT[next_state],
                    "torque_permitted": outputs.torque_permitted,
                    "regen_permitted": outputs.regen_permitted,
                    "contactor_command": outputs.contactor_command.value,
                    "derating_factor": outputs.derating.speed,
                    "active_faults": fault_set_to_mask(set(outputs.active_faults)),
                    "display_message_code": outputs.display_message_code,
                },
            }
        )
        state = next_state

    fault_inputs = [
        SensorInputs(throttle_adc=50),
        SensorInputs(brake_adc=5000),
        SensorInputs(throttle=0.5, brake=0.5),
        SensorInputs(wheel_speed_valid=False),
        SensorInputs(pack_voltage_v=70.0),
        SensorInputs(pack_voltage_v=30.0),
        SensorInputs(motor_temp_c=130.0),
        SensorInputs(motor_temp_c=110.0),
        SensorInputs(battery_temp_c=65.0),
        SensorInputs(speed_mps=25.0),
        SensorInputs(watchdog_reset_detected=True),
        SensorInputs(can_vesc_alive=False),
    ]
    for sensor in fault_inputs:
        detection = DetectionState()
        faults = detect_faults(sensor, config, detection_state=detection)
        cases.append(
            {
                "kind": "detect_faults",
                "inputs": asdict(sensor),
                "config": asdict(config),
                "previous_throttle_adc": detection.previous_throttle_adc,
                "expected_faults": fault_set_to_mask(faults),
            }
        )

    # precharge failure path
    state = SafetyState.ARMED
    timers = SafetyTimers(precharge_elapsed_s=0.0)
    inputs = SafetyInputs(precharge_feedback_ok=False)
    next_state, outputs, timers, latched = safety_step(
        state, inputs, config, timers, latched_faults=set(), dt=0.01
    )
    cases.append(
        {
            "state": SAFETY_STATE_TO_INT[state],
            "inputs": {
                "precharge_feedback_ok": False,
                "detected_faults": 0,
            },
            "config": asdict(config),
            "timers": {"state_elapsed_s": 0.0, "precharge_elapsed_s": 0.0, "shutdown_elapsed_s": 0.0},
            "latched_faults": 0,
            "dt": 0.01,
            "expected": {
                "state": SAFETY_STATE_TO_INT[next_state],
                "torque_permitted": outputs.torque_permitted,
                "contactor_command": outputs.contactor_command.value,
            },
        }
    )
    return cases


def generate_control_cases(seed: int = 7) -> list[dict]:
    from gokart.config.schemas.modes import DriveMode
    from gokart.safety.state_machine import SafetyOutputs
    from gokart.safety.types import ContactorCommand

    rng = random.Random(seed)
    mode = DriveMode(
        name="Default",
        throttle_curve="linear",
        throttle_ramp_per_s=2.0,
        traction_limiter="moderate",
        regen_strength=0.5,
        limits={
            "max_speed_mps": 22.0,
            "max_motor_current_a": 120.0,
            "max_battery_current_a": 100.0,
            "max_regen_current_a": 40.0,
            "max_power_w": 6000.0,
            "max_motor_rpm": 5000.0,
            "max_accel_mps2": 5.0,
            "max_decel_mps2": 7.0,
            "max_gradient_rad": 0.15,
        },
    )
    limits = EffectiveLimits(
        max_speed_mps=20.0,
        max_motor_current_a=100.0,
        max_battery_current_a=80.0,
        max_regen_current_a=30.0,
        max_power_w=5000.0,
        max_motor_rpm=4500.0,
        max_accel_mps2=4.0,
        max_decel_mps2=6.0,
        max_gradient_rad=0.12,
    )
    safety_on = SafetyOutputs(
        torque_permitted=True,
        regen_permitted=True,
        contactor_command=ContactorCommand.CLOSE,
        derating=DeratingFactors(),
        active_faults=(),
        display_message_code=0,
        safety_state=SafetyState.DRIVING,
    )
    safety_off = SafetyOutputs(
        torque_permitted=False,
        regen_permitted=False,
        contactor_command=ContactorCommand.OPEN,
        derating=DeratingFactors(),
        active_faults=(),
        display_message_code=0,
        safety_state=SafetyState.READY,
    )
    params = ControlParams(
        mode=mode,
        motor_peak_torque_nm=40.0,
        wheel_radius_m=0.127,
        gear_ratio=4.33,
        drivetrain_efficiency=0.92,
        motor_efficiency=0.9,
    )
    cases: list[dict] = []
    state = ControlState()
    for _ in range(80):
        state_in = ControlState(
            filtered_throttle=state.filtered_throttle,
            traction_scale=state.traction_scale,
        )
        inputs = ControlInputs(
            throttle=rng.random(),
            brake=rng.random() * 0.3,
            speed_mps=rng.uniform(0.0, 18.0),
            motor_rpm=rng.uniform(100.0, 4000.0),
            pack_voltage_v=rng.uniform(44.0, 54.0),
            mass_kg=180.0,
            grip_coefficient=0.9,
            gradient_rad=0.0,
        )
        safety = safety_on if rng.random() > 0.1 else safety_off
        outputs, state = control_step(inputs, limits, safety, state, params, 0.01)
        cases.append(
            {
                "inputs": asdict(inputs),
                "limits": asdict(limits),
                "safety": {
                    "torque_permitted": safety.torque_permitted,
                    "regen_permitted": safety.regen_permitted,
                },
                "state_in": {
                    "filtered_throttle": state_in.filtered_throttle,
                    "traction_scale": state_in.traction_scale,
                },
                "params": {
                    "throttle_curve": mode.throttle_curve,
                    "throttle_ramp_per_s": mode.throttle_ramp_per_s,
                    "throttle_ramp_enabled": mode.throttle_ramp_per_s is not None,
                    "traction_limiter": mode.traction_limiter,
                    "regen_strength": mode.regen_strength,
                    "motor_peak_torque_nm": params.motor_peak_torque_nm,
                    "wheel_radius_m": params.wheel_radius_m,
                    "gear_ratio": params.gear_ratio,
                    "drivetrain_efficiency": params.drivetrain_efficiency,
                    "motor_efficiency": params.motor_efficiency,
                },
                "dt": 0.01,
                "expected": {
                    "motor_torque_request_nm": to_f32(outputs.motor_torque_request_nm),
                    "regen_torque_request_nm": to_f32(outputs.regen_torque_request_nm),
                    "mechanical_brake": to_f32(outputs.mechanical_brake),
                    "filtered_throttle": to_f32(outputs.filtered_throttle),
                    "traction_limited": outputs.traction_limited,
                },
            }
        )
    return cases


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def emit_golden_inc(
    limits_cases: list[dict],
    safety_cases: list[dict],
    control_cases: list[dict],
) -> None:
    lines: list[str] = []

    lines.append("static void run_generated_limits_cases(void) {")
    for case in limits_cases:
        hw = case["hardware"]
        vehicle = case["vehicle"]
        mode = case["mode"]
        profile = case["profile"]
        der = case["derating"]
        exp = case["expected"]
        lines.append("    {")
        lines.append(
            f"        gk_limit_layer_t hw = read_layer({hw['max_speed_mps']:.8f}f, "
            f"{hw['max_motor_current_a']:.8f}f, {hw['max_battery_current_a']:.8f}f, "
            f"{hw['max_regen_current_a']:.8f}f, {hw['max_power_w']:.8f}f, "
            f"{hw['max_motor_rpm']:.8f}f, {hw['max_accel_mps2']:.8f}f, "
            f"{hw['max_decel_mps2']:.8f}f, {hw['max_gradient_rad']:.8f}f);"
        )
        lines.append(
            f"        gk_limit_layer_t vehicle = read_layer({vehicle['max_speed_mps']:.8f}f, "
            f"{vehicle['max_motor_current_a']:.8f}f, {vehicle['max_battery_current_a']:.8f}f, "
            f"{vehicle['max_regen_current_a']:.8f}f, {vehicle['max_power_w']:.8f}f, "
            f"{vehicle['max_motor_rpm']:.8f}f, {vehicle['max_accel_mps2']:.8f}f, "
            f"{vehicle['max_decel_mps2']:.8f}f, {vehicle['max_gradient_rad']:.8f}f);"
        )
        lines.append(
            f"        gk_limit_layer_t mode = read_layer({mode['max_speed_mps']:.8f}f, "
            f"{mode['max_motor_current_a']:.8f}f, {mode['max_battery_current_a']:.8f}f, "
            f"{mode['max_regen_current_a']:.8f}f, {mode['max_power_w']:.8f}f, "
            f"{mode['max_motor_rpm']:.8f}f, {mode['max_accel_mps2']:.8f}f, "
            f"{mode['max_decel_mps2']:.8f}f, {mode['max_gradient_rad']:.8f}f);"
        )
        lines.append(
            f"        gk_limit_layer_t profile = read_layer({profile['max_speed_mps']:.8f}f, "
            f"{profile['max_motor_current_a']:.8f}f, {profile['max_battery_current_a']:.8f}f, "
            f"{profile['max_regen_current_a']:.8f}f, {profile['max_power_w']:.8f}f, "
            f"{profile['max_motor_rpm']:.8f}f, {profile['max_accel_mps2']:.8f}f, "
            f"{profile['max_decel_mps2']:.8f}f, {profile['max_gradient_rad']:.8f}f);"
        )
        lines.append(
            f"        gk_derating_factors_t der = {{{der['speed']:.8f}f, {der['motor_current']:.8f}f, "
            f"{der['battery_current']:.8f}f, {der['regen_current']:.8f}f, {der['power']:.8f}f, "
            f"{der['motor_rpm']:.8f}f, {der['accel']:.8f}f, {der['decel']:.8f}f, {der['gradient']:.8f}f}};"
        )
        lines.append(
            f"        gk_effective_limits_t exp = {{{exp['max_speed_mps']:.8f}f, "
            f"{exp['max_motor_current_a']:.8f}f, {exp['max_battery_current_a']:.8f}f, "
            f"{exp['max_regen_current_a']:.8f}f, {exp['max_power_w']:.8f}f, "
            f"{exp['max_motor_rpm']:.8f}f, {exp['max_accel_mps2']:.8f}f, "
            f"{exp['max_decel_mps2']:.8f}f, {exp['max_gradient_rad']:.8f}f}};"
        )
        lines.append("        run_limits_case(&hw, &vehicle, &mode, &profile, &der, &exp);")
        lines.append("    }")
    lines.append("}")

    lines.append("static void run_generated_safety_cases(void) {")
    for case in safety_cases:
        if case.get("kind") == "detect_faults":
            sensor = case["inputs"]
            config = case["config"]
            lines.append("    {")
            lines.append(
                f"        gk_sensor_inputs_t sensor = {{{sensor['throttle_adc']}, "
                f"{sensor['brake_adc']}, {sensor['throttle']:.8f}f, {sensor['brake']:.8f}f, "
                f"{sensor['speed_mps']:.8f}f, {sensor['motor_rpm']:.8f}f, "
                f"{sensor['implied_speed_mps']:.8f}f, {sensor['pack_voltage_v']:.8f}f, "
                f"{sensor['min_cell_voltage_v']:.8f}f, {sensor['max_cell_voltage_v']:.8f}f, "
                f"{sensor['motor_temp_c']:.8f}f, {sensor['controller_temp_c']:.8f}f, "
                f"{sensor['battery_temp_c']:.8f}f, "
                f"{str(sensor['wheel_speed_valid']).lower()}, "
                f"{str(sensor['can_vesc_alive']).lower()}, "
                f"{str(sensor['can_bms_alive']).lower()}, "
                f"{sensor['can_silence_s']:.8f}f, "
                f"{str(sensor['vesc_fault_active']).lower()}, "
                f"{str(sensor['bms_fault_active']).lower()}, "
                f"{str(sensor['watchdog_reset_detected']).lower()}}};"
            )
            lines.append(
                f"        gk_safety_config_t config = {{{config['throttle_adc_min']}, "
                f"{config['throttle_adc_max']}, {config['brake_adc_min']}, {config['brake_adc_max']}, "
                f"{config['throttle_brake_simultaneous_threshold']:.8f}f, "
                f"{config['pack_voltage_max_v']:.8f}f, {config['pack_voltage_min_v']:.8f}f, "
                f"{config['cell_voltage_max_v']:.8f}f, {config['cell_voltage_min_v']:.8f}f, "
                f"{config['motor_temp_derate_c']:.8f}f, {config['motor_temp_fault_c']:.8f}f, "
                f"{config['controller_temp_derate_c']:.8f}f, {config['controller_temp_fault_c']:.8f}f, "
                f"{config['battery_temp_derate_c']:.8f}f, {config['battery_temp_fault_c']:.8f}f, "
                f"{config['max_speed_mps']:.8f}f, {config['can_timeout_s']:.8f}f, "
                f"{config['precharge_timeout_s']:.8f}f, {config['self_test_duration_s']:.8f}f, "
                f"{config['throttle_drive_deadband']:.8f}f, "
                f"{config['wheel_speed_disagreement_ratio']:.8f}f, {config['derate_factor']:.8f}f}};"
            )
            lines.append(
                f"        run_detect_case(&sensor, &config, 0, {case['expected_faults']}u);"
            )
            lines.append("    }")
            continue

        inputs = case.get("inputs", {})
        config = case["config"]
        timers = case["timers"]
        expected = case["expected"]
        lines.append("    {")
        lines.append(
            f"        gk_safety_inputs_t inputs = {{{str(inputs.get('power_on_request', False)).lower()}, "
            f"{str(inputs.get('arm_request', False)).lower()}, "
            f"{str(inputs.get('disarm_request', False)).lower()}, "
            f"{str(inputs.get('fault_ack_request', False)).lower()}, "
            f"{str(inputs.get('power_cycle_event', False)).lower()}, "
            f"{str(inputs.get('driver_authenticated', True)).lower()}, "
            f"{str(inputs.get('brake_pressed', False)).lower()}, "
            f"{inputs.get('throttle', 0.0):.8f}f, {inputs.get('detected_faults', 0)}u, "
            f"{str(inputs.get('precharge_feedback_ok', True)).lower()}, false, true}};"
        )
        lines.append(
            f"        gk_safety_config_t config = {{{config['throttle_adc_min']}, "
            f"{config['throttle_adc_max']}, {config['brake_adc_min']}, {config['brake_adc_max']}, "
            f"{config['throttle_brake_simultaneous_threshold']:.8f}f, "
            f"{config['pack_voltage_max_v']:.8f}f, {config['pack_voltage_min_v']:.8f}f, "
            f"{config['cell_voltage_max_v']:.8f}f, {config['cell_voltage_min_v']:.8f}f, "
            f"{config['motor_temp_derate_c']:.8f}f, {config['motor_temp_fault_c']:.8f}f, "
            f"{config['controller_temp_derate_c']:.8f}f, {config['controller_temp_fault_c']:.8f}f, "
            f"{config['battery_temp_derate_c']:.8f}f, {config['battery_temp_fault_c']:.8f}f, "
            f"{config['max_speed_mps']:.8f}f, {config['can_timeout_s']:.8f}f, "
            f"{config['precharge_timeout_s']:.8f}f, {config['self_test_duration_s']:.8f}f, "
            f"{config['throttle_drive_deadband']:.8f}f, "
            f"{config['wheel_speed_disagreement_ratio']:.8f}f, {config['derate_factor']:.8f}f}};"
        )
        lines.append(
            f"        gk_safety_timers_t timers = {{{timers['state_elapsed_s']:.8f}f, "
            f"{timers['precharge_elapsed_s']:.8f}f, {timers['shutdown_elapsed_s']:.8f}f}};"
        )
        torque = expected.get("torque_permitted", False)
        lines.append(
            f"        run_safety_case((gk_safety_state_t){case['state']}, &inputs, &config, "
            f"&timers, {case['latched_faults']}u, {case['dt']:.8f}f, "
            f"(gk_safety_state_t){expected['state']}, {str(torque).lower()});"
        )
        lines.append("    }")
    lines.append("}")

    lines.append("static void run_generated_control_cases(void) {")
    lines.append("    gk_control_state_t state = {0.0f, 1.0f};")
    for case in control_cases:
        inputs = case["inputs"]
        limits = case["limits"]
        safety = case["safety"]
        params = case["params"]
        expected = case["expected"]
        state_in = case["state_in"]
        lines.append("    state.filtered_throttle = " f"{state_in['filtered_throttle']:.8f}f;")
        lines.append("    state.traction_scale = " f"{state_in['traction_scale']:.8f}f;")
        lines.append("    {")
        lines.append(
            f"        gk_control_inputs_t inputs = {{{inputs['throttle']:.8f}f, "
            f"{inputs['brake']:.8f}f, {inputs['speed_mps']:.8f}f, {inputs['motor_rpm']:.8f}f, "
            f"{inputs['pack_voltage_v']:.8f}f, {inputs['mass_kg']:.8f}f, "
            f"{inputs['grip_coefficient']:.8f}f, {inputs['gradient_rad']:.8f}f}};"
        )
        lines.append(
            f"        gk_effective_limits_t limits = {{{limits['max_speed_mps']:.8f}f, "
            f"{limits['max_motor_current_a']:.8f}f, {limits['max_battery_current_a']:.8f}f, "
            f"{limits['max_regen_current_a']:.8f}f, {limits['max_power_w']:.8f}f, "
            f"{limits['max_motor_rpm']:.8f}f, {limits['max_accel_mps2']:.8f}f, "
            f"{limits['max_decel_mps2']:.8f}f, {limits['max_gradient_rad']:.8f}f}};"
        )
        lines.append(
            f"        gk_safety_outputs_t safety = {{{str(safety['torque_permitted']).lower()}, "
            f"{str(safety['regen_permitted']).lower()}, GK_CONTACTOR_CLOSE, "
            f"{{1,1,1,1,1,1,1,1,1}}, 0, 0, GK_SAFETY_DRIVING}};"
        )
        curve = params["throttle_curve"]
        limiter = params["traction_limiter"]
        lines.append(
            f"        gk_control_params_t params = {{"
            f'{{"{curve}", {params["throttle_ramp_per_s"]:.8f}f, '
            f"{str(params['throttle_ramp_enabled']).lower()}, "
            f'"{limiter}", {params["regen_strength"]:.8f}f}}, '
            f"{params['motor_peak_torque_nm']:.8f}f, {params['wheel_radius_m']:.8f}f, "
            f"{params['gear_ratio']:.8f}f, {params['drivetrain_efficiency']:.8f}f, "
            f"{params['motor_efficiency']:.8f}f}};"
        )
        lines.append(
            f"        gk_control_outputs_t expected = {{{expected['motor_torque_request_nm']:.8f}f, "
            f"{expected['regen_torque_request_nm']:.8f}f, {expected['mechanical_brake']:.8f}f, "
            f"{expected['filtered_throttle']:.8f}f, {str(expected['traction_limited']).lower()}}};"
        )
        lines.append(
            f"        run_control_case(&inputs, &limits, &safety, &state, &params, "
            f"{case['dt']:.8f}f, &expected);"
        )
        lines.append("    }")
    lines.append("}")

    GENERATED_HEADER.parent.mkdir(parents=True, exist_ok=True)
    inc_path = GENERATED_HEADER.parent / "golden_cases.inc"
    inc_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    limits_cases = generate_limits_cases()
    safety_cases = generate_safety_cases()
    control_cases = generate_control_cases()

    write_json(GOLDEN_DIR / "limits.json", {"version": 1, "cases": limits_cases})
    write_json(GOLDEN_DIR / "safety.json", {"version": 1, "cases": safety_cases})
    write_json(GOLDEN_DIR / "control.json", {"version": 1, "cases": control_cases})
    emit_golden_inc(limits_cases, safety_cases, control_cases)

    print(f"Wrote {len(limits_cases)} limits cases")
    print(f"Wrote {len(safety_cases)} safety cases")
    print(f"Wrote {len(control_cases)} control cases")


if __name__ == "__main__":
    main()
