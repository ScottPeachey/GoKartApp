"""Load, save, and list configuration records on disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from gokart.config.hashing import content_hash
from gokart.config.schemas import (
    COMPONENT_TYPE_MAP,
    CalibrationSet,
    ComponentBase,
    DriveMode,
    DriverProfile,
    VehicleConfig,
)

T = TypeVar("T", bound=BaseModel)

DEFAULT_DATA_ROOT = Path("data")


def _bundled_data_root() -> Path:
    return Path(__file__).resolve().parents[3] / DEFAULT_DATA_ROOT


def data_root(root: Path | None = None) -> Path:
    if root is not None:
        return root
    cwd_data = Path.cwd() / DEFAULT_DATA_ROOT
    if (cwd_data / "vehicles").is_dir():
        return cwd_data
    bundled = _bundled_data_root()
    if (bundled / "vehicles").is_dir():
        return bundled
    return cwd_data


class ConfigStoreError(Exception):
    """Raised when a configuration cannot be loaded or saved."""


class ImmutableConfigError(ConfigStoreError):
    """Raised when an existing configuration would be overwritten."""


def _component_path(root: Path, component_type: str, component_id: str) -> Path:
    return root / "components" / component_type / f"{component_id}.json"


def _vehicle_path(root: Path, name: str, version: str) -> Path:
    safe_name = name.replace(" ", "_")
    return root / "vehicles" / safe_name / f"{version}.json"


def _drive_mode_path(root: Path, name: str) -> Path:
    return root / "drive_modes" / f"{name.lower()}.json"


def _driver_profile_path(root: Path, name: str) -> Path:
    return root / "driver_profiles" / f"{name.lower()}.json"


def _calibration_path(root: Path, name: str, version: str) -> Path:
    safe_name = name.replace(" ", "_")
    return root / "calibration" / safe_name / f"{version}.json"


def _write_json(path: Path, model: BaseModel, *, allow_overwrite: bool = False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not allow_overwrite:
        raise ImmutableConfigError(f"Refusing to overwrite existing config at {path}")
    payload = model.model_dump(mode="json")
    digest = content_hash(payload)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return digest


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise ConfigStoreError(f"Configuration not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_component(
    component: ComponentBase,
    *,
    root: Path | None = None,
    allow_overwrite: bool = False,
) -> str:
    component_type = component.component_type
    path = _component_path(data_root(root), component_type, component.id)
    return _write_json(path, component, allow_overwrite=allow_overwrite)


def load_component(
    component_type: str,
    component_id: str,
    *,
    root: Path | None = None,
) -> ComponentBase:
    if component_type not in COMPONENT_TYPE_MAP:
        raise ConfigStoreError(f"Unknown component type: {component_type}")
    path = _component_path(data_root(root), component_type, component_id)
    model_cls = COMPONENT_TYPE_MAP[component_type]
    return model_cls.model_validate(_read_json(path))


def list_components(
    component_type: str | None = None,
    *,
    root: Path | None = None,
) -> list[Path]:
    components_root = data_root(root) / "components"
    if component_type is not None:
        return sorted((components_root / component_type).glob("*.json"))
    return sorted(components_root.glob("*/*.json"))


def save_vehicle(
    vehicle: VehicleConfig,
    *,
    root: Path | None = None,
    allow_overwrite: bool = False,
) -> str:
    path = _vehicle_path(data_root(root), vehicle.name, vehicle.version)
    return _write_json(path, vehicle, allow_overwrite=allow_overwrite)


def load_vehicle(
    name: str,
    version: str,
    *,
    root: Path | None = None,
) -> VehicleConfig:
    store_root = data_root(root)
    path = _vehicle_path(store_root, name, version)
    if path.exists():
        return VehicleConfig.model_validate(_read_json(path))
    for candidate in list_vehicles(root=store_root):
        data = _read_json(candidate)
        if data.get("name") == name and data.get("version") == version:
            return VehicleConfig.model_validate(data)
    raise ConfigStoreError(f"Vehicle not found: {name} {version}")


def list_vehicles(*, root: Path | None = None) -> list[Path]:
    return sorted(data_root(root).glob("vehicles/*/*.json"))


def save_drive_mode(
    mode: DriveMode,
    *,
    root: Path | None = None,
    allow_overwrite: bool = True,
) -> str:
    path = _drive_mode_path(data_root(root), mode.name)
    return _write_json(path, mode, allow_overwrite=allow_overwrite)


def load_drive_mode(name: str, *, root: Path | None = None) -> DriveMode:
    path = _drive_mode_path(data_root(root), name)
    return DriveMode.model_validate(_read_json(path))


def list_drive_modes(*, root: Path | None = None) -> list[Path]:
    return sorted(data_root(root).glob("drive_modes/*.json"))


def save_driver_profile(
    profile: DriverProfile,
    *,
    root: Path | None = None,
    allow_overwrite: bool = True,
) -> str:
    path = _driver_profile_path(data_root(root), profile.name)
    return _write_json(path, profile, allow_overwrite=allow_overwrite)


def load_driver_profile(name: str, *, root: Path | None = None) -> DriverProfile:
    path = _driver_profile_path(data_root(root), name)
    return DriverProfile.model_validate(_read_json(path))


def list_driver_profiles(*, root: Path | None = None) -> list[Path]:
    return sorted(data_root(root).glob("driver_profiles/*.json"))


def save_calibration(
    calibration: CalibrationSet,
    *,
    root: Path | None = None,
    allow_overwrite: bool = False,
) -> str:
    path = _calibration_path(data_root(root), calibration.name, calibration.version)
    return _write_json(path, calibration, allow_overwrite=allow_overwrite)


def load_calibration(
    name: str,
    version: str,
    *,
    root: Path | None = None,
) -> CalibrationSet:
    path = _calibration_path(data_root(root), name, version)
    return CalibrationSet.model_validate(_read_json(path))


def verify_component_ref(ref_component_id: str, ref_hash: str, component: ComponentBase) -> bool:
    actual = content_hash(component.model_dump(mode="json"))
    return ref_component_id == component.id and ref_hash == actual


def load_config_file(path: Path) -> tuple[str, BaseModel]:
    """Load any supported JSON config by inspecting its structure."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if "component_type" in data:
        model_cls = COMPONENT_TYPE_MAP[data["component_type"]]
        return "component", model_cls.model_validate(data)
    if "drivetrain" in data and "limits" in data:
        return "vehicle", VehicleConfig.model_validate(data)
    if "throttle_curve" in data:
        return "drive_mode", DriveMode.model_validate(data)
    if "pin_hash" in data or (
        "limits" in data and "throttle_curve" not in data and "version" not in data
    ):
        return "driver_profile", DriverProfile.model_validate(data)
    if "throttle" in data and "wheel_speed" in data:
        return "calibration", CalibrationSet.model_validate(data)
    raise ConfigStoreError(f"Unrecognized configuration file: {path}")
