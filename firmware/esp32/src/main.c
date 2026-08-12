#include "gokart_config.h"
#include "display_console.h"
#include "display_driver.h"
#include "gokart_app.h"
#include "mock_sensors.h"
#include "telemetry_stream.h"

#include "esp_log.h"
#include "esp_system.h"
#include "esp_task_wdt.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

static const char *TAG = "gokart_main";
static const display_driver_t *g_active_display = &g_display_console_driver;

static void sensor_task(void *arg) {
    (void)arg;
    gokart_app_t *app = gokart_app_get();
    TickType_t last_wake = xTaskGetTickCount();
    const TickType_t period = pdMS_TO_TICKS(5);
    while (true) {
        mock_sensors_update(app, 0.005f);
        sensor_snapshot_publish(&app->sensor_snapshot, &app->sensors);
        vTaskDelayUntil(&last_wake, period);
    }
}

static void control_task(void *arg) {
    (void)arg;
    gokart_app_t *app = gokart_app_get();
    ESP_ERROR_CHECK(esp_task_wdt_add(NULL));
    TickType_t last_wake = xTaskGetTickCount();
    const TickType_t period = pdMS_TO_TICKS(10);
    while (true) {
        gokart_app_control_tick(app, 0.01f);
        ESP_ERROR_CHECK(esp_task_wdt_reset());
        vTaskDelayUntil(&last_wake, period);
    }
}

static void can_task(void *arg) {
    (void)arg;
    gokart_app_t *app = gokart_app_get();
    TickType_t last_wake = xTaskGetTickCount();
    const TickType_t period = pdMS_TO_TICKS(20);
    while (true) {
        command_slot_t command;
        command_slot_read(&app->command_slot, &command);
        (void)command;
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
        g_active_display->render(app);
        vTaskDelayUntil(&last_wake, period);
    }
}

void app_main(void) {
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }

    ESP_ERROR_CHECK(esp_task_wdt_init(3, true));

    bool watchdog_reset =
        esp_reset_reason() == ESP_RST_TASK_WDT || esp_reset_reason() == ESP_RST_INT_WDT;
    gokart_app_t *app = gokart_app_get();
    gokart_app_init(app, watchdog_reset);

    ESP_LOGI(
        TAG,
        "GoKart firmware booting (mock sensors=%d reset_reason=%d watchdog=%d)",
        CONFIG_GOKART_MOCK_SENSORS,
        (int)esp_reset_reason(),
        (int)watchdog_reset
    );

    xTaskCreatePinnedToCore(sensor_task, "sensor_task", 4096, NULL, 9, NULL, 0);
    xTaskCreatePinnedToCore(control_task, "control_task", 4096, NULL, 10, NULL, 1);
    xTaskCreatePinnedToCore(can_task, "can_task", 4096, NULL, 8, NULL, 0);
    xTaskCreatePinnedToCore(telemetry_task, "telemetry_task", 4096, NULL, 3, NULL, 0);
    xTaskCreatePinnedToCore(display_task, "display_task", 4096, NULL, 2, NULL, 0);
}
