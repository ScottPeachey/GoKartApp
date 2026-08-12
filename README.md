# Electric Go-Kart Software

A configuration-driven platform for a custom electric go-kart: virtual
simulation before the kart exists, a driver dashboard, and telemetry
logging/analysis — all built on **one shared vehicle model**, per the
requirements specification in this repo.

## Documents

Read in this order:

1. `Electric Go-Kart Software — Requirements Specification.docx` — what the
   system must do (v1.1, the authoritative requirements).
2. `docs/ARCHITECTURE.md` — how the system is designed: repository layout,
   technology choices, data model, limit hierarchy, control pipeline, safety
   state machine, physics engine, and telemetry.
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

## Autonomous track racing (in progress)

Import kart-scale circuits and run a rule-based autonomous driver from the
dashboard (**Auto drive** mode) or extend with RL/benchmarking per the autonomous
racing plan.

```bash
gokart track import /path/to/circuit.geojson
gokart track list
gokart dashboard   # Simulation → Auto drive, pick a track and lap count
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
- [x] Autonomous racing Phases 1–5 — tracks, lap timing, 4-wheel physics, tyre model
- [x] Autonomous racing Phase 6 — rule-based driver + Auto drive sessions
- [ ] Autonomous racing Phases 7–9 — per-config RL training to clean ceiling, ceiling validation/benchmarking, 3D viz
