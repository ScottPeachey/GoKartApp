"""RL driver tests (no full training run)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from gokart.rl.actions import ACTION_DIM, decode_rl_action, encode_expert_action
from gokart.rl.env import make_env
from gokart.rl.observations import OBS_DIM, build_observation
from gokart.rl.policy_key import build_policy_identity, identity_from_dict
from gokart.rl.registry import PolicyManifest, save_manifest
from gokart.rl.rewards import RewardState, compute_reward, reward_preset
from gokart.rl.training_setup import (
    WarmupConfig,
    default_training_setup,
    training_setup_from_dict,
    training_setup_schema,
)
from gokart.track.importer import import_geojson_track

FIXTURES = Path(__file__).parent / "fixtures"
HAIRPIN = FIXTURES / "test-hairpin.geojson"

_TICK = {
    "active_faults": "",
    "safety_state": "DRIVING",
    "speed_mps": 4.0,
    "battery_temp_c": 30.0,
    "motor_temp_c": 35.0,
    "soc": 0.9,
    "throttle": 0.7,
    "brake": 0.0,
    "steering": 0.0,
    "max_speed_mps": 12.5,
    "derating_factor": 1.0,
    "torque_permitted": 1.0,
}


@pytest.fixture
def hairpin_track():
    return import_geojson_track(HAIRPIN, track_id="test-hairpin", fetch_elevation=False)


def _reward(tick: dict, info: dict, state: RewardState | None = None):
    return compute_reward(
        tick_values=tick,
        step_info=info,
        weights=reward_preset("god"),
        dt_s=0.01,
        state=state or RewardState(),
        objective="god",
    )


def test_training_setup_from_dict_round_trip() -> None:
    schema = training_setup_schema()
    setup = training_setup_from_dict(schema["defaults"])
    assert setup.objective == "god"
    assert setup.ppo.ent_coef == pytest.approx(0.02)
    assert setup.warmup.demo_steps == 2_000
    assert "warmup" in schema["sections"]
    throttle_field = next(
        field
        for field in schema["sections"]["action"]["fields"]
        if field["key"] == "throttle_breakaway"
    )
    assert throttle_field["step"] == pytest.approx(0.05)
    off_track_field = next(
        field
        for field in schema["sections"]["env"]["fields"]
        if field["key"] == "terminate_on_off_track"
    )
    assert off_track_field["type"] == "bool"
    assert off_track_field["default"] is True
    custom = training_setup_from_dict(
        {
            "objective": "custom",
            "ppo": {"ent_coef": 0.1},
            "rewards": {"standstill": 0.5, "progress": 1.5},
            "env": {"terminate_on_off_track": 0},
            "warmup": {"demo_steps": 2000, "bc_epochs": 3},
        }
    )
    assert custom.objective == "custom"
    assert custom.ppo.ent_coef == pytest.approx(0.1)
    assert custom.rewards.progress == pytest.approx(1.5)
    assert not hasattr(custom.rewards, "standstill")
    assert custom.env.terminate_on_off_track is False
    assert custom.warmup.demo_steps == 2000
    assert custom.warmup.bc_epochs == 3


def test_default_setup_is_min_time() -> None:
    setup = default_training_setup()
    assert setup.env.max_stagnant_steps == 300
    assert setup.env.max_off_track_steps == 800
    assert setup.rewards.wall == pytest.approx(8.0)
    assert setup.rewards.time == pytest.approx(1.0)
    assert not hasattr(setup.rewards, "alignment")
    assert setup.warmup.demo_steps == 2_000
    assert setup.warmup.bc_epochs == 12
    assert setup.action.hold_ticks == 8
    assert ACTION_DIM == 2
    assert OBS_DIM == 16


def test_reward_penalizes_stagnant_terminal() -> None:
    reward, _, components = _reward(
        {**_TICK, "speed_mps": 0.0, "throttle": 0.0},
        {
            "delta_track_s_m": 0.0,
            "lateral_offset_m": 0.0,
            "heading_error_deg": 0.0,
            "track_width_m": 10.0,
            "truncated_stagnant": True,
        },
    )
    assert components["stagnant_terminal"] < 0.0
    assert reward < 0.0


def test_reward_penalizes_wall_hit_when_off_track_terminates() -> None:
    info = {
        "delta_track_s_m": 0.0,
        "lateral_offset_m": 8.0,
        "heading_error_deg": 20.0,
        "track_width_m": 10.0,
        "terminated_off_track": True,
    }
    _, _, slow_parts = _reward({**_TICK, "speed_mps": 1.0}, info)
    _, _, fast_parts = _reward({**_TICK, "speed_mps": 12.5}, info)
    assert slow_parts["wall_hit"] == pytest.approx(-8.0)
    assert fast_parts["wall_hit"] == pytest.approx(slow_parts["wall_hit"])


def test_idle_on_track_is_not_rewarded() -> None:
    reward, _, components = _reward(
        {**_TICK, "speed_mps": 0.0, "throttle": 0.0},
        {
            "delta_track_s_m": 0.0,
            "lateral_offset_m": 0.0,
            "heading_error_deg": 0.0,
            "track_width_m": 10.0,
            "terminated_off_track": False,
        },
    )
    assert reward < 0.0
    assert components["time"] < 0.0
    assert "progress" not in components
    assert "alignment" not in components


def test_frozen_policy_predicts_without_mutating_source() -> None:
    from gokart.rl.trainer import FrozenPolicy

    class _Policy:
        def __init__(self) -> None:
            self.training = True

        def set_training_mode(self, flag: bool) -> None:
            self.training = flag

        def predict(self, obs, deterministic=True):
            return np.array([1.0, 0.0], dtype=np.float32), None

    source = _Policy()
    frozen = FrozenPolicy(source)
    action, _ = frozen.predict(None, deterministic=True)
    assert action[0] == pytest.approx(1.0)
    assert source.training is True
    assert frozen.policy.training is False


def test_decode_rl_action_maps_accel_and_steer() -> None:
    throttle, brake, steering = decode_rl_action(np.array([-1.0, 0.5], dtype=np.float32))
    assert throttle == 0.0
    assert brake == pytest.approx(1.0)
    assert steering == pytest.approx(0.5)

    assist_throttle, assist_brake, _ = decode_rl_action(
        np.array([0.2, 0.0], dtype=np.float32),
        speed_mps=0.0,
    )
    assert assist_brake == 0.0
    assert assist_throttle == pytest.approx(0.2 + 0.8 * 0.2)

    moving_throttle, _, _ = decode_rl_action(
        np.array([0.2, 0.0], dtype=np.float32),
        speed_mps=2.0,
    )
    assert moving_throttle == pytest.approx(0.2)

    full_throttle, full_brake, _ = decode_rl_action(
        np.array([1.0, 0.0], dtype=np.float32), speed_mps=2.0
    )
    assert full_throttle == 1.0
    assert full_brake == 0.0

    coast_throttle, coast_brake, _ = decode_rl_action(
        np.array([0.0, 0.0], dtype=np.float32),
        speed_mps=2.0,
    )
    assert coast_throttle == 0.0
    assert coast_brake == 0.0

    hard_brake_throttle, hard_brake, _ = decode_rl_action(np.array([-0.9, 0.0], dtype=np.float32))
    assert hard_brake_throttle == 0.0
    assert hard_brake == pytest.approx(0.9)


def test_env_holds_each_decision_for_several_ticks(hairpin_track) -> None:
    env = make_env(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        track=hairpin_track,
        drive_mode="default",
        driver_profile="owner",
        objective="god",
        target_laps=99,
        max_steps=400,
    )
    env.reset()
    steps_before = env._drive_steps
    env.step(np.array([0.0, 1.0], dtype=np.float32))
    assert env._drive_steps - steps_before == env.setup.action.hold_ticks
    assert len(env.physics_tick_rows) == env.setup.action.hold_ticks
    _throttle, _brake, steering = env._last_policy_controls
    assert steering == pytest.approx(1.0)


def test_encode_expert_action_round_trips() -> None:
    encoded = encode_expert_action(0.7, 0.0, 0.25)
    throttle, brake, steering = decode_rl_action(encoded, speed_mps=5.0)
    assert throttle == pytest.approx(0.7)
    assert brake == pytest.approx(0.0)
    assert steering == pytest.approx(0.25)

    braked = encode_expert_action(0.0, 0.8, -0.4)
    throttle, brake, steering = decode_rl_action(braked, speed_mps=5.0)
    assert throttle == pytest.approx(0.0)
    assert brake == pytest.approx(0.8)
    assert steering == pytest.approx(-0.4)


def test_policy_key_includes_circuit_stack(hairpin_track) -> None:
    a = build_policy_identity(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        track_id=hairpin_track.id,
        drive_mode="default",
        driver_profile="owner",
        objective="god",
    )
    b = build_policy_identity(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        track_id=hairpin_track.id,
        drive_mode="default",
        driver_profile="owner",
        objective="god",
    )
    assert a.policy_key == b.policy_key
    assert len(a.policy_key) == 16
    assert a.stack == "circuit_v3"
    payload = a.to_dict()
    del payload["stack"]
    legacy = identity_from_dict(payload)
    assert legacy.stack == "legacy"
    assert legacy.policy_key != a.policy_key


def test_forward_drive_beats_start_line_u_turn() -> None:
    forward, _, forward_parts = _reward(
        _TICK,
        {
            "delta_track_s_m": 0.04,
            "lateral_offset_m": 0.2,
            "heading_error_deg": 5.0,
            "track_width_m": 10.0,
            "terminated_off_track": False,
        },
    )
    u_turn, _, u_turn_parts = _reward(
        {**_TICK, "steering": 0.9},
        {
            "delta_track_s_m": -0.01,
            "lateral_offset_m": 0.2,
            "heading_error_deg": 160.0,
            "track_width_m": 10.0,
            "terminated_off_track": False,
        },
    )
    assert forward > 0.0
    assert u_turn < 0.0
    assert forward > u_turn
    assert "progress" in forward_parts
    assert "reverse" in u_turn_parts
    assert "alignment" not in forward_parts
    assert "alignment" not in u_turn_parts


def test_off_track_is_penalized_and_does_not_pay_progress() -> None:
    _, _, components = _reward(
        _TICK,
        {
            "delta_track_s_m": 80.0,
            "lateral_offset_m": 12.0,
            "heading_error_deg": 20.0,
            "track_width_m": 10.0,
            "terminated_off_track": False,
        },
    )
    assert "progress" not in components
    assert "alignment" not in components
    assert components["off_track"] < 0.0


def test_reward_penalizes_reverse_track_progress() -> None:
    _, _, components = _reward(
        _TICK,
        {
            "delta_track_s_m": -0.2,
            "lateral_offset_m": 0.2,
            "heading_error_deg": 170.0,
            "track_width_m": 10.0,
            "terminated_off_track": False,
        },
    )
    assert components["reverse"] < 0.0
    assert "progress" not in components


def test_reward_pays_lap_bonus() -> None:
    state = RewardState(last_lap_number=1.0)
    reward, _, components = _reward(
        _TICK,
        {
            "delta_track_s_m": 0.04,
            "lateral_offset_m": 0.1,
            "heading_error_deg": 3.0,
            "track_width_m": 10.0,
            "lap_number": 2.0,
            "terminated_off_track": False,
        },
        state=state,
    )
    assert components["lap"] == pytest.approx(50.0)
    assert reward > 49.0


def test_faster_completed_lap_beats_slower_one() -> None:
    def _episode_reward(ticks: int, delta_s: float) -> float:
        state = RewardState(last_lap_number=1.0)
        total = 0.0
        for index in range(ticks):
            info = {
                "delta_track_s_m": delta_s,
                "lateral_offset_m": 1.5,
                "heading_error_deg": 18.0,
                "track_width_m": 10.0,
                "terminated_off_track": False,
                "lap_number": 2.0 if index == ticks - 1 else 1.0,
            }
            step_reward, state, _ = _reward(_TICK, info, state=state)
            total += step_reward
        return total

    same_distance_m = 16.0
    fast_ticks = 400
    slow_ticks = 800
    assert _episode_reward(fast_ticks, same_distance_m / fast_ticks) > _episode_reward(
        slow_ticks, same_distance_m / slow_ticks
    )


def test_using_track_width_is_not_penalized() -> None:
    center, _, center_parts = _reward(
        _TICK,
        {
            "delta_track_s_m": 0.04,
            "lateral_offset_m": 0.1,
            "heading_error_deg": 4.0,
            "track_width_m": 10.0,
            "terminated_off_track": False,
        },
    )
    apex, _, apex_parts = _reward(
        _TICK,
        {
            "delta_track_s_m": 0.04,
            "lateral_offset_m": 3.5,
            "heading_error_deg": 22.0,
            "track_width_m": 10.0,
            "terminated_off_track": False,
        },
    )
    assert center == pytest.approx(apex)
    assert center_parts["progress"] == pytest.approx(apex_parts["progress"])
    assert "alignment" not in center_parts
    assert "alignment" not in apex_parts


def test_observation_shape(hairpin_track) -> None:
    obs = build_observation(
        tick_values={
            "speed_mps": 8.0,
            "heading_deg": 45.0,
            "position_x_m": hairpin_track.centerline[0].x,
            "position_y_m": hairpin_track.centerline[0].y,
            "soc": 0.95,
            "battery_temp_c": 30.0,
            "motor_temp_c": 35.0,
            "derating_factor": 1.0,
            "torque_permitted": 1.0,
            "active_faults": "",
            "throttle": 0.4,
            "brake": 0.0,
            "steering": 0.1,
            "max_speed_mps": 12.5,
        },
        step_info={
            "track_s_m": 0.0,
            "lateral_offset_m": 0.0,
            "heading_error_deg": 5.0,
            "off_track": 0.0,
            "completed_laps": 0,
        },
        track=hairpin_track,
        target_laps=3,
        max_steps=5000,
        step_index=10,
    )
    assert obs.shape == (OBS_DIM,)
    assert np.isfinite(obs).all()
    assert obs[8] == pytest.approx(0.4)
    assert obs[9] == pytest.approx(0.0)
    assert obs[10] == pytest.approx(0.1)


def test_env_reset_and_step(hairpin_track) -> None:
    env = make_env(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        track=hairpin_track,
        drive_mode="default",
        driver_profile="owner",
        objective="god",
        target_laps=99,
        max_steps=500,
    )
    obs, info = env.reset()
    assert obs.shape == (OBS_DIM,)
    assert env.action_space.shape == (ACTION_DIM,)
    assert "safety_state" in info
    total_reward = 0.0
    for _ in range(50):
        action = env.action_space.sample()
        obs, reward, terminated, truncated, _info = env.step(action)
        total_reward += reward
        if terminated or truncated:
            break
    assert np.isfinite(total_reward)


def test_env_reset_starts_driving_without_boot_brake(hairpin_track) -> None:
    env = make_env(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        track=hairpin_track,
        drive_mode="default",
        driver_profile="owner",
        objective="god",
        target_laps=99,
        max_steps=500,
    )
    obs, info = env.reset()
    assert info["safety_state"] == "DRIVING"
    assert obs[8] == pytest.approx(0.0)
    assert obs[9] == pytest.approx(0.0)
    assert float(env.session.state.last_tick.values["brake"]) < 0.5


def test_mean_throttle_action_moves_after_reset(hairpin_track) -> None:
    env = make_env(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        track=hairpin_track,
        drive_mode="default",
        driver_profile="owner",
        objective="god",
        target_laps=99,
        max_steps=400,
    )
    env.reset()
    moved = False
    for _ in range(200):
        _obs, _reward, terminated, truncated, _info = env.step(
            np.array([0.8, 0.0], dtype=np.float32)
        )
        if float(env.session.state.vehicle_state.speed_mps) > 0.5:
            moved = True
            break
        if terminated or truncated:
            break
    assert moved


def test_rl_env_terminates_when_off_track(hairpin_track) -> None:
    env = make_env(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        track=hairpin_track,
        drive_mode="default",
        driver_profile="owner",
        objective="god",
        target_laps=3,
        max_steps=500,
    )
    env.reset()
    off_track = False
    terminated = False
    for _ in range(200):
        action = np.array([1.0, 1.0], dtype=np.float32)
        _obs, _reward, terminated, truncated, info = env.step(action)
        if info.get("off_track"):
            off_track = True
        if terminated or truncated:
            break
    assert off_track or env.session.state.step_index > 0
    if off_track:
        assert terminated


def test_rl_env_reaches_driving_with_brake_heavy_policy(hairpin_track) -> None:
    env = make_env(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        track=hairpin_track,
        drive_mode="default",
        driver_profile="owner",
        objective="god",
        target_laps=1,
        max_steps=400,
    )
    env.reset()
    driving_steps = 0
    for _ in range(200):
        _obs, _reward, terminated, truncated, _info = env.step(
            np.array([-0.8, 1.0], dtype=np.float32)
        )
        if env.session.state.safety_state.value == "DRIVING":
            driving_steps += 1
        if terminated or truncated:
            break
    assert driving_steps > 20


def test_expert_dataset_moves_forward(hairpin_track) -> None:
    from gokart.rl.demos import collect_expert_dataset

    env = make_env(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        track=hairpin_track,
        drive_mode="default",
        driver_profile="owner",
        objective="god",
        target_laps=99,
        max_steps=800,
    )
    observations, actions = collect_expert_dataset(env, steps=250)
    assert observations.shape == (250, OBS_DIM)
    assert actions.shape == (250, ACTION_DIM)
    assert float(np.mean(actions[:, 0])) > 0.05
    assert np.isfinite(observations).all()
    assert np.isfinite(actions).all()


def test_behavior_clone_fits_expert_mean(hairpin_track) -> None:
    from stable_baselines3 import PPO

    from gokart.rl.demos import behavior_clone, collect_expert_dataset

    env = make_env(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        track=hairpin_track,
        drive_mode="default",
        driver_profile="owner",
        objective="god",
        target_laps=99,
        max_steps=800,
    )
    observations, actions = collect_expert_dataset(env, steps=300)
    model = PPO("MlpPolicy", env, verbose=0, seed=0, n_steps=64, batch_size=64)
    loss = behavior_clone(model, observations, actions, epochs=3, batch_size=64)
    assert np.isfinite(loss)
    predicted, _ = model.predict(observations[:64], deterministic=True)
    predicted = np.asarray(predicted, dtype=np.float32)
    assert float(np.mean(predicted[:, 0])) > 0.0


def test_warm_start_can_be_skipped(hairpin_track) -> None:
    from stable_baselines3 import PPO

    from gokart.rl.trainer import TrainingConfig, _warm_start_from_expert
    from gokart.rl.training_setup import RlTrainingSetup

    env = make_env(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        track=hairpin_track,
        drive_mode="default",
        driver_profile="owner",
        objective="god",
        target_laps=1,
        max_steps=200,
    )
    model = PPO("MlpPolicy", env, verbose=0, seed=0, n_steps=64, batch_size=64)
    statuses: list[str] = []
    setup = RlTrainingSetup(warmup=WarmupConfig(demo_steps=0, bc_epochs=0))
    _warm_start_from_expert(
        model,
        config=TrainingConfig(
            vehicle_name="Scott Kart V1",
            vehicle_version="V1.0",
            track_id=hairpin_track.id,
        ),
        track=hairpin_track,
        setup=setup,
        should_stop=lambda: False,
        on_status=lambda status, **_kwargs: statuses.append(status),
    )
    assert statuses == []


def test_manifest_round_trip(tmp_path, hairpin_track) -> None:
    identity = build_policy_identity(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        track_id=hairpin_track.id,
        drive_mode="default",
        driver_profile="owner",
        objective="god",
    )
    manifest = PolicyManifest(identity=identity, status="training")
    path = save_manifest(manifest, root=tmp_path)
    assert path.exists()
    loaded = PolicyManifest.from_dict(__import__("json").loads(path.read_text(encoding="utf-8")))
    assert loaded.identity.policy_key == identity.policy_key
    assert loaded.identity.stack == "circuit_v3"
    assert loaded.reward_preset == "min_time_v1"


def test_run_preview_episode_records_full_episode(hairpin_track) -> None:
    from gokart.rl.trainer import TrainingConfig, run_preview_episode

    calls: list[bool] = []

    class _StubModel:
        def predict(self, obs, deterministic=True):
            calls.append(deterministic)
            return np.array([0.4, 0.05], dtype=np.float32), None

    recorded: list[dict] = []

    class _TickHooks:
        def on_progress(self, progress) -> None:
            return

        def on_preview_tick(self, row: dict) -> None:
            return

        def should_stop(self) -> bool:
            return False

        def start_preview_recording(self, *, timestep: int) -> str:
            return ""

        def finish_preview_recording(self) -> None:
            return

        def record_episode(
            self,
            *,
            ticks,
            timestep,
            kind="episode",
            episode_index=0,
            episode_reward=None,
        ) -> str:
            recorded.extend(ticks)
            return "preview-session"

    config = TrainingConfig(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        track_id=hairpin_track.id,
        target_laps=1,
    )
    lap, clean, reward, session_id = run_preview_episode(
        _StubModel(),
        config=config,
        track=hairpin_track,
        hooks=_TickHooks(),
        timestep=10_000,
        max_steps=400,
    )
    assert np.isfinite(reward)
    assert clean in {0.0, 1.0}
    assert session_id == "preview-session"
    assert calls
    assert all(flag is False for flag in calls)
    assert len(recorded) > 50
    assert "speed_mps" in recorded[0]


def test_episode_recording_env_flushes_on_done(hairpin_track) -> None:
    from stable_baselines3.common.monitor import Monitor

    from gokart.rl.episode_recording import EpisodeRecordingEnv

    episodes: list[list[dict]] = []

    env = make_env(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        track=hairpin_track,
        drive_mode="default",
        driver_profile="owner",
        objective="god",
        target_laps=99,
        max_steps=120,
    )
    env = EpisodeRecordingEnv(
        env,
        timestep_provider=lambda: 42,
        on_episode_complete=lambda ticks, episode_index, **_kwargs: episodes.append(ticks),
    )
    env = Monitor(env)
    obs, _ = env.reset()
    done = False
    while not done:
        action = env.action_space.sample()
        obs, _reward, terminated, truncated, _info = env.step(action)
        done = terminated or truncated
    assert episodes
    assert len(episodes[0]) > 10
    assert "speed_mps" in episodes[0][0]


def test_stream_training_tick_unwraps_monitor() -> None:
    from types import SimpleNamespace

    from gokart.rl.trainer import _stream_training_tick

    ticks: list[dict] = []

    class _Hooks:
        def on_progress(self, progress) -> None:
            return

        def on_preview_tick(self, row: dict) -> None:
            ticks.append(row)

        def should_stop(self) -> bool:
            return False

        def start_preview_recording(self, *, timestep: int) -> str:
            return ""

        def finish_preview_recording(self) -> None:
            return

        def record_episode(
            self, *, ticks, timestep, kind="episode", episode_index=0, episode_reward=None
        ) -> str:
            return ""

    inner = SimpleNamespace(
        session=SimpleNamespace(
            state=SimpleNamespace(last_tick=SimpleNamespace(to_row=lambda: {"speed_mps": 3.2}))
        )
    )
    vec = SimpleNamespace(envs=[SimpleNamespace(env=inner)])
    _stream_training_tick(vec, _Hooks())
    assert ticks == [{"speed_mps": 3.2}]
