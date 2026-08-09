#include "gk_faults.h"

#include <stdbool.h>
#include <stddef.h>

static bool fault_is_derate(gk_fault_id_t fault) {
    return fault == GK_FAULT_MOTOR_OVERTEMP_DERATE ||
           fault == GK_FAULT_CONTROLLER_OVERTEMP_DERATE ||
           fault == GK_FAULT_BATTERY_OVERTEMP_DERATE;
}

static bool fault_is_blocking(gk_fault_id_t fault) {
    switch (fault) {
    case GK_FAULT_MOTOR_OVERTEMP_DERATE:
    case GK_FAULT_CONTROLLER_OVERTEMP_DERATE:
    case GK_FAULT_BATTERY_OVERTEMP_DERATE:
        return false;
    default:
        return true;
    }
}

static bool fault_is_critical(gk_fault_id_t fault) {
    switch (fault) {
    case GK_FAULT_PACK_OVERVOLTAGE:
    case GK_FAULT_PACK_UNDERVOLTAGE:
    case GK_FAULT_CELL_OVERVOLTAGE:
    case GK_FAULT_CELL_UNDERVOLTAGE:
    case GK_FAULT_BATTERY_OVERTEMP:
    case GK_FAULT_CONTACTOR_FEEDBACK_MISMATCH:
    case GK_FAULT_PRECHARGE_FAILURE:
        return true;
    default:
        return false;
    }
}

uint32_t gk_merge_faults(uint32_t a, uint32_t b) { return a | b; }

uint32_t gk_detect_faults(
    const gk_sensor_inputs_t *inputs,
    const gk_safety_config_t *config,
    gk_detection_state_t *detection_state
) {
    uint32_t active = 0;

    if (
        inputs->throttle_adc < config->throttle_adc_min ||
        inputs->throttle_adc > config->throttle_adc_max
    ) {
        active |= (1u << GK_FAULT_THROTTLE_OUT_OF_RANGE);
    }
    if (inputs->brake_adc < config->brake_adc_min || inputs->brake_adc > config->brake_adc_max) {
        active |= (1u << GK_FAULT_BRAKE_SENSOR_FAULT);
    }

    if (detection_state != NULL) {
        int adc_delta = inputs->throttle_adc - detection_state->previous_throttle_adc;
        if (adc_delta < 0) {
            adc_delta = -adc_delta;
        }
        if (adc_delta > 800) {
            active |= (1u << GK_FAULT_THROTTLE_IMPLAUSIBLE);
        }
        detection_state->previous_throttle_adc = inputs->throttle_adc;
    }

    if (
        inputs->throttle > config->throttle_brake_simultaneous_threshold &&
        inputs->brake > config->throttle_brake_simultaneous_threshold
    ) {
        active |= (1u << GK_FAULT_THROTTLE_BRAKE_SIMULTANEOUS);
    }

    if (!inputs->wheel_speed_valid) {
        active |= (1u << GK_FAULT_WHEEL_SPEED_FAULT);
    }

    if (inputs->speed_mps > 1.0f && inputs->implied_speed_mps > 0.1f) {
        float denom = inputs->speed_mps;
        if (denom < 0.1f) {
            denom = 0.1f;
        }
        float ratio = inputs->speed_mps - inputs->implied_speed_mps;
        if (ratio < 0.0f) {
            ratio = -ratio;
        }
        ratio /= denom;
        if (ratio > config->wheel_speed_disagreement_ratio) {
            active |= (1u << GK_FAULT_SENSOR_DISAGREEMENT);
        }
    }

    bool can_dead =
        inputs->can_silence_s >= config->can_timeout_s || !inputs->can_vesc_alive ||
        !inputs->can_bms_alive;
    if (can_dead) {
        active |= (1u << GK_FAULT_CAN_TIMEOUT);
    }
    if (inputs->vesc_fault_active) {
        active |= (1u << GK_FAULT_VESC_FAULT);
    }
    if (inputs->bms_fault_active) {
        active |= (1u << GK_FAULT_BMS_FAULT);
    }

    if (inputs->pack_voltage_v > config->pack_voltage_max_v) {
        active |= (1u << GK_FAULT_PACK_OVERVOLTAGE);
    }
    if (inputs->pack_voltage_v < config->pack_voltage_min_v) {
        active |= (1u << GK_FAULT_PACK_UNDERVOLTAGE);
    }
    if (inputs->max_cell_voltage_v > config->cell_voltage_max_v) {
        active |= (1u << GK_FAULT_CELL_OVERVOLTAGE);
    }
    if (inputs->min_cell_voltage_v < config->cell_voltage_min_v) {
        active |= (1u << GK_FAULT_CELL_UNDERVOLTAGE);
    }

    if (inputs->motor_temp_c >= config->motor_temp_fault_c) {
        active |= (1u << GK_FAULT_MOTOR_OVERTEMP);
    } else if (inputs->motor_temp_c >= config->motor_temp_derate_c) {
        active |= (1u << GK_FAULT_MOTOR_OVERTEMP_DERATE);
    }

    if (inputs->controller_temp_c >= config->controller_temp_fault_c) {
        active |= (1u << GK_FAULT_CONTROLLER_OVERTEMP);
    } else if (inputs->controller_temp_c >= config->controller_temp_derate_c) {
        active |= (1u << GK_FAULT_CONTROLLER_OVERTEMP_DERATE);
    }

    if (inputs->battery_temp_c >= config->battery_temp_fault_c) {
        active |= (1u << GK_FAULT_BATTERY_OVERTEMP);
    } else if (inputs->battery_temp_c >= config->battery_temp_derate_c) {
        active |= (1u << GK_FAULT_BATTERY_OVERTEMP_DERATE);
    }

    if (inputs->speed_mps > config->max_speed_mps) {
        active |= (1u << GK_FAULT_OVERSPEED);
    }

    if (inputs->watchdog_reset_detected) {
        active |= (1u << GK_FAULT_WATCHDOG_RESET);
    }

    return active;
}

gk_derating_factors_t gk_derating_from_faults(uint32_t faults, const gk_safety_config_t *config) {
    bool derate = false;
    for (int i = 0; i < GK_FAULT_COUNT; ++i) {
        if ((faults & (1u << i)) && fault_is_derate((gk_fault_id_t)i)) {
            derate = true;
            break;
        }
    }
    float factor = derate ? config->derate_factor : 1.0f;
    gk_derating_factors_t out = {
        factor, factor, factor, factor, factor, factor, factor, factor, factor,
    };
    return out;
}

bool gk_fault_is_blocking(gk_fault_id_t fault) { return fault_is_blocking(fault); }

bool gk_fault_is_critical(gk_fault_id_t fault) { return fault_is_critical(fault); }

bool gk_has_blocking_fault(uint32_t faults) {
    for (int i = 0; i < GK_FAULT_COUNT; ++i) {
        if ((faults & (1u << i)) && fault_is_blocking((gk_fault_id_t)i)) {
            return true;
        }
    }
    return false;
}

bool gk_has_critical_fault(uint32_t faults) {
    for (int i = 0; i < GK_FAULT_COUNT; ++i) {
        if ((faults & (1u << i)) && fault_is_critical((gk_fault_id_t)i)) {
            return true;
        }
    }
    return false;
}

bool gk_fault_is_latching(gk_fault_id_t fault) {
    switch (fault) {
    case GK_FAULT_PACK_OVERVOLTAGE:
    case GK_FAULT_PACK_UNDERVOLTAGE:
    case GK_FAULT_CELL_OVERVOLTAGE:
    case GK_FAULT_CELL_UNDERVOLTAGE:
    case GK_FAULT_BATTERY_OVERTEMP:
    case GK_FAULT_WATCHDOG_RESET:
    case GK_FAULT_CONTACTOR_FEEDBACK_MISMATCH:
    case GK_FAULT_PRECHARGE_FAILURE:
        return true;
    default:
        return false;
    }
}
