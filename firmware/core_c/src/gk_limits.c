#include "gk_limits.h"

#include <float.h>

static float min4(float a, float b, float c, float d) {
    float m = a;
    if (b < m) {
        m = b;
    }
    if (c < m) {
        m = c;
    }
    if (d < m) {
        m = d;
    }
    return m;
}

static float apply_derate(float base, float factor) {
    if (factor > 1.0f) {
        factor = 1.0f;
    }
    return base * factor;
}

void gk_resolve_limits(
    const gk_limit_layer_t *hardware,
    const gk_limit_layer_t *vehicle,
    const gk_limit_layer_t *mode,
    const gk_limit_layer_t *profile,
    const gk_derating_factors_t *derating,
    gk_effective_limits_t *out
) {
    const gk_derating_factors_t unit = {
        1.0f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f,
    };
    const gk_derating_factors_t *factors = derating ? derating : &unit;

    out->max_speed_mps = apply_derate(
        min4(
            hardware->max_speed_mps,
            vehicle->max_speed_mps,
            mode->max_speed_mps,
            profile->max_speed_mps
        ),
        factors->speed
    );
    out->max_motor_current_a = apply_derate(
        min4(
            hardware->max_motor_current_a,
            vehicle->max_motor_current_a,
            mode->max_motor_current_a,
            profile->max_motor_current_a
        ),
        factors->motor_current
    );
    out->max_battery_current_a = apply_derate(
        min4(
            hardware->max_battery_current_a,
            vehicle->max_battery_current_a,
            mode->max_battery_current_a,
            profile->max_battery_current_a
        ),
        factors->battery_current
    );
    out->max_regen_current_a = apply_derate(
        min4(
            hardware->max_regen_current_a,
            vehicle->max_regen_current_a,
            mode->max_regen_current_a,
            profile->max_regen_current_a
        ),
        factors->regen_current
    );
    out->max_power_w = apply_derate(
        min4(
            hardware->max_power_w, vehicle->max_power_w, mode->max_power_w, profile->max_power_w
        ),
        factors->power
    );
    out->max_motor_rpm = apply_derate(
        min4(
            hardware->max_motor_rpm, vehicle->max_motor_rpm, mode->max_motor_rpm, profile->max_motor_rpm
        ),
        factors->motor_rpm
    );
    out->max_accel_mps2 = apply_derate(
        min4(
            hardware->max_accel_mps2,
            vehicle->max_accel_mps2,
            mode->max_accel_mps2,
            profile->max_accel_mps2
        ),
        factors->accel
    );
    out->max_decel_mps2 = apply_derate(
        min4(
            hardware->max_decel_mps2,
            vehicle->max_decel_mps2,
            mode->max_decel_mps2,
            profile->max_decel_mps2
        ),
        factors->decel
    );
    out->max_gradient_rad = apply_derate(
        min4(
            hardware->max_gradient_rad,
            vehicle->max_gradient_rad,
            mode->max_gradient_rad,
            profile->max_gradient_rad
        ),
        factors->gradient
    );
}
