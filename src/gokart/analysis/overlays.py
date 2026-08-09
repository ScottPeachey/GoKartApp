"""Calibration overlay schemas for virtual tuning."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from pydantic import BaseModel, Field

from gokart.config.hashing import content_hash
from gokart.physics.vehicle import VehicleModel


class CalibrationOverlay(BaseModel):
    """Named parameter adjustment set applied on top of a vehicle config for simulation."""

    name: str
    version: str
    rolling_resistance_scale: float = Field(default=1.0, gt=0)
    mass_correction_kg: float = 0.0
    motor_efficiency_scale: float = Field(default=1.0, gt=0)
    battery_resistance_scale: float = Field(default=1.0, gt=0)
    notes: str | None = None

    def content_hash(self) -> str:
        return content_hash(self.model_dump(mode="json"))


@dataclass
class OverlayState:
    overlay: CalibrationOverlay
    content_hash: str


def apply_overlay(model: VehicleModel, overlay: CalibrationOverlay) -> None:
    """Apply overlay scales to a loaded vehicle model in place."""
    model.mass_kg += overlay.mass_correction_kg
    model.rolling_resistance_coefficient *= overlay.rolling_resistance_scale
    model.battery_params = replace(
        model.battery_params,
        internal_resistance_ohm=(
            model.battery_params.internal_resistance_ohm * overlay.battery_resistance_scale
        ),
    )
    model.motor_efficiency_scale *= overlay.motor_efficiency_scale


def load_overlay(path: Path) -> CalibrationOverlay:
    return CalibrationOverlay.model_validate_json(path.read_text(encoding="utf-8"))


def save_overlay(overlay: CalibrationOverlay, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(overlay.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return overlay.content_hash()
