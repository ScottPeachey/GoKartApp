const configState = {
  detail: null,
  componentOptions: {},
};

function configVehicleKey() {
  return document.getElementById("config-vehicle-select").value;
}

function configVehicleParts() {
  const [name, version] = configVehicleKey().split("|");
  return { name, version };
}

function formatComponentOption(summary) {
  const bits = [summary.manufacturer, summary.model].filter(Boolean).join(" ");
  const extras = [];
  if (summary.peak_power_w) extras.push(`${(summary.peak_power_w / 1000).toFixed(1)} kW`);
  if (summary.capacity_ah) extras.push(`${summary.capacity_ah} Ah`);
  if (summary.nominal_voltage_v) extras.push(`${summary.nominal_voltage_v} V`);
  const extra = extras.length ? ` — ${extras.join(", ")}` : "";
  return `${summary.id}: ${bits}${extra}`;
}

function setConfigStatus(message, isError = false) {
  const el = document.getElementById("config-status");
  el.textContent = message;
  el.classList.remove("hidden", "error", "success");
  el.classList.add(isError ? "error" : "success");
}

async function ensureComponentOptions(componentType) {
  if (configState.componentOptions[componentType]) {
    return configState.componentOptions[componentType];
  }
  const items = await api(`/api/config/components/${componentType}`);
  configState.componentOptions[componentType] = items;
  return items;
}

async function renderConfigSlots() {
  const detail = configState.detail;
  const container = document.getElementById("config-slots-list");
  container.innerHTML = "";
  if (!detail) return;

  for (const [slotId, slot] of Object.entries(detail.slots)) {
    if (!slot || !slot.component_type) continue;
    const row = document.createElement("div");
    row.className = "config-slot-row";

    const label = document.createElement("div");
    label.className = "config-slot-label";
    label.textContent = slot.label;

    const current = document.createElement("div");
    current.className = "config-slot-current";
    const summary = slot.summary || {};
    current.textContent = `${summary.manufacturer || ""} ${summary.model || ""}`.trim() || slot.component_id;

    const select = document.createElement("select");
    select.dataset.slotId = slotId;
    select.className = "config-slot-select";
    const options = await ensureComponentOptions(slot.component_type);
    for (const option of options) {
      const el = document.createElement("option");
      el.value = option.id;
      el.textContent = formatComponentOption(option);
      if (option.id === slot.component_id) el.selected = true;
      select.appendChild(el);
    }

    row.append(label, current, select);
    container.appendChild(row);
  }
}

async function loadConfigEditor() {
  const { name, version } = configVehicleParts();
  configState.detail = await api(
    `/api/config/vehicles/${encodeURIComponent(name)}/${encodeURIComponent(version)}/detail`,
  );
  document.getElementById("config-new-version").placeholder = configState.detail.suggested_next_version;
  document.getElementById("cfg-motor-sprocket").value = configState.detail.drivetrain.motor_sprocket_teeth;
  document.getElementById("cfg-axle-sprocket").value = configState.detail.drivetrain.axle_sprocket_teeth;
  document.getElementById("cfg-mass").textContent = configState.detail.mass_kg.toFixed(1);
  await renderConfigSlots();
}

async function saveConfigEditor() {
  const { name, version } = configVehicleParts();
  const slots = {};
  document.querySelectorAll(".config-slot-select").forEach((select) => {
    slots[select.dataset.slotId] = select.value;
  });
  const newVersion = document.getElementById("config-new-version").value.trim();
  const payload = {
    base_name: name,
    base_version: version,
    new_version: newVersion || null,
    slots,
    drivetrain: {
      motor_sprocket_teeth: Number(document.getElementById("cfg-motor-sprocket").value),
      axle_sprocket_teeth: Number(document.getElementById("cfg-axle-sprocket").value),
      chain_efficiency: configState.detail.drivetrain.chain_efficiency,
      axle_efficiency: configState.detail.drivetrain.axle_efficiency,
    },
  };

  try {
    const result = await api("/api/config/vehicles/save", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setConfigStatus(`Saved ${result.name} ${result.version}. Use it in the simulation dropdown.`, false);
    if (typeof window.refreshVehicleLists === "function") {
      await window.refreshVehicleLists(result.name, result.version);
    }
    document.getElementById("config-new-version").value = "";
    await loadConfigEditor();
  } catch (error) {
    let message = error.message;
    try {
      const parsed = JSON.parse(message);
      if (parsed.detail?.violations) {
        message = parsed.detail.violations.join("; ");
      } else if (parsed.detail?.message) {
        message = `${parsed.detail.message}: ${(parsed.detail.violations || []).join("; ")}`;
      }
    } catch (_ignored) {
      /* use raw message */
    }
    setConfigStatus(message, true);
  }
}

function setupConfigEditor() {
  document.getElementById("btn-config-save").addEventListener("click", saveConfigEditor);
  document.getElementById("config-vehicle-select").addEventListener("change", () => {
    loadConfigEditor();
  });
}

window.loadConfigEditor = loadConfigEditor;
setupConfigEditor();
