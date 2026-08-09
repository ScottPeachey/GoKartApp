"""Standard performance test runners."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gokart.analysis.metrics import SessionMetrics, compute_metrics
from gokart.analysis.overlays import CalibrationOverlay, apply_overlay
from gokart.config.schemas.vehicle import VehicleConfig
from gokart.config.store import data_root
from gokart.physics.aero import aero_drag_force_n, rolling_resistance_force_n
from gokart.physics.vehicle import VehicleModel, load_validated_vehicle_model
from gokart.sim.engine import run_simulation
from gokart.sim.scenarios import Scenario, standing_start_30s
from gokart.units import kmh_to_mps, mps_to_kmh


@dataclass(frozen=True)
class TestResult:
    name: str
    passed: bool
    metrics: SessionMetrics
    details: dict[str, Any]


def _samples_from_result(result) -> list[dict[str, Any]]:
    return [record.to_row() for record in result.records]


def theoretical_top_speed_mps(model: VehicleModel, *, gradient_rad: float = 0.0) -> float:
    """Analytic force-balance top speed at peak motor force."""
    motor_peak_force = (
        model.motor_params.peak_torque_nm
        * model.drivetrain_params.gear_ratio
        * model.drivetrain_params.total_efficiency
        / model.drivetrain_params.wheel_radius_m
    )

    def net_force(speed_mps: float) -> float:
        return (
            motor_peak_force
            - aero_drag_force_n(speed_mps, model.drag_coefficient, model.frontal_area_m2)
            - rolling_resistance_force_n(
                model.mass_kg,
                model.rolling_resistance_coefficient,
                gradient_rad,
            )
        )

    speed = 0.0
    for _ in range(20_000):
        if net_force(speed) <= 0:
            break
        speed += 0.01
    return speed


def run_acceleration_test(
    vehicle_name: str,
    vehicle_version: str,
    *,
    scenario_name: str = "standing_start_30s",
    data_root_path: Path | None = None,
    overlay: CalibrationOverlay | None = None,
) -> TestResult:
    root = data_root_path or data_root()
    if scenario_name == "standing_start_30s":
        scenario = standing_start_30s()
    else:
        scenario = _load_named(scenario_name)
    result = _run_with_overlay(vehicle_name, vehicle_version, scenario, root, overlay)
    metrics = compute_metrics(_samples_from_result(result))
    passed = metrics.accel_30_kmh_s is not None
    return TestResult(
        name="acceleration",
        passed=passed,
        metrics=metrics,
        details={"scenario": scenario_name, "accel_30_kmh_s": metrics.accel_30_kmh_s},
    )


def run_top_speed_test(
    vehicle_name: str,
    vehicle_version: str,
    *,
    scenario_name: str = "standing_start_30s",
    tolerance: float = 0.15,
    data_root_path: Path | None = None,
    overlay: CalibrationOverlay | None = None,
) -> TestResult:
    root = data_root_path or data_root()
    model = load_validated_vehicle_model(vehicle_name, vehicle_version, data_root=root)
    if overlay is not None:
        apply_overlay(model, overlay)
    theoretical = theoretical_top_speed_mps(model)
    if scenario_name == "standing_start_30s":
        scenario = standing_start_30s()
    else:
        scenario = _load_named(scenario_name)
    result = _run_with_overlay(vehicle_name, vehicle_version, scenario, root, overlay)
    metrics = compute_metrics(_samples_from_result(result))
    sim_top = kmh_to_mps(metrics.top_speed_kmh)
    passed = abs(sim_top - theoretical) <= theoretical * tolerance + 1e-6
    return TestResult(
        name="top_speed",
        passed=passed,
        metrics=metrics,
        details={
            "theoretical_kmh": mps_to_kmh(theoretical),
            "simulated_kmh": metrics.top_speed_kmh,
            "tolerance": tolerance,
        },
    )


def run_hill_climb_test(
    vehicle_name: str,
    vehicle_version: str,
    *,
    gradient_rad: float = 0.1,
    target_distance_m: float = 100.0,
    data_root_path: Path | None = None,
    overlay: CalibrationOverlay | None = None,
) -> TestResult:
    from gokart.physics.vehicle import Environment

    scenario = Scenario(
        name="hill_climb_analysis",
        duration_s=120.0,
        environment=Environment(gradient_rad=gradient_rad),
        inputs=list(standing_start_30s().inputs),
    )
    root = data_root_path or data_root()
    result = _run_with_overlay(vehicle_name, vehicle_version, scenario, root, overlay)
    samples = _samples_from_result(result)
    metrics = compute_metrics(samples)
    final_position = float(samples[-1]["position_m"]) if samples else 0.0
    passed = final_position >= target_distance_m
    return TestResult(
        name="hill_climb",
        passed=passed,
        metrics=metrics,
        details={
            "gradient_rad": gradient_rad,
            "distance_m": final_position,
            "target_distance_m": target_distance_m,
        },
    )


def run_range_test(
    vehicle_name: str,
    vehicle_version: str,
    *,
    scenario_name: str = "duty_cycle_range",
    data_root_path: Path | None = None,
    overlay: CalibrationOverlay | None = None,
) -> TestResult:
    from gokart.sim.scenarios import BUILTIN_SCENARIOS

    root = data_root_path or data_root()
    scenario = BUILTIN_SCENARIOS.get(scenario_name)
    if scenario is None:
        scenario = _load_named(scenario_name)
    result = _run_with_overlay(vehicle_name, vehicle_version, scenario, root, overlay)
    metrics = compute_metrics(_samples_from_result(result))
    passed = metrics.distance_km > 0 and metrics.energy_used_wh > 0
    return TestResult(
        name="range",
        passed=passed,
        metrics=metrics,
        details={
            "scenario": scenario_name,
            "distance_km": metrics.distance_km,
            "energy_used_wh": metrics.energy_used_wh,
            "wh_per_km": metrics.wh_per_km,
        },
    )


def _load_named(scenario_name: str) -> Scenario:
    from gokart.sim.scenarios import load_scenario

    return load_scenario(scenario_name)


def _run_with_overlay(
    vehicle_name: str,
    vehicle_version: str,
    scenario: Scenario,
    root: Path,
    overlay: CalibrationOverlay | None,
):
    return run_simulation(
        vehicle_name,
        vehicle_version,
        scenario,
        data_root_path=root,
        overlay=overlay,
    )


def run_with_vehicle_config(
    config: VehicleConfig,
    scenario: Scenario,
    *,
    data_root_path: Path | None = None,
    overlay: CalibrationOverlay | None = None,
):
    return run_simulation(
        config.name,
        config.version,
        scenario,
        data_root_path=data_root_path,
        vehicle_config=config,
        overlay=overlay,
    )
