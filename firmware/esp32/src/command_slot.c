#include "command_slot.h"

void command_slot_init(command_slot_t *slot) {
    slot->motor_torque_request_nm = 0.0f;
    slot->regen_torque_request_nm = 0.0f;
    slot->mechanical_brake = 0.0f;
    slot->torque_permitted = false;
    slot->sequence = 0u;
}

void command_slot_publish(
    command_slot_t *slot,
    float motor_torque_nm,
    float regen_torque_nm,
    float mechanical_brake,
    bool torque_permitted
) {
    slot->motor_torque_request_nm = motor_torque_nm;
    slot->regen_torque_request_nm = regen_torque_nm;
    slot->mechanical_brake = mechanical_brake;
    slot->torque_permitted = torque_permitted;
    slot->sequence += 1u;
}

void command_slot_read(const command_slot_t *slot, command_slot_t *out) {
    *out = *slot;
}
