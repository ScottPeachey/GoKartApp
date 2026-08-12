"""Gymnasium environment for track racing RL."""

from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from gokart.rl.observations import OBS_DIM, build_observation
from gokart.rl.rewards import RewardState, compute_reward, reward_preset
from gokart.sim.session import ControlSource, SessionConfig, SimulationSession
from gokart.track.model import Track


class TrackRacingEnv(gym.Env):
    """Gym environment stepping the real kart simulation."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        *,
        session_config: SessionConfig,
        objective: str = "god",
        render_mode: str | None = None,
    ) -> None:
        super().__init__()
        self.session_config = session_config
        self.objective = objective
        self.render_mode = render_mode
        self.session = SimulationSession(session_config)
        self.weights = reward_preset(objective)
        self._reward_state = RewardState()
        self._last_obs = np.zeros(OBS_DIM, dtype=np.float32)

        self.action_space = spaces.Box(
            low=np.array([0.0, 0.0, -1.0], dtype=np.float32),
            high=np.array([1.0, 1.0, 1.0], dtype=np.float32),
            dtype=np.float32,
        )
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(OBS_DIM,),
            dtype=np.float32,
        )

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        self._reward_state = RewardState()
        step_result = self.session.reset()
        obs = self._obs_from_step(step_result.tick.values, step_result.info)
        self._last_obs = obs
        return obs, {"safety_state": step_result.safety_state.value}

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        action_tuple = (
            float(np.clip(action[0], 0.0, 1.0)),
            float(np.clip(action[1], 0.0, 1.0)),
            float(np.clip(action[2], -1.0, 1.0)),
        )
        step_result = self.session.step(action=action_tuple)
        reward, self._reward_state, components = compute_reward(
            tick_values=step_result.tick.values,
            step_info=step_result.info,
            weights=self.weights,
            dt_s=self.session_config.dt_s,
            state=self._reward_state,
            objective=self.objective,
        )
        obs = self._obs_from_step(step_result.tick.values, step_result.info)
        self._last_obs = obs
        info = {
            **step_result.info,
            "reward_components": components,
            "safety_state": step_result.safety_state.value,
            "active_faults": step_result.tick.values.get("active_faults", ""),
        }
        return (
            obs,
            reward,
            step_result.terminated,
            step_result.truncated,
            info,
        )

    def _obs_from_step(self, tick_values: dict[str, Any], step_info: dict[str, Any]) -> np.ndarray:
        return build_observation(
            tick_values=tick_values,
            step_info=step_info,
            track=self.session_config.track,
            target_laps=self.session_config.target_laps,
            max_steps=self.session_config.max_steps,
            step_index=self.session.state.step_index,
        )


def make_env(
    *,
    vehicle_name: str,
    vehicle_version: str,
    track: Track,
    drive_mode: str,
    driver_profile: str,
    objective: str,
    target_laps: int = 3,
    max_steps: int = 12_000,
) -> TrackRacingEnv:
    config = SessionConfig(
        vehicle_name=vehicle_name,
        vehicle_version=vehicle_version,
        track=track,
        mode_name=drive_mode,
        profile_name=driver_profile,
        control_source=ControlSource.RL,
        target_laps=target_laps,
        auto_boot=True,
        max_steps=max_steps,
    )
    return TrackRacingEnv(session_config=config, objective=objective)
