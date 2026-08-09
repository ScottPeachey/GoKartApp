"""Declarative parameter sweep execution."""

from __future__ import annotations

import copy
import itertools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from gokart.analysis.metrics import SessionMetrics, compute_metrics, metric_value
from gokart.analysis.overlays import CalibrationOverlay
from gokart.analysis.tests import _samples_from_result
from gokart.config.schemas.vehicle import VehicleConfig
from gokart.config.store import data_root, load_vehicle
from gokart.sim.engine import run_simulation
from gokart.sim.scenarios import load_scenario

Direction = Literal["minimize", "maximize"]


@dataclass(frozen=True)
class SweepConstraint:
    metric: str
    op: str
    value: float


@dataclass(frozen=True)
class SweepObjective:
    metric: str
    direction: Direction = "minimize"


@dataclass(frozen=True)
class SweepSpec:
    vehicle_name: str
    vehicle_version: str
    scenario: str
    parameters: dict[str, list[float | int]]
    objective: SweepObjective
    constraints: tuple[SweepConstraint, ...] = ()
    overlay: CalibrationOverlay | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SweepSpec:
        overlay = None
        if "overlay" in data:
            overlay = CalibrationOverlay.model_validate(data["overlay"])
        return cls(
            vehicle_name=data["vehicle_name"],
            vehicle_version=data["vehicle_version"],
            scenario=data["scenario"],
            parameters=data["parameters"],
            objective=SweepObjective(
                metric=data["objective"]["metric"],
                direction=data["objective"].get("direction", "minimize"),
            ),
            constraints=tuple(
                SweepConstraint(metric=item["metric"], op=item["op"], value=float(item["value"]))
                for item in data.get("constraints", [])
            ),
            overlay=overlay,
        )


@dataclass(frozen=True)
class SweepResultRow:
    parameters: dict[str, float | int]
    metrics: SessionMetrics
    objective_value: float | None
    feasible: bool


def load_sweep_spec(path: Path) -> SweepSpec:
    return SweepSpec.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _set_parameter(config: VehicleConfig, path: str, value: float | int) -> None:
    parts = path.split(".")
    target: Any = config
    for part in parts[:-1]:
        target = getattr(target, part)
    setattr(target, parts[-1], value)


def _meets_constraint(metrics: SessionMetrics, constraint: SweepConstraint) -> bool:
    value = metric_value(metrics, constraint.metric)
    if value is None:
        return False
    if constraint.op == ">=":
        return value >= constraint.value
    if constraint.op == "<=":
        return value <= constraint.value
    if constraint.op == ">":
        return value > constraint.value
    if constraint.op == "<":
        return value < constraint.value
    if constraint.op == "==":
        return value == constraint.value
    raise ValueError(f"Unsupported constraint operator: {constraint.op}")


def run_sweep(
    spec: SweepSpec,
    *,
    data_root_path: Path | None = None,
) -> list[SweepResultRow]:
    root = data_root_path or data_root()
    base_config = load_vehicle(spec.vehicle_name, spec.vehicle_version, root=root)
    scenario = load_scenario(spec.scenario)
    param_names = list(spec.parameters)
    value_lists = [spec.parameters[name] for name in param_names]
    rows: list[SweepResultRow] = []

    for combo in itertools.product(*value_lists):
        config = copy.deepcopy(base_config)
        params = dict(zip(param_names, combo, strict=True))
        for path, value in params.items():
            _set_parameter(config, path, value)
        result = run_simulation(
            config.name,
            config.version,
            scenario,
            data_root_path=root,
            vehicle_config=config,
            overlay=spec.overlay,
        )
        metrics = compute_metrics(_samples_from_result(result))
        feasible = all(_meets_constraint(metrics, c) for c in spec.constraints)
        objective_value = metric_value(metrics, spec.objective.metric)
        rows.append(
            SweepResultRow(
                parameters=params,
                metrics=metrics,
                objective_value=objective_value,
                feasible=feasible,
            )
        )

    reverse = spec.objective.direction == "maximize"
    feasible_rows = [row for row in rows if row.feasible and row.objective_value is not None]
    feasible_rows.sort(key=lambda row: row.objective_value or 0.0, reverse=reverse)
    infeasible_rows = [row for row in rows if not row.feasible]
    return feasible_rows + infeasible_rows
