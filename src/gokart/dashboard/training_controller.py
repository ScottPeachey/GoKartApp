"""Background RL training with live preview and metrics for the dashboard."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from gokart.rl.hooks import TrainingProgress, TrainingHooks
from gokart.rl.trainer import TrainingConfig, train_policy
from gokart.telemetry.bus import TelemetryBus
from gokart.telemetry.channels import validate_sample_row


@dataclass
class TrainingRunRequest:
    vehicle_name: str
    vehicle_version: str
    track_id: str
    drive_mode: str = "default"
    driver_profile: str = "owner"
    objective: str = "god"
    target_laps: int = 3
    total_timesteps: int = 50_000
    preview_freq: int = 10_000
    seed: int = 0


@dataclass
class TrainingControllerStatus:
    running: bool = False
    progress: TrainingProgress = field(default_factory=TrainingProgress)
    metrics_seq: int = 0


class TrainingController:
    def __init__(self, *, bus: TelemetryBus) -> None:
        self.bus = bus
        self._lock = threading.Lock()
        self._stop_requested = False
        self._thread: threading.Thread | None = None
        self.status = TrainingControllerStatus()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            payload = self.status.progress.to_dict()
            payload["running"] = self.status.running
            payload["seq"] = self.status.metrics_seq
            return payload

    def poll_metrics(self, since_seq: int) -> dict[str, Any] | None:
        with self._lock:
            if self.status.metrics_seq <= since_seq:
                return None
            payload = self.status.progress.to_dict()
            payload["running"] = self.status.running
            payload["seq"] = self.status.metrics_seq
            return payload

    def start(self, request: TrainingRunRequest) -> None:
        with self._lock:
            if self.status.running:
                raise RuntimeError("Training already running")
            self._stop_requested = False
            self.status = TrainingControllerStatus(
                running=True,
                progress=TrainingProgress(
                    status="starting",
                    total_timesteps=request.total_timesteps,
                ),
            )
            self.status.metrics_seq = 1
            self._thread = threading.Thread(
                target=self._run,
                kwargs={"request": request},
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_requested = True
        with self._lock:
            if self.status.running:
                self.status.progress.status = "stopping"

    def reset(self) -> None:
        self.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        with self._lock:
            self.status = TrainingControllerStatus()
            self._thread = None
            self._stop_requested = False

    def _publish_progress(self, progress: TrainingProgress) -> None:
        with self._lock:
            self.status.progress = progress
            self.status.metrics_seq += 1

    def _run(self, *, request: TrainingRunRequest) -> None:
        hooks = _DashboardTrainingHooks(self)

        config = TrainingConfig(
            vehicle_name=request.vehicle_name,
            vehicle_version=request.vehicle_version,
            track_id=request.track_id,
            drive_mode=request.drive_mode,
            driver_profile=request.driver_profile,
            objective=request.objective,
            target_laps=request.target_laps,
            total_timesteps=request.total_timesteps,
            preview_freq=request.preview_freq,
            eval_freq=request.preview_freq,
            seed=request.seed,
        )
        try:
            hooks.on_progress(
                TrainingProgress(
                    status="training",
                    total_timesteps=config.total_timesteps,
                    policy_key=_policy_key_for(config),
                )
            )
            result = train_policy(config, hooks=hooks, stop_check=self._should_stop)
            hooks.on_progress(
                TrainingProgress(
                    timesteps=config.total_timesteps,
                    total_timesteps=config.total_timesteps,
                    status=result.manifest.status,
                    policy_key=result.identity.policy_key,
                    best_lap_s=result.best_lap_s,
                    clean_lap_rate=result.clean_lap_rate,
                    preview_running=False,
                )
            )
        except Exception as exc:  # noqa: BLE001 - surface to dashboard
            progress = TrainingProgress(
                status="failed",
                total_timesteps=config.total_timesteps,
                error=str(exc),
            )
            with self._lock:
                if self.status.progress.policy_key:
                    progress.policy_key = self.status.progress.policy_key
            hooks.on_progress(progress)
        finally:
            with self._lock:
                self.status.running = False
            self._stop_requested = False

    def _should_stop(self) -> bool:
        return self._stop_requested


class _DashboardTrainingHooks:
    def __init__(self, controller: TrainingController) -> None:
        self._controller = controller

    def on_progress(self, progress: TrainingProgress) -> None:
        self._controller._publish_progress(progress)

    def on_preview_tick(self, row: dict[str, Any]) -> None:
        self._controller.bus.publish(validate_sample_row(row))

    def should_stop(self) -> bool:
        return self._controller._should_stop()


def _policy_key_for(config: TrainingConfig) -> str:
    from gokart.rl.policy_key import build_policy_identity

    identity = build_policy_identity(
        vehicle_name=config.vehicle_name,
        vehicle_version=config.vehicle_version,
        track_id=config.track_id,
        drive_mode=config.drive_mode,
        driver_profile=config.driver_profile,
        objective=config.objective,  # type: ignore[arg-type]
    )
    return identity.policy_key
