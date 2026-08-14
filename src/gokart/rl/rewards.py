"""Minimum-time circuit reward.

The objective is the fastest lap the kart can do with its real limits.
Time on track is costly, so a quicker lap is worth more than a slow one.
On-track heading and lateral offset are free: the policy may use the full
width, brake, and accelerate however the components allow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RewardWeights:
    time: float = 1.0
    progress: float = 0.4
    reverse: float = 1.2
    off_track: float = 2.0
    wall: float = 8.0
    stagnant_terminal: float = 4.0
    lap: float = 50.0


GOD_WEIGHTS = RewardWeights()
ENDURANCE_WEIGHTS = RewardWeights(
    time=0.7,
    progress=0.35,
    lap=60.0,
)


@dataclass
class RewardState:
    last_lap_number: float = 0.0
    prev_lateral_m: float = 0.0
    lap_faults: set[str] = field(default_factory=set)


def reward_preset(objective: str) -> RewardWeights:
    if objective == "endurance":
        return ENDURANCE_WEIGHTS
    return GOD_WEIGHTS


def compute_reward(
    *,
    tick_values: dict[str, Any],
    step_info: dict[str, Any],
    weights: RewardWeights,
    dt_s: float,
    state: RewardState,
    objective: str = "god",
    endurance_soc_floor: float = 0.15,
) -> tuple[float, RewardState, dict[str, float]]:
    del objective, endurance_soc_floor
    reward = 0.0
    components: dict[str, float] = {}

    delta_s = float(step_info.get("delta_track_s_m", 0.0))
    lateral = abs(float(step_info.get("lateral_offset_m", 0.0)))
    track_width = max(float(step_info.get("track_width_m", 10.0)), 1.0)
    off_track = lateral > track_width * 0.5
    safety_state = str(tick_values.get("safety_state", "DRIVING"))
    can_control = safety_state == "DRIVING"

    time_cost = -weights.time * dt_s
    reward += time_cost
    components["time"] = time_cost

    if can_control:
        if delta_s > 0.0 and not off_track:
            progress = weights.progress * min(delta_s, 0.4)
            reward += progress
            components["progress"] = progress
        elif delta_s < 0.0:
            reverse = -weights.reverse * min(abs(delta_s), 0.4)
            reward += reverse
            components["reverse"] = reverse

    if off_track:
        off_penalty = -weights.off_track * dt_s
        reward += off_penalty
        components["off_track"] = off_penalty

    if bool(step_info.get("terminated_off_track")):
        wall = -weights.wall
        reward += wall
        components["wall_hit"] = wall

    if bool(step_info.get("truncated_stagnant")):
        stagnant = -weights.stagnant_terminal
        reward += stagnant
        components["stagnant_terminal"] = stagnant

    lap_number = float(step_info.get("lap_number", 0.0))
    if lap_number > state.last_lap_number and state.last_lap_number > 0:
        reward += weights.lap
        components["lap"] = weights.lap
    state.last_lap_number = lap_number
    state.prev_lateral_m = lateral
    return reward, state, components
