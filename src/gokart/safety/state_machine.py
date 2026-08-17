"""Safety state machine — pure transition function."""

from __future__ import annotations

from dataclasses import dataclass, field

from gokart.limits.resolver import DeratingFactors
from gokart.safety.faults import (
    FAULT_REGISTRY,
    SafetyConfig,
    derating_from_faults,
    highest_severity,
    merge_fault_sets,
)
from gokart.safety.types import ContactorCommand, FaultId, FaultSeverity, SafetyState


@dataclass(frozen=True)
class SafetyOutputs:
    torque_permitted: bool
    regen_permitted: bool
    contactor_command: ContactorCommand
    derating: DeratingFactors
    active_faults: tuple[FaultId, ...]
    display_message_code: int
    safety_state: SafetyState


@dataclass
class SafetyInputs:
    power_on_request: bool = False
    arm_request: bool = False
    disarm_request: bool = False
    fault_ack_request: bool = False
    power_cycle_event: bool = False
    driver_authenticated: bool = True
    brake_pressed: bool = False
    throttle: float = 0.0
    autonomous_drive: bool = False
    detected_faults: set[FaultId] = field(default_factory=set)
    precharge_feedback_ok: bool = True
    contactor_feedback_closed: bool = False
    contactor_feedback_open: bool = True


@dataclass
class SafetyTimers:
    state_elapsed_s: float = 0.0
    precharge_elapsed_s: float = 0.0
    shutdown_elapsed_s: float = 0.0


def _blocking_faults(faults: set[FaultId]) -> set[FaultId]:
    return {
        fault
        for fault in faults
        if FAULT_REGISTRY[fault].severity in {FaultSeverity.FAULT, FaultSeverity.CRITICAL}
    }


def _critical_faults(faults: set[FaultId]) -> set[FaultId]:
    return {fault for fault in faults if FAULT_REGISTRY[fault].severity == FaultSeverity.CRITICAL}


def _latch_blocking_faults(faults: set[FaultId], latched: set[FaultId]) -> None:
    """Keep recoverable blocking faults visible until the operator acknowledges."""
    latched |= _blocking_faults(faults)


def _outputs_for_state(
    state: SafetyState,
    faults: set[FaultId],
    config: SafetyConfig,
    *,
    contactor: ContactorCommand,
    torque: bool,
    regen: bool,
    message: int = 0,
) -> SafetyOutputs:
    return SafetyOutputs(
        torque_permitted=torque,
        regen_permitted=regen,
        contactor_command=contactor,
        derating=derating_from_faults(faults, config),
        active_faults=tuple(sorted(faults, key=lambda f: f.value)),
        display_message_code=message,
        safety_state=state,
    )


def safety_step(
    state: SafetyState,
    inputs: SafetyInputs,
    config: SafetyConfig,
    timers: SafetyTimers,
    *,
    latched_faults: set[FaultId] | None = None,
    dt: float = 0.01,
) -> tuple[SafetyState, SafetyOutputs, SafetyTimers, set[FaultId]]:
    """Advance the safety state machine by one control tick."""
    latched = set(latched_faults or ())
    timers = SafetyTimers(
        state_elapsed_s=timers.state_elapsed_s + dt,
        precharge_elapsed_s=timers.precharge_elapsed_s,
        shutdown_elapsed_s=timers.shutdown_elapsed_s,
    )
    active_faults = merge_fault_sets(inputs.detected_faults, latched)
    critical = _critical_faults(active_faults)
    blocking = _blocking_faults(active_faults)

    if inputs.power_cycle_event:
        latched.clear()
        active_faults = set(inputs.detected_faults)

    if state == SafetyState.OFF:
        if inputs.power_on_request:
            state = SafetyState.BOOT
            timers.state_elapsed_s = 0.0
        return (
            state,
            _outputs_for_state(
                state,
                active_faults,
                config,
                contactor=ContactorCommand.OPEN,
                torque=False,
                regen=False,
            ),
            timers,
            latched,
        )

    if state == SafetyState.BOOT:
        if FaultId.WATCHDOG_RESET in active_faults:
            latched.add(FaultId.WATCHDOG_RESET)
            state = SafetyState.FAULT
        elif timers.state_elapsed_s >= dt:
            state = SafetyState.SELF_TEST
            timers.state_elapsed_s = 0.0
        return (
            state,
            _outputs_for_state(
                state,
                active_faults,
                config,
                contactor=ContactorCommand.OPEN,
                torque=False,
                regen=False,
            ),
            timers,
            latched,
        )

    if state == SafetyState.SELF_TEST:
        if critical or blocking:
            _latch_blocking_faults(inputs.detected_faults, latched)
            active_faults = merge_fault_sets(inputs.detected_faults, latched)
            blocking = _blocking_faults(active_faults)
            critical = _critical_faults(active_faults)
            state = SafetyState.FAULT
        elif timers.state_elapsed_s >= config.self_test_duration_s:
            state = SafetyState.READY
            timers.state_elapsed_s = 0.0
        return (
            state,
            _outputs_for_state(
                state,
                active_faults,
                config,
                contactor=ContactorCommand.OPEN,
                torque=False,
                regen=False,
            ),
            timers,
            latched,
        )

    if state == SafetyState.READY:
        if critical:
            for fault in critical:
                if FAULT_REGISTRY[fault].latching:
                    latched.add(fault)
            state = SafetyState.SAFE_SHUTDOWN
            timers.shutdown_elapsed_s = 0.0
        elif blocking:
            _latch_blocking_faults(inputs.detected_faults, latched)
            active_faults = merge_fault_sets(inputs.detected_faults, latched)
            blocking = _blocking_faults(active_faults)
            state = SafetyState.FAULT
        elif inputs.arm_request and inputs.driver_authenticated and inputs.brake_pressed:
            timers.precharge_elapsed_s = 0.0
            state = SafetyState.ARMED
            timers.state_elapsed_s = 0.0
        return (
            state,
            _outputs_for_state(
                state,
                active_faults,
                config,
                contactor=ContactorCommand.OPEN,
                torque=False,
                regen=False,
            ),
            timers,
            latched,
        )

    if state == SafetyState.ARMED:
        if critical:
            for fault in critical:
                if FAULT_REGISTRY[fault].latching:
                    latched.add(fault)
            state = SafetyState.SAFE_SHUTDOWN
            timers.shutdown_elapsed_s = 0.0
            return (
                state,
                _outputs_for_state(
                    state,
                    active_faults,
                    config,
                    contactor=ContactorCommand.OPEN,
                    torque=False,
                    regen=False,
                ),
                timers,
                latched,
            )

        if blocking:
            _latch_blocking_faults(inputs.detected_faults, latched)
            active_faults = merge_fault_sets(inputs.detected_faults, latched)
            state = SafetyState.FAULT
            return (
                state,
                _outputs_for_state(
                    state,
                    active_faults,
                    config,
                    contactor=ContactorCommand.OPEN,
                    torque=False,
                    regen=False,
                ),
                timers,
                latched,
            )

        timers.precharge_elapsed_s += dt
        if config.ice_powertrain:
            timers.precharge_elapsed_s = config.precharge_timeout_s
        if timers.precharge_elapsed_s < config.precharge_timeout_s:
            if not inputs.precharge_feedback_ok and not config.ice_powertrain:
                active_faults.add(FaultId.PRECHARGE_FAILURE)
                latched.add(FaultId.PRECHARGE_FAILURE)
                state = SafetyState.SAFE_SHUTDOWN
                timers.shutdown_elapsed_s = 0.0
                return (
                    state,
                    _outputs_for_state(
                        state,
                        active_faults,
                        config,
                        contactor=ContactorCommand.OPEN,
                        torque=False,
                        regen=False,
                    ),
                    timers,
                    latched,
                )
            contactor = ContactorCommand.PRECHARGE
        else:
            contactor = ContactorCommand.CLOSE
            if inputs.autonomous_drive or (
                inputs.throttle > config.throttle_drive_deadband and not inputs.brake_pressed
            ):
                state = SafetyState.DRIVING
                timers.state_elapsed_s = 0.0

        return (
            state,
            _outputs_for_state(
                state,
                active_faults,
                config,
                contactor=contactor,
                torque=False,
                regen=False,
            ),
            timers,
            latched,
        )

    if state == SafetyState.DRIVING:
        if critical:
            for fault in critical:
                if FAULT_REGISTRY[fault].latching:
                    latched.add(fault)
            state = SafetyState.SAFE_SHUTDOWN
            timers.shutdown_elapsed_s = 0.0
            return (
                state,
                _outputs_for_state(
                    state,
                    active_faults,
                    config,
                    contactor=ContactorCommand.OPEN,
                    torque=False,
                    regen=False,
                ),
                timers,
                latched,
            )

        if blocking:
            _latch_blocking_faults(inputs.detected_faults, latched)
            active_faults = merge_fault_sets(inputs.detected_faults, latched)
            state = SafetyState.FAULT
            return (
                state,
                _outputs_for_state(
                    state,
                    active_faults,
                    config,
                    contactor=ContactorCommand.OPEN,
                    torque=False,
                    regen=False,
                ),
                timers,
                latched,
            )

        if inputs.disarm_request or inputs.brake_pressed:
            state = SafetyState.READY
            timers.state_elapsed_s = 0.0
            return (
                state,
                _outputs_for_state(
                    state,
                    active_faults,
                    config,
                    contactor=ContactorCommand.OPEN,
                    torque=False,
                    regen=False,
                ),
                timers,
                latched,
            )

        return (
            state,
            _outputs_for_state(
                state,
                active_faults,
                config,
                contactor=ContactorCommand.CLOSE,
                torque=True,
                regen=True,
            ),
            timers,
            latched,
        )

    if state == SafetyState.FAULT:
        _latch_blocking_faults(inputs.detected_faults, latched)
        active_faults = merge_fault_sets(inputs.detected_faults, latched)
        blocking = _blocking_faults(active_faults)
        critical = _critical_faults(active_faults)
        detected_blocking = _blocking_faults(inputs.detected_faults)
        if critical:
            for fault in critical:
                if FAULT_REGISTRY[fault].latching:
                    latched.add(fault)
            state = SafetyState.SAFE_SHUTDOWN
            timers.shutdown_elapsed_s = 0.0
        elif not detected_blocking and inputs.fault_ack_request:
            latched.clear()
            active_faults = merge_fault_sets(inputs.detected_faults, latched)
            state = SafetyState.READY
            timers.state_elapsed_s = 0.0
        return (
            state,
            _outputs_for_state(
                state,
                active_faults,
                config,
                contactor=ContactorCommand.OPEN,
                torque=False,
                regen=False,
                message=1,
            ),
            timers,
            latched,
        )

    if state == SafetyState.SAFE_SHUTDOWN:
        timers.shutdown_elapsed_s += dt
        if (
            inputs.power_cycle_event
            and inputs.fault_ack_request
            and not _critical_faults(inputs.detected_faults)
        ):
            state = SafetyState.OFF
            timers.shutdown_elapsed_s = 0.0
        elif timers.shutdown_elapsed_s >= 0.5:
            state = SafetyState.OFF
        contactor = ContactorCommand.OPEN
        return (
            state,
            _outputs_for_state(
                state,
                active_faults,
                config,
                contactor=contactor,
                torque=False,
                regen=False,
                message=2,
            ),
            timers,
            latched,
        )

    return (
        state,
        _outputs_for_state(
            state, active_faults, config, contactor=ContactorCommand.OPEN, torque=False, regen=False
        ),
        timers,
        latched,
    )


def severity_for_faults(faults: set[FaultId]) -> FaultSeverity | None:
    return highest_severity(faults)
