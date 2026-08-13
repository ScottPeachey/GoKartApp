"""Map normalized RL policy outputs to simulator controls."""

from __future__ import annotations

import numpy as np

# Standing-start assist only applies when the policy requests throttle while
# nearly stopped. Zero throttle must remain zero so the agent can coast.
THROTTLE_BREAKAWAY = 0.25
STANDING_START_SPEED_MPS = 0.15
BRAKE_CUTOFF = 0.85


def decode_rl_action(
    action: np.ndarray | tuple[float, float, float],
    *,
    speed_mps: float = 0.0,
) -> tuple[float, float, float]:
    """Convert policy actions into throttle, brake, and steering commands."""
    values = np.asarray(action, dtype=np.float32).reshape(-1)
    raw_throttle = float(np.clip(values[0], 0.0, 1.0))
    brake = float(np.clip(values[1], 0.0, 1.0))
    steering = float(np.clip(values[2], -1.0, 1.0))

    if brake > BRAKE_CUTOFF:
        throttle = 0.0
    elif raw_throttle <= 0.0:
        throttle = 0.0
    elif speed_mps < STANDING_START_SPEED_MPS:
        throttle = THROTTLE_BREAKAWAY + (1.0 - THROTTLE_BREAKAWAY) * raw_throttle
    else:
        throttle = raw_throttle

    return throttle, brake, steering
