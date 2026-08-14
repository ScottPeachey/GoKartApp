"""Fault-aware reward shaping for RL training."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gokart.safety.faults import FAULT_REGISTRY
from gokart.safety.types import FaultSeverity
from gokart.track.lap import along_track_delta


@dataclass(frozen=True)
class RewardWeights:
    progress: float = 0.5
    centerline: float = 0.12
    heading: float = 0.06
    speed: float = 0.06
    standstill: float = 0.35
    throttle_go: float = 0.55
    low_speed_steer: float = 0.08
    lap_bonus: float = 25.0
    fault_block: float = 80.0
    fault_derate: float = 12.0
    off_track_rate: float = 4.0
    off_track_lateral_cap: float = 2.0
    off_track_progress: float = 0.0
    recover_track: float = 0.8
    heading_off_track: float = 0.12
    reverse: float = 0.4
    shortcut: float = 2.0
    max_progress_delta_m: float = 1.5
    off_track_terminal: float = 80.0
    wall_speed: float = 1.0
    wander_terminal: float = 8.0
    stagnant_terminal: float = 10.0
    battery_margin: float = 0.08
    motor_margin: float = 0.05
    soc_margin: float = 0.1
    jerk: float = 0.02
    throttle_brake_overlap: float = 1.5
    time_penalty: float = 0.01


GOD_WEIGHTS = RewardWeights()
ENDURANCE_WEIGHTS = RewardWeights(
    progress=0.22,
    centerline=0.1,
    heading=0.05,
    speed=0.03,
    lap_bonus=35.0,
    soc_margin=0.25,
    time_penalty=0.015,
)


@dataclass
class RewardState:
    prev_throttle: float = 0.0
    prev_brake: float = 0.0
    prev_steering: float = 0.0
    lap_faults: set[str] = field(default_factory=set)
    off_track_time_s: float = 0.0
    last_lap_number: float = 0.0
    prev_lateral_m: float = 0.0
    best_s_m: float | None = None
    was_off_track: bool = False


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
    objective: str,
    endurance_soc_floor: float = 0.15,
) -> tuple[float, RewardState, dict[str, float]]:
    reward = 0.0
    components: dict[str, float] = {}

    active_faults = _parse_faults(str(tick_values.get("active_faults", "")))
    blocking = _blocking_fault_names(active_faults)
    derate = _derate_fault_names(active_faults)
    lateral = abs(float(step_info.get("lateral_offset_m", 0.0)))
    track_width = max(float(step_info.get("track_width_m", 10.0)), 1.0)
    half_width = track_width * 0.5
    lateral_ratio = lateral / max(half_width, 0.1)
    off_track = lateral_ratio > 1.0
    speed = float(tick_values.get("speed_mps", 0.0))
    max_speed = max(float(tick_values.get("max_speed_mps", 12.5)), 0.1)
    throttle = float(tick_values.get("throttle", 0.0))
    brake = float(tick_values.get("brake", 0.0))
    steering = float(tick_values.get("steering", 0.0))
    if off_track:
        state.off_track_time_s += dt_s

    safety_state = str(tick_values.get("safety_state", "DRIVING"))
    can_control = safety_state == "DRIVING"

    delta_s = float(step_info.get("delta_track_s_m", 0.0))
    track_s = float(step_info.get("track_s_m", 0.0))
    track_length = float(step_info.get("track_length_m", 0.0))
    heading_error_deg = abs(float(step_info.get("heading_error_deg", 0.0)))
    max_progress_delta = max(weights.max_progress_delta_m, 0.05)
    shortcut_jump = abs(delta_s) > max_progress_delta
    if state.best_s_m is None:
        state.best_s_m = track_s
    frontier_gain = along_track_delta(track_s, state.best_s_m, track_length)
    behind_frontier = frontier_gain < -1e-6
    if can_control and not blocking:
        if shortcut_jump:
            shortcut_penalty = -weights.shortcut * min(abs(delta_s) / max_progress_delta, 8.0)
            reward += shortcut_penalty
            components["shortcut"] = shortcut_penalty
        elif delta_s < 0.0:
            reverse_scale = 1.0 if off_track else 1.75
            reverse_penalty = -weights.reverse * reverse_scale * abs(delta_s)
            reward += reverse_penalty
            components["reverse"] = reverse_penalty
        elif delta_s > 0.0 and not off_track:
            # New ground only. Catching up to the leave-point from behind
            # must not pay progress.
            if not behind_frontier:
                progress = weights.progress * delta_s
                reward += progress
                components["progress"] = progress
        elif delta_s > 0.0 and off_track and weights.off_track_progress > 0.0:
            progress = weights.progress * weights.off_track_progress * delta_s
            reward += progress
            components["progress"] = progress

    if can_control:
        reward -= weights.time_penalty * dt_s
        components["time"] = -weights.time_penalty * dt_s

    motion = min(max(speed / 2.0, 0.0), 1.0)
    normalized_lateral = min(lateral_ratio, 1.0)
    if can_control and not off_track and not blocking:
        centerline_reward = weights.centerline * (1.0 - normalized_lateral) * motion * dt_s
        reward += centerline_reward
        components["centerline"] = centerline_reward

        heading_reward = weights.heading * max(0.0, 1.0 - heading_error_deg / 90.0) * motion * dt_s
        reward += heading_reward
        components["heading"] = heading_reward

        if speed > 0.05:
            speed_reward = weights.speed * (speed / max_speed) * dt_s
            reward += speed_reward
            components["speed"] = speed_reward

    if can_control and not blocking:
        if speed < 0.2:
            standstill_penalty = -weights.standstill * dt_s
            reward += standstill_penalty
            components["standstill"] = standstill_penalty
            if throttle > 0.05 and not off_track:
                throttle_go = weights.throttle_go * throttle * dt_s
                reward += throttle_go
                components["throttle_go"] = throttle_go

        if speed < 1.0:
            steer_penalty = -weights.low_speed_steer * abs(steering) * dt_s
            reward += steer_penalty
            components["low_speed_steer"] = steer_penalty

    if off_track:
        penalty_lateral = min(max(lateral_ratio, 1.0), max(weights.off_track_lateral_cap, 1.0))
        off_penalty = -weights.off_track_rate * penalty_lateral * dt_s
        reward += off_penalty
        components["off_track"] = off_penalty
        hit_wall = bool(step_info.get("terminated_off_track"))
        if not hit_wall:
            if can_control and lateral + 1e-6 < state.prev_lateral_m:
                recover = weights.recover_track * (state.prev_lateral_m - lateral)
                reward += recover
                components["recover_track"] = recover
            elif can_control and lateral > state.prev_lateral_m + 1e-6:
                depart = -weights.recover_track * (lateral - state.prev_lateral_m)
                reward += depart
                components["depart_track"] = depart
            if can_control and speed > 0.3:
                heading_recover = (
                    weights.heading_off_track
                    * max(0.0, 1.0 - heading_error_deg / 90.0)
                    * motion
                    * dt_s
                )
                reward += heading_recover
                components["heading_off_track"] = heading_recover
                if heading_error_deg > 90.0:
                    wrong_way = -weights.heading_off_track * motion * dt_s
                    reward += wrong_way
                    components["wrong_way"] = wrong_way
        if bool(step_info.get("truncated_off_track_wander")):
            wander_penalty = -weights.wander_terminal
            reward += wander_penalty
            components["wander_terminal"] = wander_penalty

    if bool(step_info.get("terminated_off_track")):
        impact = 1.0 + max(weights.wall_speed, 0.0) * min(max(speed / max_speed, 0.0), 1.5)
        wall_penalty = -weights.off_track_terminal * impact
        reward += wall_penalty
        components["wall_hit"] = wall_penalty
        components["off_track_terminal"] = wall_penalty

    if bool(step_info.get("truncated_stagnant")):
        stagnant_penalty = -weights.stagnant_terminal
        reward += stagnant_penalty
        components["stagnant_terminal"] = stagnant_penalty

    battery_temp = float(tick_values.get("battery_temp_c", 25.0))
    battery_derate = float(step_info.get("battery_temp_derate_c", 50.0))
    battery_fault = float(step_info.get("battery_temp_fault_c", 60.0))
    motor_temp = float(tick_values.get("motor_temp_c", 25.0))
    soc = float(tick_values.get("soc", 1.0))

    batt_penalty = _heat_proximity_penalty(
        battery_temp, battery_derate, battery_fault, weights.battery_margin
    )
    if batt_penalty != 0.0:
        reward += batt_penalty
        components["battery_margin"] = batt_penalty

    motor_penalty = _heat_proximity_penalty(
        motor_temp, battery_derate, battery_fault, weights.motor_margin
    )
    if motor_penalty != 0.0:
        reward += motor_penalty
        components["motor_margin"] = motor_penalty

    if objective == "endurance" and soc < endurance_soc_floor:
        soc_penalty = -weights.soc_margin * (endurance_soc_floor - soc)
        reward += soc_penalty
        components["soc"] = soc_penalty

    jerk = (
        abs(throttle - state.prev_throttle)
        + abs(brake - state.prev_brake)
        + abs(steering - state.prev_steering)
    )
    jerk_penalty = -weights.jerk * jerk
    reward += jerk_penalty
    components["jerk"] = jerk_penalty

    if throttle > 0.12 and brake > 0.12:
        overlap = -weights.throttle_brake_overlap * min(throttle, brake)
        reward += overlap
        components["throttle_brake"] = overlap

    if derate:
        derate_penalty = -weights.fault_derate * len(derate)
        reward += derate_penalty
        components["derate"] = derate_penalty
        state.lap_faults.update(derate)

    if blocking:
        block_penalty = -weights.fault_block * len(blocking)
        reward += block_penalty
        components["blocking"] = block_penalty
        state.lap_faults.update(blocking)

    lap_number = float(step_info.get("lap_number", 0.0))
    if lap_number > state.last_lap_number and state.last_lap_number > 0:
        lap_time = float(step_info.get("lap_time_s", 0.0))
        off_track_ratio = state.off_track_time_s / max(lap_time, 0.1)
        if not state.lap_faults and off_track_ratio < 0.02:
            reward += weights.lap_bonus
            components["lap_bonus"] = weights.lap_bonus
        state.lap_faults.clear()
        state.off_track_time_s = 0.0
    state.last_lap_number = lap_number
    state.prev_lateral_m = lateral
    if shortcut_jump and not off_track and frontier_gain > 0.0:
        state.best_s_m = track_s
    elif not off_track and delta_s > 0.0 and not shortcut_jump and not behind_frontier:
        state.best_s_m = track_s
    state.was_off_track = off_track

    state.prev_throttle = throttle
    state.prev_brake = brake
    state.prev_steering = steering
    return reward, state, components


def _heat_proximity_penalty(temp_c: float, derate_c: float, fault_c: float, weight: float) -> float:
    """Penalize only when temperature approaches derate; never reward being cool."""
    span = max(fault_c - derate_c, 1.0)
    start = derate_c - span
    if temp_c <= start:
        return 0.0
    proximity = min(max((temp_c - start) / span, 0.0), 1.0)
    return -weight * proximity


def _parse_faults(raw: str) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _blocking_fault_names(faults: list[str]) -> list[str]:
    blocking: list[str] = []
    for name in faults:
        try:
            from gokart.safety.types import FaultId

            fault_id = FaultId(name)
            severity = FAULT_REGISTRY[fault_id].severity
            if severity in {FaultSeverity.FAULT, FaultSeverity.CRITICAL}:
                blocking.append(name)
        except ValueError:
            continue
    return blocking


def _derate_fault_names(faults: list[str]) -> list[str]:
    derate: list[str] = []
    for name in faults:
        try:
            from gokart.safety.types import FaultId

            fault_id = FaultId(name)
            if FAULT_REGISTRY[fault_id].severity == FaultSeverity.DERATE:
                derate.append(name)
        except ValueError:
            continue
    return derate
