"""Gymnasium environment for track racing RL."""

from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from gokart.rl.actions import decode_rl_action
from gokart.rl.observations import OBS_DIM, build_observation
from gokart.rl.rewards import RewardState, compute_reward
from gokart.rl.training_setup import EnvRuntimeConfig, RlTrainingSetup, default_training_setup
from gokart.sim.session import ControlSource, SessionConfig, SimulationSession
from gokart.track.model import Track


class TrackRacingEnv(gym.Env):
    """Gym environment stepping the real kart simulation."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        *,
        session_config: SessionConfig,
        setup: RlTrainingSetup | None = None,
        render_mode: str | None = None,
    ) -> None:
        super().__init__()
        self.session_config = session_config
        self.setup = setup or default_training_setup()
        self.objective = self.setup.objective
        self.render_mode = render_mode
        self.session = SimulationSession(session_config)
        self.weights = self.setup.resolved_rewards()
        self._reward_state = RewardState()
        self._last_obs = np.zeros(OBS_DIM, dtype=np.float32)
        self._stagnant_steps = 0

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

    @property
    def _env_cfg(self) -> EnvRuntimeConfig:
        return self.setup.env

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        self._reward_state = RewardState()
        self._stagnant_steps = 0
        step_result = self.session.reset()
        obs = self._obs_from_step(step_result.tick.values, step_result.info)
        self._last_obs = obs
        return obs, {"safety_state": step_result.safety_state.value}

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        speed_mps = float(self.session.state.vehicle_state.speed_mps) if self.session.state.vehicle_state else 0.0
        action_tuple = decode_rl_action(
            action,
            speed_mps=speed_mps,
            action_config=self.setup.action,
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
        env_cfg = self._env_cfg
        speed = float(step_result.tick.values.get("speed_mps", 0.0))
        delta_s = float(step_result.info.get("delta_track_s_m", 0.0))
        driving = step_result.safety_state.value == "DRIVING"
        if (
            driving
            and env_cfg.max_stagnant_steps > 0
            and speed < env_cfg.stagnant_speed_mps
            and delta_s < env_cfg.stagnant_delta_s
        ):
            self._stagnant_steps += 1
        else:
            self._stagnant_steps = 0
        truncated = step_result.truncated
        if env_cfg.max_stagnant_steps > 0:
            truncated = truncated or self._stagnant_steps >= env_cfg.max_stagnant_steps
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
            truncated,
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
    objective: str = "god",
    target_laps: int = 3,
    max_steps: int | None = None,
    setup: RlTrainingSetup | None = None,
) -> TrackRacingEnv:
    resolved_setup = setup or default_training_setup()
    if objective and resolved_setup.objective != objective:
        resolved_setup = RlTrainingSetup(
            objective=objective,
            action=resolved_setup.action,
            env=resolved_setup.env,
            ppo=resolved_setup.ppo,
            rewards=resolved_setup.rewards,
        )
    env_cfg = resolved_setup.env
    config = SessionConfig(
        vehicle_name=vehicle_name,
        vehicle_version=vehicle_version,
        track=track,
        mode_name=drive_mode,
        profile_name=driver_profile,
        control_source=ControlSource.RL,
        target_laps=target_laps,
        auto_boot=True,
        max_steps=max_steps if max_steps is not None else env_cfg.max_steps,
        terminate_on_off_track=env_cfg.terminate_on_off_track,
    )
    return TrackRacingEnv(session_config=config, setup=resolved_setup)
