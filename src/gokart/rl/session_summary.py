"""Build end-of-training session summaries for the dashboard."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import mean, median
from typing import Any

from gokart.rl.policy_key import PolicyIdentity
from gokart.rl.registry import load_training_metrics, training_metrics_path
from gokart.telemetry.storage import TelemetryStore

_LOW_REWARD = 400.0
_HIGH_REWARD = 1100.0


@dataclass(frozen=True)
class PreviewHighlight:
    timestep: int
    session_id: str
    reward: float | None
    max_speed_kmh: float | None
    avg_speed_kmh: float | None
    best_lap_s: float | None
    laps_completed: int
    sample_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestep": self.timestep,
            "session_id": self.session_id,
            "reward": self.reward,
            "max_speed_kmh": self.max_speed_kmh,
            "avg_speed_kmh": self.avg_speed_kmh,
            "best_lap_s": self.best_lap_s,
            "laps_completed": self.laps_completed,
            "sample_count": self.sample_count,
        }


def _session_stats(store: TelemetryStore | None, session_id: str) -> dict[str, Any]:
    if store is None or not session_id:
        return {}
    samples = store.load_samples(session_id)
    if not samples:
        return {}
    speeds = [float(sample.get("speed_mps") or 0.0) for sample in samples]
    last = samples[-1]
    best_lap = float(last.get("best_lap_time_s") or 0.0)
    if best_lap <= 0.0:
        lap_time = float(last.get("last_lap_time_s") or 0.0)
        lap_number = int(float(last.get("lap_number") or 0))
        best_lap = lap_time if lap_number > 1 and lap_time > 0 else None
    else:
        best_lap = best_lap if best_lap > 0 else None
    laps_completed = len(store.list_laps(session_id))
    if laps_completed == 0 and best_lap is not None:
        laps_completed = 1
    return {
        "max_speed_kmh": max(speeds) * 3.6 if speeds else None,
        "avg_speed_kmh": (sum(speeds) / len(speeds)) * 3.6 if speeds else None,
        "best_lap_s": best_lap,
        "laps_completed": laps_completed,
        "sample_count": len(samples),
    }


def _preview_entries(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    for entry in sessions:
        kind = str(entry.get("kind") or "")
        if kind == "preview":
            previews.append(entry)
            continue
        if kind in {"episode", "test"}:
            continue
        if "episode" not in entry:
            previews.append(entry)
    return previews


def _episode_entries(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        entry
        for entry in sessions
        if entry.get("kind") == "episode" or "episode" in entry
    ]


def _highlight_from_entry(
    entry: dict[str, Any],
    *,
    store: TelemetryStore | None,
) -> PreviewHighlight:
    stats = _session_stats(store, str(entry.get("session_id") or ""))
    reward = entry.get("episode_reward")
    return PreviewHighlight(
        timestep=int(entry.get("timestep") or 0),
        session_id=str(entry.get("session_id") or ""),
        reward=float(reward) if reward is not None else None,
        max_speed_kmh=stats.get("max_speed_kmh"),
        avg_speed_kmh=stats.get("avg_speed_kmh"),
        best_lap_s=stats.get("best_lap_s"),
        laps_completed=int(stats.get("laps_completed") or 0),
        sample_count=int(stats.get("sample_count") or 0),
    )


def _pick_best_preview(
    previews: list[dict[str, Any]],
    *,
    store: TelemetryStore | None,
) -> PreviewHighlight | None:
    if not previews:
        return None
    highlights = [_highlight_from_entry(entry, store=store) for entry in previews]
    ranked = sorted(
        highlights,
        key=lambda item: (
            item.reward is not None,
            item.reward or 0.0,
            item.best_lap_s is not None,
            -(item.best_lap_s or 1e9),
            item.max_speed_kmh or 0.0,
        ),
        reverse=True,
    )
    return ranked[0]


def _pick_best_lap_preview(
    previews: list[dict[str, Any]],
    *,
    store: TelemetryStore | None,
) -> PreviewHighlight | None:
    highlights = [
        item
        for item in (_highlight_from_entry(entry, store=store) for entry in previews)
        if item.best_lap_s is not None and item.best_lap_s > 0
    ]
    if not highlights:
        return None
    return min(highlights, key=lambda item: item.best_lap_s or 1e9)


def _pick_fastest_preview(
    previews: list[dict[str, Any]],
    *,
    store: TelemetryStore | None,
) -> PreviewHighlight | None:
    highlights = [
        item
        for item in (_highlight_from_entry(entry, store=store) for entry in previews)
        if item.max_speed_kmh is not None and item.max_speed_kmh > 0
    ]
    if not highlights:
        return None
    return max(highlights, key=lambda item: item.max_speed_kmh or 0.0)


def _reward_stats(entries: list[dict[str, Any]]) -> dict[str, Any]:
    rewards = [
        float(entry["episode_reward"])
        for entry in entries
        if entry.get("episode_reward") is not None
    ]
    if not rewards:
        return {
            "mean_reward": None,
            "median_reward": None,
            "min_reward": None,
            "max_reward": None,
            "low_count": 0,
            "high_count": 0,
            "count": 0,
        }
    return {
        "mean_reward": mean(rewards),
        "median_reward": median(rewards),
        "min_reward": min(rewards),
        "max_reward": max(rewards),
        "low_count": sum(1 for value in rewards if value < _LOW_REWARD),
        "high_count": sum(1 for value in rewards if value >= _HIGH_REWARD),
        "count": len(rewards),
    }


def _previous_top_speed(previous: dict[str, Any]) -> float | None:
    value = previous.get("session_top_speed_kmh")
    if value is not None:
        return float(value)
    legacy = previous.get("best_preview_max_speed_kmh")
    return float(legacy) if legacy is not None else None


def _compare_sessions(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    if not previous:
        return {"verdict": "first_session"}

    def _delta(key: str) -> float | None:
        cur = current.get(key)
        prev = previous.get(key)
        if cur is None or prev is None:
            return None
        return float(cur) - float(prev)

    delta_mean = _delta("mean_reward")
    delta_best_preview = _delta("best_preview_reward")
    delta_best_lap = _delta("best_lap_s")
    cur_top_speed = current.get("session_top_speed_kmh")
    prev_top_speed = _previous_top_speed(previous)
    delta_max_speed = (
        float(cur_top_speed) - float(prev_top_speed)
        if cur_top_speed is not None and prev_top_speed is not None
        else None
    )
    delta_final = _delta("final_timesteps")

    improved = 0
    regressed = 0
    if delta_mean is not None:
        improved += delta_mean > 25
        regressed += delta_mean < -25
    if delta_best_preview is not None:
        improved += delta_best_preview > 25
        regressed += delta_best_preview < -25
    if delta_best_lap is not None:
        improved += delta_best_lap < -1.0
        regressed += delta_best_lap > 1.0
    if delta_max_speed is not None:
        improved += delta_max_speed > 2.0
        regressed += delta_max_speed < -2.0

    if improved and not regressed:
        verdict = "improved"
    elif regressed and not improved:
        verdict = "regressed"
    elif improved and regressed:
        verdict = "mixed"
    else:
        verdict = "flat"

    return {
        "verdict": verdict,
        "previous_final_timesteps": previous.get("final_timesteps"),
        "previous_mean_reward": previous.get("mean_reward"),
        "previous_best_preview_reward": previous.get("best_preview_reward"),
        "previous_best_lap_s": previous.get("best_lap_s"),
        "previous_session_top_speed_kmh": _previous_top_speed(previous),
        "delta_mean_reward": delta_mean,
        "delta_best_preview_reward": delta_best_preview,
        "delta_best_lap_s": delta_best_lap,
        "delta_session_top_speed_kmh": delta_max_speed,
        "delta_final_timesteps": delta_final,
    }


def _build_highlights(
    *,
    best_preview: PreviewHighlight | None,
    best_lap_preview: PreviewHighlight | None,
    fastest_preview: PreviewHighlight | None,
    reward_stats: dict[str, Any],
    best_lap_s: float | None,
    best_checkpoint_timestep: int | None,
) -> list[str]:
    lines: list[str] = []
    if best_preview and best_preview.reward is not None:
        lines.append(
            f"Best preview reward {best_preview.reward:.0f} at "
            f"{best_preview.timestep:,} training steps"
        )
    if best_lap_preview and best_lap_preview.best_lap_s is not None:
        lines.append(
            f"Fastest preview lap {best_lap_preview.best_lap_s:.1f}s at "
            f"{best_lap_preview.timestep:,} steps"
        )
    if fastest_preview and fastest_preview.max_speed_kmh is not None:
        lines.append(
            f"Top preview speed {fastest_preview.max_speed_kmh:.1f} km/h at "
            f"{fastest_preview.timestep:,} steps"
        )
    if best_lap_s is not None:
        lines.append(f"Best recorded lap {best_lap_s:.1f}s")
    if best_checkpoint_timestep is not None:
        lines.append(f"Best checkpoint saved at {best_checkpoint_timestep:,} steps")
    if reward_stats.get("high_count"):
        lines.append(
            f"{reward_stats['high_count']} strong episodes (reward ≥ {_HIGH_REWARD:.0f})"
        )
    return lines[:5]


def _build_good_points(
    *,
    comparison: dict[str, Any],
    reward_stats: dict[str, Any],
    best_lap_preview: PreviewHighlight | None,
    clean_lap_rate: float,
) -> list[str]:
    points: list[str] = []
    verdict = comparison.get("verdict")
    if verdict == "improved":
        points.append("Overall metrics improved versus the previous training session.")
    if best_lap_preview is not None:
        points.append("The policy completed at least one full preview lap.")
    if reward_stats.get("high_count", 0) >= 3:
        points.append("Several high-reward episodes show the policy can drive cleanly.")
    if clean_lap_rate > 0:
        points.append(f"Clean eval lap rate reached {clean_lap_rate * 100:.0f}%.")
    delta_speed = comparison.get("delta_session_top_speed_kmh")
    if delta_speed is not None and delta_speed > 2:
        points.append(f"Preview top speed up {delta_speed:.1f} km/h from last session.")
    delta_lap = comparison.get("delta_best_lap_s")
    if delta_lap is not None and delta_lap < -1:
        points.append(f"Best preview lap improved by {abs(delta_lap):.1f}s.")
    return points[:4]


def _build_issues(
    *,
    status: str,
    reward_stats: dict[str, Any],
    best_lap_s: float | None,
    error: str | None,
    comparison: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    if error:
        issues.append(f"Training error: {error}")
    if status in {"failed", "stopped"} and status != "ceiling_reached":
        if status == "stopped":
            issues.append("Training was stopped before the budget finished.")
        elif best_lap_s is None:
            issues.append("No clean eval lap was recorded by the end of training.")
    if best_lap_s is None:
        issues.append("No validated best lap time yet — previews may still be incomplete.")
    low = int(reward_stats.get("low_count") or 0)
    total = int(reward_stats.get("count") or 0)
    if total and low / total >= 0.25:
        issues.append(
            f"{low} of {total} recorded episodes scored below {_LOW_REWARD:.0f} "
            "(often early bail-outs or incomplete laps)."
        )
    if comparison.get("verdict") == "regressed":
        issues.append("Mean reward and/or lap pace regressed versus the previous session.")
    if comparison.get("verdict") == "mixed":
        issues.append("Peaks improved but low-reward collapses are still frequent.")
    return issues[:5]


def _entry_kind(entry: dict[str, Any]) -> str:
    kind = str(entry.get("kind") or "")
    if kind in {"preview", "episode", "test"}:
        return kind
    if "episode" in entry:
        return "episode"
    return "preview"


def _build_reward_series(
    sessions: list[dict[str, Any]],
    *,
    resumed_from_timesteps: int,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for entry in sessions:
        reward = entry.get("episode_reward")
        if reward is None:
            continue
        timestep = int(entry.get("timestep") or 0)
        points.append(
            {
                "timestep": timestep,
                "session_step": max(0, timestep - resumed_from_timesteps),
                "reward": float(reward),
                "kind": _entry_kind(entry),
                "session_id": str(entry.get("session_id") or ""),
            }
        )
    points.sort(key=lambda item: item["timestep"])
    return points


def build_session_summary(
    *,
    store: TelemetryStore | None,
    preview_sessions: list[dict[str, Any]],
    status: str,
    policy_key: str,
    resumed_from_timesteps: int,
    session_timesteps: int,
    final_timesteps: int,
    best_lap_s: float | None,
    clean_lap_rate: float,
    best_checkpoint_timestep: int | None,
    previous_summary: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    previews = _preview_entries(preview_sessions)
    episodes = _episode_entries(preview_sessions)
    preview_stats = _reward_stats(previews)
    episode_stats = _reward_stats(episodes)
    combined_stats = _reward_stats(preview_sessions)

    best_preview = _pick_best_preview(previews, store=store)
    best_lap_preview = _pick_best_lap_preview(previews, store=store)
    fastest_preview = _pick_fastest_preview(previews, store=store)
    session_top_speed_kmh = (
        fastest_preview.max_speed_kmh if fastest_preview else None
    )
    session_best_lap = best_lap_s
    if session_best_lap is None and best_lap_preview is not None:
        session_best_lap = best_lap_preview.best_lap_s

    summary_core = {
        "ended_at": datetime.now(UTC).isoformat(),
        "status": status,
        "policy_key": policy_key,
        "resumed_from_timesteps": resumed_from_timesteps,
        "session_timesteps": session_timesteps,
        "final_timesteps": final_timesteps,
        "best_checkpoint_timestep": best_checkpoint_timestep,
        "best_lap_s": session_best_lap,
        "clean_lap_rate": clean_lap_rate,
        "mean_reward": combined_stats["mean_reward"],
        "median_reward": combined_stats["median_reward"],
        "min_reward": combined_stats["min_reward"],
        "max_reward": combined_stats["max_reward"],
        "low_episode_count": combined_stats["low_count"],
        "high_episode_count": combined_stats["high_count"],
        "preview_count": len(previews),
        "episode_count": len(episodes),
        "preview_mean_reward": preview_stats["mean_reward"],
        "episode_mean_reward": episode_stats["mean_reward"],
        "best_preview_reward": best_preview.reward if best_preview else None,
        "session_top_speed_kmh": session_top_speed_kmh,
        "best_preview_max_speed_kmh": session_top_speed_kmh,
        "best_preview": best_preview.to_dict() if best_preview else None,
        "best_lap_preview": best_lap_preview.to_dict() if best_lap_preview else None,
        "fastest_preview": fastest_preview.to_dict() if fastest_preview else None,
    }
    comparison = _compare_sessions(summary_core, previous_summary)
    reward_series = _build_reward_series(
        preview_sessions,
        resumed_from_timesteps=resumed_from_timesteps,
    )
    previous_reward_series = (
        previous_summary.get("reward_series")
        if isinstance(previous_summary, dict)
        else None
    )
    summary = {
        **summary_core,
        "comparison": comparison,
        "reward_series": reward_series,
        "previous_reward_series": previous_reward_series,
        "highlights": _build_highlights(
            best_preview=best_preview,
            best_lap_preview=best_lap_preview,
            fastest_preview=fastest_preview,
            reward_stats=combined_stats,
            best_lap_s=session_best_lap,
            best_checkpoint_timestep=best_checkpoint_timestep,
        ),
        "good": _build_good_points(
            comparison=comparison,
            reward_stats=combined_stats,
            best_lap_preview=best_lap_preview,
            clean_lap_rate=clean_lap_rate,
        ),
        "issues": _build_issues(
            status=status,
            reward_stats=combined_stats,
            best_lap_s=session_best_lap,
            error=error,
            comparison=comparison,
        ),
    }
    return summary


def persist_session_summary(
    identity: PolicyIdentity,
    summary: dict[str, Any],
    *,
    root: Any | None = None,
    extra_metrics: dict[str, Any] | None = None,
) -> None:
    path = training_metrics_path(identity, root=root)
    prior = load_training_metrics(identity, root=root)
    payload = {**prior, **(extra_metrics or {})}
    previous = prior.get("last_session_summary")
    if isinstance(previous, dict):
        payload["previous_session_summary"] = previous
    payload["last_session_summary"] = summary
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
