const $ = id => document.getElementById(id);
function tickClock() {
  $('dashboard-clock').textContent = new Intl.DateTimeFormat('en-GB', {timeZone:'Asia/Singapore', hour:'2-digit', minute:'2-digit', hour12:false}).format(new Date());
}
tickClock(); setInterval(tickClock, 1000);
let state = null;
let lastTick = Date.now();
let musicView = 'now';
let queueSignature = '';
let inputSignature = '';
let lastActiveInput = '';
let browserState = null;
let browserLoading = false;
let browserPlan = {section: 'albums', steps: []};
let lastRestoredHash = '';
let browserRendering = false;
let browserPendingRequest = null;
let browserPreviousHeight = null;
let browserScrubDragging = false;
let browserScrollRestore = null;
const browserSectionScrolls = new Map();
const artistProfiles = new Map();
const browserSession = sessionStorage.getItem('pi-home-roon-browser') || (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`);
sessionStorage.setItem('pi-home-roon-browser', browserSession);
const proxied = location.pathname.startsWith('/roon');
const api = path => `${proxied ? '/roon' : ''}${path}`;
const mainOrigin = proxied ? location.origin : `${location.protocol}//${location.hostname}:8765`;
$('settings-link').href = `${mainOrigin}/admin`;
$('bus-link').href = `${mainOrigin}/`;
$('home-link').href = `${mainOrigin}/home.html`;

const playIcon = PiHomeIcons.svg('play');
const pauseIcon = PiHomeIcons.svg('pause');
const format = value => {
  value = Math.max(0, Math.round(value || 0));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`;
};

const scrollingCopy = new Map();

function setScrollingText(element, text) {
  const value = String(text || '');
  let entry = scrollingCopy.get(element);
  if (!entry) {
    const content = document.createElement('span'); content.className = 'scrolling-content';
    element.replaceChildren(content); entry = {content, animation: null, value: ''}; scrollingCopy.set(element, entry);
  }
  if (entry.value === value) return;
  entry.value = value; entry.content.textContent = value;
  requestAnimationFrame(() => refreshScrollingText(element));
}

function refreshScrollingText(element) {
  const entry = scrollingCopy.get(element);
  if (!entry) return;
  if (entry.animation) { entry.animation.cancel(); entry.animation = null; }
  const distance = Math.ceil(entry.content.scrollWidth - element.clientWidth);
  element.classList.toggle('is-scrolling', distance > 4);
  if (distance <= 4 || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const startPause = 10000; const endPause = 5000;
  const outward = Math.max(4500, distance / 22 * 1000); const returning = Math.max(3000, distance / 34 * 1000);
  const total = startPause + outward + endPause + returning;
  entry.animation = entry.content.animate([
    {transform: 'translateX(0)', offset: 0},
    {transform: 'translateX(0)', offset: startPause / total},
    {transform: `translateX(${-distance}px)`, offset: (startPause + outward) / total},
    {transform: `translateX(${-distance}px)`, offset: (startPause + outward + endPause) / total},
    {transform: 'translateX(0)', offset: 1}
  ], {duration: total, iterations: Infinity, easing: 'linear'});
}

let scrollingResizeTimer = null;
addEventListener('resize', () => {
  clearTimeout(scrollingResizeTimer);
  scrollingResizeTimer = setTimeout(() => scrollingCopy.forEach((_, element) => refreshScrollingText(element)), 150);
});

function compactLabel(label) {
  const words = String(label || '').trim().split(/\s+/).filter(Boolean);
  return (words[words.length - 1] || '').toUpperCase();
}

function setNavLabel(button, label) {
  const full = String(label || '').trim().toUpperCase();
  if (button.dataset.fullLabel === full) return;
  button.dataset.fullLabel = full;
  button.setAttribute('aria-label', label);
  button.replaceChildren();
  const wide = document.createElement('span'); wide.className = 'nav-label-full'; wide.textContent = full;
  const compact = document.createElement('span'); compact.className = 'nav-label-compact'; compact.textContent = compactLabel(label);
  button.append(wide, compact);
}

async function post(path, data) {
  await fetch(api(path), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
}

function render(next) {
  state = next;
  const theme = next.labels?.display_theme === 'roon' ? 'roon' : 'fresh-mint';
  document.body.dataset.theme = theme;
  const favicon = document.querySelector('link[rel="icon"]');
  if (favicon) favicon.href = theme === 'roon' ? '/favicon-roon.svg' : '/favicon.svg';
  const labels = next.labels || {};
  $('roon-link').textContent = labels.display || 'Roon';
  setNavLabel($('now-tab'), labels.now_playing || 'Now Playing');
  setNavLabel($('queue-tab'), labels.queue || 'Queue');
  setNavLabel($('browse-tab'), labels.browse || 'Browse');
  $('browse-tab').hidden = !next.browser_enabled;
  if (!next.browser_enabled && musicView === 'browse') musicView = 'now';
  lastTick = Date.now();
  const zone = next.zone;
  const amplifier = next.amplifier || {};
  const activeInput = String(amplifier.active_input?.id || '');
  $('bus-link').hidden = next.labels?.bus_enabled === false;
  if (activeInput !== lastActiveInput) {
    if (activeInput) musicView = 'source';
    else if (lastActiveInput && musicView === 'source') musicView = 'now';
    lastActiveInput = activeInput;
  }
  renderAmplifier(amplifier, zone);
  // Keep bounded secondary views current while an external input is visible,
  // so opening Queue or Details never waits for a later SSE update.
  renderQueue(next.queue || {});
  renderDetails(next.details || {});
  const external = Boolean(amplifier.connected && amplifier.active_input);
  const externalView = external && musicView === 'source';
  $('source-view').hidden = !externalView;
  $('now-view').hidden = musicView !== 'now';
  $('queue-view').hidden = musicView !== 'queue';
  $('browser-view').hidden = musicView !== 'browse';
  $('details-view').hidden = musicView !== 'details';
  syncDiscoveryNavigation();
  $('now-tab').disabled = $('queue-tab').disabled = $('browse-tab').disabled = false;
  if (externalView) return;
  if (!zone) {
    $('title').textContent = next.connected ? 'Choose a Roon zone' : 'Waiting for Roon';
    $('artist').textContent = next.connected ? 'Start playback in a zone' : 'Enable RoonDeck in Roon → Settings → Extensions';
    $('art').removeAttribute('src');
    $('previous').disabled = $('play').disabled = $('next').disabled = true;
    $('volume-panel').hidden = true;
    return;
  }

  if (zone.available === false) {
    $('zone').textContent = zone.name;
    setScrollingText($('title'), 'Nothing playing');
    setScrollingText($('artist'), 'Selected zone is offline');
    $('art').removeAttribute('src'); $('placeholder').hidden = false;
    $('previous').disabled = $('play').disabled = $('next').disabled = true;
    $('volume-panel').hidden = true; $('fixed').hidden = false;
    return;
  }

  const playing = zone.now_playing || {};
  const lines = playing.three_line || playing.two_line || playing.one_line || {};
  $('zone').textContent = zone.name;
  setScrollingText($('title'), lines.line1 || 'Nothing playing');
  setScrollingText($('artist'), playing.display_artist || String(lines.line2 || 'Roon').split(/\s+\/\s+|\s*;\s*/)[0]);
  if (playing.image_key) {
    const url = api(`/api/image?key=${encodeURIComponent(playing.image_key)}`);
    if ($('art').src !== location.origin + url) $('art').src = url;
    $('placeholder').hidden = true;
  } else {
    $('art').removeAttribute('src');
    $('placeholder').hidden = false;
  }

  $('play').innerHTML = external ? playIcon : (zone.state === 'playing' ? pauseIcon : playIcon);
  $('play').disabled = external ? !zone.can_play && !zone.can_pause : !(zone.can_play || zone.can_pause);
  $('previous').disabled = external || !zone.can_previous;
  $('next').disabled = external || !zone.can_next;
  const length = playing.length || 1;
  $('seek').max = length;
  $('seek').value = zone.seek_position || 0;
  $('elapsed').textContent = format(zone.seek_position);
  $('remaining').textContent = `−${format(length - (zone.seek_position || 0))}`;

  const volume = amplifier.connected && amplifier.volume ? {min: 0, max: 100, step: 1, value: amplifier.volume.value, is_muted: amplifier.volume.muted} : zone.output?.volume;
  $('volume-panel').hidden = !volume;
  $('fixed').hidden = Boolean(volume);
  if (volume) {
    $('volume').min = volume.min ?? 0;
    $('volume').max = volume.max ?? 100;
    $('volume').step = volume.step ?? 1;
    $('volume').value = volume.value ?? 0;
    $('volume-value').textContent = volume.type === 'db' ? `${volume.value} dB` : Math.round(volume.value);
    $('mute').textContent = volume.is_muted ? 'UNMUTE' : 'MUTE';
  }
}

function sourcePlayerName(amplifier, zone) {return amplifier.player?.name || zone?.name || amplifier.player?.model || 'Player';}
function renderAmplifier(amplifier, zone) {
  const inputs = amplifier.inputs || [];
  const signature = JSON.stringify([amplifier.connected, amplifier.active_input?.id, inputs.map(item => [item.id, item.name])]);
  if (signature !== inputSignature) {
    inputSignature = signature;
    const picker = $('music-nav'); picker.querySelectorAll('.source-input').forEach(button => button.remove());
    inputs.forEach(input => picker.insertBefore(inputButton(input, musicView === 'source' && String(input.id) === String(amplifier.active_input?.id)), $('now-tab')));
  }
  const active = amplifier.active_input;
  $('now-tab').classList.toggle('active', musicView === 'now'); $('queue-tab').classList.toggle('active', musicView === 'queue'); $('browse-tab').classList.toggle('active', musicView === 'browse');
  $('source-title').textContent = active?.name || 'External input';
  $('source-zone').textContent = sourcePlayerName(amplifier,zone);
  $('source-subtitle').textContent = amplifier.playback?.format || '';
  $('source-subtitle').hidden = !$('source-subtitle').textContent;
  const volume = amplifier.volume;
  $('amp-volume-panel').hidden = !volume;
  if (volume) { $('amp-volume-value').textContent = Math.round(volume.value ?? 0); $('amp-mute').textContent = volume.muted ? 'UNMUTE' : 'MUTE'; }
}

function inputButton(input, active) {
  const button = document.createElement('button'); button.className = `source-input${active ? ' active' : ''}`; setNavLabel(button, input.name);
  button.dataset.inputId = input.id; button.onclick = () => { setMusicView('source'); post('/api/bluos/input', {input_id: input.id}); }; return button;
}

function queueRow(item) {
  const button = document.createElement('button');
  button.className = `queue-row${item.is_current ? ' current' : ''}${item.is_previous ? ' previous' : ''}`;
  if (!item.is_current) button.onclick = () => post('/api/queue/play', {queue_item_id: item.queue_item_id});
  const artwork = document.createElement('span'); artwork.className = `queue-art${item.is_current ? ' playing' : ''}`;
  if (item.image_key) {
    const image = document.createElement('img'); image.loading = 'lazy'; image.alt = ''; image.src = api(`/api/image?key=${encodeURIComponent(item.image_key)}&size=96`); artwork.append(image);
  }
  if (item.is_current) { const playing = document.createElement('span'); playing.className = 'queue-play-badge'; playing.append(PiHomeIcons.element('play')); artwork.append(playing); }
  const copy = document.createElement('span'); copy.className = 'queue-copy';
  const title = document.createElement('strong'); title.textContent = item.title || 'Untitled track'; copy.append(title);
  const meta = document.createElement('small'); meta.textContent = [item.artist, item.album].filter(Boolean).join(' · ') || 'Roon'; copy.append(meta);
  const duration = document.createElement('time'); duration.className = 'queue-duration'; duration.textContent = item.length ? format(item.length) : '';
  button.append(artwork, copy, duration);
  return button;
}

function renderQueue(queue) {
  const items = queue.items || [];
  const signature = JSON.stringify([queue.status,items.map(item => [item.queue_item_id, item.is_current, item.is_previous])]);
  if (signature === queueSignature) return;
  queueSignature = signature;
  const list = $('queue-list'); list.replaceChildren();
  if (!items.length) {
    if(queue.status === 'loading'){list.append(loadingNotice());return;}
    const empty = document.createElement('p'); empty.className = 'queue-empty';
    empty.textContent = queue.status === 'disabled' ? 'Queue is disabled in Settings' : 'Nothing is queued';
    list.append(empty); return;
  }
  items.forEach(item => list.append(queueRow(item)));
  if (musicView === 'queue') requestAnimationFrame(scrollQueueToCurrent);
}

function scrollQueueToCurrent() {
  const current = $('queue-list').querySelector('.current');
  if (current) current.scrollIntoView({block: 'start'});
}

function setMusicView(view, record = true) {
  musicView = view;
  const queue = view === 'queue';
  const browse = view === 'browse';
  const details = view === 'details';
  const source = view === 'source';
  $('now-view').hidden = view !== 'now'; $('queue-view').hidden = !queue; $('browser-view').hidden = !browse; $('details-view').hidden = !details; $('source-view').hidden = !source;
  $('now-tab').classList.toggle('active', view === 'now'); $('queue-tab').classList.toggle('active', queue); $('browse-tab').classList.toggle('active', browse);
  document.querySelectorAll('.source-input').forEach(button => button.classList.toggle('active', source && String(button.dataset.inputId) === String(state?.amplifier?.active_input?.id)));
  if (queue) requestAnimationFrame(scrollQueueToCurrent);
  if (browse && record && !browserState && !location.hash.startsWith('#browse/')) browseCommand('section', {section: 'albums'});
  if (record && !(view === 'browse' && location.hash.startsWith('#browse/'))) { if (location.hash !== `#${view}`) history.pushState(null, '', `#${view}`); lastRestoredHash = `#${view}`; }
  syncDiscoveryNavigation();
}

function browserRow(item) {
  if (item.hint === 'header') {
    const heading = document.createElement('h3'); heading.className = 'browser-section'; heading.textContent = item.title; return heading;
  }
  const button = document.createElement('button');
  if (item.action && /^play playlist$/i.test(item.title.trim())) { button.className = 'artist-play primary-play browser-primary-action'; button.append(PiHomeIcons.element('play'), document.createTextNode(' Play Playlist')); button.disabled = !item.item_key; button.onclick = () => browseCommand('open', {item_key:item.item_key}); return button; }
  button.className = `browser-row${item.action ? ' action' : ''}`; button.disabled = !item.item_key;
  const artwork = document.createElement('span'); artwork.className = `browser-art${item.action ? ' action-icon' : ''}`;
  if (item.action) artwork.append(browserActionIcon(item.title));
  else {
    const fallback = () => artwork.replaceChildren(missingArtwork(item.result_type === 'artists' || /\d+ albums?$/i.test(item.subtitle || '')));
    fallback();
    if (item.image_key) { const image = document.createElement('img'); image.loading = 'lazy'; image.alt = ''; image.onerror = fallback; image.src = api(`/api/image?key=${encodeURIComponent(item.image_key)}&size=128`); artwork.replaceChildren(image); }
  }
  const copy = document.createElement('span'); copy.className = 'browser-copy'; const title = document.createElement('strong'); title.textContent = item.title || 'Untitled'; copy.append(title);
  if (item.subtitle) { const subtitle = document.createElement('small'); subtitle.textContent = item.subtitle; copy.append(subtitle); }
  const arrow = document.createElement('span'); arrow.className = 'browser-arrow'; arrow.textContent = item.duration || '';
  button.append(artwork, copy, arrow); button.onclick = () => browserState?.discovery_track_actions ? performDiscoveryTrackAction(item.item_key).catch(error=>{$('browser-message').hidden=false;$('browser-message').textContent=error.message;$('browser-message').classList.add('error');}) : browseCommand('open', {item_key: item.item_key}); return button;
}

function browserActionIcon(title) {
  const value = String(title || '').toLowerCase();
  return PiHomeIcons.element(/add next/.test(value) ? 'add' : /queue/.test(value) ? 'playlist' : /shuffle/.test(value) ? 'shuffle' : /from here/.test(value) ? 'next' : 'play');
}

function browserTileSymbol(title, section) {
  const value = String(title || '').toLowerCase();
  if (section === 'playlists') return 'playlist';
  if (value.includes('jazz')) return 'jazz';
  if (value.includes('classical')) return 'classical';
  if (value.includes('electronic')) return 'electronic';
  if (value.includes('pop') || value.includes('rock')) return 'rock';
  if (value.includes('stage') || value.includes('screen') || value.includes('soundtrack')) return 'stage';
  if (value.includes('avant')) return 'avant';
  if (value.includes('folk')) return 'folk';
  if (value.includes('country')) return 'country';
  if (value.includes('blues')) return 'blues';
  if (value.includes('rap') || value.includes('hip-hop')) return 'rap';
  if (value.includes('r&b') || value.includes('rhythm')) return 'rb';
  if (value.includes('reggae')) return 'reggae';
  if (value.includes('latin')) return 'latin';
  if (value.includes('world') || value.includes('international')) return 'world';
  if (value.includes('easy listening')) return 'easy';
  if (value.includes('vocal')) return 'vocal';
  if (value.includes('new age') || value.includes('ambient')) return 'ambient';
  if (value.includes('holiday')) return 'holiday';
  if (value.includes('children')) return 'children';
  if (value.includes('comedy')) return 'comedy';
  if (value.includes('religious') || value.includes('gospel')) return 'religious';
  return 'music';
}

function missingArtwork(artist = false) {
  const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  icon.setAttribute('viewBox', '0 0 100 100'); icon.setAttribute('aria-hidden', 'true'); icon.classList.add('missing-artwork');
  icon.innerHTML = artist
    ? '<circle cx="50" cy="30" r="14"/><path d="M22 88v-8a28 28 0 0 1 56 0v8"/>'
    : '<circle cx="50" cy="50" r="31"/><circle cx="50" cy="50" r="8"/>';
  return icon;
}

function browserSvgIcon(name, className = 'browser-tile-icon') {
  return PiHomeIcons.element(name, className);
}

function browseArtwork(container, key, size, artist = false) {
  const fallback = () => container.replaceChildren(missingArtwork(artist));
  if (!key) { fallback(); return; }
  const image = document.createElement('img'); image.loading = 'lazy'; image.alt = '';
  image.onerror = fallback;
  image.src = api(`/api/image?key=${encodeURIComponent(key)}&size=${size}`); container.append(image);
}

function browserCard(item, layout, showLabels, section, showSubtitles = true) {
  const button = document.createElement('button'); button.className = `browser-card ${layout}`; button.disabled = !item.item_key;
  if (layout === 'covers' || layout === 'tiles') {
    const artwork = document.createElement('span'); artwork.className = 'browser-card-art';
    if (layout === 'covers' || item.image_key) browseArtwork(artwork, item.image_key, 320, section === 'artists');
    else if (layout === 'tiles') artwork.append(browserSvgIcon(browserTileSymbol(item.title, section)));
    button.append(artwork);
  } else {
    button.append(browserSvgIcon(/playlist/i.test(item.title) ? 'playlist' : /genre/i.test(item.title) ? 'music' : /artist/i.test(item.title) ? 'artist' : /album|library/i.test(item.title) ? 'album' : 'folder', 'browser-card-icon'));
  }
  if (layout !== 'covers' || showLabels) {
    const copy = document.createElement('span'); copy.className = 'browser-card-copy'; const title = document.createElement('strong'); title.textContent = item.title || 'Untitled'; copy.append(title);
    if (showLabels && showSubtitles && item.subtitle) { const subtitle = document.createElement('small'); subtitle.textContent = item.subtitle; copy.append(subtitle); }
    if (layout === 'tiles' && section === 'genres') button.querySelector('.browser-card-art').append(copy);
    else { if (layout === 'tiles') button.classList.add('playlist-card'); button.append(copy); }
  }
  button.setAttribute('aria-label', [item.title, item.subtitle].filter(Boolean).join(', ')); button.onclick = () => browseCommand('open', {item_key: item.item_key}); return button;
}

function renderArtistProfile(profile, playAction) {
  const panel = $('browser-artist'); panel.replaceChildren(); panel.hidden = !profile;
  $('browser-view').classList.toggle('artist-takeover', Boolean(profile));
  if (!profile) return;
  const artwork = document.createElement('div'); artwork.className = 'artist-profile-art';
  browseArtwork(artwork, profile.image_key, 400, true); panel.append(artwork);
  const title = document.createElement('h2'); title.textContent = profile.name; panel.append(title);
  if (playAction) {
    const play = document.createElement('button'); play.className = 'artist-play'; play.append(PiHomeIcons.element('play'), document.createTextNode(' Play Artist Radio'));
    play.onclick = () => browseCommand('open', {item_key: playAction.item_key}); panel.append(play);
  }
}

function renderBrowser(data) {
  browserRendering = true; browserState = data; browserLoading = false;
  $('browser-view').classList.toggle('surprise-takeover', Boolean(data.surprise_preview));
  const artistPlay = data.artist_profile ? data.items?.find(item => item.action && /^play artist(?: radio)?$/i.test(item.title.trim())) : null;
  renderArtistProfile(data.artist_profile, artistPlay);
  document.querySelector('.browser-sidebar').append($('browser-back'));
  $('browser-back').hidden = !data.can_back || Boolean(data.surprise_preview); $('browser-back').disabled = !data.can_back; $('browser-loading-more').hidden = true;
  const activeSection = data.surprise_preview ? 'surprise' : (data.section || 'albums');
  document.querySelectorAll('[data-browser-section]').forEach(button => button.classList.toggle('active', button.dataset.browserSection === activeSection));
  $('browser-search-open').classList.toggle('active', activeSection === 'search');
  $('browser-surprise').classList.toggle('active', activeSection === 'surprise');
  $('browser-surprise').hidden = false;
  $('browser-surprise').textContent = 'SURPRISE!';
  syncDiscoveryNavigation();
  $('browser-scrubber').hidden = !data.alpha_scrub;
  $('browser-message').hidden = !data.message; $('browser-message').textContent = data.message || ''; $('browser-message').classList.toggle('error', Boolean(data.error));
  const list = $('browser-list'); list.replaceChildren(); list.className = `browser-list layout-${data.layout || 'list'}`;
  list.classList.toggle('genre-grid', data.layout === 'tiles' && data.section === 'genres');
  if (data.artist_profile) { const heading = document.createElement('h3'); heading.className = 'browser-section artist-albums-heading'; heading.textContent = 'ARTIST ALBUMS'; list.append(heading); }
  if (data.status === 'unavailable') { const empty = document.createElement('p'); empty.className = 'queue-empty'; empty.textContent = 'Roon Browse is unavailable.'; list.append(empty); browserRendering = false; return; }
  if (data.surprise_preview && data.items?.length) {
    const album = data.items[0]; const preview = document.createElement('div'); preview.className = 'surprise-preview';
    const art = document.createElement('div'); art.className = 'surprise-art';
    if (album.image_key) { const image = document.createElement('img'); image.alt = `${album.title} album cover`; image.src = api(`/api/image?key=${encodeURIComponent(album.image_key)}&size=600`); art.append(image); }
    else art.append(PiHomeIcons.element('album'));
    const title = document.createElement('h2'); title.textContent = album.title;
    const artist = document.createElement('p'); artist.textContent = album.subtitle || '';
    const stage = document.createElement('div'); stage.className = 'surprise-stage';
    const buttons = [];
    for (const [symbol, label, action] of [['refresh', 'Surprise me again', 'surprise'], ['play', 'Play this album', 'surprise_play']]) {
      const controls = document.createElement('div'); controls.className = 'surprise-control';
      const button = document.createElement('button'); button.className = 'surprise-action'; button.append(PiHomeIcons.element(symbol)); button.title = label; button.setAttribute('aria-label', label); button.onclick = () => browseCommand(action);
      const caption = document.createElement('span'); caption.textContent = action === 'surprise' ? 'Surprise Me' : 'Play Now'; controls.append(button, caption); buttons.push(controls);
    }
    stage.append(buttons[0], art, buttons[1]); preview.append(stage, title, artist); list.append(preview);
  } else if (data.search_routes) {
    list.classList.add('search-groups'); let group;
    const columns = [document.createElement('div'), document.createElement('div')];
    columns.forEach(column => { column.className = 'search-column'; list.append(column); });
    for (const item of data.items || []) {
      if (item.hint === 'header' || !group) { group = document.createElement('section'); group.className = 'search-group'; columns[/^(ALBUMS|TRACKS)$/.test(item.title) ? 1 : 0].append(group); }
      group.append(browserRow(item));
    }
  } else (data.items || []).filter(item => item !== artistPlay).forEach(item => list.append(item.action ? browserRow(item) : (['home', 'menu', 'covers', 'tiles'].includes(data.layout) ? browserCard(item, data.layout, Boolean(data.show_labels), data.section, data.show_subtitles !== false) : browserRow(item))));
  if (!(data.items || []).length) { const empty = document.createElement('p'); empty.className = 'queue-empty'; empty.textContent = 'Nothing is available here.'; list.append(empty); }
  requestAnimationFrame(() => {
    if (browserPreviousHeight !== null) { browserScrollRestore += $('browser-scroll').scrollHeight - browserPreviousHeight; browserPreviousHeight = null; }
    if (browserScrollRestore !== null) { $('browser-scroll').scrollTop = browserScrollRestore; browserScrollRestore = null; }
    browserRendering = false;
    syncWebScrubber();
    maybeLoadMore();
    if (browserPendingRequest) { const pending = browserPendingRequest; browserPendingRequest = null; browseCommand(pending.action, pending.data); }
  });
}

function positionWebScrubber(value) {
  const bounded = Math.max(0, Math.min(25, Math.round(value))); const letter = String.fromCharCode(65 + bounded);
  $('browser-scrub-letter').textContent = letter; $('browser-scrub-range').value = String(bounded);
  const height = $('browser-scrubber').clientHeight;
  // Dot and letter share a single centre, including after viewport resizing.
  $('browser-scrubber').style.setProperty('--scrub-center', `${16 + Math.max(1, height - 32) * bounded / 25}px`);
}

function syncWebScrubber() {
  if (!browserState?.alpha_scrub || $('browser-scrubber').hidden || browserRendering || browserLoading || browserScrubDragging || browserPendingRequest) return;
  const top = $('browser-scroll').getBoundingClientRect().top + 45;
  const cards = [...$('browser-list').querySelectorAll('.browser-card')];
  const card = cards.find(candidate => candidate.getBoundingClientRect().bottom > top) || cards.at(-1);
  const first = String(card?.getAttribute('aria-label') || 'A').trim().replace(/^the\s+/i, '').charAt(0).toUpperCase();
  positionWebScrubber(first >= 'A' && first <= 'Z' ? first.charCodeAt(0) - 65 : 0);
}

function maybeLoadMore() {
  const view = $('browser-scroll');
  if (musicView !== 'browse' || browserRendering || browserLoading || !browserState?.has_more) return;
  if (view.scrollHeight - view.scrollTop - view.clientHeight < 260) browseCommand('more');
}

async function browseCommand(action, data = {}) {
  if (action === 'search' || action === 'route') showBrowseLoading();
  if (browserLoading || browserRendering) { if (['jump', 'section', 'search', 'route'].includes(action)) browserPendingRequest = {action, data}; return; }
  const opened = action === 'open' ? browserState?.items?.find(item => item.item_key === data.item_key) : null;
  if (action !== 'route') recordBrowseRoute(action, data, opened);
  if (['section', 'open', 'back', 'surprise'].includes(action) && !opened?.action) showBrowseLoading();
  browserLoading = true;
  if (action === 'surprise' && !browserState?.surprise_preview) browserSectionScrolls.set(browserState?.section || 'albums', $('browser-scroll').scrollTop);
  if (['section', 'search'].includes(action)) {
    browserSectionScrolls.set(browserState?.section || 'albums', $('browser-scroll').scrollTop);
    browserScrollRestore = action === 'section' ? (browserSectionScrolls.get(data.section) || 0) : 0;
  }
  else if (action === 'more') { browserScrollRestore = $('browser-scroll').scrollTop; }
  else if (action === 'previous') { browserScrollRestore = $('browser-scroll').scrollTop; browserPreviousHeight = $('browser-scroll').scrollHeight; }
  else if (action === 'back' && browserState?.surprise_preview) browserScrollRestore = browserSectionScrolls.get(browserState.return_section || 'albums') || 0;
  else if (['jump', 'open', 'back', 'surprise'].includes(action)) browserScrollRestore = 0;
  try {
    const options = action === 'current' ? {method: 'GET', cache: 'no-store'} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({session: browserSession, action, ...data})};
    const url = action === 'current' ? api(`/api/browse?session=${encodeURIComponent(browserSession)}`) : api('/api/browse');
    const response = await fetch(url, options); const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Browse failed');
    if (browserPendingRequest) { browserLoading = false; const pending = browserPendingRequest; browserPendingRequest = null; browseCommand(pending.action, pending.data); return; }
    renderBrowser(result); if (result.navigate === 'now') setMusicView('now');
  } catch (error) {
    browserLoading = false;
    if (browserPendingRequest) { const pending = browserPendingRequest; browserPendingRequest = null; browseCommand(pending.action, pending.data); return; }
    renderBrowser({...(browserState || {}), status: 'ready', title: browserState?.title || 'Browse', items: browserState?.items || [], message: error.message, error: true});
  }
}

function browseHash(plan) {
  const params = new URLSearchParams();
  if (plan.query) params.set('query', plan.query);
  if (plan.steps?.length) params.set('path', JSON.stringify(plan.steps));
  return `#browse/${plan.query ? 'search' : plan.section || 'albums'}${params.size ? '?' + params : ''}`;
}
function recordBrowseRoute(action, data, opened) {
  if (action === 'section' || action === 'root') browserPlan = {section: data.section || 'albums', steps: []};
  else if (action === 'search') browserPlan = {section: 'search', query: data.query, steps: []};
  else if (action === 'surprise') browserPlan = {section: 'surprise', steps: []};
  else if (action === 'open' && opened && !opened.action) {
    const occurrence = (browserState.items || []).filter(item => item.title === opened.title && !item.action).indexOf(opened);
    browserPlan = {...browserPlan, steps: [...browserPlan.steps, {title: opened.title, occurrence, offset: Number(browserState.offset || 0) + browserState.items.indexOf(opened)}]};
  } else if (action === 'back') browserPlan = browserPlan.steps.length ? {...browserPlan, steps: browserPlan.steps.slice(0, -1)} : {section: 'albums', steps: []};
  else return;
  const hash = browseHash(browserPlan); lastRestoredHash = hash;
  if (location.hash !== hash) history.pushState(null, '', hash);
}
function showBrowseLoading() {
  $('browser-search-panel').hidden = true;
  $('browser-artist').hidden = true; $('browser-scrubber').hidden = true;
  const list = $('browser-list'); list.className = 'browser-list'; list.replaceChildren();
  list.append(loadingNotice());
  $('browser-message').hidden = true;
  $('browser-search-open').classList.toggle('active', Boolean(browserPlan.query));
  document.querySelectorAll('[data-browser-section]').forEach(button => button.classList.toggle('active', !browserPlan.query && button.dataset.browserSection === browserPlan.section));
}

function renderDetails(info) {
  const zone = state?.zone;
  const fallback = zone?.now_playing?.three_line || zone?.now_playing?.two_line || zone?.now_playing?.one_line || {};
  $('details-title').textContent = info.album || fallback.line3 || fallback.line1 || 'Nothing playing';
  $('details-artist').textContent = info.artist || fallback.line2 || '';
  $('details-subtitle').textContent = info.status === 'loading' ? 'Loading…' : (info.subtitle || '');
  $('details-subtitle').classList.toggle('loading-notice',info.status === 'loading');
  const library = $('library-add');
  library.hidden = !(info.album || fallback.line3);
  library.classList.toggle('filled', info.library_status === 'in_library');
  library.disabled = info.status === 'loading' || library.classList.contains('library-busy');
  library.title = info.library_status === 'in_library' ? 'Album is in your library' : 'Add to Library';
  const metadata = info.metadata || {}; const facts = $('details-facts'); facts.replaceChildren();
  $('details-writeup').textContent = metadata.full_writeup || metadata.writeup || '';
  $('details-source').textContent = metadata.writeup_source ? `Source · ${metadata.writeup_source}` : '';
  const addFact = (name, value) => {
    if (!value) return;
    const item = document.createElement('div'); const term = document.createElement('dt'); const description = document.createElement('dd');
    term.textContent = name; description.textContent = value; item.append(term, description); facts.append(item);
  };
  addFact('Released', metadata.release_date || metadata.year);
  addFact('Genre', (metadata.genres || []).join(' · '));
  addFact('Type', metadata.type);
  addFact('Label', metadata.label);
  addFact('Format', metadata.format);
  addFact('Tracks', metadata.track_count ? String(metadata.track_count) : '');
  addFact('Country', metadata.country);
  addFact('Editions', metadata.edition_count > 1 ? String(metadata.edition_count) : '');
  const key = info.album_image_key || info.image_key;
  if (key) { $('details-art').src = api(`/api/image?key=${encodeURIComponent(key)}&size=700`); $('details-placeholder').hidden = true; }
  else { $('details-art').removeAttribute('src'); $('details-placeholder').hidden = false; }
  const artistName = info.artist || fallback.line2 || '';
  $('details-artist-heading').textContent = artistName || 'Unknown artist';
  for (const id of ['details-browse-artist','details-browse-artist-inline']) {
    $(id).dataset.artist = artistName;
    $(id).hidden = !artistName;
  }
  const artistKey = info.artist_image_key;
  if (artistKey) { $('details-artist-art').src = api(`/api/image?key=${encodeURIComponent(artistKey)}&size=700`); $('details-artist-placeholder').hidden = true; }
  else { $('details-artist-art').removeAttribute('src'); $('details-artist-placeholder').hidden = false; }
  renderDetailsArtist(artistName);
  const list = $('details-tracks'); list.replaceChildren();
  (info.tracks || []).forEach((track, index) => {
    const item = document.createElement('li');
    const number = document.createElement('span'); number.textContent = index + 1;
    const copy = document.createElement('span'); const title = document.createElement('strong'); title.textContent = track.title;
    copy.append(title); if (track.subtitle) { const subtitle = document.createElement('small'); subtitle.textContent = track.subtitle; copy.append(subtitle); }
    item.append(number, copy); list.append(item);
  });
}

function renderDetailsArtist(name) {
  const writeup = $('details-artist-writeup'); const source = $('details-artist-source');
  if (!name) { writeup.textContent = ''; source.textContent = ''; return; }
  const cached = artistProfiles.get(name);
  if (cached?.writeup !== undefined) {
    writeup.textContent = cached.full_writeup || cached.writeup || 'No artist background is available.';
    source.textContent = cached.source ? `Source · ${cached.source}` : '';
    return;
  }
  if (cached?.pending) return;
  writeup.textContent = 'Loading artist background…'; source.textContent = '';
  const pending = fetch(api(`/api/artist?name=${encodeURIComponent(name)}`), {cache:'no-store'})
    .then(response => response.ok ? response.json() : Promise.reject(new Error('Artist lookup failed')))
    .then(profile => { artistProfiles.set(name, profile); if ($('details-artist-heading').textContent === name) renderDetailsArtist(name); })
    .catch(() => { const profile = {writeup:'No artist background is available.',source:''}; artistProfiles.set(name, profile); if ($('details-artist-heading').textContent === name) renderDetailsArtist(name); });
  artistProfiles.set(name, {pending});
}

$('library-add').onclick = async () => {
  const button = $('library-add'); if (button.classList.contains('filled') || button.classList.contains('library-busy')) return; button.disabled = true;
  button.classList.add('library-busy'); button.setAttribute('aria-busy', 'true');
  try {
    const response = await fetch(api('/api/library/add'), {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
    if (!response.ok) throw new Error('Roon could not add this album');
    const result = await response.json();
    if (result.added || result.already_in_library) button.classList.add('filled');
  } finally { button.classList.remove('library-busy'); button.removeAttribute('aria-busy'); button.disabled = false; }
};

initDiscover();
fetch(api('/api/state'), {cache: 'no-store'})
  .then(response => response.ok ? response.json() : Promise.reject(new Error('Roon state unavailable')))
  .then(render)
  .catch(() => {});
new EventSource(api('/api/events')).onmessage = event => render(JSON.parse(event.data));
setInterval(() => {
  if (!state?.zone || state.zone.state !== 'playing') return;
  const delta = (Date.now() - lastTick) / 1000;
  const position = (state.zone.seek_position || 0) + delta;
  const length = state.zone.now_playing?.length || 1;
  $('seek').value = Math.min(position, length);
  $('elapsed').textContent = format(position);
  $('remaining').textContent = `−${format(length - position)}`;
}, 1000);

$('previous').onclick = () => post('/api/control', {action: 'previous'});
$('play').onclick = () => post('/api/control', {action: state?.amplifier?.active_input ? 'resume' : 'playpause'});
$('next').onclick = () => post('/api/control', {action: 'next'});
$('seek').onchange = event => post('/api/seek', {seconds: Number(event.target.value)});
$('volume').onchange = event => state.amplifier?.connected ? post('/api/bluos/volume', {value: Number(event.target.value)}) : post('/api/volume', {output_id: state.zone.output.id, value: Number(event.target.value)});
$('mute').onclick = () => state.amplifier?.connected ? post('/api/bluos/mute', {}) : post('/api/mute', {output_id: state.zone.output.id});
$('amp-down').onclick = () => post('/api/bluos/volume', {value: Number(state?.amplifier?.volume?.value || 0) - 2});
$('amp-up').onclick = () => post('/api/bluos/volume', {value: Number(state?.amplifier?.volume?.value || 0) + 2});
$('amp-mute').onclick = () => post('/api/bluos/mute', {});
$('now-tab').onclick = () => setMusicView('now');
$('queue-tab').onclick = () => setMusicView('queue');
$('browse-tab').onclick = () => setMusicView('browse');
$('browser-back').onclick = () => browseCommand('back');
$('browser-surprise').onclick = () => browseCommand('surprise');
$('browser-search-open').onclick = () => { if (location.hash !== '#browse/search') history.pushState(null, '', '#browse/search'); lastRestoredHash = '#browse/search'; $('browser-search-panel').hidden = false; $('browser-search-input').focus(); };
$('browser-search-input').placeholder = 'Search your library and TIDAL';
$('browser-search-input').setAttribute('enterkeyhint', 'search');
$('browser-search-cancel').onclick = () => { $('browser-search-panel').hidden = true; if (location.hash === '#browse/search') history.back(); $('browser-search-open').focus(); };
$('browser-search-panel').onkeydown = event => { if (event.key === 'Escape') { event.preventDefault(); $('browser-search-cancel').click(); } };
$('browser-search-form').onsubmit = event => {
  event.preventDefault(); const query = $('browser-search-input').value.trim();
  if (query) { $('browser-search-panel').hidden = true; browseCommand('search', {query, source: 'all'}); }
};
document.querySelectorAll('[data-browser-section]').forEach(button => button.onclick = () => browseCommand('section', {section: button.dataset.browserSection}));
$('browser-scroll').addEventListener('scroll', () => { maybeLoadMore(); syncWebScrubber(); }, {passive: true});
$('browser-scrub-range').oninput = event => positionWebScrubber(Number(event.target.value));
function scrubAtPointer(event) {
  const bounds = $('browser-scrubber').getBoundingClientRect();
  positionWebScrubber((event.clientY - bounds.top - 16) * 25 / Math.max(1, bounds.height - 32));
}
let browserSwipeStart = null;
$('browser-scroll').addEventListener('touchstart', event => {
  if (event.touches.length !== 1) { browserSwipeStart = null; return; }
  browserSwipeStart = {x:event.touches[0].clientX,y:event.touches[0].clientY,time:Date.now()};
}, {passive:true});
$('browser-scroll').addEventListener('touchend', event => {
  const start = browserSwipeStart; browserSwipeStart = null;
  if (!start || !event.changedTouches.length || !browserState?.can_back) return;
  const dx = event.changedTouches[0].clientX - start.x, dy = event.changedTouches[0].clientY - start.y;
  if (dx > 90 && dx > Math.abs(dy) * 2 && Date.now() - start.time < 900) browseCommand('back');
}, {passive:true});
$('browser-scroll').addEventListener('touchcancel', ()=>{browserSwipeStart=null}, {passive:true});
$('browser-scrub-range').onpointerdown = event => { event.preventDefault(); browserScrubDragging = true; event.target.setPointerCapture(event.pointerId); scrubAtPointer(event); };
$('browser-scrub-range').onpointermove = event => { if (browserScrubDragging) scrubAtPointer(event); };
$('browser-scrub-range').onpointerup = event => { if (!browserScrubDragging) return; scrubAtPointer(event); browserScrubDragging = false; browseCommand('jump', {letter: $('browser-scrub-letter').textContent}); };
$('browser-scrub-range').onpointercancel = () => { browserScrubDragging = false; };
window.addEventListener('resize', () => positionWebScrubber(Number($('browser-scrub-range').value)));
$('browser-scroll').addEventListener('wheel', event => { if (event.deltaY < 0 && $('browser-scroll').scrollTop < 40 && browserState?.offset > 0 && !browserRendering) browseCommand('previous'); }, {passive: true});
$('browser-scrub-range').onchange = event => browseCommand('jump', {letter: String.fromCharCode(65 + Number(event.target.value))});
$('details-open').onclick = () => setMusicView('details');
$('details-close').onclick = () => setMusicView('now');
$('details-browse-artist').onclick = $('details-browse-artist-inline').onclick = event => {
  const name = event.currentTarget.dataset.artist;
  if (!name) return;
  browserPlan = {section:'artists',query:'',steps:[]};
  setMusicView('browse');
  browseCommand('artist',{name});
};
function restoreMusicRoute() {
  if (lastRestoredHash === location.hash) return;
  lastRestoredHash = location.hash;
  const [route, queryString = ''] = location.hash.slice(1).split('?');
  const [view, section] = route.split('/');
  if(view==='discover') {
    const params=new URLSearchParams(queryString);
    if(section==='item'){setMusicView('discover',false);openDiscoveryItem(params.get('key'),false,params.get('section')||'recent',params.get('mix')||'');return;}
    openDiscover(section,params.get('mix')||'',false,params.get('view')==='picks'?'picks':params.get('mode')||'listened');return;
  }
  setMusicView(['now', 'queue', 'browse', 'details', 'source'].includes(view) ? view : 'now', false);
  if (view === 'browse' && section) {
    discoveryTab='browse';syncDiscoveryNavigation();
    const params = new URLSearchParams(queryString); const query = params.get('query') || '';
    if (section === 'search' && !query) { $('browser-search-panel').hidden = false; $('browser-search-input').focus(); return; }
    let steps = []; try { steps = JSON.parse(params.get('path') || '[]'); } catch (_) {}
    browserPlan = {section, query, steps: Array.isArray(steps) ? steps : []};
    browseCommand('route', browserPlan);
  } else $('browser-search-panel').hidden = true;
}
window.addEventListener('popstate', restoreMusicRoute);
window.addEventListener('hashchange', restoreMusicRoute);
restoreMusicRoute();
