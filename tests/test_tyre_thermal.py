"""Tyre temperature and wear tests."""

from __future__ import annotations

import pytest

from gokart.config.schemas.components import Tyre
from gokart.physics.tyre_thermal import (
    TyreThermalParams,
    TyreThermalState,
    step_tyre_thermal,
    temperature_grip_multiplier,
    wear_grip_multiplier,
)
from gokart.physics.vehicle import Environment, VehicleState, VehicleStepInputs, load_validated_vehicle_model


def test_temperature_grip_is_best_at_optimal() -> None:
    peak = temperature_grip_multiplier(60.0, optimal_temp_c=60.0, temp_window_c=18.0)
    cold = temperature_grip_multiplier(25.0, optimal_temp_c=60.0, temp_window_c=18.0)
    hot = temperature_grip_multiplier(95.0, optimal_temp_c=60.0, temp_window_c=18.0)
    assert peak == pytest.approx(1.0)
    assert peak > cold
    assert peak > hot


def test_wear_reduces_grip() -> None:
    fresh = wear_grip_multiplier(0.0, max_wear=1.0, grip_falloff_per_wear=0.4)
    worn = wear_grip_multiplier(1.0, max_wear=1.0, grip_falloff_per_wear=0.4)
    assert fresh > worn


def test_slip_heats_tyres() -> None:
    tyre = Tyre(
        id="test",
        manufacturer="test",
        model="test",
        diameter_m=0.254,
        width_m=0.114,
        rolling_resistance_coefficient=0.015,
        dry_grip_coefficient=1.1,
        max_speed_mps=22.0,
        max_load_kg=120.0,
        heating_rate=0.05,
        cooling_rate=0.01,
    )
    params = TyreThermalParams.from_tyre(tyre, ambient_temp_c=25.0)
    state = TyreThermalState.initial(25.0)
    new_state, outputs = step_tyre_thermal(
        state,
        params,
        params,
        front_longitudinal_n=-800.0,
        front_lateral_n=600.0,
        rear_longitudinal_n=900.0,
        rear_lateral_n=0.0,
        front_normal_n=900.0,
        rear_normal_n=900.0,
        front_grip_coefficient=1.1,
        rear_grip_coefficient=1.1,
        speed_mps=12.0,
        dt=1.0,
    )
    assert outputs.front_temp_c > 25.0
    assert outputs.rear_temp_c > 25.0
    assert new_state.front.wear > 0.0
    assert new_state.rear.wear > 0.0


def test_vehicle_step_reports_tyre_telemetry() -> None:
    vehicle = load_validated_vehicle_model("Scott_Kart_V2", "V2.0")
    state = vehicle.initial_state()
    _, outputs = vehicle.step(
        state,
        VehicleStepInputs(
            motor_torque_request_nm=40.0,
            regen_torque_request_nm=0.0,
            mechanical_brake=0.0,
            environment=Environment(),
            steering=0.2,
        ),
        dt=0.5,
    )
    assert outputs.tyre_temp_front_c >= 20.0
    assert outputs.grip_front_effective > 0.0
    assert outputs.tyre_wear_front >= 0.0


def test_hard_driving_raises_tyre_temperature() -> None:
    vehicle = load_validated_vehicle_model("Scott_Kart_V2", "V2.0")
    state = vehicle.initial_state()
    start_temp = state.tyre_thermal.rear.temperature_c if state.tyre_thermal else 25.0
    for _ in range(800):
        state, outputs = vehicle.step(
            state,
            VehicleStepInputs(
                motor_torque_request_nm=45.0,
                regen_torque_request_nm=0.0,
                mechanical_brake=0.0,
                environment=Environment(),
                steering=0.75,
            ),
            dt=0.01,
        )
    assert outputs.tyre_temp_rear_c > start_temp + 5.0
    assert outputs.tyre_wear_rear > 0.0001
