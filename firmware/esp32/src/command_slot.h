#ifndef COMMAND_SLOT_H
#define COMMAND_SLOT_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    float motor_torque_request_nm;
    float regen_torque_request_nm;
    float mechanical_brake;
    bool torque_permitted;
    uint32_t sequence;
} command_slot_t;

void command_slot_init(command_slot_t *slot);
void command_slot_publish(
    command_slot_t *slot,
    float motor_torque_nm,
    float regen_torque_nm,
    float mechanical_brake,
    bool torque_permitted
);
void command_slot_read(const command_slot_t *slot, command_slot_t *out);

#endif
