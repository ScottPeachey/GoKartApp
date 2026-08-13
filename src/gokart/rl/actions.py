"""Map normalized RL policy outputs to simulator controls."""

from __future__ import annotations

import numpy as np

from gokart.rl.training_setup import ActionConfig

DEFAULT_ACTION_CONFIG = ActionConfig()


def decode_rl_action(
    action: np.ndarray | tuple[float, float, float],
    *,
    speed_mps: float = 0.0,
    action_config: ActionConfig | None = None,
) -> tuple[float, float, float]:
    """Convert policy actions into throttle, brake, and steering commands."""
    cfg = action_config or DEFAULT_ACTION_CONFIG
    values = np.asarray(action, dtype=np.float32).reshape(-1)
    raw_throttle = float(np.clip(values[0], 0.0, 1.0))
    brake = float(np.clip(values[1], 0.0, 1.0))
    steering = float(np.clip(values[2], -1.0, 1.0))

    if brake > cfg.brake_cutoff:
        throttle = 0.0
    elif raw_throttle <= 0.0:
        throttle = 0.0
    elif speed_mps < cfg.standing_start_speed_mps:
        throttle = cfg.throttle_breakaway + (1.0 - cfg.throttle_breakaway) * raw_throttle
    else:
        throttle = raw_throttle

    return throttle, brake, steering
