/**
 * RPM-locked kart engine / EV motor synth.
 *
 * ICE pitch is engine_rpm / 60 Hz (2-stroke, one combustion per rev).
 * RPM is smoothed per sample so telemetry steps do not zipper the pitch.
 */
class KartEngineProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.phase = 0;
    this.evPhase = 0;
    this.noise = 1;
    this.lp = 0;
    this.hp = 0;
    this.comb = new Float32Array(4096);
    this.combIndex = 0;
    this.overrun = 0;
    this.targetRpm = 0;
    this.rpm = 0;
    this.targetLoad = 0;
    this.load = 0;
    this.targetGain = 0;
    this.gain = 0;
    this.ice = 1;
    this.targetClutch = 1;
    this.clutch = 1;
    this.targetBrake = 0;
    this.brake = 0;
    this.delay = 120;
    this.idleLfo = 0;
    this.port.onmessage = (event) => {
      const data = event.data || {};
      if (typeof data.rpm === "number") this.targetRpm = data.rpm;
      if (typeof data.load === "number") this.targetLoad = data.load;
      if (typeof data.gain === "number") this.targetGain = data.gain;
      if (typeof data.ice === "number") this.ice = data.ice;
      if (typeof data.clutch === "number") this.targetClutch = data.clutch;
      if (typeof data.brake === "number") this.targetBrake = data.brake;
    };
  }

  static get parameterDescriptors() {
    return [
      { name: "rpm", defaultValue: 0, minValue: 0, maxValue: 20000, automationRate: "k-rate" },
    ];
  }

  _noise() {
    this.noise = (Math.imul(this.noise, 1664525) + 1013904223) | 0;
    return this.noise * (1 / 2147483648);
  }

  _polyblep(t, dt) {
    if (dt <= 0) return 0;
    if (t < dt) {
      const x = t / dt;
      return x + x - x * x - 1;
    }
    if (t > 1 - dt) {
      const x = (t - 1) / dt;
      return x * x + x + x + 1;
    }
    return 0;
  }

  process(_inputs, outputs, parameters) {
    const output = outputs[0][0];
    if (!output) return true;

    const paramRpm = parameters.rpm[0];
    if (this.targetRpm <= 0 && paramRpm) this.targetRpm = paramRpm;

    const sr = sampleRate;
    const smooth = 1 - Math.exp(-1 / (sr * 0.04));
    const gainSmooth = 1 - Math.exp(-1 / (sr * 0.02));
    const ice = this.ice >= 0.5;
    const len = this.comb.length;

    for (let i = 0; i < output.length; i += 1) {
      this.rpm += (this.targetRpm - this.rpm) * smooth;
      this.load += (this.targetLoad - this.load) * smooth;
      this.gain += (this.targetGain - this.gain) * gainSmooth;
      this.clutch += (this.targetClutch - this.clutch) * smooth;
      this.brake += (this.targetBrake - this.brake) * smooth;

      const rpm = Math.max(0, this.rpm);
      const load = Math.max(0, Math.min(1, this.load));
      const gain = Math.max(0, Math.min(1, this.gain));
      if (gain < 0.0008 || rpm < 180) {
        this.lp *= 0.995;
        output[i] = this.lp * 0.04;
        continue;
      }

      const fireHz = rpm / 60;
      const increment = fireHz / sr;
      this.idleLfo += 7.3 / sr;
      if (this.idleLfo >= 1) this.idleLfo -= 1;
      const idleWarp = rpm < 2800 ? 1 + Math.sin(this.idleLfo * Math.PI * 2) * 0.008 : 1;

      let sample = 0;
      if (ice) {
        this.phase += increment * idleWarp;
        this.phase -= Math.floor(this.phase);
        const saw = 2 * this.phase - 1 - this._polyblep(this.phase, increment);
        const twoPi = this.phase * Math.PI * 2;
        const tone =
          Math.sin(twoPi) * 0.42 +
          Math.sin(twoPi * 2) * 0.28 +
          Math.sin(twoPi * 3) * 0.16 +
          Math.sin(twoPi * 5) * 0.07 +
          saw * 0.12;
        const slip = 1 - Math.max(0, Math.min(1, this.clutch));
        const exhaust = this._noise() * (0.06 + load * 0.1 + slip * 0.08);
        const pop = Math.max(0, 1 - this.phase / 0.18);
        this.overrun += ((this.brake > 0.28 && load < 0.22 ? 0.35 : 0.04) - this.overrun) * 0.002;
        const crackle = this.overrun * pop * pop * this._noise() * 0.25;
        const dry = tone * (0.55 + load * 0.35) + exhaust + crackle;

        const targetDelay = Math.max(48, Math.min(len - 4, sr * (0.0028 + (1 - rpm / 14000) * 0.0012)));
        this.delay += (targetDelay - this.delay) * smooth;
        const delayInt = Math.floor(this.delay);
        const frac = this.delay - delayInt;
        const i1 = (this.combIndex + len - delayInt) % len;
        const i2 = (this.combIndex + len - delayInt - 1) % len;
        const delayed = this.comb[i1] * (1 - frac) + this.comb[i2] * frac;
        const wet = dry + delayed * 0.38;
        this.comb[this.combIndex] = wet;
        this.combIndex = (this.combIndex + 1) % len;
        sample = wet;
      } else {
        this.evPhase += increment;
        this.evPhase -= Math.floor(this.evPhase);
        const twoPi = this.evPhase * Math.PI * 2;
        const whine =
          Math.sin(twoPi * 4) * 0.42 +
          Math.sin(twoPi * 9) * 0.14 +
          Math.sin(twoPi * 17) * 0.05;
        const inverter = this._noise() * (0.015 + load * 0.04);
        sample = whine * (0.35 + load * 0.55) + inverter;
      }

      const cutoff = ice
        ? 700 + (rpm / 13500) * 6200 + load * 1400
        : 900 + (rpm / 8000) * 4200 + load * 800;
      const lpCoeff = 1 - Math.exp((-2 * Math.PI * cutoff) / sr);
      this.lp += lpCoeff * (sample - this.lp);
      this.hp += 0.035 * (this.lp - this.hp);
      const bright = this.lp - this.hp * 0.28;
      const idleDuck = rpm < 2200 ? 0.55 + (rpm / 2200) * 0.3 : 1;
      output[i] = bright * gain * idleDuck * 0.2;
    }
    return true;
  }
}

registerProcessor("kart-engine", KartEngineProcessor);
