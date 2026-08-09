#ifndef GOKART_GK_SAFETY_H
#define GOKART_GK_SAFETY_H

#include "gk_types.h"

void gk_safety_step(
    gk_safety_state_t state,
    const gk_safety_inputs_t *inputs,
    const gk_safety_config_t *config,
    gk_safety_timers_t *timers,
    uint32_t latched_faults_in,
    float dt,
    gk_safety_state_t *next_state,
    gk_safety_outputs_t *outputs,
    uint32_t *latched_faults_out
);

#endif
