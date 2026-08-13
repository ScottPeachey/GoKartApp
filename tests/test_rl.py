"""RL driver tests (no full training run)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from gokart.rl.actions import decode_rl_action
from gokart.rl.env import make_env
from gokart.rl.observations import OBS_DIM, build_observation
from gokart.rl.policy_key import build_policy_identity
from gokart.rl.registry import PolicyManifest, save_manifest
from gokart.rl.rewards import RewardState, compute_reward, reward_preset
from gokart.track.importer import import_geojson_track

FIXTURES = Path(__file__).parent / "fixtures"
HAIRPIN = FIXTURES / "test-hairpin.geojson"


@pytest.fixture
def hairpin_track():
    return import_geojson_track(HAIRPIN, track_id="test-hairpin", fetch_elevation=False)


def test_decode_rl_action_maps_low_throttle_to_breakaway() -> None:
    throttle, brake, steering = decode_rl_action(np.array([0.0, 0.0, 0.5], dtype=np.float32))
    assert throttle == pytest.approx(0.25)
    assert brake == 0.0
    assert steering == 0.5

    coast_throttle, coast_brake, _ = decode_rl_action(np.array([0.2, 0.8, 0.0], dtype=np.float32))
    assert coast_throttle == 0.0
    assert coast_brake == pytest.approx(0.8)


def test_untrained_policy_can_move_from_standstill(hairpin_track) -> None:
    from stable_baselines3 import PPO

    env = make_env(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        track=hairpin_track,
        drive_mode="default",
        driver_profile="owner",
        objective="god",
        target_laps=1,
        max_steps=900,
    )
    model = PPO("MlpPolicy", env, verbose=0, seed=0, n_steps=256, batch_size=64)
    obs, _ = env.reset()
    max_speed = 0.0
    for _ in range(900):
        action, _ = model.predict(obs, deterministic=True)
        obs, *_ = env.step(action)
        tick = env.session.state.last_tick
        if tick is not None:
            max_speed = max(max_speed, float(tick.values.get("speed_mps", 0.0)))
    assert max_speed > 0.25


def test_policy_key_stable(hairpin_track) -> None:
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


def test_reward_penalizes_blocking_fault() -> None:
    state = RewardState()
    reward, _, components = compute_reward(
        tick_values={
            "active_faults": "BATTERY_OVERTEMP",
            "speed_mps": 5.0,
            "battery_temp_c": 65.0,
            "motor_temp_c": 40.0,
            "soc": 0.9,
            "throttle": 0.5,
            "brake": 0.0,
            "steering": 0.0,
            "max_speed_mps": 12.5,
            "derating_factor": 0.5,
            "torque_permitted": 0.0,
        },
        step_info={
            "delta_track_s_m": 0.5,
            "lateral_offset_m": 0.0,
            "track_width_m": 10.0,
            "battery_temp_derate_c": 50.0,
            "battery_temp_fault_c": 60.0,
        },
        weights=reward_preset("god"),
        dt_s=0.01,
        state=state,
        objective="god",
    )
    assert reward < 0.0
    assert "blocking" in components


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
            "off_track": 0.0,
            "battery_temp_derate_c": 50.0,
            "battery_temp_fault_c": 60.0,
            "completed_laps": 0,
        },
        track=hairpin_track,
        target_laps=3,
        max_steps=5000,
        step_index=10,
    )
    assert obs.shape == (OBS_DIM,)
    assert np.isfinite(obs).all()


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
    assert "safety_state" in info
    total_reward = 0.0
    for _ in range(50):
        action = env.action_space.sample()
        obs, reward, terminated, truncated, _info = env.step(action)
        total_reward += reward
        if terminated or truncated:
            break
    assert np.isfinite(total_reward)


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
    for _ in range(200):
        action = np.array([1.0, 0.0, 1.0], dtype=np.float32)
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
        max_steps=800,
    )
    obs, _ = env.reset()
    driving_steps = 0
    for _ in range(800):
        action = np.array([0.2, 0.8, 1.0], dtype=np.float32)
        obs, _reward, terminated, truncated, _info = env.step(action)
        if env.session.state.safety_state.value == "DRIVING":
            driving_steps += 1
        if terminated or truncated:
            break
    assert driving_steps > 100


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
    loaded = PolicyManifest.from_dict(
        __import__("json").loads(path.read_text(encoding="utf-8"))
    )
    assert loaded.identity.policy_key == identity.policy_key


def test_run_preview_episode_with_stub_model(hairpin_track) -> None:
    from gokart.rl.trainer import TrainingConfig, run_preview_episode

    class _StubModel:
        def predict(self, obs, deterministic=True):
            return np.array([0.25, 0.0, 0.05], dtype=np.float32), None

    ticks: list[dict] = []

    class _TickHooks:
        def on_progress(self, progress) -> None:
            return

        def on_preview_tick(self, row: dict) -> None:
            ticks.append(row)

        def should_stop(self) -> bool:
            return False

    config = TrainingConfig(
        vehicle_name="Scott Kart V1",
        vehicle_version="V1.0",
        track_id=hairpin_track.id,
        preview_log_every_n=5,
        target_laps=1,
    )
    lap, clean, reward = run_preview_episode(
        _StubModel(),
        config=config,
        track=hairpin_track,
        hooks=_TickHooks(),
        timestep=10_000,
        max_steps=400,
    )
    assert np.isfinite(reward)
    assert clean in {0.0, 1.0}
    assert len(ticks) > 0
    assert "speed_mps" in ticks[0]


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

    inner = SimpleNamespace(
        session=SimpleNamespace(
            state=SimpleNamespace(
                last_tick=SimpleNamespace(to_row=lambda: {"speed_mps": 3.2})
            )
        )
    )
    vec = SimpleNamespace(envs=[SimpleNamespace(env=inner)])
    _stream_training_tick(vec, _Hooks())
    assert ticks == [{"speed_mps": 3.2}]
