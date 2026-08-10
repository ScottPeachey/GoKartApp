const state = {
  channels: [],
  lastSample: {},
  ws: null,
  vehicles: [],
  inputPollTimer: null,
};

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
  document.getElementById("drive-mode").textContent = sample.drive_mode || "—";
  document.getElementById("safety-state").textContent = sample.safety_state || "OFF";
  const powerKw = (Number(sample.power_w || 0) / 1000).toFixed(1);
  document.getElementById("power-kw").textContent = `${powerKw} kW`;
  const soc = Number(sample.soc || 0);
  document.getElementById("soc-text").textContent = `${(soc * 100).toFixed(0)}%`;
  document.getElementById("soc-fill").style.width = `${soc * 100}%`;
  setFaultBanner(sample);
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
  }
}

window.refreshVehicleLists = refreshVehicleLists;

async function refreshSessions() {
  const sessions = await api("/api/sessions");
  const select = document.getElementById("session-select");
  select.innerHTML = "";
  for (const session of sessions) {
    const option = document.createElement("option");
    option.value = session.session_id;
    option.textContent = `${session.started_at} — ${session.vehicle_name} (${session.sample_count} samples)`;
    select.appendChild(option);
  }
  if (sessions.length) {
    await drawSessionChart(sessions[0].session_id);
  }
}

async function drawSessionChart(sessionId) {
  const samples = await api(`/api/sessions/${sessionId}/samples?limit=5000`);
  const canvas = document.getElementById("history-chart");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!samples.length) return;

  const speeds = samples.map((s) => Number(s.speed_mps || 0) * 3.6);
  const max = Math.max(...speeds, 1);
  const width = canvas.width;
  const height = canvas.height;

  ctx.strokeStyle = "#3dd6c6";
  ctx.lineWidth = 2;
  ctx.beginPath();
  speeds.forEach((speed, index) => {
    const x = (index / Math.max(samples.length - 1, 1)) * width;
    const y = height - (speed / max) * (height - 20) - 10;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  ctx.fillStyle = "#8aa0b8";
  ctx.font = "12px sans-serif";
  ctx.fillText(`Top speed: ${max.toFixed(1)} km/h`, 10, 18);
}

function selectedVehicle() {
  const [name, version] = document.getElementById("vehicle-select").value.split("|");
  return { vehicle_name: name, vehicle_version: version };
}

async function sendInputs() {
  if (!document.getElementById("manual-mode").checked) return;
  await api("/api/sim/inputs", {
    method: "POST",
    body: JSON.stringify({
      throttle: Number(document.getElementById("throttle").value) / 100,
      brake: Number(document.getElementById("brake").value) / 100,
    }),
  });
}

function startManualInputPolling() {
  stopManualInputPolling();
  if (!document.getElementById("manual-mode").checked) return;
  void sendInputs();
  state.inputPollTimer = setInterval(() => {
    void sendInputs();
  }, 100);
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
      if (tab === "history") refreshSessions();
      if (tab === "config" && typeof window.loadConfigEditor === "function") {
        window.loadConfigEditor();
      }
    });
  });
}

function setupControls() {
  document.getElementById("btn-start").addEventListener("click", async () => {
    const vehicle = selectedVehicle();
    const manual = document.getElementById("manual-mode").checked;
    await api("/api/sim/start", {
      method: "POST",
      body: JSON.stringify({
        ...vehicle,
        scenario: document.getElementById("scenario-select").value,
        manual,
        speedup: 5.0,
      }),
    });
    if (manual) startManualInputPolling();
  });

  document.getElementById("btn-stop").addEventListener("click", async () => {
    stopManualInputPolling();
    await api("/api/sim/stop", { method: "POST" });
  });
  document.getElementById("btn-arm").addEventListener("click", () => api("/api/sim/arm", { method: "POST" }));
  document.getElementById("btn-ack").addEventListener("click", () => api("/api/sim/ack", { method: "POST" }));
  document.getElementById("btn-refresh-sessions").addEventListener("click", refreshSessions);
  document.getElementById("session-select").addEventListener("change", (event) => {
    drawSessionChart(event.target.value);
  });

  for (const id of ["throttle", "brake"]) {
    document.getElementById(id).addEventListener("input", sendInputs);
  }
}

async function init() {
  setupTabs();
  setupControls();
  await loadConfig();
  connectWebSocket();
}

init();
