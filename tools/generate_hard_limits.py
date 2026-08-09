#!/usr/bin/env python3
"""Emit compile-time hardware limit ceilings from seed vehicle configs."""

from __future__ import annotations

import json
from pathlib import Path

from gokart.config.schemas.components import BatteryPack, Bms, Motor, MotorController
from gokart.config.store import data_root, load_component, load_vehicle
from gokart.config.validation import hardware_limits_from_components

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "firmware" / "esp32" / "include" / "hard_limits.json"


def main() -> None:
    root = data_root()
    records = []
    for name, version in (("Scott Kart V1", "V1.0"), ("Scott Kart V2", "V2.0")):
        config = load_vehicle(name, version, root=root)
        motor = load_component("motor", config.motor.component_id, root=root)
        controller = load_component(
            "motor_controller", config.motor_controller.component_id, root=root
        )
        battery = load_component("battery", config.battery.component_id, root=root)
        bms = load_component("bms", config.bms.component_id, root=root)
        assert isinstance(motor, Motor)
        assert isinstance(controller, MotorController)
        assert isinstance(battery, BatteryPack)
        assert isinstance(bms, Bms)
        limits = hardware_limits_from_components(motor, controller, battery, bms)
        records.append(
            {
                "vehicle": name,
                "version": version,
                "limits": limits.model_dump(mode="json"),
            }
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
