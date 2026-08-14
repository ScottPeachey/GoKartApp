"""Policy registry and training manifests."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from gokart.config.store import data_root
from gokart.rl.policy_key import PolicyIdentity, identity_from_dict, policy_dir

PolicyStatus = Literal["training", "ceiling_reached", "stale", "failed"]


@dataclass
class PolicyManifest:
    identity: PolicyIdentity
    status: PolicyStatus = "training"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    training_seed: int = 0
    sim_version: str = "0.1.0"
    reward_preset: str = "circuit_v2"
    ceiling_lap_s: float | None = None
    clean_lap_rate: float | None = None
    parent_policy_key: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["policy_key"] = self.identity.policy_key
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyManifest:
        nested = data.get("identity")
        if isinstance(nested, dict):
            identity = identity_from_dict(nested)
        else:
            identity = identity_from_dict(data)
        return cls(
            identity=identity,
            status=data.get("status", "training"),
            created_at=data.get("created_at", datetime.now(UTC).isoformat()),
            updated_at=data.get("updated_at", datetime.now(UTC).isoformat()),
            training_seed=int(data.get("training_seed", 0)),
            sim_version=data.get("sim_version", "0.1.0"),
            reward_preset=data.get("reward_preset", "circuit_v2"),
            ceiling_lap_s=data.get("ceiling_lap_s"),
            clean_lap_rate=data.get("clean_lap_rate"),
            parent_policy_key=data.get("parent_policy_key"),
            notes=data.get("notes", ""),
        )


def manifest_path(identity: PolicyIdentity, root: Path | None = None) -> Path:
    return policy_dir(identity, root=root) / "manifest.json"


def model_path(identity: PolicyIdentity, root: Path | None = None) -> Path:
    return policy_dir(identity, root=root) / "model.zip"


def save_manifest(manifest: PolicyManifest, root: Path | None = None) -> Path:
    path = manifest_path(manifest.identity, root=root)
    manifest.updated_at = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
    return path


def load_manifest(identity: PolicyIdentity, root: Path | None = None) -> PolicyManifest | None:
    path = manifest_path(identity, root=root)
    if not path.exists():
        return None
    return PolicyManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_policies(root: Path | None = None) -> list[PolicyManifest]:
    base = (root or data_root()) / "policies"
    if not base.exists():
        return []
    manifests: list[PolicyManifest] = []
    for entry in sorted(base.iterdir()):
        manifest_file = entry / "manifest.json"
        if manifest_file.is_file():
            manifests.append(
                PolicyManifest.from_dict(json.loads(manifest_file.read_text(encoding="utf-8")))
            )
    return manifests


def find_policy(
    *,
    vehicle_name: str,
    vehicle_version: str,
    track_id: str,
    drive_mode: str,
    driver_profile: str,
    objective: str,
    root: Path | None = None,
) -> PolicyManifest | None:
    from gokart.rl.policy_key import build_policy_identity

    identity = build_policy_identity(
        vehicle_name=vehicle_name,
        vehicle_version=vehicle_version,
        track_id=track_id,
        drive_mode=drive_mode,
        driver_profile=driver_profile,
        objective=objective,  # type: ignore[arg-type]
        root=root,
    )
    return load_manifest(identity, root=root)
