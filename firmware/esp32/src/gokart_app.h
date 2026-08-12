#ifndef GOKART_APP_H
#define GOKART_APP_H

#include <stdbool.h>

#include "gk_control.h"
#include "gk_safety.h"
#include "gk_types.h"
#include "command_slot.h"
#include "sensor_snapshot.h"

typedef struct {
    gk_safety_state_t safety_state;
    gk_safety_timers_t timers;
    uint32_t latched_faults;
    gk_safety_config_t safety_config;
    gk_safety_outputs_t safety_outputs;
    gk_control_state_t control_state;
    gk_control_params_t control_params;
    gk_control_outputs_t control_outputs;
    gk_effective_limits_t limits;
    gk_sensor_inputs_t sensors;
    gk_detection_state_t detection_state;
    sensor_snapshot_t sensor_snapshot;
    command_slot_t command_slot;
    float speed_mps;
    float soc;
    bool power_on_request;
    bool arm_request;
    float time_s;
} gokart_app_t;

gokart_app_t *gokart_app_get(void);
void gokart_app_init(gokart_app_t *app, bool watchdog_reset);
void gokart_app_control_tick(gokart_app_t *app, float dt);

#endif
