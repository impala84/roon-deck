'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {AccessoryControl} = require('./accessory-control');

function fixture(extra = {}) {
  const config = {enabled: true, target: 'selected', sensitivity: 'normal', acceleration: false, maximum_volume: null, single: 'playpause', double: 'next', long: 'mute', ...extra};
  const output = {output_id: 'dac', volume: {type: 'number', value: 40, min: 0, max: 100, step: 1}};
  const zone = {zone_id: 'room', outputs: [output], is_play_allowed: true, is_next_allowed: true};
  const calls = [];
  const transport = {
    get_zones(done) { done(false, {zones: [zone]}); },
    change_volume(out, mode, value, done) { calls.push({output: out.output_id, mode, value}); out.volume.value = value; done(); },
    mute(out, value, done) { calls.push({mute: value}); done(); },
    control(room, action, done) { calls.push({zone: room.zone_id, action}); done(); },
  };
  const adapter = new AccessoryControl({config: () => config, zone: () => zone, output: () => output, zones: () => [zone], transport: () => transport, delay: async () => {}});
  return {adapter, config, output, zone, calls, transport};
}
test('rotation changes Roon output volume and bounds a rapid burst', async () => {
  const f = fixture(); await f.adapter.run({kind: 'rotate', steps: 24, fast: true});
  assert.deepEqual(f.calls, [{output: 'dac', mode: 'absolute', value: 44}]);
});
test('maximum volume clamps increases without jumping down from an external higher volume', async () => {
  const f = fixture({maximum_volume: 41}); await f.adapter.run({kind: 'rotate', steps: 10}); assert.equal(f.output.volume.value, 41);
  f.output.volume.value = 60; await f.adapter.run({kind: 'rotate', steps: 1}); assert.equal(f.calls.length, 1);
  await f.adapter.run({kind: 'rotate', steps: -1}); assert.equal(f.output.volume.value, 58);
});
test('dB limits and increments use the Roon output scale', async () => {
  const f = fixture({maximum_volume: -20}); Object.assign(f.output.volume, {type: 'db', value: -21, min: -80, max: 0, step: .5});
  await f.adapter.run({kind: 'rotate', steps: 10}); assert.equal(f.output.volume.value, -20);
});
test('a fresh Roon query wins over an old subscription after interruption', async () => {
  const f = fixture();
  const fresh = {...f.output, volume: {...f.output.volume, value: 70}};
  f.transport.get_zones = done => done(false, {zones: [{...f.zone, outputs: [fresh]}]});
  f.transport.change_volume = (output, mode, value, done) => { f.calls.push({value}); f.output.volume.value = value; done(); };
  await f.adapter.run({kind: 'rotate', steps: 1});
  assert.equal(f.calls[0].value, 72);
});
test('a fractional ceiling rounds down to a supported volume step', async () => {
  const f = fixture({maximum_volume: 41.5});
  await f.adapter.run({kind: 'rotate', steps: 10}); assert.equal(f.output.volume.value, 41);
});
test('no control is applied while disabled, disconnected or fixed-volume', async () => {
  const f = fixture({enabled: false}); await assert.rejects(f.adapter.run({kind: 'single'}), /disabled/);
  f.config.enabled = true; f.adapter.transport = () => null; await assert.rejects(f.adapter.run({kind: 'single'}), /disconnected/);
  f.adapter.transport = () => f.transport; f.output.volume = null; await assert.rejects(f.adapter.run({kind: 'rotate', steps: 1}), /fixed volume/);
  assert.equal(f.calls.length, 0);
});
test('a missing configured Bridge never falls back to another room', async () => {
  const f = fixture({target: 'output', output_id: 'missing'});
  await assert.rejects(f.adapter.run({kind: 'single'}), /unavailable/); assert.equal(f.calls.length, 0);
});
test('press mappings reuse existing playback and mute actions', async () => {
  const f = fixture(); await f.adapter.run({kind: 'single'}); await f.adapter.run({kind: 'double'}); await f.adapter.run({kind: 'long'});
  assert.deepEqual(f.calls, [{zone: 'room', action: 'playpause'}, {zone: 'room', action: 'next'}, {mute: 'mute'}]);
});
test('pending rotations are rejected until Roon confirms its volume subscription', async () => {
  const f = fixture(); let release;
  f.transport.change_volume = (out, mode, value, done) => { release = () => { out.volume.value = value; done(); }; };
  const first = f.adapter.run({kind: 'rotate', steps: 1});
  await assert.rejects(f.adapter.run({kind: 'rotate', steps: 1}), /Waiting/);
  await Promise.resolve();
  release(); await first;
});
test('a missing volume acknowledgement stops the burst', async () => {
  const f = fixture(); f.transport.change_volume = (out, mode, value, done) => done();
  await assert.rejects(f.adapter.run({kind: 'rotate', steps: 1}), /not confirmed/);
});
test('switching zones during volume acknowledgement does not replay in the new room', async () => {
  const f = fixture(); f.transport.change_volume = (out, mode, value, done) => { f.adapter.zone = () => ({...f.zone, zone_id: 'other'}); done(); };
  await assert.rejects(f.adapter.run({kind: 'rotate', steps: 1}), /zone changed/);
});
test('invalid rotations and dangerously large output steps are rejected', async () => {
  const f = fixture();
  for (const steps of [0, 25, -25, NaN, 1.5, '1']) await assert.rejects(f.adapter.run({kind: 'rotate', steps}), /Invalid/);
  f.output.volume.step = 20; await assert.rejects(f.adapter.run({kind: 'rotate', steps: 1}), /too large/); assert.equal(f.calls.length, 0);
});
