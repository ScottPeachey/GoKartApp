"""Rule-based autonomous driver agent."""

from __future__ import annotations

from dataclasses import dataclass

from gokart.driver.pure_pursuit import pure_pursuit_step
from gokart.driver.racing_line import build_racing_line, project_to_line
from gokart.driver.speed_profile import SpeedProfile, build_speed_profile
from gokart.track.model import Track


@dataclass(frozen=True)
class DriverConfig:
    grip_coefficient: float
    max_speed_mps: float
    wheelbase_m: float
    aggression: float = 1.0
    apex_offset_m: float = 0.85


@dataclass(frozen=True)
class DriverOutputs:
    throttle: float
    brake: float
    steering: float
    target_speed_mps: float
    track_s_m: float
    lateral_m: float


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

    @property
    def racing_line(self):
        return self._line

    @property
    def speed_profile(self) -> SpeedProfile:
        return self._profile

    def step(
        self,
        *,
        x: float,
        y: float,
        heading_rad: float,
        speed_mps: float,
        soc: float = 1.0,
    ) -> DriverOutputs:
        s_m, lateral_m = project_to_line(self._line, x, y)
        pursuit = pure_pursuit_step(
            x=x,
            y=y,
            heading_rad=heading_rad,
            speed_mps=speed_mps,
            s_m=s_m,
            line=self._line,
            profile=self._profile,
            track_length_m=self.track.length_m,
            wheelbase_m=self.config.wheelbase_m,
            soc=soc,
            aggression=self.config.aggression,
        )
        return DriverOutputs(
            throttle=pursuit.throttle,
            brake=pursuit.brake,
            steering=pursuit.steering,
            target_speed_mps=pursuit.target_speed_mps,
            track_s_m=s_m,
            lateral_m=lateral_m,
        )
