# Electric Go-Kart Software

A configuration-driven platform for a custom electric go-kart: virtual
simulation before the kart exists, real-time control firmware (ESP32),
a driver dashboard, and telemetry logging/analysis — all built on **one
shared vehicle model**, per the requirements specification in this repo.

## Documents

Read in this order:

1. `Electric Go-Kart Software — Requirements Specification.docx` — what the
   system must do (v1.1, the authoritative requirements).
2. `docs/ARCHITECTURE.md` — how the system is designed: repository layout,
   technology choices, data model, limit hierarchy, control pipeline, safety
   state machine, physics engine, telemetry, firmware strategy, and the key
   decisions with rationale.
3. `docs/IMPLEMENTATION_PLAN.md` — the phased build order with concrete
   tasks, required tests, and acceptance criteria per phase.

## For the implementing agent

- Follow `docs/IMPLEMENTATION_PLAN.md` phase by phase, starting at Phase 0.
  Do not skip ahead; each phase's acceptance criteria gate the next.
- Design questions are answered by `docs/ARCHITECTURE.md`; sequencing
  questions by the plan. Genuine ambiguities: pick the simplest option
  consistent with the architecture, record it under `## Decisions` at the
  bottom of the plan, and continue.
## Pre-build testing (Phases 0–5)

You can configure and test the full software loop **before the kart exists**:

```bash
uv sync
gokart config validate data/vehicles/Scott_Kart_V1/V1.0.json
gokart sim run "Scott Kart V1" V1.0 standing_start_30s --out run.csv
gokart dashboard
gokart sweep run data/sweeps/sprocket_0_30.json
```

In the dashboard, open the **Configuration** tab to swap components or change
sprocket sizes. Saving creates a new vehicle version automatically (no JSON or
hashes).

## Firmware (Phase 6+)

Phase 6 adds the ESP32 firmware skeleton and a C port of the safety/limits/control
core, verified by golden test vectors:

```bash
gokart firmware golden
make -C firmware/core_c/tests test
# ESP32 (requires PlatformIO): cd firmware/esp32 && pio run -e esp32s3_mock
gokart telemetry ingest --file firmware_capture.jsonl
```


## Status

- [x] Requirements specification (v1.1)
- [x] Architecture (`docs/ARCHITECTURE.md`)
- [x] Implementation plan (`docs/IMPLEMENTATION_PLAN.md`)
- [x] Phase 0 — scaffolding
- [x] Phase 1 — data model, validation, seed configs
- [x] Phase 2 — physics engine and simulation loop
- [x] Phase 3 — safety state machine, fault injection, mode/profile switching
- [x] Phase 4 — telemetry storage and virtual dashboard
- [x] Phase 5 — analysis and virtual tuning
- [x] Phase 6 — portable C core and ESP32 firmware skeleton
- [ ] Phases 7–9 — drivers, real telemetry, HIL
