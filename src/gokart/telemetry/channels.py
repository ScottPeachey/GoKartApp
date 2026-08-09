"""Simulation telemetry channel definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TelemetryChannel:
    name: str
    unit: str


TELEMETRY_CHANNELS: tuple[TelemetryChannel, ...] = (
    TelemetryChannel("time_s", "s"),
    TelemetryChannel("position_m", "m"),
    TelemetryChannel("speed_mps", "m/s"),
    TelemetryChannel("acceleration_mps2", "m/s2"),
    TelemetryChannel("throttle", "1"),
    TelemetryChannel("brake", "1"),
    TelemetryChannel("motor_rpm", "rpm"),
    TelemetryChannel("motor_torque_nm", "N*m"),
    TelemetryChannel("motor_current_a", "A"),
    TelemetryChannel("battery_current_a", "A"),
    TelemetryChannel("pack_voltage_v", "V"),
    TelemetryChannel("soc", "1"),
    TelemetryChannel("power_w", "W"),
    TelemetryChannel("traction_force_n", "N"),
    TelemetryChannel("motor_temp_c", "C"),
    TelemetryChannel("battery_temp_c", "C"),
    TelemetryChannel("traction_limited", "1"),
    TelemetryChannel("filtered_throttle", "1"),
)

CHANNEL_NAMES: tuple[str, ...] = tuple(channel.name for channel in TELEMETRY_CHANNELS)
