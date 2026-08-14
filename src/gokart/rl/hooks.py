"""Callbacks for live RL training progress and preview streaming."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class TrainingProgress:
    timesteps: int = 0
    total_timesteps: int = 0
    status: str = "idle"
    policy_key: str = ""
    best_lap_s: float | None = None
    clean_lap_rate: float = 0.0
    eval_history: list[float | None] = field(default_factory=list)
    last_episode_reward: float | None = None
    last_eval_lap_s: float | None = None
    preview_running: bool = False
    preview_session_id: str = ""
    preview_sessions: list[dict[str, Any]] = field(default_factory=list)
    previews_completed: int = 0
    test_running: bool = False
    tests_completed: int = 0
    last_test_session_id: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timesteps": self.timesteps,
            "total_timesteps": self.total_timesteps,
            "progress_pct": (
                100.0 * self.timesteps / self.total_timesteps
                if self.total_timesteps > 0
                else 0.0
            ),
            "status": self.status,
            "policy_key": self.policy_key,
            "best_lap_s": self.best_lap_s,
            "clean_lap_rate": self.clean_lap_rate,
            "eval_history": list(self.eval_history),
            "last_episode_reward": self.last_episode_reward,
            "last_eval_lap_s": self.last_eval_lap_s,
            "preview_running": self.preview_running,
            "preview_session_id": self.preview_session_id,
            "preview_sessions": list(self.preview_sessions),
            "previews_completed": self.previews_completed,
            "test_running": self.test_running,
            "tests_completed": self.tests_completed,
            "last_test_session_id": self.last_test_session_id,
            "error": self.error,
        }


class TrainingHooks(Protocol):
    def on_progress(self, progress: TrainingProgress) -> None: ...

    def on_preview_tick(self, row: dict[str, Any]) -> None: ...

    def should_stop(self) -> bool: ...

    def consume_test_request(self) -> bool: ...

    def start_preview_recording(self, *, timestep: int) -> str: ...

    def finish_preview_recording(self) -> None: ...

    def record_episode(
        self,
        *,
        ticks: list[dict[str, Any]],
        timestep: int,
        kind: str = "episode",
        episode_index: int = 0,
        episode_reward: float | None = None,
    ) -> str: ...


class NullTrainingHooks:
    """No-op hooks for CLI training."""

    def on_progress(self, progress: TrainingProgress) -> None:
        return

    def on_preview_tick(self, row: dict[str, Any]) -> None:
        return

    def should_stop(self) -> bool:
        return False

    def consume_test_request(self) -> bool:
        return False

    def start_preview_recording(self, *, timestep: int) -> str:
        return ""

    def finish_preview_recording(self) -> None:
        return

    def record_episode(
        self,
        *,
        ticks: list[dict[str, Any]],
        timestep: int,
        kind: str = "episode",
        episode_index: int = 0,
        episode_reward: float | None = None,
    ) -> str:
        return ""
