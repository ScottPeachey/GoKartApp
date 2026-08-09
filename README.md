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
- The MVP is Phases 0–5 (pure software: configure → validate → simulate →
  dashboard → log → analyse). Firmware and hardware integration are
  Phases 6–9.

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
- [ ] Phases 6–9 — firmware, drivers, real telemetry, HIL
