"""Map normalized RL policy outputs to simulator controls."""

from __future__ import annotations

import numpy as np

# Standing-start tests on the kart model need roughly this much throttle before
# the rear tyres break static friction and the vehicle begins to roll.
THROTTLE_BREAKAWAY = 0.25


def decode_rl_action(action: np.ndarray | tuple[float, float, float]) -> tuple[float, float, float]:
    """Convert policy actions into throttle, brake, and steering commands."""
    values = np.asarray(action, dtype=np.float32).reshape(-1)
    raw_throttle = float(np.clip(values[0], 0.0, 1.0))
    brake = float(np.clip(values[1], 0.0, 1.0))
    steering = float(np.clip(values[2], -1.0, 1.0))

    if brake > 0.5:
        throttle = 0.0
    else:
        throttle = THROTTLE_BREAKAWAY + (1.0 - THROTTLE_BREAKAWAY) * raw_throttle

    return throttle, brake, steering
