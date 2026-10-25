'use strict';

const http = require('http');
const {execFile} = require('child_process');

const decode = value => String(value || '')
  .replace(/&#(\d+);/g, (_, code) => String.fromCodePoint(Number(code)))
  .replace(/&#x([0-9a-f]+);/gi, (_, code) => String.fromCodePoint(parseInt(code, 16)))
  .replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
const attribute = (source, name) => decode(source.match(new RegExp(`\\b${name}="([^"]*)"`, 'i'))?.[1] || '');
const element = (source, name) => decode(source.match(new RegExp(`<${name}(?:\\s[^>]*)?>([\\s\\S]*?)</${name}>`, 'i'))?.[1]?.replace(/<[^>]+>/g, '') || '').trim();
const number = value => Number.isFinite(Number(value)) ? Number(value) : null;
const encodedBluOSUrl = value => {
  const raw = String(value || '');
  try { return encodeURIComponent(decodeURIComponent(raw)); }
  catch { return encodeURIComponent(raw); }
};

function parseStatus(xml) {
  const root = xml.match(/<status\b([^>]*)>/i)?.[1] || '';
  return {
    etag: attribute(root, 'etag'), state: element(xml, 'state').toLowerCase(), service: element(xml, 'service'),
    title: element(xml, 'title1'), subtitle: element(xml, 'title2'), album: element(xml, 'title3'),
    stream_url: element(xml, 'streamUrl'), image: element(xml, 'image'), elapsed: number(element(xml, 'secs')),
    duration: number(element(xml, 'totlen')), format: element(xml, 'streamFormat')
  };
}

function parseVolume(xml) {
  const root = xml.match(/<volume\b([^>]*)>([^<]*)/i);
  return root ? {value: number(root[2]), muted: attribute(root[1], 'mute') === '1', db: number(attribute(root[1], 'db'))} : null;
}

function parsePlayer(xml) {
  const root = xml.match(/<SyncStatus\b([^>]*)>/i)?.[1] || '';
  return {id: attribute(root, 'id'), name: attribute(root, 'name'), model: attribute(root, 'modelName'), brand: attribute(root, 'brand')};
}

function parseInputs(xml) {
  const results = [];
  for (const match of xml.matchAll(/<(item|remoteitem)\b([^>]*?)(?:\/>|>([\s\S]*?)<\/\1>)/gi)) {
    const attrs = match[2]; const body = match[3] || '';
    const inputType = attribute(attrs, 'inputType') || attribute(attrs, 'inputtype');
    const id = attribute(attrs, 'id');
    const url = element(body, 'url') || attribute(attrs, 'url');
    if (!inputType && !/^input/i.test(id) && !/^(?:Capture|Input)$/i.test(element(body, 'service'))) continue;
    results.push({id: id || inputType || url, name: element(body, 'text') || element(body, 'title') || attribute(attrs, 'text') || inputType || 'Input', input_type: inputType, url});
  }
  return results.filter((item, index) => item.url && results.findIndex(other => other.url === item.url) === index);
}

function normaliseAddress(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  const candidate = /^https?:\/\//i.test(raw) ? raw : `http://${raw}`;
  const url = new URL(candidate);
  if (!url.port) url.port = '11000';
  url.pathname = ''; url.search = ''; url.hash = '';
  return url.toString().replace(/\/$/, '');
}

function discoverPlayers() {
  return new Promise(resolve => {
    execFile('avahi-browse', ['-rtp', '_musc._tcp'], {timeout: 5000}, (error, stdout) => {
      if (error && !stdout) return resolve([]);
      const players = [];
      for (const line of String(stdout).split('\n')) {
        if (!line.startsWith('=')) continue;
        const fields = line.split(';');
        if (fields.length < 9 || fields[2] !== 'IPv4') continue;
        const address = fields[7]; const port = Number(fields[8]) || 11000;
        const item = {name: fields[3].replace(/\\(\d{3})/g, (_, octal) => String.fromCharCode(Number(octal))), address: `http://${address}:${port}`};
        if (!players.some(player => player.address === item.address)) players.push(item);
      }
      resolve(players);
    });
  });
}

class BluOSClient {
  constructor(getConfig, changed) {
    this.getConfig = getConfig; this.changed = changed; this.generation = 0; this.base = ''; this.timer = null;
    this.state = {enabled: false, connected: false, status: 'Disabled', player: null, inputs: [], active_input: null, playback: null, volume: null};
  }
  publicState() { return this.state; }
  async refreshConfig() {
    const config = this.getConfig(); const base = config.enabled ? normaliseAddress(config.address) : '';
    if (base === this.base && Boolean(config.enabled) === this.state.enabled) return;
    this.base = base; this.generation += 1; clearTimeout(this.timer);
    this.state = config.enabled
      ? {...this.state, enabled: true, connected: false, status: base ? 'Connecting' : 'Select a player'}
      : {enabled: false, connected: false, status: 'Disabled', player: null, inputs: [], active_input: null, playback: null, volume: null};
    this.changed();
    if (base) this.connect(this.generation);
  }
  request(path, timeout = 5000) {
    return new Promise((resolve, reject) => {
      const request = http.get(`${this.base}${path}`, {timeout}, response => {
        let data = ''; response.setEncoding('utf8'); response.on('data', chunk => data += chunk);
        response.on('end', () => response.statusCode >= 200 && response.statusCode < 300 ? resolve(data) : reject(new Error(`BluOS HTTP ${response.statusCode}`)));
      });
      request.on('timeout', () => request.destroy(new Error('BluOS request timed out'))); request.on('error', reject);
    });
  }
  activeInput(status, inputs) {
    const target = String(status.stream_url || '').toLowerCase();
    return inputs.find(input => target && String(input.url).toLowerCase() === target) ||
      inputs.find(input => [status.title, status.subtitle, status.service].some(value => value && value.toLowerCase() === input.name.toLowerCase())) || null;
  }
  async connect(generation) {
    try {
      const [syncXml, inputXml, volumeXml, statusXml] = await Promise.all([
        this.request('/SyncStatus'),
        // Some firmware does not expose Capture browsing even though status
        // and volume control are healthy.
        this.request('/RadioBrowse?service=Capture').catch(() => ''),
        this.request('/Volume'), this.request('/Status')
      ]);
      if (generation !== this.generation) return;
      const inputs = parseInputs(inputXml); const playback = parseStatus(statusXml);
      this.state = {enabled: true, connected: true, status: 'Connected', player: parsePlayer(syncXml), inputs,
        active_input: this.activeInput(playback, inputs), playback, volume: parseVolume(volumeXml)};
      this.changed(); this.poll(generation, playback.etag);
    } catch (error) { this.failed(generation, error); }
  }
  async poll(generation, etag) {
    if (generation !== this.generation || !this.base) return;
    try {
      const suffix = etag ? `&etag=${encodeURIComponent(etag)}` : '';
      const statusXml = await this.request(`/Status?timeout=60${suffix}`, 70000);
      const [volumeXml] = await Promise.all([this.request('/Volume')]);
      if (generation !== this.generation) return;
      const playback = parseStatus(statusXml);
      this.state = {...this.state, connected: true, status: 'Connected', playback, volume: parseVolume(volumeXml), active_input: this.activeInput(playback, this.state.inputs)};
      this.changed(); this.poll(generation, playback.etag || etag);
    } catch (error) { this.failed(generation, error); }
  }
  failed(generation, error) {
    if (generation !== this.generation) return;
    this.state = {...this.state, connected: false, status: 'Unavailable', error: error.message}; this.changed();
    this.timer = setTimeout(() => this.connect(generation), 5000);
  }
  async command(path) { const result = await this.request(path); setTimeout(() => this.connect(++this.generation), 100); return result; }
  selectInput(inputId) {
    const input = this.state.inputs.find(item => String(item.id) === String(inputId));
    if (!input) throw new Error('Input is no longer available');
    return this.command(`/Play?url=${encodedBluOSUrl(input.url)}`);
  }
  setVolume(value) { return this.command(`/Volume?level=${encodeURIComponent(Math.max(0, Math.min(100, Number(value))))}`); }
  toggleMute() { return this.command(`/Volume?mute=${this.state.volume?.muted ? 0 : 1}`); }
}

module.exports = {BluOSClient, discoverPlayers, encodedBluOSUrl, normaliseAddress, parseInputs, parsePlayer, parseStatus, parseVolume};
