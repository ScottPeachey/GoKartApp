#include "gokart_app.h"

#include <string.h>

#include "gk_faults.h"
#include "gk_limits.h"
#include "mock_sensors.h"

static gokart_app_t g_app;

gokart_app_t *gokart_app_get(void) { return &g_app; }

void gokart_app_init(gokart_app_t *app, bool watchdog_reset) {
    memset(app, 0, sizeof(*app));
    app->safety_state = GK_SAFETY_OFF;
    app->safety_config = (gk_safety_config_t){
        .throttle_adc_min = 100,
        .throttle_adc_max = 3900,
        .brake_adc_min = 100,
        .brake_adc_max = 3900,
        .throttle_brake_simultaneous_threshold = 0.15f,
        .pack_voltage_max_v = 60.0f,
        .pack_voltage_min_v = 40.0f,
        .cell_voltage_max_v = 3.65f,
        .cell_voltage_min_v = 2.8f,
        .motor_temp_derate_c = 100.0f,
        .motor_temp_fault_c = 120.0f,
        .controller_temp_derate_c = 75.0f,
        .controller_temp_fault_c = 85.0f,
        .battery_temp_derate_c = 50.0f,
        .battery_temp_fault_c = 60.0f,
        .max_speed_mps = 20.0f,
        .can_timeout_s = 0.5f,
        .precharge_timeout_s = 2.0f,
        .self_test_duration_s = 0.5f,
        .throttle_drive_deadband = 0.05f,
        .wheel_speed_disagreement_ratio = 0.25f,
        .derate_factor = 0.5f,
    };
    app->control_params = (gk_control_params_t){
        .mode =
            {
                .throttle_curve = "linear",
                .throttle_ramp_per_s = 2.0f,
                .throttle_ramp_enabled = true,
                .traction_limiter = "moderate",
                .regen_strength = 0.5f,
            },
        .motor_peak_torque_nm = 40.0f,
        .wheel_radius_m = 0.127f,
        .gear_ratio = 4.33f,
        .drivetrain_efficiency = 0.92f,
        .motor_efficiency = 0.9f,
    };
    gk_limit_layer_t hw = {
        30.0f, 200.0f, 180.0f, 40.0f, 10000.0f, 6000.0f, 6.0f, 8.0f, 0.2f,
    };
    gk_limit_layer_t vehicle = {
        25.0f, 150.0f, 120.0f, 40.0f, 8000.0f, 5500.0f, 5.0f, 7.0f, 0.15f,
    };
    gk_limit_layer_t mode = {
        22.0f, 120.0f, 100.0f, 35.0f, 6000.0f, 5000.0f, 4.5f, 6.0f, 0.12f,
    };
    gk_limit_layer_t profile = {
        20.0f, 100.0f, 80.0f, 30.0f, 5000.0f, 4500.0f, 4.0f, 5.5f, 0.1f,
    };
    gk_resolve_limits(&hw, &vehicle, &mode, &profile, NULL, &app->limits);
    app->soc = 1.0f;
    app->power_on_request = true;
    if (watchdog_reset) {
        app->sensors.watchdog_reset_detected = true;
    }
    mock_sensors_init(app);
}

void gokart_app_control_tick(gokart_app_t *app, float dt) {
    app->time_s += dt;
    mock_sensors_update(app, dt);

    uint32_t detected = gk_detect_faults(&app->sensors, &app->safety_config, &app->detection_state);
    gk_safety_inputs_t safety_inputs = {
        .power_on_request = app->power_on_request,
        .arm_request = app->arm_request,
        .driver_authenticated = true,
        .brake_pressed = app->sensors.brake > 0.5f,
        .throttle = app->sensors.throttle,
        .detected_faults = detected,
        .precharge_feedback_ok = app->sensors.precharge_feedback_ok,
    };

    gk_safety_state_t next_state;
    gk_safety_outputs_t safety_outputs;
    gk_safety_step(
        app->safety_state,
        &safety_inputs,
        &app->safety_config,
        &app->timers,
        app->latched_faults,
        dt,
        &next_state,
        &safety_outputs,
        &app->latched_faults
    );
    app->safety_state = next_state;

    gk_derating_factors_t derating = safety_outputs.derating;
    gk_resolve_limits(
        &(gk_limit_layer_t){30, 200, 180, 40, 10000, 6000, 6, 8, 0.2f},
        &(gk_limit_layer_t){25, 150, 120, 40, 8000, 5500, 5, 7, 0.15f},
        &(gk_limit_layer_t){22, 120, 100, 35, 6000, 5000, 4.5f, 6, 0.12f},
        &(gk_limit_layer_t){20, 100, 80, 30, 5000, 4500, 4, 5.5f, 0.1f},
        &derating,
        &app->limits
    );

    gk_control_inputs_t control_inputs = {
        .throttle = app->sensors.throttle,
        .brake = app->sensors.brake,
        .speed_mps = app->speed_mps,
        .motor_rpm = app->sensors.motor_rpm,
        .pack_voltage_v = app->sensors.pack_voltage_v,
        .mass_kg = 180.0f,
        .grip_coefficient = 0.9f,
        .gradient_rad = 0.0f,
    };
    gk_control_outputs_t control_outputs;
    gk_control_step(
        &control_inputs,
        &app->limits,
        &safety_outputs,
        &app->control_state,
        &app->control_params,
        dt,
        &control_outputs
    );

    if (app->safety_state == GK_SAFETY_READY && app->time_s > 1.0f) {
        app->arm_request = true;
    }
    if (app->safety_state == GK_SAFETY_DRIVING) {
        app->speed_mps += control_outputs.motor_torque_request_nm * 0.0005f;
        if (app->speed_mps < 0.0f) {
            app->speed_mps = 0.0f;
        }
    }
}
