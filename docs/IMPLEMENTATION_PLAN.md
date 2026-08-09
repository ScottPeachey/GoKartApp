# Electric Go-Kart Software — Implementation Plan

Version: 1.0
Date: 2026-08-09
Companion document: `docs/ARCHITECTURE.md` (read it first — it defines the
design; this document defines the build order).

---

## How to use this plan (instructions for the implementing agent)

- Work through phases **in order**. Within a phase, work through tasks in
  order unless a task explicitly says it is independent.
- **Do not start a phase until the previous phase's acceptance criteria all
  pass.** Run the full test suite before declaring a phase complete.
- Every task lists the files it creates or touches. Follow the repository
  layout in `ARCHITECTURE.md` Section 4 exactly.
- Write tests **with** the code, not after the phase. Safety, limits, and
  control code must be developed test-first: write the failing test, then
  the implementation.
- All internal values are SI units. Field names encode units
  (`mass_kg`, `max_speed_mps`, `peak_current_a`, `max_temp_c`). Never store
  km/h, hp, or other display units in data or logic.
- Pure-logic modules (`limits/`, `safety/`, `control/`, `physics/`) must not
  perform I/O, read the clock, use randomness, or hold module-level mutable
  state. All state goes in explicit dataclasses passed in and returned.
- When something is ambiguous, choose the simplest option consistent with
  `ARCHITECTURE.md`, note the decision in a `## Decisions` section appended
  to this file, and continue. Do not invent features beyond the current
  phase.
- Definition of done for every task: code + tests written, `pytest` green,
  `ruff check` and `ruff format --check` clean, no linter errors.

**MVP = Phases 0–5.** That delivers the spec's required end-to-end loop
(configure → validate → simulate → dashboard → log → analyse) before any
hardware exists. Phases 6–9 add firmware and hardware.

---

## Phase 0 — Project scaffolding

**Goal:** a working, tested, empty skeleton.

Tasks:

1. Create `pyproject.toml`: package `gokart`, `src/` layout, Python ≥ 3.12.
   Runtime deps: `pydantic>=2`, `numpy`, `fastapi`, `uvicorn`, `websockets`,
   `matplotlib`. Dev deps: `pytest`, `ruff`, `cantools`, `python-can`.
   Configure `ruff` (line length 100) and `pytest` in the same file.
2. Create the directory tree from `ARCHITECTURE.md` Section 4 (Python side
   only — `firmware/` waits until Phase 6): `src/gokart/{config/schemas,limits,control,safety,physics,sim,telemetry,analysis,dashboard,drivers}`,
   `shared/{schemas,can,golden}`, `data/{components,vehicles,drive_modes,driver_profiles}`,
   `tests/`, with `__init__.py` files and a trivial smoke test.
3. Create `src/gokart/units.py`: display-conversion helpers only
   (`mps_to_kmh`, `kmh_to_mps`, `rpm_to_rads`, `rads_to_rpm`, `c_to_k`).
   Document that these are for presentation and boundary conversion only.

**Acceptance:** `uv sync && uv run pytest` passes; `uv run ruff check` clean;
`uv run python -c "import gokart"` works.

---

## Phase 1 — Data model, component database, versioning, validation

**Goal:** the configuration backbone. Everything else consumes this.

Tasks:

1. **Component schemas** — `src/gokart/config/schemas/components.py`.
   Pydantic models per `ARCHITECTURE.md` 5.1 and spec Section 5:
   `Motor` (incl. optional torque/efficiency map as list of
   (rpm, torque_nm, efficiency) points, CSV-importable), `MotorController`,
   `BatteryPack` (electrical + thermal + optional OCV(SOC) and R(SOC) curves
   with sensible LiFePO4/NMC defaults), `Bms`, `Tyre`, `Wheel`, `Brake`,
   `DcDcConverter`, `Contactor`, `Sensor`. Common base: id, manufacturer,
   model, part number, datasheet path, source, price, date added, notes.
   Each carries its hardware absolute limits.
2. **Vehicle / mode / profile / calibration schemas** —
   `schemas/vehicle.py`, `schemas/modes.py`, `schemas/calibration.py`.
   Vehicle config references components by `(component_id, content_hash)`.
   Include the vehicle parameters from spec 4.1 and limit blocks per layer.
3. **Canonical hashing + store** — `config/store.py`. Canonical JSON
   (sorted keys, fixed float format) → SHA-256. Load/save/list components
   and vehicle configs under `data/`. Immutability rule: refuse to overwrite
   a file whose hash is referenced anywhere in the telemetry DB (dependency
   on Phase 4 — until then, refuse to overwrite, always create new version).
4. **Validation** — `config/validation.py`, implementing all four layers
   from `ARCHITECTURE.md` 5.2. Returns
   `ValidationResult(ok: bool, violations: list[Violation])` where each
   `Violation` names the field, the constraint, the limiting component/value,
   and a human-readable message.
5. **Limit resolver** — `src/gokart/limits/resolver.py` exactly as specified
   in `ARCHITECTURE.md` Section 6, including hardware-minimum aggregation
   across motor/controller/battery/BMS and derating factors.
6. **Audit log** — `config/audit.py`: append-only SQLite table
   (`telemetry/sessions.sqlite`, table `config_audit`) recording every
   accepted and rejected change with timestamp, entity, from/to hash, diff
   summary, validation outcome.
7. **Seed data** — `data/` entries for a plausible V1 kart (48 V / 40 Ah
   pack, ~5 kW motor, VESC-class controller, 12T/52T drivetrain) and a V2
   variant (72 V / 50 Ah, ~8–10 kW), three drive modes (e.g. Training: 20
   km/h; Normal: 40 km/h; Track: unrestricted-to-vehicle-limit) and two
   driver profiles (Owner, Junior). Values may be representative; they are
   placeholders the user will replace with real component data.
8. **CLI** — `src/gokart/cli.py` (exposed as `gokart` script):
   `gokart config validate <file>`, `gokart config list`,
   `gokart config show <name> <version>`, `gokart component import/export`.

**Tests (minimum):** schema round-trip (save→load→identical hash); hash
stability across key order; every validation layer has ≥1 accept and ≥1
reject case; hierarchy violations report the correct limiting layer; resolver
returns element-wise minimum and applies derating; audit rows written on
accept and reject.

**Acceptance:** seed V1 and V2 configs validate; deliberately raising a mode
limit above the vehicle limit is rejected with a message naming the vehicle
limit; `gokart config validate` exercises this from the command line.

---

## Phase 2 — Physics engine + simulation loop

**Goal:** configure → simulate works end-to-end (headless).

Tasks:

1. **Component physics** — `src/gokart/physics/`: `motor.py` (map
   interpolation with nameplate fallback), `drivetrain.py` (single ratio
   constant shared by kinematic and force paths), `tyres.py` (longitudinal
   friction + rolling resistance), `brakes.py` (mechanical + regen as
   separate paths), `battery.py` (equivalent circuit: OCV(SOC) interpolation,
   R(SOC,T), coulomb-counting SOC, sag, heat, remaining energy/range),
   `thermal.py` (single thermal mass per component), `aero.py`,
   `accessories.py` (LV power budget + brown-out flag).
   Each: pure `step(state, inputs, params, dt) -> (state, outputs)`.
2. **Vehicle composition** — `physics/vehicle.py`: builds all component
   models from a validated `VehicleConfig`, executes the data-flow order in
   `ARCHITECTURE.md` Section 9, integrates with semi-implicit Euler,
   dt = 0.01 s.
3. **Control pipeline (initial)** — `src/gokart/control/pipeline.py`:
   `control_step` per `ARCHITECTURE.md` Section 7. For this phase, safety
   gate is stubbed permissive (real one arrives in Phase 3); throttle curve,
   limit clamps, speed-limit taper, regen arbitration, and the traction
   limiter are real.
4. **Simulation engine** — `sim/engine.py` (tick loop per `ARCHITECTURE.md`
   Section 10), `sim/scenarios.py` (scenario dataclass + JSON loader +
   built-ins: standing start full throttle 30 s; hill climb; constant-speed
   cruise; duty cycle for range), `sim/clock.py` (real-time pacing vs
   accelerated).
5. **CLI** — `gokart sim run <vehicle> <version> <scenario> [--speedup N]
   [--out file.csv]` producing a CSV of all telemetry channels.

**Tests (minimum):** motor map interpolation vs hand-computed points;
kinematic/force path consistency (RPM-implied speed == integrated speed in
steady state); coast-down decelerates and stops (drag + rolling resistance);
top speed within tolerance of analytic force-balance solution for a simple
config; battery sags under load and SOC decreases monotonically under
discharge; energy conservation sanity (battery energy out ≥ kinetic + losses,
within tolerance); traction limiter caps torque on a low-µ surface scenario;
accelerated time produces identical traces to real-time (determinism).

**Acceptance:** `gokart sim run` on seed V1 with the standing-start scenario
produces a plausible trace (reaches a top speed in the 30–45 km/h band,
currents within configured limits at every sample) and the same command with
`--speedup 100` gives byte-identical results.

---

## Phase 3 — Drive modes, safety state machine, fault injection

**Goal:** the safety layer, fully unit-tested without hardware (spec-mandated).

Tasks:

1. **Fault registry** — `safety/faults.py`: every fault from
   `ARCHITECTURE.md` 8.2 as a declarative entry (id, severity, latching,
   detection parameters). Detection functions
   `detect_faults(inputs, config) -> set[FaultId]` are pure.
2. **State machine** — `safety/state_machine.py`: `safety_step` per
   `ARCHITECTURE.md` 8.3, covering the full state set, self-test sequence,
   arm preconditions (brake pressed + valid driver profile), precharge/
   contactor command sequencing with feedback timeout, fault-severity
   dispatch, recoverable-fault acknowledgement flow, and watchdog-reset
   detection on entry to BOOT.
3. **Wire into control** — replace the Phase 2 permissive stub: `sim/engine.py`
   now runs `detect_faults → safety_step → resolve_limits → control_step`
   every tick; derating factors from safety outputs feed the resolver.
4. **Fault injection** — `sim/fault_injection.py`: schedule sensor-value
   overrides or direct fault flags at time/condition triggers; injectable
   from scenario files.
5. **Mode/profile runtime switching** — mode changes only in READY or below
   `mode_change_max_speed_mps` (configurable, default 0 — stationary);
   profile switching only in READY.

**Tests (minimum):** full happy-path traversal OFF→…→DRIVING; every
FAULT/CRITICAL fault in the registry has an injection test asserting the
resulting state, torque-permitted flag, and contactor command; throttle+brake
plausibility zeroes torque; CAN-timeout fault fires at the configured
timeout; precharge feedback failure → CRITICAL; recoverable fault clears only
after condition gone + acknowledgement; latched critical persists until
power-cycle event; property-style test: for random input sequences, torque
is never permitted outside DRIVING, and commanded values never exceed
resolved limits.

**Acceptance:** a scenario that injects a battery over-temperature mid-run
shows (in the output CSV) derating, then FAULT on the higher threshold, zero
torque, and SAFE_SHUTDOWN contactor opening — with the state trace matching
the transition table in `ARCHITECTURE.md` 8.1.

---

## Phase 4 — Telemetry storage + virtual dashboard

**Goal:** watch the simulated kart live; every run is a stored session.

Tasks:

1. **Channel schema** — `telemetry/channels.py` per `ARCHITECTURE.md`
   Section 11 (single source of truth; CSV headers, SQLite columns, and
   WebSocket payloads all derive from it).
2. **Recorder + storage** — `telemetry/recorder.py`, `telemetry/storage.py`:
   session lifecycle (create with full metadata incl. config + calibration
   hashes, append samples at configured rate, close with end SOC), SQLite
   schema (`sessions`, `samples`), CSV export, session list/query API.
3. **Live bus** — `telemetry/bus.py`: in-process pub/sub with a bounded
   queue per subscriber; drops oldest on overflow (telemetry must never
   block the sim/control loop).
4. **Dashboard** — `dashboard/app.py` (FastAPI): serves static UI, WebSocket
   `/ws/live`, REST for sessions/configs; `dashboard/static/` plain
   HTML/JS/CSS. Driving view priority order: large speed (km/h), drive mode,
   SOC bar, fault banner, power. Tabs (stationary only): config browser,
   live channels table, session history with time-series charts (use a
   lightweight charting lib vendored into `static/`, e.g. uPlot).
   Sim controls: pick vehicle/version + scenario or manual throttle/brake
   sliders, start/stop, arm/acknowledge buttons (these drive the safety
   state machine's requests).
5. **CLI** — `gokart dashboard` launches server + simulator together.

**Tests (minimum):** recorder writes correct metadata and sample counts;
CSV export matches SQLite contents; bus overflow drops data without blocking
the producer (timing-asserted); WebSocket endpoint streams schema-conformant
JSON; session query filters by vehicle/config hash.

**Acceptance:** `gokart dashboard` → browser shows the simulated kart driving
a scenario live with correct unit conversion; after the run, the session
appears in history with charts; injected fault shows the fault banner within
one UI update.

---

## Phase 5 — Analysis & virtual tuning (completes the MVP)

**Goal:** the spec's analysis set + tuning loop, closing the MVP.

Tasks:

1. **Metrics** — `analysis/metrics.py`: from any session (sim or real):
   accel times to 10/20/30/40/50 km/h, top speed, peak/avg power, energy
   used, Wh/km, regenerated energy, max/avg temperatures.
2. **Standard tests** — `analysis/tests.py`: acceleration test, top speed
   (analytic force-balance theoretical + simulated practical), hill climb
   (gradient + distance → pass/fail, time, energy), range under a named duty
   cycle per drive mode.
3. **Comparison** — `analysis/compare.py`: run same scenario across N config
   versions → metric diff table. Replay mode: real session's throttle/brake
   → simulator → overlaid traces + per-channel RMS/peak error.
4. **Calibration overlays** — named parameter adjustment sets (rolling
   resistance scale, mass correction, motor efficiency scale, battery
   resistance scale) stored/versioned like calibration sets and applied on
   top of a config for simulation; recorded in session metadata.
5. **Parameter sweep** — `analysis/sweep.py`: declarative sweep spec (JSON:
   parameters + ranges, objective metric, constraint metrics), combinatorial
   execution using accelerated sim, ranked results table. Example shipped:
   sprocket sweep maximising 0–30 km/h time subject to top speed ≥ 35 km/h
   and battery current ≤ limit.
6. **Reports** — `analysis/report.py`: self-contained HTML report (metrics
   tables, matplotlib plots inlined, config name/version/hash, scenario).
7. **CLI** — `gokart analyze session <id>`, `gokart analyze compare ...`,
   `gokart sweep run <spec.json>`, `gokart report <session-id>`.

**Tests:** metric extraction against a synthetic session with known values;
theoretical top speed matches analytic solution; sweep respects constraints
and ranking; report generation produces valid self-contained HTML.

**Acceptance (MVP complete):** starting from a fresh checkout, the documented
workflow — create/validate config → simulate → watch dashboard → session
stored → analysis + report → change sprocket in a new config version → sweep
shows the trade-off — works end-to-end with no hardware.

---

## Phase 6 — Portable C core + ESP32 firmware skeleton

**Goal:** shared logic running on the ESP32; firmware skeleton with all
safety scaffolding.

Tasks:

1. **Golden vectors** — `tools/generate_golden.py`: from the Python
   reference, emit `shared/golden/{limits,safety,control}.json` — thousands
   of cases: exhaustive state-transition coverage, limit boundaries, fault
   combinations, plus randomized cases with a fixed seed. Wire into CI order:
   pytest → regenerate → C tests.
2. **C core** — `firmware/core_c/`: C99 ports of `resolve_limits`,
   `detect_faults`, `safety_step`, `control_step` (single-precision, no
   heap, no OS). Host-compiled test runner (plain C or Unity) replays every
   golden vector; tolerance 1e-5 relative.
3. **ESP32 project** — `firmware/esp32/` (PlatformIO, ESP-IDF): task layout
   per `ARCHITECTURE.md` 12.2; compile-time hard limits header generated
   from the hardware component records (`tools/generate_hard_limits.py`);
   NVS/SD config + calibration loading with hash verification; task
   watchdog on `control_task`; reset-reason detection; contactor/precharge
   GPIO driver with feedback check; OTA-capable partition table (slot
   reserved, OTA itself out of scope); mock sensor mode (build flag) so the
   firmware runs on a bare devkit.
4. **Display + telemetry stubs** — `display_task` writing to serial console
   (real display driver later); `telemetry_task` streaming the shared
   channel schema as JSON lines over serial, ingestible by the Phase 4
   recorder (`gokart telemetry ingest --serial <port>`).

**Acceptance:** C golden runner passes all vectors; firmware builds; on a
bare devkit in mock-sensor mode it boots OFF→BOOT→SELF_TEST→READY, streams
telemetry that the PC recorder stores as a normal session, and a forced
watchdog trip lands in FAULT after reboot.

---

## Phase 7 — VESC + BMS drivers, CAN, calibration

**Goal:** talk to real hardware behind the driver abstraction.

Tasks:

1. **DBC** — `shared/can/gokart.dbc`: VESC status/command frames, BMS
   frames, internal kart frames (state, mode, display). Round-trip test via
   `cantools` on the PC side; firmware structs kept in sync by a test that
   decodes fixture frames both ways.
2. **Firmware drivers** — TWAI-based VESC driver (status 1–5 ingest, current
   command, limit setting), BMS driver, CAN-timeout detection feeding the
   fault registry.
3. **Python drivers** — `drivers/vesc/`, `drivers/bms/` implementing the
   Protocols from `ARCHITECTURE.md` 12.3 over `python-can`, so the PC can
   bench-test hardware directly; `drivers/mock/` already exists via sim.
4. **Calibration workflow** — guided CLI (`gokart calibrate throttle|brake|
   wheel|...`) capturing endpoints/scale via live telemetry, producing a
   versioned calibration set; firmware applies calibration in
   `sensor_task`; calibration hash reported in telemetry metadata.

**Acceptance:** bench rig (ESP32 + VESC + motor, wheels off ground): throttle
commands current through the driver, live values match VESC Tool readings
within tolerance; unplugging CAN mid-run → FAULT within the configured
timeout; a calibration set survives reboot and its hash appears in sessions.

---

## Phase 8 — Real telemetry + measured-vs-predicted + calibration loop

**Goal:** the engineering loop from spec Section 16 with real data.

Tasks:

1. Robust on-kart logging (SD ring buffer, session finalisation on power
   loss) + `gokart telemetry import` from SD.
2. Sim-vs-real replay (Phase 5 machinery) applied to real sessions;
   comparison report template with overlay plots and error metrics.
3. Guided calibration adjustment: suggest overlay values that minimise error
   for chosen channels (simple 1-D scans, not black-box optimisation);
   user accepts → new calibration overlay version.

**Acceptance:** for a real drive, the comparison report shows overlaid
measured/predicted speed, current, and SOC, and applying a suggested overlay
demonstrably reduces the reported error on a second replay.

---

## Phase 9 — HIL and model depth

**Goal:** progressive hardware-in-the-loop + richer dynamics, per spec.

Tasks:

1. SIL: simulator exposes its VESC/BMS models on a virtual CAN bus (DBC
   frames), PC-side firmware-free validation of the bus contract.
2. HIL level 1: real ESP32 + USB-CAN adapter against the simulator playing
   VESC/BMS; run the full fault-injection suite against real firmware.
3. Tyre model upgrade: slip-ratio-based longitudinal force, wheelspin and
   lock-up detection; extend the traction limiter accordingly (golden
   vectors regenerated).
4. Optional: PDF report export, accessory model refinement, additional
   analysis views — pick up remaining spec items as needed.

**Acceptance:** the Phase 3 fault-injection suite passes against real
firmware over CAN (HIL level 1), and the upgraded tyre model reproduces the
simple model's behaviour when slip is small (regression tests).

---

## Cross-cutting requirements checklist (verify at every phase)

- [ ] No V1/V2 numbers hard-coded anywhere — configuration only.
- [ ] Control/safety code paths never blocked by UI, telemetry, or storage.
- [ ] Every telemetry session carries config hash, calibration hash,
      firmware version, driver profile.
- [ ] Limit hierarchy cannot be violated by any code path (resolver is the
      only place limits combine).
- [ ] All safety/limits/control logic changes regenerate golden vectors
      (Phase ≥ 6).
- [ ] SI units internally; conversions only in `units.py` consumers at the
      presentation/hardware boundary.

## Decisions

(Appended by the implementing agent as ambiguities are resolved — keep each
entry to: date, question, decision, reason.)
