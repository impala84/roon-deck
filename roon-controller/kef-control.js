'use strict';

// Use the existing Roon connection; never guess a target from a room name.
class KefRoonControl {
  constructor({zones, transport, delay = ms => new Promise(resolve => setTimeout(resolve, ms))}) {
    Object.assign(this, {zones, transport, delay});
  }
  output(id) {
    if (typeof id !== 'string' || !id || id.length > 128) throw new Error('Choose the KEF Roon output.');
    const output = this.zones().flatMap(zone => zone.outputs || []).find(output => output.output_id === id);
    if (!output) throw new Error('The configured KEF Roon output is unavailable.');
    return output;
  }
  status(id) {
    const output = this.output(id), controls = output.source_controls || [];
    if (!controls.length) throw new Error('This Roon output does not report power controls.');
    const selected = controls.some(control => control.status === 'selected');
    const standby = controls.every(control => control.status === 'standby');
    const volume = output.volume;
    return {connected: true, powered: !standby, input: selected ? 'wifi' : 'unknown',
      volume: volume?.type === 'number' ? volume.value : null, muted: !!volume?.is_muted,
      control_path: 'roon', direct_inputs_available: false};
  }
  invoke(fn) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Roon KEF control timed out.')), 2000);
      try { fn(error => {clearTimeout(timer); error ? reject(new Error(`Roon KEF control failed: ${error}`)) : resolve();}); }
      catch (error) {clearTimeout(timer); reject(error);}
    });
  }
  async command(id, action, value, maximum) {
    const output = this.output(id), transport = this.transport();
    if (!transport) throw new Error('Roon is disconnected.');
    this.status(id);
    let expected;
    if ((action === 'power' && value === true) || (action === 'input' && value === 'wifi')) {
      await this.invoke(done => transport.convenience_switch(output, {}, done));
      expected = state => state.powered && state.input === 'wifi';
    } else if (action === 'power' && value === false) {
      if (!(output.source_controls || []).some(control => control.supports_standby)) throw new Error('This KEF output does not support standby through Roon.');
      await this.invoke(done => transport.standby(output, {}, done));
      expected = state => !state.powered;
    } else if (['volume', 'volume_delta', 'mute'].includes(action)) {
      const volume = output.volume;
      if (volume?.type !== 'number' || volume.min !== 0 || volume.max !== 100 || !Number.isFinite(volume.value)) throw new Error('KEF needs a 0–100 device-volume control in Roon.');
      if (action === 'mute') {
        const muted = !volume.is_muted;
        await this.invoke(done => transport.mute(output, muted ? 'mute' : 'unmute', done));
        expected = state => state.muted === muted;
      } else {
        if (!Number.isInteger(value) || Math.abs(value) > 100 || !Number.isInteger(maximum) || maximum < 0 || maximum > 100) throw new Error('Invalid KEF volume.');
        const ceiling = Math.min(maximum, Number.isFinite(volume.hard_limit_max) ? volume.hard_limit_max : 100);
        const target = Math.max(0, Math.min(ceiling, action === 'volume' ? value : volume.value + value));
        await this.invoke(done => transport.change_volume(output, 'absolute', target, done));
        expected = state => state.volume === target;
      }
    } else throw new Error('Roon can select Wi-Fi; other KEF inputs need the direct speaker connection.');
    for (let attempt = 0; attempt < 20; attempt++) {
      const state = this.status(id);
      if (expected(state)) return state;
      await this.delay(100);
    }
    throw new Error('Roon has not confirmed the KEF change.');
  }
}
module.exports = {KefRoonControl};
