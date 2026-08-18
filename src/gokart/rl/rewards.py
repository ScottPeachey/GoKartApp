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
    progress: float = 0.5
    reverse: float = 1.2
    off_track: float = 2.0
    wall: float = 12.0
    stagnant_terminal: float = 8.0
    off_track_wander: float = 10.0
    early_exit: float = 1.0
    lap: float = 60.0
    thermal: float = 0.5
    thermal_fault: float = 6.0


GOD_WEIGHTS = RewardWeights()
ENDURANCE_WEIGHTS = RewardWeights(
    time=0.7,
    progress=0.4,
    wall=10.0,
    stagnant_terminal=6.0,
    off_track_wander=8.0,
    early_exit=0.7,
    lap=70.0,
    thermal=0.7,
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


def _failure_exit_penalties(
    *,
    step_info: dict[str, Any],
    weights: RewardWeights,
    dt_s: float,
) -> dict[str, float]:
    """Penalise failed early endings so they cannot beat a full slow episode."""
    if step_info.get("truncated_max_steps"):
        return {}

    failed = bool(step_info.get("terminated_off_track")) or bool(
        step_info.get("truncated_stagnant")
    ) or bool(step_info.get("truncated_off_track_wander"))
    if not failed:
        return {}

    components: dict[str, float] = {}
    max_steps = int(step_info.get("max_drive_steps", 0))
    step_index = int(step_info.get("drive_step_index", 0))
    if weights.early_exit > 0.0 and max_steps > 0 and step_index > 0:
        remaining_s = max(0.0, (max_steps - step_index) * dt_s)
        if remaining_s > 0.0:
            early_exit = -weights.early_exit * remaining_s
            components["early_exit"] = early_exit

    if bool(step_info.get("truncated_off_track_wander")) and weights.off_track_wander > 0.0:
        components["off_track_wander"] = -weights.off_track_wander

    return components


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

    for name, value in _failure_exit_penalties(
        step_info=step_info,
        weights=weights,
        dt_s=dt_s,
    ).items():
        reward += value
        components[name] = value

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
