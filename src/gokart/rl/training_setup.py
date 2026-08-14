"""Dashboard-editable RL training setup (rewards, actions, env, PPO)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, get_type_hints

from gokart.rl.rewards import ENDURANCE_WEIGHTS, GOD_WEIGHTS, RewardWeights


@dataclass(frozen=True)
class ActionConfig:
    throttle_breakaway: float = 0.15
    standing_start_speed_mps: float = 0.15
    brake_cutoff: float = 0.85


@dataclass(frozen=True)
class EnvRuntimeConfig:
    max_steps: int = 12_000
    terminate_on_off_track: bool = True
    stagnant_speed_mps: float = 0.15
    stagnant_delta_s: float = 0.0005
    max_stagnant_steps: int = 500
    max_off_track_steps: int = 2500


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
    "env.max_off_track_steps": {"step": 250, "min": 0, "max": 20_000},
    "ppo.learning_rate": {"step": 0.00001, "min": 0.000001, "max": 0.01},
    "ppo.n_steps": {"step": 256, "min": 256, "max": 16_384},
    "ppo.batch_size": {"step": 32, "min": 32, "max": 2048},
    "ppo.ent_coef": {"step": 0.005, "min": 0, "max": 1},
    "ppo.gamma": {"step": 0.001, "min": 0.9, "max": 0.9999},
    "rewards.progress": {"step": 0.01, "min": 0, "max": 5},
    "rewards.centerline": {"step": 0.01, "min": 0, "max": 5},
    "rewards.heading": {"step": 0.01, "min": 0, "max": 5},
    "rewards.speed": {"step": 0.01, "min": 0, "max": 5},
    "rewards.forward_speed": {"step": 0.05, "min": 0, "max": 10},
    "rewards.standstill": {"step": 0.01, "min": 0, "max": 5},
    "rewards.throttle_go": {"step": 0.01, "min": 0, "max": 5},
    "rewards.low_speed_steer": {"step": 0.01, "min": 0, "max": 5},
    "rewards.spin": {"step": 0.05, "min": 0, "max": 5},
    "rewards.lap_bonus": {"step": 1, "min": 0, "max": 500},
    "rewards.fault_block": {"step": 1, "min": 0, "max": 500},
    "rewards.fault_derate": {"step": 1, "min": 0, "max": 500},
    "rewards.off_track_rate": {"step": 0.1, "min": 0, "max": 50},
    "rewards.off_track_lateral_cap": {"step": 0.1, "min": 1, "max": 10},
    "rewards.off_track_progress": {"step": 0.01, "min": 0, "max": 1},
    "rewards.recover_track": {"step": 0.05, "min": 0, "max": 5},
    "rewards.heading_off_track": {"step": 0.01, "min": 0, "max": 5},
    "rewards.reverse": {"step": 0.05, "min": 0, "max": 5},
    "rewards.wrong_way": {"step": 0.05, "min": 0, "max": 10},
    "rewards.shortcut": {"step": 0.1, "min": 0, "max": 50},
    "rewards.max_progress_delta_m": {"step": 0.1, "min": 0.05, "max": 20},
    "rewards.off_track_terminal": {"step": 1, "min": 0, "max": 500},
    "rewards.wander_terminal": {"step": 1, "min": 0, "max": 500},
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
                    "max_steps": "How long ONE episode may last, in sim ticks (0.01 s each). 12,000 = 120 seconds, not 'record every 12,000 training steps'.",
                    "terminate_on_off_track": "End the episode as soon as the kart leaves the track (like hitting a wall). Applies the wall-hit penalty on that tick.",
                    "stagnant_speed_mps": "Speed below this counts as not moving.",
                    "stagnant_delta_s": "Forward progress below this counts as stagnant.",
                    "max_stagnant_steps": "End the episode after this many ticks with no forward track progress — sitting still OR circling in place (~ticks × 0.01 s).",
                    "max_off_track_steps": "When off-track termination is off, end the episode after this many consecutive off-track ticks (0 = unlimited). Caps penalty from long wanders.",
                },
                {
                    "max_steps": "Max ticks per episode",
                    "max_stagnant_steps": "Idle/spin ticks before cut",
                    "max_off_track_steps": "Off-track ticks before cut",
                },
            ),
            "ppo": _section(
                PpoConfig,
                "ppo",
                "PPO learner",
                {
                    "learning_rate": "Adam learning rate.",
                    "n_steps": "How many ticks PPO collects before one learning update (not recording frequency).",
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
                    "speed": "Small extra speed bonus while facing along the circuit.",
                    "forward_speed": "Speed along the circuit; negative if it turns around.",
                    "standstill": "Penalty per second while stopped on track.",
                    "throttle_go": "Bonus for throttle while slow and facing forward.",
                    "low_speed_steer": "Penalty for large steering at low speed.",
                    "spin": "Penalty for steering hard while making no forward track progress (donuts / tightening circles).",
                    "heading_off_track": "Keep at 0. Off-track heading bonuses can reward spinning to face a nearby stretch.",
                    "lap_bonus": "Bonus for a clean completed lap.",
                    "off_track_rate": "Per-second penalty while off track; scales with distance beyond the edge up to the lateral cap.",
                    "off_track_lateral_cap": "Maximum lateral-distance multiplier for the off-track penalty (limits damage from one long wander).",
                    "off_track_progress": "Fraction of on-track progress still paid while off track. Keep at 0 so infield shortcuts are not rewarded.",
                    "recover_track": "Off-track only: reward per metre back toward the stretch you left. Stops the instant you are on the circuit again.",
                    "reverse": "Penalty per metre of backward circuit progress. Stronger on track so the kart cannot reverse to the leave-point.",
                    "wrong_way": "Penalty for facing more than 90° from circuit direction.",
                    "shortcut": "Penalty when track progress jumps more than max_progress_delta_m in one tick (snapping to another section).",
                    "max_progress_delta_m": "Largest along-track jump counted as real progress in one 0.01 s tick. Bigger jumps are treated as shortcuts.",
                    "off_track_terminal": "Wall-hit cost. Keep ~12; 80+ makes sitting still better than driving.",
                    "wander_terminal": "One-shot penalty when episode ends from the off-track wander limit.",
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
