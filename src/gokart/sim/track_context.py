"""Track-aware simulation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from gokart.physics.vehicle import Environment
from gokart.track.lap import LapTimer, project_xy_to_track, spawn_pose_on_track
from gokart.track.model import Track

# Keep progress locked to the current stretch so off-track karts cannot snap
# to a later/earlier section of the circuit (infield shortcuts, S/F loops).
PROGRESS_WINDOW_M = 30.0


@dataclass
class TrackSimulationContext:
    track: Track
    lap_timer: LapTimer = field(init=False)
    _progress_s: float | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.lap_timer = LapTimer(self.track)
        self._progress_s = None

    @property
    def completed_laps(self):
        return self.lap_timer.completed_laps

    def reset(self) -> None:
        self.lap_timer.reset()
        self._progress_s = None

    def spawn_pose(self) -> tuple[float, float, float]:
        return spawn_pose_on_track(self.track)

    def environment_at(self, x: float, y: float, base: Environment) -> Environment:
        projection = project_xy_to_track(
            self.track.centerline,
            x,
            y,
            around_s_m=self._progress_s,
            window_m=PROGRESS_WINDOW_M,
            length_m=self.track.length_m,
        )
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
        projection = project_xy_to_track(
            self.track.centerline,
            x,
            y,
            around_s_m=self._progress_s,
            window_m=PROGRESS_WINDOW_M,
            length_m=self.track.length_m,
        )
        self._progress_s = projection.s_m
        lap_values = self.lap_timer.update(time_s, x, y, speed_mps)
        return {
            "track_s_m": projection.s_m,
            "track_lateral_m": projection.lateral_m,
            "path_heading_rad": projection.heading_rad,
            "elevation_m": projection.elevation_m,
            **lap_values,
        }
