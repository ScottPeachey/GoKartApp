#include "gk_safety.h"

#include "gk_faults.h"

static gk_safety_outputs_t make_outputs(
    gk_safety_state_t state,
    uint32_t faults,
    const gk_safety_config_t *config,
    gk_contactor_command_t contactor,
    bool torque,
    bool regen,
    int message
) {
    gk_safety_outputs_t out;
    out.torque_permitted = torque;
    out.regen_permitted = regen;
    out.contactor_command = contactor;
    out.derating = gk_derating_from_faults(faults, config);
    out.active_faults = faults;
    out.display_message_code = message;
    out.safety_state = state;
    return out;
}

static void latch_critical(uint32_t faults, uint32_t *latched) {
    for (int i = 0; i < GK_FAULT_COUNT; ++i) {
        if ((faults & (1u << i)) && gk_fault_is_latching((gk_fault_id_t)i) &&
            gk_fault_is_critical((gk_fault_id_t)i)) {
            *latched |= (1u << i);
        }
    }
}

void gk_safety_step(
    gk_safety_state_t state,
    const gk_safety_inputs_t *inputs,
    const gk_safety_config_t *config,
    gk_safety_timers_t *timers,
    uint32_t latched_faults_in,
    float dt,
    gk_safety_state_t *next_state,
    gk_safety_outputs_t *outputs,
    uint32_t *latched_faults_out
) {
    uint32_t latched = latched_faults_in;
    timers->state_elapsed_s += dt;

    uint32_t active_faults = gk_merge_faults(inputs->detected_faults, latched);
    if (inputs->power_cycle_event) {
        latched = 0;
        active_faults = inputs->detected_faults;
    }

    bool critical = gk_has_critical_fault(active_faults);
    bool blocking = gk_has_blocking_fault(active_faults);

    switch (state) {
    case GK_SAFETY_OFF:
        if (inputs->power_on_request) {
            state = GK_SAFETY_BOOT;
            timers->state_elapsed_s = 0.0f;
        }
        *outputs = make_outputs(
            state, active_faults, config, GK_CONTACTOR_OPEN, false, false, 0
        );
        break;

    case GK_SAFETY_BOOT:
        if (active_faults & (1u << GK_FAULT_WATCHDOG_RESET)) {
            latched |= (1u << GK_FAULT_WATCHDOG_RESET);
            state = GK_SAFETY_FAULT;
        } else if (timers->state_elapsed_s >= dt) {
            state = GK_SAFETY_SELF_TEST;
            timers->state_elapsed_s = 0.0f;
        }
        *outputs = make_outputs(
            state, active_faults, config, GK_CONTACTOR_OPEN, false, false, 0
        );
        break;

    case GK_SAFETY_SELF_TEST:
        if (critical || blocking) {
            state = GK_SAFETY_FAULT;
        } else if (timers->state_elapsed_s >= config->self_test_duration_s) {
            state = GK_SAFETY_READY;
            timers->state_elapsed_s = 0.0f;
        }
        *outputs = make_outputs(
            state, active_faults, config, GK_CONTACTOR_OPEN, false, false, 0
        );
        break;

    case GK_SAFETY_READY:
        if (critical) {
            latch_critical(active_faults, &latched);
            state = GK_SAFETY_SAFE_SHUTDOWN;
            timers->shutdown_elapsed_s = 0.0f;
        } else if (blocking) {
            state = GK_SAFETY_FAULT;
        } else if (inputs->arm_request && inputs->driver_authenticated && inputs->brake_pressed) {
            timers->precharge_elapsed_s = 0.0f;
            state = GK_SAFETY_ARMED;
            timers->state_elapsed_s = 0.0f;
        }
        *outputs = make_outputs(
            state, active_faults, config, GK_CONTACTOR_OPEN, false, false, 0
        );
        break;

    case GK_SAFETY_ARMED:
        if (critical) {
            latch_critical(active_faults, &latched);
            state = GK_SAFETY_SAFE_SHUTDOWN;
            timers->shutdown_elapsed_s = 0.0f;
            *outputs = make_outputs(
                state, active_faults, config, GK_CONTACTOR_OPEN, false, false, 0
            );
            break;
        }
        if (blocking) {
            state = GK_SAFETY_FAULT;
            *outputs = make_outputs(
                state, active_faults, config, GK_CONTACTOR_OPEN, false, false, 0
            );
            break;
        }

        timers->precharge_elapsed_s += dt;
        if (timers->precharge_elapsed_s < config->precharge_timeout_s) {
            if (!inputs->precharge_feedback_ok) {
                active_faults |= (1u << GK_FAULT_PRECHARGE_FAILURE);
                latched |= (1u << GK_FAULT_PRECHARGE_FAILURE);
                state = GK_SAFETY_SAFE_SHUTDOWN;
                timers->shutdown_elapsed_s = 0.0f;
                *outputs = make_outputs(
                    state, active_faults, config, GK_CONTACTOR_OPEN, false, false, 0
                );
                break;
            }
            *outputs = make_outputs(
                state, active_faults, config, GK_CONTACTOR_PRECHARGE, false, false, 0
            );
        } else {
            if (
                inputs->throttle > config->throttle_drive_deadband && !inputs->brake_pressed
            ) {
                state = GK_SAFETY_DRIVING;
                timers->state_elapsed_s = 0.0f;
            }
            *outputs = make_outputs(
                state, active_faults, config, GK_CONTACTOR_CLOSE, false, false, 0
            );
        }
        break;

    case GK_SAFETY_DRIVING:
        if (critical) {
            latch_critical(active_faults, &latched);
            state = GK_SAFETY_SAFE_SHUTDOWN;
            timers->shutdown_elapsed_s = 0.0f;
            *outputs = make_outputs(
                state, active_faults, config, GK_CONTACTOR_OPEN, false, false, 0
            );
            break;
        }
        if (blocking) {
            state = GK_SAFETY_FAULT;
            *outputs = make_outputs(
                state, active_faults, config, GK_CONTACTOR_OPEN, false, false, 0
            );
            break;
        }
        if (inputs->disarm_request || inputs->brake_pressed) {
            state = GK_SAFETY_READY;
            timers->state_elapsed_s = 0.0f;
            *outputs = make_outputs(
                state, active_faults, config, GK_CONTACTOR_OPEN, false, false, 0
            );
            break;
        }
        *outputs = make_outputs(
            state, active_faults, config, GK_CONTACTOR_CLOSE, true, true, 0
        );
        break;

    case GK_SAFETY_FAULT:
        if (critical) {
            latch_critical(active_faults, &latched);
            state = GK_SAFETY_SAFE_SHUTDOWN;
            timers->shutdown_elapsed_s = 0.0f;
        } else if (!blocking && inputs->fault_ack_request) {
            state = GK_SAFETY_READY;
            timers->state_elapsed_s = 0.0f;
        }
        *outputs = make_outputs(
            state, active_faults, config, GK_CONTACTOR_OPEN, false, false, 1
        );
        break;

    case GK_SAFETY_SAFE_SHUTDOWN:
        timers->shutdown_elapsed_s += dt;
        if (timers->shutdown_elapsed_s >= 0.5f) {
            state = GK_SAFETY_OFF;
        }
        *outputs = make_outputs(
            state, active_faults, config, GK_CONTACTOR_OPEN, false, false, 2
        );
        break;

    default:
        *outputs = make_outputs(
            state, active_faults, config, GK_CONTACTOR_OPEN, false, false, 0
        );
        break;
    }

    *next_state = state;
    *latched_faults_out = latched;
}
