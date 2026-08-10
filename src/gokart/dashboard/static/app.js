const state = {
  channels: [],
  lastSample: {},
  ws: null,
  vehicles: [],
  inputPollTimer: null,
  brakeHold: false,
  simRunning: false,
  historyPollTimer: null,
};

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
  if (faults) {
    banner.textContent = `FAULT: ${faults}`;
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

function simMode() {
  return document.getElementById("sim-mode").value;
}

function interactiveInputsEnabled() {
  const mode = simMode();
  return mode === "free" || mode === "manual";
}

function updateChannelsTable(sample) {
  const tbody = document.querySelector("#channels-table tbody");
  tbody.innerHTML = "";
  for (const channel of state.channels) {
    const row = document.createElement("tr");
    const value = sample[channel.name] ?? "";
    row.innerHTML = `<td>${channel.name}</td><td>${value}</td><td>${channel.unit}</td>`;
    tbody.appendChild(row);
  }
}

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  state.ws = new WebSocket(`${protocol}://${location.host}/ws/live`);
  state.ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type !== "sample") return;
    state.lastSample = message.data;
    updateDrivePanel(message.data, message.speed_kmh);
    updateChannelsTable(message.data);
  };
  state.ws.onclose = () => setTimeout(connectWebSocket, 1000);
}

async function loadConfig() {
  state.channels = await api("/api/channels");
  await refreshVehicleLists();
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
  const select = document.getElementById("session-select");
  const previousSessionId = select.value;
  const tabVisible = !document.getElementById("tab-history").classList.contains("hidden");

  if (forceSessionList || tabVisible) {
    const sessions = await api("/api/sessions");
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

  const sessionId = select.value;
  if (sessionId) {
    await drawSessionChart(sessionId);
  }
}

function startHistoryPolling() {
  stopHistoryPolling();
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
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  const margin = 20;
  const plotW = pathCanvas.width - margin * 2;
  const plotH = pathCanvas.height - margin * 2;

  pathCtx.strokeStyle = "#3dd6c6";
  pathCtx.lineWidth = 2;
  pathCtx.beginPath();
  xs.forEach((x, index) => {
    const y = ys[index];
    const px = margin + ((x - minX) / spanX) * plotW;
    const py = margin + plotH - ((y - minY) / spanY) * plotH;
    if (index === 0) pathCtx.moveTo(px, py);
    else pathCtx.lineTo(px, py);
  });
  pathCtx.stroke();

  pathCtx.fillStyle = "#8aa0b8";
  pathCtx.font = "12px sans-serif";
  pathCtx.fillText("Path trace (plan view)", 10, 16);
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
  if (active) slider.value = "100";
  else if (slider.value === "100") slider.value = "0";
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
    setStep("session");
    return;
  }

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
      hint.innerHTML = "Precharge complete. <strong>Release the brake</strong> (toggle brake hold or lower the slider), then use throttle.";
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
      hint.innerHTML = "Fault active — click <strong>Ack fault</strong>, then repeat the arm sequence.";
      armBtn.disabled = true;
      driving.classList.add("locked");
      break;
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

  document.getElementById("btn-start").addEventListener("click", async () => {
    const vehicle = selectedVehicle();
    const mode = simMode();
    await api("/api/sim/start", {
      method: "POST",
      body: JSON.stringify({
        ...vehicle,
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

  document.getElementById("btn-arm-with-brake").addEventListener("click", () => {
    void armWithBrake();
  });
  document.getElementById("btn-disarm").addEventListener("click", () => api("/api/sim/disarm", { method: "POST" }));
  document.getElementById("btn-ack").addEventListener("click", () => api("/api/sim/ack", { method: "POST" }));
  document.getElementById("btn-brake-hold").addEventListener("click", () => setBrakeHold(!state.brakeHold));
  document.getElementById("btn-arm-scenario").addEventListener("click", () => api("/api/sim/arm", { method: "POST" }));
  document.getElementById("btn-ack-scenario").addEventListener("click", () => api("/api/sim/ack", { method: "POST" }));
  document.getElementById("btn-refresh-sessions").addEventListener("click", refreshSessions);
  document.getElementById("session-select").addEventListener("change", (event) => {
    drawSessionChart(event.target.value);
  });

  for (const id of ["throttle", "brake", "steering"]) {
    document.getElementById(id).addEventListener("input", sendInputs);
  }
  updateSimModeUi();
}

async function init() {
  setupTabs();
  setupControls();
  await loadConfig();
  connectWebSocket();
}

init();
