const configState = {
  detail: null,
  componentOptions: {},
  loading: false,
  vehicleCatalog: [],
};

function configVehicleKey() {
  return document.getElementById("config-vehicle-select").value;
}

function configVehicleParts() {
  const key = configVehicleKey();
  if (!key || !key.includes("|")) {
    return null;
  }
  const splitAt = key.indexOf("|");
  const name = key.slice(0, splitAt);
  const version = key.slice(splitAt + 1);
  if (!name || !version) return null;
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

function setConfigLoading(loading) {
  configState.loading = loading;
  document.getElementById("config-loading").classList.toggle("hidden", !loading);
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
  if (!detail) {
    container.innerHTML = '<p class="config-hint">No components loaded yet.</p>';
    return;
  }

  const slotEntries = Object.entries(detail.slots).filter(([, slot]) => slot && slot.component_type);
  if (!slotEntries.length) {
    container.innerHTML = '<p class="config-hint">This vehicle has no editable component slots.</p>';
    return;
  }

  for (const [slotId, slot] of slotEntries) {
    const row = document.createElement("div");
    row.className = "config-slot-row";

    const label = document.createElement("div");
    label.className = "config-slot-label";
    label.textContent = slot.label;

    const current = document.createElement("div");
    current.className = "config-slot-current";
    const summary = slot.summary || {};
    const summaryText = `${summary.manufacturer || ""} ${summary.model || ""}`.trim();
    current.textContent = summaryText
      ? `${summaryText} (${slot.component_id})`
      : slot.component_id;

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

async function refreshVehicleCatalog() {
  configState.vehicleCatalog = await api("/api/config/vehicles");
  return configState.vehicleCatalog;
}

window.refreshVehicleCatalog = refreshVehicleCatalog;

async function loadConfigEditor() {
  const parts = configVehicleParts();
  if (!parts) {
    setConfigStatus("Select a vehicle above to load its fitted components.", true);
    return;
  }

  setConfigLoading(true);
  try {
    const { name, version } = parts;
    let detail = configState.vehicleCatalog.find(
      (vehicle) => vehicle.name === name && vehicle.version === version,
    )?.detail;

    if (!detail) {
      await refreshVehicleCatalog();
      detail = configState.vehicleCatalog.find(
        (vehicle) => vehicle.name === name && vehicle.version === version,
      )?.detail;
    }

    if (!detail) {
      detail = await api("/api/config/vehicle-detail", {
        method: "POST",
        body: JSON.stringify({
          vehicle_name: name,
          vehicle_version: version,
        }),
      });
    }

    configState.detail = detail;
    document.getElementById("config-new-version").placeholder =
      configState.detail.suggested_next_version;
    document.getElementById("cfg-motor-sprocket").value =
      configState.detail.drivetrain.motor_sprocket_teeth;
    document.getElementById("cfg-axle-sprocket").value =
      configState.detail.drivetrain.axle_sprocket_teeth;
    document.getElementById("cfg-mass").textContent = configState.detail.mass_kg.toFixed(1);
    await renderConfigSlots();
    document.getElementById("config-status").classList.add("hidden");
  } catch (error) {
    let message = error.message;
    try {
      const parsed = JSON.parse(message);
      message = parsed.detail || message;
    } catch (_ignored) {
      /* use raw message */
    }
    setConfigStatus(`Could not load vehicle: ${message}`, true);
    document.getElementById("config-slots-list").innerHTML =
      '<p class="config-hint">Failed to load components. Click Reload or refresh the page.</p>';
    document.getElementById("cfg-mass").textContent = "—";
  } finally {
    setConfigLoading(false);
  }
}

async function saveConfigEditor() {
  const parts = configVehicleParts();
  if (!parts || !configState.detail) {
    setConfigStatus("Load a vehicle configuration before saving.", true);
    return;
  }

  const { name, version } = parts;
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
    setConfigStatus(`Saved ${result.name} ${result.version}. Use it in the Simulation dropdown.`, false);
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
  document.getElementById("btn-config-reload").addEventListener("click", () => {
    void loadConfigEditor();
  });
  document.getElementById("config-vehicle-select").addEventListener("change", () => {
    void loadConfigEditor();
  });
}

window.loadConfigEditor = loadConfigEditor;
setupConfigEditor();
