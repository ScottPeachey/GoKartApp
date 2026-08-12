"""Rule-based autonomous driver agent."""

from __future__ import annotations

from dataclasses import dataclass

from gokart.driver.pure_pursuit import pure_pursuit_step
from gokart.driver.racing_line import build_racing_line
from gokart.driver.speed_profile import SpeedProfile, build_speed_profile
from gokart.driver.track_progress import advance_track_progress
from gokart.track.model import Track


@dataclass(frozen=True)
class DriverConfig:
    grip_coefficient: float
    max_speed_mps: float
    wheelbase_m: float
    aggression: float = 1.0
    apex_offset_m: float = 0.85
    battery_temp_derate_c: float = 50.0
    battery_temp_fault_c: float = 60.0


@dataclass(frozen=True)
class DriverOutputs:
    throttle: float
    brake: float
    steering: float
    target_speed_mps: float
    track_s_m: float
    lateral_m: float


@dataclass
class _DriverActuatorState:
    throttle: float = 0.0
    brake: float = 0.0
    steering: float = 0.0


class RuleBasedDriver:
    """Closed-loop driver that follows a racing line at a curvature-limited pace."""

    def __init__(self, track: Track, config: DriverConfig) -> None:
        self.track = track
        self.config = config
        self._line = build_racing_line(track, apex_offset_m=config.apex_offset_m)
        self._profile: SpeedProfile = build_speed_profile(
            self._line,
            grip_coefficient=config.grip_coefficient,
            max_speed_mps=config.max_speed_mps,
            aggression=config.aggression,
        )
        self._actuators = _DriverActuatorState()
        self._track_s_m: float | None = None

    @property
    def racing_line(self):
        return self._line

    @property
    def speed_profile(self) -> SpeedProfile:
        return self._profile

    def reset_progress(self) -> None:
        self._track_s_m = None
        self._actuators = _DriverActuatorState()

    def step(
        self,
        *,
        x: float,
        y: float,
        heading_rad: float,
        speed_mps: float,
        soc: float = 1.0,
        battery_temp_c: float = 25.0,
        dt: float = 0.01,
    ) -> DriverOutputs:
        s_m, lateral_m, _path_heading = advance_track_progress(
            self.track,
            x=x,
            y=y,
            speed_mps=speed_mps,
            heading_rad=heading_rad,
            prev_s_m=self._track_s_m,
            dt=dt,
        )
        self._track_s_m = s_m
        pursuit = pure_pursuit_step(
            x=x,
            y=y,
            heading_rad=heading_rad,
            speed_mps=speed_mps,
            s_m=s_m,
            lateral_m=lateral_m,
            line=self._line,
            profile=self._profile,
            track_length_m=self.track.length_m,
            wheelbase_m=self.config.wheelbase_m,
            soc=soc,
            aggression=self.config.aggression,
            battery_temp_c=battery_temp_c,
            battery_derate_c=self.config.battery_temp_derate_c,
            battery_fault_c=self.config.battery_temp_fault_c,
            max_speed_mps=self.config.max_speed_mps,
            grip_coefficient=self.config.grip_coefficient,
        )
        throttle = _slew_asymmetric(
            self._actuators.throttle,
            pursuit.throttle,
            up_rate_per_s=3.0,
            down_rate_per_s=15.0,
            dt=dt,
        )
        brake = _slew(self._actuators.brake, pursuit.brake, 2.0, dt)
        steering = _slew_signed(self._actuators.steering, pursuit.steering, 2.5, dt)
        self._actuators.throttle = throttle
        self._actuators.brake = brake
        self._actuators.steering = steering
        return DriverOutputs(
            throttle=throttle,
            brake=brake,
            steering=steering,
            target_speed_mps=pursuit.target_speed_mps,
            track_s_m=s_m,
            lateral_m=lateral_m,
        )


def _slew_asymmetric(
    current: float,
    target: float,
    *,
    up_rate_per_s: float,
    down_rate_per_s: float,
    dt: float,
) -> float:
    if dt <= 0.0:
        return target
    rate = up_rate_per_s if target > current else down_rate_per_s
    delta = max(-rate * dt, min(rate * dt, target - current))
    return max(0.0, min(1.0, current + delta))


def _slew(current: float, target: float, max_rate_per_s: float, dt: float) -> float:
    if dt <= 0.0:
        return target
    delta = max(-max_rate_per_s * dt, min(max_rate_per_s * dt, target - current))
    return max(0.0, min(1.0, current + delta))


def _slew_signed(current: float, target: float, max_rate_per_s: float, dt: float) -> float:
    if dt <= 0.0:
        return target
    delta = max(-max_rate_per_s * dt, min(max_rate_per_s * dt, target - current))
    return max(-1.0, min(1.0, current + delta))
