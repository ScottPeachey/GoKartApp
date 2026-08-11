"""High-level vehicle configuration editing — hides hashes and file layout."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from gokart.config.audit import AuditLog
from gokart.config.hashing import content_hash
from gokart.config.schemas.components import COMPONENT_TYPE_MAP, ComponentBase
from gokart.config.schemas.vehicle import ComponentRef, DrivetrainConfig, VehicleConfig
from gokart.config.store import (
    ConfigStoreError,
    data_root,
    list_components,
    list_vehicles,
    load_component,
    load_vehicle,
    save_component,
    save_vehicle,
)
from gokart.config.validation import validate_intra_component, validate_vehicle_config


@dataclass(frozen=True)
class VehicleSlot:
    slot_id: str
    label: str
    field_name: str
    component_type: str
    required: bool = True


VEHICLE_SLOTS: tuple[VehicleSlot, ...] = (
    VehicleSlot("motor", "Motor", "motor", "motor"),
    VehicleSlot("motor_controller", "Motor controller", "motor_controller", "motor_controller"),
    VehicleSlot("battery", "Battery pack", "battery", "battery"),
    VehicleSlot("bms", "BMS", "bms", "bms"),
    VehicleSlot("front_tyre", "Front tyre", "front_tyre", "tyre", required=False),
    VehicleSlot("rear_tyre", "Rear tyre", "rear_tyre", "tyre", required=False),
    VehicleSlot("wheel", "Wheel", "wheel", "wheel", required=False),
    VehicleSlot("brake", "Brake", "brake", "brake", required=False),
    VehicleSlot("dcdc", "DC-DC converter", "dcdc", "dcdc", required=False),
    VehicleSlot("contactor", "Contactor", "contactor", "contactor", required=False),
)


COMPONENT_TYPE_LABELS: dict[str, str] = {
    "motor": "Motor",
    "motor_controller": "Motor controller",
    "battery": "Battery pack",
    "bms": "BMS",
    "tyre": "Tyre",
    "wheel": "Wheel",
    "brake": "Brake",
    "dcdc": "DC-DC converter",
    "contactor": "Contactor",
    "sensor": "Sensor",
}


class SaveComponentRequest(BaseModel):
    data: dict[str, Any]
    allow_overwrite: bool = False


class SaveComponentResult(BaseModel):
    id: str
    component_type: str
    content_hash: str
    validation_ok: bool
    violations: list[str] = Field(default_factory=list)


class SaveVehicleRequest(BaseModel):
    base_name: str
    base_version: str
    new_version: str | None = None
    slots: dict[str, str] = Field(default_factory=dict)
    drivetrain: DrivetrainConfig | None = None


class SaveVehicleResult(BaseModel):
    name: str
    version: str
    validation_ok: bool
    violations: list[str] = Field(default_factory=list)


def bump_version(version: str) -> str:
    match = re.fullmatch(r"V(\d+)\.(\d+)", version)
    if match:
        major, minor = match.groups()
        return f"V{major}.{int(minor) + 1}"
    return f"{version}.1"


def suggest_next_version(name: str, *, root: Path | None = None) -> str:
    store_root = data_root(root)
    versions: list[str] = []
    for path in list_vehicles(root=store_root):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("name") == name:
            versions.append(data["version"])
    if not versions:
        return "V1.0"
    return bump_version(sorted(versions)[-1])


def component_ref(component: ComponentBase) -> ComponentRef:
    digest = content_hash(component.model_dump(mode="json"))
    return ComponentRef(component_id=component.id, content_hash=digest)


def component_summary(component: ComponentBase) -> dict[str, Any]:
    data = component.model_dump(mode="json")
    summary: dict[str, Any] = {
        "id": component.id,
        "manufacturer": component.manufacturer,
        "model": component.model,
        "component_type": data.get("component_type"),
    }
    if hasattr(component, "peak_power_w"):
        summary["peak_power_w"] = component.peak_power_w
    if hasattr(component, "peak_torque_nm"):
        summary["peak_torque_nm"] = component.peak_torque_nm
    if hasattr(component, "nominal_voltage_v"):
        summary["nominal_voltage_v"] = component.nominal_voltage_v
    if hasattr(component, "capacity_ah"):
        summary["capacity_ah"] = component.capacity_ah
    if hasattr(component, "peak_discharge_current_a"):
        summary["peak_discharge_current_a"] = component.peak_discharge_current_a
    return summary


def list_component_summaries(
    component_type: str,
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    store_root = data_root(root)
    summaries: list[dict[str, Any]] = []
    for path in list_components(component_type, root=store_root):
        component = load_component(component_type, path.stem, root=store_root)
        summaries.append(component_summary(component))
    return sorted(summaries, key=lambda item: item["id"])


def list_component_types() -> list[dict[str, str]]:
    return [
        {"id": key, "label": COMPONENT_TYPE_LABELS.get(key, key)}
        for key in sorted(COMPONENT_TYPE_MAP)
    ]


def load_component_detail(
    component_type: str,
    component_id: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    component = load_component(component_type, component_id, root=data_root(root))
    return component.model_dump(mode="json")


def new_component_template(component_type: str, *, root: Path | None = None) -> dict[str, Any]:
    if component_type not in COMPONENT_TYPE_MAP:
        raise ConfigStoreError(f"Unknown component type: {component_type}")
    store_root = data_root(root)
    summaries = list_component_summaries(component_type, root=store_root)
    if not summaries:
        raise ConfigStoreError(f"No existing {component_type} components to use as a template")
    base = load_component(component_type, summaries[0]["id"], root=store_root)
    data = base.model_dump(mode="json")
    data["id"] = f"new_{component_type}"
    data["manufacturer"] = "New"
    data["model"] = "Component"
    data["notes"] = "Created in dashboard component editor"
    return data


def save_component_record(
    request: SaveComponentRequest,
    *,
    root: Path | None = None,
    actor: str = "dashboard",
) -> SaveComponentResult:
    store_root = data_root(root)
    component_type = request.data.get("component_type")
    if component_type not in COMPONENT_TYPE_MAP:
        return SaveComponentResult(
            id=str(request.data.get("id", "")),
            component_type=str(component_type or ""),
            content_hash="",
            validation_ok=False,
            violations=[f"Unknown component_type: {component_type}"],
        )
    model_cls = COMPONENT_TYPE_MAP[component_type]
    try:
        component: ComponentBase = model_cls.model_validate(request.data)
    except Exception as exc:
        return SaveComponentResult(
            id=str(request.data.get("id", "")),
            component_type=str(component_type),
            content_hash="",
            validation_ok=False,
            violations=[str(exc)],
        )

    intra = validate_intra_component(component)
    violations = [v.message for v in intra.violations]
    if not intra.ok:
        return SaveComponentResult(
            id=component.id,
            component_type=component_type,
            content_hash="",
            validation_ok=False,
            violations=violations,
        )

    try:
        digest = save_component(
            component,
            root=store_root,
            allow_overwrite=request.allow_overwrite,
        )
    except ConfigStoreError as exc:
        return SaveComponentResult(
            id=component.id,
            component_type=component_type,
            content_hash="",
            validation_ok=False,
            violations=[str(exc)],
        )

    AuditLog().record(
        actor=actor,
        entity_type="component",
        entity_id=f"{component_type}:{component.id}",
        from_hash=None,
        to_hash=digest,
        diff_summary="saved from dashboard",
        validation_ok=True,
        validation_messages=[],
    )
    return SaveComponentResult(
        id=component.id,
        component_type=component_type,
        content_hash=digest,
        validation_ok=True,
    )


def _slot_ref(vehicle: VehicleConfig, slot: VehicleSlot) -> ComponentRef | None:
    return getattr(vehicle, slot.field_name.strip())


def build_vehicle_detail(
    name: str,
    version: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    store_root = data_root(root)
    vehicle = load_vehicle(name, version, root=store_root)
    slots: dict[str, Any] = {}
    for slot in VEHICLE_SLOTS:
        ref = _slot_ref(vehicle, slot)
        if ref is None:
            if slot.required:
                slots[slot.slot_id] = {"label": slot.label, "fitted": None}
            continue
        component = load_component(slot.component_type, ref.component_id, root=store_root)
        slots[slot.slot_id] = {
            "label": slot.label,
            "component_type": slot.component_type,
            "component_id": ref.component_id,
            "summary": component_summary(component),
        }
    total_mass = vehicle.dry_mass_kg + vehicle.battery_mass_kg + vehicle.driver_mass_kg
    return {
        "name": vehicle.name,
        "version": vehicle.version,
        "suggested_next_version": suggest_next_version(vehicle.name, root=store_root),
        "mass_kg": total_mass,
        "dry_mass_kg": vehicle.dry_mass_kg,
        "battery_mass_kg": vehicle.battery_mass_kg,
        "driver_mass_kg": vehicle.driver_mass_kg,
        "wheelbase_m": vehicle.wheelbase_m,
        "front_track_m": vehicle.front_track_m,
        "rear_track_m": vehicle.rear_track_m,
        "drivetrain": vehicle.drivetrain.model_dump(mode="json"),
        "limits": vehicle.limits.model_dump(mode="json"),
        "slots": slots,
    }


def save_vehicle_as_new_version(
    request: SaveVehicleRequest,
    *,
    root: Path | None = None,
    actor: str = "dashboard",
) -> SaveVehicleResult:
    store_root = data_root(root)
    base = load_vehicle(request.base_name, request.base_version, root=store_root)
    new_version = request.new_version or suggest_next_version(base.name, root=store_root)

    updated = base.model_copy(deep=True)
    updated.version = new_version

    for slot in VEHICLE_SLOTS:
        if slot.slot_id not in request.slots:
            continue
        component_id = request.slots[slot.slot_id]
        component = load_component(slot.component_type, component_id, root=store_root)
        setattr(updated, slot.field_name.strip(), component_ref(component))

    if request.drivetrain is not None:
        updated.drivetrain = request.drivetrain

    validation = validate_vehicle_config(updated, data_root=store_root)
    audit = AuditLog()

    violations = [v.message for v in validation.violations]
    if not validation.ok:
        audit.record(
            actor=actor,
            entity_type="vehicle",
            entity_id=f"{updated.name}:{new_version}",
            from_hash=content_hash(base.model_dump(mode="json")),
            to_hash=None,
            diff_summary=f"rejected save from {base.version}",
            validation_ok=False,
            validation_messages=violations,
        )
        return SaveVehicleResult(
            name=updated.name,
            version=new_version,
            validation_ok=False,
            violations=violations,
        )

    try:
        digest = save_vehicle(updated, root=store_root, allow_overwrite=False)
    except ConfigStoreError as exc:
        return SaveVehicleResult(
            name=updated.name,
            version=new_version,
            validation_ok=False,
            violations=[str(exc)],
        )

    audit.record(
        actor=actor,
        entity_type="vehicle",
        entity_id=f"{updated.name}:{new_version}",
        from_hash=content_hash(base.model_dump(mode="json")),
        to_hash=digest,
        diff_summary=f"saved from {base.version}",
        validation_ok=True,
        validation_messages=[],
    )
    return SaveVehicleResult(name=updated.name, version=new_version, validation_ok=True)
