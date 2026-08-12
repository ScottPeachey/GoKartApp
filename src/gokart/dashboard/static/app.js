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
  faultAckPending: false,
  faultControlsActive: false,
  faultContext: null,
  effectiveLimits: null,
  hiddenChannels: new Set(),
  channelCustomiseOpen: false,
  historySessionListKey: "",
  historyViewSessionId: "",
  historySamplesFingerprint: "",
  historyMarkerFingerprint: "",
  historyChartLastDrawMs: 0,
  pathRedrawScheduled: false,
  historyPathTransform: null,
  historyPathBaseTransform: null,
  historyPathLayer: null,
  historyPathColorMaxKmh: null,
  pathView: {
    zoom: 1,
    panX: 0,
    panY: 0,
  },
  pathFollowKart: false,
  pathPan: {
    active: false,
    pointerId: null,
    startX: 0,
    startY: 0,
    startPanX: 0,
    startPanY: 0,
    moved: false,
  },
  historyLimitsCacheKey: "",
  historyLimitsCacheValue: null,
  track: {
    id: null,
    data: null,
    editStartFinish: false,
    suppressDirectionChange: false,
  },
  vehicleDimensionsCache: {},
  historyVehicleDims: { wheelbase_m: 1.04, track_m: 0.9 },
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
  elevation_m: { decimals: 1, deadband: 0.05 },
  pitch_deg: { decimals: 1, deadband: 0.2 },
  roll_deg: { decimals: 1, deadband: 0.2 },
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
  tyre_temp_front_c: { decimals: 1, deadband: 0.1 },
  tyre_temp_rear_c: { decimals: 1, deadband: 0.1 },
  tyre_wear_front: { decimals: 4, deadband: 0.00005 },
  tyre_wear_rear: { decimals: 4, deadband: 0.00005 },
  tyre_wear_fl: { decimals: 4, deadband: 0.00005 },
  tyre_wear_fr: { decimals: 4, deadband: 0.00005 },
  tyre_wear_rl: { decimals: 4, deadband: 0.00005 },
  tyre_wear_rr: { decimals: 4, deadband: 0.00005 },
  grip_fl_effective: { decimals: 2, deadband: 0.02 },
  grip_fr_effective: { decimals: 2, deadband: 0.02 },
  grip_rl_effective: { decimals: 2, deadband: 0.02 },
  grip_rr_effective: { decimals: 2, deadband: 0.02 },
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
  OVERSPEED: "Speed exceeded the drive-mode limit — ease off the throttle.",
  MOTOR_OVERTEMP: "Motor temperature too high — reduce throttle and let it cool.",
  MOTOR_OVERTEMP_DERATE: "Motor is hot — power is reduced until it cools.",
  CONTROLLER_OVERTEMP: "Controller temperature too high — reduce throttle.",
  BATTERY_OVERTEMP: "Battery temperature too high — stop and let the pack cool.",
  PRECHARGE_TIMEOUT: "Precharge did not complete in time — try arming again with brake held.",
  CONTACTOR_WELDED: "Contactor welded — critical fault; use New session.",
  PACK_OVERVOLTAGE:
    "Pack voltage too high — release brake, wait a moment, then click Clear fault to power-cycle and recover.",
  PACK_UNDERVOLTAGE: "Pack voltage too low — stop driving and click Clear fault after the pack recovers.",
  CELL_OVERVOLTAGE: "Cell voltage too high — release brake/regen, wait, then click Clear fault.",
  CELL_UNDERVOLTAGE: "Cell voltage too low — stop driving and click Clear fault after recovery.",
};

const OVERSPEED_FAULT_MARGIN_KMH = 1.8;

function describeFaultCode(code, sample = {}, context = null) {
  const trimmed = code.trim();
  if (trimmed === "OVERSPEED") {
    const peakKmh = context?.peakSpeedKmh ?? Number(sample.speed_mps || 0) * 3.6;
    const limitKmh = Number(state.effectiveLimits?.max_speed_kmh || 0);
    const faultKmh = limitKmh > 0 ? limitKmh + OVERSPEED_FAULT_MARGIN_KMH : 0;
    const speedPart = peakKmh > 0 ? `${peakKmh.toFixed(1)} km/h` : "speed too high";
    const limitPart = limitKmh > 0
      ? `limit ${limitKmh.toFixed(0)} km/h (fault above ${faultKmh.toFixed(1)} km/h)`
      : "the drive-mode speed limit";
    return `Speed ${speedPart} exceeded ${limitPart}. Ease off the throttle, slow down, then click Clear fault.`;
  }
  return FAULT_HELP[trimmed] || trimmed;
}

function describeFaults(faultCodes, sample = {}, context = null) {
  if (!faultCodes) return "A safety fault was detected.";
  return faultCodes
    .split(",")
    .filter(Boolean)
    .map((code) => describeFaultCode(code, sample, context))
    .join(" ");
}

function updateFaultContext(sample) {
  const faults = sample.active_faults || "";
  const safetyState = sample.safety_state || "";
  const speedKmh = Number(sample.speed_mps || 0) * 3.6;
  const faultActive = Boolean(faults) || isFaultSafetyState(safetyState);

  if (faultActive) {
    const codes = faults || state.faultContext?.codes || "";
    const peakSpeedKmh = Math.max(state.faultContext?.peakSpeedKmh || 0, speedKmh);
    state.faultContext = { codes, peakSpeedKmh };
    return;
  }

  if (safetyState === "READY" || safetyState === "OFF" || safetyState === "DRIVING") {
    state.faultContext = null;
  }
}

function faultDisplayCodes(sample) {
  const faults = sample.active_faults || "";
  if (faults) return faults;
  return state.faultContext?.codes || "";
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

function isFaultSafetyState(safetyState) {
  return safetyState === "FAULT" || safetyState === "SAFE_SHUTDOWN";
}

function setDrivingControlsFaultMode(active) {
  const driving = document.getElementById("driving-controls");
  if (!driving) return;
  driving.classList.toggle("fault-active", active);
  if (active) {
    document.getElementById("throttle").value = "0";
    updateSliderReadouts();
  }
}

function syncFaultDrivingControls(safetyState) {
  const active = isFaultSafetyState(safetyState);
  if (active && !state.faultControlsActive) {
    state.faultControlsActive = true;
    setDrivingControlsFaultMode(true);
    void sendInputs();
  } else if (!active && state.faultControlsActive) {
    state.faultControlsActive = false;
    setDrivingControlsFaultMode(false);
  }
}

function setFaultBanner(sample) {
  const banner = document.getElementById("fault-banner");
  updateFaultContext(sample);
  const faults = faultDisplayCodes(sample);
  const safetyState = sample.safety_state || "";
  if (faults || safetyState === "FAULT" || safetyState === "SAFE_SHUTDOWN") {
    const codes = faults
      .split(",")
      .map((code) => code.trim())
      .filter(Boolean);
    const detail = faults
      ? describeFaults(faults, sample, state.faultContext)
      : "Safety fault active — check active faults and click Clear fault when safe.";
    const prefix = safetyState === "SAFE_SHUTDOWN" ? "SAFE SHUTDOWN" : "FAULT";
    banner.replaceChildren();
    const title = document.createElement("div");
    title.className = "fault-banner-title";
    title.textContent = codes.length ? `${prefix}: ${codes.join(", ")}` : `${prefix}`;
    banner.appendChild(title);
    const body = document.createElement("div");
    body.className = "fault-banner-detail";
    body.textContent = detail;
    banner.appendChild(body);
    banner.classList.remove("hidden");
  } else {
    banner.classList.add("hidden");
    banner.replaceChildren();
  }
}

function formatLapTime(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value <= 0) return "—";
  const mins = Math.floor(value / 60);
  const secs = value - mins * 60;
  if (mins > 0) {
    return `${mins}:${secs.toFixed(1).padStart(4, "0")}`;
  }
  return `${secs.toFixed(1)}s`;
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
  const elevationM = Number(sample.elevation_m);
  const hasElevation = Number.isFinite(elevationM);
  document.getElementById("elevation-pill")?.classList.toggle("hidden", !hasElevation && !sample.track_s_m);
  document.getElementById("elevation-value").textContent = hasElevation
    ? `${elevationM.toFixed(1)} m`
    : "—";
  document.getElementById("pitch-value").textContent = `${Number(sample.pitch_deg || 0).toFixed(1)}°`;
  document.getElementById("roll-value").textContent = `${Number(sample.roll_deg || 0).toFixed(1)}°`;
  const soc = Number(sample.soc || 0);
  document.getElementById("soc-text").textContent = `${(soc * 100).toFixed(0)}%`;
  document.getElementById("soc-fill").style.width = `${soc * 100}%`;

  const lapNumber = Number(sample.lap_number || 0);
  const lapTime = Number(sample.lap_time_s || 0);
  const bestLap = Number(sample.best_lap_time_s || 0);
  const hasTrackLap = lapNumber > 0 || lapTime > 0 || bestLap > 0;
  document.getElementById("lap-pill").classList.toggle("hidden", !hasTrackLap);
  document.getElementById("lap-time-pill").classList.toggle("hidden", !hasTrackLap);
  document.getElementById("best-lap-pill").classList.toggle("hidden", !hasTrackLap || bestLap <= 0);
  if (hasTrackLap) {
    document.getElementById("lap-number").textContent = lapNumber > 0 ? String(Math.round(lapNumber)) : "—";
    document.getElementById("lap-time").textContent = formatLapTime(lapTime);
    document.getElementById("best-lap-time").textContent = formatLapTime(bestLap);
  }

  setFaultBanner(sample);
  syncFaultDrivingControls(safetyState);
  syncSlidersFromSample(sample);
  updateFreeDriveGuide(safetyState);
  updateAxlePhysicsPanel(sample);
}

const WHEEL_IDS = ["fl", "fr", "rl", "rr"];
const DISPLAY_GRIP_COEFF = 1.1;

function setGripMeterBar(barId, pct) {
  const bar = document.getElementById(barId);
  if (!bar) return;
  const clamped = Math.max(0, Math.min(100, pct));
  bar.style.width = `${clamped}%`;
  bar.classList.remove("grip-low", "grip-mid", "grip-high");
  if (clamped >= 90) {
    bar.classList.add("grip-high");
  } else if (clamped >= 65) {
    bar.classList.add("grip-mid");
  } else {
    bar.classList.add("grip-low");
  }
}

function effectiveLoadTransferAccel(sample) {
  const speed = Number(sample.speed_mps || 0);
  const accel = Number(sample.acceleration_mps2 || 0);
  if (speed <= 0.05 && accel < 0) {
    return 0;
  }
  return accel;
}

function formatTyreWear(wear) {
  const pct = Number(wear || 0) * 100;
  if (pct < 0.01) {
    return `${(pct * 10).toFixed(2)}‰`;
  }
  return `${pct.toFixed(2)}%`;
}

function updateWheelCard(wheelId, sample) {
  const normal = Number(sample[`normal_${wheelId}_n`] || 0);
  const gripCoeff = Number(sample[`grip_${wheelId}_effective`] || DISPLAY_GRIP_COEFF);
  const isRear = wheelId === "rl" || wheelId === "rr";
  const speed = Number(sample.speed_mps || 0);
  const driving = sample.safety_state === "DRIVING";
  const brake = Number(sample.brake || 0);
  const lateralForce = Math.abs(Number(sample[`lateral_${wheelId}_n`] || 0));
  const longitudinalForce = Math.abs(Number(sample[`longitudinal_${wheelId}_n`] || 0));
  const usedForce = isRear
    ? longitudinalForce
    : Math.hypot(lateralForce, longitudinalForce);
  const limit = normal * (gripCoeff > 0 ? gripCoeff : DISPLAY_GRIP_COEFF);
  const gripPct = limit > 0 ? (usedForce / limit) * 100 : 0;
  const temp = Number(sample[`tyre_temp_${wheelId}_c`] ?? 25);
  const wear = sample[`tyre_wear_${wheelId}`];

  document.getElementById(`wheel-${wheelId}-load`).textContent = normal > 1 ? `${Math.round(normal)} N` : "—";
  const showGrip = driving && (speed >= 0.05 || usedForce > 25);
  if (!showGrip) {
    setGripMeterBar(`wheel-${wheelId}-grip-bar`, 0);
    const parkedLabel = !driving
      ? (brake > 0.1 ? "Brake hold" : "Parked")
      : "Rolling";
    document.getElementById(`wheel-${wheelId}-grip-label`).textContent = parkedLabel;
  } else {
    setGripMeterBar(`wheel-${wheelId}-grip-bar`, gripPct);
    document.getElementById(`wheel-${wheelId}-grip-label`).textContent = isRear
      ? `Drive ${Math.min(999, gripPct).toFixed(0)}%`
      : `Lateral ${Math.min(999, gripPct).toFixed(0)}%`;
  }
  document.getElementById(`wheel-${wheelId}-tyre-meta`).textContent =
    `${temp.toFixed(1)}°C · wear ${formatTyreWear(wear)}`;
  return { normal, gripPct, isRear, usedForce, speed, driving };
}

function updateAxlePhysicsPanel(sample) {
  const panel = document.getElementById("axle-physics-panel");
  if (!panel) return;

  const wheelStats = WHEEL_IDS.map((wheelId) => updateWheelCard(wheelId, sample));
  const frontN = Number(sample.front_normal_n || wheelStats[0].normal + wheelStats[1].normal);
  const rearN = Number(sample.rear_normal_n || wheelStats[2].normal + wheelStats[3].normal);
  const total = frontN + rearN;
  const hasData = total > 1;
  panel.classList.toggle("inactive", !hasData);
  if (!hasData) {
    document.getElementById("load-transfer-hint").textContent = "Start driving to see load transfer";
    return;
  }

  const frontPct = (frontN / total) * 100;
  const rearPct = 100 - frontPct;
  document.getElementById("front-load-segment").style.width = `${frontPct}%`;
  document.getElementById("rear-load-segment").style.width = `${rearPct}%`;
  document.getElementById("front-load-pct").textContent = `F ${frontPct.toFixed(0)}%`;
  document.getElementById("rear-load-pct").textContent = `R ${rearPct.toFixed(0)}%`;

  const frontLat = Math.abs(Number(sample.front_lateral_n || 0));
  const rearTrac = Math.abs(Number(sample.rear_traction_n || sample.traction_force_n || 0));
  const speed = Number(sample.speed_mps || 0);
  const brake = Number(sample.brake || 0);
  const driving = sample.safety_state === "DRIVING";
  const loadAccel = effectiveLoadTransferAccel(sample);
  const hint = document.getElementById("load-transfer-hint");
  const outsideLoaded = sample.normal_fr_n > sample.normal_fl_n + 5;
  if (!driving) {
    hint.textContent = brake > 0.1
      ? "Brake hold — tyres stay cold until you drive"
      : "Tyres at ambient until driving";
  } else if (speed <= 0.05 && brake > 0.1) {
    hint.textContent = "Brakes held";
  } else if (loadAccel > 0.8) {
    hint.textContent = "Load → rear";
  } else if (loadAccel < -0.8) {
    hint.textContent = "Load → front";
  } else if (outsideLoaded) {
    hint.textContent = "Load → right (turning left)";
  } else if (sample.normal_fl_n > sample.normal_fr_n + 5) {
    hint.textContent = "Load → left (turning right)";
  } else if (frontLat > 200) {
    hint.textContent = "Front cornering";
  } else if (wheelStats[2].gripPct > 75 || wheelStats[3].gripPct > 75) {
    hint.textContent = "Rear grip limited";
  } else {
    hint.textContent = "Balanced";
  }
}

function resetAxlePhysicsPanel() {
  const panel = document.getElementById("axle-physics-panel");
  if (!panel) return;
  panel.classList.add("inactive");
  document.getElementById("front-load-segment").style.width = "50%";
  document.getElementById("rear-load-segment").style.width = "50%";
  document.getElementById("front-load-pct").textContent = "F 50%";
  document.getElementById("rear-load-pct").textContent = "R 50%";
  for (const wheelId of WHEEL_IDS) {
    document.getElementById(`wheel-${wheelId}-load`).textContent = "—";
    document.getElementById(`wheel-${wheelId}-grip-label`).textContent =
      wheelId === "rl" || wheelId === "rr" ? "Drive —" : "Lateral —";
    document.getElementById(`wheel-${wheelId}-tyre-meta`).textContent = "— °C · wear —";
    setGripMeterBar(`wheel-${wheelId}-grip-bar`, 0);
  }
  document.getElementById("load-transfer-hint").textContent = "—";
}

const STEER_MAX_DEG = 28;

function updateSliderReadouts() {
  const throttle = Number(document.getElementById("throttle")?.value || 0);
  const brake = Number(document.getElementById("brake")?.value || 0);
  const steering = Number(document.getElementById("steering")?.value || 0);
  const throttleReadout = document.getElementById("throttle-readout");
  const brakeReadout = document.getElementById("brake-readout");
  const steeringReadout = document.getElementById("steering-readout");
  if (throttleReadout) throttleReadout.textContent = `${Math.round(throttle)}%`;
  if (brakeReadout) brakeReadout.textContent = `${Math.round(brake)}%`;
  if (steeringReadout) {
    const steerDeg = (steering / 100) * STEER_MAX_DEG;
    const prefix = steerDeg > 0 ? "+" : "";
    steeringReadout.textContent = `${prefix}${steerDeg.toFixed(0)}°`;
  }
}

function resetLiveHistoryState() {
  state.historyViewSessionId = "";
  state.historySamplesFingerprint = "";
  state.historyMarkerFingerprint = "";
}

function resetLivePathLayer() {
  const pathColorMaxKmh = state.historyPathLayer?.pathColorMaxKmh ?? 45;
  state.historyPathLayer = {
    marker: { x: 0, y: 0, heading: 0, xs: [], ys: [], useLiveMarker: false },
    speeds: [],
    pathColorMaxKmh,
  };
}

async function waitForLiveSessionId(maxAttempts = 40) {
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const status = await api("/api/sim/status");
    if (status.session_id) {
      return status.session_id;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 50));
  }
  return null;
}

async function beginLiveSession() {
  const sessionId = await waitForLiveSessionId();
  if (!sessionId) return;

  state.liveSessionId = sessionId;
  resetLiveHistoryState();
  resetLivePathLayer();

  const trackId = document.getElementById("sim-track-select")?.value
    || document.getElementById("track-select")?.value;
  if (trackId) {
    if (!state.track.data || state.track.id !== trackId) {
      syncTrackSelectValue(trackId);
      await loadSelectedTrack(true, false);
    }
    ensureTrackMapVisible(false);
  }

  const sessions = await api("/api/sessions");
  const sessionSelect = document.getElementById("session-select");
  updateSessionSelect(sessions, sessionSelect, sessionId);
  sessionSelect.value = sessionId;
  resetLiveHistoryState();
  ensureTrackMapVisible(false);
  await drawSessionChart(sessionId);
  updateHistoryMarkerFromLive();
}

function resetDriveUi() {
  document.getElementById("throttle").value = "0";
  document.getElementById("brake").value = "0";
  document.getElementById("steering").value = "0";
  setBrakeHold(false);
  state.faultControlsActive = false;
  setDrivingControlsFaultMode(false);
  state.lastSample = {};
  state.pendingLiveSample = null;
  document.getElementById("speed-value").textContent = "0";
  document.getElementById("drive-mode").textContent = "—";
  document.getElementById("safety-state").textContent = "OFF";
  document.getElementById("power-kw").textContent = "0.0 kW";
  document.getElementById("steer-value").textContent = "0°";
  document.getElementById("heading-value").textContent = "0°";
  document.getElementById("elevation-value").textContent = "—";
  document.getElementById("pitch-value").textContent = "0°";
  document.getElementById("roll-value").textContent = "0°";
  document.getElementById("elevation-pill")?.classList.add("hidden");
  document.getElementById("soc-text").textContent = "—";
  document.getElementById("soc-fill").style.width = "0%";
  const safetyCard = document.getElementById("safety-card");
  safetyCard.classList.remove(...SAFETY_CLASSES);
  safetyCard.classList.add("safety-off");
  document.getElementById("fault-banner").classList.add("hidden");
  document.getElementById("fault-banner").replaceChildren();
  document.getElementById("fault-recovery-panel")?.classList.add("hidden");
  state.faultContext = null;
  state.channelStableValues = {};
  updateSliderReadouts();
  resetAxlePhysicsPanel();
}

async function resetSession() {
  stopManualInputPolling();
  await api("/api/sim/reset", { method: "POST" });
  state.simRunning = false;
  state.liveSessionId = null;
  resetDriveUi();
  updateFreeDriveGuide("OFF");
  resetLiveHistoryState();
  resetLivePathLayer();

  const trackId = document.getElementById("sim-track-select")?.value
    || document.getElementById("track-select")?.value;
  if (trackId) {
    syncTrackSelectValue(trackId);
    if (!state.track.data || state.track.id !== trackId) {
      await loadSelectedTrack(true, false);
    }
    ensureTrackMapVisible(true);
  } else {
    invalidateHistoryDrawCache();
  }
}

function simMode() {
  return document.getElementById("sim-mode").value;
}

function interactiveInputsEnabled() {
  const mode = simMode();
  return mode === "free" || mode === "manual";
}

function autoDriveActive() {
  return simMode() === "auto" && state.simRunning;
}

function syncSlidersFromSample(sample) {
  if (!autoDriveActive()) return;
  const throttleEl = document.getElementById("throttle");
  const brakeEl = document.getElementById("brake");
  const steeringEl = document.getElementById("steering");
  if (!throttleEl || !brakeEl || !steeringEl) return;

  const throttlePct = Math.round(Math.max(0, Math.min(100, Number(sample.throttle || 0) * 100)));
  const brakePct = Math.round(Math.max(0, Math.min(100, Number(sample.brake || 0) * 100)));
  const steeringPct = Math.round(
    Math.max(-100, Math.min(100, -Number(sample.steering || 0) * 100)),
  );

  if (Number(throttleEl.value) !== throttlePct) throttleEl.value = String(throttlePct);
  if (Number(brakeEl.value) !== brakePct) brakeEl.value = String(brakePct);
  if (Number(steeringEl.value) !== steeringPct) steeringEl.value = String(steeringPct);
  updateSliderReadouts();
}

const CHANNEL_UI = {
  time_s: { icon: "⏱", label: "Time" },
  position_m: { icon: "📍", label: "Distance" },
  speed_mps: { icon: "🏎", label: "Speed" },
  acceleration_mps2: { icon: "📈", label: "Acceleration" },
  throttle: { icon: "🦶", label: "Throttle" },
  brake: { icon: "🛑", label: "Brake" },
  steering: { icon: "🎮", label: "Steering" },
  steering_angle_deg: { icon: "↩", label: "Steer angle" },
  heading_deg: { icon: "🧭", label: "Heading" },
  elevation_m: { icon: "⛰", label: "Elevation" },
  pitch_deg: { icon: "↕", label: "Pitch" },
  roll_deg: { icon: "↔", label: "Roll" },
  position_x_m: { icon: "↔", label: "Position X" },
  position_y_m: { icon: "↕", label: "Position Y" },
  track_s_m: { icon: "🛣", label: "Track distance" },
  track_lateral_m: { icon: "↔", label: "Track offset" },
  lap_number: { icon: "🏁", label: "Lap" },
  lap_time_s: { icon: "⏱", label: "Lap time" },
  last_lap_time_s: { icon: "⏱", label: "Last lap" },
  best_lap_time_s: { icon: "🏆", label: "Best lap" },
  motor_rpm: { icon: "⚙", label: "Motor RPM" },
  motor_torque_nm: { icon: "🔧", label: "Torque" },
  motor_current_a: { icon: "⚡", label: "Motor current" },
  battery_current_a: { icon: "🔋", label: "Battery current" },
  pack_voltage_v: { icon: "🔌", label: "Pack voltage" },
  soc: { icon: "🔋", label: "State of charge" },
  power_w: { icon: "💡", label: "Power" },
  traction_force_n: { icon: "🛞", label: "Traction" },
  front_normal_n: { icon: "⬇", label: "Front load" },
  rear_normal_n: { icon: "⬇", label: "Rear load" },
  front_lateral_n: { icon: "↔", label: "Front lateral" },
  rear_traction_n: { icon: "🛞", label: "Rear traction" },
  normal_fl_n: { icon: "⬇", label: "FL load" },
  normal_fr_n: { icon: "⬇", label: "FR load" },
  normal_rl_n: { icon: "⬇", label: "RL load" },
  normal_rr_n: { icon: "⬇", label: "RR load" },
  lateral_fl_n: { icon: "↔", label: "FL lateral" },
  lateral_fr_n: { icon: "↔", label: "FR lateral" },
  longitudinal_fl_n: { icon: "🛞", label: "FL brake" },
  longitudinal_fr_n: { icon: "🛞", label: "FR brake" },
  longitudinal_rl_n: { icon: "🛞", label: "RL drive" },
  longitudinal_rr_n: { icon: "🛞", label: "RR drive" },
  tyre_temp_front_c: { icon: "🌡", label: "Front tyre temp" },
  tyre_temp_rear_c: { icon: "🌡", label: "Rear tyre temp" },
  tyre_temp_fl_c: { icon: "🌡", label: "FL temp" },
  tyre_temp_fr_c: { icon: "🌡", label: "FR temp" },
  tyre_temp_rl_c: { icon: "🌡", label: "RL temp" },
  tyre_temp_rr_c: { icon: "🌡", label: "RR temp" },
  tyre_wear_front: { icon: "🛞", label: "Front wear" },
  tyre_wear_rear: { icon: "🛞", label: "Rear wear" },
  tyre_wear_fl: { icon: "🛞", label: "FL wear" },
  tyre_wear_fr: { icon: "🛞", label: "FR wear" },
  tyre_wear_rl: { icon: "🛞", label: "RL wear" },
  tyre_wear_rr: { icon: "🛞", label: "RR wear" },
  grip_front_effective: { icon: "🛞", label: "Front grip" },
  grip_rear_effective: { icon: "🛞", label: "Rear grip" },
  grip_fl_effective: { icon: "🛞", label: "FL grip" },
  grip_fr_effective: { icon: "🛞", label: "FR grip" },
  grip_rl_effective: { icon: "🛞", label: "RL grip" },
  grip_rr_effective: { icon: "🛞", label: "RR grip" },
  motor_temp_c: { icon: "🌡", label: "Motor temp" },
  battery_temp_c: { icon: "🌡", label: "Battery temp" },
  traction_limited: { icon: "🛞", label: "Traction limited" },
  filtered_throttle: { icon: "🎚", label: "Filtered throttle" },
  drive_mode: { icon: "🏁", label: "Drive mode" },
  safety_state: { icon: "🛡", label: "Safety state" },
  contactor_command: { icon: "🔀", label: "Contactor" },
  torque_permitted: { icon: "✅", label: "Torque permitted" },
  active_faults: { icon: "⚠", label: "Active faults" },
  derating_factor: { icon: "📉", label: "Derating" },
};

function channelUiMeta(name) {
  return CHANNEL_UI[name] || { icon: "📊", label: name.replace(/_/g, " ") };
}

const CHANNEL_VISIBILITY_STORAGE_KEY = "gokart.hiddenChannels";

function loadHiddenChannels() {
  try {
    const raw = localStorage.getItem(CHANNEL_VISIBILITY_STORAGE_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return new Set(Array.isArray(parsed) ? parsed.filter((name) => typeof name === "string") : []);
  } catch (_error) {
    return new Set();
  }
}

function saveHiddenChannels() {
  localStorage.setItem(
    CHANNEL_VISIBILITY_STORAGE_KEY,
    JSON.stringify([...state.hiddenChannels].sort()),
  );
}

function syncHiddenChannelsWithSchema() {
  const known = new Set(state.channels.map((channel) => channel.name));
  let changed = false;
  for (const name of state.hiddenChannels) {
    if (!known.has(name)) {
      state.hiddenChannels.delete(name);
      changed = true;
    }
  }
  if (changed) {
    saveHiddenChannels();
  }
}

function isChannelVisible(name) {
  return !state.hiddenChannels.has(name);
}

function visibleChannels() {
  return state.channels.filter((channel) => isChannelVisible(channel.name));
}

function setChannelCustomiseOpen(open) {
  state.channelCustomiseOpen = open;
  document.getElementById("channel-customise-menu")?.classList.toggle("hidden", !open);
}

function renderChannelCustomiseMenu() {
  const list = document.getElementById("channel-customise-list");
  if (!list) return;
  list.innerHTML = "";
  const sorted = [...state.channels].sort((left, right) => {
    const leftLabel = channelUiMeta(left.name).label;
    const rightLabel = channelUiMeta(right.name).label;
    return leftLabel.localeCompare(rightLabel);
  });
  for (const channel of sorted) {
    const meta = channelUiMeta(channel.name);
    const item = document.createElement("label");
    item.className = "channel-customise-item";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = isChannelVisible(channel.name);
    checkbox.dataset.channel = channel.name;
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        state.hiddenChannels.delete(channel.name);
      } else {
        state.hiddenChannels.add(channel.name);
      }
      saveHiddenChannels();
      rebuildChannelsGrid();
      if (state.lastSample && Object.keys(state.lastSample).length) {
        updateChannelsGrid(state.lastSample);
      }
    });
    const text = document.createElement("span");
    text.textContent = meta.label;
    item.append(checkbox, text);
    list.appendChild(item);
  }
}

function setupChannelCustomise() {
  const button = document.getElementById("btn-channel-customise");
  const menu = document.getElementById("channel-customise-menu");
  if (!button || !menu) return;

  button.addEventListener("click", (event) => {
    event.stopPropagation();
    const open = !state.channelCustomiseOpen;
    setChannelCustomiseOpen(open);
    if (open) {
      renderChannelCustomiseMenu();
    }
  });

  document.getElementById("btn-channel-show-all")?.addEventListener("click", () => {
    state.hiddenChannels.clear();
    saveHiddenChannels();
    renderChannelCustomiseMenu();
    rebuildChannelsGrid();
    if (state.lastSample && Object.keys(state.lastSample).length) {
      updateChannelsGrid(state.lastSample);
    }
  });

  document.addEventListener("click", (event) => {
    if (!state.channelCustomiseOpen) return;
    if (menu.contains(event.target) || button.contains(event.target)) return;
    setChannelCustomiseOpen(false);
  });
}

function channelCardClass(name, value) {
  if (name === "active_faults" && value) return "channel-fault";
  if (name === "safety_state" && String(value).includes("FAULT")) return "channel-fault";
  if (name === "safety_state" && String(value) === "DRIVING") return "channel-active";
  if (name === "torque_permitted" && Number(value) > 0) return "channel-active";
  if (name === "traction_limited" && Number(value) > 0) return "channel-warn";
  return "";
}

function ensureChannelsGrid() {
  const grid = document.getElementById("channels-grid");
  if (!grid || !state.channels.length) return;
  const channels = visibleChannels();
  const existing = [...grid.children].map((card) => card.dataset.channel);
  const expected = channels.map((channel) => channel.name);
  if (state.channelRowsBuilt && existing.join("|") === expected.join("|")) return;

  grid.innerHTML = "";
  for (const channel of channels) {
    const meta = channelUiMeta(channel.name);
    const card = document.createElement("article");
    card.className = "channel-card";
    card.dataset.channel = channel.name;
    card.innerHTML = `
      <span class="channel-card-icon" aria-hidden="true">${meta.icon}</span>
      <span class="channel-card-label">${meta.label}</span>
      <span class="channel-card-value">—</span>
      <span class="channel-card-unit">${channel.unit}</span>
    `;
    grid.appendChild(card);
  }
  state.channelRowsBuilt = true;
}

function rebuildChannelsGrid() {
  state.channelRowsBuilt = false;
  ensureChannelsGrid();
  if (state.channelCustomiseOpen) {
    renderChannelCustomiseMenu();
  }
}

function formatChannelValue(value, channelType = "float", channelName = "") {
  if (value === null || value === undefined || value === "") return "—";
  if (channelType === "string") return String(value);
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  const stable = stabilizeChannelValue(channelName, num);
  const { decimals } = channelDisplayRule(channelName);
  return Number(stable).toFixed(decimals);
}

function updateChannelsGrid(sample) {
  ensureChannelsGrid();
  const typeByName = Object.fromEntries(
    state.channels.map((channel) => [channel.name, channel.type || "float"]),
  );
  for (const card of document.querySelectorAll("#channels-grid .channel-card")) {
    const name = card.dataset.channel;
    const cell = card.querySelector(".channel-card-value");
    if (!cell) continue;
    const raw = sample[name];
    const text = formatChannelValue(raw, typeByName[name], name);
    if (cell.textContent !== text) {
      cell.textContent = text;
    }
    const nextClass = `channel-card ${channelCardClass(name, raw)}`.trim();
    if (card.className !== nextClass) {
      card.className = nextClass;
    }
  }
}

function flushLiveUi() {
  state.liveUiScheduled = false;
  const sample = state.pendingLiveSample;
  if (!sample) return;
  state.lastSample = sample;
  updateDrivePanel(sample, sample._speedKmh);
  updateChannelsGrid(sample);
  updateHistoryMarkerFromLive();
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
    if (message.channels?.length) {
      state.channels = message.channels;
      syncHiddenChannelsWithSchema();
      rebuildChannelsGrid();
    }
    if (message.type !== "sample" || !message.data) return;
    scheduleLiveUi(message.data, message.speed_kmh);
  };
  state.ws.onclose = () => setTimeout(connectWebSocket, 1000);
}

async function loadConfig() {
  state.channels = await api("/api/channels");
  syncHiddenChannelsWithSchema();
  rebuildChannelsGrid();
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
    state.effectiveLimits = limits;
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

function sessionOptionLabel(session) {
  return `${session.started_at} — ${session.vehicle_name} (${session.sample_count} samples)`;
}

function updateSessionSelect(sessions, select, previousSessionId) {
  const listKey = sessions.map((s) => `${s.session_id}:${s.sample_count}`).join("|");
  if (listKey === state.historySessionListKey && select.options.length === sessions.length) {
    for (const session of sessions) {
      const option = select.querySelector(`option[value="${session.session_id}"]`);
      if (!option) continue;
      const label = sessionOptionLabel(session);
      if (option.textContent !== label) {
        option.textContent = label;
      }
    }
    return;
  }

  state.historySessionListKey = listKey;
  select.innerHTML = "";
  for (const session of sessions) {
    const option = document.createElement("option");
    option.value = session.session_id;
    option.textContent = sessionOptionLabel(session);
    select.appendChild(option);
  }
  if (previousSessionId && [...select.options].some((o) => o.value === previousSessionId)) {
    select.value = previousSessionId;
  } else if (sessions.length) {
    select.value = sessions[0].session_id;
  }
}

function resolvePathMarker(sessionId, samples) {
  const xs = samples.map((s) => Number(s.position_x_m || 0));
  const ys = samples.map((s) => Number(s.position_y_m || 0));
  const live = state.lastSample;
  const liveX = Number(live.position_x_m);
  const liveY = Number(live.position_y_m);
  const liveHeading = Number(live.heading_deg);
  const last = samples[samples.length - 1];
  const lastHeading = Number(last?.heading_deg || 0);
  const useLiveMarker = state.simRunning
    && state.liveSessionId === sessionId
    && Number.isFinite(liveX)
    && Number.isFinite(liveY);
  return {
    x: useLiveMarker ? liveX : xs[xs.length - 1],
    y: useLiveMarker ? liveY : ys[ys.length - 1],
    heading: useLiveMarker && Number.isFinite(liveHeading) ? liveHeading : lastHeading,
    useLiveMarker,
    xs,
    ys,
  };
}

function historySamplesFingerprint(sessionId, samples) {
  const last = samples[samples.length - 1];
  return [
    sessionId,
    samples.length,
    last?.time_s ?? "",
    last?.position_x_m ?? "",
    last?.position_y_m ?? "",
    last?.speed_mps ?? "",
  ].join("|");
}

function historyMarkerFingerprint(marker) {
  return `${marker.x.toFixed(2)}|${marker.y.toFixed(2)}|${Number(marker.heading || 0).toFixed(1)}`;
}

function makePathToPx(base, view) {
  return (x, y) => worldToScreen(Number(x), Number(y), base, view);
}

function worldToScreen(x, y, base, view) {
  const px = base.offsetX + (x - base.minX) * base.scale;
  const py = base.offsetY + base.drawH - (y - base.minY) * base.scale;
  const cx = base.inset + base.plotW / 2;
  const cy = base.inset + base.plotH / 2;
  return {
    px: cx + (px - cx) * view.zoom + view.panX,
    py: cy + (py - cy) * view.zoom + view.panY,
  };
}

function screenToWorld(sx, sy, base, view) {
  const cx = base.inset + base.plotW / 2;
  const cy = base.inset + base.plotH / 2;
  const px = cx + (sx - cx - view.panX) / view.zoom;
  const py = cy + (sy - cy - view.panY) / view.zoom;
  return {
    x: base.minX + (px - base.offsetX) / base.scale,
    y: base.minY + (base.offsetY + base.drawH - py) / base.scale,
  };
}

function effectivePathScale(base, view) {
  return base.scale * view.zoom;
}

function resetPathView() {
  state.pathView.zoom = 1;
  state.pathView.panX = 0;
  state.pathView.panY = 0;
}

function getPathFollowWorldPosition() {
  const layer = state.historyPathLayer;
  if (layer?.marker) {
    const x = Number(layer.marker.x);
    const y = Number(layer.marker.y);
    if (Number.isFinite(x) && Number.isFinite(y)) {
      return { x, y };
    }
  }
  const sample = state.lastSample;
  if (sample) {
    const x = Number(sample.position_x_m);
    const y = Number(sample.position_y_m);
    if (Number.isFinite(x) && Number.isFinite(y)) {
      return { x, y };
    }
  }
  return null;
}

function centerPathViewOnWorld(x, y) {
  const base = state.historyPathBaseTransform;
  if (!base) return;
  const view = state.pathView;
  const cx = base.inset + base.plotW / 2;
  const cy = base.inset + base.plotH / 2;
  const px0 = base.offsetX + (x - base.minX) * base.scale;
  const py0 = base.offsetY + base.drawH - (y - base.minY) * base.scale;
  view.panX = (cx - px0) * view.zoom;
  view.panY = (cy - py0) * view.zoom;
}

function applyPathFollowIfEnabled() {
  if (!state.pathFollowKart) return false;
  const position = getPathFollowWorldPosition();
  if (!position) return false;
  centerPathViewOnWorld(position.x, position.y);
  return true;
}

function setPathFollowKart(active) {
  state.pathFollowKart = active;
  const btn = document.getElementById("btn-path-follow");
  if (btn) {
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
  }
  if (active) {
    applyPathFollowIfEnabled();
    schedulePathRedraw();
  }
}

function buildPathTransformFromTrack(track, canvas) {
  const bbox = track.bbox;
  return buildPathTransform(
    [Number(bbox.x_min), Number(bbox.x_max)],
    [Number(bbox.y_min), Number(bbox.y_max)],
    canvas,
  );
}

function decimatePathSeries(xs, ys, speeds, maxPoints = 1200) {
  if (xs.length <= maxPoints) {
    return { xs, ys, speeds };
  }
  const step = Math.ceil(xs.length / maxPoints);
  const dx = [];
  const dy = [];
  const ds = [];
  for (let index = 0; index < xs.length; index += step) {
    dx.push(xs[index]);
    dy.push(ys[index]);
    ds.push(speeds[index] ?? 0);
  }
  const lastIndex = xs.length - 1;
  if (dx[dx.length - 1] !== xs[lastIndex]) {
    dx.push(xs[lastIndex]);
    dy.push(ys[lastIndex]);
    ds.push(speeds[lastIndex] ?? 0);
  }
  return { xs: dx, ys: dy, speeds: ds };
}

function schedulePathRedraw() {
  if (state.pathRedrawScheduled) return;
  state.pathRedrawScheduled = true;
  requestAnimationFrame(() => {
    state.pathRedrawScheduled = false;
    redrawPathLayer();
  });
}

function ensureTrackMapVisible(resetView = false) {
  const pathCanvas = document.getElementById("history-path");
  if (!pathCanvas || !state.track.data) return false;
  state.historyPathBaseTransform = buildPathTransformFromTrack(state.track.data, pathCanvas);
  if (resetView && !state.pathFollowKart) {
    resetPathView();
  }
  if (!state.historyPathLayer) {
    state.historyPathLayer = {
      marker: { x: 0, y: 0, heading: 0, xs: [], ys: [], useLiveMarker: false },
      speeds: [],
      pathColorMaxKmh: 45,
    };
  }
  schedulePathRedraw();
  return true;
}

function zoomPathViewAt(canvasX, canvasY, factor) {
  const base = state.historyPathBaseTransform;
  if (!base) return;
  const view = state.pathView;
  const before = screenToWorld(canvasX, canvasY, base, view);
  view.zoom = Math.max(0.4, Math.min(24, view.zoom * factor));
  const after = worldToScreen(before.x, before.y, base, view);
  view.panX += canvasX - after.px;
  view.panY += canvasY - after.py;
  applyPathFollowIfEnabled();
  redrawPathLayer();
}

function canvasCoordsFromEvent(canvas, event) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  return {
    x: (event.clientX - rect.left) * scaleX,
    y: (event.clientY - rect.top) * scaleY,
  };
}

function redrawPathLayer() {
  const layer = state.historyPathLayer;
  const base = state.historyPathBaseTransform;
  if (!layer || !base) return;

  applyPathFollowIfEnabled();

  const pathCanvas = document.getElementById("history-path");
  const markerCanvas = document.getElementById("history-marker");
  if (!pathCanvas || !markerCanvas) return;

  const pathCtx = pathCanvas.getContext("2d");
  const view = state.pathView;
  const toPx = (x, y) => worldToScreen(x, y, base, view);
  state.historyPathTransform = { base, view };

  pathCtx.clearRect(0, 0, pathCanvas.width, pathCanvas.height);
  drawTrackUnderlay(pathCtx, state.track.data, toPx);
  const pathSeries = decimatePathSeries(layer.marker.xs, layer.marker.ys, layer.speeds);
  drawSpeedColoredPath(
    pathCtx,
    pathSeries.xs,
    pathSeries.ys,
    pathSeries.speeds,
    layer.pathColorMaxKmh,
    toPx,
  );
  drawStartFinishLine(pathCtx, state.track.data, toPx);
  pathCtx.fillStyle = "#8aa0b8";
  pathCtx.font = "12px sans-serif";
  const trackLabel = state.track.data ? ` | ${state.track.data.name}` : "";
  const zoomLabel = view.zoom === 1 ? "" : ` · ${view.zoom.toFixed(1)}×`;
  const followLabel = state.pathFollowKart ? " · follow on" : "";
  pathCtx.fillText(
    `Path trace — blue slow → red at ${layer.pathColorMaxKmh.toFixed(0)} km/h limit${trackLabel}${zoomLabel}${followLabel}`,
    10,
    16,
  );

  drawPathMarkerOverlay(layer.marker.x, layer.marker.y, layer.marker.heading, state.historyVehicleDims);
}

function buildPathTransform(boundsXs, boundsYs, canvas) {
  const minX = Math.min(...boundsXs);
  const maxX = Math.max(...boundsXs);
  const minY = Math.min(...boundsYs);
  const maxY = Math.max(...boundsYs);
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  const inset = 27;
  const plotW = canvas.width - inset * 2;
  const plotH = canvas.height - inset * 2;
  const scale = Math.min(plotW / spanX, plotH / spanY);
  const drawW = spanX * scale;
  const drawH = spanY * scale;
  const offsetX = inset + (plotW - drawW) / 2;
  const offsetY = inset + (plotH - drawH) / 2;
  return {
    minX,
    maxX,
    minY,
    maxY,
    spanX,
    spanY,
    inset,
    plotW,
    plotH,
    scale,
    offsetX,
    offsetY,
    drawW,
    drawH,
  };
}

function collectPathBounds(marker) {
  const xs = marker.useLiveMarker ? marker.xs.concat(marker.x) : marker.xs.slice();
  const ys = marker.useLiveMarker ? marker.ys.concat(marker.y) : marker.ys.slice();
  const track = state.track.data;
  if (track) {
    track.inner_boundary.forEach((point) => {
      xs.push(Number(point.x));
      ys.push(Number(point.y));
    });
    track.outer_boundary.forEach((point) => {
      xs.push(Number(point.x));
      ys.push(Number(point.y));
    });
  }
  return { xs, ys };
}

function pxToWorld(px, py, base, view) {
  return screenToWorld(px, py, base, view);
}

function findNearestCenterlinePoint(centerline, x, y) {
  let best = centerline[0];
  let bestDist = Number.POSITIVE_INFINITY;
  for (const point of centerline) {
    const dx = Number(point.x) - x;
    const dy = Number(point.y) - y;
    const dist = dx * dx + dy * dy;
    if (dist < bestDist) {
      best = point;
      bestDist = dist;
    }
  }
  return best;
}

function drawPolyline(pathCtx, points, toPx) {
  if (!points.length) return;
  pathCtx.beginPath();
  const first = toPx(Number(points[0].x), Number(points[0].y));
  pathCtx.moveTo(first.px, first.py);
  for (let index = 1; index < points.length; index += 1) {
    const point = toPx(Number(points[index].x), Number(points[index].y));
    pathCtx.lineTo(point.px, point.py);
  }
  pathCtx.stroke();
}

function drawTrackUnderlay(pathCtx, track, toPx) {
  if (!track) return;
  pathCtx.lineWidth = 1.25;
  pathCtx.strokeStyle = "rgba(110, 130, 150, 0.55)";
  drawPolyline(pathCtx, track.outer_boundary, toPx);
  pathCtx.strokeStyle = "rgba(90, 110, 130, 0.45)";
  drawPolyline(pathCtx, track.inner_boundary, toPx);
  pathCtx.setLineDash([5, 7]);
  pathCtx.strokeStyle = "rgba(150, 170, 190, 0.35)";
  drawPolyline(pathCtx, track.centerline, toPx);
  pathCtx.setLineDash([]);
}

function drawStartFinishLine(pathCtx, track, toPx) {
  const line = track?.start_finish_line;
  if (!line) return;
  const start = toPx(line.x1, line.y1);
  const end = toPx(line.x2, line.y2);
  pathCtx.strokeStyle = "#4ade80";
  pathCtx.lineWidth = 3;
  pathCtx.beginPath();
  pathCtx.moveTo(start.px, start.py);
  pathCtx.lineTo(end.px, end.py);
  pathCtx.stroke();
}

async function resolveVehicleDimensions(vehicleName, vehicleVersion) {
  const cacheKey = `${vehicleName}|${vehicleVersion}`;
  if (state.vehicleDimensionsCache[cacheKey]) {
    return state.vehicleDimensionsCache[cacheKey];
  }
  const detail = await api(
    `/api/config/vehicles/${encodeURIComponent(vehicleName)}/${encodeURIComponent(vehicleVersion)}/detail`,
  );
  const dims = {
    wheelbase_m: Number(detail.wheelbase_m) || 1.04,
    track_m: ((Number(detail.front_track_m) || 0.9) + (Number(detail.rear_track_m) || 0.9)) / 2,
  };
  state.vehicleDimensionsCache[cacheKey] = dims;
  return dims;
}

async function resolvePathColorMaxKmh(session, peakSpeedKmh) {
  const cacheKey = [
    session.vehicle_name,
    session.vehicle_version,
    session.drive_mode,
    session.driver_profile,
  ].join("|");
  if (state.historyLimitsCacheKey === cacheKey && state.historyLimitsCacheValue) {
    return state.historyLimitsCacheValue;
  }
  try {
    const params = new URLSearchParams({
      vehicle_name: session.vehicle_name,
      vehicle_version: session.vehicle_version,
      mode: session.drive_mode,
      profile: session.driver_profile,
    });
    const limits = await api(`/api/config/effective-limits?${params}`);
    state.historyLimitsCacheKey = cacheKey;
    state.historyLimitsCacheValue = limits.max_speed_kmh;
    return limits.max_speed_kmh;
  } catch (_error) {
    return peakSpeedKmh;
  }
}

function drawPathMarkerOverlay(markerX, markerY, headingDeg, dims) {
  const markerCanvas = document.getElementById("history-marker");
  const base = state.historyPathBaseTransform;
  if (!markerCanvas || !base) return;
  const markerCtx = markerCanvas.getContext("2d");
  markerCtx.clearRect(0, 0, markerCanvas.width, markerCanvas.height);
  const view = state.pathView;
  const toPx = (x, y) => worldToScreen(x, y, base, view);
  const effectiveTransform = { ...base, scale: effectivePathScale(base, view) };
  drawKartMarker(
    markerCtx,
    markerX,
    markerY,
    headingDeg,
    dims,
    toPx,
    markerCanvas,
    effectiveTransform,
  );
}

function drawKartMarker(markerCtx, x, y, headingDeg, dims, toPx, canvas, transform) {
  let { px, py } = toPx(x, y);
  const metersPerPx = Math.max(transform.scale, 1e-6);
  const lengthPx = Math.max(dims.wheelbase_m / metersPerPx, 8);
  const widthPx = Math.max(dims.track_m / metersPerPx, 5);
  ({ px, py } = clampPathMarkerPx(px, py, canvas, Math.max(lengthPx, widthPx)));

  const angleRad = (-Number(headingDeg) * Math.PI) / 180;
  markerCtx.save();
  markerCtx.translate(px, py);
  markerCtx.rotate(angleRad);
  markerCtx.fillStyle = "#ff3b30";
  markerCtx.strokeStyle = "#ffffff";
  markerCtx.lineWidth = 1.5;
  markerCtx.fillRect(-lengthPx / 2, -widthPx / 2, lengthPx, widthPx);
  markerCtx.strokeRect(-lengthPx / 2, -widthPx / 2, lengthPx, widthPx);
  markerCtx.fillStyle = "#ffffff";
  markerCtx.fillRect(lengthPx / 2 - 2, -1.5, 3, 3);
  markerCtx.restore();
}

function invalidateHistoryDrawCache() {
  state.historyViewSessionId = "";
  state.historySamplesFingerprint = "";
  state.historyMarkerFingerprint = "";
  state.historyChartLastDrawMs = 0;
  state.historyPathTransform = null;
  state.historyPathBaseTransform = null;
  state.historyPathLayer = null;
  resetPathView();
}

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
      updateSessionSelect(sessions, select, previousSessionId);
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

function historyPollIntervalMs() {
  return state.simRunning ? 400 : 250;
}

function startHistoryPolling() {
  stopHistoryPolling();
  state.historyPollCount = 0;
  void refreshHistoryView(true);
  const scheduleNextPoll = () => {
    state.historyPollTimer = window.setTimeout(() => {
      void refreshHistoryView(false);
      scheduleNextPoll();
    }, historyPollIntervalMs());
  };
  scheduleNextPoll();
}

function stopHistoryPolling() {
  if (state.historyPollTimer !== null) {
    clearTimeout(state.historyPollTimer);
    state.historyPollTimer = null;
  }
}

function isHistoryTabActive() {
  const tab = activeTabName();
  if (tab === "config") return false;
  if (isSplitTelemetryView()) return true;
  return tab === "history";
}

const SPLIT_TELEMETRY_MQ = window.matchMedia("(min-width: 1200px)");

function isSplitTelemetryView() {
  return SPLIT_TELEMETRY_MQ.matches;
}

function activeTabName() {
  return document.querySelector(".tab.active")?.dataset.tab || "live";
}

function syncTelemetryPanels(tab) {
  const live = document.getElementById("tab-live");
  const history = document.getElementById("tab-history");
  const split = document.getElementById("telemetry-split");
  const config = document.getElementById("tab-config");
  const tabsBar = document.querySelector(".tabs");

  if (tab === "config") {
    split.classList.add("hidden");
    config.classList.remove("hidden");
    tabsBar?.classList.remove("split-telemetry-active");
    stopHistoryPolling();
    return;
  }

  split.classList.remove("hidden");
  config.classList.add("hidden");

  if (isSplitTelemetryView()) {
    split.classList.add("layout-split");
    live.classList.remove("hidden");
    history.classList.remove("hidden");
    tabsBar?.classList.add("split-telemetry-active");
    rebuildChannelsGrid();
    if (state.lastSample && Object.keys(state.lastSample).length) {
      updateChannelsGrid(state.lastSample);
    }
    startHistoryPolling();
    return;
  }

  split.classList.remove("layout-split");
  tabsBar?.classList.remove("split-telemetry-active");
  live.classList.toggle("hidden", tab !== "live");
  history.classList.toggle("hidden", tab !== "history");
  if (tab === "history") {
    startHistoryPolling();
  } else {
    stopHistoryPolling();
  }
  if (tab === "live") {
    rebuildChannelsGrid();
    if (state.lastSample && Object.keys(state.lastSample).length) {
      updateChannelsGrid(state.lastSample);
    }
  }
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
  const hue = 240 * (1 - t);
  return `hsl(${hue}, 82%, 48%)`;
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
  drawKartMarker(
    pathCtx,
    x,
    y,
    0,
    state.historyVehicleDims,
    toPx,
    canvas,
    state.historyPathTransform,
  );
}

async function drawSessionChart(sessionId) {
  if (!isHistoryTabActive()) return;

  await applySessionTrack(sessionId);
  await renderSessionLaps(sessionId);

  const sessionChanged = sessionId !== state.historyViewSessionId;
  if (sessionChanged) {
    state.historyViewSessionId = sessionId;
    state.historySamplesFingerprint = "";
    state.historyMarkerFingerprint = "";
  }

  const [samples, session] = await Promise.all([
    api(`/api/sessions/${sessionId}/samples?limit=5000`),
    api(`/api/sessions/${sessionId}`),
  ]);

  const pathCanvas = document.getElementById("history-path");
  if (!samples.length) {
    ensureTrackMapVisible(sessionChanged);
    return;
  }

  const marker = resolvePathMarker(sessionId, samples);
  const samplesFingerprint = historySamplesFingerprint(sessionId, samples);
  const markerFingerprint = historyMarkerFingerprint(marker);
  const samplesChanged = samplesFingerprint !== state.historySamplesFingerprint;
  const markerChanged = markerFingerprint !== state.historyMarkerFingerprint;
  const vehicleDims = await resolveVehicleDimensions(session.vehicle_name, session.vehicle_version);
  state.historyVehicleDims = vehicleDims;

  if (!samplesChanged && !markerChanged) {
    return;
  }

  const canvas = document.getElementById("history-chart");
  const markerCanvas = document.getElementById("history-marker");
  const ctx = canvas.getContext("2d");

  if (samplesChanged) {
    const speeds = samples.map((s) => Number(s.speed_mps || 0) * 3.6);
    const steers = samples.map((s) => Number(s.steering_angle_deg || 0));
    const peakSpeed = Math.max(...speeds, 0);
    const maxSpeed = Math.max(peakSpeed, 1);
    const pathColorMaxKmh = await resolvePathColorMaxKmh(session, maxSpeed);

    if (state.track.data && pathCanvas) {
      state.historyPathBaseTransform = buildPathTransformFromTrack(state.track.data, pathCanvas);
    } else if (pathCanvas) {
      const bounds = collectPathBounds(marker);
      state.historyPathBaseTransform = buildPathTransform(bounds.xs, bounds.ys, pathCanvas);
    }
    if (sessionChanged && !state.pathFollowKart) {
      resetPathView();
    }

    state.historyPathColorMaxKmh = pathColorMaxKmh;
    state.historyPathLayer = {
      marker,
      speeds,
      pathColorMaxKmh,
    };

    const now = performance.now();
    const shouldDrawCharts = sessionChanged
      || !state.simRunning
      || now - state.historyChartLastDrawMs > 750;
    if (shouldDrawCharts) {
      const maxSteer = Math.max(...steers.map((v) => Math.abs(v)), 1);
      const steerNorm = steers.map((v) => (v + maxSteer) / (2 * maxSteer));
      const panelHeight = (canvas.height - 50) / 2;

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      plotSeries(ctx, samples, speeds, "#3dd6c6", 24, panelHeight, maxSpeed);
      plotSeries(ctx, samples, steerNorm, "#ffb020", 24 + panelHeight + 16, panelHeight, 1);
      ctx.fillStyle = "#8aa0b8";
      ctx.font = "12px sans-serif";
      ctx.fillText(`Speed (max ${maxSpeed.toFixed(1)} km/h)`, 10, 16);
      ctx.fillText(`Steering (±${maxSteer.toFixed(0)}°)`, 10, 24 + panelHeight + 12);
      state.historyChartLastDrawMs = now;
    }

    schedulePathRedraw();
  }

  if (markerChanged && !samplesChanged) {
    if (state.historyPathLayer) {
      state.historyPathLayer.marker = marker;
    }
    drawPathMarkerOverlay(marker.x, marker.y, marker.heading, vehicleDims);
  }

  state.historySamplesFingerprint = samplesFingerprint;
  state.historyMarkerFingerprint = markerFingerprint;
}

function updateHistoryMarkerFromLive() {
  if (!isHistoryTabActive() || !state.historyPathBaseTransform) return;
  if (!state.simRunning || !state.liveSessionId) return;

  const sessionSelect = document.getElementById("session-select");
  if (sessionSelect.value !== state.liveSessionId) {
    if ([...sessionSelect.options].some((option) => option.value === state.liveSessionId)) {
      sessionSelect.value = state.liveSessionId;
      resetLiveHistoryState();
    } else {
      return;
    }
  }

  const liveX = Number(state.lastSample.position_x_m);
  const liveY = Number(state.lastSample.position_y_m);
  const liveHeading = Number(state.lastSample.heading_deg);
  const liveSpeedKmh = Number(state.lastSample.speed_mps || 0) * 3.6;
  if (!Number.isFinite(liveX) || !Number.isFinite(liveY)) return;

  const markerFingerprint = historyMarkerFingerprint({
    x: liveX,
    y: liveY,
    heading: liveHeading,
  });
  if (markerFingerprint === state.historyMarkerFingerprint) return;

  if (state.historyPathLayer) {
    const marker = state.historyPathLayer.marker;
    const xs = marker.xs.slice();
    const ys = marker.ys.slice();
    const speeds = state.historyPathLayer.speeds.slice();
    const lastX = xs.length ? xs[xs.length - 1] : null;
    const lastY = ys.length ? ys[ys.length - 1] : null;
    const moved = lastX === null || Math.hypot(liveX - lastX, liveY - lastY) > 0.05;
    if (moved) {
      xs.push(liveX);
      ys.push(liveY);
      speeds.push(liveSpeedKmh);
    }
    state.historyPathLayer.marker = {
      ...marker,
      x: liveX,
      y: liveY,
      heading: liveHeading,
      useLiveMarker: true,
      xs,
      ys,
    };
    state.historyPathLayer.speeds = speeds;
    if (moved) {
      schedulePathRedraw();
    } else if (state.pathFollowKart) {
      applyPathFollowIfEnabled();
      schedulePathRedraw();
    }
  }

  drawPathMarkerOverlay(liveX, liveY, liveHeading, state.historyVehicleDims);
  state.historyMarkerFingerprint = markerFingerprint;
}

function selectedVehicle() {
  const [name, version] = document.getElementById("vehicle-select").value.split("|");
  return { vehicle_name: name, vehicle_version: version };
}

async function sendInputs() {
  if (!interactiveInputsEnabled()) return;
  const safetyState = state.lastSample?.safety_state || "";
  const faultActive = state.faultControlsActive || isFaultSafetyState(safetyState);
  const brake = state.brakeHold
    ? 1.0
    : Number(document.getElementById("brake").value) / 100;
  await api("/api/sim/inputs", {
    method: "POST",
    body: JSON.stringify({
      throttle: faultActive ? 0 : Number(document.getElementById("throttle").value) / 100,
      brake,
      steering: -Number(document.getElementById("steering").value) / 100,
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
  updateSliderReadouts();
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
      state.faultAckPending = false;
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
      const faults = faultDisplayCodes(state.lastSample);
      const recovery = document.getElementById("fault-recovery-panel");
      const recoveryText = document.getElementById("fault-recovery-text");
      if (recovery && recoveryText) {
        recovery.classList.remove("hidden");
        recoveryText.textContent = describeFaults(
          faults,
          state.lastSample,
          state.faultContext,
        );
      }
      const isCritical = String(faults).includes("PACK_") || String(faults).includes("CELL_")
        || String(faults).includes("BATTERY_OVERTEMP") || String(faults).includes("CONTACTOR")
        || String(faults).includes("PRECHARGE");
      const waitingToRecover = state.faultAckPending;
      hint.innerHTML = waitingToRecover
        ? "<strong>Recovering…</strong> Power and regen are off — use the <strong>brake</strong> to slow down, then click <strong>Clear fault</strong>."
        : safetyState === "SAFE_SHUTDOWN"
        ? isCritical
          ? "<strong>Power cut</strong> — throttle and regen are off. Use the <strong>brake</strong> to stop, wait for voltage to settle, then click <strong>Clear fault</strong>."
          : "<strong>System shut down</strong> — use the <strong>brake</strong> to stop, then click <strong>Clear fault</strong>."
        : isCritical
          ? "Critical fault — power and regen are off. Use the <strong>brake</strong> to slow down, then click <strong>Clear fault</strong>."
          : "Fault active — power and regen are off. Use the <strong>brake</strong> to slow down, then click <strong>Clear fault</strong>.";
      armBtn.disabled = true;
      driving.classList.remove("locked");
      driving.classList.add("fault-active");
      break;
    }
    default:
      hint.textContent = `Safety state: ${safetyState}`;
      armBtn.disabled = true;
      driving.classList.add("locked");
      driving.classList.remove("fault-active");
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

function syncDrivingControlsState() {
  const mode = simMode();
  const interactive = interactiveInputsEnabled();
  const auto = autoDriveActive();
  const driving = document.getElementById("driving-controls");
  document.getElementById("btn-brake-hold").classList.toggle("hidden", mode !== "free");
  driving.classList.toggle("auto-passive", auto);

  if (auto) {
    driving.classList.remove("locked");
    return;
  }
  driving.classList.remove("auto-passive");

  if (!interactive) {
    driving.classList.add("locked");
    return;
  }
  if (mode === "manual") {
    driving.classList.toggle("locked", !state.simRunning);
  }
}

function updateSimModeUi() {
  const mode = simMode();
  const free = mode === "free";
  const auto = mode === "auto";
  document.getElementById("scenario-label").classList.toggle("hidden", free || auto);
  document.getElementById("free-drive-panel").classList.toggle("hidden", !free);
  document.getElementById("auto-drive-panel")?.classList.toggle("hidden", !auto);
  document.getElementById("btn-arm-scenario").classList.toggle("hidden", free || auto);
  document.getElementById("btn-ack-scenario").classList.toggle("hidden", free || auto);

  syncDrivingControlsState();

  const startBtn = document.getElementById("btn-start");
  const stopBtn = document.getElementById("btn-stop");
  if (auto) {
    startBtn.textContent = "Start auto drive";
    stopBtn.textContent = "Stop";
  } else if (free) {
    startBtn.textContent = "Start session";
    stopBtn.textContent = "End session";
  } else {
    startBtn.textContent = "Start";
    stopBtn.textContent = "Stop";
  }
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
      syncTelemetryPanels(button.dataset.tab);
      if (button.dataset.tab === "config" && typeof window.loadConfigEditor === "function") {
        window.loadConfigEditor();
      }
    });
  });

  SPLIT_TELEMETRY_MQ.addEventListener("change", () => {
    syncTelemetryPanels(activeTabName());
  });
}

function setStartFinishEditMode(active) {
  state.track.editStartFinish = active;
  document.getElementById("btn-edit-start-finish")?.classList.toggle("active", active);
  document.getElementById("track-edit-hint")?.classList.toggle("hidden", !active);
  document.getElementById("history-path-stack")?.classList.toggle("edit-start-finish", active);
}

async function loadTrackCatalog() {
  try {
    const tracks = await api("/api/tracks");
    for (const selectId of ["track-select", "sim-track-select"]) {
      const select = document.getElementById(selectId);
      if (!select) continue;
      const current = select.value;
      const emptyLabel = selectId === "sim-track-select"
        ? "No track (free plane)"
        : "No track";
      select.innerHTML = `<option value="">${emptyLabel}</option>`;
      for (const track of tracks) {
        const option = document.createElement("option");
        option.value = track.id;
        option.textContent = `${track.name} (${Math.round(track.length_m)} m)`;
        select.appendChild(option);
      }
      if (current && [...select.options].some((option) => option.value === current)) {
        select.value = current;
      }
    }
  } catch (_error) {
    /* track list is optional */
  }
}

function syncTrackSelectValue(trackId) {
  for (const selectId of ["track-select", "sim-track-select"]) {
    const select = document.getElementById(selectId);
    if (!select) continue;
    if (trackId && [...select.options].some((option) => option.value === trackId)) {
      select.value = trackId;
    } else if (!trackId) {
      select.value = "";
    }
  }
}

async function renderSessionLaps(sessionId) {
  const panel = document.getElementById("session-laps-panel");
  const body = document.querySelector("#session-laps-table tbody");
  if (!panel || !body) return;
  try {
    const laps = await api(`/api/sessions/${encodeURIComponent(sessionId)}/laps`);
    body.innerHTML = "";
    if (!laps.length) {
      panel.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");
    for (const lap of laps) {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${lap.lap_number}</td>
        <td>${formatLapTime(lap.lap_time_s)}</td>
        <td>${Number(lap.completed_at_time_s).toFixed(1)}</td>
      `;
      body.appendChild(row);
    }
  } catch (_error) {
    panel.classList.add("hidden");
  }
}

async function applySessionTrack(sessionId) {
  if (!sessionId) return;
  try {
    const session = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
    if (session.track_id && session.track_id !== state.track.id) {
      syncTrackSelectValue(session.track_id);
      await loadSelectedTrack(true, false);
    }
  } catch (_error) {
    /* optional */
  }
}

async function loadSelectedTrack(force = false, redrawSession = true) {
  const trackId = document.getElementById("track-select").value;
  const directionSelect = document.getElementById("track-direction-select");
  if (!trackId) {
    state.track.id = null;
    state.track.data = null;
    if (directionSelect) {
      directionSelect.disabled = true;
      directionSelect.value = "clockwise";
    }
    invalidateHistoryDrawCache();
    const sessionId = document.getElementById("session-select").value;
    if (sessionId) await drawSessionChart(sessionId);
    return;
  }
  if (!force && state.track.id === trackId && state.track.data) return;
  state.track.data = await api(`/api/tracks/${encodeURIComponent(trackId)}`);
  state.track.id = trackId;
  syncTrackDirectionControls();
  syncTrackSelectValue(trackId);
  const sessionId = document.getElementById("session-select").value;
  if (sessionId && redrawSession) {
    invalidateHistoryDrawCache();
    await drawSessionChart(sessionId);
  } else if (!sessionId) {
    ensureTrackMapVisible(true);
  } else {
    ensureTrackMapVisible(false);
  }
}

function syncTrackDirectionControls() {
  const directionSelect = document.getElementById("track-direction-select");
  if (!directionSelect) return;
  const hasTrack = Boolean(state.track.data);
  directionSelect.disabled = !hasTrack;
  if (!hasTrack) {
    directionSelect.value = "clockwise";
    return;
  }
  state.track.suppressDirectionChange = true;
  directionSelect.value = state.track.data.direction || "clockwise";
  state.track.suppressDirectionChange = false;
}

async function saveTrackDirection(direction) {
  if (!state.track.id || !state.track.data) return;
  state.track.data = await api(`/api/tracks/${encodeURIComponent(state.track.id)}/direction`, {
    method: "POST",
    body: JSON.stringify({ direction }),
  });
  syncTrackDirectionControls();
  invalidateHistoryDrawCache();
  const sessionId = document.getElementById("session-select").value;
  if (sessionId) await drawSessionChart(sessionId);
}

async function handleTrackCanvasClick(event) {
  if (state.pathPan.moved) return;
  if (!state.track.editStartFinish || !state.track.data || !state.historyPathBaseTransform) return;
  const pathCanvas = document.getElementById("history-path");
  const coords = canvasCoordsFromEvent(pathCanvas, event);
  const world = screenToWorld(coords.x, coords.y, state.historyPathBaseTransform, state.pathView);
  const nearest = findNearestCenterlinePoint(state.track.data.centerline, world.x, world.y);
  state.track.data = await api(`/api/tracks/${encodeURIComponent(state.track.id)}/start-finish`, {
    method: "POST",
    body: JSON.stringify({ s_m: Number(nearest.s) }),
  });
  setStartFinishEditMode(false);
  redrawPathLayer();
}

function setupPathMapInteractions() {
  const stack = document.getElementById("history-path-stack");
  const pathCanvas = document.getElementById("history-path");
  if (!stack || !pathCanvas) return;

  const releasePathPan = (event) => {
    if (!state.pathPan.active) return;
    if (event && event.pointerId !== state.pathPan.pointerId) return;
    try {
      if (event?.pointerId != null) {
        stack.releasePointerCapture(event.pointerId);
      }
    } catch (_error) {
      /* pointer may already be released */
    }
    state.pathPan.active = false;
    state.pathPan.pointerId = null;
    stack.classList.remove("is-panning");
    if (state.pathPan.moved) {
      window.setTimeout(() => {
        state.pathPan.moved = false;
      }, 0);
    }
  };

  stack.addEventListener(
    "wheel",
    (event) => {
      if (!state.historyPathBaseTransform) return;
      event.preventDefault();
      const coords = canvasCoordsFromEvent(pathCanvas, event);
      const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
      zoomPathViewAt(coords.x, coords.y, factor);
    },
    { passive: false },
  );

  stack.addEventListener("pointerdown", (event) => {
    if (!state.historyPathBaseTransform) return;
    if (state.track.editStartFinish && event.button === 0) return;
    if (event.button !== 0 && event.button !== 2) return;
    event.preventDefault();
    stack.setPointerCapture(event.pointerId);
    state.pathPan.active = true;
    state.pathPan.pointerId = event.pointerId;
    state.pathPan.startX = event.clientX;
    state.pathPan.startY = event.clientY;
    state.pathPan.startPanX = state.pathView.panX;
    state.pathPan.startPanY = state.pathView.panY;
    state.pathPan.moved = false;
    stack.classList.add("is-panning");
  });

  stack.addEventListener("pointermove", (event) => {
    if (!state.pathPan.active || event.pointerId !== state.pathPan.pointerId) return;
    const dx = event.clientX - state.pathPan.startX;
    const dy = event.clientY - state.pathPan.startY;
    if (Math.hypot(dx, dy) > 4) {
      state.pathPan.moved = true;
      if (state.pathFollowKart) {
        setPathFollowKart(false);
      }
    }
    const rect = pathCanvas.getBoundingClientRect();
    const scaleX = pathCanvas.width / rect.width;
    const scaleY = pathCanvas.height / rect.height;
    state.pathView.panX = state.pathPan.startPanX + dx * scaleX;
    state.pathView.panY = state.pathPan.startPanY + dy * scaleY;
    redrawPathLayer();
  });

  stack.addEventListener("pointerup", releasePathPan);
  stack.addEventListener("pointercancel", releasePathPan);
  window.addEventListener("pointerup", releasePathPan);
  window.addEventListener("pointercancel", releasePathPan);

  pathCanvas.addEventListener("click", (event) => {
    void handleTrackCanvasClick(event);
  });

  stack.addEventListener("dblclick", () => {
    if (!state.historyPathBaseTransform) return;
    setPathFollowKart(false);
    resetPathView();
    redrawPathLayer();
  });

  stack.addEventListener("contextmenu", (event) => {
    event.preventDefault();
  });

  const followBtn = document.getElementById("btn-path-follow");
  if (followBtn) {
    followBtn.addEventListener("click", () => {
      setPathFollowKart(!state.pathFollowKart);
    });
  }
}

function setupControls() {
  document.getElementById("sim-mode").addEventListener("change", updateSimModeUi);
  const autoAggression = document.getElementById("auto-aggression");
  const autoAggressionValue = document.getElementById("auto-aggression-value");
  if (autoAggression && autoAggressionValue) {
    autoAggression.addEventListener("input", () => {
      autoAggressionValue.textContent = `${autoAggression.value}%`;
    });
  }
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
    const trackId = document.getElementById("sim-track-select")?.value;
    if (mode === "auto" && !trackId) {
      window.alert("Auto drive requires a track — select one in the Track dropdown.");
      return;
    }
    if (trackId) {
      syncTrackSelectValue(trackId);
      await loadSelectedTrack(true);
    }
    const aggressionPct = Number(document.getElementById("auto-aggression")?.value || 100);
    await api("/api/sim/start", {
      method: "POST",
      body: JSON.stringify({
        ...vehicle,
        ...driveSettings,
        scenario: document.getElementById("scenario-select").value,
        manual: mode === "manual",
        free_mode: mode === "free",
        auto_drive: mode === "auto",
        target_laps: Number(document.getElementById("auto-laps")?.value || 3),
        aggression: aggressionPct / 100,
        speedup: mode === "auto" ? 20.0 : 5.0,
        track_id: trackId || null,
      }),
    });
    state.simRunning = true;
    if (interactiveInputsEnabled()) startManualInputPolling();
    syncDrivingControlsState();
    await beginLiveSession();
    updateSimModeUi();
    updateFreeDriveGuide(state.lastSample.safety_state || "OFF");
  });

  document.getElementById("btn-stop").addEventListener("click", async () => {
    stopManualInputPolling();
    setBrakeHold(false);
    state.simRunning = false;
    state.liveSessionId = null;
    await api("/api/sim/stop", { method: "POST" });
    updateSimModeUi();
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
    updateSliderReadouts();
    await sendInputs();
    state.faultAckPending = true;
    state.faultContext = null;
    await api("/api/sim/ack", { method: "POST" });
  });
  document.getElementById("btn-brake-hold").addEventListener("click", () => setBrakeHold(!state.brakeHold));
  document.getElementById("btn-arm-scenario").addEventListener("click", () => api("/api/sim/arm", { method: "POST" }));
  document.getElementById("btn-ack-scenario").addEventListener("click", async () => {
    document.getElementById("throttle").value = "0";
    document.getElementById("brake").value = "0";
    updateSliderReadouts();
    await sendInputs();
    state.faultAckPending = true;
    state.faultContext = null;
    await api("/api/sim/ack", { method: "POST" });
  });
  document.getElementById("btn-refresh-sessions").addEventListener("click", () => {
    void refreshHistoryView(true);
  });
  document.getElementById("session-select").addEventListener("change", (event) => {
    invalidateHistoryDrawCache();
    void drawSessionChart(event.target.value);
  });
  document.getElementById("track-select").addEventListener("change", () => {
    setStartFinishEditMode(false);
    syncTrackSelectValue(document.getElementById("track-select").value);
    void loadSelectedTrack(true);
  });
  document.getElementById("sim-track-select")?.addEventListener("change", (event) => {
    syncTrackSelectValue(event.target.value);
    void loadSelectedTrack(true);
  });
  document.getElementById("track-direction-select").addEventListener("change", (event) => {
    if (state.track.suppressDirectionChange) return;
    void saveTrackDirection(event.target.value);
  });
  document.getElementById("btn-edit-start-finish").addEventListener("click", () => {
    if (!state.track.data) return;
    setStartFinishEditMode(!state.track.editStartFinish);
  });
  setupPathMapInteractions();

  for (const id of ["throttle", "steering"]) {
    document.getElementById(id).addEventListener("input", () => {
      updateSliderReadouts();
      sendInputs();
    });
  }
  document.getElementById("brake").addEventListener("input", () => {
    updateSliderReadouts();
    onBrakeSliderInput();
  });
  document.getElementById("steering").addEventListener("dblclick", () => {
    document.getElementById("steering").value = "0";
    updateSliderReadouts();
    void sendInputs();
  });
  updateSliderReadouts();
  updateSimModeUi();
}

async function init() {
  state.hiddenChannels = loadHiddenChannels();
  setupTabs();
  setupControls();
  setupChannelCustomise();
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
  await loadTrackCatalog();
  const initialTrackId = document.getElementById("sim-track-select")?.value;
  if (initialTrackId) {
    syncTrackSelectValue(initialTrackId);
    await loadSelectedTrack(true);
  }
  connectWebSocket();
  syncTelemetryPanels(activeTabName());
}

init();

window.loadDriveSettingOptions = loadDriveSettingOptions;
window.updateEffectiveLimits = updateEffectiveLimits;
