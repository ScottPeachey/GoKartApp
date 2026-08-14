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
from gokart.rl.training_setup import training_setup_from_dict, training_setup_schema
from gokart.track.importer import import_geojson_track

FIXTURES = Path(__file__).parent / "fixtures"
HAIRPIN = FIXTURES / "test-hairpin.geojson"


@pytest.fixture
def hairpin_track():
    return import_geojson_track(HAIRPIN, track_id="test-hairpin", fetch_elevation=False)


def test_training_setup_from_dict_round_trip() -> None:
    schema = training_setup_schema()
    setup = training_setup_from_dict(schema["defaults"])
    assert setup.objective == "god"
    assert setup.ppo.ent_coef == pytest.approx(0.05)
    throttle_field = next(
        field for field in schema["sections"]["action"]["fields"] if field["key"] == "throttle_breakaway"
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
            "rewards": {"standstill": 0.5},
            "env": {"terminate_on_off_track": 0},
        }
    )
    assert custom.objective == "custom"
    assert custom.ppo.ent_coef == pytest.approx(0.1)
    assert custom.rewards.standstill == pytest.approx(0.5)
    assert custom.env.terminate_on_off_track is False


def test_reward_penalizes_stagnant_terminal() -> None:
    state = RewardState()
    reward, _, components = compute_reward(
        tick_values={
            "active_faults": "",
            "speed_mps": 0.0,
            "battery_temp_c": 30.0,
            "motor_temp_c": 35.0,
            "soc": 0.9,
            "throttle": 0.0,
            "brake": 0.0,
            "steering": 0.0,
            "max_speed_mps": 12.5,
            "derating_factor": 1.0,
            "torque_permitted": 1.0,
        },
        step_info={
            "delta_track_s_m": 0.0,
            "lateral_offset_m": 0.0,
            "heading_error_deg": 0.0,
            "track_width_m": 10.0,
            "battery_temp_derate_c": 50.0,
            "battery_temp_fault_c": 60.0,
            "truncated_stagnant": True,
        },
        weights=reward_preset("god"),
        dt_s=0.01,
        state=state,
        objective="god",
    )
    assert "stagnant_terminal" in components
    assert components["stagnant_terminal"] < 0.0
    assert reward < 0.0


def test_reward_penalizes_wall_hit_when_off_track_terminates() -> None:
    driving = {
        "active_faults": "",
        "safety_state": "DRIVING",
        "battery_temp_c": 30.0,
        "motor_temp_c": 35.0,
        "soc": 0.9,
        "throttle": 0.4,
        "brake": 0.0,
        "steering": 0.0,
        "max_speed_mps": 12.5,
        "derating_factor": 1.0,
        "torque_permitted": 1.0,
    }
    info = {
        "delta_track_s_m": 0.0,
        "lateral_offset_m": 8.0,
        "heading_error_deg": 20.0,
        "track_width_m": 10.0,
        "battery_temp_derate_c": 50.0,
        "battery_temp_fault_c": 60.0,
        "terminated_off_track": True,
    }
    _, _, slow_parts = compute_reward(
        tick_values={**driving, "speed_mps": 1.0},
        step_info=info,
        weights=reward_preset("god"),
        dt_s=0.01,
        state=RewardState(),
        objective="god",
    )
    _, _, fast_parts = compute_reward(
        tick_values={**driving, "speed_mps": 12.5},
        step_info=info,
        weights=reward_preset("god"),
        dt_s=0.01,
        state=RewardState(),
        objective="god",
    )
    assert slow_parts["wall_hit"] == pytest.approx(-80.0)
    assert fast_parts["wall_hit"] == pytest.approx(slow_parts["wall_hit"])
    assert "recover_track" not in slow_parts


def test_frozen_policy_predicts_without_mutating_source() -> None:
    from gokart.rl.trainer import FrozenPolicy

    class _Policy:
        def __init__(self) -> None:
            self.training = True

        def set_training_mode(self, flag: bool) -> None:
            self.training = flag

        def predict(self, obs, deterministic=True):
            return np.array([1.0, 0.0, 0.0], dtype=np.float32), None

    source = _Policy()
    frozen = FrozenPolicy(source)
    action, _ = frozen.predict(None, deterministic=True)
    assert action[0] == pytest.approx(1.0)
    assert source.training is True
    assert frozen.policy.training is False


def test_decode_rl_action_keeps_zero_throttle_at_zero() -> None:
    throttle, brake, steering = decode_rl_action(np.array([-1.0, 0.0, 0.5], dtype=np.float32))
    assert throttle == 0.0
    assert brake == 0.0
    assert steering == 0.5

    assist_throttle, _, _ = decode_rl_action(
        np.array([-0.6, 0.0, 0.0], dtype=np.float32),
        speed_mps=0.0,
    )
    assert assist_throttle == pytest.approx(0.32)

    moving_throttle, _, _ = decode_rl_action(
        np.array([-0.6, 0.0, 0.0], dtype=np.float32),
        speed_mps=2.0,
    )
    assert moving_throttle == pytest.approx(0.2)

    full_throttle, _, _ = decode_rl_action(np.array([1.0, 0.0, 0.0], dtype=np.float32), speed_mps=2.0)
    assert full_throttle == 1.0

    coast_throttle, coast_brake, _ = decode_rl_action(
        np.array([-0.6, 0.8, 0.0], dtype=np.float32),
        speed_mps=2.0,
    )
    assert coast_throttle == pytest.approx(0.2)
    assert coast_brake == pytest.approx(0.8)

    hard_brake_throttle, hard_brake, _ = decode_rl_action(np.array([0.0, 0.9, 0.0], dtype=np.float32))
    assert hard_brake_throttle == 0.0
    assert hard_brake == pytest.approx(0.9)


def test_cool_battery_does_not_reward_idling() -> None:
    state = RewardState()
    reward, _, components = compute_reward(
        tick_values={
            "active_faults": "",
            "safety_state": "DRIVING",
            "speed_mps": 0.0,
            "battery_temp_c": 25.0,
            "motor_temp_c": 25.0,
            "soc": 0.9,
            "throttle": 0.0,
            "brake": 0.0,
            "steering": 0.0,
            "max_speed_mps": 12.5,
            "derating_factor": 1.0,
            "torque_permitted": 1.0,
        },
        step_info={
            "delta_track_s_m": 0.0,
            "lateral_offset_m": 0.0,
            "heading_error_deg": 0.0,
            "track_width_m": 10.0,
            "battery_temp_derate_c": 50.0,
            "battery_temp_fault_c": 60.0,
            "terminated_off_track": False,
        },
        weights=reward_preset("god"),
        dt_s=0.01,
        state=state,
        objective="god",
    )
    assert components.get("battery_margin", 0.0) <= 0.0
    assert components.get("motor_margin", 0.0) <= 0.0
    assert reward < 0.0


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
    assert max_speed > 0.1


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


def test_reward_penalizes_standstill_on_track() -> None:
    state = RewardState()
    reward, _, components = compute_reward(
        tick_values={
            "active_faults": "",
            "speed_mps": 0.0,
            "battery_temp_c": 30.0,
            "motor_temp_c": 35.0,
            "soc": 0.9,
            "throttle": 0.0,
            "brake": 0.0,
            "steering": 1.0,
            "max_speed_mps": 12.5,
            "derating_factor": 1.0,
            "torque_permitted": 1.0,
        },
        step_info={
            "delta_track_s_m": 0.0,
            "lateral_offset_m": 0.0,
            "heading_error_deg": 0.0,
            "track_width_m": 10.0,
            "battery_temp_derate_c": 50.0,
            "battery_temp_fault_c": 60.0,
            "terminated_off_track": False,
        },
        weights=reward_preset("god"),
        dt_s=0.01,
        state=state,
        objective="god",
    )
    assert "standstill" in components
    assert components["standstill"] < 0.0
    assert "low_speed_steer" in components
    assert components["low_speed_steer"] < 0.0


def test_reward_penalizes_steering_while_off_track() -> None:
    state = RewardState()
    _, _, components = compute_reward(
        tick_values={
            "active_faults": "",
            "safety_state": "DRIVING",
            "speed_mps": 0.5,
            "battery_temp_c": 30.0,
            "motor_temp_c": 35.0,
            "soc": 0.9,
            "throttle": 0.0,
            "brake": 0.0,
            "steering": 1.0,
            "max_speed_mps": 12.5,
            "derating_factor": 1.0,
            "torque_permitted": 1.0,
        },
        step_info={
            "delta_track_s_m": 0.0,
            "lateral_offset_m": 8.0,
            "heading_error_deg": 90.0,
            "track_width_m": 10.0,
            "battery_temp_derate_c": 50.0,
            "battery_temp_fault_c": 60.0,
            "terminated_off_track": False,
        },
        weights=reward_preset("god"),
        dt_s=0.01,
        state=state,
        objective="god",
    )
    assert "low_speed_steer" in components
    assert components["low_speed_steer"] < 0.0
    assert "off_track" in components
    assert components["off_track"] < components["low_speed_steer"]


def test_reward_does_not_pay_speed_for_tightening_circles() -> None:
    state = RewardState()
    _, _, components = compute_reward(
        tick_values={
            "active_faults": "",
            "safety_state": "DRIVING",
            "speed_mps": 4.0,
            "battery_temp_c": 30.0,
            "motor_temp_c": 35.0,
            "soc": 0.9,
            "throttle": 0.6,
            "brake": 0.0,
            "steering": 0.9,
            "max_speed_mps": 12.5,
            "derating_factor": 1.0,
            "torque_permitted": 1.0,
        },
        step_info={
            "delta_track_s_m": 0.0,
            "lateral_offset_m": 0.2,
            "heading_error_deg": 8.0,
            "track_width_m": 10.0,
            "battery_temp_derate_c": 50.0,
            "battery_temp_fault_c": 60.0,
            "terminated_off_track": False,
        },
        weights=reward_preset("god"),
        dt_s=0.01,
        state=state,
        objective="god",
    )
    assert "speed" not in components
    assert "centerline" not in components
    assert "heading" not in components
    assert components["spin"] < 0.0


def test_off_track_penalty_scales_with_lateral_distance() -> None:
    state_near = RewardState()
    _, _, near = compute_reward(
        tick_values={
            "active_faults": "",
            "safety_state": "DRIVING",
            "speed_mps": 2.0,
            "battery_temp_c": 30.0,
            "motor_temp_c": 35.0,
            "soc": 0.9,
            "throttle": 0.0,
            "brake": 0.0,
            "steering": 0.0,
            "max_speed_mps": 12.5,
            "derating_factor": 1.0,
            "torque_permitted": 1.0,
        },
        step_info={
            "delta_track_s_m": 0.0,
            "lateral_offset_m": 6.0,
            "heading_error_deg": 0.0,
            "track_width_m": 10.0,
            "battery_temp_derate_c": 50.0,
            "battery_temp_fault_c": 60.0,
            "terminated_off_track": False,
        },
        weights=reward_preset("god"),
        dt_s=0.01,
        state=state_near,
        objective="god",
    )
    state_far = RewardState()
    _, _, far = compute_reward(
        tick_values={
            "active_faults": "",
            "safety_state": "DRIVING",
            "speed_mps": 2.0,
            "battery_temp_c": 30.0,
            "motor_temp_c": 35.0,
            "soc": 0.9,
            "throttle": 0.0,
            "brake": 0.0,
            "steering": 0.0,
            "max_speed_mps": 12.5,
            "derating_factor": 1.0,
            "torque_permitted": 1.0,
        },
        step_info={
            "delta_track_s_m": 0.0,
            "lateral_offset_m": 20.0,
            "heading_error_deg": 0.0,
            "track_width_m": 10.0,
            "battery_temp_derate_c": 50.0,
            "battery_temp_fault_c": 60.0,
            "terminated_off_track": False,
        },
        weights=reward_preset("god"),
        dt_s=0.01,
        state=state_far,
        objective="god",
    )
    assert near["off_track"] < 0.0
    assert far["off_track"] < near["off_track"]


def test_reward_recovers_toward_track_when_off_track() -> None:
    state = RewardState(prev_lateral_m=8.0)
    _, _, components = compute_reward(
        tick_values={
            "active_faults": "",
            "safety_state": "DRIVING",
            "speed_mps": 1.0,
            "battery_temp_c": 30.0,
            "motor_temp_c": 35.0,
            "soc": 0.9,
            "throttle": 0.4,
            "brake": 0.0,
            "steering": 0.0,
            "max_speed_mps": 12.5,
            "derating_factor": 1.0,
            "torque_permitted": 1.0,
        },
        step_info={
            "delta_track_s_m": 0.0,
            "lateral_offset_m": 6.0,
            "heading_error_deg": 0.0,
            "track_width_m": 10.0,
            "battery_temp_derate_c": 50.0,
            "battery_temp_fault_c": 60.0,
            "terminated_off_track": False,
        },
        weights=reward_preset("god"),
        dt_s=0.01,
        state=state,
        objective="god",
    )
    assert components.get("recover_track", 0.0) > 0.0


def test_reward_does_not_pay_progress_for_off_track_shortcuts() -> None:
    state = RewardState()
    _, _, components = compute_reward(
        tick_values={
            "active_faults": "",
            "safety_state": "DRIVING",
            "speed_mps": 4.0,
            "battery_temp_c": 30.0,
            "motor_temp_c": 35.0,
            "soc": 0.9,
            "throttle": 0.5,
            "brake": 0.0,
            "steering": 0.0,
            "max_speed_mps": 12.5,
            "derating_factor": 1.0,
            "torque_permitted": 1.0,
        },
        step_info={
            "delta_track_s_m": 80.0,
            "lateral_offset_m": 12.0,
            "heading_error_deg": 20.0,
            "track_width_m": 10.0,
            "battery_temp_derate_c": 50.0,
            "battery_temp_fault_c": 60.0,
            "terminated_off_track": False,
        },
        weights=reward_preset("god"),
        dt_s=0.01,
        state=state,
        objective="god",
    )
    assert "progress" not in components
    assert components["shortcut"] < 0.0


def test_reward_penalizes_reverse_track_progress() -> None:
    state = RewardState()
    _, _, components = compute_reward(
        tick_values={
            "active_faults": "",
            "safety_state": "DRIVING",
            "speed_mps": 3.0,
            "battery_temp_c": 30.0,
            "motor_temp_c": 35.0,
            "soc": 0.9,
            "throttle": 0.4,
            "brake": 0.0,
            "steering": 0.0,
            "max_speed_mps": 12.5,
            "derating_factor": 1.0,
            "torque_permitted": 1.0,
        },
        step_info={
            "delta_track_s_m": -0.2,
            "lateral_offset_m": 0.2,
            "heading_error_deg": 170.0,
            "track_width_m": 10.0,
            "battery_temp_derate_c": 50.0,
            "battery_temp_fault_c": 60.0,
            "terminated_off_track": False,
        },
        weights=reward_preset("god"),
        dt_s=0.01,
        state=state,
        objective="god",
    )
    assert components["reverse"] < 0.0
    assert "progress" not in components


def test_on_track_does_not_reward_returning_to_leave_point() -> None:
    state = RewardState(best_s_m=200.0, prev_lateral_m=8.0, was_off_track=True)
    driving = {
        "active_faults": "",
        "safety_state": "DRIVING",
        "speed_mps": 4.0,
        "battery_temp_c": 30.0,
        "motor_temp_c": 35.0,
        "soc": 0.9,
        "throttle": 0.5,
        "brake": 0.0,
        "steering": 0.0,
        "max_speed_mps": 12.5,
        "derating_factor": 1.0,
        "torque_permitted": 1.0,
    }
    _, state, on_track = compute_reward(
        tick_values=driving,
        step_info={
            "delta_track_s_m": 0.2,
            "track_s_m": 190.2,
            "track_length_m": 1000.0,
            "lateral_offset_m": 0.4,
            "heading_error_deg": 8.0,
            "track_width_m": 10.0,
            "battery_temp_derate_c": 50.0,
            "battery_temp_fault_c": 60.0,
            "terminated_off_track": False,
        },
        weights=reward_preset("god"),
        dt_s=0.01,
        state=state,
        objective="god",
    )
    assert "recover_track" not in on_track
    assert "progress" not in on_track
    assert state.best_s_m == pytest.approx(200.0)

    _, _, reverse_to_exit = compute_reward(
        tick_values=driving,
        step_info={
            "delta_track_s_m": -0.3,
            "track_s_m": 199.7,
            "track_length_m": 1000.0,
            "lateral_offset_m": 0.2,
            "heading_error_deg": 170.0,
            "track_width_m": 10.0,
            "battery_temp_derate_c": 50.0,
            "battery_temp_fault_c": 60.0,
            "terminated_off_track": False,
        },
        weights=reward_preset("god"),
        dt_s=0.01,
        state=RewardState(best_s_m=220.0, was_off_track=False),
        objective="god",
    )
    assert reverse_to_exit["reverse"] < 0.0
    assert "progress" not in reverse_to_exit
    assert "recover_track" not in reverse_to_exit


def test_wander_terminal_reward_applied() -> None:
    state = RewardState()
    _, _, components = compute_reward(
        tick_values={
            "active_faults": "",
            "safety_state": "DRIVING",
            "speed_mps": 2.0,
            "battery_temp_c": 30.0,
            "motor_temp_c": 35.0,
            "soc": 0.9,
            "throttle": 0.5,
            "brake": 0.0,
            "steering": 0.0,
            "max_speed_mps": 12.5,
            "derating_factor": 1.0,
            "torque_permitted": 1.0,
        },
        step_info={
            "delta_track_s_m": 0.0,
            "lateral_offset_m": 8.0,
            "heading_error_deg": 0.0,
            "track_width_m": 10.0,
            "battery_temp_derate_c": 50.0,
            "battery_temp_fault_c": 60.0,
            "truncated_off_track_wander": True,
        },
        weights=reward_preset("god"),
        dt_s=0.01,
        state=state,
        objective="god",
    )
    assert components["wander_terminal"] < 0.0


def test_default_setup_caps_off_track_wander() -> None:
    from gokart.rl.training_setup import default_training_setup

    setup = default_training_setup()
    assert setup.env.max_off_track_steps == 2500
    assert setup.rewards.off_track_lateral_cap == pytest.approx(2.0)
    assert setup.rewards.throttle_go > setup.rewards.standstill


def test_reward_prefers_centered_on_track_alignment() -> None:
    state = RewardState()
    reward, _, components = compute_reward(
        tick_values={
            "active_faults": "",
            "speed_mps": 6.0,
            "battery_temp_c": 30.0,
            "motor_temp_c": 35.0,
            "soc": 0.9,
            "throttle": 0.5,
            "brake": 0.0,
            "steering": 0.0,
            "max_speed_mps": 12.5,
            "derating_factor": 1.0,
            "torque_permitted": 1.0,
        },
        step_info={
            "delta_track_s_m": 0.4,
            "lateral_offset_m": 0.2,
            "heading_error_deg": 5.0,
            "track_width_m": 10.0,
            "battery_temp_derate_c": 50.0,
            "battery_temp_fault_c": 60.0,
            "terminated_off_track": False,
        },
        weights=reward_preset("god"),
        dt_s=0.01,
        state=state,
        objective="god",
    )
    assert reward > 0.0
    assert "centerline" in components
    assert "heading" in components
    assert "speed" in components


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
        action = np.array([-0.6, 0.8, 1.0], dtype=np.float32)
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


def test_run_preview_episode_records_full_episode(hairpin_track) -> None:
    from gokart.rl.trainer import TrainingConfig, run_preview_episode

    class _StubModel:
        def predict(self, obs, deterministic=True):
            return np.array([0.25, 0.0, 0.05], dtype=np.float32), None

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

        def record_episode(self, *, ticks, timestep, kind="episode", episode_index=0) -> str:
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
    assert len(recorded) > 50
    assert "speed_mps" in recorded[0]


def test_episode_recording_env_flushes_on_done(hairpin_track) -> None:
    from stable_baselines3.common.monitor import Monitor

    from gokart.rl.env import make_env
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
        on_episode_complete=lambda ticks, episode_index: episodes.append(ticks),
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

        def record_episode(self, *, ticks, timestep, kind="episode", episode_index=0) -> str:
            return ""

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
