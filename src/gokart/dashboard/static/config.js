const configState = {
  detail: null,
  componentOptions: {},
  componentTypes: [],
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

function clearComponentOptionsCache(componentType = null) {
  if (componentType) {
    delete configState.componentOptions[componentType];
    return;
  }
  configState.componentOptions = {};
}

function setComponentEditorStatus(message, isError = false) {
  const el = document.getElementById("component-editor-status");
  if (!el) return;
  el.textContent = message;
  el.classList.remove("hidden", "error", "success");
  el.classList.add(isError ? "error" : "success");
}

async function loadComponentTypeSelect() {
  const select = document.getElementById("component-type-select");
  if (!select) return;
  configState.componentTypes = await api("/api/config/component-types");
  select.innerHTML = "";
  for (const item of configState.componentTypes) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.label;
    select.appendChild(option);
  }
  await refreshComponentIdSelect();
}

async function refreshComponentIdSelect() {
  const typeSelect = document.getElementById("component-type-select");
  const idSelect = document.getElementById("component-id-select");
  if (!typeSelect || !idSelect) return;
  const componentType = typeSelect.value;
  const items = await ensureComponentOptions(componentType);
  const previous = idSelect.value;
  idSelect.innerHTML = "";
  for (const item of items) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = formatComponentOption(item);
    idSelect.appendChild(option);
  }
  if (previous && [...idSelect.options].some((o) => o.value === previous)) {
    idSelect.value = previous;
  }
}

async function loadSelectedComponentIntoEditor() {
  const typeSelect = document.getElementById("component-type-select");
  const idSelect = document.getElementById("component-id-select");
  const editor = document.getElementById("component-json-editor");
  if (!typeSelect || !idSelect || !editor) return;
  const detail = await api(`/api/config/components/${typeSelect.value}/${idSelect.value}`);
  editor.value = JSON.stringify(detail, null, 2);
  setComponentEditorStatus(`Loaded ${detail.id}`, false);
}

async function createComponentTemplate() {
  const typeSelect = document.getElementById("component-type-select");
  const editor = document.getElementById("component-json-editor");
  if (!typeSelect || !editor) return;
  const template = await api(`/api/config/components/${typeSelect.value}/template`);
  editor.value = JSON.stringify(template, null, 2);
  setComponentEditorStatus(`New ${typeSelect.value} template — edit the id and fields, then Save.`, false);
}

async function saveComponentEditor() {
  const editor = document.getElementById("component-json-editor");
  const allowOverwrite = document.getElementById("component-allow-overwrite")?.checked ?? true;
  if (!editor) return;
  let data;
  try {
    data = JSON.parse(editor.value);
  } catch (error) {
    setComponentEditorStatus(`Invalid JSON: ${error.message}`, true);
    return;
  }

  try {
    const result = await api("/api/config/components/save", {
      method: "POST",
      body: JSON.stringify({ data, allow_overwrite: allowOverwrite }),
    });
    clearComponentOptionsCache(data.component_type);
    setComponentEditorStatus(`Saved ${result.component_type}/${result.id}`, false);
    await refreshComponentIdSelect();
    const idSelect = document.getElementById("component-id-select");
    if (idSelect) idSelect.value = result.id;
    if (configState.detail) {
      await renderConfigSlots();
    }
  } catch (error) {
    let message = error.message;
    try {
      const parsed = JSON.parse(message);
      if (parsed.detail?.violations) {
        message = parsed.detail.violations.join("; ");
      } else if (typeof parsed.detail === "string") {
        message = parsed.detail;
      }
    } catch (_ignored) {
      /* use raw message */
    }
    setComponentEditorStatus(message, true);
  }
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

function setDriveSettingsStatus(message, isError = false) {
  const el = document.getElementById("drive-settings-status");
  if (!el) return;
  el.textContent = message;
  el.classList.remove("hidden", "error", "success");
  el.classList.add(isError ? "error" : "success");
}

async function refreshDriveSettingsNames() {
  const type = document.getElementById("drive-settings-type")?.value || "mode";
  const select = document.getElementById("drive-settings-name");
  if (!select) return;
  const previous = select.value;
  const names = await api(type === "profile" ? "/api/config/profiles" : "/api/config/modes");
  select.innerHTML = "";
  for (const name of names) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  }
  if (previous && [...select.options].some((o) => o.value === previous)) {
    select.value = previous;
  }
}

async function loadDriveSettingsEditor() {
  const type = document.getElementById("drive-settings-type").value;
  const name = document.getElementById("drive-settings-name").value;
  if (!name) return;
  const path = type === "profile" ? `/api/config/profiles/${name}` : `/api/config/modes/${name}`;
  const data = await api(path);
  document.getElementById("drive-settings-editor").value = JSON.stringify(data, null, 2);
  setDriveSettingsStatus(`Loaded ${type} "${name}".`);
}

async function saveDriveSettingsEditor() {
  const type = document.getElementById("drive-settings-type").value;
  const editor = document.getElementById("drive-settings-editor");
  const allowOverwrite = document.getElementById("drive-settings-allow-overwrite").checked;
  let data;
  try {
    data = JSON.parse(editor.value);
  } catch (_error) {
    setDriveSettingsStatus("Invalid JSON in editor.", true);
    return;
  }
  const path = type === "profile" ? "/api/config/profiles/save" : "/api/config/modes/save";
  try {
    const result = await api(path, {
      method: "POST",
      body: JSON.stringify({ data, allow_overwrite: allowOverwrite }),
    });
    setDriveSettingsStatus(`Saved ${type} "${result.name}".`);
    if (typeof window.loadDriveSettingOptions === "function") {
      await window.loadDriveSettingOptions();
    }
    if (typeof window.updateEffectiveLimits === "function") {
      await window.updateEffectiveLimits();
    }
  } catch (error) {
    setDriveSettingsStatus(error.message, true);
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

  document.getElementById("btn-component-load")?.addEventListener("click", () => {
    void loadSelectedComponentIntoEditor();
  });
  document.getElementById("btn-component-new")?.addEventListener("click", () => {
    void createComponentTemplate();
  });
  document.getElementById("btn-component-save")?.addEventListener("click", () => {
    void saveComponentEditor();
  });
  document.getElementById("component-type-select")?.addEventListener("change", () => {
    void refreshComponentIdSelect();
  });
  document.getElementById("drive-settings-type")?.addEventListener("change", () => {
    void refreshDriveSettingsNames();
  });
  document.getElementById("btn-drive-settings-load")?.addEventListener("click", () => {
    void loadDriveSettingsEditor();
  });
  document.getElementById("btn-drive-settings-save")?.addEventListener("click", () => {
    void saveDriveSettingsEditor();
  });
  void loadComponentTypeSelect();
  void refreshDriveSettingsNames();
}

window.loadConfigEditor = loadConfigEditor;
window.refreshDriveSettingsNames = refreshDriveSettingsNames;
setupConfigEditor();
