#include "display_console.h"

#include <stdio.h>

void display_console_render(const gokart_app_t *app) {
    float speed_kmh = app->speed_mps * 3.6f;
    printf(
        "DISPLAY speed=%.1f km/h mode=Default soc=%.0f%% state=%d fault=0 power=%.0fW\n",
        speed_kmh,
        app->soc * 100.0f,
        (int)app->safety_state,
        app->sensors.pack_voltage_v * 10.0f
    );
}
