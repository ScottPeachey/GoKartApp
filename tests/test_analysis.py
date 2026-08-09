"""Phase 5 analysis and virtual tuning tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from gokart.analysis.compare import compare_configs, replay_session
from gokart.analysis.metrics import compute_metrics
from gokart.analysis.overlays import CalibrationOverlay
from gokart.analysis.report import write_session_report
from gokart.analysis.sweep import load_sweep_spec, run_sweep
from gokart.analysis.tests import run_top_speed_test, theoretical_top_speed_mps
from gokart.physics.vehicle import load_validated_vehicle_model
from gokart.sim.engine import run_simulation
from gokart.sim.scenarios import standing_start_30s
from gokart.telemetry.recorder import SessionMetadata, SessionRecorder
from gokart.telemetry.storage import TelemetryStore
from gokart.units import kmh_to_mps, mps_to_kmh


def _synthetic_samples() -> list[dict]:
    samples = []
    for index in range(100):
        time_s = index * 0.1
        speed = min(kmh_to_mps(40.0), index * 0.15)
        samples.append(
            {
                "time_s": time_s,
                "speed_mps": speed,
                "position_m": sum(min(kmh_to_mps(40.0), i * 0.15) for i in range(index + 1)) * 0.1,
                "power_w": 2000.0 if speed < kmh_to_mps(30.0) else 500.0,
                "battery_current_a": 40.0,
                "motor_current_a": 45.0,
                "motor_temp_c": 30.0 + index * 0.05,
                "battery_temp_c": 28.0 + index * 0.03,
                "soc": 1.0 - index * 0.001,
            }
        )
    return samples


def test_metric_extraction_synthetic() -> None:
    metrics = compute_metrics(_synthetic_samples())
    assert metrics.top_speed_kmh == pytest.approx(40.0, abs=1.0)
    assert metrics.accel_10_kmh_s is not None
    assert metrics.accel_30_kmh_s is not None
    assert metrics.energy_used_wh > 0
    assert metrics.peak_battery_current_a == pytest.approx(40.0)


def test_theoretical_top_speed_matches_analytic() -> None:
    root = Path(__file__).resolve().parents[1]
    model = load_validated_vehicle_model("Scott Kart V1", "V1.0", data_root=root / "data")
    theoretical = theoretical_top_speed_mps(model)
    result = run_top_speed_test(
        "Scott Kart V1",
        "V1.0",
        data_root_path=root / "data",
        tolerance=0.2,
    )
    assert result.details["theoretical_kmh"] == pytest.approx(mps_to_kmh(theoretical), rel=0.01)


def test_sweep_respects_constraints_and_ranking() -> None:
    root = Path(__file__).resolve().parents[1]
    spec = load_sweep_spec(root / "data" / "sweeps" / "sprocket_0_30.json")
    results = run_sweep(spec, data_root_path=root / "data")
    assert results
    feasible = [row for row in results if row.feasible and row.objective_value is not None]
    assert feasible
    objectives = [row.objective_value for row in feasible]
    assert objectives == sorted(objectives)


def test_report_generates_valid_html(tmp_path: Path) -> None:
    store = TelemetryStore(tmp_path / "sessions.sqlite")
    recorder = SessionRecorder(
        SessionMetadata(
            vehicle_name="Scott Kart V1",
            vehicle_version="V1.0",
            config_hash="abc",
            driver_profile="Owner",
            drive_mode="Default",
            scenario_name="test",
        ),
        store=store,
        log_every_n=1,
    )
    for sample in _synthetic_samples():
        recorder.record_tick(sample)
    recorder.close(end_soc=0.8)
    out = tmp_path / "report.html"
    write_session_report(recorder.session_id, out, store=store)
    html = out.read_text(encoding="utf-8")
    assert "<html" in html
    assert "Session Report" in html
    assert "data:image/png;base64," in html


def test_compare_configs_produces_diff_table() -> None:
    root = Path(__file__).resolve().parents[1]
    rows = compare_configs(
        [("Scott Kart V1", "V1.0"), ("Scott Kart V1", "V1.0")],
        "coast_down",
        data_root_path=root / "data",
    )
    assert rows
    top_speed_row = next(row for row in rows if row.metric == "top_speed_kmh")
    assert top_speed_row.delta == pytest.approx(0.0)


def test_overlay_affects_simulation() -> None:
    root = Path(__file__).resolve().parents[1]
    baseline = run_simulation(
        "Scott Kart V1",
        "V1.0",
        standing_start_30s(),
        data_root_path=root / "data",
    )
    overlay = CalibrationOverlay(
        name="high_roll",
        version="1.0",
        rolling_resistance_scale=1.5,
    )
    adjusted = run_simulation(
        "Scott Kart V1",
        "V1.0",
        standing_start_30s(),
        data_root_path=root / "data",
        overlay=overlay,
    )
    baseline_top = max(r.values["speed_mps"] for r in baseline.records)
    adjusted_top = max(r.values["speed_mps"] for r in adjusted.records)
    assert adjusted_top < baseline_top


def test_replay_session_channel_errors(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    store = TelemetryStore(tmp_path / "sessions.sqlite")
    recorder = SessionRecorder(
        SessionMetadata(
            vehicle_name="Scott Kart V1",
            vehicle_version="V1.0",
            config_hash="abc",
            driver_profile="Owner",
            drive_mode="Default",
            scenario_name="standing_start_30s",
        ),
        store=store,
        log_every_n=1,
    )
    result = run_simulation(
        "Scott Kart V1",
        "V1.0",
        standing_start_30s(),
        data_root_path=root / "data",
        recorder=recorder,
    )
    recorder.close(end_soc=result.final_state.battery.soc if result.final_state.battery else None)
    replay = replay_session(recorder.session_id, store=store, data_root_path=root / "data")
    assert "speed_mps_rms" in replay.channel_errors
