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
from gokart.sim.engine import run_simulation, write_csv
from gokart.sim.scenarios import BUILTIN_SCENARIOS, load_scenario
from gokart.units import mps_to_kmh


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


def cmd_sim_run(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    result = run_simulation(
        args.vehicle,
        args.version,
        scenario,
        speedup=args.speedup,
        initial_speed_mps=args.initial_speed,
    )
    if args.out:
        write_csv(Path(args.out), result.records)
        print(f"Wrote {len(result.records)} samples to {args.out}")
    max_speed = max(record.values["speed_mps"] for record in result.records)
    print(
        f"Simulation complete: max speed {mps_to_kmh(max_speed):.1f} km/h, "
        f"final SOC {result.final_state.battery.soc:.3f}"
    )
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    import uvicorn

    from gokart.dashboard.app import create_app

    app = create_app()
    print(f"Dashboard: http://{args.host}:{args.port}/")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_analyze_session(args: argparse.Namespace) -> int:
    from gokart.analysis.metrics import compute_metrics
    from gokart.telemetry.storage import TelemetryStore

    store = TelemetryStore()
    session = store.get_session(args.session_id)
    if session is None:
        print(f"Session not found: {args.session_id}", file=sys.stderr)
        return 1
    samples = store.load_samples(args.session_id)
    metrics = compute_metrics(samples)
    print(f"Session {args.session_id}")
    print(f"  Vehicle: {session.vehicle_name} {session.vehicle_version}")
    print(f"  Samples: {session.sample_count}")
    for name, value in metrics.as_dict().items():
        if value is not None:
            print(f"  {name}: {value:.4g}" if isinstance(value, float) else f"  {name}: {value}")
    return 0


def cmd_analyze_compare(args: argparse.Namespace) -> int:
    from gokart.analysis.compare import compare_configs

    rows = compare_configs(
        [(args.vehicle, args.version_a), (args.vehicle, args.version_b)],
        args.scenario,
    )
    labels = [f"{args.vehicle} {args.version_a}", f"{args.vehicle} {args.version_b}"]
    print(f"{'Metric':<28} {labels[0]:>16} {labels[1]:>16} {'Delta':>12}")
    for row in rows:
        left = row.values[labels[0]]
        right = row.values[labels[1]]
        delta = row.delta
        left_s = f"{left:.4g}" if left is not None else "—"
        right_s = f"{right:.4g}" if right is not None else "—"
        delta_s = f"{delta:+.4g}" if delta is not None else "—"
        print(f"{row.metric:<28} {left_s:>16} {right_s:>16} {delta_s:>12}")
    return 0


def cmd_sweep_run(args: argparse.Namespace) -> int:
    from gokart.analysis.sweep import load_sweep_spec, run_sweep

    spec = load_sweep_spec(Path(args.spec))
    results = run_sweep(spec)
    print(f"{'Feasible':<10} {'Objective':>12} Parameters")
    for row in results:
        params = ", ".join(f"{k}={v}" for k, v in row.parameters.items())
        objective = f"{row.objective_value:.4g}" if row.objective_value is not None else "—"
        print(f"{str(row.feasible):<10} {objective:>12} {params}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from gokart.analysis.report import write_session_report

    out = Path(args.out) if args.out else Path(f"telemetry/reports/{args.session_id}.html")
    write_session_report(args.session_id, out)
    print(f"Wrote report to {out}")
    return 0


def cmd_track_import(args: argparse.Namespace) -> int:
    from gokart.track.importer import import_geojson_track
    from gokart.track.store import save_track

    track = import_geojson_track(
        Path(args.file),
        track_id=args.id,
        target_length_m=args.length,
        width_m=args.width,
        direction=args.direction,
        fetch_elevation=not args.no_elevation,
    )
    path = save_track(track, allow_overwrite=args.force)
    print(
        f"Imported track '{track.name}' ({track.id}): "
        f"{track.length_m:.0f} m, width {track.width_m:.0f} m, "
        f"scale {track.scale:.4f}"
    )
    print(f"Wrote {path}")
    return 0


def cmd_track_list(_args: argparse.Namespace) -> int:
    from gokart.track.store import list_tracks, load_track

    paths = list_tracks()
    if not paths:
        print("No tracks found.")
        return 0
    for path in paths:
        track = load_track(path.stem)
        print(f"  {track.id}: {track.name} ({track.length_m:.0f} m)")
    return 0


def cmd_track_import_f1(args: argparse.Namespace) -> int:
    from gokart.track.f1 import import_f1_circuits

    results = import_f1_circuits(
        width_m=args.width,
        direction=args.direction,
        fetch_elevation=not args.no_elevation,
        allow_overwrite=args.force,
    )
    ok_count = sum(1 for row in results if row.ok)
    fail_count = len(results) - ok_count
    for row in results:
        prefix = "OK" if row.ok else "FAIL"
        track_id = row.track_id or "—"
        print(f"{prefix:4} {row.filename:<18} {track_id:<12} {row.message}")
    print(f"\nImported {ok_count}/{len(results)} circuits.")
    return 1 if fail_count else 0


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

    sim = sub.add_parser("sim", help="Simulation commands")
    sim_sub = sim.add_subparsers(dest="sim_command", required=True)

    run = sim_sub.add_parser("run", help="Run a simulation scenario")
    run.add_argument("vehicle", help="Vehicle name")
    run.add_argument("version", help="Vehicle version")
    run.add_argument(
        "scenario",
        help=f"Built-in scenario name or JSON path ({', '.join(sorted(BUILTIN_SCENARIOS))})",
    )
    run.add_argument("--speedup", type=float, default=0.0, help="Real-time pacing factor (0=fast)")
    run.add_argument("--initial-speed", type=float, default=0.0, help="Initial speed in m/s")
    run.add_argument("--out", help="CSV output path")
    run.set_defaults(func=cmd_sim_run)

    dashboard = sub.add_parser("dashboard", help="Launch the virtual dashboard")
    dashboard.add_argument("--host", default="127.0.0.1", help="Bind host")
    dashboard.add_argument("--port", type=int, default=8000, help="Bind port")
    dashboard.set_defaults(func=cmd_dashboard)

    analyze = sub.add_parser("analyze", help="Session analysis commands")
    analyze_sub = analyze.add_subparsers(dest="analyze_command", required=True)

    session = analyze_sub.add_parser("session", help="Print metrics for a stored session")
    session.add_argument("session_id", help="Telemetry session UUID")
    session.set_defaults(func=cmd_analyze_session)

    compare = analyze_sub.add_parser("compare", help="Compare two config versions on a scenario")
    compare.add_argument("vehicle", help="Vehicle name")
    compare.add_argument("version_a", help="First version")
    compare.add_argument("version_b", help="Second version")
    compare.add_argument("scenario", help="Scenario name or path")
    compare.set_defaults(func=cmd_analyze_compare)

    sweep = sub.add_parser("sweep", help="Parameter sweep commands")
    sweep_sub = sweep.add_subparsers(dest="sweep_command", required=True)
    sweep_run = sweep_sub.add_parser("run", help="Run a sweep spec JSON file")
    sweep_run.add_argument("spec", help="Path to sweep spec JSON")
    sweep_run.set_defaults(func=cmd_sweep_run)

    report = sub.add_parser("report", help="Generate HTML session report")
    report.add_argument("session_id", help="Telemetry session UUID")
    report.add_argument("--out", help="Output HTML path")
    report.set_defaults(func=cmd_report)

    track = sub.add_parser("track", help="Track import commands")
    track_sub = track.add_subparsers(dest="track_command", required=True)

    track_import = track_sub.add_parser("import", help="Import a GeoJSON circuit as a kart track")
    track_import.add_argument("file", help="Path to GeoJSON file")
    track_import.add_argument("--id", help="Track id (defaults to slugified name)")
    track_import.add_argument(
        "--length",
        type=float,
        help="Target lap length in metres (default: auto-scale to 1000–1600 m)",
    )
    track_import.add_argument("--width", type=float, default=10.0, help="Track width in metres")
    track_import.add_argument(
        "--direction",
        choices=["clockwise", "counterclockwise"],
        default="clockwise",
        help="Racing direction",
    )
    track_import.add_argument(
        "--no-elevation",
        action="store_true",
        help="Skip elevation fetch (flat track)",
    )
    track_import.add_argument("--force", action="store_true", help="Allow overwrite existing track")
    track_import.set_defaults(func=cmd_track_import)

    track_list = track_sub.add_parser("list", help="List imported tracks")
    track_list.set_defaults(func=cmd_track_list)

    track_import_f1 = track_sub.add_parser(
        "import-f1",
        help="Download and import all F1 circuits from bacinger/f1-circuits",
    )
    track_import_f1.add_argument("--width", type=float, default=10.0, help="Track width in metres")
    track_import_f1.add_argument(
        "--direction",
        choices=["clockwise", "counterclockwise"],
        default="clockwise",
        help="Racing direction",
    )
    track_import_f1.add_argument(
        "--no-elevation",
        action="store_true",
        help="Skip elevation fetch (flat tracks)",
    )
    track_import_f1.add_argument(
        "--force",
        action="store_true",
        help="Allow overwrite existing tracks",
    )
    track_import_f1.set_defaults(func=cmd_track_import_f1)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ConfigStoreError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
