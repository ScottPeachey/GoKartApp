"""Map policy outputs to simulator controls.

The policy has two axes in [-1, 1]:
- accel: positive is throttle, negative is brake
- steer: left/right

Commands are slewed on those axes first, then turned into pedals.
That way throttle and brake cannot be on together, and 100 Hz noise
cannot dump the throttle every other tick.
"""

from __future__ import annotations

import numpy as np

from gokart.rl.training_setup import ActionConfig

ACTION_DIM = 2
DEFAULT_ACTION_CONFIG = ActionConfig()


def parse_rl_action(action: np.ndarray | tuple[float, ...]) -> tuple[float, float]:
    values = np.asarray(action, dtype=np.float32).reshape(-1)
    accel = float(np.clip(values[0], -1.0, 1.0))
    steering = float(np.clip(values[1] if values.size > 1 else 0.0, -1.0, 1.0))
    return accel, steering


def decode_rl_action(
    action: np.ndarray | tuple[float, ...],
    *,
    speed_mps: float = 0.0,
    action_config: ActionConfig | None = None,
) -> tuple[float, float, float]:
    """Convert policy (accel, steer) into throttle, brake, and steering."""
    cfg = action_config or DEFAULT_ACTION_CONFIG
    accel, steering = parse_rl_action(action)
    throttle, brake = _pedals_from_accel(accel, speed_mps=speed_mps, cfg=cfg)
    return throttle, brake, steering


def realize_rl_action(
    action: np.ndarray | tuple[float, ...],
    *,
    speed_mps: float,
    current_command: tuple[float, float],
    dt_s: float,
    action_config: ActionConfig | None = None,
) -> tuple[tuple[float, float, float], tuple[float, float]]:
    """Slew the command, then map to plant pedals. Returns (controls, command)."""
    cfg = action_config or DEFAULT_ACTION_CONFIG
    raw_accel, raw_steer = parse_rl_action(action)
    accel = _slew(
        current_command[0],
        raw_accel,
        rate_per_s=cfg.accel_slew_per_s,
        dt_s=dt_s,
        low=-1.0,
        high=1.0,
    )
    steering = _slew(
        current_command[1],
        raw_steer,
        rate_per_s=cfg.steer_slew_per_s,
        dt_s=dt_s,
        low=-1.0,
        high=1.0,
    )
    throttle, brake = _pedals_from_accel(accel, speed_mps=speed_mps, cfg=cfg)
    return (throttle, brake, steering), (accel, steering)


def encode_expert_action(throttle: float, brake: float, steering: float) -> np.ndarray:
    """Project plant controls into the policy action space."""
    accel = float(np.clip(throttle, 0.0, 1.0)) - float(np.clip(brake, 0.0, 1.0))
    return np.array(
        [float(np.clip(accel, -1.0, 1.0)), float(np.clip(steering, -1.0, 1.0))],
        dtype=np.float32,
    )


def _pedals_from_accel(accel: float, *, speed_mps: float, cfg: ActionConfig) -> tuple[float, float]:
    deadzone = max(0.0, float(cfg.brake_deadzone))
    at_rest = speed_mps < cfg.standing_start_speed_mps

    if at_rest and accel > -deadzone:
        throttle = cfg.throttle_breakaway + (1.0 - cfg.throttle_breakaway) * max(accel, 0.0)
        return float(np.clip(throttle, 0.0, 1.0)), 0.0

    if accel >= deadzone:
        return float(np.clip(accel, 0.0, 1.0)), 0.0
    if accel <= -deadzone:
        return 0.0, float(np.clip(-accel, 0.0, 1.0))
    return 0.0, 0.0


def _slew(
    current: float,
    target: float,
    *,
    rate_per_s: float,
    dt_s: float,
    low: float,
    high: float,
) -> float:
    if dt_s <= 0.0 or rate_per_s <= 0.0:
        return float(np.clip(target, low, high))
    delta = max(-rate_per_s * dt_s, min(rate_per_s * dt_s, target - current))
    return float(np.clip(current + delta, low, high))
