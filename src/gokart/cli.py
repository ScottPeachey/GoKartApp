"""Command-line interface for go-kart configuration management."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gokart.config.audit import AuditLog
from gokart.config.hashing import content_hash
from gokart.config.schemas import COMPONENT_TYPE_MAP, ComponentBase
from gokart.config.store import (
    ConfigStoreError,
    data_root,
    list_components,
    list_drive_modes,
    list_driver_profiles,
    list_vehicles,
    load_config_file,
    load_vehicle,
    save_component,
)
from gokart.config.validation import validate_vehicle_config


def _print_violations(violations: list) -> None:
    for violation in violations:
        print(f"  [{violation.limiting_layer}] {violation.field}: {violation.message}")


def cmd_config_validate(args: argparse.Namespace) -> int:
    path = Path(args.file)
    kind, model = load_config_file(path)
    audit = AuditLog()

    if kind == "vehicle":
        result = validate_vehicle_config(model)
        audit.record(
            actor=args.actor,
            entity_type="vehicle",
            entity_id=f"{model.name}:{model.version}",
            from_hash=None,
            to_hash=content_hash(model.model_dump(mode="json")),
            diff_summary=f"validate {path}",
            validation_ok=result.ok,
            validation_messages=[v.message for v in result.violations],
        )
        if result.ok:
            print(f"OK: {path}")
            return 0
        print(f"INVALID: {path}")
        _print_violations(result.violations)
        return 1

    print(f"Validated {kind} file (field-level pydantic checks only): {path}")
    audit.record(
        actor=args.actor,
        entity_type=kind,
        entity_id=getattr(model, "id", getattr(model, "name", path.stem)),
        from_hash=None,
        to_hash=content_hash(model.model_dump(mode="json")),
        diff_summary=f"validate {path}",
        validation_ok=True,
        validation_messages=[],
    )
    return 0


def cmd_config_list(_args: argparse.Namespace) -> int:
    root = data_root()
    print("Vehicles:")
    for path in list_vehicles(root=root):
        print(f"  {path.relative_to(root)}")
    print("Drive modes:")
    for path in list_drive_modes(root=root):
        print(f"  {path.relative_to(root)}")
    print("Driver profiles:")
    for path in list_driver_profiles(root=root):
        print(f"  {path.relative_to(root)}")
    print("Components:")
    for path in list_components(root=root):
        print(f"  {path.relative_to(root)}")
    return 0


def cmd_config_show(args: argparse.Namespace) -> int:
    vehicle = load_vehicle(args.name, args.version)
    print(json.dumps(vehicle.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


def cmd_component_import(args: argparse.Namespace) -> int:
    path = Path(args.file)
    data = json.loads(path.read_text(encoding="utf-8"))
    component_type = data.get("component_type")
    if component_type not in COMPONENT_TYPE_MAP:
        print(f"Unknown component_type: {component_type}", file=sys.stderr)
        return 1
    model_cls = COMPONENT_TYPE_MAP[component_type]
    component: ComponentBase = model_cls.model_validate(data)
    digest = save_component(component, allow_overwrite=args.force)
    print(f"Imported {component_type}/{component.id} (hash {digest[:12]}...)")
    return 0


def cmd_component_export(args: argparse.Namespace) -> int:
    from gokart.config.store import load_component

    component = load_component(args.type, args.id)
    out = Path(args.out) if args.out else Path(f"{args.id}.json")
    out.write_text(
        json.dumps(component.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Exported to {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gokart", description="Go-kart configuration tools")
    parser.add_argument("--actor", default="cli", help="Actor name for audit log entries")
    sub = parser.add_subparsers(dest="command", required=True)

    config = sub.add_parser("config", help="Vehicle configuration commands")
    config_sub = config.add_subparsers(dest="config_command", required=True)

    validate = config_sub.add_parser("validate", help="Validate a configuration file")
    validate.add_argument("file", help="Path to JSON configuration file")
    validate.set_defaults(func=cmd_config_validate)

    list_cmd = config_sub.add_parser("list", help="List known configurations")
    list_cmd.set_defaults(func=cmd_config_list)

    show = config_sub.add_parser("show", help="Show a vehicle configuration")
    show.add_argument("name", help="Vehicle name")
    show.add_argument("version", help="Vehicle version")
    show.set_defaults(func=cmd_config_show)

    component = sub.add_parser("component", help="Component record commands")
    component_sub = component.add_subparsers(dest="component_command", required=True)

    imp = component_sub.add_parser("import", help="Import a component JSON file")
    imp.add_argument("file", help="Path to component JSON")
    imp.add_argument("--force", action="store_true", help="Allow overwrite")
    imp.set_defaults(func=cmd_component_import)

    exp = component_sub.add_parser("export", help="Export a component to JSON")
    exp.add_argument("type", help="Component type (motor, battery, ...)")
    exp.add_argument("id", help="Component id")
    exp.add_argument("--out", help="Output file path")
    exp.set_defaults(func=cmd_component_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigStoreError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
