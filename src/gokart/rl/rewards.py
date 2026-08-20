"""Progress-first circuit reward.

The learning signal is metres of forward track. Sitting still, crawling, and
ending the episode early are all worse than driving — but failed exits are not
charged leftover episode time, which previously made every crash score the same.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAX_PROGRESS_M_PER_TICK = 0.35


@dataclass(frozen=True)
class RewardWeights:
    progress: float = 1.0
    time: float = 0.05
    reverse: float = 2.0
    off_track: float = 4.0
    wall: float = 15.0
    stagnant_terminal: float = 5.0
    off_track_wander: float = 8.0
    incomplete_lap: float = 40.0
    lap: float = 80.0
    thermal: float = 0.3
    thermal_fault: float = 6.0


GOD_WEIGHTS = RewardWeights()
ENDURANCE_WEIGHTS = RewardWeights(
    progress=0.9,
    time=0.04,
    lap=100.0,
    thermal=0.5,
    thermal_fault=8.0,
)

_BLOCKING_THERMAL_FAULTS = frozenset(
    {"CONTROLLER_OVERTEMP", "MOTOR_OVERTEMP", "ENGINE_OVERTEMP"}
)


@dataclass
class RewardState:
    last_lap_number: float = 0.0
    prev_lateral_m: float = 0.0
    lap_faults: set[str] = field(default_factory=set)
    thermal_faulted: bool = False


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

    if can_control and not off_track:
        if delta_s > 0.0:
            progress = weights.progress * min(delta_s, MAX_PROGRESS_M_PER_TICK)
            reward += progress
            components["progress"] = progress
        elif delta_s < 0.0:
            reverse = -weights.reverse * min(abs(delta_s), MAX_PROGRESS_M_PER_TICK)
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

    if bool(step_info.get("truncated_off_track_wander")):
        wander = -weights.off_track_wander
        reward += wander
        components["off_track_wander"] = wander

    if bool(step_info.get("truncated_max_steps")):
        target_laps = int(step_info.get("target_laps", 1))
        completed_laps = int(step_info.get("completed_laps", 0))
        if target_laps > 0 and completed_laps < target_laps:
            incomplete = -weights.incomplete_lap
            reward += incomplete
            components["incomplete_lap"] = incomplete

    is_ice = str(tick_values.get("powertrain_type", "ev")) == "ice"
    if is_ice:
        temp_c = float(tick_values.get("engine_temp_c", 25.0))
        derate_c = float(
            tick_values.get(
                "engine_temp_derate_c",
                step_info.get("engine_temp_derate_c", 100.0),
            )
        )
        fault_c = float(
            tick_values.get(
                "engine_temp_fault_c",
                step_info.get("engine_temp_fault_c", 120.0),
            )
        )
    else:
        temp_c = float(tick_values.get("motor_temp_c", 25.0))
        derate_c = float(
            tick_values.get(
                "controller_temp_derate_c",
                step_info.get("controller_temp_derate_c", 75.0),
            )
        )
        fault_c = float(
            tick_values.get(
                "controller_temp_fault_c",
                step_info.get("controller_temp_fault_c", 85.0),
            )
        )
    if temp_c > derate_c and weights.thermal > 0.0:
        span = max(fault_c - derate_c, 1.0)
        frac = min(max((temp_c - derate_c) / span, 0.0), 1.0)
        thermal = -weights.thermal * frac * dt_s
        reward += thermal
        components["thermal"] = thermal

    faults = {
        part.strip()
        for part in str(tick_values.get("active_faults", "")).split(",")
        if part.strip()
    }
    if faults & _BLOCKING_THERMAL_FAULTS and not state.thermal_faulted:
        thermal_fault = -weights.thermal_fault
        reward += thermal_fault
        components["thermal_fault"] = thermal_fault
        state.thermal_faulted = True

    lap_number = float(step_info.get("lap_number", 0.0))
    if lap_number > state.last_lap_number and state.last_lap_number >= 1.0:
        reward += weights.lap
        components["lap"] = weights.lap
    state.last_lap_number = lap_number
    state.prev_lateral_m = lateral
    return reward, state, components
