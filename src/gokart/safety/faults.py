"""Fault registry and pure detection logic."""

from __future__ import annotations

from dataclasses import dataclass

from gokart.limits.resolver import DeratingFactors
from gokart.safety.types import FaultId, FaultSeverity


@dataclass(frozen=True)
class FaultDefinition:
    fault_id: FaultId
    description: str
    severity: FaultSeverity
    latching: bool


FAULT_REGISTRY: dict[FaultId, FaultDefinition] = {
    FaultId.THROTTLE_OUT_OF_RANGE: FaultDefinition(
        FaultId.THROTTLE_OUT_OF_RANGE,
        "Throttle ADC out of calibrated range",
        FaultSeverity.FAULT,
        False,
    ),
    FaultId.THROTTLE_IMPLAUSIBLE: FaultDefinition(
        FaultId.THROTTLE_IMPLAUSIBLE,
        "Throttle signal changed faster than physically possible",
        FaultSeverity.FAULT,
        False,
    ),
    FaultId.BRAKE_SENSOR_FAULT: FaultDefinition(
        FaultId.BRAKE_SENSOR_FAULT,
        "Brake ADC out of calibrated range",
        FaultSeverity.FAULT,
        False,
    ),
    FaultId.THROTTLE_BRAKE_SIMULTANEOUS: FaultDefinition(
        FaultId.THROTTLE_BRAKE_SIMULTANEOUS,
        "Throttle and brake pressed simultaneously",
        FaultSeverity.FAULT,
        False,
    ),
    FaultId.WHEEL_SPEED_FAULT: FaultDefinition(
        FaultId.WHEEL_SPEED_FAULT,
        "Wheel-speed sensor invalid or missing",
        FaultSeverity.FAULT,
        False,
    ),
    FaultId.SENSOR_DISAGREEMENT: FaultDefinition(
        FaultId.SENSOR_DISAGREEMENT,
        "Wheel speed and motor RPM imply inconsistent vehicle speed",
        FaultSeverity.FAULT,
        False,
    ),
    FaultId.CAN_TIMEOUT: FaultDefinition(
        FaultId.CAN_TIMEOUT,
        "CAN bus timeout — VESC or BMS not responding",
        FaultSeverity.FAULT,
        False,
    ),
    FaultId.VESC_FAULT: FaultDefinition(
        FaultId.VESC_FAULT,
        "Motor controller reported a fault code",
        FaultSeverity.FAULT,
        False,
    ),
    FaultId.BMS_FAULT: FaultDefinition(
        FaultId.BMS_FAULT,
        "BMS reported a fault code",
        FaultSeverity.FAULT,
        False,
    ),
    FaultId.PACK_OVERVOLTAGE: FaultDefinition(
        FaultId.PACK_OVERVOLTAGE,
        "Pack voltage above maximum safe limit",
        FaultSeverity.CRITICAL,
        True,
    ),
    FaultId.PACK_UNDERVOLTAGE: FaultDefinition(
        FaultId.PACK_UNDERVOLTAGE,
        "Pack voltage below minimum safe limit",
        FaultSeverity.CRITICAL,
        True,
    ),
    FaultId.CELL_OVERVOLTAGE: FaultDefinition(
        FaultId.CELL_OVERVOLTAGE,
        "Cell voltage above maximum safe limit",
        FaultSeverity.CRITICAL,
        True,
    ),
    FaultId.CELL_UNDERVOLTAGE: FaultDefinition(
        FaultId.CELL_UNDERVOLTAGE,
        "Cell voltage below minimum safe limit",
        FaultSeverity.CRITICAL,
        True,
    ),
    FaultId.MOTOR_OVERTEMP_DERATE: FaultDefinition(
        FaultId.MOTOR_OVERTEMP_DERATE,
        "Motor temperature high — power derated",
        FaultSeverity.DERATE,
        False,
    ),
    FaultId.MOTOR_OVERTEMP: FaultDefinition(
        FaultId.MOTOR_OVERTEMP,
        "Motor temperature above fault threshold",
        FaultSeverity.FAULT,
        False,
    ),
    FaultId.CONTROLLER_OVERTEMP_DERATE: FaultDefinition(
        FaultId.CONTROLLER_OVERTEMP_DERATE,
        "Controller temperature high — power derated",
        FaultSeverity.DERATE,
        False,
    ),
    FaultId.CONTROLLER_OVERTEMP: FaultDefinition(
        FaultId.CONTROLLER_OVERTEMP,
        "Controller temperature above fault threshold",
        FaultSeverity.FAULT,
        False,
    ),
    FaultId.BATTERY_OVERTEMP_DERATE: FaultDefinition(
        FaultId.BATTERY_OVERTEMP_DERATE,
        "Battery temperature high — power derated",
        FaultSeverity.DERATE,
        False,
    ),
    FaultId.BATTERY_OVERTEMP: FaultDefinition(
        FaultId.BATTERY_OVERTEMP,
        "Battery temperature above fault threshold",
        FaultSeverity.CRITICAL,
        True,
    ),
    FaultId.OVERSPEED: FaultDefinition(
        FaultId.OVERSPEED,
        "Vehicle speed above configured maximum",
        FaultSeverity.FAULT,
        False,
    ),
    FaultId.WATCHDOG_RESET: FaultDefinition(
        FaultId.WATCHDOG_RESET,
        "MCU watchdog reset detected on boot",
        FaultSeverity.FAULT,
        True,
    ),
    FaultId.CONTACTOR_FEEDBACK_MISMATCH: FaultDefinition(
        FaultId.CONTACTOR_FEEDBACK_MISMATCH,
        "Contactor feedback does not match commanded state",
        FaultSeverity.CRITICAL,
        True,
    ),
    FaultId.PRECHARGE_FAILURE: FaultDefinition(
        FaultId.PRECHARGE_FAILURE,
        "Precharge sequence failed or timed out",
        FaultSeverity.CRITICAL,
        True,
    ),
}


@dataclass(frozen=True)
class SafetyConfig:
    throttle_adc_min: int = 100
    throttle_adc_max: int = 3900
    brake_adc_min: int = 100
    brake_adc_max: int = 3900
    throttle_brake_simultaneous_threshold: float = 0.15
    pack_voltage_max_v: float = 60.0
    pack_voltage_min_v: float = 40.0
    cell_voltage_max_v: float = 3.65
    cell_voltage_min_v: float = 2.8
    motor_temp_derate_c: float = 100.0
    motor_temp_fault_c: float = 120.0
    controller_temp_derate_c: float = 75.0
    controller_temp_fault_c: float = 85.0
    battery_temp_derate_c: float = 50.0
    battery_temp_fault_c: float = 60.0
    max_speed_mps: float = 20.0
    overspeed_margin_mps: float = 0.5
    overspeed_confirm_s: float = 0.35
    can_timeout_s: float = 0.5
    precharge_timeout_s: float = 2.0
    self_test_duration_s: float = 0.5
    throttle_drive_deadband: float = 0.05
    wheel_speed_disagreement_ratio: float = 0.25
    mode_change_max_speed_mps: float = 0.0
    derate_factor: float = 0.5
    ice_powertrain: bool = False


@dataclass
class SensorInputs:
    throttle_adc: int = 0
    brake_adc: int = 0
    throttle: float = 0.0
    brake: float = 0.0
    speed_mps: float = 0.0
    motor_rpm: float = 0.0
    implied_speed_mps: float = 0.0
    pack_voltage_v: float = 48.0
    min_cell_voltage_v: float = 3.2
    max_cell_voltage_v: float = 3.3
    motor_temp_c: float = 25.0
    controller_temp_c: float = 25.0
    battery_temp_c: float = 25.0
    wheel_speed_valid: bool = True
    can_vesc_alive: bool = True
    can_bms_alive: bool = True
    can_silence_s: float = 0.0
    vesc_fault_active: bool = False
    bms_fault_active: bool = False
    contactor_feedback_closed: bool = False
    precharge_feedback_ok: bool = True
    watchdog_reset_detected: bool = False


@dataclass
class DetectionState:
    previous_throttle_adc: int = 0
    overspeed_elapsed_s: float = 0.0


def detect_faults(
    inputs: SensorInputs,
    config: SafetyConfig,
    *,
    detection_state: DetectionState | None = None,
    dt: float = 0.01,
) -> set[FaultId]:
    """Pure fault detection from sensor and bus signals."""
    active: set[FaultId] = set()

    if (
        inputs.throttle_adc < config.throttle_adc_min
        or inputs.throttle_adc > config.throttle_adc_max
    ):
        active.add(FaultId.THROTTLE_OUT_OF_RANGE)
    if inputs.brake_adc < config.brake_adc_min or inputs.brake_adc > config.brake_adc_max:
        active.add(FaultId.BRAKE_SENSOR_FAULT)

    if detection_state is not None:
        adc_delta = abs(inputs.throttle_adc - detection_state.previous_throttle_adc)
        if adc_delta > 800:
            active.add(FaultId.THROTTLE_IMPLAUSIBLE)

    if (
        inputs.throttle > config.throttle_brake_simultaneous_threshold
        and inputs.brake > config.throttle_brake_simultaneous_threshold
    ):
        active.add(FaultId.THROTTLE_BRAKE_SIMULTANEOUS)

    if not inputs.wheel_speed_valid:
        active.add(FaultId.WHEEL_SPEED_FAULT)

    if not config.ice_powertrain:
        if inputs.speed_mps > 1.0 and inputs.implied_speed_mps > 0.1:
            ratio = abs(inputs.speed_mps - inputs.implied_speed_mps) / max(inputs.speed_mps, 0.1)
            if ratio > config.wheel_speed_disagreement_ratio:
                active.add(FaultId.SENSOR_DISAGREEMENT)

        can_dead = (
            inputs.can_silence_s >= config.can_timeout_s
            or not inputs.can_vesc_alive
            or not inputs.can_bms_alive
        )
        if can_dead:
            active.add(FaultId.CAN_TIMEOUT)
        if inputs.vesc_fault_active:
            active.add(FaultId.VESC_FAULT)
        if inputs.bms_fault_active:
            active.add(FaultId.BMS_FAULT)

        if inputs.pack_voltage_v > config.pack_voltage_max_v:
            active.add(FaultId.PACK_OVERVOLTAGE)
        if inputs.pack_voltage_v < config.pack_voltage_min_v:
            active.add(FaultId.PACK_UNDERVOLTAGE)
        if inputs.max_cell_voltage_v > config.cell_voltage_max_v:
            active.add(FaultId.CELL_OVERVOLTAGE)
        if inputs.min_cell_voltage_v < config.cell_voltage_min_v:
            active.add(FaultId.CELL_UNDERVOLTAGE)

        if inputs.battery_temp_c >= config.battery_temp_fault_c:
            active.add(FaultId.BATTERY_OVERTEMP)
        elif inputs.battery_temp_c >= config.battery_temp_derate_c:
            active.add(FaultId.BATTERY_OVERTEMP_DERATE)

    if inputs.motor_temp_c >= config.motor_temp_fault_c:
        active.add(FaultId.MOTOR_OVERTEMP)
    elif inputs.motor_temp_c >= config.motor_temp_derate_c:
        active.add(FaultId.MOTOR_OVERTEMP_DERATE)

    if inputs.controller_temp_c >= config.controller_temp_fault_c:
        active.add(FaultId.CONTROLLER_OVERTEMP)
    elif inputs.controller_temp_c >= config.controller_temp_derate_c:
        active.add(FaultId.CONTROLLER_OVERTEMP_DERATE)

    if not config.ice_powertrain:
        if inputs.battery_temp_c >= config.battery_temp_fault_c:
            active.add(FaultId.BATTERY_OVERTEMP)
        elif inputs.battery_temp_c >= config.battery_temp_derate_c:
            active.add(FaultId.BATTERY_OVERTEMP_DERATE)

    over_limit = inputs.speed_mps > config.max_speed_mps + config.overspeed_margin_mps
    if detection_state is not None:
        if over_limit:
            detection_state.overspeed_elapsed_s += max(0.0, dt)
        else:
            detection_state.overspeed_elapsed_s = 0.0
        if detection_state.overspeed_elapsed_s >= config.overspeed_confirm_s:
            active.add(FaultId.OVERSPEED)
    elif over_limit:
        active.add(FaultId.OVERSPEED)

    if inputs.watchdog_reset_detected:
        active.add(FaultId.WATCHDOG_RESET)

    return active


def highest_severity(faults: set[FaultId]) -> FaultSeverity | None:
    order = (
        FaultSeverity.CRITICAL,
        FaultSeverity.FAULT,
        FaultSeverity.DERATE,
        FaultSeverity.WARNING,
    )
    severities = {FAULT_REGISTRY[fid].severity for fid in faults if fid in FAULT_REGISTRY}
    for severity in order:
        if severity in severities:
            return severity
    return None


def derating_from_faults(faults: set[FaultId], config: SafetyConfig) -> DeratingFactors:
    factor = (
        config.derate_factor
        if any(
            FAULT_REGISTRY[f].severity == FaultSeverity.DERATE
            for f in faults
            if f in FAULT_REGISTRY
        )
        else 1.0
    )
    return DeratingFactors(
        speed=factor,
        motor_current=factor,
        battery_current=factor,
        regen_current=factor,
        power=factor,
        motor_rpm=factor,
        accel=factor,
        decel=factor,
        gradient=factor,
    )


def merge_fault_sets(*fault_sets: set[FaultId]) -> set[FaultId]:
    merged: set[FaultId] = set()
    for faults in fault_sets:
        merged |= faults
    return merged
