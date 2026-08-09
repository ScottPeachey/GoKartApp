#include "gk_control.h"

#include <math.h>
#include <string.h>

static float clamp01(float value) {
    if (value < 0.0f) {
        return 0.0f;
    }
    if (value > 1.0f) {
        return 1.0f;
    }
    return value;
}

static float apply_throttle_curve(float throttle, const char *curve) {
    float t = clamp01(throttle);
    if (curve != NULL && strcmp(curve, "progressive") == 0) {
        return t * t;
    }
    if (curve != NULL && strcmp(curve, "aggressive") == 0) {
        return sqrtf(t);
    }
    return t;
}

static float traction_threshold(const char *policy) {
    if (policy != NULL && strcmp(policy, "off") == 0) {
        return 0.0f;
    }
    if (policy != NULL && strcmp(policy, "gentle") == 0) {
        return 0.85f;
    }
    if (policy != NULL && strcmp(policy, "moderate") == 0) {
        return 0.92f;
    }
    if (policy != NULL && strcmp(policy, "aggressive") == 0) {
        return 0.98f;
    }
    return 0.92f;
}

static float rpm_to_rads(float rpm) { return rpm * 0.104719755f; }

static float max_traction_force_n(float mass_kg, float grip, float gradient_rad) {
    return mass_kg * GK_GRAVITY_MPS2 * cosf(gradient_rad) * grip;
}

static float estimate_motor_current(
    float torque_nm,
    float motor_rpm,
    float voltage_v,
    float efficiency
) {
    float omega = rpm_to_rads(motor_rpm < 1.0f ? 1.0f : motor_rpm);
    float mechanical = fabsf(torque_nm) * omega;
    float eff = efficiency < 0.05f ? 0.05f : efficiency;
    float electrical = mechanical / eff;
    if (voltage_v <= 1.0f) {
        return 0.0f;
    }
    return electrical / voltage_v;
}

void gk_control_step(
    const gk_control_inputs_t *inputs,
    const gk_effective_limits_t *limits,
    const gk_safety_outputs_t *safety,
    gk_control_state_t *state,
    const gk_control_params_t *params,
    float dt,
    gk_control_outputs_t *outputs
) {
    float throttle = clamp01(inputs->throttle);
    float brake = clamp01(inputs->brake);
    float filtered = state->filtered_throttle;

    if (!params->mode.throttle_ramp_enabled) {
        filtered = throttle;
    } else {
        float delta = params->mode.throttle_ramp_per_s * dt;
        float throttle_delta = throttle - state->filtered_throttle;
        if (throttle_delta > delta) {
            throttle_delta = delta;
        }
        if (throttle_delta < -delta) {
            throttle_delta = -delta;
        }
        filtered = state->filtered_throttle + throttle_delta;
    }

    if (!safety->torque_permitted) {
        outputs->motor_torque_request_nm = 0.0f;
        outputs->regen_torque_request_nm = 0.0f;
        outputs->mechanical_brake = brake;
        outputs->filtered_throttle = filtered;
        outputs->traction_limited = false;
        state->filtered_throttle = filtered;
        state->traction_scale = 1.0f;
        return;
    }

    float shaped = apply_throttle_curve(filtered, params->mode.throttle_curve);
    float motor_torque = shaped * params->motor_peak_torque_nm;
    bool traction_limited = false;
    float traction_scale = 1.0f;

    if (
        params->mode.traction_limiter != NULL &&
        strcmp(params->mode.traction_limiter, "off") != 0 && inputs->speed_mps >= 0.0f
    ) {
        float wheel_torque =
            motor_torque * params->gear_ratio * params->drivetrain_efficiency;
        float force_req =
            params->wheel_radius_m > 0.0f ? wheel_torque / params->wheel_radius_m : 0.0f;
        float force_avail = max_traction_force_n(
            inputs->mass_kg, inputs->grip_coefficient, inputs->gradient_rad
        );
        float threshold = traction_threshold(params->mode.traction_limiter);
        if (force_avail > 0.0f && force_req > force_avail * threshold) {
            traction_scale = (force_avail * threshold) / force_req;
            motor_torque *= traction_scale;
            traction_limited = true;
        }
    }

    if (inputs->speed_mps > 0.0f && limits->max_speed_mps > 0.0f) {
        float taper_start = limits->max_speed_mps * 0.9f;
        if (inputs->speed_mps > taper_start) {
            float span = limits->max_speed_mps - taper_start;
            if (span > 0.0f) {
                float taper = (limits->max_speed_mps - inputs->speed_mps) / span;
                if (taper < 0.0f) {
                    taper = 0.0f;
                }
                motor_torque *= taper;
            }
        }
    }

    if (motor_torque > params->motor_peak_torque_nm) {
        motor_torque = params->motor_peak_torque_nm;
    }

    if (limits->max_power_w > 0.0f && inputs->pack_voltage_v > 1.0f) {
        float omega = rpm_to_rads(inputs->motor_rpm < 1.0f ? 1.0f : inputs->motor_rpm);
        if (omega > 0.0f) {
            float power_limited_torque = limits->max_power_w / omega;
            if (motor_torque > power_limited_torque) {
                motor_torque = power_limited_torque;
            }
        }
    }

    float est_current = estimate_motor_current(
        motor_torque, inputs->motor_rpm, inputs->pack_voltage_v, params->motor_efficiency
    );
    if (limits->max_motor_current_a > 0.0f && est_current > limits->max_motor_current_a) {
        motor_torque *= limits->max_motor_current_a / est_current;
    }

    float regen_torque = 0.0f;
    if (safety->regen_permitted && brake > 0.0f) {
        regen_torque = brake * params->motor_peak_torque_nm * params->mode.regen_strength;
        if (limits->max_regen_current_a > 0.0f && inputs->pack_voltage_v > 1.0f) {
            float omega = rpm_to_rads(inputs->motor_rpm < 1.0f ? 1.0f : inputs->motor_rpm);
            if (omega > 0.0f) {
                float max_regen_torque =
                    limits->max_regen_current_a * inputs->pack_voltage_v *
                    params->motor_efficiency / omega;
                if (regen_torque > max_regen_torque) {
                    regen_torque = max_regen_torque;
                }
            }
        }
        motor_torque -= regen_torque;
    }

    outputs->motor_torque_request_nm = motor_torque;
    outputs->regen_torque_request_nm = regen_torque;
    outputs->mechanical_brake = brake;
    outputs->filtered_throttle = filtered;
    outputs->traction_limited = traction_limited;
    state->filtered_throttle = filtered;
    state->traction_scale = traction_scale;
}
