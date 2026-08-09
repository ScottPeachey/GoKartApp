"""Simulation pacing — real-time vs accelerated."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class SimClock:
    speedup: float = 1.0
    _sim_time_s: float = 0.0
    _wall_start: float | None = None

    def start(self) -> None:
        self._wall_start = time.perf_counter()

    def tick(self, dt: float) -> float:
        self._sim_time_s += dt
        if self.speedup <= 0:
            return self._sim_time_s
        if self._wall_start is None:
            self.start()
        target_wall = self._sim_time_s / self.speedup
        elapsed = time.perf_counter() - self._wall_start
        delay = target_wall - elapsed
        if delay > 0:
            time.sleep(delay)
        return self._sim_time_s
