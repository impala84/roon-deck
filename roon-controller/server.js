'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const RoonApi = require('node-roon-api');
const RoonApiBrowse = require('node-roon-api-browse');
const RoonApiImage = require('node-roon-api-image');
const RoonApiStatus = require('node-roon-api-status');
const RoonApiTransport = require('node-roon-api-transport');
const {publicQueueItems, updateQueueState} = require('./queue-state');
const {displayArtist} = require('./artist-name');
const {playingMetadata, loadDetails, loadArtistProfile, loadAlbumNotes} = require('./details-state');
const artistProfileCache = new Map();
const {BluOSClient, discoverPlayers} = require('./bluos-client');
const {BrowseManager} = require('./browse-state');
const {DiscoveryManager} = require('./discovery-state');
const {openDiscovery} = require('./discovery-bridge');
const {brokerWireId} = require('../tools/discovery-wire.cjs');
const discovery = new DiscoveryManager();
const {LibraryManager}=require('./library-state');
const library=new LibraryManager({changed:()=>broadcast()});
const discoveryCores = new Map();
function discoveryTarget() {
  const host = core?.moo?.transport?.host;
  const found = discoveryCores.get(host);
  discovery.setTarget(core && found ? {...found,coreId:core.core_id} : null);
  library.setTarget(core && found ? {...found,coreId:core.core_id} : null);
}

const port = Number(process.env.PORT || 8766);
const staticDir = path.join(__dirname, 'static');
let buildRevision = '';
try { buildRevision = fs.readFileSync(path.join(__dirname, '..', '.source-commit'), 'utf8').trim(); } catch (_) { /* Development checkout. */ }
let core = null;
let transport = null;
let imageService = null;
let browseService = null;
let zones = new Map();
const rememberedOutputIds = new Map();
let queueItems = [];
let queueHistory = [];
let queueZoneId = null;
let queueSubscription = null;
let details = {status: 'unavailable'};
let detailsKey = '';
let detailsRequest = 0;
let detailsRetryCount = 0;
const detailsCache = new Map();
const albumNotesCache = new Map();
const listeners = new Set();
const imageCache = new Map();
const QUEUE_LIMIT = 100;
const IMAGE_CACHE_LIMIT = 64;
let runtimeConfig = null;
let runtimeConfigExpires = 0;

function configuredRuntime() {
  const now = Date.now();
  if (runtimeConfig && now < runtimeConfigExpires) return runtimeConfig;
  const defaults = {zoneName: process.env.ROON_ZONE_NAME || '', displayName: 'Roon', nowPlayingName: 'Now Playing', queueName: 'Queue', queueEnabled: true, browserEnabled: true, bluos: {enabled: false, address: '', visibleInputs: [], inputNames: []}};
  try {
    const text = fs.readFileSync(process.env.CONFIG_PATH || '/etc/pi-bus-time-display/config.toml', 'utf8');
    const stringValue = name => JSON.parse(text.match(new RegExp(`^${name}\\s*=\\s*("(?:[^"\\\\]|\\\\.)*")`, 'm'))?.[1] || '""');
    const arrayValue = name => JSON.parse(text.match(new RegExp(`^${name}\\s*=\\s*(\\[[^\\n]*\\])`, 'm'))?.[1] || '[]');
    runtimeConfig = {
      zoneName: process.env.ROON_ZONE_NAME || stringValue('roon_zone_name'),
      displayName: stringValue('roon_display_name') || 'Roon',
      displayTheme: stringValue('display_theme') === 'roon' ? 'roon' : 'fresh-mint',
      busEnabled: text.match(/^bus_enabled\s*=\s*(true|false)/m)?.[1] !== 'false',
      nowPlayingName: stringValue('roon_now_playing_name') || 'Now Playing',
      queueName: stringValue('roon_queue_name') || 'Queue',
      queueEnabled: text.match(/^roon_show_queue\s*=\s*(true|false)/m)?.[1] !== 'false',
      browserEnabled: text.match(/^roon_show_browser\s*=\s*(true|false)/m)?.[1] !== 'false',
      bluos: {
        enabled: text.match(/^bluos_enabled\s*=\s*(true|false)/m)?.[1] === 'true',
        address: stringValue('bluos_player_address'),
        visibleInputs: arrayValue('bluos_visible_inputs'),
        inputNames: arrayValue('bluos_input_names')
      }
    };
  } catch (_) { runtimeConfig = defaults; }
  runtimeConfigExpires = now + 1000;
  return runtimeConfig;
}

function configuredZoneName() {
  return configuredRuntime().zoneName;
}

function configuredQueueEnabled() {
  return configuredRuntime().queueEnabled;
}

function configuredBluOS() {
  return configuredRuntime().bluos;
}

function publicAmplifierState() {
  const state = bluos.publicState(); const config = configuredBluOS(); const visible = new Set(config.visibleInputs || []);
  if (!config.enabled) return {enabled: false, connected: false, status: 'Disabled', player: null, inputs: [], active_input: null, playback: null, volume: null};
  const aliases = new Map((config.inputNames || []).map(item => { const split = String(item).indexOf('='); return split < 0 ? [item, ''] : [item.slice(0, split), item.slice(split + 1)]; }));
  const named = input => input ? {...input, name: aliases.get(String(input.id)) || input.name} : null;
  return {...state, inputs: (visible.size ? state.inputs.filter(input => visible.has(String(input.id))) : state.inputs).map(named), active_input: named(state.active_input)};
}

function rememberZoneOutputs(entries) {
  for (const zone of entries || []) {
    const outputs = zone?.outputs || [];
    for (const output of outputs) if (output?.display_name && output?.output_id) rememberedOutputIds.set(output.display_name, output.output_id);
    if (zone?.display_name && outputs.length === 1 && outputs[0]?.output_id) rememberedOutputIds.set(zone.display_name, outputs[0].output_id);
  }
}

function carryGroupedPlayback(previousZones) {
  for (const [zoneId, zone] of zones) {
    if (zone?.state !== 'playing' || zone.now_playing) continue;
    const outputIds = new Set((zone.outputs || []).map(output => output?.output_id).filter(Boolean));
    const previous = (previousZones || []).find(candidate => candidate?.now_playing && candidate.state === 'playing' &&
      (candidate.outputs || []).some(output => outputIds.has(output?.output_id)));
    if (previous) zones.set(zoneId, {...previous, ...zone, now_playing: previous.now_playing,
      seek_position: zone.seek_position ?? previous.seek_position ?? previous.now_playing?.seek_position ?? 0});
  }
}

function selectedZone() {
  const requested = configuredZoneName().trim();
  const all = [...zones.values()];
  const remembered = rememberedOutputIds.get(requested);
  if (requested) return all.find(zone => zone.display_name === requested ||
    (zone.outputs || []).some(output => output.display_name === requested || (remembered && output.output_id === remembered))) || null;
  return all.find(zone => zone.state === 'playing') || all[0] || null;
}

function selectedOutput(zone) {
  const outputs = zone?.outputs || [];
  const requested = configuredZoneName().trim();
  const remembered = rememberedOutputIds.get(requested);
  return (requested ? outputs.find(output => output.display_name === requested || (remembered && output.output_id === remembered)) : null) ||
    outputs.find(output => output.volume) || outputs[0] || null;
}

function resumeRoon(zone) {
  const play = () => transport.control(zone, 'play', () => {});
  // BluOS can leave Roon reporting "playing" after a physical input takes over.
  // A deliberate pause/play edge makes the endpoint reclaim the audio source.
  if (zone.state === 'playing') transport.control(zone, 'pause', () => setTimeout(play, 160));
  else play();
}

function publicState() {
  bluos.refreshConfig().catch(() => {});
  const configured = configuredRuntime();
  const zone = selectedZone();
  const labels = {display: configured.displayName, now_playing: configured.nowPlayingName, queue: configured.queueName, browse: 'Browse'};
  labels.display_theme = configured.displayTheme || 'fresh-mint';
  labels.bus_enabled = configured.busEnabled !== false;
  if (!zone) {
    const availableZones = [...zones.values()].map(item => ({id: item.zone_id, name: item.display_name}));
    const unavailable = core && configured.zoneName.trim() ? {
      id: null, name: configured.zoneName.trim(), state: 'unavailable', available: false,
      now_playing: null, seek_position: 0, can_previous: false, can_next: false,
      can_play: false, can_pause: false, can_seek: false, output: null
    } : null;
    return {connected: Boolean(core), authorised: Boolean(core), zones: availableZones, zone: unavailable, labels, browser_enabled: configured.browserEnabled, queue: {status: 'unavailable', items: []}, details: {status: 'unavailable'}, amplifier: publicAmplifierState()};
  }
  const output = selectedOutput(zone);
  return {
    connected: true,
    authorised: true,
    zones: [...zones.values()].map(item => ({id: item.zone_id, name: item.display_name})),
    zone: {
      id: zone.zone_id, name: zone.display_name, state: zone.state,
      now_playing: zone.now_playing ? {...zone.now_playing, display_artist: displayArtist(zone.now_playing)} : null,
      seek_position: zone.seek_position ?? zone.now_playing?.seek_position ?? 0,
      can_previous: Boolean(zone.is_previous_allowed), can_next: Boolean(zone.is_next_allowed),
      can_play: Boolean(zone.is_play_allowed), can_pause: Boolean(zone.is_pause_allowed),
      can_seek: Boolean(zone.is_seek_allowed), output: output ? {id: output.output_id, volume: output.volume || null} : null
    },
    queue: {status: !configuredQueueEnabled() ? 'disabled' : (queueZoneId === zone.zone_id ? 'ready' : 'loading'), items: queueZoneId === zone.zone_id ? publicQueueItems(queueItems, queueHistory) : []},
    labels, browser_enabled: configured.browserEnabled, details: {...details,...library.getLibraryStatus(zone)}, amplifier: publicAmplifierState()
  };
}

function broadcast() {
  const message = `data: ${JSON.stringify(publicState())}\n\n`;
  for (const response of listeners) response.write(message);
}

const bluos = new BluOSClient(configuredBluOS, () => broadcast());
const browser = new BrowseManager(() => browseService, () => selectedZone());
bluos.refreshConfig().catch(() => {});

function mergeZones(command, data) {
  // The Roon SDK closes subscriptions without a payload on disconnect.
  // Ignore that notification; core_unpaired owns connection-state cleanup.
  if (!data || typeof data !== 'object') return;
  const previousZones = [...zones.values()];
  rememberZoneOutputs(previousZones);
  rememberZoneOutputs(data.zones || []);
  rememberZoneOutputs(data.zones_added || []);
  rememberZoneOutputs(data.zones_changed || []);
  if (command === 'Subscribed') zones = new Map((data.zones || []).map(zone => [zone.zone_id, zone]));
  for (const zone of data.zones_added || []) zones.set(zone.zone_id, zone);
  for (const zone of data.zones_changed || []) zones.set(zone.zone_id, {...zones.get(zone.zone_id), ...zone});
  for (const zone of data.zones_removed || []) zones.delete(typeof zone === 'string' ? zone : zone.zone_id);
  carryGroupedPlayback(previousZones);
  ensureQueueSubscription();
  ensureDetails();
  broadcast();
}

function ensureDetails(force = false) {
  const zone = selectedZone();
  const metadata = playingMetadata(zone);
  const nextKey = zone ? `${zone.zone_id}|${metadata.key}` : '';
  if (!zone || !metadata.key) {
    detailsKey = nextKey; details = {status: 'unavailable', ...metadata}; return;
  }
  if (nextKey === detailsKey && !force) return;
  if (nextKey !== detailsKey) detailsRetryCount = 0;
  detailsKey = nextKey;
  const cached = detailsCache.get(nextKey);
  if (cached) { details = cached; return; }
  details = {status: 'loading', ...metadata, album_image_key: metadata.image_key, artist_image_key: null, subtitle: '', tracks: []};
  const requestId = ++detailsRequest;
  loadDetails(browseService, zone).then(result => {
    if (requestId !== detailsRequest || detailsKey !== nextKey) return;
    details = result;
    if (result.metadata_retryable) retryDetails(nextKey);
    else detailsCache.set(nextKey, result);
    while (detailsCache.size > 24) detailsCache.delete(detailsCache.keys().next().value);
    broadcast();
  }).catch(() => {
    if (requestId !== detailsRequest || detailsKey !== nextKey) return;
    details = {...details, status: 'ready'}; retryDetails(nextKey); broadcast();
  });
}

function retryDetails(key) {
  if (detailsRetryCount >= 2) return;
  detailsRetryCount += 1;
  const requestId = detailsRequest;
  setTimeout(() => { if (detailsKey === key && detailsRequest === requestId) ensureDetails(true); }, 30000).unref();
}

function stopQueueSubscription() {
  const subscription = queueSubscription;
  queueSubscription = null;
  queueZoneId = null;
  queueItems = [];
  queueHistory = [];
  if (subscription?.unsubscribe) {
    try { subscription.unsubscribe(() => {}); } catch (_) {}
  }
}

function ensureQueueSubscription() {
  const zone = selectedZone();
  if (!transport || !zone || !configuredQueueEnabled()) {
    if (queueSubscription) stopQueueSubscription();
    return;
  }
  if (queueSubscription && queueZoneId === zone.zone_id) return;
  stopQueueSubscription();
  const subscribedZoneId = zone.zone_id;
  queueZoneId = subscribedZoneId;
  queueSubscription = transport.subscribe_queue(zone, QUEUE_LIMIT, (command, data) => {
    if (queueZoneId !== subscribedZoneId) return;
    const next = updateQueueState(command, data, queueItems, queueHistory, QUEUE_LIMIT);
    queueItems = next.items; queueHistory = next.history;
    broadcast();
  });
}

function cachedImage(key, size, callback) {
  const cacheKey = `${key}:${size}`;
  const cached = imageCache.get(cacheKey);
  if (cached) {
    imageCache.delete(cacheKey); imageCache.set(cacheKey, cached);
    return callback(null, cached.type, cached.data);
  }
  imageService.get_image(key, {scale: 'fit', width: size, height: size}, (error, type, data) => {
    if (!error && data) {
      imageCache.set(cacheKey, {type: type || 'image/jpeg', data});
      while (imageCache.size > IMAGE_CACHE_LIMIT) imageCache.delete(imageCache.keys().next().value);
    }
    callback(error, type, data);
  });
}

const roon = new RoonApi({
  extension_id: 'com.impala84.pi-bus-time-display',
  display_name: 'RoonDeck',
  display_version: require('./package.json').version,
  publisher: 'RoonDeck',
  email: 'noreply@example.invalid',
  website: 'https://github.com/impala84/roon-deck',
  core_paired: pairedCore => {
    core = pairedCore;
    discoveryTarget();
    transport = core.services.RoonApiTransport;
    imageService = core.services.RoonApiImage;
    browseService = core.services.RoonApiBrowse;
    status.set_status('Connected to Roon; touchscreen controller ready', false);
    transport.subscribe_zones(mergeZones);
    broadcast();
  },
  core_unpaired: () => {
    stopQueueSubscription();
    browser.clear();
    core = transport = imageService = browseService = null;
    discovery.setTarget(null);
    library.setTarget(null);
    details = {status: 'unavailable'}; detailsKey = ''; detailsRequest += 1;
    zones.clear();
    rememberedOutputIds.clear();
    status.set_status('Waiting for Roon authorisation', false);
    broadcast();
  }
});
const status = new RoonApiStatus(roon);
roon.init_services({required_services: [RoonApiTransport, RoonApiImage, RoonApiBrowse], provided_services: [status]});
status.set_status('Waiting for Roon authorisation', false);
roon.start_discovery();
roon._sood.on('message', message => {
  if (message.props.service_id !== '00720724-5143-4a9b-abac-0e50cba674bb') return;
  try {
    const local = Object.values(require('node:os').networkInterfaces()).flat().some(address=>address?.address===message.from.ip);
    const host = local ? '127.0.0.1' : message.from.ip;
    const httpPort = Number(message.props.http_port);
    if (!Number.isInteger(httpPort) || httpPort < 1 || httpPort > 65535) return;
    discoveryCores.set(host,{host,httpPort,brokerId:brokerWireId(message.props.unique_id)});
    if(discoveryCores.size>16) discoveryCores.delete(discoveryCores.keys().next().value);
    discoveryTarget();
  } catch { /* Malformed announcements must not affect official playback. */ }
});

function json(response, statusCode, body) {
  const data = Buffer.from(JSON.stringify(body));
  response.writeHead(statusCode, {'Content-Type': 'application/json', 'Content-Length': data.length, 'Cache-Control': 'no-store'});
  response.end(data);
}

function body(request) {
  return new Promise((resolve, reject) => {
    let data = '';
    request.on('data', chunk => { data += chunk; if (data.length > 4096) reject(new Error('Request too large')); });
    request.on('end', () => { try { resolve(data ? JSON.parse(data) : {}); } catch (error) { reject(error); } });
  });
}

function serveStatic(request, response) {
  const names = {'/': 'index.html', '/icons.js': 'icons.js', '/app.js': 'app.js', '/discovery.js': 'discovery.js', '/discovery.css': 'discovery.css', '/style.css': 'style.css', '/refinements.css': 'refinements.css', '/favicon.svg': 'favicon.svg', '/favicon-roon.svg': 'favicon-roon.svg'};
  const pathname = new URL(request.url, 'http://localhost').pathname;
  const allowedIcons = new Set(['music','jazz','classical','electronic','rock','stage','avant','folk','country','blues','rap','rb','reggae','latin','world','easy','vocal','ambient','holiday','children','religious','comedy','search','playlist','artist','album','folder','settings','clock','play','pause','previous','next','add','remove','back','forward','close','refresh','shuffle','heart','fan','light','switch','switchon','brightness','home','bus','discover','overflow','power','orientation','check','erase']);
  const icon = /^\/icons\/([a-z]+)-symbolic\.svg$/.exec(pathname);
  const name = names[pathname] || (icon && allowedIcons.has(icon[1]) ? pathname.slice(1) : null);
  if (!name) return false;
  const types = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml'};
  const data = fs.readFileSync(path.join(staticDir, name));
  response.writeHead(200, {'Content-Type': types[path.extname(name)], 'Content-Length': data.length, 'Cache-Control': 'no-store, must-revalidate'});
  response.end(data);
  return true;
}

http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url, 'http://localhost');
    if (request.method === 'GET' && url.pathname === '/api/build') return json(response, 200, {revision: buildRevision});
    if (request.method === 'GET' && url.pathname === '/api/artist') {
      const name = String(url.searchParams.get('name') || '').trim().slice(0, 200);
      if (!name) return json(response, 400, {error:'Artist name required'});
      if (!artistProfileCache.has(name)) {
        const pending = loadArtistProfile(name).then(profile => {
          if (!profile.writeup) artistProfileCache.delete(name);
          return profile;
        }).catch(()=>{
          artistProfileCache.delete(name);
          return {name,writeup:'',source:''};
        });
        artistProfileCache.set(name, pending);
        while (artistProfileCache.size > 64) artistProfileCache.delete(artistProfileCache.keys().next().value);
      }
      return json(response, 200, await artistProfileCache.get(name));
    }
    if (request.method === 'GET' && url.pathname === '/api/state') { ensureQueueSubscription(); return json(response, 200, publicState()); }
    if (request.method === 'GET' && url.pathname === '/api/album-notes') {
      const album = String(url.searchParams.get('album') || '').trim().slice(0, 300);
      const artist = String(url.searchParams.get('artist') || '').trim().slice(0, 300);
      if (!album || !artist) return json(response, 400, {error:'Album and artist required'});
      const key = JSON.stringify([album, artist]);
      if (!albumNotesCache.has(key)) {
        const pending = loadAlbumNotes(album, artist).then(notes => {
          if (!notes.writeup) albumNotesCache.delete(key);
          return notes;
        }).catch(() => {
          albumNotesCache.delete(key);
          return {album, artist, writeup:'', source:''};
        });
        albumNotesCache.set(key, pending);
        while (albumNotesCache.size > 48) albumNotesCache.delete(albumNotesCache.keys().next().value);
      }
      return json(response, 200, await albumNotesCache.get(key));
    }
    if (request.method === 'GET' && url.pathname === '/api/browse') {
      if (!configuredRuntime().browserEnabled) return json(response, 404, {error: 'Roon Browse is disabled'});
      return json(response, 200, await browser.run(url.searchParams.get('session'), 'current'));
    }
    if (request.method === 'GET' && url.pathname === '/api/bluos/players') return json(response, 200, {players: await discoverPlayers()});
    if (request.method === 'GET' && url.pathname === '/api/bluos/inputs') return json(response, 200, {connected: bluos.publicState().connected, inputs: bluos.publicState().inputs});
    if (request.method === 'GET' && url.pathname === '/api/events') {
      response.writeHead(200, {'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', Connection: 'keep-alive'});
      listeners.add(response); response.write(`data: ${JSON.stringify(publicState())}\n\n`);
      request.on('close', () => listeners.delete(response)); return;
    }
    if (request.method === 'GET' && url.pathname === '/api/image') {
      if (!imageService || !url.searchParams.get('key')) return response.writeHead(404).end();
      const size = Math.max(48, Math.min(900, Number(url.searchParams.get('size')) || 900));
      return cachedImage(url.searchParams.get('key'), size, (error, type, data) => {
        if (error) return response.writeHead(404).end();
        response.writeHead(200, {'Content-Type': type || 'image/jpeg', 'Cache-Control': 'private, max-age=3600'}); response.end(data);
      });
    }
    if (request.method === 'GET' && url.pathname === '/api/discovery') {
      const section = url.searchParams.get('section') || 'recent', client = url.searchParams.get('client') || '';
      return json(response,200,section === 'daily-home' ? discovery.home(client) : discovery.state(section,url.searchParams.get('id') || '',client));
    }
    if (request.method === 'GET' && url.pathname === '/api/discovery/image') {
      const imageUrl = discovery.imageUrl(url.searchParams.get('key'));
      if(!imageUrl) return response.writeHead(404).end();
      const upstream = await fetch(imageUrl,{signal:AbortSignal.timeout(4000),redirect:'error'});
      if(!upstream.ok) return response.writeHead(404).end();
      const chunks=[]; let length=0;
      for await(const chunk of upstream.body) {length+=chunk.length;if(length>3*1024*1024) throw new Error('Artwork exceeds the size limit');chunks.push(chunk);}
      const bytes=Buffer.concat(chunks);
      const jpeg=bytes[0]===255&&bytes[1]===216, png=bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]));
      if(!jpeg&&!png) return response.writeHead(404).end();
      response.writeHead(200,{'Content-Type':jpeg?'image/jpeg':'image/png','Cache-Control':'private, max-age=300'});return response.end(bytes);
    }
    if (request.method === 'POST' && url.pathname.startsWith('/api/')) {
      const data = await body(request); const zone = selectedZone();
      if (url.pathname === '/api/bluos/input') {
        await bluos.selectInput(data.input_id); return json(response, 200, {ok: true});
      }
      if (url.pathname === '/api/bluos/volume') { await bluos.setVolume(data.value); return json(response, 200, {ok: true}); }
      if (url.pathname === '/api/bluos/mute') { await bluos.toggleMute(); return json(response, 200, {ok: true}); }
      if (!transport || !zone) return json(response, 409, {error: 'Roon is not connected'});
      if(url.pathname === '/api/discovery/mix-action') return json(response,200,await discovery.mixAction(data.id,zone.zone_id,data.action,data.nonce));
      if(url.pathname === '/api/discovery/track-action') return json(response,200,await discovery.trackAction(data.key,zone.zone_id,data.action,data.nonce));
      if(url.pathname === '/api/library/add') {
        const result = await library.mutate(zone,{action:'add',albumId:data.album_id});
        return json(response,200,result);
      }
      if(url.pathname === '/api/library/favorite') return json(response,200,await library.mutate(zone,{action:'favorite',albumId:data.album_id,favorite:data.favorite}));
      if(url.pathname === '/api/discovery/open') {
        if(!discovery.find(data.key) && data.section) {
          discovery.state(data.section,data.id||'');
          await discovery.tail;
        }
        return json(response,200,await openDiscovery(browser,data.session,discovery.find(data.key)));
      }
      if (url.pathname === '/api/browse') {
        if (!configuredRuntime().browserEnabled) return json(response, 404, {error: 'Roon Browse is disabled'});
        const action = ['root', 'open', 'back', 'more', 'previous', 'jump', 'section', 'sort', 'search', 'surprise', 'surprise_play', 'current', 'route', 'artist'].includes(data.action) ? data.action : 'current';
        return json(response, 200, await browser.run(data.session, action, data));
      }
      if (url.pathname === '/api/control' && data.action === 'resume') resumeRoon(zone);
      else if (url.pathname === '/api/control' && ['previous', 'playpause', 'next'].includes(data.action)) transport.control(zone, data.action);
      else if (url.pathname === '/api/queue/play') {
        const item = [...queueHistory, ...queueItems].find(candidate => String(candidate.queue_item_id) === String(data.queue_item_id));
        if (!item) return json(response, 409, {error: 'That queue item is no longer available'});
        transport.play_from_here(zone, item.queue_item_id, () => {});
      }
      else if (url.pathname === '/api/seek' && zone.is_seek_allowed) transport.seek(zone, 'absolute', Number(data.seconds));
      else {
        const output = (zone.outputs || []).find(item => item.output_id === data.output_id) || selectedOutput(zone);
        if (!output?.volume) return json(response, 409, {error: 'This zone has fixed volume'});
        if (url.pathname === '/api/volume') transport.change_volume(output, 'absolute', Number(data.value));
        else if (url.pathname === '/api/mute') transport.mute(output, output.volume.is_muted ? 'unmute' : 'mute');
        else return json(response, 404, {error: 'Unknown command'});
      }
      return json(response, 200, {ok: true});
    }
    if (request.method === 'GET' && serveStatic(request, response)) return;
    json(response, 404, {error: 'Not found'});
  } catch (error) { json(response, 400, {error: error.message}); }
}).listen(port, '127.0.0.1');
