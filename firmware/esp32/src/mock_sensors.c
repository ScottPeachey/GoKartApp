#include "mock_sensors.h"

void mock_sensors_init(gokart_app_t *app) {
    app->sensors.throttle_adc = 2000;
    app->sensors.brake_adc = 2000;
    app->sensors.throttle = 0.0f;
    app->sensors.brake = 0.0f;
    app->sensors.pack_voltage_v = 51.2f;
    app->sensors.min_cell_voltage_v = 3.2f;
    app->sensors.max_cell_voltage_v = 3.3f;
    app->sensors.motor_temp_c = 30.0f;
    app->sensors.controller_temp_c = 30.0f;
    app->sensors.battery_temp_c = 28.0f;
    app->sensors.wheel_speed_valid = true;
    app->sensors.can_vesc_alive = true;
    app->sensors.can_bms_alive = true;
    app->sensors.precharge_feedback_ok = true;
}

void mock_sensors_update(gokart_app_t *app, float dt) {
    (void)dt;
    if (app->safety_state == GK_SAFETY_READY && app->time_s > 0.3f) {
        app->sensors.brake = 1.0f;
        app->sensors.brake_adc = 3900;
        app->sensors.throttle = 0.0f;
        app->sensors.throttle_adc = 2000;
    }

    if (
        app->safety_state == GK_SAFETY_ARMED &&
        app->timers.precharge_elapsed_s < app->safety_config.precharge_timeout_s
    ) {
        app->sensors.brake = 1.0f;
        app->sensors.brake_adc = 3900;
        app->sensors.throttle = 0.0f;
        app->sensors.throttle_adc = 2000;
    }

    if (
        app->safety_state == GK_SAFETY_ARMED &&
        app->timers.precharge_elapsed_s >= app->safety_config.precharge_timeout_s
    ) {
        app->sensors.brake = 0.0f;
        app->sensors.brake_adc = 2000;
        app->sensors.throttle = 0.55f;
        app->sensors.throttle_adc = 2700;
    }

    if (app->safety_state == GK_SAFETY_DRIVING) {
        app->sensors.throttle = 0.65f;
        app->sensors.throttle_adc = 2800;
        app->sensors.brake = 0.0f;
        app->sensors.brake_adc = 2000;
    }

    if (app->safety_state == GK_SAFETY_FAULT || app->safety_state == GK_SAFETY_SAFE_SHUTDOWN) {
        app->sensors.throttle = 0.0f;
        app->sensors.throttle_adc = 2000;
    }

    app->sensors.speed_mps = app->speed_mps;
    app->sensors.implied_speed_mps = app->speed_mps;
    app->sensors.motor_rpm =
        app->speed_mps * 60.0f / (2.0f * 3.14159265f * 0.127f) * app->control_params.gear_ratio;
}
