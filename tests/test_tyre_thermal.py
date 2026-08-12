"""Tyre temperature and wear tests."""

from __future__ import annotations

import pytest

from gokart.config.schemas.components import Tyre
from gokart.physics.load_transfer import WheelLoads
from gokart.physics.tyre_thermal import (
    TyreThermalParams,
    TyreThermalState,
    step_tyre_thermal,
    temperature_grip_multiplier,
    wear_grip_multiplier,
)
from gokart.physics.tyres import WheelTyreOutputs
from gokart.physics.vehicle import Environment, VehicleStepInputs, load_validated_vehicle_model


def _wheel_outputs(
    *,
    fl_long: float = 0.0,
    fl_lat: float = 0.0,
    fr_long: float = 0.0,
    fr_lat: float = 0.0,
    rl_long: float = 0.0,
    rr_long: float = 0.0,
    fl_normal: float = 450.0,
    fr_normal: float = 450.0,
    rl_normal: float = 450.0,
    rr_normal: float = 450.0,
) -> WheelTyreOutputs:
    loads = WheelLoads(
        fl_normal_n=fl_normal,
        fr_normal_n=fr_normal,
        rl_normal_n=rl_normal,
        rr_normal_n=rr_normal,
    )
    return WheelTyreOutputs(
        wheel_loads=loads,
        fl_longitudinal_n=fl_long,
        fl_lateral_n=fl_lat,
        fr_longitudinal_n=fr_long,
        fr_lateral_n=fr_lat,
        rl_longitudinal_n=rl_long,
        rl_lateral_n=0.0,
        rr_longitudinal_n=rr_long,
        rr_lateral_n=0.0,
        traction_force_n=rl_long + rr_long,
        traction_force_requested_n=rl_long + rr_long,
        normal_load_n=loads.front_normal_n + loads.rear_normal_n,
        lateral_force_n=fl_lat + fr_lat,
        longitudinal_grip_limit_n=900.0,
        front_normal_n=loads.front_normal_n,
        rear_normal_n=loads.rear_normal_n,
        front_longitudinal_n=fl_long + fr_long,
        rear_longitudinal_n=rl_long + rr_long,
        front_lateral_n=fl_lat + fr_lat,
        rear_lateral_n=0.0,
    )


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
    tyre_out = _wheel_outputs(
        fl_long=-400.0,
        fl_lat=600.0,
        fr_long=-400.0,
        fr_lat=600.0,
        rl_long=900.0,
        rr_long=900.0,
    )
    new_state, outputs = step_tyre_thermal(
        state,
        params,
        params,
        tyre_out=tyre_out,
        front_grip_coefficient=1.1,
        rear_grip_coefficient=1.1,
        speed_mps=12.0,
        dt=1.0,
    )
    assert outputs.fl_temp_c > 25.0
    assert outputs.rr_temp_c > 25.0
    assert new_state.fl.wear > 0.0
    assert new_state.rr.wear > 0.0


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
    assert outputs.tyre_temp_fl_c >= 20.0
    assert outputs.grip_front_effective > 0.0
    assert outputs.tyre_wear_front >= 0.0


def test_hard_driving_raises_tyre_temperature() -> None:
    vehicle = load_validated_vehicle_model("Scott_Kart_V2", "V2.0")
    state = vehicle.initial_state()
    start_temp = state.tyre_thermal.rr.temperature_c if state.tyre_thermal else 25.0
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
    assert outputs.tyre_temp_rr_c > start_temp + 5.0
    assert outputs.tyre_wear_rr > 0.0
    assert outputs.tyre_temp_rr_c < 95.0
    assert outputs.tyre_wear_rr < 0.01


def test_cornering_heats_outside_wheel_more_than_inside() -> None:
    vehicle = load_validated_vehicle_model("Scott_Kart_V2", "V2.0")
    state = vehicle.initial_state()
    for _ in range(500):
        state, outputs = vehicle.step(
            state,
            VehicleStepInputs(
                motor_torque_request_nm=40.0,
                regen_torque_request_nm=0.0,
                mechanical_brake=0.0,
                environment=Environment(),
                steering=0.8,
            ),
            dt=0.01,
        )
    assert outputs.normal_fr_n > outputs.normal_fl_n
    assert outputs.tyre_temp_fr_c >= outputs.tyre_temp_fl_c
