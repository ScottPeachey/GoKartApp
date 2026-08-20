/**
 * RPM-locked kart engine / EV motor synth.
 *
 * ICE pitch is engine_rpm / 60 Hz (2-stroke). Tone is harmonic + resonant
 * formants. Unfiltered white noise and a long delay-line comb are avoided
 * because they sound breathy and like a loop restarting.
 */
class KartEngineProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.phase = 0;
    this.evPhase = 0;
    this.noise = 1;
    this.brown = 0;
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
    this.exLp = 0;
    this.exBp = 0;
    this.bodyLp = 0;
    this.bodyBp = 0;
    this.toneLp = 0;
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

  _svf(input, cutoffHz, q, lpKey, bpKey, sr) {
    const f = 2 * Math.sin(Math.PI * Math.max(20, Math.min(cutoffHz, sr * 0.45)) / sr);
    const damp = Math.min(0.9, 1 / Math.max(0.5, q));
    let lp = this[lpKey];
    let bp = this[bpKey];
    lp += f * bp;
    const hp = input - lp - damp * bp;
    bp += f * hp;
    lp += f * bp;
    this[lpKey] = lp;
    this[bpKey] = bp;
    return { lp, bp, hp };
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
    const smooth = 1 - Math.exp(-1 / (sr * 0.05));
    const gainSmooth = 1 - Math.exp(-1 / (sr * 0.03));
    const ice = this.ice >= 0.5;

    for (let i = 0; i < output.length; i += 1) {
      this.rpm += (this.targetRpm - this.rpm) * smooth;
      this.load += (this.targetLoad - this.load) * smooth;
      this.gain += (this.targetGain - this.gain) * gainSmooth;
      this.clutch += (this.targetClutch - this.clutch) * smooth;
      this.brake += (this.targetBrake - this.brake) * smooth;

      const rpm = Math.max(0, this.rpm);
      const load = Math.max(0, Math.min(1, this.load));
      const gain = Math.max(0, Math.min(1, this.gain));
      const fireHz = rpm / 60;
      const increment = Math.max(0, fireHz / sr);

      this.phase += increment;
      this.phase -= Math.floor(this.phase);
      this.evPhase += increment;
      this.evPhase -= Math.floor(this.evPhase);

      if (gain < 0.0008 || rpm < 180) {
        this.toneLp *= 0.995;
        output[i] = this.toneLp * 0.02;
        continue;
      }

      let sample = 0;
      if (ice) {
        const twoPi = this.phase * Math.PI * 2;
        const saw = 2 * this.phase - 1 - this._polyblep(this.phase, increment);
        const pulse = this.phase < 0.16 ? 1 - this.phase / 0.16 : 0;
        const tone =
          Math.sin(twoPi) * 0.62 +
          Math.sin(twoPi * 2) * 0.38 +
          Math.sin(twoPi * 3) * 0.18 +
          Math.sin(twoPi * 4) * 0.08 +
          saw * 0.07 +
          pulse * 0.12;
        const drive = Math.tanh(tone * (1.35 + load * 1.1));

        this.brown = Math.max(-1, Math.min(1, this.brown + this._noise() * 0.034));
        const exhaustCutoff = Math.min(sr * 0.42, 180 + fireHz * 2.2 + load * 400);
        const bodyCutoff = Math.min(sr * 0.42, 90 + fireHz * 1.05);
        const exhaust = this._svf(this.brown * (0.32 + load * 0.18), exhaustCutoff, 7.5, "exLp", "exBp", sr);
        const body = this._svf(drive, bodyCutoff, 3.2, "bodyLp", "bodyBp", sr);
        const slip = 1 - Math.max(0, Math.min(1, this.clutch));
        sample =
          drive * (0.72 + load * 0.18) +
          body.bp * 0.28 +
          exhaust.bp * (0.17 + slip * 0.08);
        if (this.brake > 0.3 && load < 0.2) {
          sample += pulse * this.brown * 0.07;
        }
      } else {
        const twoPi = this.evPhase * Math.PI * 2;
        sample =
          Math.sin(twoPi * 4) * 0.5 +
          Math.sin(twoPi * 9) * 0.16 +
          Math.sin(twoPi * 17) * 0.05;
        sample *= 0.4 + load * 0.5;
      }

      const toneCut = ice ? 1800 + (rpm / 13500) * 4200 + load * 900 : 2500 + load * 800;
      const lpCoeff = 1 - Math.exp((-2 * Math.PI * toneCut) / sr);
      this.toneLp += lpCoeff * (sample - this.toneLp);
      output[i] = this.toneLp * gain * 0.24;
    }
    return true;
  }
}

registerProcessor("kart-engine", KartEngineProcessor);
