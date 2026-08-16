"""Thermal mass and ram-air cooling."""

from __future__ import annotations

from gokart.physics.thermal import (
    ThermalInputs,
    ThermalParams,
    ThermalState,
    ram_air_cooling_scale,
    step_thermal,
)


def test_ram_air_cooling_rises_with_speed_without_a_cap() -> None:
    assert ram_air_cooling_scale(0.0) == 1.0
    assert ram_air_cooling_scale(12.5) == 2.25
    assert ram_air_cooling_scale(20.0) > ram_air_cooling_scale(14.0)
    assert ram_air_cooling_scale(-1.0) == 1.0


def test_faster_airflow_dumps_more_heat() -> None:
    params = ThermalParams(thermal_capacity_j_per_k=500.0, thermal_resistance_k_per_w=0.5)
    hot = ThermalState(temperature_c=70.0)
    inputs = ThermalInputs(heat_w=50.0)
    _, still = step_thermal(hot, inputs, params, 1.0, cooling_scale=ram_air_cooling_scale(0.0))
    _, moving = step_thermal(hot, inputs, params, 1.0, cooling_scale=ram_air_cooling_scale(12.5))
    assert moving.temperature_c < still.temperature_c
