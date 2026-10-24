'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, 'server.js'), 'utf8');
const start = source.indexOf('function rememberZoneOutputs(');
const end = source.indexOf('\nfunction resumeRoon', start);

function select(requested, entries) {
  const context = vm.createContext({configuredZoneName: () => requested, rememberedOutputIds: new Map(), zones: new Map(entries.map(zone => [zone.zone_id, zone]))});
  vm.runInContext(source.slice(start, end), context);
  return context.selectedZone();
}

test('an explicit missing zone never falls through to another player', () => {
  const zones = [{zone_id: 'other', display_name: 'NAD M33', state: 'playing'}];
  assert.equal(select('LS50W RoonDeck', zones), null);
});

test('a blank zone setting continues to follow active playback', () => {
  const zones = [
    {zone_id: 'idle', display_name: 'Kitchen', state: 'stopped'},
    {zone_id: 'playing', display_name: 'NAD M33', state: 'playing'}
  ];
  assert.equal(select('  ', zones).zone_id, 'playing');
});

test('a configured output follows its grouped zone', () => {
  const grouped = {
    zone_id: 'group', display_name: 'Study + Main', state: 'playing',
    outputs: [
      {output_id: 'study-output', display_name: 'Study'},
      {output_id: 'main-output', display_name: 'Main'}
    ]
  };
  assert.equal(select('Study', [grouped]).zone_id, 'group');
  assert.equal(select('Main', [grouped]).zone_id, 'group');
});

test('volume selection stays with the configured output inside a group', () => {
  const context = vm.createContext({configuredZoneName: () => 'Study', rememberedOutputIds: new Map()});
  vm.runInContext(source.slice(start, end), context);
  const grouped = {outputs: [
    {output_id: 'main-output', display_name: 'Main', volume: {value: 40}},
    {output_id: 'study-output', display_name: 'Study', volume: {value: 22}}
  ]};
  assert.equal(context.selectedOutput(grouped).output_id, 'study-output');
});

test('either merge direction follows the stable output behind a configured zone name', () => {
  const context = vm.createContext({configuredZoneName: () => 'Living Room', rememberedOutputIds: new Map(), zones: new Map()});
  vm.runInContext(source.slice(start, end), context);
  context.rememberZoneOutputs([{zone_id:'living', display_name:'Living Room', outputs:[{output_id:'living-output', display_name:'RoonDeck Living'}]}]);
  const grouped = {zone_id:'group', display_name:'Study + Living', state:'playing', outputs:[
    {output_id:'study-output', display_name:'Study speaker', volume:{value:31}},
    {output_id:'living-output', display_name:'RoonDeck Living', volume:{value:24}}
  ]};
  context.zones.set(grouped.zone_id, grouped);
  assert.equal(context.selectedZone().zone_id, 'group');
  assert.equal(context.selectedOutput(grouped).output_id, 'living-output');
});
