"""Dashboard-editable RL training setup (rewards, actions, env, PPO)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

from gokart.rl.rewards import ENDURANCE_WEIGHTS, GOD_WEIGHTS, RewardWeights


@dataclass(frozen=True)
class ActionConfig:
    throttle_breakaway: float = 0.0
    standing_start_speed_mps: float = 0.15
    brake_cutoff: float = 0.85


@dataclass(frozen=True)
class EnvRuntimeConfig:
    max_steps: int = 12_000
    terminate_on_off_track: bool = True
    stagnant_speed_mps: float = 0.15
    stagnant_delta_s: float = 0.0005
    max_stagnant_steps: int = 500


@dataclass(frozen=True)
class PpoConfig:
    learning_rate: float = 3e-4
    n_steps: int = 2048
    batch_size: int = 64
    ent_coef: float = 0.05
    gamma: float = 0.999


@dataclass(frozen=True)
class RlTrainingSetup:
    objective: str = "god"
    action: ActionConfig = ActionConfig()
    env: EnvRuntimeConfig = EnvRuntimeConfig()
    ppo: PpoConfig = PpoConfig()
    rewards: RewardWeights = GOD_WEIGHTS

    def resolved_rewards(self) -> RewardWeights:
        return self.rewards


def default_training_setup() -> RlTrainingSetup:
    return RlTrainingSetup()


def training_setup_from_dict(data: dict[str, Any] | None) -> RlTrainingSetup:
    if not data:
        return default_training_setup()
    action = ActionConfig(**_subset(data.get("action", {}), ActionConfig))
    env = EnvRuntimeConfig(**_subset(data.get("env", {}), EnvRuntimeConfig))
    ppo = PpoConfig(**_subset(data.get("ppo", {}), PpoConfig))
    rewards = RewardWeights(**_subset(data.get("rewards", {}), RewardWeights))
    objective = str(data.get("objective", "god"))
    return RlTrainingSetup(objective=objective, action=action, env=env, ppo=ppo, rewards=rewards)


def training_setup_to_dict(setup: RlTrainingSetup) -> dict[str, Any]:
    return {
        "objective": setup.objective,
        "action": asdict(setup.action),
        "env": asdict(setup.env),
        "ppo": asdict(setup.ppo),
        "rewards": asdict(setup.rewards),
    }


def reward_preset_dict(objective: str) -> dict[str, float]:
    if objective == "endurance":
        return asdict(ENDURANCE_WEIGHTS)
    return asdict(GOD_WEIGHTS)


_NUMBER_FIELD_META: dict[str, dict[str, float | int]] = {
    "action.throttle_breakaway": {"step": 0.05, "min": 0, "max": 1},
    "action.standing_start_speed_mps": {"step": 0.05, "min": 0, "max": 5},
    "action.brake_cutoff": {"step": 0.05, "min": 0, "max": 1},
    "env.max_steps": {"step": 500, "min": 100, "max": 100_000},
    "env.stagnant_speed_mps": {"step": 0.01, "min": 0, "max": 2},
    "env.stagnant_delta_s": {"step": 0.0001, "min": 0, "max": 1},
    "env.max_stagnant_steps": {"step": 50, "min": 50, "max": 10_000},
    "ppo.learning_rate": {"step": 0.00001, "min": 0.000001, "max": 0.01},
    "ppo.n_steps": {"step": 256, "min": 256, "max": 16_384},
    "ppo.batch_size": {"step": 32, "min": 32, "max": 2048},
    "ppo.ent_coef": {"step": 0.005, "min": 0, "max": 1},
    "ppo.gamma": {"step": 0.001, "min": 0.9, "max": 0.9999},
    "rewards.progress": {"step": 0.01, "min": 0, "max": 5},
    "rewards.centerline": {"step": 0.01, "min": 0, "max": 5},
    "rewards.heading": {"step": 0.01, "min": 0, "max": 5},
    "rewards.speed": {"step": 0.01, "min": 0, "max": 5},
    "rewards.standstill": {"step": 0.01, "min": 0, "max": 5},
    "rewards.throttle_go": {"step": 0.01, "min": 0, "max": 5},
    "rewards.low_speed_steer": {"step": 0.01, "min": 0, "max": 5},
    "rewards.lap_bonus": {"step": 1, "min": 0, "max": 500},
    "rewards.fault_block": {"step": 1, "min": 0, "max": 500},
    "rewards.fault_derate": {"step": 1, "min": 0, "max": 500},
    "rewards.off_track_rate": {"step": 0.1, "min": 0, "max": 50},
    "rewards.off_track_terminal": {"step": 1, "min": 0, "max": 500},
    "rewards.stagnant_terminal": {"step": 1, "min": 0, "max": 500},
    "rewards.battery_margin": {"step": 0.01, "min": 0, "max": 5},
    "rewards.motor_margin": {"step": 0.01, "min": 0, "max": 5},
    "rewards.soc_margin": {"step": 0.01, "min": 0, "max": 5},
    "rewards.jerk": {"step": 0.01, "min": 0, "max": 5},
    "rewards.throttle_brake_overlap": {"step": 0.1, "min": 0, "max": 50},
    "rewards.time_penalty": {"step": 0.005, "min": 0, "max": 1},
}


def training_setup_schema() -> dict[str, Any]:
    """Field metadata for the dashboard UI."""
    defaults = training_setup_to_dict(default_training_setup())

    def _section(
        cls: type,
        section_key: str,
        title: str,
        descriptions: dict[str, str],
    ) -> dict[str, Any]:
        field_defs: list[dict[str, Any]] = []
        for field in fields(cls):
            entry: dict[str, Any] = {
                "key": field.name,
                "type": "bool" if field.type is bool else "number",
                "default": getattr(cls(), field.name),
                "description": descriptions.get(field.name, ""),
            }
            if field.type is not bool:
                entry.update(_NUMBER_FIELD_META.get(f"{section_key}.{field.name}", {"step": 0.01}))
            field_defs.append(entry)
        return {
            "title": title,
            "fields": field_defs,
        }

    return {
        "objectives": [
            {"id": "god", "label": "God mode (balanced)"},
            {"id": "endurance", "label": "Endurance (SOC focus)"},
            {"id": "custom", "label": "Custom reward weights"},
        ],
        "defaults": defaults,
        "reward_presets": {
            "god": reward_preset_dict("god"),
            "endurance": reward_preset_dict("endurance"),
        },
        "sections": {
            "action": _section(
                ActionConfig,
                "action",
                "Action mapping",
                {
                    "throttle_breakaway": "Minimum throttle applied when the policy requests gas from a standstill.",
                    "standing_start_speed_mps": "Below this speed, standing-start assist is active.",
                    "brake_cutoff": "Brake input above this cancels throttle (0–1).",
                },
            ),
            "env": _section(
                EnvRuntimeConfig,
                "env",
                "Episode / environment",
                {
                    "max_steps": "Maximum ticks per episode before truncation.",
                    "terminate_on_off_track": "End episode when the kart leaves the track.",
                    "stagnant_speed_mps": "Speed below this counts as not moving.",
                    "stagnant_delta_s": "Forward progress below this counts as stagnant.",
                    "max_stagnant_steps": "End episode after this many stagnant ticks (~steps × 0.01 s).",
                },
            ),
            "ppo": _section(
                PpoConfig,
                "ppo",
                "PPO learner",
                {
                    "learning_rate": "Adam learning rate.",
                    "n_steps": "Rollout length per policy update.",
                    "batch_size": "Minibatch size for PPO updates.",
                    "ent_coef": "Entropy bonus — higher explores more (try 0.01–0.1).",
                    "gamma": "Discount factor. At 100 Hz use ~0.999 so rewards more than a second ahead still matter.",
                },
            ),
            "rewards": _section(
                RewardWeights,
                "rewards",
                "Reward weights",
                {
                    "progress": "Reward per metre of forward track progress.",
                    "centerline": "Shaping for staying near centre line.",
                    "heading": "Shaping for aligning with track heading.",
                    "speed": "Reward for speed while on track.",
                    "standstill": "Penalty per second while stopped on track.",
                    "throttle_go": "Bonus for applying throttle while slow.",
                    "low_speed_steer": "Penalty for large steering at low speed.",
                    "lap_bonus": "Bonus for a clean completed lap.",
                    "off_track_rate": "Per-second penalty while off track.",
                    "off_track_terminal": "One-shot penalty when episode ends off track.",
                    "stagnant_terminal": "One-shot penalty when episode ends from standing still too long.",
                    "time_penalty": "Per-second living cost.",
                    "jerk": "Penalty for abrupt control changes.",
                    "throttle_brake_overlap": "Penalty for overlapping throttle and brake.",
                },
            ),
        },
    }


def _subset(data: dict[str, Any], cls: type) -> dict[str, Any]:
    allowed = {field.name for field in fields(cls)}
    return {key: value for key, value in data.items() if key in allowed}
