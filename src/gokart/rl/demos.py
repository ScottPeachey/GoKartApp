"""Expert demonstrations from the rule-based driver, then behaviour cloning."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from gokart.driver.agent import DriverConfig, RuleBasedDriver
from gokart.rl.actions import encode_expert_action
from gokart.rl.env import TrackRacingEnv


def make_expert_driver(env: TrackRacingEnv) -> RuleBasedDriver:
    session = env.session
    return RuleBasedDriver(
        session.config.track,
        DriverConfig(
            grip_coefficient=session.vehicle_model.grip_coefficient,
            max_speed_mps=session.base_limits.max_speed_mps,
            wheelbase_m=session.vehicle_model.config.wheelbase_m,
            aggression=session.config.aggression,
            battery_temp_derate_c=session.safety_config.battery_temp_derate_c,
            battery_temp_fault_c=session.safety_config.battery_temp_fault_c,
        ),
    )


def collect_expert_dataset(
    env: TrackRacingEnv,
    *,
    steps: int,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Roll the rule-based driver through the RL env and record (obs, action)."""
    if steps <= 0:
        empty_obs = np.zeros((0, int(env.observation_space.shape[0])), dtype=np.float32)
        empty_act = np.zeros((0, int(env.action_space.shape[0])), dtype=np.float32)
        return empty_obs, empty_act

    driver = make_expert_driver(env)
    observations: list[np.ndarray] = []
    actions: list[np.ndarray] = []
    obs, _ = env.reset()
    driver.reset_progress()
    stop = should_stop or (lambda: False)

    for _ in range(steps):
        if stop():
            break
        action = _expert_policy_action(env, driver)
        observations.append(np.asarray(obs, dtype=np.float32))
        actions.append(action)
        obs, _reward, terminated, truncated, _info = env.step(action)
        if terminated or truncated:
            obs, _ = env.reset()
            driver.reset_progress()

    return np.stack(observations), np.stack(actions)


def _expert_policy_action(env: TrackRacingEnv, driver: RuleBasedDriver) -> np.ndarray:
    vehicle = env.session.state.vehicle_state
    if vehicle is None:
        return np.zeros(int(env.action_space.shape[0]), dtype=np.float32)
    battery_soc = vehicle.battery.soc if vehicle.battery else 1.0
    battery_temp = (
        vehicle.battery_thermal.temperature_c if vehicle.battery_thermal is not None else 25.0
    )
    expert = driver.step(
        x=vehicle.position_x_m,
        y=vehicle.position_y_m,
        heading_rad=vehicle.heading_rad,
        speed_mps=vehicle.speed_mps,
        soc=battery_soc,
        battery_temp_c=battery_temp,
        dt=env.session_config.dt_s,
    )
    return encode_expert_action(expert.throttle, expert.brake, expert.steering)


def behavior_clone(
    model: Any,
    observations: np.ndarray,
    actions: np.ndarray,
    *,
    epochs: int,
    batch_size: int = 256,
    on_epoch: Callable[[int, float], None] | None = None,
) -> float:
    """Fit the PPO policy mean to expert actions with supervised MSE."""
    if epochs <= 0 or observations.shape[0] == 0:
        return 0.0

    import torch
    import torch.nn.functional as functional

    policy = model.policy
    device = model.device
    n = int(observations.shape[0])
    last_loss = 0.0
    batch = max(1, min(batch_size, n))

    for epoch in range(epochs):
        order = np.random.permutation(n)
        losses: list[float] = []
        for start in range(0, n, batch):
            index = order[start : start + batch]
            obs_batch = observations[index]
            act_batch = torch.as_tensor(actions[index], device=device, dtype=torch.float32)
            obs_tensor, _ = policy.obs_to_tensor(obs_batch)
            distribution = policy.get_distribution(obs_tensor)
            mean = distribution.mode()
            loss = functional.mse_loss(mean, act_batch)
            policy.optimizer.zero_grad()
            loss.backward()
            policy.optimizer.step()
            losses.append(float(loss.detach().item()))
        last_loss = float(np.mean(losses)) if losses else 0.0
        if on_epoch is not None:
            on_epoch(epoch, last_loss)
    return last_loss
