"""Gymnasium environment for track racing RL."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from gokart.rl.actions import ACTION_DIM, decode_rl_action
from gokart.rl.observations import OBS_DIM, build_observation
from gokart.rl.rewards import RewardState, compute_reward
from gokart.rl.training_setup import EnvRuntimeConfig, RlTrainingSetup, default_training_setup
from gokart.safety.types import SafetyState
from gokart.sim.session import ControlSource, SessionConfig, SimulationSession
from gokart.track.model import Track

# Auto-boot (self-test + precharge) is ~250 ticks at 100 Hz. Keep it out of
# policy rollouts so the agent does not learn from a held brake pedal.
BOOT_STEP_ALLOWANCE = 400


class TrackRacingEnv(gym.Env):
    """Gym environment stepping the real kart simulation."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        *,
        session_config: SessionConfig,
        setup: RlTrainingSetup | None = None,
        render_mode: str | None = None,
        max_drive_steps: int | None = None,
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
        self._off_track_steps = 0
        self._max_drive_steps = (
            max_drive_steps if max_drive_steps is not None else session_config.max_steps
        )
        self._drive_steps = 0
        self._last_policy_controls = (0.0, 0.0, 0.0)

        self.action_space = spaces.Box(
            low=np.full(ACTION_DIM, -1.0, dtype=np.float32),
            high=np.full(ACTION_DIM, 1.0, dtype=np.float32),
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
        self._off_track_steps = 0
        self._drive_steps = 0
        self._last_policy_controls = (0.0, 0.0, 0.0)
        step_result = self.session.reset()
        boot_steps = 0
        while step_result.safety_state != SafetyState.DRIVING and boot_steps < BOOT_STEP_ALLOWANCE:
            step_result = self.session.step(action=None)
            boot_steps += 1
        # Controls are chosen from the previous safety state, so the first
        # DRIVING tick still carries the precharge brake. Step once more.
        if step_result.safety_state == SafetyState.DRIVING:
            step_result = self.session.step(action=(0.0, 0.0, 0.0))
        obs = self._obs_from_step(step_result.tick.values, step_result.info)
        self._last_obs = obs
        return obs, {"safety_state": step_result.safety_state.value}

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        vehicle = self.session.state.vehicle_state
        speed_mps = float(vehicle.speed_mps) if vehicle else 0.0
        action_tuple = decode_rl_action(
            action,
            speed_mps=speed_mps,
            action_config=self.setup.action,
        )
        self._last_policy_controls = action_tuple
        step_result = self.session.step(action=action_tuple)
        env_cfg = self._env_cfg
        delta_s = float(step_result.info.get("delta_track_s_m", 0.0))
        driving = step_result.safety_state.value == "DRIVING"
        lateral_offset_m = abs(float(step_result.info.get("lateral_offset_m", 0.0)))
        track_width_m = max(float(step_result.info.get("track_width_m", 10.0)), 1.0)
        off_track_now = lateral_offset_m > track_width_m * 0.5
        no_forward = delta_s < env_cfg.stagnant_delta_s
        stagnant_now = driving and env_cfg.max_stagnant_steps > 0 and no_forward
        if stagnant_now and self._stagnant_steps + 1 >= env_cfg.max_stagnant_steps:
            step_result.info["truncated_stagnant"] = True
        if (
            not env_cfg.terminate_on_off_track
            and env_cfg.max_off_track_steps > 0
            and off_track_now
            and self._off_track_steps + 1 >= env_cfg.max_off_track_steps
        ):
            step_result.info["truncated_off_track_wander"] = True
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
        if stagnant_now:
            self._stagnant_steps += 1
        else:
            self._stagnant_steps = 0
        if off_track_now:
            self._off_track_steps += 1
        else:
            self._off_track_steps = 0
        self._drive_steps += 1
        truncated = step_result.truncated
        if self._max_drive_steps > 0:
            truncated = truncated or self._drive_steps >= self._max_drive_steps
        if env_cfg.max_stagnant_steps > 0:
            truncated = truncated or self._stagnant_steps >= env_cfg.max_stagnant_steps
        if env_cfg.max_off_track_steps > 0:
            truncated = truncated or self._off_track_steps >= env_cfg.max_off_track_steps
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
        throttle, brake, steering = self._last_policy_controls
        values = dict(tick_values)
        values["throttle"] = throttle
        values["brake"] = brake
        values["steering"] = steering
        return build_observation(
            tick_values=values,
            step_info=step_info,
            track=self.session_config.track,
            target_laps=self.session_config.target_laps,
            max_steps=self._max_drive_steps,
            step_index=self._drive_steps,
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
        resolved_setup = replace(resolved_setup, objective=objective)
    env_cfg = resolved_setup.env
    drive_steps = max_steps if max_steps is not None else env_cfg.max_steps
    config = SessionConfig(
        vehicle_name=vehicle_name,
        vehicle_version=vehicle_version,
        track=track,
        mode_name=drive_mode,
        profile_name=driver_profile,
        control_source=ControlSource.RL,
        target_laps=target_laps,
        auto_boot=True,
        max_steps=drive_steps + BOOT_STEP_ALLOWANCE,
        terminate_on_off_track=env_cfg.terminate_on_off_track,
    )
    return TrackRacingEnv(
        session_config=config,
        setup=resolved_setup,
        max_drive_steps=drive_steps,
    )
