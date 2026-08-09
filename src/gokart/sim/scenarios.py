"""Simulation scenario definitions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from gokart.physics.vehicle import Environment


@dataclass(frozen=True)
class DriverInputPoint:
    time_s: float
    throttle: float = 0.0
    brake: float = 0.0


@dataclass
class Scenario:
    name: str
    duration_s: float
    mode_name: str = "Default"
    profile_name: str = "Owner"
    environment: Environment = field(default_factory=Environment)
    inputs: list[DriverInputPoint] = field(default_factory=list)

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


BUILTIN_SCENARIOS: dict[str, Scenario] = {
    "standing_start_30s": standing_start_30s(),
    "hill_climb": hill_climb(),
    "constant_speed_cruise": constant_speed_cruise(),
    "duty_cycle_range": duty_cycle_range(),
    "coast_down": coast_down(),
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
    return Scenario(
        name=data.get("name", path.stem),
        duration_s=float(data["duration_s"]),
        mode_name=data.get("mode", "Default"),
        profile_name=data.get("profile", "Owner"),
        environment=environment,
        inputs=inputs,
    )
