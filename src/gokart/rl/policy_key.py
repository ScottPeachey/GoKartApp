"""RL policy key generation and manifest metadata."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Literal

from gokart.config.hashing import content_hash
from gokart.config.store import data_root, load_vehicle

SessionObjective = Literal["god", "endurance"]


@dataclass(frozen=True)
class PolicyIdentity:
    vehicle_name: str
    vehicle_version: str
    config_hash: str
    track_id: str
    drive_mode: str
    driver_profile: str
    objective: SessionObjective
    stack: str = "circuit_v4"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @property
    def policy_key(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_policy_identity(
    *,
    vehicle_name: str,
    vehicle_version: str,
    track_id: str,
    drive_mode: str,
    driver_profile: str,
    objective: SessionObjective,
    root: Path | None = None,
) -> PolicyIdentity:
    vehicle = load_vehicle(vehicle_name, vehicle_version, root=root or data_root())
    return PolicyIdentity(
        vehicle_name=vehicle_name,
        vehicle_version=vehicle_version,
        config_hash=content_hash(vehicle.model_dump(mode="json")),
        track_id=track_id,
        drive_mode=drive_mode,
        driver_profile=driver_profile,
        objective=objective,
        stack="circuit_v4",
    )


def identity_from_dict(data: dict[str, Any]) -> PolicyIdentity:
    allowed = {item.name for item in fields(PolicyIdentity)}
    payload = {key: value for key, value in data.items() if key in allowed}
    if "stack" not in data:
        payload["stack"] = "legacy"
    return PolicyIdentity(**payload)


def policy_dir(identity: PolicyIdentity, root: Path | None = None) -> Path:
    base = (root or data_root()) / "policies" / identity.policy_key
    base.mkdir(parents=True, exist_ok=True)
    return base
