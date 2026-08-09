"""Simulation scenario definitions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gokart.physics.vehicle import Environment


@dataclass(frozen=True)
class DriverInputPoint:
    time_s: float
    throttle: float = 0.0
    brake: float = 0.0


@dataclass(frozen=True)
class ModeChangePoint:
    time_s: float
    mode_name: str


@dataclass(frozen=True)
class ProfileChangePoint:
    time_s: float
    profile_name: str


@dataclass
class Scenario:
    name: str
    duration_s: float
    mode_name: str = "Default"
    profile_name: str = "Owner"
    environment: Environment = field(default_factory=Environment)
    inputs: list[DriverInputPoint] = field(default_factory=list)
    injections: list[dict[str, Any]] | None = None
    auto_boot: bool = True
    mode_changes: list[ModeChangePoint] = field(default_factory=list)
    profile_changes: list[ProfileChangePoint] = field(default_factory=list)

    def driver_inputs_at(self, time_s: float) -> tuple[float, float]:
        if not self.inputs:
            return 0.0, 0.0
        active = self.inputs[0]
        for point in self.inputs:
            if point.time_s <= time_s:
                active = point
            else:
                break
        return active.throttle, active.brake

    def mode_at(self, time_s: float) -> str | None:
        active: str | None = None
        for point in self.mode_changes:
            if point.time_s <= time_s:
                active = point.mode_name
            else:
                break
        return active

    def profile_at(self, time_s: float) -> str | None:
        active: str | None = None
        for point in self.profile_changes:
            if point.time_s <= time_s:
                active = point.profile_name
            else:
                break
        return active


def standing_start_30s() -> Scenario:
    return Scenario(
        name="standing_start_30s",
        duration_s=30.0,
        mode_name="Default",
        profile_name="Owner",
        inputs=[DriverInputPoint(time_s=0.0, throttle=1.0, brake=0.0)],
    )


def hill_climb() -> Scenario:
    return Scenario(
        name="hill_climb",
        duration_s=60.0,
        mode_name="Default",
        profile_name="Owner",
        environment=Environment(gradient_rad=0.1),
        inputs=[DriverInputPoint(time_s=0.0, throttle=1.0, brake=0.0)],
    )


def constant_speed_cruise() -> Scenario:
    return Scenario(
        name="constant_speed_cruise",
        duration_s=120.0,
        mode_name="Default",
        profile_name="Owner",
        inputs=[DriverInputPoint(time_s=0.0, throttle=0.35, brake=0.0)],
    )


def duty_cycle_range() -> Scenario:
    return Scenario(
        name="duty_cycle_range",
        duration_s=600.0,
        mode_name="Default",
        profile_name="Owner",
        inputs=[
            DriverInputPoint(time_s=0.0, throttle=0.5, brake=0.0),
            DriverInputPoint(time_s=300.0, throttle=0.2, brake=0.0),
            DriverInputPoint(time_s=450.0, throttle=0.0, brake=0.0),
        ],
    )


def coast_down() -> Scenario:
    return Scenario(
        name="coast_down",
        duration_s=30.0,
        mode_name="Default",
        profile_name="Owner",
        inputs=[DriverInputPoint(time_s=0.0, throttle=0.0, brake=0.0)],
    )


def battery_overtemp_shutdown() -> Scenario:
    return Scenario(
        name="battery_overtemp_shutdown",
        duration_s=12.0,
        mode_name="Default",
        profile_name="Owner",
        inputs=[DriverInputPoint(time_s=0.0, throttle=1.0, brake=0.0)],
        injections=[
            {
                "time_s": 4.0,
                "ramp": {
                    "field": "battery_temp_c",
                    "duration_s": 3.0,
                    "from": 25.0,
                    "to": 65.0,
                },
            },
        ],
    )


BUILTIN_SCENARIOS: dict[str, Scenario] = {
    "standing_start_30s": standing_start_30s(),
    "hill_climb": hill_climb(),
    "constant_speed_cruise": constant_speed_cruise(),
    "duty_cycle_range": duty_cycle_range(),
    "coast_down": coast_down(),
    "battery_overtemp_shutdown": battery_overtemp_shutdown(),
}


def load_scenario(name_or_path: str) -> Scenario:
    if name_or_path in BUILTIN_SCENARIOS:
        return BUILTIN_SCENARIOS[name_or_path]
    path = Path(name_or_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    env_data = data.get("environment", {})
    environment = Environment(
        gradient_rad=env_data.get("gradient_rad", 0.0),
        ambient_temp_c=env_data.get("ambient_temp_c", 25.0),
        surface_mu_scale=env_data.get("surface_mu_scale", 1.0),
    )
    inputs = [
        DriverInputPoint(
            time_s=point["time_s"],
            throttle=point.get("throttle", 0.0),
            brake=point.get("brake", 0.0),
        )
        for point in data.get("inputs", [])
    ]
    mode_changes = [
        ModeChangePoint(time_s=point["time_s"], mode_name=point["mode"])
        for point in data.get("mode_changes", [])
    ]
    profile_changes = [
        ProfileChangePoint(time_s=point["time_s"], profile_name=point["profile"])
        for point in data.get("profile_changes", [])
    ]
    return Scenario(
        name=data.get("name", path.stem),
        duration_s=float(data["duration_s"]),
        mode_name=data.get("mode", "Default"),
        profile_name=data.get("profile", "Owner"),
        environment=environment,
        inputs=inputs,
        injections=data.get("injections"),
        auto_boot=data.get("auto_boot", True),
        mode_changes=mode_changes,
        profile_changes=profile_changes,
    )
