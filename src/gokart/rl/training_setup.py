"""Dashboard-editable RL training setup (rewards, actions, env, PPO)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, get_type_hints

from gokart.rl.rewards import ENDURANCE_WEIGHTS, GOD_WEIGHTS, RewardWeights


@dataclass(frozen=True)
class ActionConfig:
    throttle_breakaway: float = 0.2
    standing_start_speed_mps: float = 0.25
    hold_ticks: int = 8


@dataclass(frozen=True)
class EnvRuntimeConfig:
    max_steps: int = 15_000
    target_laps: int = 1
    terminate_on_off_track: bool = False
    stagnant_delta_s: float = 0.01
    max_stagnant_steps: int = 250
    max_off_track_steps: int = 250


@dataclass(frozen=True)
class WarmupConfig:
    demo_steps: int = 2_000
    bc_epochs: int = 12


@dataclass(frozen=True)
class PpoConfig:
    learning_rate: float = 3e-4
    n_steps: int = 2048
    batch_size: int = 64
    ent_coef: float = 0.008
    gamma: float = 0.995


@dataclass(frozen=True)
class RlTrainingSetup:
    objective: str = "god"
    action: ActionConfig = ActionConfig()
    env: EnvRuntimeConfig = EnvRuntimeConfig()
    warmup: WarmupConfig = WarmupConfig()
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
    warmup = WarmupConfig(**_subset(data.get("warmup", {}), WarmupConfig))
    ppo = PpoConfig(**_subset(data.get("ppo", {}), PpoConfig))
    rewards = RewardWeights(**_subset(data.get("rewards", {}), RewardWeights))
    objective = str(data.get("objective", "god"))
    return RlTrainingSetup(
        objective=objective,
        action=action,
        env=env,
        warmup=warmup,
        ppo=ppo,
        rewards=rewards,
    )


def training_setup_to_dict(setup: RlTrainingSetup) -> dict[str, Any]:
    return {
        "objective": setup.objective,
        "action": asdict(setup.action),
        "env": asdict(setup.env),
        "warmup": asdict(setup.warmup),
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
    "action.hold_ticks": {"step": 1, "min": 1, "max": 20},
    "env.max_steps": {"step": 500, "min": 100, "max": 100_000},
    "env.target_laps": {"step": 1, "min": 1, "max": 50},
    "env.stagnant_delta_s": {"step": 0.0005, "min": 0, "max": 1},
    "env.max_stagnant_steps": {"step": 50, "min": 50, "max": 10_000},
    "env.max_off_track_steps": {"step": 50, "min": 0, "max": 20_000},
    "warmup.demo_steps": {"step": 1000, "min": 0, "max": 200_000},
    "warmup.bc_epochs": {"step": 1, "min": 0, "max": 100},
    "ppo.learning_rate": {"step": 0.00001, "min": 0.000001, "max": 0.01},
    "ppo.n_steps": {"step": 256, "min": 256, "max": 16_384},
    "ppo.batch_size": {"step": 32, "min": 32, "max": 2048},
    "ppo.ent_coef": {"step": 0.005, "min": 0, "max": 1},
    "ppo.gamma": {"step": 0.001, "min": 0.9, "max": 0.9999},
    "rewards.progress": {"step": 0.1, "min": 0, "max": 20},
    "rewards.time": {"step": 0.01, "min": 0, "max": 10},
    "rewards.reverse": {"step": 0.05, "min": 0, "max": 10},
    "rewards.off_track": {"step": 0.1, "min": 0, "max": 50},
    "rewards.wall": {"step": 1, "min": 0, "max": 50},
    "rewards.stagnant_terminal": {"step": 1, "min": 0, "max": 50},
    "rewards.off_track_wander": {"step": 1, "min": 0, "max": 50},
    "rewards.lap": {"step": 1, "min": 0, "max": 200},
    "rewards.thermal": {"step": 0.05, "min": 0, "max": 10},
    "rewards.thermal_fault": {"step": 1, "min": 0, "max": 50},
}


def training_setup_schema() -> dict[str, Any]:
    """Field metadata for the dashboard UI."""
    defaults = training_setup_to_dict(default_training_setup())

    def _section(
        cls: type,
        section_key: str,
        title: str,
        descriptions: dict[str, str],
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        hints = get_type_hints(cls)
        field_defs: list[dict[str, Any]] = []
        for field in fields(cls):
            is_bool = hints.get(field.name) is bool
            entry: dict[str, Any] = {
                "key": field.name,
                "label": (labels or {}).get(field.name, field.name.replace("_", " ")),
                "type": "bool" if is_bool else "number",
                "default": getattr(cls(), field.name),
                "description": descriptions.get(field.name, ""),
            }
            if not is_bool:
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
            "warmup": _section(
                WarmupConfig,
                "warmup",
                "Expert warmup",
                {
                    "demo_steps": (
                        "Expert decisions cloned before PPO. Each is held for Hold ticks."
                    ),
                    "bc_epochs": "Passes over those demos to copy expert steering and throttle.",
                },
                {
                    "demo_steps": "Expert decisions",
                    "bc_epochs": "Clone epochs",
                },
            ),
            "action": _section(
                ActionConfig,
                "action",
                "Action mapping",
                {
                    "throttle_breakaway": "Minimum throttle when asking for gas from a standstill.",
                    "standing_start_speed_mps": "Below this speed, standing-start assist is on.",
                    "hold_ticks": "Sim ticks (0.01 s) each decision is held. 8 = 80 ms.",
                },
                {
                    "hold_ticks": "Hold ticks",
                },
            ),
            "env": _section(
                EnvRuntimeConfig,
                "env",
                "Episode / environment",
                {
                    "max_steps": "Max ticks in one episode (0.01 s each). 15,000 = 150 seconds.",
                    "target_laps": (
                        "Stop after this many valid laps. 1 ends at the first real "
                        "finish-line crossing, not the start-line pass at spawn."
                    ),
                    "terminate_on_off_track": "End the episode when the kart leaves the track.",
                    "stagnant_delta_s": "Forward metres per tick below this count as not moving.",
                    "max_stagnant_steps": "Cut the episode after this many idle ticks (2.5 s).",
                    "max_off_track_steps": (
                        "If off-track terminate is off, cut after these ticks. 250 = 2.5 s."
                    ),
                },
                {
                    "max_steps": "Max ticks per episode",
                    "target_laps": "Laps before episode ends",
                    "max_stagnant_steps": "Idle ticks before cut",
                    "max_off_track_steps": "Off-track ticks before cut",
                },
            ),
            "ppo": _section(
                PpoConfig,
                "ppo",
                "PPO learner",
                {
                    "learning_rate": "Adam learning rate.",
                    "n_steps": "Ticks collected before one PPO update.",
                    "batch_size": "Minibatch size for PPO updates.",
                    "ent_coef": "Entropy bonus. Keep low so steering does not saturate randomly.",
                    "gamma": "Discount factor. 0.995 with 80 ms action holds looks ~8 s ahead.",
                },
            ),
            "rewards": _section(
                RewardWeights,
                "rewards",
                "Reward weights",
                {
                    "progress": "Bonus per metre of forward track. This is the main racing signal.",
                    "time": "Tiny per-second cost so a faster lap of equal distance scores more.",
                    "reverse": "Penalty per metre of backward progress.",
                    "off_track": "Per-second penalty while off the circuit.",
                    "wall": "One-shot cost when off-track terminate ends the episode.",
                    "stagnant_terminal": "Small one-shot cost when cut for not moving.",
                    "off_track_wander": (
                        "One-shot cost when the episode is cut after wandering off track."
                    ),
                    "lap": "Flat bonus for finishing a lap.",
                    "thermal": "Per-second cost as motor/controller temp goes from derate to trip.",
                    "thermal_fault": "One-shot cost when overtemp ends the episode.",
                },
            ),
        },
    }


def _subset(data: dict[str, Any], cls: type) -> dict[str, Any]:
    allowed = {field.name for field in fields(cls)}
    hints = get_type_hints(cls)
    coerced: dict[str, Any] = {}
    for key, value in data.items():
        if key not in allowed:
            continue
        if hints.get(key) is bool:
            coerced[key] = _as_bool(value)
        else:
            coerced[key] = value
    return coerced


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value)
