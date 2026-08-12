#ifndef SENSOR_SNAPSHOT_H
#define SENSOR_SNAPSHOT_H

#include <stdint.h>

#include "gk_types.h"

typedef struct {
    gk_sensor_inputs_t sensors;
    uint32_t sequence;
} sensor_snapshot_frame_t;

typedef struct {
    sensor_snapshot_frame_t buffers[2];
    volatile uint8_t read_index;
    volatile uint8_t write_index;
} sensor_snapshot_t;

void sensor_snapshot_init(sensor_snapshot_t *snapshot);
void sensor_snapshot_publish(sensor_snapshot_t *snapshot, const gk_sensor_inputs_t *sensors);
void sensor_snapshot_read(const sensor_snapshot_t *snapshot, gk_sensor_inputs_t *out, uint32_t *sequence_out);

#endif
