/**
 * RPM-locked kart engine / EV motor synth.
 *
 * ICE: 2-stroke firing (one combustion per revolution) plus an exhaust comb,
 * matching Rotax 125 MAX character more closely than a 4-stroke car model.
 * EV: inverter/whine stack keyed to motor RPM.
 *
 * Inspired by physically informed engine synthesis (Baldan et al. 2015) and
 * browser work such as Antonio-R1/engine-sound-generator — this file is original.
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
  }

  static get parameterDescriptors() {
    return [
      { name: "rpm", defaultValue: 0, minValue: 0, maxValue: 20000, automationRate: "k-rate" },
      { name: "load", defaultValue: 0, minValue: 0, maxValue: 1, automationRate: "k-rate" },
      { name: "gain", defaultValue: 0, minValue: 0, maxValue: 1, automationRate: "k-rate" },
      { name: "ice", defaultValue: 1, minValue: 0, maxValue: 1, automationRate: "k-rate" },
      { name: "clutch", defaultValue: 1, minValue: 0, maxValue: 1, automationRate: "k-rate" },
      { name: "brake", defaultValue: 0, minValue: 0, maxValue: 1, automationRate: "k-rate" },
    ];
  }

  _noise() {
    this.noise = (Math.imul(this.noise, 1664525) + 1013904223) | 0;
    return this.noise * (1 / 2147483648);
  }

  process(_inputs, outputs, parameters) {
    const output = outputs[0][0];
    if (!output) return true;

    const rpm = Math.max(0, parameters.rpm[0] || 0);
    const load = Math.max(0, Math.min(1, parameters.load[0] || 0));
    const gain = Math.max(0, Math.min(1, parameters.gain[0] || 0));
    const ice = (parameters.ice[0] || 0) >= 0.5;
    const clutch = Math.max(0, Math.min(1, parameters.clutch[0] || 0));
    const brake = Math.max(0, Math.min(1, parameters.brake[0] || 0));

    if (gain < 0.0008 || rpm < 180) {
      output.fill(0);
      this.lp *= 0.9;
      return true;
    }

    const sr = sampleRate;
    const fireHz = rpm / 60;
    const increment = fireHz / sr;
    const slip = 1 - clutch;
    const cutoff = ice
      ? 480 + (rpm / 13500) * 7200 + load * 1600
      : 900 + (rpm / 8000) * 4200 + load * 800;
    const lpCoeff = 1 - Math.exp((-2 * Math.PI * cutoff) / sr);
    const delaySamples = Math.max(
      40,
      Math.min(this.comb.length - 2, Math.floor(sr * (0.0026 + (1 - rpm / 14000) * 0.0014))),
    );

    for (let i = 0; i < output.length; i += 1) {
      let sample = 0;
      if (ice) {
        this.phase += increment;
        if (this.phase >= 1) {
          this.phase -= 1;
          if (rpm < 2800) {
            this.phase += (this._noise() * 0.5) * 0.03;
            if (this.phase < 0) this.phase = 0;
          }
          this.overrun = brake > 0.28 && load < 0.22 ? 0.85 : 0.12;
        }
        const env = Math.exp(-this.phase * (10 + load * 14));
        const pop = (2 * this.phase - 1) * env;
        const rasp = this._noise() * env * (0.35 + load * 0.45 + slip * 0.35);
        const crackle = this.overrun * env * env * this._noise();
        this.overrun *= 0.9992;
        const dry = pop * (0.55 + load * 0.35) + rasp + crackle * 0.55;
        const readIndex = (this.combIndex + this.comb.length - delaySamples) % this.comb.length;
        const delayed = this.comb[readIndex];
        const wet = dry + delayed * 0.32;
        this.comb[this.combIndex] = wet;
        this.combIndex = (this.combIndex + 1) % this.comb.length;
        sample = wet;
      } else {
        this.evPhase += increment;
        if (this.evPhase >= 1) this.evPhase -= 1;
        const twoPi = this.evPhase * Math.PI * 2;
        const whine = Math.sin(twoPi * 4) * 0.42 + Math.sin(twoPi * 9) * 0.14 + Math.sin(twoPi * 17) * 0.05;
        const inverter = this._noise() * (0.02 + load * 0.05);
        sample = whine * (0.35 + load * 0.55) + inverter;
      }

      this.lp += lpCoeff * (sample - this.lp);
      this.hp += 0.04 * (this.lp - this.hp);
      const bright = this.lp - this.hp * 0.35;
      const idleDuck = rpm < 2200 ? 0.45 + (rpm / 2200) * 0.35 : 1;
      output[i] = bright * gain * idleDuck * 0.22;
    }
    return true;
  }
}

registerProcessor("kart-engine", KartEngineProcessor);
