#ifndef DISPLAY_DRIVER_H
#define DISPLAY_DRIVER_H

#include "gokart_app.h"

typedef struct {
    const char *name;
    void (*render)(const gokart_app_t *app);
} display_driver_t;

extern const display_driver_t g_display_console_driver;

#endif
