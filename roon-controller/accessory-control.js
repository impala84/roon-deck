'use strict';

// Reuse the controller's Roon connection and subscription. Never touch ALSA.
class AccessoryControl {
  constructor({config, zone, output, zones, transport, delay = ms => new Promise(resolve => setTimeout(resolve, ms))}) {
    Object.assign(this, {config, zone, output, zones, transport, delay});
    this.busy = false;
  }

  command(invoke) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Roon control timed out.')), 1500);
      try {
        invoke((error, result) => {
          clearTimeout(timer);
          if (error) reject(new Error('Roon could not apply this control.'));
          else resolve(result);
        });
      } catch {
        clearTimeout(timer); reject(new Error('Roon control is unavailable.'));
      }
    });
  }

  resolve(config) {
    if (config.target === 'output') {
      for (const zone of this.zones()) {
        const output = (zone.outputs || []).find(item => item.output_id === config.output_id);
        if (output) return {zone, output};
      }
      throw new Error('The configured Roon Bridge output is unavailable.');
    }
    const zone = this.zone();
    if (!zone) throw new Error('The selected Roon zone is unavailable.');
    return {zone, output: this.output(zone)};
  }

  async run(event) {
    const config = this.config();
    if (!config.enabled) throw new Error('Surface Dial controls are disabled.');
    if (this.busy) throw new Error('Waiting for Roon volume confirmation.');
    if (!['rotate', 'single', 'double', 'long'].includes(event.kind)) throw new Error('Unknown Dial event.');
    const transport = this.transport();
    if (!transport) throw new Error('Roon is disconnected.');
    let {zone, output} = this.resolve(config);
    const action = event.kind === 'rotate' ? 'volume' : config[event.kind];
    if (action === 'none') return {ok: true};
    if (['playpause', 'next', 'previous'].includes(action)) {
      const allowed = action === 'next' ? zone.is_next_allowed : action === 'previous' ? zone.is_previous_allowed : zone.is_play_allowed || zone.is_pause_allowed;
      if (!allowed) throw new Error('This playback action is unavailable.');
      await this.command(callback => transport.control(zone, action, callback));
      return {ok: true};
    }
    this.busy = true;
    try {
      // Query the same Roon connection before computing an absolute value.
      // Never calculate from a stale subscription after a network interruption.
      const state = await this.command(callback => transport.get_zones(callback));
      const freshZone = state?.zones?.find(item => item.zone_id === zone.zone_id);
      const freshOutput = freshZone?.outputs?.find(item => item.output_id === output?.output_id);
      const current = this.resolve(this.config());
      if (!this.config().enabled || !freshZone || !freshOutput || current.zone.zone_id !== zone.zone_id || current.output?.output_id !== output?.output_id) throw new Error('The selected Roon zone changed.');
      zone = freshZone; output = freshOutput;
      const volume = output.volume;
      if (!volume || volume.type === 'fixed' || !Number.isFinite(volume.value)) throw new Error('This Roon output has fixed volume. Choose a variable-volume output in Roon.');
      if (action === 'mute') {
        await this.command(callback => transport.mute(output, volume.is_muted ? 'unmute' : 'mute', callback));
        return {ok: true};
      }
      if (action !== 'volume' || !Number.isInteger(event.steps) || event.steps === 0 || Math.abs(event.steps) > 24) throw new Error('Invalid Dial rotation.');
      const step = Number.isFinite(volume.step) && volume.step > 0 ? volume.step : volume.type === 'db' ? .5 : 1;
      // Sensitivity is applied by the Dial reader (degrees of turning per step), so each step here is one Roon step.
      const acceleration = config.acceleration && event.fast === true ? 2 : 1;
      if (step > (volume.type === 'db' ? 2 : 4)) throw new Error('This Roon output uses volume steps too large for safe Dial control.');
      const delta = Math.sign(event.steps) * Math.min(Math.abs(event.steps) * acceleration, 3, Math.floor((volume.type === 'db' ? 2 : 4) / step)) * step;
      const minimum = Number.isFinite(volume.min) ? volume.min : volume.type === 'db' ? -100 : 0;
      const maximum = Number.isFinite(volume.max) ? volume.max : 100;
      const limit = config.maximum_volume;
      const ceiling = Number.isFinite(limit) ? Math.min(maximum, limit) : maximum;
      const steppedCeiling = minimum + Math.floor((ceiling - minimum) / step + 1e-9) * step;
      // A lowered ceiling must not turn one downward step into a sudden jump.
      const value = delta > 0 ? Math.max(volume.value, Math.min(steppedCeiling, volume.value + delta)) : Math.max(minimum, volume.value + delta);
      if (value === volume.value) return {ok: true};
      if (value < minimum || value > maximum) throw new Error('Roon reported an invalid volume range.');
      await this.command(callback => transport.change_volume(output, 'absolute', value, callback));
      // Wait for the existing zone subscription. No queued stale volume writes,
      // optimistic UI state, or large replay when the server reconnects.
      for (let attempt = 0; attempt < 30; attempt++) {
        const current = this.resolve(config);
        if (current.zone.zone_id !== zone.zone_id || current.output?.output_id !== output.output_id) throw new Error('The selected Roon zone changed.');
        if (Math.abs((current.output.volume?.value ?? NaN) - value) < step / 2) return {ok: true};
        await this.delay(40);
      }
      throw new Error('Roon has not confirmed the volume change. Retry after the connection recovers.');
    } finally { this.busy = false; }
  }
}

module.exports = {AccessoryControl};
