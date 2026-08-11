"""Background simulation runner for the dashboard."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from gokart.config.hashing import content_hash
from gokart.config.store import data_root, load_drive_mode, load_driver_profile, load_vehicle
from gokart.sim.engine import run_simulation
from gokart.sim.runtime import RuntimeControls
from gokart.sim.scenarios import Scenario, load_scenario
from gokart.track.store import load_track
from gokart.telemetry.bus import TelemetryBus
from gokart.telemetry.recorder import SessionMetadata, SessionRecorder


@dataclass
class SimStatus:
    running: bool = False
    session_id: str | None = None
    error: str | None = None
    last_sample: dict[str, Any] = field(default_factory=dict)


class SimController:
    def __init__(self, *, bus: TelemetryBus, store_path=None) -> None:
        self.bus = bus
        self.controls = RuntimeControls()
        self.status = SimStatus()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._recorder: SessionRecorder | None = None
        from gokart.telemetry.storage import TelemetryStore

        self._store = TelemetryStore(store_path) if store_path else TelemetryStore()

    def start(
        self,
        *,
        vehicle_name: str,
        vehicle_version: str,
        scenario_name: str,
        drive_mode: str = "default",
        driver_profile: str = "owner",
        manual: bool = False,
        free_mode: bool = False,
        speedup: float = 1.0,
        track_id: str | None = None,
    ) -> str:
        with self._lock:
            if self.status.running:
                raise RuntimeError("Simulation already running")
            self.controls = RuntimeControls(manual=manual, free_mode=free_mode)
            if free_mode:
                self.controls.power_on_request = True
            self.status = SimStatus(running=True)
            self._thread = threading.Thread(
                target=self._run,
                kwargs={
                    "vehicle_name": vehicle_name,
                    "vehicle_version": vehicle_version,
                    "scenario_name": scenario_name,
                    "drive_mode": drive_mode,
                    "driver_profile": driver_profile,
                    "speedup": speedup,
                    "manual": manual,
                    "free_mode": free_mode,
                    "track_id": track_id,
                },
                daemon=True,
            )
            self._thread.start()
            return "starting"

    def stop(self) -> None:
        self.controls.stop_requested = True

    def set_inputs(self, *, throttle: float, brake: float, steering: float = 0.0) -> None:
        self.controls.throttle = max(0.0, min(1.0, throttle))
        self.controls.brake = max(0.0, min(1.0, brake))
        self.controls.steering = max(-1.0, min(1.0, steering))

    def arm(self) -> None:
        self.controls.arm_request = True

    def power_on(self) -> None:
        self.controls.power_on_request = True

    def disarm(self) -> None:
        self.controls.disarm_request = True

    def acknowledge_fault(self) -> None:
        self.controls.fault_ack_request = True
        self.controls.power_cycle_request = True
        self.controls.power_on_request = True

    def reset(self) -> None:
        """Stop any running simulation and clear dashboard session state."""
        self.controls.stop_requested = True
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self.controls = RuntimeControls()
        self.status = SimStatus()
        self._recorder = None
        self._thread = None

    def _run(
        self,
        *,
        vehicle_name: str,
        vehicle_version: str,
        scenario_name: str,
        drive_mode: str,
        driver_profile: str,
        speedup: float,
        manual: bool,
        free_mode: bool,
        track_id: str | None,
    ) -> None:
        try:
            track = load_track(track_id) if track_id else None
            base = load_scenario(scenario_name)
            mode_name = drive_mode or base.mode_name
            profile_name = driver_profile or base.profile_name
            if free_mode:
                scenario = Scenario(
                    name="free_drive",
                    duration_s=1e9,
                    mode_name=mode_name,
                    profile_name=profile_name,
                    auto_boot=False,
                )
                self.controls.free_mode = True
                self.controls.manual = True
            elif manual:
                scenario = Scenario(
                    name="manual",
                    duration_s=1e9,
                    mode_name=mode_name,
                    profile_name=profile_name,
                    auto_boot=True,
                )
                self.controls.manual = True
            else:
                scenario = Scenario(
                    name=base.name,
                    duration_s=base.duration_s,
                    mode_name=mode_name,
                    profile_name=profile_name,
                    environment=base.environment,
                    inputs=base.inputs,
                    injections=base.injections,
                    auto_boot=base.auto_boot,
                    mode_changes=base.mode_changes,
                    profile_changes=base.profile_changes,
                )
            vehicle = load_vehicle(vehicle_name, vehicle_version, root=data_root())
            mode = load_drive_mode(scenario.mode_name, root=data_root())
            profile = load_driver_profile(scenario.profile_name, root=data_root())
            config_hash = content_hash(vehicle.model_dump(mode="json"))
            self._recorder = SessionRecorder(
                SessionMetadata(
                    vehicle_name=vehicle_name,
                    vehicle_version=vehicle_version,
                    config_hash=config_hash,
                    driver_profile=profile.name,
                    drive_mode=mode.name,
                    scenario_name=scenario.name,
                    track_id=track.id if track else None,
                ),
                store=self._store,
                bus=self.bus,
            )
            self.status.session_id = self._recorder.session_id

            def on_tick(tick) -> None:
                self.status.last_sample = tick.to_row()
                safety = str(tick.values.get("safety_state", "OFF"))
                if safety != "READY":
                    self.controls.arm_request = False
                if safety != "OFF":
                    self.controls.power_on_request = False
                if safety != "DRIVING":
                    self.controls.disarm_request = False
                self.controls.fault_ack_request = False
                self.controls.power_cycle_request = False

            result = run_simulation(
                vehicle_name,
                vehicle_version,
                scenario,
                speedup=speedup,
                controls=self.controls,
                on_tick=on_tick,
                recorder=self._recorder,
                keep_records=False,
                track=track,
            )
            if result.completed_laps:
                self._store.save_laps(
                    self._recorder.session_id,
                    [
                        {
                            "lap_number": lap.lap_number,
                            "lap_time_s": lap.lap_time_s,
                            "completed_at_time_s": lap.completed_at_time_s,
                        }
                        for lap in result.completed_laps
                    ],
                )
            end_soc = result.final_state.battery.soc if result.final_state.battery else None
            self._recorder.close(end_soc=end_soc)
        except Exception as exc:  # noqa: BLE001 - surface to dashboard
            self.status.error = str(exc)
        finally:
            self.status.running = False
            self.controls.stop_requested = False
