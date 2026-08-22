"""Training session summary generation."""

from __future__ import annotations

from unittest.mock import MagicMock

from gokart.rl.session_summary import build_session_summary


def _store_with_speeds(speeds_by_session: dict[str, list[float]]) -> MagicMock:
    store = MagicMock()

    def load_samples(session_id: str, **kwargs):
        mps_values = speeds_by_session.get(session_id, [])
        return [{"speed_mps": value} for value in mps_values]

    store.load_samples.side_effect = load_samples
    store.list_laps.return_value = []
    return store


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


def test_session_top_speed_uses_fastest_preview_not_best_reward() -> None:
    store = _store_with_speeds(
        {
            "fast": [15.0, 16.0],
            "reward": [12.0, 13.0],
        }
    )
    summary = build_session_summary(
        store=store,
        preview_sessions=[
            {
                "timestep": 800_000,
                "episode_reward": 1235.0,
                "kind": "preview",
                "session_id": "reward",
            },
            {
                "timestep": 1_200_000,
                "episode_reward": 1229.0,
                "kind": "preview",
                "session_id": "fast",
            },
        ],
        status="stopped",
        policy_key="abc123",
        resumed_from_timesteps=700_000,
        session_timesteps=500_000,
        final_timesteps=1_200_000,
        best_lap_s=115.5,
        clean_lap_rate=0.0,
        best_checkpoint_timestep=800_000,
    )
    assert summary["best_preview_reward"] == 1235.0
    assert summary["session_top_speed_kmh"] == 16.0 * 3.6
    assert summary["best_preview"]["max_speed_kmh"] == 13.0 * 3.6
    assert summary["fastest_preview"]["timestep"] == 1_200_000
    assert any("Top preview speed" in line for line in summary["highlights"])
