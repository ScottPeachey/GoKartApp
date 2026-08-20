(() => {
  const STORAGE_ENABLED = "gokart.engineAudio.enabled";
  const STORAGE_VOLUME = "gokart.engineAudio.volume";
  const WORKLET_URL = "/static/engine-audio-worklet.js?v=5";

  const audio = {
    enabled: false,
    volume: 0.4,
    context: null,
    worklet: null,
    master: null,
    starting: null,
    pendingSample: null,
    lastRpm: 0,
    lastFireHz: 0,
    lastSource: "none",
    uiTimer: 0,
    lastPostMs: 0,
    lastPosted: null,
    masterAudible: null,
  };

  function clamp01(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0;
    return Math.max(0, Math.min(1, number));
  }

  function firingHzFromRpm(rpm) {
    return Math.max(0, Number(rpm) || 0) / 60;
  }

  function telemetryFromSample(sample) {
    const engineRpm = Number(sample?.engine_rpm);
    const motorRpm = Number(sample?.motor_rpm);
    const hasEngine = Number.isFinite(engineRpm);
    const hasMotor = Number.isFinite(motorRpm);
    const type = String(sample?.powertrain_type || "");
    const isIce = type === "ice" || (type !== "ev" && hasEngine && engineRpm > 1);
    let rpm = 0;
    let source = "none";
    if (isIce) {
      rpm = engineRpm;
      source = "engine_rpm";
    } else if (hasMotor && motorRpm > 1) {
      rpm = motorRpm;
      source = "motor_rpm";
    } else if (hasEngine && engineRpm > 0) {
      rpm = engineRpm;
      source = "engine_rpm";
    }
    const throttle = clamp01(sample?.throttle);
    const brake = clamp01(sample?.brake);
    const clutchLocked = Number(sample?.clutch_locked);
    const safety = String(sample?.safety_state || "");
    const powered = safety === "DRIVING" || safety === "ARMED" || safety === "READY";
    return {
      rpm: Math.max(0, Number.isFinite(rpm) ? rpm : 0),
      fireHz: firingHzFromRpm(rpm),
      load: throttle,
      ice: isIce ? 1 : 0,
      clutch: Number.isFinite(clutchLocked) ? clamp01(clutchLocked) : 1,
      brake,
      powered,
      source,
    };
  }

  function loadPrefs() {
    try {
      audio.enabled = localStorage.getItem(STORAGE_ENABLED) === "1";
      const stored = Number(localStorage.getItem(STORAGE_VOLUME));
      if (Number.isFinite(stored)) audio.volume = clamp01(stored);
    } catch (_error) {
      audio.enabled = false;
    }
  }

  function savePrefs() {
    try {
      localStorage.setItem(STORAGE_ENABLED, audio.enabled ? "1" : "0");
      localStorage.setItem(STORAGE_VOLUME, String(audio.volume));
    } catch (_error) {
      /* ignore quota / private mode */
    }
  }

  function postTelemetry(tel, gain) {
    if (!audio.worklet) return;
    const nowMs = performance.now();
    const prev = audio.lastPosted;
    const rpmChanged = !prev || Math.abs(prev.rpm - tel.rpm) >= 8;
    const loadChanged = !prev || Math.abs(prev.load - tel.load) >= 0.02;
    const gainChanged = !prev || prev.gain !== gain;
    const iceChanged = !prev || prev.ice !== tel.ice;
    if (!rpmChanged && !loadChanged && !gainChanged && !iceChanged && nowMs - audio.lastPostMs < 20) {
      return;
    }
    audio.lastPosted = { rpm: tel.rpm, load: tel.load, gain, ice: tel.ice };
    audio.lastPostMs = nowMs;
    audio.worklet.port.postMessage({
      rpm: tel.rpm,
      load: tel.load,
      gain,
      ice: tel.ice,
      clutch: tel.clutch,
      brake: tel.brake,
    });
    const param = audio.worklet.parameters?.get("rpm");
    if (param) param.value = tel.rpm;
  }

  function setMasterAudible(audible) {
    if (!audio.master || !audio.context) return;
    if (audio.masterAudible === audible) return;
    audio.masterAudible = audible;
    const now = audio.context.currentTime;
    audio.master.gain.setTargetAtTime(audible ? audio.volume : 0, now, audible ? 0.06 : 0.04);
  }

  async function ensureGraph() {
    if (audio.worklet) {
      if (audio.context.state === "suspended") await audio.context.resume();
      return true;
    }
    if (audio.starting) return audio.starting;

    audio.starting = (async () => {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const context = new AudioCtx({ latencyHint: "interactive" });
      await context.audioWorklet.addModule(WORKLET_URL);
      const worklet = new AudioWorkletNode(context, "kart-engine", {
        numberOfInputs: 0,
        numberOfOutputs: 1,
        outputChannelCount: [1],
      });
      const compressor = context.createDynamicsCompressor();
      compressor.threshold.value = -22;
      compressor.knee.value = 18;
      compressor.ratio.value = 2.4;
      compressor.attack.value = 0.008;
      compressor.release.value = 0.18;
      const master = context.createGain();
      master.gain.value = 0;
      worklet.connect(compressor);
      compressor.connect(master);
      master.connect(context.destination);
      audio.context = context;
      audio.worklet = worklet;
      audio.master = master;
      if (context.state === "suspended") await context.resume();
      return true;
    })();

    try {
      return await audio.starting;
    } catch (error) {
      console.warn("Engine audio failed to start", error);
      audio.worklet = null;
      return false;
    } finally {
      audio.starting = null;
    }
  }

  function applyTelemetry(tel, audible) {
    if (!audio.master || !audio.context) return;
    const live = Boolean(audible && tel.powered && tel.rpm >= 180);
    postTelemetry(tel, live ? 1 : 0);
    setMasterAudible(live);
  }

  function scheduleRpmUi() {
    const now = performance.now();
    if (now - audio.uiTimer < 80) return;
    audio.uiTimer = now;
    const rpmEl = document.getElementById("engine-audio-rpm");
    if (!rpmEl) return;
    if (audio.lastRpm >= 180) {
      rpmEl.textContent = `${Math.round(audio.lastRpm)} rpm · ${audio.lastFireHz.toFixed(1)} Hz`;
    } else {
      rpmEl.textContent = "no rpm";
    }
  }

  function update(sample, { audible = true } = {}) {
    if (sample) audio.pendingSample = sample;
    const tel = telemetryFromSample(sample);
    audio.lastRpm = tel.rpm;
    audio.lastFireHz = tel.fireHz;
    audio.lastSource = tel.source;
    scheduleRpmUi();
    if (!audio.enabled) return;
    if (!audio.worklet) {
      void ensureGraph().then((ready) => {
        if (ready) applyTelemetry(tel, audible);
      });
      return;
    }
    applyTelemetry(tel, audible);
  }

  function silence() {
    if (audio.worklet) {
      audio.worklet.port.postMessage({ rpm: audio.lastRpm, load: 0, gain: 0, ice: 1, clutch: 1, brake: 0 });
    }
    if (!audio.master || !audio.context) return;
    audio.masterAudible = null;
    audio.master.gain.setTargetAtTime(0, audio.context.currentTime, 0.04);
  }

  async function setEnabled(enabled) {
    audio.enabled = Boolean(enabled);
    savePrefs();
    syncUi();
    if (!audio.enabled) {
      silence();
      if (audio.context && audio.context.state === "running") {
        try {
          await audio.context.suspend();
        } catch (_error) {
          /* ignore */
        }
      }
      return;
    }
    await ensureGraph();
    if (audio.pendingSample) {
      await update(audio.pendingSample, { audible: true });
    }
  }

  function setVolume(volume) {
    audio.volume = clamp01(volume);
    savePrefs();
    if (audio.master && audio.enabled && audio.context && audio.masterAudible) {
      audio.masterAudible = null;
      setMasterAudible(true);
    }
    syncUi();
  }

  function syncUi() {
    const toggle = document.getElementById("btn-engine-audio");
    const slider = document.getElementById("engine-audio-volume");
    const readout = document.getElementById("engine-audio-volume-readout");
    const rpmEl = document.getElementById("engine-audio-rpm");
    if (toggle) {
      toggle.classList.toggle("active", audio.enabled);
      toggle.setAttribute("aria-pressed", audio.enabled ? "true" : "false");
      toggle.textContent = audio.enabled ? "Engine sound: ON" : "Engine sound: OFF";
    }
    if (rpmEl) {
      if (audio.lastRpm >= 180) {
        rpmEl.textContent = `${Math.round(audio.lastRpm)} rpm · ${audio.lastFireHz.toFixed(1)} Hz`;
      } else {
        rpmEl.textContent = "no rpm";
      }
    }
    if (slider && Number(slider.value) !== Math.round(audio.volume * 100)) {
      slider.value = String(Math.round(audio.volume * 100));
    }
    if (readout) readout.textContent = `${Math.round(audio.volume * 100)}%`;
    slider?.toggleAttribute("disabled", !audio.enabled);
  }

  function bindUi() {
    loadPrefs();
    syncUi();
    document.getElementById("btn-engine-audio")?.addEventListener("click", () => {
      void setEnabled(!audio.enabled);
    });
    document.getElementById("engine-audio-volume")?.addEventListener("input", (event) => {
      setVolume(Number(event.target.value) / 100);
    });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) silence();
    });
    if (audio.enabled) {
      const unlock = () => {
        void ensureGraph();
      };
      document.addEventListener("pointerdown", unlock, { once: true });
    }
  }

  window.KartEngineAudio = {
    update,
    silence,
    setEnabled,
    setVolume,
    bindUi,
    isEnabled: () => audio.enabled,
    telemetryFromSample,
    firingHzFromRpm,
    debug: () => ({
      rpm: audio.lastRpm,
      fireHz: audio.lastFireHz,
      source: audio.lastSource,
      enabled: audio.enabled,
    }),
  };
})();
