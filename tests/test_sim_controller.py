"""Dashboard simulation controller tests."""

from __future__ import annotations

from gokart.dashboard.sim_controller import SimController
from gokart.sim.runtime import RuntimeControls
from gokart.telemetry.bus import TelemetryBus


def test_fault_ack_persists_while_in_fault_state() -> None:
    controller = SimController(bus=TelemetryBus())
    controller.controls = RuntimeControls(manual=True, free_mode=True)
    controller.controls.fault_ack_request = True
    controller.controls.power_cycle_request = True

    controller.sync_controls_after_tick({"safety_state": "FAULT"})
    assert controller.controls.fault_ack_request is True
    assert controller.controls.power_cycle_request is True

    controller.sync_controls_after_tick({"safety_state": "READY"})
    assert controller.controls.fault_ack_request is False
    assert controller.controls.power_cycle_request is False
