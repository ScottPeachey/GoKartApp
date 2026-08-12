#include "sensor_snapshot.h"

#include <string.h>

void sensor_snapshot_init(sensor_snapshot_t *snapshot) {
    memset(snapshot, 0, sizeof(*snapshot));
}

void sensor_snapshot_publish(sensor_snapshot_t *snapshot, const gk_sensor_inputs_t *sensors) {
    uint8_t next = (uint8_t)(snapshot->write_index ^ 1u);
    snapshot->buffers[next].sensors = *sensors;
    snapshot->buffers[next].sequence = snapshot->buffers[snapshot->write_index].sequence + 1u;
    snapshot->write_index = next;
    snapshot->read_index = next;
}

void sensor_snapshot_read(const sensor_snapshot_t *snapshot, gk_sensor_inputs_t *out, uint32_t *sequence_out) {
    uint8_t index = snapshot->read_index;
    *out = snapshot->buffers[index].sensors;
    if (sequence_out != NULL) {
        *sequence_out = snapshot->buffers[index].sequence;
    }
}
