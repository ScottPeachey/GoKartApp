"""Configuration editor service tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from gokart.config.editor import (
    SaveVehicleRequest,
    build_vehicle_detail,
    bump_version,
    save_vehicle_as_new_version,
    suggest_next_version,
)
from gokart.config.schemas.vehicle import DrivetrainConfig
from gokart.config.store import load_vehicle


@pytest.fixture
def data_copy(tmp_path: Path) -> Path:
    root = Path(__file__).resolve().parents[1] / "data"
    target = tmp_path / "data"
    shutil.copytree(root, target)
    return target


def test_bump_version() -> None:
    assert bump_version("V1.0") == "V1.1"
    assert bump_version("V2.3") == "V2.4"


def test_suggest_next_version(data_copy: Path) -> None:
    assert suggest_next_version("Scott Kart V1", root=data_copy) == "V1.1"


def test_build_vehicle_detail(data_copy: Path) -> None:
    detail = build_vehicle_detail("Scott Kart V1", "V1.0", root=data_copy)
    assert detail["name"] == "Scott Kart V1"
    assert "motor" in detail["slots"]
    assert detail["slots"]["motor"]["component_id"] == "v1_motor_5kw"
    assert detail["powertrain_type"] == "ev"


def test_ice_vehicle_detail_is_not_battery_powered(data_copy: Path) -> None:
    detail = build_vehicle_detail("Rotax 125", "V1.0", root=data_copy)
    assert detail["powertrain_type"] == "ice"
    assert "battery" not in detail["slots"]


def test_save_new_version_with_sprocket_change(data_copy: Path) -> None:
    result = save_vehicle_as_new_version(
        SaveVehicleRequest(
            base_name="Scott Kart V1",
            base_version="V1.0",
            new_version="V1.1",
            slots={"motor": "v1_motor_5kw"},
            drivetrain=DrivetrainConfig(
                motor_sprocket_teeth=11,
                axle_sprocket_teeth=52,
                chain_efficiency=0.97,
                axle_efficiency=0.98,
            ),
        ),
        root=data_copy,
    )
    assert result.validation_ok
    vehicle = load_vehicle("Scott Kart V1", "V1.1", root=data_copy)
    assert vehicle.drivetrain.motor_sprocket_teeth == 11


def test_save_rejects_duplicate_version(data_copy: Path) -> None:
    first = save_vehicle_as_new_version(
        SaveVehicleRequest(
            base_name="Scott Kart V1",
            base_version="V1.0",
            new_version="V1.3",
            slots={"motor": "v1_motor_5kw"},
        ),
        root=data_copy,
    )
    assert first.validation_ok
    second = save_vehicle_as_new_version(
        SaveVehicleRequest(
            base_name="Scott Kart V1",
            base_version="V1.0",
            new_version="V1.3",
            slots={"motor": "v1_motor_5kw"},
        ),
        root=data_copy,
    )
    assert not second.validation_ok
    assert second.violations
