# Electric Go-Kart Software — Architecture

Version: 1.1
Date: 2026-08-09
Source requirements: `Electric Go-Kart Software — Requirements Specification.docx` (v1.1)
Companion document: `docs/IMPLEMENTATION_PLAN.md`
Revision notes (v1.1): clarified physical/steering-wheel display as a pluggable
driver; strengthened fault injection to require signal-level stimulation;
defined Chill/Track/Drift/Default/RAW drive modes; fixed physics algebraic
loop + wheel-slip model notes; firmware concurrency, display driver, and
limit-validation clarifications from design review.

This document defines **what to build and how the pieces fit together**. The
implementation plan defines **the order to build it in**. If the two ever
conflict, this document wins for design questions and the plan wins for
sequencing questions.

---

## 1. Design Mandate (non-negotiable)

From the requirements spec, Section 21:

> Do not build three independent applications. Build a shared,
> configuration-driven vehicle model and control architecture. Python
> simulation, ESP32 firmware, and the dashboard act as different interfaces to
> that underlying model wherever practical.

Concretely, this means:

1. **One configuration format.** A single, schema-validated vehicle
   configuration is the authoritative description of the kart. The simulator,
   firmware, and dashboard all consume it (or artifacts derived from it).
   Nothing hard-codes V1 or V2 numbers.
2. **One control/safety logic definition.** The limit hierarchy, drive-mode
   arbitration, throttle mapping, traction limiter, and safety state machine
   are defined once as **pure, deterministic functions** with explicit
   inputs/outputs. Python is the reference implementation; the ESP32 port is
   verified against shared **golden test vectors** (Section 12).
3. **One telemetry schema.** Simulated and real telemetry use the same channel
   names, units, and session metadata, so the analysis tools cannot tell them
   apart except by a `source` field.
4. **SI units everywhere internally.** m, m/s, m/s², N, N·m, W, Wh (energy
   storage/consumption), V, A, °C (temperature is the one deliberate
   non-Kelvin choice), kg, rad/s. Display conversion (km/h, etc.) happens only
   in presentation layers.

---

## 2. System Overview

```mermaid
graph TD
    DB["Component / Vehicle Database<br/>(JSON files + SQLite index,<br/>content-hash versioned)"]
    CORE["SHARED VEHICLE + CONTROL MODEL<br/>config schemas · physics · limit hierarchy ·<br/>drive modes · safety state machine"]
    SIM["Python Simulation Engine<br/>(fixed-timestep, fault injection,<br/>accelerated time)"]
    FW["ESP32 Firmware<br/>(portable C control core +<br/>ESP-IDF platform layer)"]
    DASH["Dashboard<br/>(FastAPI + browser UI)"]
    HW["Physical kart:<br/>VESC · BMS · sensors ·<br/>contactor · display"]
    TEL["Telemetry Store<br/>(SQLite + CSV export)"]
    AN["Analysis & Tuning Tools<br/>(metrics, sweeps, sim-vs-real)"]

    DB --> CORE
    CORE --> SIM
    CORE --> FW
    CORE --> DASH
    FW --> HW
    SIM --> TEL
    FW --> TEL
    TEL --> AN
    DASH -->|reads live| SIM
    DASH -->|reads live| FW
```

The **shared model** is a Python package (`gokart`) containing data schemas
and pure logic. The simulator, dashboard, and analysis tools import it
directly. The firmware cannot run Python, so the safety/limits/control subset
is ported to portable C99 (`firmware/core_c/`) and held equivalent by golden
test vectors generated from the Python reference implementation.

---

## 3. Technology Choices

| Area | Choice | Rationale |
|---|---|---|
| Shared model + simulation | Python 3.12+, `pydantic` v2, `numpy` (analysis only) | Fast to develop, excellent validation, unit-testable |
| Package / env management | `uv` with `pyproject.toml` | Fast, reproducible, single-file config |
| Config storage | JSON files on disk, content-hash (SHA-256) versioned | Human-readable, diffable, git-friendly; no DB migration pain for config data |
| Telemetry + audit storage | SQLite (stdlib `sqlite3`) + CSV export | Required by spec; zero external services; offline-capable |
| Dashboard | FastAPI + WebSocket + static HTML/JS (no build step) | Simple, works on any PC/tablet browser, no Node toolchain to maintain |
| Plotting / reports | `matplotlib` + HTML report generation | Meets "PDF or HTML" report requirement via HTML first |
| Firmware | PlatformIO project, ESP-IDF framework (FreeRTOS), C/C++ | Deterministic tasks, watchdog, TWAI (CAN) support built in |
| Portable control core | C99, no heap, no OS deps, single-precision float | Compiles for ESP32 and for host tests; ESP32 FPU is single-precision |
| CAN definitions | DBC file (`shared/can/gokart.dbc`) + `cantools`/`python-can` on PC side | One source of truth for message layout across sim, HIL, firmware |
| Tests | `pytest` (Python), Unity or plain C test runner (C core), golden vectors (cross-language) | Spec requires safety logic testable without hardware |

Everything runs offline. No cloud services, no internet dependency at runtime.

---

## 4. Repository Layout

```
GoKartApp/
├── README.md
├── docs/
│   ├── ARCHITECTURE.md            ← this file
│   └── IMPLEMENTATION_PLAN.md
├── pyproject.toml                 # Python project (package: gokart)
├── src/gokart/
│   ├── config/                    # schemas, validation, store, versioning, audit
│   │   ├── schemas/               # pydantic models: components, vehicle, modes, profiles, calibration
│   │   ├── store.py               # load/save/list configs, content hashing
│   │   ├── validation.py          # cross-component + limit-hierarchy validation
│   │   └── audit.py               # append-only change log
│   ├── limits/                    # effective-limit resolver (hardware ≥ vehicle ≥ mode ≥ driver)
│   ├── control/                   # throttle map, torque request, traction limiter, control step
│   ├── safety/                    # fault registry, state machine (pure functions)
│   ├── physics/                   # motor, battery, drivetrain, tyres, brakes, thermal, accessories, vehicle
│   ├── sim/                       # simulation engine, scenarios, fault injection, time control
│   ├── telemetry/                 # channel schema, ring buffer/bus, recorder, SQLite/CSV storage, sessions
│   ├── analysis/                  # metrics, acceleration/range/hill tests, parameter sweeps, sim-vs-real
│   ├── dashboard/                 # FastAPI app + static/ UI assets
│   └── drivers/                   # hardware abstraction: interfaces + vesc/, bms/, mock/
├── firmware/
│   ├── core_c/                    # portable C99 control core (shared logic port)
│   │   ├── include/gokart_core/
│   │   ├── src/
│   │   └── tests/                 # host-runnable C tests incl. golden vector runner
│   └── esp32/                     # PlatformIO ESP-IDF project (links core_c)
├── shared/
│   ├── schemas/                   # exported JSON Schema (generated from pydantic)
│   ├── can/gokart.dbc             # CAN message definitions
│   └── golden/                    # cross-language golden test vectors (JSON)
├── data/
│   ├── components/                # reusable component records (JSON)
│   ├── vehicles/                  # vehicle configurations (JSON)
│   ├── drive_modes/               # drive mode definitions (JSON)
│   └── driver_profiles/           # driver profiles (JSON)
├── telemetry/                     # runtime output: sessions.sqlite, CSV exports (gitignored)
└── tests/                         # pytest suite mirroring src/gokart/
```

---

## 5. Configuration System (the data backbone)

### 5.1 Entities

```mermaid
erDiagram
    COMPONENT ||--o{ VEHICLE_CONFIG : "referenced by"
    VEHICLE_CONFIG ||--o{ DRIVE_MODE : "constrains"
    VEHICLE_CONFIG ||--o{ DRIVER_PROFILE : "constrains"
    VEHICLE_CONFIG ||--o{ TELEMETRY_SESSION : "identified in"
    CALIBRATION_SET ||--o{ TELEMETRY_SESSION : "identified in"
    VEHICLE_CONFIG ||--o{ AUDIT_ENTRY : "changes logged"
```

- **Component record** (`data/components/<type>/<id>.json`): one physical part
  — motor, controller, battery pack, BMS, tyre, wheel, brake, DC-DC, sensor,
  contactor. Stores manufacturer, model, part number, specifications,
  datasheet path, source, price, date added, notes. Component records carry
  the **hardware absolute limits**.
- **Vehicle configuration** (`data/vehicles/<name>/<version>.json`): vehicle
  parameters (masses, geometry, aero, rolling resistance, speed/accel limits)
  plus references to component records **by id + content hash**, plus
  vehicle-level configurable limits.
- **Drive mode** and **driver profile**: named limit sets, both independently
  constrained by the vehicle (and thus by hardware). Any profile may be used
  with any mode; the runtime effective limit is `min(hardware, vehicle, mode,
  profile)` (Section 6). Mode definitions also carry **behaviour parameters**
  that are not simple min-limits: throttle response curve, throttle ramp rate,
  traction-limiter policy (Section 6.1). Profiles add authentication metadata
  (PIN/RFID/key — mechanism is an extension point, PIN first).
- **Calibration set**: sensor calibration values (throttle/brake ADC endpoints
  and deadbands, wheel-speed pulses per revolution, voltage/current/temperature
  scaling, steering centre). Stored **separately** from vehicle config,
  versioned the same way.

### 5.2 Schema and validation

Pydantic v2 models in `src/gokart/config/schemas/` are the **single source of
truth** for structure and units. JSON Schema is exported to `shared/schemas/`
for tooling and documentation. Every numeric field name encodes its SI unit
(`mass_kg`, `max_speed_mps`, `wheel_radius_m`, `peak_current_a`,
`max_temp_c`) so unit errors are visible at the field level.

Validation layers, all of which must pass before a config is accepted:

1. **Field validation** — types, ranges, required fields (pydantic).
2. **Intra-component sanity** — e.g. peak current ≥ continuous current,
   max voltage ≥ nominal voltage.
3. **Cross-component compatibility** — battery max voltage ≤ controller max
   voltage; motor max RPM vs gearing vs vehicle max speed consistency; BMS
   discharge limit vs controller battery-current setting.
4. **Limit hierarchy** (Section 6) — vehicle limits ≤ hardware absolute
   limits; mode limits ≤ vehicle limits; profile limits ≤ vehicle limits.
   Modes and profiles are **independent** limit sets (any profile may be
   used with any mode). Config-time validation does **not** require
   profile ≤ mode. At runtime the effective limit is the element-wise
   minimum of all active layers.

Rejected changes return a machine-readable list of violations, each with the
offending field, the constraint, and the limiting value — the spec requires
rejections to "clearly state the reason".

### 5.3 Versioning, hashing, audit

- A configuration file is **immutable once referenced by a telemetry
  session**. Changes create a new semantic version (`V1.1`, `V2.0`) in a new
  file.
- Every saved config gets a **SHA-256 content hash** computed over its
  canonical JSON form (sorted keys, normalized floats). The hash is the
  tamper-evident identity; the version string is the human name.
- `audit.py` maintains an append-only log (SQLite table): timestamp, actor,
  entity, from-hash, to-hash, field-level diff summary, validation result.

---

## 6. Limit Hierarchy Resolver

The strictly enforced hierarchy (spec Section 9), evaluated as an
element-wise **minimum** at runtime:

```
                  ┌─ drive-mode limits + behaviour
hardware absolute ─┴─ vehicle configuration limits ─┬─→ EffectiveLimits
                  └─ driver-profile limits ─────────┘
                         (× derating ≤ 1)
```

Modes and profiles are siblings under vehicle/hardware — not nested. A
Junior profile still caps Track or RAW top speed because `min()` includes
the profile layer.

`src/gokart/limits/resolver.py` provides one pure function used by both the
validator (at config time) and the control loop (at run time):

```python
@dataclass(frozen=True)
class EffectiveLimits:
    max_speed_mps: float
    max_motor_current_a: float
    max_battery_current_a: float
    max_regen_current_a: float
    max_power_w: float
    max_motor_rpm: float
    max_accel_mps2: float
    max_decel_mps2: float

def resolve_limits(
    hardware: HardwareLimits,      # min() across motor/controller/battery/BMS records
    vehicle: VehicleLimits,
    mode: DriveModeLimits,
    profile: DriverProfileLimits,
    derating: DeratingFactors,     # thermal/SOC derating, 0.0–1.0 per channel
) -> EffectiveLimits: ...
```

Rules:

- Each field of the result is the **minimum** across the four layers,
  multiplied by the applicable derating factor.
- `hardware` is itself the minimum of the motor, controller, battery, and BMS
  limits for each quantity — the spec requires "the minimum of motor,
  controller, battery, and BMS limits at every step".
- Derating (from thermal model or low SOC) can only reduce, never raise.
- This function is part of the **portable core** (Section 12): it is
  reimplemented in C and covered by golden vectors.

### 6.1 Seed drive modes (behaviour + limits)

Modes are data, not hard-coded behaviour trees. Seed definitions for Phase 1
(representative numbers; user replaces with real values):

| Mode | Top speed (mode layer) | Throttle response | Traction limiter |
|---|---|---|---|
| **Chill** | Lowered (e.g. ~20 km/h class) | Very smooth; slow initial ramp (`throttle_ramp_per_s` low, progressive curve) | On, aggressive (low slip threshold) — effectively no wheelspin |
| **Default** | Mid (between Chill and Track) | Moderate ramp and curve | On, moderate |
| **Track** | Unrestricted at mode layer (`null` → vehicle/profile/hardware bind) | Race-car response (faster ramp, near-linear curve) | On, tuned to minimise wheelspin without killing drive |
| **Drift** | Limited (mode sets a cap) | Drift-car response (fast ramp, allows snap) | **Off** — no software wheelspin limit |
| **RAW** | Unrestricted at mode layer | Instant (no software ramp; curve = identity) | **Off** |

**Always still enforced for every mode, including RAW:**

1. Hardware absolute limits (immutable).
2. Vehicle configuration limits.
3. Active driver-profile limits — so a Junior profile still caps top speed
   even in Track or RAW (`effective_speed = min(mode, profile, vehicle,
   hardware)`). RAW means “no *mode-imposed* soft limits / traction /
   throttle shaping”, not “bypass safety or profiles”.

Mode schema fields beyond numeric limits:

```python
class DriveModeBehaviour:
    throttle_curve: Literal["linear", "progressive", "aggressive"]
    throttle_ramp_per_s: float | None   # None = instant (RAW)
    traction_limiter: Literal["off", "gentle", "moderate", "aggressive"]
    regen_strength: float               # 0–1 scale on permitted regen
```

---

## 7. Control Pipeline

One deterministic step, executed at the control rate (100 Hz in sim and on
ESP32). Pure function, no I/O, no globals:

```python
def control_step(
    inputs: ControlInputs,      # throttle 0–1, brake 0–1, speed, motor rpm, currents, temps, voltages
    limits: EffectiveLimits,
    safety: SafetyOutputs,      # from safety state machine: drive enabled? torque scale?
    state: ControlState,        # traction limiter state, filtered signals
    params: ControlParams,      # throttle curve, regen config, traction thresholds
) -> tuple[ControlOutputs, ControlState]:
```

Pipeline inside the step:

1. **Input conditioning** — apply calibration, clamp, rate-limit throttle per
   mode's `throttle_ramp_per_s` / curve (`None` ramp = instant for RAW).
2. **Safety gate** — if the safety state machine says torque is not permitted,
   output zero torque request (and regen only if permitted).
3. **Throttle → torque request** — configurable curve (linear / progressive /
   aggressive), scaled to the mode's power/torque budget.
4. **Traction limiter** (mode-dependent; skipped when mode sets `off`, e.g.
   Drift/RAW) — compare estimated available traction (`µ · N`) against the
   tractive force implied by the torque request; if demand exceeds available
   traction, scale torque down and recover with hysteresis. Prefer
   force-based limiting over RPM-slip for the MVP rigid-coupling model
   (Section 9); when Phase 9 adds wheel inertia / slip, the limiter may also
   use measured slip ratio. (Spec calls this a "high-value early feature".)
5. **Limit clamp** — clamp resulting torque/current so motor current, battery
   current, power, RPM, and speed limits in `EffectiveLimits` are all
   respected (speed limit implemented as torque taper approaching max speed,
   not a hard cut).
6. **Regen arbitration** — map brake input to regen torque, clamped by regen
   current limit and battery charge-current limit; mechanical brake model
   handles the remainder (in sim).

`ControlOutputs` = torque/current command to send to the motor controller +
diagnostic values for telemetry. This entire pipeline is portable-core logic
(Python reference + C port + golden vectors).

---

## 8. Safety State Machine and Fault Handling

### 8.1 States

```
OFF → BOOT → SELF_TEST → READY → ARMED → DRIVING
                             ↘      ↘       ↘
                              FAULT ←────────┘
                                │
                          SAFE_SHUTDOWN → OFF
```

| State | Meaning | HV contactor | Torque allowed |
|---|---|---|---|
| OFF | System unpowered / logic idle | Open | No |
| BOOT | Firmware/sim initialising, config loading | Open | No |
| SELF_TEST | Power-on self-test: sensors in range, CAN alive, VESC/BMS responding, brake/throttle plausibility | Open | No |
| READY | Tests passed, waiting for arm request (driver authenticated, brake pressed) | Open | No |
| ARMED | Precharge sequence complete, contactor closed | Closed | No (zero torque) |
| DRIVING | Normal operation; entered from ARMED when the driver applies throttle above a deadband (or an explicit "go" input) while brake is released | Closed | Yes |
| FAULT | A fault requiring stop; torque zeroed; recoverable faults allow return to READY after clear | Depends on severity | No |
| SAFE_SHUTDOWN | Controlled ramp-down, contactor opened, state persisted | Opening → Open | No |

### 8.2 Fault model

A central fault registry (`src/gokart/safety/faults.py`) defines every fault
with: id, description, detection condition, severity, latching behaviour, and
required action. Severities:

- **WARNING** — log + display, no behaviour change.
- **DERATE** — reduce limits via `DeratingFactors` (e.g. motor temp high).
- **FAULT** — zero torque, transition to FAULT; recoverable after condition
  clears and driver acknowledges.
- **CRITICAL** — immediate SAFE_SHUTDOWN, contactor open, latched until
  power cycle.

Minimum fault set (from spec Section 10): throttle signal out of
range/implausible, brake sensor fault, throttle+brake simultaneous
(plausibility), wheel-speed sensor fault, sensor disagreement, CAN timeout,
VESC fault codes, BMS fault codes, pack over/under-voltage, cell
over/under-voltage, motor/controller/battery over-temperature, overspeed,
MCU watchdog reset detected, contactor feedback mismatch, precharge failure.

### 8.3 Contract

The state machine is a pure transition function — portable-core logic:

```python
def safety_step(
    state: SafetyState,
    inputs: SafetyInputs,        # sensor validity, fault flags, arm/disarm requests, speed
    config: SafetyConfig,        # thresholds, timeouts, self-test requirements
    timers: SafetyTimers,
) -> tuple[SafetyState, SafetyOutputs, SafetyTimers]:
```

`SafetyOutputs` carries: torque permitted (bool), regen permitted (bool),
contactor command (open/close/precharge), derating factors, active fault list,
display message code.

### 8.4 Hardware independence

Software shutdown is **not** the only protection (spec requirement). The
architecture assumes and documents hardware interlocks: physical e-stop in the
contactor coil path, BMS-controlled disconnect, and the ESP32 watchdog. The
firmware treats these as facts it must tolerate (e.g. contactor opened
externally → detect via feedback, enter FAULT), never as functions it owns
exclusively.

### 8.5 Fault injection (signal-level first)

Fault verification must exercise the **same detection path** the real kart
uses. Prefer corrupting the signals that detectors read; do not skip
detection by planting a finished `FaultId`.

Injection modes (in priority order for acceptance tests):

1. **Signal / value injection (required for every FAULT/CRITICAL):** override
   or synthesise physical quantities the detectors consume — ADC throttle/
   brake voltages, pack voltage, pack/motor/controller currents,
   temperatures, wheel-speed pulse rate, CAN silence (drop frames), contactor
   feedback GPIO, VESC/BMS reported fault bits / out-of-range fields. The
   simulation loop still runs `detect_faults(inputs) → safety_step(...)`.
   Example: battery over-temp is tested by ramping the battery temperature
   signal through the DERATE then FAULT thresholds, not by calling
   `raise_fault(BATTERY_OVERTEMP)`.
2. **Bus-level injection:** drop, delay, or corrupt CAN frames (timeouts,
   stale data, CRC-style garbage treated as invalid). Used for CAN-timeout
   and sensor-disagreement cases.
3. **Direct fault-flag injection (optional, unit tests only):** plant a
   `FaultId` to unit-test state-machine transitions in isolation. **Not**
   sufficient for Phase 3 acceptance of that fault.

Every FAULT/CRITICAL registry entry must have at least one Type-1 (or Type-2
where the fault is inherently bus-level) scenario that proves detection →
correct severity → correct state/outputs. This is mandatory per the spec.

---

## 9. Physics Engine

Fixed-timestep (default 10 ms), longitudinal point-mass model. Each component
model is a small class with `step(dt, inputs) -> outputs` and explicit state.
No component talks to another directly; `vehicle.py` composes them so the
data flow is auditable.

### 9.1 Core equations (MVP)

Drivetrain ratio (single constant used everywhere):

\[
i = \frac{N_{\mathrm{axle}}}{N_{\mathrm{motor}}} \qquad
\tau_{\mathrm{wheel}} = \tau_{\mathrm{motor}} \cdot i \cdot \eta_{\mathrm{chain}} \cdot \eta_{\mathrm{axle}}
\]

Kinematic link (MVP = **rigid coupling**, no independent wheel inertia):

\[
\omega_{\mathrm{wheel}} = \frac{v}{r} \qquad
\omega_{\mathrm{motor}} = \omega_{\mathrm{wheel}} \cdot i
\]

Forces:

\[
F_{\mathrm{trac,req}} = \frac{\tau_{\mathrm{wheel}}}{r} \qquad
F_{\mathrm{trac}} = \mathrm{clip}\bigl(F_{\mathrm{trac,req}},\, -\mu N,\, +\mu N\bigr)
\]

\[
F_{\mathrm{aero}} = \tfrac{1}{2}\, C_d\, A\, \rho\, v\, |v| \qquad
F_{\mathrm{roll}} = C_{rr}\, m\, g\, \cos\theta \qquad
F_{\mathrm{grad}} = m\, g\, \sin\theta
\]

\[
F_{\mathrm{net}} = F_{\mathrm{trac}} - F_{\mathrm{aero}} - F_{\mathrm{roll}} - F_{\mathrm{grad}} - F_{\mathrm{brake,mech}}
\]

\[
a = F_{\mathrm{net}} / m_{\mathrm{total}}
\]

Semi-implicit Euler:

\[
v_{n+1} = v_n + a\, \Delta t \qquad
x_{n+1} = x_n + v_{n+1}\, \Delta t
\]

Battery (equivalent circuit):

\[
V_{\mathrm{pack}} = V_{\mathrm{oc}}(\mathrm{SOC}) - I_{\mathrm{pack}}\, R_{\mathrm{int}}(\mathrm{SOC}, T)
\]

\[
\mathrm{SOC}_{n+1} = \mathrm{SOC}_n - \frac{I_{\mathrm{pack}}\, \Delta t}{Q_{\mathrm{nom}}}
\]

(sign convention: \(I_{\mathrm{pack}} > 0\) discharging.) Motor electrical power
and accessory LV loads set \(I_{\mathrm{pack}}\) given the previous-step pack
voltage (Section 9.3).

Thermal mass (per component):

\[
C_{\mathrm{th}}\, \dot{T} = P_{\mathrm{heat}} - \frac{T - T_{\mathrm{amb}}}{R_{\mathrm{th}}}
\]

### 9.2 Composition order

```
torque request (from control pipeline)
  → MotorModel: available torque at current RPM & voltage (map or nameplate
    fallback), electrical power draw, efficiency, heat
  → DrivetrainModel: gear ratio + chain/axle efficiency → wheel torque;
    kinematic path uses the same ratio constant as the force path
  → TyreModel: longitudinal grip limit F ≤ µ·N (not a 2-D friction circle
    until lateral dynamics exist)
  → Force balance → a → integrate v, x (semi-implicit Euler)
  → BatteryModel: OCV(SOC) + R_int(SOC,T); sag, current, SOC, heat, range
  → ThermalModel (motor, controller, battery)
  → AccessoryModel: LV loads via DC-DC → battery current; brown-out flag
```

### 9.3 Algebraic loop (motor ↔ battery)

Motor available torque and efficiency depend on pack voltage; pack voltage
depends on current; current depends on motor electrical power. Within one
timestep resolve this by **using the previous step's pack voltage** for the
motor calculation, then updating the battery with the resulting current.
Document this lag (one control period ≈ 10 ms) in code comments; do not
iterate to convergence in the MVP. Tests must still pass force-balance and
energy-sanity checks under this scheme.

### 9.4 Rigid coupling vs wheelspin (important)

MVP physics **cannot** have motor RPM diverge from \(v \cdot i / r\) because
there is no wheel rotational inertia state. Therefore:

- **Traction limiting in control** is force-based (`µ·N` vs requested
  tractive force), not RPM-slip-based.
- Tyre model **saturates** delivered force at `±µ·N` (physical wheelspin is
  approximated as "torque that did not become longitudinal force").
- Drift / RAW modes turn the **software** traction limiter off so the
  controller will request force beyond `µ·N`; physics still saturates at the
  tyre limit (kart accelerates at the grip limit, excess torque is "lost").
- **Phase 9** adds wheel rotational inertia and slip ratio so motor RPM and
  vehicle speed can genuinely diverge; only then does RPM-based slip control
  and visible wheelspin become meaningful.

### 9.5 Notes

- **Motor model preference order** (spec 5.1): CSV torque/efficiency map if
  provided, else nameplate continuous/peak + constant efficiency.
- **Limits are enforced by the control pipeline**, not the physics. Physics
  models what the hardware *would* do; control decides what is *requested*.
  Physical saturation (motor torque-speed envelope, tyre µ·N) lives in
  physics.
- Battery model is equivalent-circuit + thermal mass **only** — no
  electrochemical models in early releases.
- Brakes: mechanical and regen are separate paths; regen respects battery
  charge-current limit.
- **Motor speed units:** store and compute as rad/s internally; convert to
  RPM only at telemetry/display/VESC boundaries (same rule as km/h). Field
  names use `_rad_s` / `_rpm` accordingly. `EffectiveLimits.max_motor_rpm`
  is a presentation/config convenience mirrored as rad/s inside the
  resolver.

---

## 10. Simulation Engine

`src/gokart/sim/engine.py` runs the loop:

```
for each tick (dt = 10 ms):
    scenario → driver inputs (throttle, brake) + environment (gradient, surface, ambient temp)
    fault injector → override/corrupt sensor & plant signals (Section 8.5);
                     do not plant FaultIds in acceptance scenarios
    safety_step(...)            # shared logic (after detect_faults on signals)
    resolve_limits(...)         # shared logic (with current derating)
    control_step(...)           # shared logic
    vehicle.step(...)           # physics
    telemetry.emit(tick_record) # same schema as firmware telemetry
```

- **Scenarios** are data (JSON/YAML): sequences of driver input vs time or vs
  distance, plus environment. Standard scenarios ship in the repo: full
  throttle standing start, hill climb, duty-cycle range test, throttle/brake
  replay from a recorded session.
- **Time control**: real-time (paced to wall clock, feeds live dashboard) or
  accelerated (as fast as CPU allows, for range runs) — same code path, only
  the pacing differs.
- **Replay**: a recorded telemetry session's throttle/brake traces can be used
  as a scenario, enabling the measured-vs-predicted comparison loop.

---

## 11. Telemetry, Sessions, and Storage

- **Channel schema** (`src/gokart/telemetry/channels.py`): the canonical list
  of channels with name, SI unit, and type — timestamp, speed, motor RPM,
  throttle, brake, torque request/actual, motor/battery currents, pack
  voltage, SOC, temperatures (motor/controller/battery), drive mode, safety
  state, active faults, acceleration, regen power, GPS (nullable). Simulated
  and real sessions use identical channels plus `source: sim | kart`.
- **Session metadata**: session id (UUID), start/end time, vehicle config
  version **and content hash**, calibration set hash, firmware version,
  driver profile, drive mode(s) used, start/end SOC, notes.
- **Storage**: SQLite database (`telemetry/sessions.sqlite`) with `sessions`
  and `samples` tables; CSV export per session for simple inspection.
  Sampling rate configurable (default 50 Hz log rate from the 100 Hz loop).
- **Live path**: an in-process pub/sub bus; the dashboard subscribes via
  WebSocket bridge. On the kart, the ESP32 streams the same records over
  Wi-Fi/serial to whatever is recording. Telemetry is strictly best-effort:
  loss of the telemetry path must never affect the control/safety loop
  (non-functional requirement: recoverability).

---

## 12. Firmware Architecture (ESP32) and the Portable Core

### 12.1 Portable core strategy — how "one logic" is achieved

The safety state machine, limit resolver, control pipeline, and throttle/regen
mapping are written twice but **defined once**:

1. **Python reference implementation** in `src/gokart/{safety,limits,control}`
   — developed first, unit-tested exhaustively.
2. **Golden test vectors** in `shared/golden/*.json` — generated by a script
   from the Python implementation: thousands of (input state → expected
   output) cases including boundary and fault conditions.
3. **C99 port** in `firmware/core_c/` — no heap, no floating-point doubles,
   no OS calls; a host-compiled test runner must reproduce every golden
   vector within float tolerance: **max(1e-5 relative, 1e-6 absolute)** so
   near-zero values do not spuriously fail.

CI order is therefore: Python tests → regenerate vectors → C tests. A change
to control logic that isn't reflected in both implementations fails the
vector suite. This satisfies "the same logic can be unit-tested in Python and
faithfully implemented on the ESP32" without cross-compilation tricks.

### 12.2 Firmware task layout (ESP-IDF / FreeRTOS)

| Task | Rate / trigger | Priority | Responsibility |
|---|---|---|---|
| `control_task` | 100 Hz timer | Highest | Read latest sensor snapshot → `detect_faults` → `safety_step` → `resolve_limits` → `control_step` → publish motor command to the command slot. Feeds hardware watchdog. |
| `can_task` | On CAN RX + 50 Hz TX | High | VESC/BMS frames in/out via TWAI; updates sensor snapshot; transmits the latest command slot; detects timeouts. |
| `sensor_task` | 200 Hz | High | ADC throttle/brake, wheel-speed pulse counting, applies calibration; writes sensor snapshot. |
| `telemetry_task` | 50 Hz | Low | Serialise tick records; write to SD/flash ring buffer; stream if link available. |
| `display_task` | 10 Hz | Low | Push speed/mode/SOC/fault/power to the active `DisplayDriver` (console stub, SPI panel, or steering-wheel screen). |
| `config_task` | On demand | Low | Load vehicle config + calibration from NVS/SD at boot; accept updates only when stationary and in READY/OFF. |

**Concurrency rules (mandatory):**

- Sensor and CAN producers write into a **double-buffered snapshot**;
  `control_task` always reads a complete, consistent frame (no torn reads).
  Prefer atomics / FreeRTOS task notifications over long critical sections.
- Motor commands are written by `control_task` into a single **command slot**
  (`set_current` / limits); only `can_task` talks to TWAI. Control never
  blocks on the CAN peripheral.
- Telemetry and display are best-effort consumers of a copy of the last
  tick; they must never block control.

Rules baked into the firmware design:

- **Hard upper bounds** are a final backstop clamp. Prefer loading them from
  a signed/hashed hardware-limits record flashed with the config (so one
  firmware binary can serve V1 and V2), with a compile-time ceiling set to
  the maximum any supported kart may ever use. User configuration cannot
  raise either layer.
- Control/safety never blocks on telemetry, display, or Wi-Fi (determinism +
  recoverability requirements).
- Watchdog: hardware task watchdog on `control_task`; a missed deadline →
  reset → BOOT detects the reset reason → FAULT state.
- Contactor/precharge sequencing is owned by the safety outputs
  (`SafetyOutputs.contactor_command`), executed by a GPIO driver with
  feedback verification.
- Target MCU recommendation: **ESP32-S3** (better ADC for throttle/brake)
  unless an existing board forces classic ESP32; architecture stays the same.

### 12.3 Driver abstraction

`src/gokart/drivers/` (Python) and the firmware mirror the same interface
concept:

```python
class MotorControllerDriver(Protocol):
    def read_status(self) -> ControllerStatus: ...   # rpm, currents, voltage, duty, temps, faults
    def set_current(self, amps: float) -> None: ...
    def set_current_limits(self, motor_a: float, battery_a: float) -> None: ...

class BmsDriver(Protocol):
    def read_status(self) -> BmsStatus: ...          # pack V/A, SOC, cell voltages, temps, faults
```

Implementations: `vesc/` (VESC CAN protocol), `bms/` (target BMS protocol),
`mock/` (returns simulated values — used by the simulator and by HIL level 1).
Protocol details never leak past these modules. The DBC file defines all
frame layouts; PC-side code parses it with `cantools`, firmware uses
generated/handwritten structs kept in sync with the DBC (checked by a test
that round-trips example frames).

---

## 13. Dashboard and Driver Displays

Three consumers, one information contract (priority order while moving:
**large speed → drive mode → battery SOC → fault/warning → power**):

1. **Development/virtual dashboard** (MVP): FastAPI app serving a static
   HTML/JS page. WebSocket pushes live telemetry records. Additional tabs
   (stationary only): configuration browser, diagnostics/live channels, trip
   history. All unit conversion happens here.
2. **Physical driver display** (firmware `display_task`): any on-kart screen
   — dash-mounted panel, or a **steering-wheel-integrated display**. Driven
   by a `DisplayDriver` interface (SPI/I²C panel, UART to a wheel module,
   CAN display node, etc.). The kart must remain fully functional with only
   this path (offline-operation requirement); it never depends on the FastAPI
   app.
3. **Optional later clients** (phone browser, etc.): same telemetry bus.

### Steering-wheel screen — in this project or separate?

**Already covered in principle** by requirements Section 12 (dashboard
priorities) and Section 13 (firmware "display communication"), and by this
architecture's `display_task` + `DisplayDriver` abstraction.

**Recommendation:** keep it in this project's architecture, but **do not buy
or build the wheel hardware in the MVP**. What belongs here now:

- The display **information contract** (which fields, update rate, units,
  fault banner behaviour, "no complex menus while moving").
- A `DisplayDriver` interface + a console/stub implementation (Phase 6).

What can wait until you choose a product or DIY wheel:

- The specific panel/SoC, mounting, buttons on the wheel, and the concrete
  driver (SPI vs UART vs CAN). Swapping that in is a new `DisplayDriver`
  implementation — no change to control, safety, or physics.

Buying a ready-made wheel with a screen is fine later; treat it as a display
peripheral that speaks whatever protocol its manufacturer uses, wrapped by
one driver file.

The web dashboard reads from the telemetry bus, so it works identically
whether the producer is the simulator or the real kart streaming over Wi-Fi.

---

## 14. Analysis & Virtual Tuning

`src/gokart/analysis/` builds on stored sessions and on directly-driven
simulations:

- **Standard performance tests** (each a scenario + metric extractor):
  acceleration times to 10/20/30/40/50 km/h, theoretical vs practical top
  speed, hill climb (user gradient + distance), range under configurable duty
  cycles per drive mode.
- **Virtual tuning**: run the same scenario against two config versions and
  produce a side-by-side diff of metrics.
- **Parameter sweeps**: grid sweep over declared parameter ranges (e.g.
  sprocket teeth 10–16 × 48–60) with user-defined objective and constraints;
  results table sorted by objective. Simple combinatorial only — no fancy
  optimisers in early releases (per spec).
- **Sim vs real**: given a real session, replay its throttle/brake through
  the simulator with the same config version, overlay traces, compute error
  metrics per channel; expose model parameters (e.g. rolling resistance,
  effective mass, motor efficiency scale) for manual calibration adjustment,
  stored as a named calibration overlay on the config.
- **Reports**: HTML report per analysis (plots + config hash + metric tables).

---

## 15. Hardware-in-the-Loop Progression

Three levels, matching the spec:

1. **SIL**: PC simulator exposes a virtual CAN bus (SocketCAN on Linux /
   `python-can` virtual bus elsewhere) speaking the DBC-defined messages. Any
   CAN-speaking client sees a "real" kart.
2. **HIL level 1**: ESP32 running real firmware connected via a USB-CAN
   adapter to the PC simulator, which plays the roles of VESC and BMS. Fault
   injection now exercises real firmware.
3. **HIL level 2 / real**: real throttle → ESP32 → real VESC → real motor.
   Simulator drops out; telemetry pipeline unchanged.

Because sim, firmware, and drivers all speak the same DBC and telemetry
schema, each level is a wiring change, not a software change.

---

## 16. Extension Points (design for, don't build)

Explicitly reserved, per spec Section 18: GPS/geofencing (GPS channels
already nullable in telemetry schema), phone app (dashboard is already a web
client — a phone browser works), BLE/Wi-Fi provisioning, OTA updates
(firmware partition scheme should reserve an OTA slot from day one — cheap
now, painful later), lap timing, cloud sync (telemetry store is
export-friendly), multi-vehicle (config store is already keyed by vehicle
name), advanced cell-level battery health, concrete steering-wheel display
hardware behind `DisplayDriver`.

---

## 17. Key Decisions (ADR summary)

| # | Decision | Alternatives considered | Why |
|---|---|---|---|
| 1 | Python reference + C99 port + golden vectors for shared logic | Single C core wrapped for Python via cffi | Golden vectors are simpler to build/maintain, keep Python development friction-free, and still guarantee equivalence; cffi build adds toolchain pain for little gain at this scale |
| 2 | JSON files + content hash for configs; SQLite only for telemetry/audit | Everything in SQLite | Configs benefit from being diffable/git-trackable text; telemetry is high-volume tabular data where SQLite shines |
| 3 | FastAPI + vanilla JS dashboard, no frontend build step | React/Vite SPA | Minimises toolchain surface for the implementing model; the UI is gauges + charts, not a complex app |
| 4 | ESP-IDF (via PlatformIO) over Arduino framework | Arduino-ESP32 | Need FreeRTOS task control, TWAI driver, task watchdog, OTA partitioning — first-class in IDF |
| 5 | Semi-implicit Euler @ 100 Hz for physics | RK4, variable step | Adequate accuracy for longitudinal dynamics at this timestep; trivially portable; deterministic |
| 6 | Limits enforced in control layer, saturation in physics | Enforce in physics | Keeps "what hardware does" separate from "what software requests", which is exactly the sim/firmware split |
| 7 | °C for temperatures, otherwise strict SI (motor speed as rad/s internally) | Kelvin; RPM everywhere | Datasheets use °C; RPM only at VESC/display boundaries |
| 8 | MVP rigid drivetrain + force-based traction limit; wheel inertia in Phase 9 | Full slip model from day one | Spec prioritises closed loop early; true wheelspin needs inertia state the MVP deliberately omits |
| 9 | Signal-level fault injection for acceptance | Flag-only injection | Genuine test of `detect_faults`; matches how the kart fails in reality |
| 10 | Modes and profiles independent; runtime `min()` | Profile nested under mode | Any profile with any mode; Junior still caps Track/RAW speed |
