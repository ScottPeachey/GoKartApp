#include "telemetry_stream.h"

#include <stdio.h>

#include "esp_log.h"

static const char *TAG = "telemetry";

void telemetry_stream_publish(const gokart_app_t *app) {
    float power_w = app->sensors.pack_voltage_v * 10.0f;
    printf(
        "{\"time_s\":%.3f,\"speed_mps\":%.3f,\"throttle\":%.3f,\"brake\":%.3f,"
        "\"motor_rpm\":%.1f,\"battery_current_a\":10.0,\"pack_voltage_v\":%.2f,"
        "\"soc\":%.3f,\"power_w\":%.1f,\"safety_state\":\"%d\","
        "\"contactor_command\":\"%d\",\"torque_permitted\":%s}\n",
        app->time_s,
        app->speed_mps,
        app->sensors.throttle,
        app->sensors.brake,
        app->sensors.motor_rpm,
        app->sensors.pack_voltage_v,
        app->soc,
        power_w,
        (int)app->safety_state,
        0,
        app->safety_state == GK_SAFETY_DRIVING ? "true" : "false"
    );
    ESP_LOGD(TAG, "state=%d speed=%.2f", app->safety_state, app->speed_mps);
}
