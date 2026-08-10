const state = {
  channels: [],
  lastSample: {},
  ws: null,
  vehicles: [],
  inputPollTimer: null,
  brakeHold: false,
  simRunning: false,
  historyPollTimer: null,
  historyRefreshInFlight: false,
  historyPollCount: 0,
  liveSessionId: null,
  pendingLiveSample: null,
  liveUiScheduled: false,
  channelRowsBuilt: false,
  channelStableValues: {},
};

const CHANNEL_DISPLAY = {
  time_s: { decimals: 2, deadband: 0.02 },
  speed_mps: { decimals: 2, deadband: 0.05 },
  acceleration_mps2: { decimals: 2, deadband: 0.05 },
  throttle: { decimals: 2, deadband: 0.02 },
  brake: { decimals: 2, deadband: 0.02 },
  steering: { decimals: 2, deadband: 0.02 },
  steering_angle_deg: { decimals: 1, deadband: 0.5 },
  heading_deg: { decimals: 1, deadband: 0.5 },
  position_m: { decimals: 2, deadband: 0.05 },
  position_x_m: { decimals: 2, deadband: 0.05 },
  position_y_m: { decimals: 2, deadband: 0.05 },
  motor_rpm: { decimals: 0, deadband: 10 },
  motor_torque_nm: { decimals: 1, deadband: 0.2 },
  motor_current_a: { decimals: 1, deadband: 0.2 },
  battery_current_a: { decimals: 1, deadband: 0.2 },
  pack_voltage_v: { decimals: 2, deadband: 0.1 },
  soc: { decimals: 1, deadband: 0.005 },
  power_w: { decimals: 0, deadband: 10 },
  traction_force_n: { decimals: 0, deadband: 5 },
  motor_temp_c: { decimals: 1, deadband: 0.3 },
  battery_temp_c: { decimals: 1, deadband: 0.3 },
  traction_limited: { decimals: 0, deadband: 0.5 },
  filtered_throttle: { decimals: 2, deadband: 0.02 },
  torque_permitted: { decimals: 0, deadband: 0.5 },
  derating_factor: { decimals: 2, deadband: 0.02 },
};

function channelDisplayRule(name) {
  if (CHANNEL_DISPLAY[name]) return CHANNEL_DISPLAY[name];
  return { decimals: 2, deadband: 0.05 };
}

function stabilizeChannelValue(name, value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return value;
  const rule = channelDisplayRule(name);
  const last = state.channelStableValues[name];
  if (last !== undefined && Math.abs(num - last) < rule.deadband) {
    return last;
  }
  state.channelStableValues[name] = num;
  return num;
}

const FAULT_HELP = {
  THROTTLE_BRAKE_SIMULTANEOUS: "Throttle and brake were pressed together — release one pedal.",
  THROTTLE_IMPLAUSIBLE: "Throttle changed too quickly — move the slider smoothly.",
  THROTTLE_OUT_OF_RANGE: "Throttle reading out of range — return the slider to zero.",
  BRAKE_SENSOR_FAULT: "Brake reading out of range — release the brake slider.",
  WHEEL_SPEED_FAULT: "Wheel speed sensor fault.",
  SENSOR_DISAGREEMENT: "Sensor readings disagree.",
  PRECHARGE_TIMEOUT: "Precharge did not complete in time — try arming again with brake held.",
  CONTACTOR_WELDED: "Contactor welded — critical fault; use New session.",
  PACK_OVERVOLTAGE:
    "Pack voltage too high — release brake, wait a moment, then click Clear fault to power-cycle and recover.",
  PACK_UNDERVOLTAGE: "Pack voltage too low — stop driving and click Clear fault after the pack recovers.",
  CELL_OVERVOLTAGE: "Cell voltage too high — release brake/regen, wait, then click Clear fault.",
  CELL_UNDERVOLTAGE: "Cell voltage too low — stop driving and click Clear fault after recovery.",
};

function describeFaults(faultCodes) {
  if (!faultCodes) return "A safety fault was detected.";
  return faultCodes
    .split(",")
    .filter(Boolean)
    .map((code) => FAULT_HELP[code.trim()] || code.trim())
    .join(" ");
}

const SAFETY_CLASSES = [
  "safety-off",
  "safety-boot",
  "safety-self_test",
  "safety-ready",
  "safety-armed",
  "safety-driving",
  "safety-fault",
  "safety-safe_shutdown",
];

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  return response.json();
}

function setFaultBanner(sample) {
  const banner = document.getElementById("fault-banner");
  const faults = sample.active_faults || "";
  const safetyState = sample.safety_state || "";
  if (faults || safetyState === "FAULT" || safetyState === "SAFE_SHUTDOWN") {
    const detail = faults ? describeFaults(faults) : "Safety fault active.";
    banner.textContent = safetyState === "SAFE_SHUTDOWN"
      ? `SAFE SHUTDOWN: ${detail}`
      : `FAULT: ${detail}`;
    banner.classList.remove("hidden");
  } else {
    banner.classList.add("hidden");
  }
}

function updateDrivePanel(sample, speedKmh) {
  document.getElementById("speed-value").textContent = Math.round(speedKmh || 0);
  const driveMode = sample.drive_mode || "—";
  const safetyState = sample.safety_state || "OFF";
  document.getElementById("drive-mode").textContent = driveMode;
  document.getElementById("safety-state").textContent = safetyState;
  const safetyCard = document.getElementById("safety-card");
  safetyCard.classList.remove(...SAFETY_CLASSES);
  safetyCard.classList.add(`safety-${String(safetyState).toLowerCase()}`);
  const powerKw = (Number(sample.power_w || 0) / 1000).toFixed(1);
  document.getElementById("power-kw").textContent = `${powerKw} kW`;
  const steerDeg = Number(sample.steering_angle_deg || 0);
  const headingDeg = Number(sample.heading_deg || 0);
  document.getElementById("steer-value").textContent = `${steerDeg.toFixed(0)}°`;
  document.getElementById("heading-value").textContent = `${headingDeg.toFixed(0)}°`;
  const soc = Number(sample.soc || 0);
  document.getElementById("soc-text").textContent = `${(soc * 100).toFixed(0)}%`;
  document.getElementById("soc-fill").style.width = `${soc * 100}%`;
  setFaultBanner(sample);
  updateFreeDriveGuide(safetyState);
}

function resetDriveUi() {
  document.getElementById("throttle").value = "0";
  document.getElementById("brake").value = "0";
  document.getElementById("steering").value = "0";
  setBrakeHold(false);
  state.lastSample = {};
  state.pendingLiveSample = null;
  document.getElementById("speed-value").textContent = "0";
  document.getElementById("drive-mode").textContent = "—";
  document.getElementById("safety-state").textContent = "OFF";
  document.getElementById("power-kw").textContent = "0.0 kW";
  document.getElementById("steer-value").textContent = "0°";
  document.getElementById("heading-value").textContent = "0°";
  document.getElementById("soc-text").textContent = "—";
  document.getElementById("soc-fill").style.width = "0%";
  const safetyCard = document.getElementById("safety-card");
  safetyCard.classList.remove(...SAFETY_CLASSES);
  safetyCard.classList.add("safety-off");
  document.getElementById("fault-banner").classList.add("hidden");
  document.getElementById("fault-recovery-panel")?.classList.add("hidden");
  state.channelStableValues = {};
}

async function resetSession() {
  stopManualInputPolling();
  await api("/api/sim/reset", { method: "POST" });
  state.simRunning = false;
  resetDriveUi();
  updateFreeDriveGuide("OFF");
}

function simMode() {
  return document.getElementById("sim-mode").value;
}

function interactiveInputsEnabled() {
  const mode = simMode();
  return mode === "free" || mode === "manual";
}

function ensureChannelsTable() {
  if (state.channelRowsBuilt) return;
  const tbody = document.querySelector("#channels-table tbody");
  tbody.innerHTML = "";
  for (const channel of state.channels) {
    const row = document.createElement("tr");
    row.dataset.channel = channel.name;
    row.innerHTML = `<td>${channel.name}</td><td class="channel-value"></td><td>${channel.unit}</td>`;
    tbody.appendChild(row);
  }
  state.channelRowsBuilt = true;
}

function formatChannelValue(value, channelType = "float", channelName = "") {
  if (value === null || value === undefined || value === "") return "";
  if (channelType === "string") return String(value);
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  const stable = stabilizeChannelValue(channelName, num);
  const { decimals } = channelDisplayRule(channelName);
  return Number(stable).toFixed(decimals);
}

function updateChannelsTable(sample) {
  ensureChannelsTable();
  const typeByName = Object.fromEntries(
    state.channels.map((channel) => [channel.name, channel.type || "float"]),
  );
  for (const row of document.querySelectorAll("#channels-table tbody tr")) {
    const name = row.dataset.channel;
    const cell = row.querySelector(".channel-value");
    if (!cell) continue;
    const text = formatChannelValue(sample[name], typeByName[name], name);
    if (cell.textContent !== text) {
      cell.textContent = text;
    }
  }
}

function flushLiveUi() {
  state.liveUiScheduled = false;
  const sample = state.pendingLiveSample;
  if (!sample) return;
  state.lastSample = sample;
  updateDrivePanel(sample, sample._speedKmh);
  updateChannelsTable(sample);
}

function scheduleLiveUi(sample, speedKmh) {
  sample._speedKmh = speedKmh;
  state.pendingLiveSample = sample;
  if (state.liveUiScheduled) return;
  state.liveUiScheduled = true;
  requestAnimationFrame(flushLiveUi);
}

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  state.ws = new WebSocket(`${protocol}://${location.host}/ws/live`);
  state.ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type !== "sample") return;
    if (message.channels?.length) {
      state.channels = message.channels;
      state.channelRowsBuilt = false;
    }
    scheduleLiveUi(message.data, message.speed_kmh);
  };
  state.ws.onclose = () => setTimeout(connectWebSocket, 1000);
}

async function loadConfig() {
  state.channels = await api("/api/channels");
  await refreshVehicleLists();
  await loadDriveSettingOptions();
  if (typeof window.refreshVehicleCatalog === "function") {
    await window.refreshVehicleCatalog();
  }
  const scenarios = await api("/api/config/scenarios");

  const scenarioSelect = document.getElementById("scenario-select");
  scenarioSelect.innerHTML = "";
  for (const scenario of scenarios) {
    const option = document.createElement("option");
    option.value = scenario;
    option.textContent = scenario;
    scenarioSelect.appendChild(option);
  }
  await updateEffectiveLimits();
}

async function loadDriveSettingOptions() {
  const modes = await api("/api/config/modes");
  const profiles = await api("/api/config/profiles");
  const modeSelect = document.getElementById("drive-mode-select");
  const profileSelect = document.getElementById("driver-profile-select");
  const previousMode = modeSelect.value;
  const previousProfile = profileSelect.value;
  modeSelect.innerHTML = "";
  profileSelect.innerHTML = "";
  for (const mode of modes) {
    const option = document.createElement("option");
    option.value = mode;
    option.textContent = mode;
    modeSelect.appendChild(option);
  }
  for (const profile of profiles) {
    const option = document.createElement("option");
    option.value = profile;
    option.textContent = profile;
    profileSelect.appendChild(option);
  }
  if (previousMode && [...modeSelect.options].some((o) => o.value === previousMode)) {
    modeSelect.value = previousMode;
  } else if ([...modeSelect.options].some((o) => o.value === "default")) {
    modeSelect.value = "default";
  }
  if (previousProfile && [...profileSelect.options].some((o) => o.value === previousProfile)) {
    profileSelect.value = previousProfile;
  } else if ([...profileSelect.options].some((o) => o.value === "owner")) {
    profileSelect.value = "owner";
  }
  if (typeof window.refreshDriveSettingsNames === "function") {
    window.refreshDriveSettingsNames();
  }
}

function selectedDriveSettings() {
  return {
    drive_mode: document.getElementById("drive-mode-select").value,
    driver_profile: document.getElementById("driver-profile-select").value,
  };
}

async function updateEffectiveLimits() {
  const el = document.getElementById("effective-limits");
  if (!el) return;
  const vehicle = selectedVehicle();
  const { drive_mode: mode, driver_profile: profile } = selectedDriveSettings();
  if (!vehicle.vehicle_name || !vehicle.vehicle_version || !mode || !profile) {
    el.textContent = "Effective max speed: —";
    return;
  }
  try {
    const params = new URLSearchParams({
      vehicle_name: vehicle.vehicle_name,
      vehicle_version: vehicle.vehicle_version,
      mode,
      profile,
    });
    const limits = await api(`/api/config/effective-limits?${params}`);
    const layerLabel = {
      hardware: "hardware",
      vehicle: "vehicle",
      mode: limits.layers.mode.name,
      profile: limits.layers.profile.name,
    }[limits.binding_layer] || limits.binding_layer;
    const binding = limits.binding_layer
      ? ` (limited by ${layerLabel})`
      : "";
    el.textContent = `Effective max speed: ${limits.max_speed_kmh.toFixed(1)} km/h${binding}`;
  } catch (_error) {
    el.textContent = "Effective max speed: —";
  }
}

async function refreshVehicleLists(selectName = null, selectVersion = null) {
  state.vehicles = await api("/api/config/vehicles");

  const vehicleSelect = document.getElementById("vehicle-select");
  const previous = vehicleSelect.value;
  vehicleSelect.innerHTML = "";
  for (const vehicle of state.vehicles) {
    const option = document.createElement("option");
    option.value = `${vehicle.name}|${vehicle.version}`;
    option.textContent = `${vehicle.name} ${vehicle.version}`;
    vehicleSelect.appendChild(option);
  }
  if (selectName && selectVersion) {
    vehicleSelect.value = `${selectName}|${selectVersion}`;
  } else if (previous) {
    vehicleSelect.value = previous;
  }

  const configSelect = document.getElementById("config-vehicle-select");
  if (configSelect) {
    const configPrevious = configSelect.value;
    configSelect.innerHTML = "";
    for (const vehicle of state.vehicles) {
      const option = document.createElement("option");
      option.value = `${vehicle.name}|${vehicle.version}`;
      option.textContent = `${vehicle.name} ${vehicle.version}`;
      configSelect.appendChild(option);
    }
    if (selectName && selectVersion) {
      configSelect.value = `${selectName}|${selectVersion}`;
    } else if (configPrevious) {
      configSelect.value = configPrevious;
    }
    if (typeof window.loadConfigEditor === "function" && !document.getElementById("tab-config").classList.contains("hidden")) {
      void window.loadConfigEditor();
    }
  }
}

window.refreshVehicleLists = refreshVehicleLists;

async function refreshSessions() {
  await refreshHistoryView(true);
}

async function refreshHistoryView(forceSessionList = false) {
  if (state.historyRefreshInFlight) return;
  state.historyRefreshInFlight = true;
  try {
    const select = document.getElementById("session-select");
    const previousSessionId = select.value;
    state.historyPollCount += 1;
    const refreshList = forceSessionList || state.historyPollCount % 30 === 0;

    let sessions = [];
    if (refreshList) {
      sessions = await api("/api/sessions");
      select.innerHTML = "";
      for (const session of sessions) {
        const option = document.createElement("option");
        option.value = session.session_id;
        option.textContent = `${session.started_at} — ${session.vehicle_name} (${session.sample_count} samples)`;
        select.appendChild(option);
      }
      if (previousSessionId && [...select.options].some((o) => o.value === previousSessionId)) {
        select.value = previousSessionId;
      } else if (sessions.length) {
        select.value = sessions[0].session_id;
      }
      if (!sessions.length) return;
    }

    if (state.simRunning) {
      try {
        const status = await api("/api/sim/status");
        state.liveSessionId = status.session_id || null;
        if (status.session_id && [...select.options].some((o) => o.value === status.session_id)) {
          select.value = status.session_id;
        }
      } catch (_error) {
        /* keep current selection */
      }
    } else {
      state.liveSessionId = null;
    }

    const sessionId = select.value;
    if (!sessionId) return;

    await drawSessionChart(sessionId);
  } finally {
    state.historyRefreshInFlight = false;
  }
}

function startHistoryPolling() {
  stopHistoryPolling();
  state.historyPollCount = 0;
  void refreshHistoryView(true);
  state.historyPollTimer = setInterval(() => {
    void refreshHistoryView(false);
  }, 100);
}

function stopHistoryPolling() {
  if (state.historyPollTimer !== null) {
    clearInterval(state.historyPollTimer);
    state.historyPollTimer = null;
  }
}

function isHistoryTabActive() {
  return !document.getElementById("tab-history").classList.contains("hidden");
}

function plotSeries(ctx, samples, values, color, topPad, height, maxValue) {
  const width = ctx.canvas.width;
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = (index / Math.max(samples.length - 1, 1)) * width;
    const y = topPad + height - (value / maxValue) * height;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function speedToPathColor(speedKmh, maxSpeedKmh) {
  const t = Math.min(1, Math.max(0, speedKmh / Math.max(maxSpeedKmh, 0.1)));
  if (t < 0.5) {
    const u = t * 2;
    const g = Math.round(255 * u);
    const b = Math.round(255 * (1 - u));
    return `rgb(0,${g},${b})`;
  }
  const u = (t - 0.5) * 2;
  const r = Math.round(255 * u);
  const g = Math.round(255 * (1 - u));
  return `rgb(${r},${g},0)`;
}

function pathPlotTransform(xs, ys, canvas, margin = 20, markerPad = 7) {
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  const inset = margin + markerPad;
  const plotW = canvas.width - inset * 2;
  const plotH = canvas.height - inset * 2;
  const toPx = (x, y) => ({
    px: inset + ((x - minX) / spanX) * plotW,
    py: inset + plotH - ((y - minY) / spanY) * plotH,
  });
  return { toPx, minX, maxX, minY, maxY, inset, plotW, plotH };
}

function clampPathMarkerPx(px, py, canvas, radius = 5) {
  const pad = radius + 2;
  return {
    px: Math.max(pad, Math.min(canvas.width - pad, px)),
    py: Math.max(pad, Math.min(canvas.height - pad, py)),
  };
}

function drawSpeedColoredPath(pathCtx, xs, ys, speedsKmh, maxSpeedKmh, toPx) {
  pathCtx.lineWidth = 2.5;
  pathCtx.lineCap = "round";
  pathCtx.lineJoin = "round";
  for (let index = 1; index < xs.length; index += 1) {
    const speed = (speedsKmh[index] + speedsKmh[index - 1]) / 2;
    pathCtx.strokeStyle = speedToPathColor(speed, maxSpeedKmh);
    pathCtx.beginPath();
    const start = toPx(xs[index - 1], ys[index - 1]);
    const end = toPx(xs[index], ys[index]);
    pathCtx.moveTo(start.px, start.py);
    pathCtx.lineTo(end.px, end.py);
    pathCtx.stroke();
  }
}

function drawPathMarker(pathCtx, x, y, toPx, canvas) {
  let { px, py } = toPx(x, y);
  ({ px, py } = clampPathMarkerPx(px, py, canvas));
  pathCtx.beginPath();
  pathCtx.fillStyle = "#ff3b30";
  pathCtx.arc(px, py, 5, 0, Math.PI * 2);
  pathCtx.fill();
  pathCtx.strokeStyle = "#ffffff";
  pathCtx.lineWidth = 1.5;
  pathCtx.stroke();
}

async function drawSessionChart(sessionId) {
  const samples = await api(`/api/sessions/${sessionId}/samples?limit=5000`);
  const canvas = document.getElementById("history-chart");
  const pathCanvas = document.getElementById("history-path");
  const ctx = canvas.getContext("2d");
  const pathCtx = pathCanvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  pathCtx.clearRect(0, 0, pathCanvas.width, pathCanvas.height);
  if (!samples.length) return;

  const speeds = samples.map((s) => Number(s.speed_mps || 0) * 3.6);
  const steers = samples.map((s) => Number(s.steering_angle_deg || 0));
  const maxSpeed = Math.max(...speeds, 1);
  const maxSteer = Math.max(...steers.map((v) => Math.abs(v)), 1);
  const steerNorm = steers.map((v) => (v + maxSteer) / (2 * maxSteer));
  const panelHeight = (canvas.height - 50) / 2;

  plotSeries(ctx, samples, speeds, "#3dd6c6", 24, panelHeight, maxSpeed);
  plotSeries(ctx, samples, steerNorm, "#ffb020", 24 + panelHeight + 16, panelHeight, 1);

  ctx.fillStyle = "#8aa0b8";
  ctx.font = "12px sans-serif";
  ctx.fillText(`Speed (max ${maxSpeed.toFixed(1)} km/h)`, 10, 16);
  ctx.fillText(`Steering (±${maxSteer.toFixed(0)}°)`, 10, 24 + panelHeight + 12);

  const xs = samples.map((s) => Number(s.position_x_m || 0));
  const ys = samples.map((s) => Number(s.position_y_m || 0));

  const live = state.lastSample;
  const liveX = Number(live.position_x_m);
  const liveY = Number(live.position_y_m);
  const useLiveMarker = state.simRunning
    && state.liveSessionId === sessionId
    && Number.isFinite(liveX)
    && Number.isFinite(liveY);
  const markerX = useLiveMarker ? liveX : xs[xs.length - 1];
  const markerY = useLiveMarker ? liveY : ys[ys.length - 1];

  const boundsXs = useLiveMarker ? xs.concat(markerX) : xs;
  const boundsYs = useLiveMarker ? ys.concat(markerY) : ys;
  const { toPx } = pathPlotTransform(boundsXs, boundsYs, pathCanvas);

  drawSpeedColoredPath(pathCtx, xs, ys, speeds, maxSpeed, toPx);
  drawPathMarker(pathCtx, markerX, markerY, toPx, pathCanvas);

  pathCtx.fillStyle = "#8aa0b8";
  pathCtx.font = "12px sans-serif";
  pathCtx.fillText("Path trace — blue slow → green → red fast", 10, 16);
}

function selectedVehicle() {
  const [name, version] = document.getElementById("vehicle-select").value.split("|");
  return { vehicle_name: name, vehicle_version: version };
}

async function sendInputs() {
  if (!interactiveInputsEnabled()) return;
  const brake = state.brakeHold
    ? 1.0
    : Number(document.getElementById("brake").value) / 100;
  await api("/api/sim/inputs", {
    method: "POST",
    body: JSON.stringify({
      throttle: Number(document.getElementById("throttle").value) / 100,
      brake,
      steering: Number(document.getElementById("steering").value) / 100,
    }),
  });
}

function setBrakeHold(active) {
  state.brakeHold = active;
  const btn = document.getElementById("btn-brake-hold");
  if (btn) {
    btn.classList.toggle("active", active);
    btn.textContent = active ? "Brake hold: ON" : "Brake hold: OFF";
  }
  const slider = document.getElementById("brake");
  if (active) {
    slider.value = "100";
  } else if (slider.value === "100") {
    slider.value = "0";
  }
  void sendInputs();
}

function onBrakeSliderInput() {
  const slider = document.getElementById("brake");
  if (state.brakeHold && Number(slider.value) < 95) {
    state.brakeHold = false;
    const btn = document.getElementById("btn-brake-hold");
    if (btn) {
      btn.classList.remove("active");
      btn.textContent = "Brake hold: OFF";
    }
  }
  void sendInputs();
}

async function armWithBrake() {
  setBrakeHold(true);
  await sendInputs();
  await api("/api/sim/arm", { method: "POST" });
}

function updateFreeDriveGuide(safetyState) {
  if (simMode() !== "free") return;

  const hint = document.getElementById("free-drive-hint");
  const armBtn = document.getElementById("btn-arm-with-brake");
  const driving = document.getElementById("driving-controls");
  const steps = document.querySelectorAll(".free-step");

  const setStep = (active, doneBefore) => {
    steps.forEach((el) => {
      const step = el.dataset.step;
      el.classList.toggle("active", step === active);
      const order = ["session", "boot", "arm", "drive"];
      el.classList.toggle("done", order.indexOf(step) < order.indexOf(active));
    });
  };

  if (!state.simRunning) {
    hint.innerHTML = "Press <strong>Start session</strong> to power up the kart and begin.";
    armBtn.disabled = true;
    driving.classList.add("locked");
    document.getElementById("fault-recovery-panel")?.classList.add("hidden");
    setStep("session");
    return;
  }

  document.getElementById("fault-recovery-panel")?.classList.add("hidden");

  switch (safetyState) {
    case "OFF":
    case "BOOT":
    case "SELF_TEST":
      hint.textContent = "System is booting… wait for the safety state to show READY.";
      armBtn.disabled = true;
      driving.classList.add("locked");
      setStep("boot");
      break;
    case "READY":
      hint.innerHTML = "Safety is <strong>READY</strong>. Click <strong>Arm with brake</strong> — brake is applied automatically.";
      armBtn.disabled = false;
      driving.classList.add("locked");
      setStep("arm");
      break;
    case "ARMED":
      hint.innerHTML =
        "Precharge complete. <strong>Lower the brake slider to zero</strong> (or turn off brake hold), then <strong>add throttle</strong> to enter DRIVING.";
      armBtn.disabled = true;
      driving.classList.remove("locked");
      setStep("drive");
      break;
    case "DRIVING":
      hint.innerHTML = "You're driving. Use the pedals below — steering slider turns the front wheels.";
      armBtn.disabled = true;
      driving.classList.remove("locked");
      setStep("drive");
      steps.forEach((el) => el.classList.add("done"));
      break;
    case "FAULT":
    case "SAFE_SHUTDOWN": {
      const faults = state.lastSample.active_faults || "";
      const recovery = document.getElementById("fault-recovery-panel");
      const recoveryText = document.getElementById("fault-recovery-text");
      if (recovery && recoveryText) {
        recovery.classList.remove("hidden");
        recoveryText.textContent = describeFaults(faults);
      }
      const isCritical = String(faults).includes("PACK_") || String(faults).includes("CELL_")
        || String(faults).includes("BATTERY_OVERTEMP") || String(faults).includes("CONTACTOR")
        || String(faults).includes("PRECHARGE");
      hint.innerHTML = safetyState === "SAFE_SHUTDOWN"
        ? isCritical
          ? "<strong>Critical fault</strong> — release brake if you were regen-braking, wait for voltage to settle, then click <strong>Clear fault</strong>."
          : "<strong>System shut down</strong> — click <strong>Clear fault</strong> to recover, or use <strong>New session</strong>."
        : isCritical
          ? "Critical fault — fix the cause (see below), wait a moment, then click <strong>Clear fault</strong>."
          : "Fault active — click <strong>Clear fault</strong> to return to READY.";
      armBtn.disabled = true;
      driving.classList.add("locked");
      break;
    }
    default:
      hint.textContent = `Safety state: ${safetyState}`;
      armBtn.disabled = true;
      driving.classList.add("locked");
  }
}

function startManualInputPolling() {
  stopManualInputPolling();
  if (!interactiveInputsEnabled()) return;
  void sendInputs();
  state.inputPollTimer = setInterval(() => {
    void sendInputs();
  }, 100);
}

function updateSimModeUi() {
  const mode = simMode();
  const free = mode === "free";
  document.getElementById("scenario-label").classList.toggle("hidden", free);
  document.getElementById("free-drive-panel").classList.toggle("hidden", !free);
  document.getElementById("steering-label").classList.toggle("hidden", !free);
  document.getElementById("btn-brake-hold").classList.toggle("hidden", !free);
  document.getElementById("btn-arm-scenario").classList.toggle("hidden", free);
  document.getElementById("btn-ack-scenario").classList.toggle("hidden", free);

  const startBtn = document.getElementById("btn-start");
  const stopBtn = document.getElementById("btn-stop");
  startBtn.textContent = free ? "Start session" : "Start";
  stopBtn.textContent = free ? "End session" : "Stop";
  startBtn.classList.toggle("btn-primary", free);
  startBtn.classList.toggle("btn-primary-lg", free);

  updateFreeDriveGuide(state.lastSample.safety_state || "OFF");
}

function stopManualInputPolling() {
  if (state.inputPollTimer !== null) {
    clearInterval(state.inputPollTimer);
    state.inputPollTimer = null;
  }
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((el) => el.classList.remove("active"));
      button.classList.add("active");
      const tab = button.dataset.tab;
      document.getElementById("tab-live").classList.toggle("hidden", tab !== "live");
      document.getElementById("tab-history").classList.toggle("hidden", tab !== "history");
      document.getElementById("tab-config").classList.toggle("hidden", tab !== "config");
      if (tab === "history") startHistoryPolling();
      else stopHistoryPolling();
      if (tab === "config" && typeof window.loadConfigEditor === "function") {
        window.loadConfigEditor();
      }
    });
  });
}

function setupControls() {
  document.getElementById("sim-mode").addEventListener("change", updateSimModeUi);
  document.getElementById("vehicle-select").addEventListener("change", () => {
    void updateEffectiveLimits();
  });
  document.getElementById("drive-mode-select").addEventListener("change", () => {
    void updateEffectiveLimits();
  });
  document.getElementById("driver-profile-select").addEventListener("change", () => {
    void updateEffectiveLimits();
  });

  document.getElementById("btn-start").addEventListener("click", async () => {
    const vehicle = selectedVehicle();
    const mode = simMode();
    const driveSettings = selectedDriveSettings();
    await api("/api/sim/start", {
      method: "POST",
      body: JSON.stringify({
        ...vehicle,
        ...driveSettings,
        scenario: document.getElementById("scenario-select").value,
        manual: mode === "manual",
        free_mode: mode === "free",
        speedup: 5.0,
      }),
    });
    state.simRunning = true;
    if (interactiveInputsEnabled()) startManualInputPolling();
    updateFreeDriveGuide(state.lastSample.safety_state || "OFF");
  });

  document.getElementById("btn-stop").addEventListener("click", async () => {
    stopManualInputPolling();
    setBrakeHold(false);
    state.simRunning = false;
    await api("/api/sim/stop", { method: "POST" });
    updateFreeDriveGuide("OFF");
  });

  document.getElementById("btn-reset-session").addEventListener("click", () => {
    void resetSession();
  });

  document.getElementById("btn-arm-with-brake").addEventListener("click", () => {
    void armWithBrake();
  });
  document.getElementById("btn-disarm").addEventListener("click", () => api("/api/sim/disarm", { method: "POST" }));
  document.getElementById("btn-ack").addEventListener("click", async () => {
    document.getElementById("throttle").value = "0";
    document.getElementById("brake").value = "0";
    setBrakeHold(false);
    await sendInputs();
    await api("/api/sim/ack", { method: "POST" });
  });
  document.getElementById("btn-brake-hold").addEventListener("click", () => setBrakeHold(!state.brakeHold));
  document.getElementById("btn-arm-scenario").addEventListener("click", () => api("/api/sim/arm", { method: "POST" }));
  document.getElementById("btn-ack-scenario").addEventListener("click", async () => {
    document.getElementById("throttle").value = "0";
    document.getElementById("brake").value = "0";
    await sendInputs();
    await api("/api/sim/ack", { method: "POST" });
  });
  document.getElementById("btn-refresh-sessions").addEventListener("click", () => {
    void refreshHistoryView(true);
  });
  document.getElementById("session-select").addEventListener("change", (event) => {
    drawSessionChart(event.target.value);
  });

  for (const id of ["throttle", "steering"]) {
    document.getElementById(id).addEventListener("input", sendInputs);
  }
  document.getElementById("brake").addEventListener("input", onBrakeSliderInput);
  document.getElementById("steering").addEventListener("dblclick", () => {
    document.getElementById("steering").value = "0";
    void sendInputs();
  });
  updateSimModeUi();
}

async function init() {
  setupTabs();
  setupControls();
  try {
    const version = await api("/api/version");
    const el = document.getElementById("app-version");
    if (el) {
      el.textContent = `(${version.dashboard}, physics ${version.physics || "?"})`;
    }
  } catch (_error) {
    /* version badge is optional */
  }
  await loadConfig();
  connectWebSocket();
}

init();

window.loadDriveSettingOptions = loadDriveSettingOptions;
window.updateEffectiveLimits = updateEffectiveLimits;
