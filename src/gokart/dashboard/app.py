"""FastAPI dashboard application."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from gokart.config.store import data_root, list_drive_modes, list_driver_profiles, list_vehicles
from gokart.dashboard.sim_controller import SimController
from gokart.sim.scenarios import BUILTIN_SCENARIOS
from gokart.telemetry.bus import TelemetryBus
from gokart.telemetry.channels import channel_schema
from gokart.telemetry.storage import TelemetryStore
from gokart.units import mps_to_kmh

STATIC_DIR = Path(__file__).resolve().parent / "static"


class SimStartRequest(BaseModel):
    vehicle_name: str
    vehicle_version: str
    scenario: str = "standing_start_30s"
    manual: bool = False
    speedup: float = Field(default=1.0, ge=0.0)


class SimInputsRequest(BaseModel):
    throttle: float = Field(ge=0.0, le=1.0)
    brake: float = Field(ge=0.0, le=1.0)


def create_app(
    *,
    bus: TelemetryBus | None = None,
    store: TelemetryStore | None = None,
) -> FastAPI:
    telemetry_bus = bus or TelemetryBus()
    telemetry_store = store or TelemetryStore()
    sim_controller = SimController(bus=telemetry_bus, store_path=telemetry_store.db_path)

    app = FastAPI(title="Go-Kart Dashboard", version="0.1.0")
    app.state.bus = telemetry_bus
    app.state.store = telemetry_store
    app.state.sim = sim_controller

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/channels")
    def api_channels() -> list[dict[str, str]]:
        return channel_schema()

    @app.get("/api/config/vehicles")
    def api_vehicles() -> list[dict[str, str]]:
        root = data_root()
        vehicles = []
        for path in list_vehicles(root=root):
            data = json.loads(path.read_text(encoding="utf-8"))
            vehicles.append(
                {
                    "name": data["name"],
                    "version": data["version"],
                }
            )
        return vehicles

    @app.get("/api/config/modes")
    def api_modes() -> list[str]:
        return [path.stem for path in list_drive_modes(root=data_root())]

    @app.get("/api/config/profiles")
    def api_profiles() -> list[str]:
        return [path.stem for path in list_driver_profiles(root=data_root())]

    @app.get("/api/config/scenarios")
    def api_scenarios() -> list[str]:
        return sorted(BUILTIN_SCENARIOS)

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
            "sample_count": session.sample_count,
            "start_soc": session.start_soc,
            "end_soc": session.end_soc,
        }

    @app.get("/api/sessions/{session_id}/samples")
    def api_session_samples(session_id: str, limit: int = 5000) -> list[dict[str, Any]]:
        if telemetry_store.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")
        samples = telemetry_store.load_samples(session_id)
        return samples[:limit]

    @app.post("/api/sim/start")
    def api_sim_start(request: SimStartRequest) -> dict[str, Any]:
        try:
            sim_controller.start(
                vehicle_name=request.vehicle_name,
                vehicle_version=request.vehicle_version,
                scenario_name=request.scenario,
                manual=request.manual,
                speedup=request.speedup,
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
        sim_controller.set_inputs(throttle=request.throttle, brake=request.brake)
        return {"status": "ok"}

    @app.post("/api/sim/arm")
    def api_sim_arm() -> dict[str, str]:
        sim_controller.arm()
        return {"status": "armed"}

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

    @app.websocket("/ws/live")
    async def ws_live(websocket: WebSocket) -> None:
        await websocket.accept()
        sub_id = telemetry_bus.subscribe(name="dashboard", maxsize=128)
        try:
            while True:
                sample = await asyncio.to_thread(telemetry_bus.poll, sub_id, timeout_s=0.05)
                if sample is not None:
                    payload = {
                        "type": "sample",
                        "channels": channel_schema(),
                        "data": sample,
                        "speed_kmh": mps_to_kmh(float(sample.get("speed_mps", 0.0))),
                    }
                    await websocket.send_json(payload)
                else:
                    await asyncio.sleep(0.01)
        except WebSocketDisconnect:
            pass
        finally:
            telemetry_bus.unsubscribe(sub_id)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app
