'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {BluOSClient, encodedBluOSUrl, normaliseAddress, parseInputs, parsePlayer, parseStatus, parseVolume} = require('./bluos-client');

test('normalises a player hostname onto the BluOS port', () => {
  assert.equal(normaliseAddress('nad-m33.local'), 'http://nad-m33.local:11000');
  assert.equal(normaliseAddress('http://10.0.0.8:11000'), 'http://10.0.0.8:11000');
});

test('parses BluOS player, status and volume responses', () => {
  assert.deepEqual(parsePlayer('<SyncStatus id="abc" name="Living Room" modelName="NAD M33" brand="NAD"/>'), {id: 'abc', name: 'Living Room', model: 'NAD M33', brand: 'NAD'});
  assert.deepEqual(parseVolume('<volume db="-35.0" mute="1">22</volume>'), {value: 22, muted: true, db: -35});
  const status = parseStatus('<status etag="17"><state>stream</state><service>Capture</service><title1>HDMI eARC</title1><title2>Television</title2><streamUrl>capture:arc-1</streamUrl><secs>12</secs><totlen>90</totlen></status>');
  assert.equal(status.etag, '17'); assert.equal(status.title, 'HDMI eARC'); assert.equal(status.stream_url, 'capture:arc-1'); assert.equal(status.duration, 90);
});

test('keeps only selectable capture inputs', () => {
  const inputs = parseInputs('<browse><item id="input1" inputType="arc"><text>HDMI eARC</text><url>capture:arc-1</url><service>Capture</service></item><item id="cloud"><text>Spotify</text><url>spotify:</url><service>Cloud</service></item></browse>');
  assert.deepEqual(inputs, [{id: 'input1', name: 'HDMI eARC', input_type: 'arc', url: 'capture:arc-1'}]);
});

test('parses compact RadioBrowse input items', () => {
  assert.deepEqual(parseInputs('<browse><item id="input2" inputType="analog" text="Record player" url="capture:analog-1"/></browse>'), [{id: 'input2', name: 'Record player', input_type: 'analog', url: 'capture:analog-1'}]);
});

test('sends an already encoded NAD capture URL exactly once', async () => {
  assert.equal(encodedBluOSUrl('Capture%3Ahw%3Aimxspdif%2C0%2F1%3Fid%3Dinput0'), 'Capture%3Ahw%3Aimxspdif%2C0%2F1%3Fid%3Dinput0');
  const client = new BluOSClient(() => ({enabled: true, address: 'nad.local'}), () => {});
  client.state.inputs = [{id: 'input0', url: 'Capture%3Ahw%3Aimxspdif%2C0%2F1%3Fid%3Dinput0'}];
  let requested = '';
  client.command = async path => { requested = path; };
  await client.selectInput('input0');
  assert.equal(requested, '/Play?url=Capture%3Ahw%3Aimxspdif%2C0%2F1%3Fid%3Dinput0');
});

test('connects for playback and volume when input browsing is unavailable', async () => {
  const client = new BluOSClient(() => ({enabled: true, address: 'nad.local'}), () => {});
  client.base = 'http://nad.local:11000';
  client.request = async path => {
    if (path === '/RadioBrowse?service=Capture') throw new Error('unsupported');
    if (path === '/SyncStatus') return '<SyncStatus id="abc" name="Living Room" modelName="NAD M33" brand="NAD"/>';
    if (path === '/Volume') return '<volume db="-35" mute="0">22</volume>';
    return '<status etag="17"><state>stream</state><title1>Roon</title1></status>';
  };
  client.poll = () => {};
  await client.connect(0);
  assert.equal(client.publicState().connected, true);
  assert.deepEqual(client.publicState().inputs, []);
  assert.equal(client.publicState().volume.value, 22);
});

test('disabling BluOS immediately clears previously selected inputs', async () => {
  let config = {enabled: true, address: 'nad.local'};
  const client = new BluOSClient(() => config, () => {});
  client.base = 'http://nad.local:11000';
  client.state = {enabled: true, connected: true, status: 'Connected', player: {name: 'NAD'},
    inputs: [{id: 'input0', name: 'TV'}], active_input: {id: 'input0', name: 'TV'},
    playback: {title: 'TV'}, volume: {value: 22}};
  config = {enabled: false, address: 'nad.local'};
  await client.refreshConfig();
  assert.deepEqual(client.publicState(), {enabled: false, connected: false, status: 'Disabled', player: null,
    inputs: [], active_input: null, playback: null, volume: null});
});
