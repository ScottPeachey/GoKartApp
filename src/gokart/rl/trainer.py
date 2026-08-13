"""PPO training orchestration with clean-ceiling detection."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gokart import __version__
from gokart.rl.env import make_env
from gokart.rl.episode_recording import EpisodeRecordingEnv, session_tick_row
from gokart.rl.hooks import NullTrainingHooks, TrainingHooks, TrainingProgress
from gokart.rl.policy_key import PolicyIdentity, build_policy_identity, policy_dir
from gokart.rl.registry import PolicyManifest, model_path, save_manifest
from gokart.track.store import load_track


@dataclass(frozen=True)
class TrainingConfig:
    vehicle_name: str
    vehicle_version: str
    track_id: str
    drive_mode: str = "default"
    driver_profile: str = "owner"
    objective: str = "god"
    target_laps: int = 3
    total_timesteps: int = 50_000
    preview_freq: int = 10_000
    record_training_episodes: bool = True
    preview_max_steps: int = 6_000
    preview_laps: int = 1
    rollout_stream_every: int = 0
    progress_every: int = 50
    eval_freq: int = 10_000
    n_eval_episodes: int = 2
    n_steps: int = 2048
    batch_size: int = 64
    seed: int = 0
    learning_rate: float = 3e-4
    plateau_evals: int = 3
    min_improvement_s: float = 0.05
    clean_lap_fault_free: bool = True


@dataclass
class TrainingResult:
    identity: PolicyIdentity
    manifest: PolicyManifest
    model_path: Path
    best_lap_s: float | None
    clean_lap_rate: float
    plateau_reached: bool


def run_preview_episode(
    model,
    *,
    config: TrainingConfig,
    track,
    hooks: TrainingHooks | None = None,
    timestep: int = 0,
    max_steps: int | None = None,
) -> tuple[float | None, float, float, str]:
    """Run one deterministic rollout, optionally streaming ticks to hooks."""
    env = make_env(
        vehicle_name=config.vehicle_name,
        vehicle_version=config.vehicle_version,
        track=track,
        drive_mode=config.drive_mode,
        driver_profile=config.driver_profile,
        objective=config.objective,
        target_laps=config.preview_laps,
        max_steps=max_steps or config.preview_max_steps,
    )
    obs, _ = env.reset()
    done = False
    episode_reward = 0.0
    lap_best: float | None = None
    had_fault = False
    ticks: list[dict[str, Any]] = []
    if row := session_tick_row(env):
        ticks.append(row)
    preview_session_id = ""
    while not done:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        episode_reward += float(reward)
        done = terminated or truncated
        if info.get("active_faults"):
            had_fault = True
        best = float(info.get("best_lap_time_s", 0.0) or 0.0)
        if best > 0:
            lap_best = best if lap_best is None else min(lap_best, best)
        if row := session_tick_row(env):
            ticks.append(row)
    if hooks is not None and ticks:
        preview_session_id = hooks.record_episode(
            ticks=ticks,
            timestep=timestep,
            kind="preview",
        )
    clean = 1.0 if lap_best is not None and not had_fault else 0.0
    return lap_best, clean, episode_reward, preview_session_id


def train_policy(
    config: TrainingConfig,
    *,
    root: Path | None = None,
    hooks: TrainingHooks | None = None,
    stop_check: Callable[[], bool] | None = None,
) -> TrainingResult:
    callbacks = hooks or NullTrainingHooks()
    should_stop = stop_check or (lambda: False)

    track = load_track(config.track_id, root=root)
    identity = build_policy_identity(
        vehicle_name=config.vehicle_name,
        vehicle_version=config.vehicle_version,
        track_id=config.track_id,
        drive_mode=config.drive_mode,
        driver_profile=config.driver_profile,
        objective=config.objective,  # type: ignore[arg-type]
        root=root,
    )

    def _status(status: str, **kwargs: Any) -> None:
        callbacks.on_progress(
            TrainingProgress(
                timesteps=int(kwargs.get("timesteps", 0)),
                total_timesteps=config.total_timesteps,
                status=status,
                policy_key=identity.policy_key,
                preview_running=bool(kwargs.get("preview_running", False)),
            )
        )

    _status("loading_libraries")
    try:
        from stable_baselines3 import PPO
        from stable_baselines3.common.callbacks import BaseCallback
        from stable_baselines3.common.monitor import Monitor
    except ImportError as exc:
        raise RuntimeError(
            "RL training requires stable-baselines3. Install with: uv sync --group rl"
        ) from exc

    manifest = PolicyManifest(
        identity=identity,
        status="training",
        training_seed=config.seed,
        sim_version=__version__,
        reward_preset=f"{config.objective}_v1",
    )
    save_manifest(manifest, root=root)

    training_state = {"timesteps": 0}

    def _make():
        env = make_env(
            vehicle_name=config.vehicle_name,
            vehicle_version=config.vehicle_version,
            track=track,
            drive_mode=config.drive_mode,
            driver_profile=config.driver_profile,
            objective=config.objective,
            target_laps=config.target_laps,
        )
        if config.record_training_episodes:

            def _on_episode_complete(ticks: list[dict[str, Any]], episode_index: int) -> None:
                callbacks.record_episode(
                    ticks=ticks,
                    timestep=training_state["timesteps"],
                    kind="episode",
                    episode_index=episode_index,
                )

            env = EpisodeRecordingEnv(
                env,
                timestep_provider=lambda: training_state["timesteps"],
                on_episode_complete=_on_episode_complete,
            )
        return Monitor(env)

    _status("building_model")
    env = _make()
    model = PPO(
        "MlpPolicy",
        env,
        verbose=0,
        seed=config.seed,
        learning_rate=config.learning_rate,
        n_steps=config.n_steps,
        batch_size=config.batch_size,
    )

    eval_history: list[float | None] = []
    best_lap: float | None = None
    clean_rates: list[float] = []
    stop_training_flag = False
    previews_completed = 0
    last_episode_reward: float | None = None
    last_eval_lap: float | None = None

    def _emit_progress(
        *,
        timesteps: int,
        preview_running: bool = False,
        preview_session_id: str = "",
        status: str = "training",
    ) -> None:
        callbacks.on_progress(
            TrainingProgress(
                timesteps=timesteps,
                total_timesteps=config.total_timesteps,
                status=status,
                policy_key=identity.policy_key,
                best_lap_s=best_lap,
                clean_lap_rate=(sum(clean_rates) / len(clean_rates)) if clean_rates else 0.0,
                eval_history=list(eval_history),
                last_episode_reward=last_episode_reward,
                last_eval_lap_s=last_eval_lap,
                preview_running=preview_running,
                preview_session_id=preview_session_id,
                previews_completed=previews_completed,
            )
        )

    class CeilingCallback(BaseCallback):
        def _on_step(self) -> bool:
            nonlocal best_lap, stop_training_flag, previews_completed
            nonlocal last_episode_reward, last_eval_lap
            training_state["timesteps"] = self.num_timesteps
            if stop_training_flag or should_stop() or callbacks.should_stop():
                stop_training_flag = True
                return False

            if (
                self.num_timesteps > 0
                and config.progress_every > 0
                and self.num_timesteps % config.progress_every == 0
            ):
                _emit_progress(timesteps=self.num_timesteps)

            if (
                config.rollout_stream_every > 0
                and self.num_timesteps % config.rollout_stream_every == 0
            ):
                _stream_training_tick(self.training_env, callbacks)

            run_preview = (
                self.num_timesteps > 0
                and config.preview_freq > 0
                and self.num_timesteps % config.preview_freq == 0
            )
            run_silent_eval = (
                not run_preview
                and self.num_timesteps > 0
                and config.eval_freq > 0
                and self.num_timesteps % config.eval_freq == 0
            )

            if run_preview:
                if should_stop() or callbacks.should_stop():
                    stop_training_flag = True
                    return False
                _emit_progress(
                    timesteps=self.num_timesteps,
                    preview_running=True,
                    status="preview_recording",
                )
                lap, clean, reward, preview_session_id = run_preview_episode(
                    model,
                    config=config,
                    track=track,
                    hooks=callbacks,
                    timestep=self.num_timesteps,
                )
                previews_completed += 1
                last_episode_reward = reward
                last_eval_lap = lap
                eval_history.append(lap)
                clean_rates.append(clean)
                if lap is not None and (
                    best_lap is None or lap < best_lap - config.min_improvement_s
                ):
                    best_lap = lap
                if _plateau_reached(eval_history, config.plateau_evals, config.min_improvement_s):
                    stop_training_flag = True
                    _emit_progress(
                        timesteps=self.num_timesteps,
                        preview_session_id=preview_session_id,
                    )
                    return False
                _emit_progress(
                    timesteps=self.num_timesteps,
                    preview_session_id=preview_session_id,
                    preview_running=False,
                )
            elif run_silent_eval:
                lap, clean_rate = evaluate_policy(
                    model,
                    config=config,
                    track=track,
                    episodes=config.n_eval_episodes,
                )
                eval_history.append(lap)
                clean_rates.append(clean_rate)
                last_eval_lap = lap
                if lap is not None and (
                    best_lap is None or lap < best_lap - config.min_improvement_s
                ):
                    best_lap = lap
                if _plateau_reached(eval_history, config.plateau_evals, config.min_improvement_s):
                    stop_training_flag = True
                    return False
                _emit_progress(timesteps=self.num_timesteps)

            return True

    _emit_progress(timesteps=0)
    callback = CeilingCallback()
    model.learn(total_timesteps=config.total_timesteps, callback=callback)

    if should_stop() or callbacks.should_stop():
        manifest.status = "stopped"
    else:
        final_lap, clean_rate = evaluate_policy(
            model,
            config=config,
            track=track,
            episodes=max(config.n_eval_episodes, 3),
        )
        if final_lap is not None:
            best_lap = final_lap if best_lap is None else min(best_lap, final_lap)
        clean_rates.append(clean_rate)

    out_path = model_path(identity, root=root)
    model.save(str(out_path))

    if manifest.status != "stopped":
        manifest.status = "ceiling_reached" if best_lap is not None else "failed"
    manifest.ceiling_lap_s = best_lap
    manifest.clean_lap_rate = (sum(clean_rates) / len(clean_rates)) if clean_rates else 0.0
    save_manifest(manifest, root=root)

    metrics_path = policy_dir(identity, root=root) / "training_metrics.json"
    metrics_path.write_text(
        json.dumps(
            {
                "eval_history": eval_history,
                "best_lap_s": best_lap,
                "clean_lap_rate": manifest.clean_lap_rate,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return TrainingResult(
        identity=identity,
        manifest=manifest,
        model_path=out_path,
        best_lap_s=best_lap,
        clean_lap_rate=manifest.clean_lap_rate,
        plateau_reached=_plateau_reached(
            eval_history, config.plateau_evals, config.min_improvement_s
        ),
    )


def evaluate_policy(
    model,
    *,
    config: TrainingConfig,
    track,
    episodes: int,
) -> tuple[float | None, float]:
    from gokart.rl.env import make_env

    best_laps: list[float] = []
    clean = 0
    for _ in range(episodes):
        env = make_env(
            vehicle_name=config.vehicle_name,
            vehicle_version=config.vehicle_version,
            track=track,
            drive_mode=config.drive_mode,
            driver_profile=config.driver_profile,
            objective=config.objective,
            target_laps=config.target_laps,
        )
        obs, _ = env.reset()
        done = False
        lap_best = None
        had_fault = False
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, _reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
            if info.get("active_faults"):
                had_fault = True
            best = float(info.get("best_lap_time_s", 0.0) or 0.0)
            if best > 0:
                lap_best = best if lap_best is None else min(lap_best, best)
        if lap_best is not None and not had_fault:
            clean += 1
            best_laps.append(lap_best)
    if not best_laps:
        return None, 0.0
    return min(best_laps), clean / episodes


def verify_policy(identity: PolicyIdentity, *, episodes: int = 5, root: Path | None = None) -> dict:
    manifest = load_manifest(identity, root=root)
    if manifest is None:
        raise FileNotFoundError(f"no manifest for policy {identity.policy_key}")
    try:
        from stable_baselines3 import PPO
    except ImportError as exc:
        raise RuntimeError("Install RL deps: uv sync --group rl") from exc

    model = PPO.load(str(model_path(identity, root=root)))
    config = TrainingConfig(
        vehicle_name=identity.vehicle_name,
        vehicle_version=identity.vehicle_version,
        track_id=identity.track_id,
        drive_mode=identity.drive_mode,
        driver_profile=identity.driver_profile,
        objective=identity.objective,
    )
    track = load_track(identity.track_id, root=root)
    best_lap, clean_rate = evaluate_policy(model, config=config, track=track, episodes=episodes)
    passed = clean_rate >= 0.95 and best_lap is not None
    return {
        "policy_key": identity.policy_key,
        "passed": passed,
        "ceiling_lap_s": best_lap,
        "clean_lap_rate": clean_rate,
        "episodes": episodes,
    }


def _unwrap_env(vec_env: Any) -> Any:
    env = vec_env
    envs = getattr(env, "envs", None)
    if envs:
        env = envs[0]
    for _ in range(8):
        inner = getattr(env, "env", None)
        if inner is None:
            break
        env = inner
    return env


def _stream_training_tick(vec_env: Any, hooks: TrainingHooks) -> None:
    kart_env = _unwrap_env(vec_env)
    session = getattr(kart_env, "session", None)
    if session is None or session.state.last_tick is None:
        return
    hooks.on_preview_tick(session.state.last_tick.to_row())


def _plateau_reached(history: list[float | None], window: int, epsilon: float) -> bool:
    if len(history) < window:
        return False
    recent = [value for value in history[-window:] if value is not None]
    if len(recent) < window:
        return False
    return max(recent) - min(recent) < epsilon


from gokart.rl.registry import load_manifest  # noqa: E402
