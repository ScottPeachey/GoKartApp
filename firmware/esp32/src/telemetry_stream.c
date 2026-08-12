#include "telemetry_stream.h"

#include <stdio.h>

#include "esp_log.h"

static const char *TAG = "telemetry";

static const char *safety_state_name(gk_safety_state_t state) {
    switch (state) {
        case GK_SAFETY_OFF:
            return "OFF";
        case GK_SAFETY_BOOT:
            return "BOOT";
        case GK_SAFETY_SELF_TEST:
            return "SELF_TEST";
        case GK_SAFETY_READY:
            return "READY";
        case GK_SAFETY_ARMED:
            return "ARMED";
        case GK_SAFETY_DRIVING:
            return "DRIVING";
        case GK_SAFETY_FAULT:
            return "FAULT";
        case GK_SAFETY_SAFE_SHUTDOWN:
            return "SAFE_SHUTDOWN";
        default:
            return "OFF";
    }
}

static const char *contactor_command_name(gk_contactor_command_t command) {
    switch (command) {
        case GK_CONTACTOR_OPEN:
            return "OPEN";
        case GK_CONTACTOR_PRECHARGE:
            return "PRECHARGE";
        case GK_CONTACTOR_CLOSE:
            return "CLOSE";
        default:
            return "OPEN";
    }
}

void telemetry_stream_publish(const gokart_app_t *app) {
    float power_w = app->sensors.pack_voltage_v * 10.0f;
    printf(
        "{\"time_s\":%.3f,\"speed_mps\":%.3f,\"throttle\":%.3f,\"brake\":%.3f,"
        "\"motor_rpm\":%.1f,\"battery_current_a\":10.0,\"pack_voltage_v\":%.2f,"
        "\"soc\":%.3f,\"power_w\":%.1f,\"safety_state\":\"%s\","
        "\"contactor_command\":\"%s\",\"torque_permitted\":%s,"
        "\"motor_torque_nm\":%.2f,\"filtered_throttle\":%.3f}\n",
        app->time_s,
        app->speed_mps,
        app->sensors.throttle,
        app->sensors.brake,
        app->sensors.motor_rpm,
        app->sensors.pack_voltage_v,
        app->soc,
        power_w,
        safety_state_name(app->safety_state),
        contactor_command_name(app->safety_outputs.contactor_command),
        app->safety_outputs.torque_permitted ? "1.0" : "0.0",
        app->control_outputs.motor_torque_request_nm,
        app->control_outputs.filtered_throttle
    );
    ESP_LOGD(TAG, "state=%s speed=%.2f", safety_state_name(app->safety_state), app->speed_mps);
}
