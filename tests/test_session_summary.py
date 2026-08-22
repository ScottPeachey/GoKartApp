"""Training session summary generation."""

from __future__ import annotations

from gokart.rl.session_summary import build_session_summary


def test_build_session_summary_includes_reward_series() -> None:
    summary = build_session_summary(
        store=None,
        preview_sessions=[
            {"timestep": 100_000, "episode_reward": 500.0, "kind": "preview", "session_id": "a"},
            {"timestep": 120_000, "episode_reward": 1200.0, "kind": "episode", "episode": 20, "session_id": "b"},
            {"timestep": 150_000, "episode_reward": 300.0, "kind": "episode", "episode": 40, "session_id": "c"},
        ],
        status="stopped",
        policy_key="abc123",
        resumed_from_timesteps=0,
        session_timesteps=200_000,
        final_timesteps=200_000,
        best_lap_s=None,
        clean_lap_rate=0.0,
        best_checkpoint_timestep=120_000,
    )
    assert len(summary["reward_series"]) == 3
    assert summary["reward_series"][0]["session_step"] == 100_000
    assert summary["comparison"]["verdict"] == "first_session"
    assert summary["highlights"]


def test_build_session_summary_compares_to_previous() -> None:
    previous = {
        "mean_reward": 650.0,
        "best_preview_reward": 1000.0,
        "best_lap_s": 140.0,
        "best_preview_max_speed_kmh": 42.0,
        "final_timesteps": 500_000,
        "reward_series": [{"timestep": 100_000, "session_step": 100_000, "reward": 900.0, "kind": "preview"}],
    }
    summary = build_session_summary(
        store=None,
        preview_sessions=[
            {"timestep": 600_000, "episode_reward": 1220.0, "kind": "preview", "session_id": "a"},
            {"timestep": 620_000, "episode_reward": 200.0, "kind": "episode", "episode": 20, "session_id": "b"},
        ],
        status="stopped",
        policy_key="abc123",
        resumed_from_timesteps=500_000,
        session_timesteps=200_000,
        final_timesteps=700_000,
        best_lap_s=119.0,
        clean_lap_rate=0.0,
        best_checkpoint_timestep=600_000,
        previous_summary=previous,
    )
    assert summary["comparison"]["verdict"] == "improved"
    assert summary["comparison"]["delta_mean_reward"] is not None
    assert summary["previous_reward_series"] == previous["reward_series"]
    assert any("improved" in point.lower() for point in summary["good"])
