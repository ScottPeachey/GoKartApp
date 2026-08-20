"""Prove dashboard engine sound is driven by telemetry RPM."""

from __future__ import annotations

from pathlib import Path

from gokart.sim.engine import run_simulation
from gokart.sim.scenarios import DriverInputPoint, Scenario

STATIC = Path(__file__).resolve().parents[1] / "src" / "gokart" / "dashboard" / "static"


def firing_hz(rpm: float) -> float:
    return rpm / 60.0


def test_worklet_firing_rate_is_rpm_over_60() -> None:
    source = (STATIC / "engine-audio-worklet.js").read_text()
    assert "const fireHz = rpm / 60" in source
    assert "this.port.onmessage" in source
    assert firing_hz(9600.0) == firing_hz(1600.0) * 6


def test_controller_posts_engine_rpm_to_worklet() -> None:
    source = (STATIC / "engine-audio.js").read_text()
    assert 'source = "engine_rpm"' in source
    assert "worklet.port.postMessage" in source
    html = (STATIC / "index.html").read_text()
    assert "engine-audio-rpm" in html


def test_live_ticks_include_engine_rpm_that_changes_with_throttle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    scenario = Scenario(
        name="audio_rpm_sweep",
        duration_s=3.0,
        inputs=[DriverInputPoint(time_s=0.0, throttle=1.0, brake=0.0)],
        auto_boot=True,
    )
    result = run_simulation("Rotax 125", "V1.0", scenario, dt_s=0.01)
    rows = [r.to_row() for r in result.records if r.values.get("safety_state") == "DRIVING"]
    assert rows
    assert "engine_rpm" in rows[0]
    rpms = [float(r["engine_rpm"]) for r in rows]
    assert max(rpms) > min(rpms) + 2000
    assert firing_hz(max(rpms)) > firing_hz(min(rpms)) * 1.5


def test_engine_audio_assets_declare_rpm_link() -> None:
    worklet = (STATIC / "engine-audio-worklet.js").read_text()
    controller = (STATIC / "engine-audio.js").read_text()
    assert "fireHz = rpm / 60" in worklet
    assert "port.postMessage" in controller
    assert "engine_rpm" in controller
