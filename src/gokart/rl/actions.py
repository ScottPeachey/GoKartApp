"""Map policy outputs to simulator controls.

The policy has two axes in [-1, 1]:
- accel: positive is throttle, negative is brake
- steer: left/right

Decoded commands are then rate-limited so the plant cannot chatter
faster than a driver / actuator could move.
"""

from __future__ import annotations

import numpy as np

from gokart.rl.training_setup import ActionConfig

ACTION_DIM = 2
DEFAULT_ACTION_CONFIG = ActionConfig()


def decode_rl_action(
    action: np.ndarray | tuple[float, ...],
    *,
    speed_mps: float = 0.0,
    action_config: ActionConfig | None = None,
) -> tuple[float, float, float]:
    """Convert policy (accel, steer) into throttle, brake, and steering."""
    cfg = action_config or DEFAULT_ACTION_CONFIG
    values = np.asarray(action, dtype=np.float32).reshape(-1)
    accel = float(np.clip(values[0], -1.0, 1.0))
    steering = float(np.clip(values[1] if values.size > 1 else 0.0, -1.0, 1.0))

    if accel >= 0.0:
        brake = 0.0
        throttle = accel
        if 0.0 < throttle and speed_mps < cfg.standing_start_speed_mps:
            throttle = cfg.throttle_breakaway + (1.0 - cfg.throttle_breakaway) * throttle
    else:
        throttle = 0.0
        brake = -accel

    return throttle, brake, steering


def apply_actuator_slew(
    target: tuple[float, float, float],
    current: tuple[float, float, float],
    *,
    dt_s: float,
    action_config: ActionConfig | None = None,
) -> tuple[float, float, float]:
    """Move plant controls toward the policy command at realistic rates."""
    cfg = action_config or DEFAULT_ACTION_CONFIG
    throttle = _slew_asymmetric(
        current[0],
        target[0],
        up_rate_per_s=cfg.throttle_slew_up_per_s,
        down_rate_per_s=cfg.throttle_slew_down_per_s,
        dt_s=dt_s,
        low=0.0,
        high=1.0,
    )
    brake = _slew(
        current[1],
        target[1],
        rate_per_s=cfg.brake_slew_per_s,
        dt_s=dt_s,
        low=0.0,
        high=1.0,
    )
    steering = _slew(
        current[2],
        target[2],
        rate_per_s=cfg.steer_slew_per_s,
        dt_s=dt_s,
        low=-1.0,
        high=1.0,
    )
    return throttle, brake, steering


def encode_expert_action(throttle: float, brake: float, steering: float) -> np.ndarray:
    """Project plant controls into the policy action space."""
    accel = float(np.clip(throttle, 0.0, 1.0)) - float(np.clip(brake, 0.0, 1.0))
    return np.array(
        [float(np.clip(accel, -1.0, 1.0)), float(np.clip(steering, -1.0, 1.0))],
        dtype=np.float32,
    )


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


def _slew_asymmetric(
    current: float,
    target: float,
    *,
    up_rate_per_s: float,
    down_rate_per_s: float,
    dt_s: float,
    low: float,
    high: float,
) -> float:
    rate = up_rate_per_s if target > current else down_rate_per_s
    return _slew(current, target, rate_per_s=rate, dt_s=dt_s, low=low, high=high)
