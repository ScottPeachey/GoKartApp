#include "display_console.h"

#include <stdio.h>

#include "display_driver.h"

static void display_console_render_impl(const gokart_app_t *app) {
    float speed_kmh = app->speed_mps * 3.6f;
    printf(
        "DISPLAY speed=%.1f km/h mode=Default soc=%.0f%% state=%d torque=%s power=%.0fW\n",
        speed_kmh,
        app->soc * 100.0f,
        (int)app->safety_state,
        app->safety_outputs.torque_permitted ? "on" : "off",
        app->sensors.pack_voltage_v * 10.0f
    );
}

const display_driver_t g_display_console_driver = {
    .name = "console",
    .render = display_console_render_impl,
};

void display_console_render(const gokart_app_t *app) {
    g_display_console_driver.render(app);
}
