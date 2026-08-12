"""Canonical telemetry channel schema — single source of truth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ChannelType = Literal["float", "string"]


@dataclass(frozen=True)
class TelemetryChannel:
    name: str
    unit: str
    channel_type: ChannelType = "float"


TELEMETRY_CHANNELS: tuple[TelemetryChannel, ...] = (
    TelemetryChannel("time_s", "s"),
    TelemetryChannel("position_m", "m"),
    TelemetryChannel("speed_mps", "m/s"),
    TelemetryChannel("acceleration_mps2", "m/s2"),
    TelemetryChannel("throttle", "1"),
    TelemetryChannel("brake", "1"),
    TelemetryChannel("steering", "1"),
    TelemetryChannel("steering_angle_deg", "deg"),
    TelemetryChannel("heading_deg", "deg"),
    TelemetryChannel("elevation_m", "m"),
    TelemetryChannel("pitch_deg", "deg"),
    TelemetryChannel("roll_deg", "deg"),
    TelemetryChannel("position_x_m", "m"),
    TelemetryChannel("position_y_m", "m"),
    TelemetryChannel("track_s_m", "m"),
    TelemetryChannel("track_lateral_m", "m"),
    TelemetryChannel("lap_number", "1"),
    TelemetryChannel("lap_time_s", "s"),
    TelemetryChannel("last_lap_time_s", "s"),
    TelemetryChannel("best_lap_time_s", "s"),
    TelemetryChannel("motor_rpm", "rpm"),
    TelemetryChannel("motor_torque_nm", "N*m"),
    TelemetryChannel("motor_current_a", "A"),
    TelemetryChannel("battery_current_a", "A"),
    TelemetryChannel("pack_voltage_v", "V"),
    TelemetryChannel("soc", "1"),
    TelemetryChannel("power_w", "W"),
    TelemetryChannel("traction_force_n", "N"),
    TelemetryChannel("front_normal_n", "N"),
    TelemetryChannel("rear_normal_n", "N"),
    TelemetryChannel("front_lateral_n", "N"),
    TelemetryChannel("rear_traction_n", "N"),
    TelemetryChannel("tyre_temp_front_c", "C"),
    TelemetryChannel("tyre_temp_rear_c", "C"),
    TelemetryChannel("tyre_temp_fl_c", "C"),
    TelemetryChannel("tyre_temp_fr_c", "C"),
    TelemetryChannel("tyre_temp_rl_c", "C"),
    TelemetryChannel("tyre_temp_rr_c", "C"),
    TelemetryChannel("tyre_wear_front", "1"),
    TelemetryChannel("tyre_wear_rear", "1"),
    TelemetryChannel("grip_front_effective", "1"),
    TelemetryChannel("grip_rear_effective", "1"),
    TelemetryChannel("motor_temp_c", "C"),
    TelemetryChannel("battery_temp_c", "C"),
    TelemetryChannel("traction_limited", "1"),
    TelemetryChannel("filtered_throttle", "1"),
    TelemetryChannel("drive_mode", "1", channel_type="string"),
    TelemetryChannel("safety_state", "1", channel_type="string"),
    TelemetryChannel("contactor_command", "1", channel_type="string"),
    TelemetryChannel("torque_permitted", "1"),
    TelemetryChannel("active_faults", "1", channel_type="string"),
    TelemetryChannel("derating_factor", "1"),
)

CHANNEL_NAMES: tuple[str, ...] = tuple(channel.name for channel in TELEMETRY_CHANNELS)
STRING_CHANNELS: frozenset[str] = frozenset(
    channel.name for channel in TELEMETRY_CHANNELS if channel.channel_type == "string"
)


def channel_schema() -> list[dict[str, str]]:
    return [
        {"name": channel.name, "unit": channel.unit, "type": channel.channel_type}
        for channel in TELEMETRY_CHANNELS
    ]


def validate_sample_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a row containing only known channels with correct types."""
    validated: dict[str, Any] = {}
    for channel in TELEMETRY_CHANNELS:
        if channel.name not in row:
            continue
        value = row[channel.name]
        if channel.channel_type == "string":
            validated[channel.name] = str(value)
        else:
            validated[channel.name] = float(value)
    return validated


def sample_to_json(row: dict[str, Any]) -> dict[str, Any]:
    return validate_sample_row(row)
