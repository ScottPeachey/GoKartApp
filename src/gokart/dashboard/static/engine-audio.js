(() => {
  const STORAGE_ENABLED = "gokart.engineAudio.enabled";
  const STORAGE_VOLUME = "gokart.engineAudio.volume";
  const WORKLET_URL = "/static/engine-audio-worklet.js?v=1";

  const audio = {
    enabled: false,
    volume: 0.4,
    context: null,
    worklet: null,
    master: null,
    starting: null,
  };

  function clamp01(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0;
    return Math.max(0, Math.min(1, number));
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

  function setParam(name, value, seconds = 0.05) {
    const param = audio.worklet?.parameters?.get(name);
    if (!param || !audio.context) return;
    const now = audio.context.currentTime;
    param.setTargetAtTime(value, now, Math.max(0.01, seconds / 3));
  }

  async function ensureGraph() {
    if (audio.worklet) {
      if (audio.context.state === "suspended") await audio.context.resume();
      return true;
    }
    if (audio.starting) return audio.starting;

    audio.starting = (async () => {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const context = new AudioCtx();
      await context.audioWorklet.addModule(WORKLET_URL);
      const worklet = new AudioWorkletNode(context, "kart-engine", {
        numberOfInputs: 0,
        numberOfOutputs: 1,
        outputChannelCount: [1],
      });
      const compressor = context.createDynamicsCompressor();
      compressor.threshold.value = -18;
      compressor.knee.value = 12;
      compressor.ratio.value = 3.5;
      compressor.attack.value = 0.003;
      compressor.release.value = 0.12;
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

  function telemetryFromSample(sample) {
    const engineRpm = Number(sample?.engine_rpm);
    const motorRpm = Number(sample?.motor_rpm);
    const isIce = Number.isFinite(engineRpm) && engineRpm > 1;
    const rpm = isIce ? engineRpm : Number.isFinite(motorRpm) ? motorRpm : 0;
    const throttle = clamp01(sample?.throttle);
    const brake = clamp01(sample?.brake);
    const clutchLocked = Number(sample?.clutch_locked);
    const safety = String(sample?.safety_state || "");
    const powered = safety === "DRIVING" || safety === "ARMED" || safety === "READY";
    return {
      rpm: Math.max(0, rpm),
      load: throttle,
      ice: isIce ? 1 : 0,
      clutch: Number.isFinite(clutchLocked) ? clamp01(clutchLocked) : 1,
      brake,
      powered,
    };
  }

  async function update(sample, { audible = true } = {}) {
    if (!audio.enabled) return;
    const ready = await ensureGraph();
    if (!ready || !audio.master || !audio.context) return;

    const now = audio.context.currentTime;
    if (!audible || !sample) {
      audio.master.gain.setTargetAtTime(0, now, 0.04);
      return;
    }

    const tel = telemetryFromSample(sample);
    if (!tel.powered || tel.rpm < 180) {
      audio.master.gain.setTargetAtTime(0, now, 0.06);
      return;
    }

    setParam("rpm", tel.rpm, 0.06);
    setParam("load", tel.load, 0.04);
    setParam("ice", tel.ice, 0.02);
    setParam("clutch", tel.clutch, 0.08);
    setParam("brake", tel.brake, 0.05);
    setParam("gain", 1, 0.04);
    audio.master.gain.setTargetAtTime(audio.volume, now, 0.05);
  }

  function silence() {
    if (!audio.master || !audio.context) return;
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
  }

  function setVolume(volume) {
    audio.volume = clamp01(volume);
    savePrefs();
    if (audio.master && audio.enabled && audio.context) {
      audio.master.gain.setTargetAtTime(audio.volume, audio.context.currentTime, 0.05);
    }
    syncUi();
  }

  function syncUi() {
    const toggle = document.getElementById("btn-engine-audio");
    const slider = document.getElementById("engine-audio-volume");
    const readout = document.getElementById("engine-audio-volume-readout");
    if (toggle) {
      toggle.classList.toggle("active", audio.enabled);
      toggle.setAttribute("aria-pressed", audio.enabled ? "true" : "false");
      toggle.textContent = audio.enabled ? "Engine sound: ON" : "Engine sound: OFF";
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
  };
})();
