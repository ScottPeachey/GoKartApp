#ifndef GOKART_GK_CONTROL_H
#define GOKART_GK_CONTROL_H

#include "gk_types.h"

void gk_control_step(
    const gk_control_inputs_t *inputs,
    const gk_effective_limits_t *limits,
    const gk_safety_outputs_t *safety,
    gk_control_state_t *state,
    const gk_control_params_t *params,
    float dt,
    gk_control_outputs_t *outputs
);

#endif
