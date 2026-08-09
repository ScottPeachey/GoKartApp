"""Fault injection and safety integration simulation tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from gokart.safety.faults import SafetyConfig, SensorInputs, detect_faults
from gokart.safety.types import FaultId, SafetyState
from gokart.sim.engine import run_simulation
from gokart.sim.fault_injection import FaultInjector, ValueRamp
from gokart.sim.scenarios import battery_overtemp_shutdown, standing_start_30s


def test_value_ramp_interpolation() -> None:
    ramp = ValueRamp(
        start_time_s=1.0,
        duration_s=2.0,
        from_value=20.0,
        to_value=60.0,
        field_name="battery_temp_c",
    )
    assert ramp.value_at(0.5) == pytest.approx(20.0)
    assert ramp.value_at(2.0) == pytest.approx(40.0)
    assert ramp.value_at(3.0) == pytest.approx(60.0)


def test_injector_overrides_battery_temp() -> None:
    injector = FaultInjector.from_scenario_data(
        [
            {
                "time_s": 0.0,
                "ramp": {
                    "field": "battery_temp_c",
                    "duration_s": 1.0,
                    "from": 25.0,
                    "to": 55.0,
                },
            }
        ]
    )
    sensors = injector.apply(0.85, SensorInputs(throttle_adc=2000, brake_adc=2000))
    assert sensors.battery_temp_c == pytest.approx(50.5)
    faults = detect_faults(sensors, SafetyConfig())
    assert FaultId.BATTERY_OVERTEMP_DERATE in faults


def test_standing_start_reaches_driving_with_auto_boot() -> None:
    root = Path(__file__).resolve().parents[1]
    result = run_simulation(
        "Scott Kart V1",
        "V1.0",
        standing_start_30s(),
        data_root_path=root / "data",
    )
    states = {r.values["safety_state"] for r in result.records}
    assert SafetyState.DRIVING.value in states
    driving_records = [r for r in result.records if r.values["safety_state"] == "DRIVING"]
    assert driving_records
    assert max(r.values["speed_mps"] for r in driving_records) > 1.0


def test_battery_overtemp_acceptance_trace() -> None:
    root = Path(__file__).resolve().parents[1]
    result = run_simulation(
        "Scott Kart V1",
        "V1.0",
        battery_overtemp_shutdown(),
        data_root_path=root / "data",
    )
    derate_seen = any(
        "BATTERY_OVERTEMP_DERATE" in r.values.get("active_faults", "") for r in result.records
    )
    fault_seen = any(
        "BATTERY_OVERTEMP" in r.values.get("active_faults", "") for r in result.records
    )
    shutdown_seen = any(
        r.values.get("safety_state") in {"SAFE_SHUTDOWN", "OFF"} for r in result.records
    )
    zero_torque_after_fault = any(
        r.values.get("torque_permitted") == 0.0
        and "BATTERY_OVERTEMP" in r.values.get("active_faults", "")
        for r in result.records
    )
    contactor_open = any(
        r.values.get("contactor_command") == "OPEN"
        and r.values.get("safety_state") in {"SAFE_SHUTDOWN", "FAULT"}
        for r in result.records
    )
    assert derate_seen, "expected DERATE from ramped battery temperature"
    assert fault_seen, "expected BATTERY_OVERTEMP fault from detection"
    assert zero_torque_after_fault
    assert shutdown_seen
    assert contactor_open
