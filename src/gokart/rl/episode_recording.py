"""Record complete RL episodes tick-by-tick."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import gymnasium as gym


def session_tick_row(env: gym.Env) -> dict[str, Any] | None:
    session = getattr(env.unwrapped, "session", None)
    if session is None:
        return None
    last_tick = session.state.last_tick
    if last_tick is None:
        return None
    return last_tick.to_row()


class EpisodeRecordingEnv(gym.Wrapper):
    """Buffer every sim tick and flush a full episode when it terminates."""

    def __init__(
        self,
        env: gym.Env,
        *,
        timestep_provider: Callable[[], int],
        on_episode_complete: Callable[..., None],
    ) -> None:
        super().__init__(env)
        self._timestep_provider = timestep_provider
        self._on_episode_complete = on_episode_complete
        self._episode_ticks: list[dict[str, Any]] = []
        self._episode_index = 0
        self._episode_reward = 0.0
        self._finalized = False

    def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):
        if not self._finalized:
            self._finalize_episode()
        self._finalized = False
        self._episode_ticks = []
        self._episode_reward = 0.0
        observation, info = self.env.reset(seed=seed, options=options)
        self._append_tick()
        return observation, info

    def step(self, action):
        observation, reward, terminated, truncated, info = self.env.step(action)
        self._episode_reward += float(reward)
        self._append_tick()
        if terminated or truncated:
            self._finalize_episode()
            self._finalized = True
        return observation, reward, terminated, truncated, info

    def _append_tick(self) -> None:
        inner = self.env.unwrapped
        rows = getattr(inner, "physics_tick_rows", None)
        if rows:
            self._episode_ticks.extend(rows)
            return
        row = session_tick_row(self.env)
        if row is not None:
            self._episode_ticks.append(row)

    def _finalize_episode(self) -> None:
        if not self._episode_ticks:
            return
        self._episode_index += 1
        self._on_episode_complete(
            list(self._episode_ticks),
            self._episode_index,
            episode_reward=self._episode_reward,
        )
        self._episode_ticks = []
        self._episode_reward = 0.0
