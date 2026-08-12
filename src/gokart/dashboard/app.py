"""FastAPI dashboard application."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from gokart.config.editor import (
    VEHICLE_SLOTS,
    SaveComponentRequest,
    SaveVehicleRequest,
    build_vehicle_detail,
    list_component_summaries,
    list_component_types,
    load_component_detail,
    new_component_template,
    save_component_record,
    save_vehicle_as_new_version,
)
from gokart.config.schemas.modes import DriveMode, DriverProfile
from gokart.config.store import (
    ConfigStoreError,
    data_root,
    list_drive_modes,
    list_driver_profiles,
    list_vehicles,
    load_drive_mode,
    load_driver_profile,
    save_drive_mode,
    save_driver_profile,
)
from gokart.dashboard.limits import compute_effective_limits
from gokart.dashboard.sim_controller import SimController
from gokart.dashboard.training_controller import TrainingController, TrainingRunRequest
from gokart.sim.scenarios import BUILTIN_SCENARIOS
from gokart.telemetry.bus import TelemetryBus
from gokart.telemetry.channels import channel_schema
from gokart.telemetry.storage import TelemetryStore
from gokart.track.api import track_detail, track_summary
from gokart.track.store import (
    list_tracks,
    load_track,
    update_track_direction,
    update_track_start_finish,
)
from gokart.units import mps_to_kmh

STATIC_DIR = Path(__file__).resolve().parent / "static"


class SimStartRequest(BaseModel):
    vehicle_name: str
    vehicle_version: str
    scenario: str = "standing_start_30s"
    drive_mode: str = "default"
    driver_profile: str = "owner"
    manual: bool = False
    free_mode: bool = False
    auto_drive: bool = False
    learned_drive: bool = False
    policy_objective: str = "god"
    target_laps: int = Field(default=3, ge=1, le=50)
    aggression: float = Field(default=1.0, ge=0.5, le=1.0)
    speedup: float = Field(default=1.0, ge=0.0)
    track_id: str | None = None


class SaveDriveSettingRequest(BaseModel):
    data: dict[str, Any]
    allow_overwrite: bool = True


class SimInputsRequest(BaseModel):
    throttle: float = Field(ge=0.0, le=1.0)
    brake: float = Field(ge=0.0, le=1.0)
    steering: float = Field(default=0.0, ge=-1.0, le=1.0)


class VehicleDetailRequest(BaseModel):
    vehicle_name: str
    vehicle_version: str


class SaveStartFinishRequest(BaseModel):
    s_m: float = Field(ge=0.0)
    width_m: float | None = Field(default=None, gt=0.0)


class SaveTrackDirectionRequest(BaseModel):
    direction: Literal["clockwise", "counterclockwise"]


class RlTrainStartRequest(BaseModel):
    vehicle_name: str
    vehicle_version: str
    track_id: str
    drive_mode: str = "default"
    driver_profile: str = "owner"
    objective: str = "god"
    target_laps: int = Field(default=3, ge=1, le=50)
    total_timesteps: int = Field(default=50_000, ge=1_000, le=5_000_000)
    preview_freq: int = Field(default=10_000, ge=500, le=500_000)
    seed: int = 0


PHYSICS_REVISION = "tyre-v1"


def create_app(
    *,
    bus: TelemetryBus | None = None,
    store: TelemetryStore | None = None,
) -> FastAPI:
    telemetry_bus = bus or TelemetryBus()
    telemetry_store = store or TelemetryStore()
    sim_controller = SimController(bus=telemetry_bus, store_path=telemetry_store.db_path)
    training_controller = TrainingController(bus=telemetry_bus)

    app = FastAPI(title="Go-Kart Dashboard", version="0.1.0")
    app.state.bus = telemetry_bus
    app.state.store = telemetry_store
    app.state.sim = sim_controller
    app.state.training = training_controller

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "index.html",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/api/channels")
    def api_channels() -> list[dict[str, str]]:
        return channel_schema()

    @app.get("/api/version")
    def api_version() -> dict[str, str]:
        return {
            "dashboard": "0.2.1",
            "physics": PHYSICS_REVISION,
            "data_root": str(data_root()),
        }

    @app.get("/api/config/vehicles")
    def api_vehicles(include_detail: bool = True) -> list[dict[str, Any]]:
        root = data_root()
        vehicles: list[dict[str, Any]] = []
        for path in list_vehicles(root=root):
            data = json.loads(path.read_text(encoding="utf-8"))
            entry: dict[str, Any] = {
                "name": data["name"],
                "version": data["version"],
            }
            if include_detail:
                entry["detail"] = build_vehicle_detail(data["name"], data["version"], root=root)
            vehicles.append(entry)
        return vehicles

    @app.get("/api/config/modes")
    def api_modes() -> list[str]:
        return [path.stem for path in list_drive_modes(root=data_root())]

    @app.get("/api/config/modes/{name}")
    def api_mode_detail(name: str) -> dict[str, Any]:
        try:
            return load_drive_mode(name, root=data_root()).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/config/modes/save")
    def api_save_mode(request: SaveDriveSettingRequest) -> dict[str, Any]:
        if sim_controller.status.running:
            raise HTTPException(
                status_code=409,
                detail="Stop the simulation before saving drive mode changes.",
            )
        mode = DriveMode.model_validate(request.data)
        save_drive_mode(mode, root=data_root(), allow_overwrite=request.allow_overwrite)
        return {"status": "saved", "name": mode.name}

    @app.get("/api/config/profiles")
    def api_profiles() -> list[str]:
        return [path.stem for path in list_driver_profiles(root=data_root())]

    @app.get("/api/config/profiles/{name}")
    def api_profile_detail(name: str) -> dict[str, Any]:
        try:
            return load_driver_profile(name, root=data_root()).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/config/profiles/save")
    def api_save_profile(request: SaveDriveSettingRequest) -> dict[str, Any]:
        if sim_controller.status.running:
            raise HTTPException(
                status_code=409,
                detail="Stop the simulation before saving driver profile changes.",
            )
        profile = DriverProfile.model_validate(request.data)
        save_driver_profile(profile, root=data_root(), allow_overwrite=request.allow_overwrite)
        return {"status": "saved", "name": profile.name}

    @app.get("/api/config/effective-limits")
    def api_effective_limits(
        vehicle_name: str,
        vehicle_version: str,
        mode: str,
        profile: str,
    ) -> dict[str, Any]:
        try:
            return compute_effective_limits(
                vehicle_name=vehicle_name,
                vehicle_version=vehicle_version,
                mode_name=mode,
                profile_name=profile,
                root=data_root(),
            )
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/config/scenarios")
    def api_scenarios() -> list[str]:
        return sorted(BUILTIN_SCENARIOS)

    @app.get("/api/config/slots")
    def api_slots() -> list[dict[str, str | bool]]:
        return [
            {
                "id": slot.slot_id,
                "label": slot.label,
                "component_type": slot.component_type,
                "required": slot.required,
            }
            for slot in VEHICLE_SLOTS
        ]

    @app.get("/api/config/vehicle-detail")
    def api_vehicle_detail_query(vehicle_name: str, vehicle_version: str) -> dict[str, Any]:
        try:
            return build_vehicle_detail(vehicle_name, vehicle_version, root=data_root())
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/config/vehicle-detail")
    def api_vehicle_detail_post(request: VehicleDetailRequest) -> dict[str, Any]:
        try:
            return build_vehicle_detail(
                request.vehicle_name,
                request.vehicle_version,
                root=data_root(),
            )
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/config/vehicles/{name}/{version}/detail")
    def api_vehicle_detail(name: str, version: str) -> dict[str, Any]:
        try:
            return build_vehicle_detail(name, version, root=data_root())
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/config/component-types")
    def api_component_types() -> list[dict[str, str]]:
        return list_component_types()

    @app.get("/api/config/components/{component_type}/template")
    def api_component_template(component_type: str) -> dict[str, Any]:
        try:
            return new_component_template(component_type, root=data_root())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/config/components/{component_type}/{component_id}")
    def api_component_detail(component_type: str, component_id: str) -> dict[str, Any]:
        try:
            return load_component_detail(component_type, component_id, root=data_root())
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/config/components/save")
    def api_save_component(request: SaveComponentRequest) -> dict[str, Any]:
        if sim_controller.status.running:
            raise HTTPException(
                status_code=409,
                detail="Stop the simulation before saving component changes.",
            )
        result = save_component_record(request, root=data_root(), actor="dashboard")
        if not result.validation_ok:
            raise HTTPException(
                status_code=400,
                detail={"message": "Validation failed", "violations": result.violations},
            )
        return result.model_dump(mode="json")

    @app.get("/api/config/components/{component_type}")
    def api_components(component_type: str) -> list[dict[str, Any]]:
        try:
            return list_component_summaries(component_type, root=data_root())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/config/vehicles/save")
    def api_save_vehicle(request: SaveVehicleRequest) -> dict[str, Any]:
        if sim_controller.status.running:
            raise HTTPException(
                status_code=409,
                detail="Stop the simulation before saving configuration changes.",
            )
        result = save_vehicle_as_new_version(request, root=data_root(), actor="dashboard")
        if not result.validation_ok:
            raise HTTPException(
                status_code=400,
                detail={"message": "Validation failed", "violations": result.violations},
            )
        return result.model_dump(mode="json")

    @app.get("/api/sessions")
    def api_sessions(
        config_hash: str | None = None,
        vehicle_name: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sessions = telemetry_store.list_sessions(
            config_hash=config_hash,
            vehicle_name=vehicle_name,
            limit=limit,
        )
        return [
            {
                "session_id": session.session_id,
                "started_at": session.started_at,
                "ended_at": session.ended_at,
                "vehicle_name": session.vehicle_name,
                "vehicle_version": session.vehicle_version,
                "config_hash": session.config_hash,
                "driver_profile": session.driver_profile,
                "drive_mode": session.drive_mode,
                "scenario_name": session.scenario_name,
                "track_id": session.track_id,
                "sample_count": session.sample_count,
                "start_soc": session.start_soc,
                "end_soc": session.end_soc,
            }
            for session in sessions
        ]

    @app.get("/api/sessions/{session_id}")
    def api_session(session_id: str) -> dict[str, Any]:
        session = telemetry_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return {
            "session_id": session.session_id,
            "started_at": session.started_at,
            "ended_at": session.ended_at,
            "vehicle_name": session.vehicle_name,
            "vehicle_version": session.vehicle_version,
            "config_hash": session.config_hash,
            "driver_profile": session.driver_profile,
            "drive_mode": session.drive_mode,
            "scenario_name": session.scenario_name,
            "track_id": session.track_id,
            "sample_count": session.sample_count,
            "start_soc": session.start_soc,
            "end_soc": session.end_soc,
        }

    @app.get("/api/sessions/{session_id}/samples")
    def api_session_samples(session_id: str, limit: int = 5000) -> list[dict[str, Any]]:
        if telemetry_store.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")
        samples = telemetry_store.load_samples(session_id, limit=limit)
        return samples

    @app.get("/api/sessions/{session_id}/laps")
    def api_session_laps(session_id: str) -> list[dict[str, Any]]:
        if telemetry_store.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")
        laps = telemetry_store.list_laps(session_id)
        return [
            {
                "lap_number": lap.lap_number,
                "lap_time_s": lap.lap_time_s,
                "completed_at_time_s": lap.completed_at_time_s,
            }
            for lap in laps
        ]

    @app.get("/api/rl/policy")
    def api_rl_policy(
        vehicle_name: str,
        vehicle_version: str,
        track_id: str,
        drive_mode: str = "default",
        driver_profile: str = "owner",
        objective: str = "god",
    ) -> dict[str, Any]:
        from gokart.rl.policy_key import build_policy_identity
        from gokart.rl.registry import load_manifest, model_path

        identity = build_policy_identity(
            vehicle_name=vehicle_name,
            vehicle_version=vehicle_version,
            track_id=track_id,
            drive_mode=drive_mode,
            driver_profile=driver_profile,
            objective=objective,  # type: ignore[arg-type]
        )
        manifest = load_manifest(identity)
        return {
            "policy_key": identity.policy_key,
            "available": manifest is not None and model_path(identity).exists(),
            "status": manifest.status if manifest else None,
            "ceiling_lap_s": manifest.ceiling_lap_s if manifest else None,
            "clean_lap_rate": manifest.clean_lap_rate if manifest else None,
        }

    @app.get("/api/rl/train/status")
    def api_rl_train_status() -> dict[str, Any]:
        return training_controller.snapshot()

    @app.post("/api/rl/train/start")
    def api_rl_train_start(request: RlTrainStartRequest) -> dict[str, Any]:
        if sim_controller.status.running:
            raise HTTPException(
                status_code=409,
                detail="Stop the simulation before starting training.",
            )
        try:
            training_controller.start(
                TrainingRunRequest(
                    vehicle_name=request.vehicle_name,
                    vehicle_version=request.vehicle_version,
                    track_id=request.track_id,
                    drive_mode=request.drive_mode,
                    driver_profile=request.driver_profile,
                    objective=request.objective,
                    target_laps=request.target_laps,
                    total_timesteps=request.total_timesteps,
                    preview_freq=request.preview_freq,
                    seed=request.seed,
                )
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"status": "started", "training": training_controller.snapshot()}

    @app.post("/api/rl/train/stop")
    def api_rl_train_stop() -> dict[str, str]:
        training_controller.stop()
        return {"status": "stopping"}

    @app.post("/api/rl/train/reset")
    def api_rl_train_reset() -> dict[str, str]:
        training_controller.reset()
        return {"status": "reset"}

    @app.post("/api/sim/start")
    def api_sim_start(request: SimStartRequest) -> dict[str, Any]:
        if training_controller.status.running:
            raise HTTPException(
                status_code=409,
                detail="Stop RL training before starting a simulation.",
            )
        try:
            sim_controller.start(
                vehicle_name=request.vehicle_name,
                vehicle_version=request.vehicle_version,
                scenario_name=request.scenario,
                drive_mode=request.drive_mode,
                driver_profile=request.driver_profile,
                manual=request.manual,
                free_mode=request.free_mode,
                auto_drive=request.auto_drive,
                learned_drive=request.learned_drive,
                policy_objective=request.policy_objective,
                target_laps=request.target_laps,
                aggression=request.aggression,
                speedup=request.speedup,
                track_id=request.track_id,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"status": "started", "session_id": sim_controller.status.session_id}

    @app.post("/api/sim/stop")
    def api_sim_stop() -> dict[str, str]:
        sim_controller.stop()
        return {"status": "stopping"}

    @app.post("/api/sim/inputs")
    def api_sim_inputs(request: SimInputsRequest) -> dict[str, str]:
        sim_controller.set_inputs(
            throttle=request.throttle,
            brake=request.brake,
            steering=request.steering,
        )
        return {"status": "ok"}

    @app.post("/api/sim/arm")
    def api_sim_arm() -> dict[str, str]:
        sim_controller.arm()
        return {"status": "armed"}

    @app.post("/api/sim/power-on")
    def api_sim_power_on() -> dict[str, str]:
        sim_controller.power_on()
        return {"status": "power_on"}

    @app.post("/api/sim/disarm")
    def api_sim_disarm() -> dict[str, str]:
        sim_controller.disarm()
        return {"status": "disarmed"}

    @app.post("/api/sim/reset")
    def api_sim_reset() -> dict[str, str]:
        sim_controller.reset()
        return {"status": "reset"}

    @app.post("/api/sim/ack")
    def api_sim_ack() -> dict[str, str]:
        sim_controller.acknowledge_fault()
        return {"status": "acknowledged"}

    @app.get("/api/sim/status")
    def api_sim_status() -> dict[str, Any]:
        sample = sim_controller.status.last_sample
        speed_kmh = mps_to_kmh(float(sample.get("speed_mps", 0.0))) if sample else 0.0
        return {
            "running": sim_controller.status.running,
            "session_id": sim_controller.status.session_id,
            "error": sim_controller.status.error,
            "speed_kmh": speed_kmh,
            "sample": sample,
        }

    @app.get("/api/tracks")
    def api_tracks() -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for path in list_tracks():
            track = load_track(path.stem)
            summaries.append(track_summary(track))
        return summaries

    @app.get("/api/tracks/{track_id}")
    def api_track_detail(track_id: str) -> dict[str, Any]:
        try:
            track = load_track(track_id)
        except ConfigStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return track_detail(track)

    @app.post("/api/tracks/{track_id}/start-finish")
    def api_track_save_start_finish(
        track_id: str,
        request: SaveStartFinishRequest,
    ) -> dict[str, Any]:
        try:
            track = update_track_start_finish(
                track_id,
                request.s_m,
                width_m=request.width_m,
            )
        except ConfigStoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return track_detail(track)

    @app.post("/api/tracks/{track_id}/direction")
    def api_track_save_direction(
        track_id: str,
        request: SaveTrackDirectionRequest,
    ) -> dict[str, Any]:
        try:
            track = update_track_direction(track_id, request.direction)
        except ConfigStoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return track_detail(track)

    @app.websocket("/ws/live")
    async def ws_live(websocket: WebSocket) -> None:
        await websocket.accept()
        sub_id = telemetry_bus.subscribe(name="dashboard", maxsize=128)
        sent_schema = False
        last_metrics_seq = 0
        try:
            while True:
                sample = await asyncio.to_thread(telemetry_bus.poll, sub_id, timeout_s=0.05)
                if sample is not None:
                    payload: dict[str, Any] = {
                        "type": "sample",
                        "data": sample,
                        "speed_kmh": mps_to_kmh(float(sample.get("speed_mps", 0.0))),
                    }
                    if not sent_schema:
                        payload["channels"] = channel_schema()
                        sent_schema = True
                    await websocket.send_json(payload)

                metrics = training_controller.poll_metrics(last_metrics_seq)
                if metrics is not None:
                    last_metrics_seq = int(metrics.get("seq", last_metrics_seq))
                    await websocket.send_json({"type": "training_metrics", "data": metrics})
                elif sample is None:
                    await asyncio.sleep(0.01)
        except WebSocketDisconnect:
            pass
        finally:
            telemetry_bus.unsubscribe(sub_id)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app
