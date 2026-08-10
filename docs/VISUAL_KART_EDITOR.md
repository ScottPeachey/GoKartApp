# Visual kart editor — future work

This document describes how to add a **diagram-based** configuration UI (kart image,
clickable arrows, component callouts). That is separate from the **simple Configuration
tab** already in the dashboard, which handles component swaps and drivetrain edits
without JSON or hashes.

Use this guide when you are ready to invest time in layout artwork and interaction design.

---

## Prerequisites

- Simple Configuration tab working (`gokart dashboard` → **Configuration**).
- Familiarity with how vehicles reference components (`src/gokart/config/editor.py`,
  `VEHICLE_SLOTS`).

---

## Phase 1 — Read-only kart diagram

**Goal:** See what is fitted on a kart layout; no editing on the diagram yet.

### Step 1 — Create slot layout metadata

Add `src/gokart/dashboard/kart_layout.json` (or extend `VEHICLE_SLOTS` in Python):

```json
{
  "motor": { "svg_id": "slot-motor", "x": 320, "y": 180, "label": "Motor" },
  "battery": { "svg_id": "slot-battery", "x": 120, "y": 220, "label": "Battery" }
}
```

Map each slot to SVG element id and callout position.

### Step 2 — Kart SVG artwork

1. Create `src/gokart/dashboard/static/kart.svg` — top-down kart (your drawing).
2. Add a `<g>` per slot: `id="slot-motor"`, class `kart-slot`, `data-slot="motor"`.
3. Optional arrows: `<line>` from kart body to callout box.

**Manual work:** positioning hotspots to match your drawing (~30–60 min).

### Step 3 — Read-only API (mostly done)

Reuse existing endpoints:

- `GET /api/config/vehicles/{name}/{version}/detail`
- `GET /api/config/components/{type}`

Optional: `GET /api/config/layout` returning `kart_layout.json`.

### Step 4 — New “Kart layout” view

1. Add sub-view or replace Configuration left panel with inline SVG (`<object>` or fetch + inject).
2. On vehicle change, update callout labels from `detail.slots`.
3. Click slot → highlight + show specs in side panel (reuse detail card).

### Step 5 — Tests

- Layout JSON loads.
- Click handler sets `data-slot` correctly (light DOM test or manual QA).

**Done when:** you can click Motor on the picture and see motor specs without opening JSON.

---

## Phase 2 — Swap from the diagram

**Goal:** Click slot → pick replacement → save (reuse `POST /api/config/vehicles/save`).

1. On slot click, open dropdown/modal populated from `/api/config/components/{type}`.
2. “Apply” updates local draft only; **Save as new version** calls existing save API.
3. Disable diagram edits while simulation is running (same 409 rule as today).

No new backend required beyond Phase 1.

---

## Phase 3 — Edit component specs in UI

**Goal:** Tweak motor torque, battery capacity, etc., without hand-editing JSON.

1. Generate forms from Pydantic `model_json_schema()` per component type.
2. `POST /api/config/components/save` — always writes **new component id** (or suffix),
   never overwrites existing files.
3. Auto-pin new component into draft vehicle on save.

---

## Phase 4 — Diagram polish

- Hover states, fitted vs library component diff
- Drivetrain sliders on diagram (sprocket icons)
- Export “config card” PDF for build notes

---

## Suggested file layout (when you build it)

```
src/gokart/dashboard/
  static/
    kart.svg
    kart_editor.js      # diagram interactions
  kart_layout.json
  config.js             # existing simple editor
docs/
  VISUAL_KART_EDITOR.md # this file
```

---

## What you do manually vs what code does

| You | Code |
|-----|------|
| Draw kart SVG | Hotspot click handlers |
| Place slot coordinates | API + validation |
| Choose summary fields per type | Version/hash/file writes |

---

## Using the simple editor today

```bash
gokart dashboard
```

Open **Configuration** → pick vehicle → change dropdowns / sprockets → **Save as new version**.
The new version appears in the simulation dropdown automatically.
