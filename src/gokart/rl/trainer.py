"""PPO training orchestration with clean-ceiling detection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from gokart import __version__
from gokart.rl.env import make_env
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
    eval_freq: int = 10_000
    n_eval_episodes: int = 2
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


def train_policy(config: TrainingConfig, *, root: Path | None = None) -> TrainingResult:
    try:
        from stable_baselines3 import PPO
        from stable_baselines3.common.callbacks import BaseCallback
        from stable_baselines3.common.monitor import Monitor
    except ImportError as exc:
        raise RuntimeError(
            "RL training requires stable-baselines3. Install with: uv sync --group rl"
        ) from exc

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
    manifest = PolicyManifest(
        identity=identity,
        status="training",
        training_seed=config.seed,
        sim_version=__version__,
        reward_preset=f"{config.objective}_v1",
    )
    save_manifest(manifest, root=root)

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
        return Monitor(env)

    env = _make()
    model = PPO(
        "MlpPolicy",
        env,
        verbose=1,
        seed=config.seed,
        learning_rate=config.learning_rate,
    )

    eval_history: list[float | None] = []
    best_lap: float | None = None
    stop_training_flag = False

    class CeilingCallback(BaseCallback):
        def _on_step(self) -> bool:
            nonlocal best_lap, stop_training_flag
            if stop_training_flag:
                return False
            if self.num_timesteps > 0 and self.num_timesteps % config.eval_freq == 0:
                lap, _clean_rate = evaluate_policy(
                    model,
                    config=config,
                    track=track,
                    episodes=config.n_eval_episodes,
                )
                eval_history.append(lap)
                if lap is not None and (
                    best_lap is None or lap < best_lap - config.min_improvement_s
                ):
                    best_lap = lap
                if _plateau_reached(eval_history, config.plateau_evals, config.min_improvement_s):
                    stop_training_flag = True
                    return False
            return True

    callback = CeilingCallback()
    model.learn(total_timesteps=config.total_timesteps, callback=callback)

    final_lap, clean_rate = evaluate_policy(
        model,
        config=config,
        track=track,
        episodes=max(config.n_eval_episodes, 3),
    )
    if final_lap is not None:
        best_lap = final_lap if best_lap is None else min(best_lap, final_lap)

    out_path = model_path(identity, root=root)
    model.save(str(out_path))

    manifest.status = "ceiling_reached" if best_lap is not None else "failed"
    manifest.ceiling_lap_s = best_lap
    manifest.clean_lap_rate = clean_rate
    save_manifest(manifest, root=root)

    metrics_path = policy_dir(identity, root=root) / "training_metrics.json"
    metrics_path.write_text(
        json.dumps(
            {
                "eval_history": eval_history,
                "best_lap_s": best_lap,
                "clean_lap_rate": clean_rate,
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
        clean_lap_rate=clean_rate,
        plateau_reached=_plateau_reached(eval_history, config.plateau_evals, config.min_improvement_s),
    )


def evaluate_policy(model, *, config: TrainingConfig, track, episodes: int) -> tuple[float | None, float]:
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


def _plateau_reached(history: list[float | None], window: int, epsilon: float) -> bool:
    if len(history) < window:
        return False
    recent = [value for value in history[-window:] if value is not None]
    if len(recent) < window:
        return False
    return max(recent) - min(recent) < epsilon


# avoid circular import for type checker
from gokart.rl.registry import load_manifest  # noqa: E402
