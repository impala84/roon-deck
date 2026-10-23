'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, 'server.js'), 'utf8');
const start = source.indexOf('function selectedZone(');
const end = source.indexOf('\nfunction resumeRoon', start);

function select(requested, entries) {
  const context = vm.createContext({configuredZoneName: () => requested, zones: new Map(entries.map(zone => [zone.zone_id, zone]))});
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
