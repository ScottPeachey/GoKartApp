"""Signal-level fault injection for simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gokart.safety.faults import SensorInputs


@dataclass(frozen=True)
class SignalOverride:
    field_name: str
    value: float | int | bool


@dataclass(frozen=True)
class ValueRamp:
    start_time_s: float
    duration_s: float
    from_value: float
    to_value: float
    field_name: str

    def value_at(self, time_s: float) -> float:
        if time_s <= self.start_time_s:
            return self.from_value
        if time_s >= self.start_time_s + self.duration_s:
            return self.to_value
        ratio = (time_s - self.start_time_s) / self.duration_s
        return self.from_value + ratio * (self.to_value - self.from_value)


@dataclass(frozen=True)
class BusInjection:
    drop_can: bool = False
    can_silence_s: float | None = None
    vesc_fault: bool | None = None
    bms_fault: bool | None = None
    precharge_feedback_ok: bool | None = None
    contactor_feedback_closed: bool | None = None
    watchdog_reset: bool | None = None


@dataclass(frozen=True)
class InjectionEvent:
    time_s: float
    overrides: tuple[SignalOverride, ...] = ()
    ramp: ValueRamp | None = None
    bus: BusInjection | None = None


@dataclass
class FaultInjector:
    events: list[InjectionEvent] = field(default_factory=list)
    _can_drop_until_s: float = -1.0

    @classmethod
    def from_scenario_data(cls, data: list[dict[str, Any]] | None) -> FaultInjector:
        if not data:
            return cls()
        events: list[InjectionEvent] = []
        for entry in data:
            overrides = tuple(
                SignalOverride(field_name=item["field"], value=item["value"])
                for item in entry.get("overrides", [])
            )
            ramp = None
            if "ramp" in entry:
                ramp_data = entry["ramp"]
                ramp = ValueRamp(
                    start_time_s=entry["time_s"],
                    duration_s=ramp_data["duration_s"],
                    from_value=ramp_data["from"],
                    to_value=ramp_data["to"],
                    field_name=ramp_data["field"],
                )
            bus = None
            if "bus" in entry:
                bus_data = entry["bus"]
                bus = BusInjection(
                    drop_can=bus_data.get("drop_can", False),
                    can_silence_s=bus_data.get("can_silence_s"),
                    vesc_fault=bus_data.get("vesc_fault"),
                    bms_fault=bus_data.get("bms_fault"),
                    precharge_feedback_ok=bus_data.get("precharge_feedback_ok"),
                    contactor_feedback_closed=bus_data.get("contactor_feedback_closed"),
                    watchdog_reset=bus_data.get("watchdog_reset"),
                )
            events.append(
                InjectionEvent(
                    time_s=entry["time_s"],
                    overrides=overrides,
                    ramp=ramp,
                    bus=bus,
                )
            )
        return cls(events=events)

    def apply(self, time_s: float, sensors: SensorInputs) -> SensorInputs:
        data = sensors.__dict__.copy()
        for event in self.events:
            if event.time_s > time_s:
                continue
            if event.ramp is not None:
                data[event.ramp.field_name] = event.ramp.value_at(time_s)
            for override in event.overrides:
                data[override.field_name] = override.value
            if event.bus is not None:
                bus = event.bus
                if bus.drop_can:
                    self._can_drop_until_s = max(self._can_drop_until_s, time_s + 10.0)
                if bus.can_silence_s is not None:
                    data["can_silence_s"] = bus.can_silence_s
                if bus.vesc_fault is not None:
                    data["vesc_fault_active"] = bus.vesc_fault
                if bus.bms_fault is not None:
                    data["bms_fault_active"] = bus.bms_fault
                if bus.precharge_feedback_ok is not None:
                    data["precharge_feedback_ok"] = bus.precharge_feedback_ok
                if bus.contactor_feedback_closed is not None:
                    data["contactor_feedback_closed"] = bus.contactor_feedback_closed
                if bus.watchdog_reset is not None:
                    data["watchdog_reset_detected"] = bus.watchdog_reset

        if time_s <= self._can_drop_until_s:
            data["can_vesc_alive"] = False
            data["can_bms_alive"] = False

        return SensorInputs(**data)
