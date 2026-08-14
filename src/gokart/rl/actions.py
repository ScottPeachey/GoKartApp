"""Map policy outputs to simulator controls.

The policy has two axes in [-1, 1]:
- accel: positive is throttle, negative is brake
- steer: left/right
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


def encode_expert_action(throttle: float, brake: float, steering: float) -> np.ndarray:
    """Project plant controls into the policy action space."""
    accel = float(np.clip(throttle, 0.0, 1.0)) - float(np.clip(brake, 0.0, 1.0))
    return np.array(
        [float(np.clip(accel, -1.0, 1.0)), float(np.clip(steering, -1.0, 1.0))],
        dtype=np.float32,
    )
