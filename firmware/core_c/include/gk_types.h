#ifndef GOKART_GK_TYPES_H
#define GOKART_GK_TYPES_H

#include <stdbool.h>
#include <stdint.h>

#define GK_GRAVITY_MPS2 9.80665f

typedef enum {
    GK_FAULT_THROTTLE_OUT_OF_RANGE = 0,
    GK_FAULT_THROTTLE_IMPLAUSIBLE,
    GK_FAULT_BRAKE_SENSOR_FAULT,
    GK_FAULT_THROTTLE_BRAKE_SIMULTANEOUS,
    GK_FAULT_WHEEL_SPEED_FAULT,
    GK_FAULT_SENSOR_DISAGREEMENT,
    GK_FAULT_CAN_TIMEOUT,
    GK_FAULT_VESC_FAULT,
    GK_FAULT_BMS_FAULT,
    GK_FAULT_PACK_OVERVOLTAGE,
    GK_FAULT_PACK_UNDERVOLTAGE,
    GK_FAULT_CELL_OVERVOLTAGE,
    GK_FAULT_CELL_UNDERVOLTAGE,
    GK_FAULT_MOTOR_OVERTEMP_DERATE,
    GK_FAULT_MOTOR_OVERTEMP,
    GK_FAULT_CONTROLLER_OVERTEMP_DERATE,
    GK_FAULT_CONTROLLER_OVERTEMP,
    GK_FAULT_BATTERY_OVERTEMP_DERATE,
    GK_FAULT_BATTERY_OVERTEMP,
    GK_FAULT_OVERSPEED,
    GK_FAULT_WATCHDOG_RESET,
    GK_FAULT_CONTACTOR_FEEDBACK_MISMATCH,
    GK_FAULT_PRECHARGE_FAILURE,
    GK_FAULT_COUNT
} gk_fault_id_t;

typedef enum {
    GK_SAFETY_OFF = 0,
    GK_SAFETY_BOOT,
    GK_SAFETY_SELF_TEST,
    GK_SAFETY_READY,
    GK_SAFETY_ARMED,
    GK_SAFETY_DRIVING,
    GK_SAFETY_FAULT,
    GK_SAFETY_SAFE_SHUTDOWN
} gk_safety_state_t;

typedef enum {
    GK_CONTACTOR_OPEN = 0,
    GK_CONTACTOR_PRECHARGE,
    GK_CONTACTOR_CLOSE
} gk_contactor_command_t;

typedef struct {
    float max_speed_mps;
    float max_motor_current_a;
    float max_battery_current_a;
    float max_regen_current_a;
    float max_power_w;
    float max_motor_rpm;
    float max_accel_mps2;
    float max_decel_mps2;
    float max_gradient_rad;
} gk_limit_layer_t;

typedef struct {
    float speed;
    float motor_current;
    float battery_current;
    float regen_current;
    float power;
    float motor_rpm;
    float accel;
    float decel;
    float gradient;
} gk_derating_factors_t;

typedef struct {
    float max_speed_mps;
    float max_motor_current_a;
    float max_battery_current_a;
    float max_regen_current_a;
    float max_power_w;
    float max_motor_rpm;
    float max_accel_mps2;
    float max_decel_mps2;
    float max_gradient_rad;
} gk_effective_limits_t;

typedef struct {
    int throttle_adc_min;
    int throttle_adc_max;
    int brake_adc_min;
    int brake_adc_max;
    float throttle_brake_simultaneous_threshold;
    float pack_voltage_max_v;
    float pack_voltage_min_v;
    float cell_voltage_max_v;
    float cell_voltage_min_v;
    float motor_temp_derate_c;
    float motor_temp_fault_c;
    float controller_temp_derate_c;
    float controller_temp_fault_c;
    float battery_temp_derate_c;
    float battery_temp_fault_c;
    float max_speed_mps;
    float can_timeout_s;
    float precharge_timeout_s;
    float self_test_duration_s;
    float throttle_drive_deadband;
    float wheel_speed_disagreement_ratio;
    float derate_factor;
} gk_safety_config_t;

typedef struct {
    int throttle_adc;
    int brake_adc;
    float throttle;
    float brake;
    float speed_mps;
    float motor_rpm;
    float implied_speed_mps;
    float pack_voltage_v;
    float min_cell_voltage_v;
    float max_cell_voltage_v;
    float motor_temp_c;
    float controller_temp_c;
    float battery_temp_c;
    bool wheel_speed_valid;
    bool can_vesc_alive;
    bool can_bms_alive;
    float can_silence_s;
    bool vesc_fault_active;
    bool bms_fault_active;
    bool watchdog_reset_detected;
} gk_sensor_inputs_t;

typedef struct {
    int previous_throttle_adc;
} gk_detection_state_t;

typedef struct {
    bool power_on_request;
    bool arm_request;
    bool disarm_request;
    bool fault_ack_request;
    bool power_cycle_event;
    bool driver_authenticated;
    bool brake_pressed;
    float throttle;
    uint32_t detected_faults;
    bool precharge_feedback_ok;
    bool contactor_feedback_closed;
    bool contactor_feedback_open;
} gk_safety_inputs_t;

typedef struct {
    float state_elapsed_s;
    float precharge_elapsed_s;
    float shutdown_elapsed_s;
} gk_safety_timers_t;

typedef struct {
    bool torque_permitted;
    bool regen_permitted;
    gk_contactor_command_t contactor_command;
    gk_derating_factors_t derating;
    uint32_t active_faults;
    int display_message_code;
    gk_safety_state_t safety_state;
} gk_safety_outputs_t;

typedef struct {
    float throttle;
    float brake;
    float speed_mps;
    float motor_rpm;
    float pack_voltage_v;
    float mass_kg;
    float grip_coefficient;
    float gradient_rad;
} gk_control_inputs_t;

typedef struct {
    float filtered_throttle;
    float traction_scale;
} gk_control_state_t;

typedef struct {
    const char *throttle_curve;
    float throttle_ramp_per_s;
    bool throttle_ramp_enabled;
    const char *traction_limiter;
    float regen_strength;
} gk_drive_mode_t;

typedef struct {
    gk_drive_mode_t mode;
    float motor_peak_torque_nm;
    float wheel_radius_m;
    float gear_ratio;
    float drivetrain_efficiency;
    float motor_efficiency;
} gk_control_params_t;

typedef struct {
    float motor_torque_request_nm;
    float regen_torque_request_nm;
    float mechanical_brake;
    float filtered_throttle;
    bool traction_limited;
} gk_control_outputs_t;

#endif
