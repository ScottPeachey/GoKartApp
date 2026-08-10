"""Runtime controls for interactive simulation and dashboard."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RuntimeControls:
    manual: bool = False
    free_mode: bool = False
    throttle: float = 0.0
    brake: float = 0.0
    steering: float = 0.0
    arm_request: bool = False
    power_on_request: bool = False
    disarm_request: bool = False
    fault_ack_request: bool = False
    stop_requested: bool = False
