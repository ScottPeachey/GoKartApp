"""Load trained policies for inference."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from gokart.rl.actions import decode_rl_action
from gokart.rl.observations import OBS_DIM, build_observation
from gokart.rl.policy_key import PolicyIdentity
from gokart.rl.registry import load_manifest, model_path
from gokart.track.model import Track


class PolicyRunner:
    """Run a saved SB3 policy on observation vectors."""

    def __init__(self, model) -> None:
        self._model = model

    @classmethod
    def from_identity(cls, identity: PolicyIdentity, root: Path | None = None) -> PolicyRunner:
        path = model_path(identity, root=root)
        if not path.exists():
            raise FileNotFoundError(f"policy model not found: {path}")
        try:
            from stable_baselines3 import PPO
        except ImportError as exc:
            raise RuntimeError(
                "stable-baselines3 is required for learned driving. "
                "Install with: uv sync --group rl"
            ) from exc
        model = PPO.load(str(path))
        return cls(model)

    @classmethod
    def try_from_identity(
        cls, identity: PolicyIdentity, root: Path | None = None
    ) -> PolicyRunner | None:
        manifest = load_manifest(identity, root=root)
        if manifest is None or manifest.status not in {"ceiling_reached", "training"}:
            return None
        path = model_path(identity, root=root)
        if not path.exists():
            return None
        return cls.from_identity(identity, root=root)

    def predict(
        self,
        observation: np.ndarray,
        *,
        deterministic: bool = True,
    ) -> tuple[float, float, float]:
        action, _ = self._model.predict(observation.reshape(1, -1), deterministic=deterministic)
        return decode_rl_action(action)

    def predict_from_tick(
        self,
        *,
        tick_values: dict,
        step_info: dict,
        track: Track,
        target_laps: int,
        max_steps: int,
        step_index: int,
        deterministic: bool = True,
    ) -> tuple[float, float, float]:
        obs = build_observation(
            tick_values=tick_values,
            step_info=step_info,
            track=track,
            target_laps=target_laps,
            max_steps=max_steps,
            step_index=step_index,
        )
        return self.predict(obs, deterministic=deterministic)


def observation_dim() -> int:
    return OBS_DIM
