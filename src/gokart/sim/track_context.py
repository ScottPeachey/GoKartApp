"""Track-aware simulation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from gokart.physics.vehicle import Environment
from gokart.track.lap import LapTimer, project_xy_to_track, spawn_pose_on_track
from gokart.track.model import Track


@dataclass
class TrackSimulationContext:
    track: Track
    lap_timer: LapTimer = field(init=False)

    def __post_init__(self) -> None:
        self.lap_timer = LapTimer(self.track)

    @property
    def completed_laps(self):
        return self.lap_timer.completed_laps

    def spawn_pose(self) -> tuple[float, float, float]:
        return spawn_pose_on_track(self.track)

    def environment_at(self, x: float, y: float, base: Environment) -> Environment:
        projection = project_xy_to_track(self.track.centerline, x, y)
        return Environment(
            gradient_rad=projection.gradient_rad,
            ambient_temp_c=base.ambient_temp_c,
            surface_mu_scale=base.surface_mu_scale,
        )

    def tick(
        self,
        time_s: float,
        x: float,
        y: float,
        speed_mps: float,
    ) -> dict[str, float]:
        projection = project_xy_to_track(self.track.centerline, x, y)
        lap_values = self.lap_timer.update(time_s, x, y, speed_mps)
        return {
            "track_s_m": projection.s_m,
            "track_lateral_m": projection.lateral_m,
            **lap_values,
        }
