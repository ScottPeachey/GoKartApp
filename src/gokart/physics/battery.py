"""Equivalent-circuit battery model."""

from __future__ import annotations

from dataclasses import dataclass

from gokart.config.schemas.components import BatteryPack, SocCurvePoint


@dataclass(frozen=True)
class BatteryParams:
    capacity_ah: float
    capacity_as: float
    nominal_voltage_v: float
    min_voltage_v: float
    max_voltage_v: float
    internal_resistance_ohm: float
    max_discharge_current_a: float
    max_charge_current_a: float
    ocv_curve: tuple[SocCurvePoint, ...]
    resistance_curve: tuple[SocCurvePoint, ...]

    @classmethod
    def from_component(cls, battery: BatteryPack) -> BatteryParams:
        ocv = tuple(battery.ocv_curve) if battery.ocv_curve else _default_lifepo4_ocv(battery)
        resistance = tuple(battery.resistance_curve) if battery.resistance_curve else ()
        return cls(
            capacity_ah=battery.capacity_ah,
            capacity_as=battery.capacity_ah * 3600.0,
            nominal_voltage_v=battery.nominal_voltage_v,
            min_voltage_v=battery.min_voltage_v,
            max_voltage_v=battery.max_voltage_v,
            internal_resistance_ohm=battery.internal_resistance_ohm,
            max_discharge_current_a=battery.peak_discharge_current_a,
            max_charge_current_a=battery.max_charge_current_a,
            ocv_curve=ocv,
            resistance_curve=resistance,
        )


def _default_lifepo4_ocv(battery: BatteryPack) -> tuple[SocCurvePoint, ...]:
    return (
        SocCurvePoint(soc=0.0, value=battery.min_voltage_v),
        SocCurvePoint(soc=0.5, value=battery.nominal_voltage_v),
        SocCurvePoint(soc=1.0, value=battery.max_voltage_v),
    )


@dataclass
class BatteryState:
    soc: float = 1.0
    temperature_c: float = 25.0


@dataclass(frozen=True)
class BatteryInputs:
    current_a: float


@dataclass(frozen=True)
class BatteryOutputs:
    pack_voltage_v: float
    open_circuit_voltage_v: float
    internal_resistance_ohm: float
    current_a: float
    power_w: float
    remaining_energy_wh: float
    heat_w: float


def _interp_curve(soc: float, curve: tuple[SocCurvePoint, ...], fallback: float) -> float:
    if not curve:
        return fallback
    if soc <= curve[0].soc:
        return curve[0].value
    if soc >= curve[-1].soc:
        return curve[-1].value
    for left, right in zip(curve, curve[1:], strict=False):
        if left.soc <= soc <= right.soc:
            span = right.soc - left.soc
            if span <= 0:
                return right.value
            ratio = (soc - left.soc) / span
            return left.value + ratio * (right.value - left.value)
    return fallback


def step_battery(
    state: BatteryState,
    inputs: BatteryInputs,
    params: BatteryParams,
    dt: float,
) -> tuple[BatteryState, BatteryOutputs]:
    """Update SOC and compute terminal voltage under load."""
    current = inputs.current_a
    if current > 0:
        current = min(current, params.max_discharge_current_a)
    else:
        current = max(current, -params.max_charge_current_a)

    ocv = _interp_curve(state.soc, params.ocv_curve, params.nominal_voltage_v)
    resistance = _interp_curve(
        state.soc,
        params.resistance_curve,
        params.internal_resistance_ohm,
    )
    if current < 0.0 and resistance > 0.0:
        headroom_v = params.max_voltage_v - ocv
        if headroom_v <= 0.0:
            current = 0.0
        else:
            max_charge_a = headroom_v / resistance
            current = max(current, -min(abs(current), max_charge_a))

    pack_voltage = max(params.min_voltage_v, min(params.max_voltage_v, ocv - current * resistance))

    soc_delta = -(current * dt) / params.capacity_as
    new_soc = max(0.0, min(1.0, state.soc + soc_delta))
    heat = (current**2) * resistance

    remaining_energy_wh = new_soc * params.capacity_ah * params.nominal_voltage_v

    new_state = BatteryState(soc=new_soc, temperature_c=state.temperature_c)
    return new_state, BatteryOutputs(
        pack_voltage_v=pack_voltage,
        open_circuit_voltage_v=ocv,
        internal_resistance_ohm=resistance,
        current_a=current,
        power_w=pack_voltage * current,
        remaining_energy_wh=remaining_energy_wh,
        heat_w=heat,
    )
