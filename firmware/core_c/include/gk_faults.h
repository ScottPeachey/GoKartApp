#ifndef GOKART_GK_FAULTS_H
#define GOKART_GK_FAULTS_H

#include "gk_types.h"

uint32_t gk_detect_faults(
    const gk_sensor_inputs_t *inputs,
    const gk_safety_config_t *config,
    gk_detection_state_t *detection_state
);

gk_derating_factors_t gk_derating_from_faults(uint32_t faults, const gk_safety_config_t *config);

uint32_t gk_merge_faults(uint32_t a, uint32_t b);

bool gk_fault_is_blocking(gk_fault_id_t fault);
bool gk_fault_is_critical(gk_fault_id_t fault);
bool gk_fault_is_latching(gk_fault_id_t fault);
bool gk_has_blocking_fault(uint32_t faults);
bool gk_has_critical_fault(uint32_t faults);

#endif
