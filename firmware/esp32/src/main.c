#include "gokart_config.h"
#include "display_console.h"
#include "gokart_app.h"
#include "mock_sensors.h"
#include "telemetry_stream.h"

#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

static const char *TAG = "gokart_main";

static void control_task(void *arg) {
    (void)arg;
    gokart_app_t *app = gokart_app_get();
    TickType_t last_wake = xTaskGetTickCount();
    const TickType_t period = pdMS_TO_TICKS(10);
    while (true) {
        gokart_app_control_tick(app, 0.01f);
        vTaskDelayUntil(&last_wake, period);
    }
}

static void telemetry_task(void *arg) {
    (void)arg;
    gokart_app_t *app = gokart_app_get();
    TickType_t last_wake = xTaskGetTickCount();
    const TickType_t period = pdMS_TO_TICKS(20);
    while (true) {
        telemetry_stream_publish(app);
        vTaskDelayUntil(&last_wake, period);
    }
}

static void display_task(void *arg) {
    (void)arg;
    gokart_app_t *app = gokart_app_get();
    TickType_t last_wake = xTaskGetTickCount();
    const TickType_t period = pdMS_TO_TICKS(100);
    while (true) {
        display_console_render(app);
        vTaskDelayUntil(&last_wake, period);
    }
}

void app_main(void) {
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }

    gokart_app_t *app = gokart_app_get();
    gokart_app_init(app, false);

    ESP_LOGI(TAG, "GoKart firmware booting (mock sensors=%d)", CONFIG_GOKART_MOCK_SENSORS);
    xTaskCreatePinnedToCore(control_task, "control_task", 4096, NULL, 10, NULL, 1);
    xTaskCreatePinnedToCore(telemetry_task, "telemetry_task", 4096, NULL, 3, NULL, 0);
    xTaskCreatePinnedToCore(display_task, "display_task", 4096, NULL, 2, NULL, 0);
}
