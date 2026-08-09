#ifndef GOKART_GK_LIMITS_H
#define GOKART_GK_LIMITS_H

#include "gk_types.h"

void gk_resolve_limits(
    const gk_limit_layer_t *hardware,
    const gk_limit_layer_t *vehicle,
    const gk_limit_layer_t *mode,
    const gk_limit_layer_t *profile,
    const gk_derating_factors_t *derating,
    gk_effective_limits_t *out
);

#endif
