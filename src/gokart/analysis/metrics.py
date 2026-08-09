"""Session metric extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gokart.units import kmh_to_mps, mps_to_kmh

SPEED_THRESHOLDS_KMH = (10, 20, 30, 40, 50)


@dataclass(frozen=True)
class SessionMetrics:
    accel_10_kmh_s: float | None = None
    accel_20_kmh_s: float | None = None
    accel_30_kmh_s: float | None = None
    accel_40_kmh_s: float | None = None
    accel_50_kmh_s: float | None = None
    top_speed_kmh: float = 0.0
    peak_power_w: float = 0.0
    avg_power_w: float = 0.0
    energy_used_wh: float = 0.0
    regen_energy_wh: float = 0.0
    distance_km: float = 0.0
    wh_per_km: float | None = None
    peak_battery_current_a: float = 0.0
    peak_motor_current_a: float = 0.0
    max_motor_temp_c: float = 0.0
    avg_motor_temp_c: float = 0.0
    max_battery_temp_c: float = 0.0
    avg_battery_temp_c: float = 0.0
    duration_s: float = 0.0
    extra: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, float | None]:
        return {
            "accel_10_kmh_s": self.accel_10_kmh_s,
            "accel_20_kmh_s": self.accel_20_kmh_s,
            "accel_30_kmh_s": self.accel_30_kmh_s,
            "accel_40_kmh_s": self.accel_40_kmh_s,
            "accel_50_kmh_s": self.accel_50_kmh_s,
            "top_speed_kmh": self.top_speed_kmh,
            "peak_power_w": self.peak_power_w,
            "avg_power_w": self.avg_power_w,
            "energy_used_wh": self.energy_used_wh,
            "regen_energy_wh": self.regen_energy_wh,
            "distance_km": self.distance_km,
            "wh_per_km": self.wh_per_km,
            "peak_battery_current_a": self.peak_battery_current_a,
            "peak_motor_current_a": self.peak_motor_current_a,
            "max_motor_temp_c": self.max_motor_temp_c,
            "avg_motor_temp_c": self.avg_motor_temp_c,
            "max_battery_temp_c": self.max_battery_temp_c,
            "avg_battery_temp_c": self.avg_battery_temp_c,
            "duration_s": self.duration_s,
            **self.extra,
        }


def _first_crossing_time(samples: list[dict[str, Any]], threshold_mps: float) -> float | None:
    for index, sample in enumerate(samples):
        speed = float(sample.get("speed_mps", 0.0))
        if speed >= threshold_mps:
            if index == 0:
                return float(sample.get("time_s", 0.0))
            prev = samples[index - 1]
            prev_speed = float(prev.get("speed_mps", 0.0))
            prev_time = float(prev.get("time_s", 0.0))
            curr_time = float(sample.get("time_s", 0.0))
            if speed == prev_speed:
                return curr_time
            ratio = (threshold_mps - prev_speed) / (speed - prev_speed)
            return prev_time + ratio * (curr_time - prev_time)
    return None


def compute_metrics(samples: list[dict[str, Any]]) -> SessionMetrics:
    if not samples:
        return SessionMetrics()

    times = [float(s.get("time_s", 0.0)) for s in samples]
    speeds = [float(s.get("speed_mps", 0.0)) for s in samples]
    powers = [float(s.get("power_w", 0.0)) for s in samples]
    positions = [float(s.get("position_m", 0.0)) for s in samples]
    motor_temps = [float(s.get("motor_temp_c", 0.0)) for s in samples]
    battery_temps = [float(s.get("battery_temp_c", 0.0)) for s in samples]
    battery_currents = [abs(float(s.get("battery_current_a", 0.0))) for s in samples]
    motor_currents = [abs(float(s.get("motor_current_a", 0.0))) for s in samples]

    duration = times[-1] - times[0] if len(times) > 1 else 0.0
    distance_m = max(positions) - min(positions)
    distance_km = distance_m / 1000.0

    energy_used_j = 0.0
    regen_j = 0.0
    for index in range(1, len(samples)):
        dt = times[index] - times[index - 1]
        if dt <= 0:
            continue
        power = powers[index]
        if power >= 0:
            energy_used_j += power * dt
        else:
            regen_j += abs(power) * dt

    accel_times: dict[str, float | None] = {}
    for threshold_kmh in SPEED_THRESHOLDS_KMH:
        key = f"accel_{threshold_kmh}_kmh_s"
        accel_times[key] = _first_crossing_time(samples, kmh_to_mps(threshold_kmh))

    wh_per_km = (energy_used_j / 3600.0) / distance_km if distance_km > 1e-6 else None

    return SessionMetrics(
        accel_10_kmh_s=accel_times["accel_10_kmh_s"],
        accel_20_kmh_s=accel_times["accel_20_kmh_s"],
        accel_30_kmh_s=accel_times["accel_30_kmh_s"],
        accel_40_kmh_s=accel_times["accel_40_kmh_s"],
        accel_50_kmh_s=accel_times["accel_50_kmh_s"],
        top_speed_kmh=mps_to_kmh(max(speeds)),
        peak_power_w=max(powers) if powers else 0.0,
        avg_power_w=sum(powers) / len(powers) if powers else 0.0,
        energy_used_wh=energy_used_j / 3600.0,
        regen_energy_wh=regen_j / 3600.0,
        distance_km=distance_km,
        wh_per_km=wh_per_km,
        peak_battery_current_a=max(battery_currents) if battery_currents else 0.0,
        peak_motor_current_a=max(motor_currents) if motor_currents else 0.0,
        max_motor_temp_c=max(motor_temps) if motor_temps else 0.0,
        avg_motor_temp_c=sum(motor_temps) / len(motor_temps) if motor_temps else 0.0,
        max_battery_temp_c=max(battery_temps) if battery_temps else 0.0,
        avg_battery_temp_c=sum(battery_temps) / len(battery_temps) if battery_temps else 0.0,
        duration_s=duration,
    )


def metric_value(metrics: SessionMetrics, name: str) -> float | None:
    data = metrics.as_dict()
    value = data.get(name)
    if value is None:
        return None
    return float(value)
