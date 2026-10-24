'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, 'server.js'), 'utf8');
const helperStart = source.indexOf('function rememberZoneOutputs(');
const helperEnd = source.indexOf('\nfunction selectedZone', helperStart);
const mergeStart = source.indexOf('function mergeZones(');
const mergeEnd = source.indexOf('\nfunction ensureDetails', mergeStart);
const zoneSource = source.slice(helperStart, helperEnd) + '\n' + source.slice(mergeStart, mergeEnd);
test('closing a zone subscription without data does not crash the controller', () => {
  let updates = 0;
  const context = vm.createContext({zones: new Map(), rememberedOutputIds: new Map(), ensureQueueSubscription() {}, ensureDetails() {}, broadcast() { updates++; }});
  vm.runInContext(zoneSource, context);
  for (const data of [undefined, null]) context.mergeZones('Unsubscribed', data);
  assert.equal(updates, 0);
  context.mergeZones('Subscribed', {zones: [{zone_id: 'one'}]});
  assert.equal(context.zones.size, 1);
  context.mergeZones('Changed', {zones_removed: ['one']});
  assert.equal(context.zones.size, 0);
  assert.equal(updates, 2);
});

test('a newly grouped playing zone retains the current track before Roon sends fresh metadata', () => {
  const context = vm.createContext({zones: new Map(), rememberedOutputIds: new Map(), ensureQueueSubscription() {}, ensureDetails() {}, broadcast() {}});
  vm.runInContext(zoneSource, context);
  context.mergeZones('Subscribed', {zones: [
    {zone_id:'living', display_name:'Living Room', state:'playing', outputs:[{output_id:'living-output'}], now_playing:{three_line:{line1:'Pet Sounds'}}},
    {zone_id:'study', display_name:'Study', state:'stopped', outputs:[{output_id:'study-output'}]}
  ]});
  context.mergeZones('Changed', {zones_added:[{zone_id:'group', display_name:'Living Room + Study', state:'playing', outputs:[{output_id:'living-output'},{output_id:'study-output'}]}], zones_removed:['living','study']});
  assert.equal(context.zones.get('group').now_playing.three_line.line1, 'Pet Sounds');
});
