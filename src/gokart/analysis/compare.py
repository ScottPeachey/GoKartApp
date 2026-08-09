"""Config comparison and session replay analysis."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gokart.analysis.metrics import SessionMetrics, compute_metrics
from gokart.analysis.overlays import CalibrationOverlay
from gokart.analysis.tests import _samples_from_result
from gokart.sim.engine import run_simulation
from gokart.sim.scenarios import DriverInputPoint, Scenario, load_scenario
from gokart.telemetry.storage import TelemetryStore


@dataclass(frozen=True)
class ComparisonRow:
    metric: str
    values: dict[str, float | None]
    delta: float | None = None


@dataclass(frozen=True)
class ReplayResult:
    session_id: str
    channel_errors: dict[str, float]
    simulated_metrics: SessionMetrics
    reference_metrics: SessionMetrics


def compare_configs(
    configs: list[tuple[str, str]],
    scenario_name: str,
    *,
    data_root_path: Path | None = None,
    overlay: CalibrationOverlay | None = None,
) -> list[ComparisonRow]:
    scenario = load_scenario(scenario_name)
    metrics_by_label: dict[str, SessionMetrics] = {}
    for index, (vehicle_name, vehicle_version) in enumerate(configs):
        label = f"{vehicle_name} {vehicle_version}"
        if sum(1 for vn, vv in configs if vn == vehicle_name and vv == vehicle_version) > 1:
            label = f"{label} ({index + 1})"
        result = run_simulation(
            vehicle_name,
            vehicle_version,
            scenario,
            data_root_path=data_root_path,
            overlay=overlay,
        )
        metrics_by_label[label] = compute_metrics(_samples_from_result(result))

    metric_names = sorted(
        {
            key
            for metrics in metrics_by_label.values()
            for key, value in metrics.as_dict().items()
            if value is not None
        }
    )
    rows: list[ComparisonRow] = []
    labels = list(metrics_by_label)
    for metric_name in metric_names:
        values = {label: metrics_by_label[label].as_dict().get(metric_name) for label in labels}
        delta = None
        if len(labels) == 2:
            left, right = values[labels[0]], values[labels[1]]
            if left is not None and right is not None:
                delta = right - left
        rows.append(ComparisonRow(metric=metric_name, values=values, delta=delta))
    return rows


def replay_session(
    session_id: str,
    *,
    store: TelemetryStore | None = None,
    data_root_path: Path | None = None,
    overlay: CalibrationOverlay | None = None,
) -> ReplayResult:
    telemetry_store = store or TelemetryStore()
    session = telemetry_store.get_session(session_id)
    if session is None:
        raise KeyError(f"Session not found: {session_id}")
    samples = telemetry_store.load_samples(session_id)
    if not samples:
        raise ValueError(f"Session {session_id} has no samples")

    inputs = [
        DriverInputPoint(
            time_s=float(sample["time_s"]),
            throttle=float(sample.get("throttle", 0.0)),
            brake=float(sample.get("brake", 0.0)),
        )
        for sample in samples
    ]
    scenario = Scenario(
        name=f"replay_{session_id[:8]}",
        duration_s=float(samples[-1]["time_s"]),
        mode_name=session.drive_mode,
        profile_name=session.driver_profile,
        inputs=inputs,
        auto_boot=True,
    )
    result = run_simulation(
        session.vehicle_name,
        session.vehicle_version,
        scenario,
        data_root_path=data_root_path,
        overlay=overlay,
    )
    simulated = _samples_from_result(result)
    channel_errors = _channel_errors(samples, simulated)
    return ReplayResult(
        session_id=session_id,
        channel_errors=channel_errors,
        simulated_metrics=compute_metrics(simulated),
        reference_metrics=compute_metrics(samples),
    )


def _channel_errors(
    reference: list[dict[str, Any]],
    simulated: list[dict[str, Any]],
) -> dict[str, float]:
    channels = ("speed_mps", "power_w", "motor_current_a", "battery_current_a", "soc")
    errors: dict[str, float] = {}
    count = min(len(reference), len(simulated))
    if count == 0:
        return errors
    for channel in channels:
        sq = 0.0
        peak = 0.0
        for index in range(count):
            ref = float(reference[index].get(channel, 0.0))
            sim = float(simulated[index].get(channel, 0.0))
            diff = sim - ref
            sq += diff * diff
            peak = max(peak, abs(diff))
        errors[f"{channel}_rms"] = math.sqrt(sq / count)
        errors[f"{channel}_peak"] = peak
    return errors
