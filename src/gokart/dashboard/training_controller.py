"""Background RL training with live preview and metrics for the dashboard."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from gokart.config.hashing import content_hash
from gokart.config.store import data_root, load_vehicle
from gokart.rl.hooks import TrainingProgress
from gokart.rl.trainer import TrainingConfig, train_policy
from gokart.rl.training_setup import RlTrainingSetup, training_setup_from_dict
from gokart.telemetry.bus import TelemetryBus
from gokart.telemetry.channels import validate_sample_row
from gokart.telemetry.recorder import SessionMetadata, SessionRecorder
from gokart.telemetry.storage import TelemetryStore


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
    setup: dict[str, Any] | None = None


@dataclass
class TrainingControllerStatus:
    running: bool = False
    progress: TrainingProgress = field(default_factory=TrainingProgress)
    metrics_seq: int = 0


class TrainingController:
    def __init__(self, *, bus: TelemetryBus, store: TelemetryStore | None = None) -> None:
        self.bus = bus
        self.store = store or TelemetryStore()
        self._lock = threading.Lock()
        self._stop_requested = False
        self._thread: threading.Thread | None = None
        self._request: TrainingRunRequest | None = None
        self._preview_recorder: SessionRecorder | None = None
        self._preview_timestep = 0
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
            self._request = request
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
            self._preview_recorder = None
            self._preview_timestep = 0

    def _publish_progress(self, progress: TrainingProgress) -> None:
        with self._lock:
            self.status.progress = progress
            self.status.metrics_seq += 1

    def _run(self, *, request: TrainingRunRequest) -> None:
        hooks = _DashboardTrainingHooks(self)

        setup = training_setup_from_dict(request.setup)
        if request.objective:
            setup = RlTrainingSetup(
                objective=request.objective,
                action=setup.action,
                env=setup.env,
                ppo=setup.ppo,
                rewards=setup.rewards,
            )

        config = TrainingConfig(
            vehicle_name=request.vehicle_name,
            vehicle_version=request.vehicle_version,
            track_id=request.track_id,
            drive_mode=request.drive_mode,
            driver_profile=request.driver_profile,
            objective=setup.objective,
            target_laps=request.target_laps,
            total_timesteps=request.total_timesteps,
            preview_freq=request.preview_freq,
            eval_freq=request.preview_freq,
            record_training_episodes=True,
            seed=request.seed,
            setup=setup,
        )
        try:
            hooks.on_progress(
                TrainingProgress(
                    status="starting",
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
                    preview_sessions=list(hooks.preview_sessions),
                    previews_completed=len(hooks.preview_sessions),
                )
            )
        except Exception as exc:  # noqa: BLE001 - surface to dashboard
            progress = TrainingProgress(
                status="failed",
                total_timesteps=config.total_timesteps,
                error=str(exc),
                preview_sessions=list(hooks.preview_sessions),
                previews_completed=len(hooks.preview_sessions),
            )
            with self._lock:
                if self.status.progress.policy_key:
                    progress.policy_key = self.status.progress.policy_key
            hooks.on_progress(progress)
        finally:
            self._close_preview_recorder()
            with self._lock:
                self.status.running = False
            self._stop_requested = False

    def _should_stop(self) -> bool:
        return self._stop_requested

    def _close_preview_recorder(self) -> None:
        recorder = self._preview_recorder
        self._preview_recorder = None
        if recorder is not None:
            recorder.close(end_soc=None)


class _DashboardTrainingHooks:
    def __init__(self, controller: TrainingController) -> None:
        self._controller = controller
        self.preview_sessions: list[dict[str, Any]] = []

    def on_progress(self, progress: TrainingProgress) -> None:
        merged = TrainingProgress(
            timesteps=progress.timesteps,
            total_timesteps=progress.total_timesteps,
            status=progress.status,
            policy_key=progress.policy_key or self._controller.status.progress.policy_key,
            best_lap_s=progress.best_lap_s,
            clean_lap_rate=progress.clean_lap_rate,
            eval_history=list(progress.eval_history),
            last_episode_reward=progress.last_episode_reward,
            last_eval_lap_s=progress.last_eval_lap_s,
            preview_running=progress.preview_running,
            preview_session_id=progress.preview_session_id,
            preview_sessions=list(self.preview_sessions),
            previews_completed=len(self.preview_sessions),
            error=progress.error,
        )
        self._controller._publish_progress(merged)

    def on_preview_tick(self, row: dict[str, Any]) -> None:
        recorder = self._controller._preview_recorder
        if recorder is not None:
            recorder.record_tick(row)
            return
        self._controller.bus.publish(validate_sample_row(row))

    def should_stop(self) -> bool:
        return self._controller._should_stop()

    def start_preview_recording(self, *, timestep: int) -> str:
        request = self._controller._request
        if request is None:
            return ""
        self._controller._preview_timestep = timestep
        vehicle = load_vehicle(request.vehicle_name, request.vehicle_version, root=data_root())
        recorder = SessionRecorder(
            SessionMetadata(
                vehicle_name=request.vehicle_name,
                vehicle_version=request.vehicle_version,
                config_hash=content_hash(vehicle.model_dump(mode="json")),
                driver_profile=request.driver_profile,
                drive_mode=request.drive_mode,
                scenario_name=f"rl_preview_{timestep}",
                track_id=request.track_id,
                notes=f"RL preview at {timestep:,} training steps",
            ),
            store=self._controller.store,
            bus=self._controller.bus,
            log_every_n=1,
        )
        self._controller._preview_recorder = recorder
        return recorder.session_id

    def finish_preview_recording(self) -> None:
        self._controller._close_preview_recorder()

    def record_episode(
        self,
        *,
        ticks: list[dict[str, Any]],
        timestep: int,
        kind: str = "episode",
        episode_index: int = 0,
    ) -> str:
        request = self._controller._request
        if request is None or not ticks:
            return ""

        if kind == "preview":
            scenario_name = f"rl_preview_{timestep}"
            notes = f"RL preview at {timestep:,} training steps"
        else:
            scenario_name = f"rl_episode_{timestep}_{episode_index}"
            notes = (
                f"RL training episode {episode_index} at {timestep:,} training steps"
            )

        vehicle = load_vehicle(request.vehicle_name, request.vehicle_version, root=data_root())
        recorder = SessionRecorder(
            SessionMetadata(
                vehicle_name=request.vehicle_name,
                vehicle_version=request.vehicle_version,
                config_hash=content_hash(vehicle.model_dump(mode="json")),
                driver_profile=request.driver_profile,
                drive_mode=request.drive_mode,
                scenario_name=scenario_name,
                track_id=request.track_id,
                notes=notes,
            ),
            store=self._controller.store,
            bus=self._controller.bus,
            log_every_n=1,
        )
        for row in ticks:
            recorder.record_tick(row)
        recorder.close(end_soc=None)

        entry: dict[str, Any] = {
            "timestep": timestep,
            "session_id": recorder.session_id,
        }
        if kind == "episode":
            entry["episode"] = episode_index
        self.preview_sessions.append(entry)
        return recorder.session_id


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
