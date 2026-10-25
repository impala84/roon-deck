'use strict';

const PAGE_SIZE = 30;

function request(service, method, options, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Roon Browse request timed out')), timeoutMs);
    try {
      service[method](options, (error, result) => {
        clearTimeout(timer);
        if (error) reject(new Error(String(error)));
        else resolve(result || {});
      });
    } catch (error) { clearTimeout(timer); reject(error); }
  });
}

function safeSession(value) {
  const clean = String(value || 'web').replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 48);
  return `pihome-${clean || 'web'}`;
}

function formatDuration(value) {
  if (value === null || value === undefined || value === '') return '';
  if (typeof value === 'string' && /^\d{1,3}:\d{2}$/.test(value.trim())) return value.trim();
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0) return '';
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

function isActionItem(item) {
  return item?.hint === 'action' || /^(play (now|album|playlist|artist|genre|from here)|add next|queue|start radio|shuffle)$/i.test(String(item?.title || '').trim());
}

function zoneOptions(zone) {
  return zone?.zone_id ? {zone_or_output_id: zone.zone_id} : {};
}

function requiresPlaybackZone(item) {
  return Boolean(item?.action) && /^(?:play(?:\s|$)|shuffle(?:\s|$)|start radio$|add next$|queue$)/i.test(String(item.title || '').trim());
}

function artistCreditMatches(value, artist) {
  const identity = text => String(text || '').toLocaleLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .split(/\s+/)
    .filter(token => token && token !== 'the' && token !== 'and')
    .join(' ');
  const wanted = identity(artist);
  // Search results are deliberately broad: a query for "Chicago" also
  // returns Chicago Symphony Orchestra and Junior Wells' Chicago Blues Band.
  // Only accept the complete credit or one explicit collaboration credit;
  // never accept the artist merely because its words occur inside a different
  // artist's name.
  const credits = [String(value || ''), ...String(value || '').split(/\s*(?:[,;/•]|·|\b(?:feat(?:uring)?|with)\b)\s*/i)];
  return Boolean(wanted) && credits.some(credit => identity(credit) === wanted);
}

function publicItem(item) {
  const originalTitle = String(item?.title || '');
  const title = /^play artist$/i.test(originalTitle.trim()) ? 'Play Artist Radio' : originalTitle;
  return {
    title, subtitle: String(item?.subtitle || '').replace(/\[\[\d+\|([^\]]+)\]\]/g, '$1'),
    image_key: item?.image_key || null, item_key: item?.item_key || null,
    hint: item?.hint || null, action: isActionItem(item),
    // Duration is not part of the original Browse contract, but newer/custom
    // cores may expose one of these fields. Preserve it when it is available.
    duration: formatDuration(item?.duration ?? item?.length ?? item?.duration_seconds),
    input_prompt: item?.input_prompt ? {
      prompt: String(item.input_prompt.prompt || 'Search'), action: String(item.input_prompt.action || 'Go'),
      value: String(item.input_prompt.value || ''), is_password: Boolean(item.input_prompt.is_password)
    } : null
  };
}

function browserLayout(hierarchy, level, list, items) {
  const title = String(list?.title || '');
  const subtitle = String(list?.subtitle || '');
  if (hierarchy === 'browse' && Number(level || 0) === 0) return {layout: 'home', show_labels: true};
  const usable = items.filter(item => item.hint !== 'header');
  if (/^library$/i.test(title)) return {layout: 'menu', show_labels: true};
  if (usable.some(isActionItem)) return {layout: 'list', show_labels: true};
  if (/^genres?$/i.test(title)) return {layout: 'tiles', show_labels: true, show_subtitles: false};
  if (/^playlists?$/i.test(title)) return {layout: 'tiles', show_labels: true, show_subtitles: false};
  if (/\btracks?\b/i.test(subtitle) && !/^tracks?$/i.test(title)) return {layout: 'list', show_labels: true};
  if (/^albums?$/i.test(title)) return {layout: 'covers', show_labels: false};
  const imageRatio = usable.length ? usable.filter(item => item.image_key).length / usable.length : 0;
  if (imageRatio >= .45) return {layout: 'covers', show_labels: !/albums?/i.test(title)};
  if (usable.length > 0 && usable.length <= 10 && !usable.some(isActionItem)) return {layout: 'menu', show_labels: true};
  return {layout: 'list', show_labels: true};
}

function libraryItems(list, items) {
  if (!/^library$/i.test(String(list?.title || '').trim())) return items;
  return items.filter(item => !/^(search|tags?)$/i.test(String(item.title || '').trim()));
}

function withFallbackImage(items, imageKey) {
  if (!imageKey) return items;
  return items.map(item => !isActionItem(item) && !item.image_key ? {...item, image_key: imageKey} : item);
}

function withAlbumArtist(items) {
  if (!items.some(item => item.action && /^play album$/i.test(String(item.title || '').trim()))) return items;
  const firstTrack = items.find(item => !item.action && item.subtitle);
  const albumArtist = String(firstTrack?.subtitle || '').split(/\s*,\s*/)[0].trim();
  return items.map(item => item.action ? item : {...item, title: String(item.title || '').replace(/^\s*(?:\d+\s*[-/]\s*\d+[.\s]+|\d+\.\s+)/, ''), subtitle: albumArtist || item.subtitle});
}

function rootItems(items) {
  const wanted = ['library', 'playlists', 'genres'];
  const available = items.filter(item => item.hint !== 'header');
  return wanted.map(name => available.find(item => String(item.title || '').trim().toLowerCase() === name)).filter(Boolean);
}

class BrowseManager {
  constructor(service, zone) {
    this.service = service;
    this.zone = zone;
    this.sessions = new Map();
    this.pending = new Map();
    this.sections = new Map();
    this.alphabetIndexes = new Map();
    this.activeSessions = new Map();
    this.lastSurprises = new Map();
    this.surpriseOrigins = new Map();
    this.artistContexts = new Map();
    this.artistRequestId = 0;
    this.searchSources = new Map();
    this.sortedCollections = new Map();
    this.pendingPlayback = null;
  }

  clear() { this.sessions.clear(); this.pending.clear(); this.sections.clear(); this.alphabetIndexes.clear(); this.activeSessions.clear(); this.lastSurprises.clear(); this.surpriseOrigins.clear(); this.artistContexts.clear(); this.searchSources.clear(); this.pendingPlayback = null; }

  async resumePendingPlayback() {
    const pending = this.pendingPlayback;
    if (!pending || !this.service() || !this.zone()) return null;
    this.pendingPlayback = null;
    try {
      return pending.surprise
        ? await this.playSurprise(pending.baseSession)
        : await this._run(pending.session, 'open', pending.data);
    } catch (error) {
      // A zone can disappear again while it is waking. Keep the user's request
      // so the next zone update can retry it rather than silently losing it.
      if (!this.zone()) this.pendingPlayback = pending;
      throw error;
    }
  }

  run(sessionName, command = 'current', data = {}) {
    const session = safeSession(sessionName);
    const previous = this.pending.get(session) || Promise.resolve();
    const current = previous.catch(() => {}).then(() => {
      if (command === 'route') return this.restoreRoute(session, data);
      if (command === 'surprise') return this.surprise(session);
      if (command === 'surprise_play') return this.playSurprise(session);
      if (command === 'artist') return this.openArtist(session, String(data.name || '').slice(0, 500));
      let active = this.activeSessions.get(session) || session;
      const activeState = this.sessions.get(active);
      const selectedArtistAlbum = command === 'open'
        ? activeState?.items?.find(item => String(item.item_key) === String(data.item_key))
        : null;
      if (selectedArtistAlbum && !selectedArtistAlbum.action && activeState?.artist_profile?.name) {
        return this.openArtistAlbum(session, activeState.artist_profile.name, selectedArtistAlbum);
      }
      const preview = activeState?.search_routes?.[data.item_key];
      if (command === 'open' && preview) {
        this.activeSessions.set(session, preview.session);
        if (!preview.key) return this.sessions.get(preview.session);
        return this._run(preview.session, 'open', {item_key: preview.key});
      }
      const origin = this.sessions.get(active)?.search_origin;
      if (command === 'back' && origin && this.sessions.get(active).level <= origin.level) {
        this.activeSessions.set(session, origin.session);
        return this.sessions.get(origin.session);
      }
      if (command === 'section' || command === 'root') {
        const section = ['albums', 'artists', 'genres', 'playlists'].includes(data.section) ? data.section : 'albums';
        active = `${session}-${section}`;
        this.activeSessions.set(session, active);
        if (this.sessions.has(active)) return this.sessions.get(active);
      } else if (command === 'search') {
        active = `${session}-search-${data.source === 'tidal' ? 'tidal' : 'library'}`; this.sections.set(active, 'search'); this.activeSessions.set(session, active);
      } else if (command === 'back' && (this.sessions.get(active)?.surprise_preview || (this.sessions.get(active)?.hierarchy === 'search' && this.sessions.get(active)?.level === 0))) {
        active = this.sessions.get(active)?.surprise_preview ? (this.surpriseOrigins.get(session) || `${session}-albums`) : `${session}-albums`;
        this.activeSessions.set(session, active);
        return this.sessions.get(active) || this._run(active, 'root', {section: 'albums'});
      } else if (command === 'current' && !this.activeSessions.has(session) && !this.sessions.has(session)) {
        active = `${session}-albums`; this.activeSessions.set(session, active);
      }
      const state = this.sessions.get(active);
      return this._run(active, command, data);
    });
    this.pending.set(session, current);
    return current.finally(() => { if (this.pending.get(session) === current) this.pending.delete(session); });
  }

  async _run(session, command, data) {
    const service = this.service(); const zone = this.zone();
    if (!service) return {status: 'unavailable', title: 'Browse', items: [], can_back: false, has_more: false};
    if (command === 'current' && this.sessions.has(session)) return this.sessions.get(session);
    if (command === 'sort') return this.sortCollection(service, session, data.order);
    if (command === 'more') return this.loadMore(service, session);
    if (command === 'previous') return this.loadPrevious(service, session);
    if (command === 'jump') return this.jumpTo(service, session, String(data.letter || 'A'));
    if (command === 'section' || command === 'root' || (command === 'current' && !this.sessions.has(session))) return this.openSection(service, zone, session, String(data.section || 'albums'));
    if (command === 'search') return this.search(service, zone, session, String(data.query || '').trim(), data.source);
    const state = this.sessions.get(session);
    if (command === 'back' && state?.hierarchy !== 'browse' && state?.level === 0) return this._run(session, 'root', {});
    const hierarchy = !state ? 'browse' : state.hierarchy;
    const options = {hierarchy, multi_session_key: session, ...zoneOptions(zone)};
    if (!state) options.pop_all = true;
    else if (command === 'back') options.pop_levels = state?.skipped_album_preview ? 2 : 1;
    else if (command === 'open' && data.item_key) options.item_key = String(data.item_key);
    else return state || this._run(session, 'root', {});
    const opened = command === 'open' ? state?.items?.find(item => String(item.item_key) === String(data.item_key)) : null;
    if (!zone && requiresPlaybackZone(opened)) {
      this.pendingPlayback = {session, data:{item_key:String(data.item_key)}};
      return {...this.save(session, {...state, message:'Playback queued. Power on the selected zone to begin.', error:false}), navigate:'now'};
    }
    if (opened?.shuffle_genre) return this.shuffleGenre(service, zone, session, state, options);
    let result = await request(service, 'browse', options);
    let playbackCompleted = opened?.action && /^play(?: now| from here)?$/i.test(opened.title.trim());
    if (state?.action_menu && opened?.action && /^(add next|queue)$/i.test(opened.title.trim()) && !result.is_error && result.action !== 'list') {
      const album = await request(service, 'browse', {hierarchy, multi_session_key:session, ...zoneOptions(zone), pop_levels:1});
      const restored = await this.follow(service, session, hierarchy, album, state.fallback_image_key);
      return this.save(session, {...restored, message: /^add next$/i.test(opened.title.trim()) ? 'Added next.' : 'Added to queue.'});
    }
    // Play Album can open a second action menu rather than start playback.
    // Complete its Play Now action explicitly, just as the Surprise preview does.
    if (!data.menu_only && opened?.action && /^play album$/i.test(opened.title.trim()) && result.action === 'list' && !result.is_error) {
      const menu = await request(service, 'load', {hierarchy, multi_session_key: session, level: result.list.level, offset: 0, count: 30});
      const playNow = menu.items?.find(item => /^play now$/i.test(String(item.title || '').trim()) && isActionItem(item));
      if (playNow?.item_key) {
        result = await request(service, 'browse', {...options, item_key: playNow.item_key});
        playbackCompleted = true;
      } else if (menu.items?.some(item => !isActionItem(item) && item.hint !== 'header')) {
        // Some cores return the album's track list after executing playback.
        playbackCompleted = true;
      }
    }
    // Roon exposes Play Artist as a menu containing Shuffle and Start Radio.
    // The UI names the actual outcome and executes Start Radio immediately.
    if (opened?.action && /^play artist radio$/i.test(opened.title.trim()) && result.action === 'list' && !result.is_error) {
      const menu = await request(service, 'load', {hierarchy, multi_session_key: session, level: result.list.level, offset: 0, count: 30});
      const startRadio = menu.items?.find(item => /^start radio$/i.test(String(item.title || '').trim()) && isActionItem(item));
      if (!startRadio?.item_key) return this.save(session, {...state, error:true, message:'Artist Radio is unavailable for this artist.'});
      result = await request(service, 'browse', {...options, item_key:startRadio.item_key});
      playbackCompleted = !result.is_error;
    }
    let next = await this.follow(service, session, hierarchy, result, opened?.image_key || (opened?.action ? state?.fallback_image_key : null) || result.list?.image_key || null);
    // Search can return a one-album wrapper before the actual track list.
    // Roon does not consistently preserve the result title on that wrapper,
    // so identify it by structure: one ordinary child and no actions. Never
    // auto-run Play Album or mistake a real track list for the wrapper.
    if (command === 'open' && hierarchy === 'search' && /^albums$/i.test(state?.title || '') && opened && !opened.action && !next.error && next.items?.length === 1) {
      const child = next.items[0];
      if (!child.action && child.hint !== 'header' && child.item_key && !next.items.some(item => item.action)) {
        const tracks = await request(service, 'browse', {...options, item_key: child.item_key});
        next = await this.follow(service, session, hierarchy, tracks, child.image_key);
        next = this.save(session, {...next, skipped_album_preview: true});
      }
    }
    if (((state?.section === 'artists' && state.section_root) || next.items?.some(item => item.action && /^play artist(?: radio)?$/i.test(item.title))) && opened && !opened.action && result.action === 'list' && !next.error) {
      this.artistContexts.set(session + ':' + next.title, {name:opened.title,image_key:opened.image_key});
      while (this.artistContexts.size > 64) this.artistContexts.delete(this.artistContexts.keys().next().value);
      return this.save(session, {...next, artist_profile:{name:opened.title,image_key:opened.image_key}});
    }
    if (opened?.action && (/^play(?: (now|album|from here))?$/i.test(opened.title.trim()) || /^play artist radio$/i.test(opened.title.trim())) && !result.is_error && (playbackCompleted || result.action !== 'list')) return {...this.save(session, {...next, message: ''}), navigate: 'now'};
    return next;
  }

  async restoreRoute(session, data) {
    if (data.section === 'surprise') return this.surprise(session);
    let active = `${session}-route`;
    this.activeSessions.set(session, active);
    this.sessions.delete(active);
    const section = ['albums', 'artists', 'genres', 'playlists'].includes(data.section) ? data.section : 'albums';
    let state;
    if (data.query) {
      this.sections.set(active, 'search');
      state = await this._run(active, 'search', {query: String(data.query).slice(0, 500), source: 'all'});
    } else state = await this._run(active, 'root', {section});
    // URLs store labels, not Roon's short-lived item keys. Resolve fresh keys
    // at each level and never replay playback actions from browser history.
    for (const step of (Array.isArray(data.steps) ? data.steps : []).slice(0, 20)) {
      if (!step || typeof step.title !== 'string') continue;
      if (!state.search_routes && Number.isFinite(step.offset) && step.offset > PAGE_SIZE && state.count > step.offset) {
        const offset = Math.max(0, Math.floor(step.offset) - 15);
        const loaded = await request(this.service(), 'load', {hierarchy: state.hierarchy, multi_session_key: active, level: state.level, offset, count: PAGE_SIZE});
        state = this.store(active, state.hierarchy, loaded.list, loaded.items || [], '', state.fallback_image_key, offset);
      }
      let matches = state.items?.filter(item => item.title === step.title && !item.action) || [];
      while (matches.length <= Number(step.occurrence || 0) && state.has_more) {
        const previousLength = state.items.length;
        state = await this._run(active, 'more', {});
        if (state.items.length <= previousLength) break;
        matches = state.items.filter(item => item.title === step.title && !item.action);
      }
      const item = matches[Number(step.occurrence || 0)];
      if (!item?.item_key) return {...state, message: 'This result is no longer available. Showing its parent page.'};
      const preview = state.search_routes?.[item.item_key];
      if (preview) {
        active = preview.session;
        state = preview.key ? await this._run(active, 'open', {item_key: preview.key}) : this.sessions.get(active);
      } else state = await this._run(active, 'open', {item_key: item.item_key});
      this.activeSessions.set(session, active);
    }
    return state;
  }

  async shuffleGenre(service, zone, session, state, options) {
    const menu = await request(service, 'browse', options);
    if (menu.action !== 'list') return this.follow(service, session, state.hierarchy, menu);
    const loaded = await request(service, 'load', {hierarchy: state.hierarchy, multi_session_key: session, level: menu.list.level, offset: 0, count: 30});
    const shuffle = loaded.items?.find(item => /^shuffle$/i.test(item.title) && item.hint === 'action');
    if (!shuffle?.item_key) return this.follow(service, session, state.hierarchy, menu);
    const result = await request(service, 'browse', {...options, item_key: shuffle.item_key});
    if (result.is_error) return this.follow(service, session, state.hierarchy, result);
    const restored = await request(service, 'browse', {hierarchy: state.hierarchy, multi_session_key: session, ...zoneOptions(zone), pop_levels: 1});
    const next = await this.follow(service, session, state.hierarchy, restored);
    return this.save(session, {...next, message: `Shuffling ${state.title}.`});
  }

  async surprise(baseSession) {
    const service = this.service(); const zone = this.zone();
    if (!service) throw new Error('Roon is not connected');
    const session = `${baseSession}-surprise`;
    const origin = this.activeSessions.get(baseSession) || `${baseSession}-albums`;
    if (!this.sessions.get(origin)?.surprise_preview) this.surpriseOrigins.set(baseSession, origin);
    const returnSection = this.sessions.get(this.surpriseOrigins.get(baseSession))?.section || 'albums';
    const albums = await this.openSection(service, zone, session, 'albums');
    if (!albums.count || albums.error) throw new Error('No library albums are available');
    const previous = this.lastSurprises.get(baseSession);
    const count = albums.count;
    let offset = Math.floor(Math.random() * (count - (count > 1 && previous !== undefined ? 1 : 0)));
    if (count > 1 && previous !== undefined && offset >= previous) offset++;
    const loaded = await request(service, 'load', {hierarchy: 'browse', multi_session_key: session, level: albums.level, offset, count: 1});
    const album = loaded.items?.[0];
    if (!album?.item_key) throw new Error('The selected album is unavailable');
    this.lastSurprises.set(baseSession, offset);
    this.activeSessions.set(baseSession, session);
    return this.save(session, {...albums, section: 'albums', section_root: false,
      items: [publicItem(album)], layout: 'covers', show_labels: true, show_subtitles: true,
      count: 1, offset: 0, has_more: false, alpha_scrub: false, can_back: true,
      surprise_album: album.title, surprise_preview: true, return_section: returnSection, message: ''});
  }

  async playSurprise(baseSession) {
    const preview = this.sessions.get(this.activeSessions.get(baseSession));
    if (!preview?.surprise_preview) throw new Error('Choose a surprise album first');
    const service = this.service(); const zone = this.zone();
    if (!service) throw new Error('Roon is not connected');
    if (!zone) {
      this.pendingPlayback = {surprise:true, baseSession};
      return {...this.save(this.activeSessions.get(baseSession), {...preview, message:'Playback queued. Power on the selected zone to begin.', error:false}), navigate:'now'};
    }
    const session = `${baseSession}-surprise-play`;
    const albums = await this.openSection(service, zone, session, 'albums');
    const options = {hierarchy: 'browse', multi_session_key: session, ...zoneOptions(zone)};
    const selected = await request(service, 'load', {...options, level: albums.level, offset: this.lastSurprises.get(baseSession), count: 1});
    const album = selected.items?.[0];
    if (!album?.item_key || album.title !== preview.surprise_album) throw new Error('The library changed. Choose another surprise album.');
    const opened = await request(service, 'browse', {...options, item_key: album.item_key});
    if (opened.action !== 'list' || opened.is_error) throw new Error('Roon could not open the album');
    const tracks = await request(service, 'load', {...options, level: opened.list.level, offset: 0, count: 30});
    const play = tracks.items?.find(item => /^play album$/i.test(item.title));
    if (!play?.item_key) throw new Error('Roon has no Play Album action for this album');
    let result = await request(service, 'browse', {...options, item_key: play.item_key});
    if (result.action === 'list') {
      const menu = await request(service, 'load', {...options, level: result.list.level, offset: 0, count: 30});
      const now = menu.items?.find(item => /^play now$/i.test(item.title) && item.hint === 'action');
      if (!now?.item_key) throw new Error('Roon has no Play Now action for this album');
      result = await request(service, 'browse', {...options, item_key: now.item_key});
    }
    if (result.is_error) throw new Error(String(result.message || 'Roon could not play the album'));
    const saved = this.save(this.activeSessions.get(baseSession), {...preview, message: ''});
    return {...saved, navigate: 'now'};
  }

  async openNamed(service, zone, session, result, title) {
    if (result?.action !== 'list' || !result.list) return null;
    const loaded = await request(service, 'load', {hierarchy: 'browse', multi_session_key: session, level: result.list.level, offset: 0, count: 100});
    const item = (loaded.items || []).find(candidate => String(candidate.title || '').trim().toLowerCase() === title);
    if (!item?.item_key) return null;
    return request(service, 'browse', {hierarchy: 'browse', multi_session_key: session, ...zoneOptions(zone), item_key: item.item_key});
  }

  async openSection(service, zone, session, requested) {
    const section = ['albums', 'artists', 'genres', 'playlists'].includes(requested.toLowerCase()) ? requested.toLowerCase() : 'albums';
    this.sections.set(session, section);
    let result = await request(service, 'browse', {hierarchy: 'browse', multi_session_key: session, ...zoneOptions(zone), pop_all: true});
    if (['albums', 'artists'].includes(section)) result = await this.openNamed(service, zone, session, result, 'library');
    result = await this.openNamed(service, zone, session, result, section);
    if (!result) return this.save(session, {status: 'ready', hierarchy: 'browse', level: 0, title: section[0].toUpperCase() + section.slice(1), section, section_root: true, breadcrumb: `LIBRARY / ${section.toUpperCase()}`, items: [], can_back: false, has_more: false, message: 'This section is not available from Roon.', error: true});
    return this.follow(service, session, 'browse', result);
  }

  async search(service, zone, session, query, source = 'library', categoryFilter = null) {
    if (!query) return this._run(session, 'root', {});
    this.searchSources.set(session, source === 'all' ? 'all' : source === 'tidal' ? 'tidal' : 'library');
    this.save(session, {status: 'ready', hierarchy: source === 'tidal' ? 'browse' : 'search', level: 0, section: 'search', search_source: this.searchSources.get(session), title: source === 'tidal' ? 'TIDAL Search' : 'Search', items: [], can_back: false, has_more: false});
    if (source === 'tidal') {
      const options = {hierarchy: 'browse', multi_session_key: session, ...zoneOptions(zone)};
      const root = await request(service, 'browse', {...options, pop_all: true});
      const tidal = await this.openNamed(service, zone, session, root, 'tidal');
      if (!tidal || tidal.is_error || tidal.action !== 'list') return this.searchUnavailable(session, 'TIDAL is not available in Roon. Check that your TIDAL account is connected in Roon Settings → Services.');
      const menu = await request(service, 'load', {...options, level: tidal.list.level, offset: 0, count: 100});
      const prompts = (menu.items || []).filter(item => item.input_prompt && /search/i.test(item.title));
      const prompt = prompts.find(item => /^search$/i.test(item.title.trim())) || prompts[0];
      if (!prompt?.item_key) return this.searchUnavailable(session, 'This Roon server does not expose TIDAL search to external controllers. Library search is still available.');
      const result = await request(service, 'browse', {...options, item_key: prompt.item_key, input: query});
      return this.follow(service, session, 'browse', result);
    }
    // Roon's search hierarchy includes library and connected catalogue hits,
    // already ordered by the core; do not split it into service-specific queries.
    // The search hierarchy takes input on the root browse request. Opening
    // it without input returns "No Results", not an input_prompt item.
    const result = await request(service, 'browse', {hierarchy: 'search', multi_session_key: session, ...zoneOptions(zone), pop_all: true, input: query});
    const root = await this.follow(service, session, 'search', result);
    const categoryOrder = ['artists', 'albums', 'tracks'];
    const allCategories = root.items.filter(item => /^(albums|artists|tracks|playlists|composers|works)$/i.test(item.title.trim()) && item.item_key);
    const categories = allCategories.filter(item => categoryOrder.includes(item.title.trim().toLowerCase()) && (!categoryFilter || item.title.trim().toLowerCase() === categoryFilter)).sort((a, b) => categoryOrder.indexOf(a.title.trim().toLowerCase()) - categoryOrder.indexOf(b.title.trim().toLowerCase()));
    if (!categories.length) return root;
    const groups = await Promise.all(categories.map(async (category, index) => {
      const items = [], routes = {};
      const child = `${session}-preview-${index}`;
      this.sections.set(child, 'search');
      try {
        // Independent Roon sessions keep result keys valid while other groups load.
        const fresh = await request(service, 'browse', {hierarchy: 'search', multi_session_key: child, ...zoneOptions(zone), pop_all: true, input: query});
        const freshRoot = await this.follow(service, child, 'search', fresh);
        const match = freshRoot.items.find(item => item.title === category.title);
        if (!match?.item_key) return {items: [category], routes};
        const opened = await request(service, 'browse', {hierarchy: 'search', multi_session_key: child, ...zoneOptions(zone), item_key: match.item_key});
        const group = await this.follow(service, child, 'search', opened);
        if (group.error || !group.items.length) return {items: group.error ? [category] : [], routes};
        this.save(child, {...group, search_origin: {session, level: group.level}});
        items.push({title: category.title.toUpperCase(), hint: 'header'});
        for (const [position, item] of group.items.filter(item => item.hint !== 'header' && !item.action).slice(0, 5).entries()) {
          const key = `preview-${index}-${position}`;
          routes[key] = {session: child, key: item.item_key};
          items.push({...item, result_type: category.title.toLowerCase(), item_key: item.item_key ? key : null});
        }
        const key = `preview-${index}-all`;
        routes[key] = {session: child};
        items.push({title: `View all ${category.title.toLowerCase()}`, subtitle: category.subtitle, item_key: key});
      } catch (_) {
        // Keep a usable category link if a catalogue cannot load its preview.
        items.push(category);
      }
      return {items, routes};
    }));
    const items = groups.flatMap(group => group.items), routes = Object.assign({}, ...groups.map(group => group.routes));
    const direct = root.items.filter(item => !allCategories.includes(item));
    if (direct.length) items.unshift({title: 'TOP RESULTS', hint: 'header'}, ...direct);
    return this.save(session, {...root, items, search_routes: routes, layout: 'list', show_labels: true, has_more: false, count: items.length});
  }

  searchUnavailable(session, message) {
    return this.save(session, {status: 'ready', hierarchy: 'browse', level: 0, section: 'search', search_source: 'tidal', title: 'TIDAL Search', items: [], can_back: false, has_more: false, message, error: true});
  }

  async follow(service, session, hierarchy, result, fallbackImageKey = null) {
    if (result.action === 'message' || result.is_error) {
      const state = this.sessions.get(session) || {status: 'ready', hierarchy, title: 'Browse', items: [], can_back: false, has_more: false};
      return this.save(session, {...state, message: String(result.message || (result.is_error ? 'Roon could not complete that action.' : 'Done.')), error: Boolean(result.is_error)});
    }
    if (result.action !== 'list' || !result.list) {
      const state = this.sessions.get(session) || {status: 'ready', hierarchy, title: 'Browse', items: [], can_back: false, has_more: false};
      return this.save(session, {...state, message: 'Done.', error: false});
    }
    const loaded = await request(service, 'load', {hierarchy, multi_session_key: session, level: result.list.level, offset: 0, count: PAGE_SIZE});
    return this.store(session, hierarchy, loaded.list || result.list, loaded.items || [], '', fallbackImageKey, Number(loaded.offset || 0));
  }

  store(session, hierarchy, list, items, message, fallbackImageKey = null, loadedOffset = 0) {
    const level = Number(list?.level || 0);
    let normalised = withAlbumArtist(withFallbackImage(libraryItems(list, (items || []).map(publicItem)), fallbackImageKey));
    normalised = normalised.map(item => /^play genre$/i.test(item.title) ? {...item, title: 'Shuffle Genre', action: true, shuffle_genre: true} : item);
    if (hierarchy === 'browse' && level === 0) normalised = rootItems(normalised);
    const presentation = browserLayout(hierarchy, level, list, normalised);
    const filteredLibrary = /^library$/i.test(String(list?.title || '').trim());
    const count = filteredLibrary ? normalised.length : Number(list?.count ?? normalised.length);
    const section = this.sections.get(session) || '';
    const sectionTitle = section ? section[0].toUpperCase() + section.slice(1) : '';
    const sectionRoot = Boolean(section && String(list?.title || '').trim().toLowerCase() === section);
    const tracks = normalised.filter(item => !item.action && item.hint !== 'header');
    const albumProfile = normalised.some(item => item.action && /^play album$/i.test(item.title)) && tracks.length ? {
      name: String(list?.title || ''), artist: tracks[0].subtitle || '',
      image_key: list?.image_key || fallbackImageKey || tracks[0].image_key || null,
      // Only display a write-up supplied by the core; never invent one.
      review: typeof list?.review === 'string' ? list.review : '',
    } : null;
    return this.save(session, {
      status: 'ready', hierarchy, level, title: presentation.layout === 'home' ? 'Browse' : String(list?.title || (hierarchy === 'search' ? 'Search' : 'Browse')),
      subtitle: String(list?.subtitle || ''), count, offset: Number(loadedOffset || list?.display_offset || 0),
      items: normalised, section, search_source: this.searchSources.get(session), section_root: sectionRoot, breadcrumb: sectionRoot ? `LIBRARY / ${section.toUpperCase()}` : `${sectionTitle.toUpperCase()} / ${String(list?.title || '').toUpperCase()}`,
      // Nested album collections (for example Genre -> Pop/Rock) need the
      // same alphabetical navigation as the library album grid once their
      // result set spans more than one page.
      alpha_scrub: (sectionRoot && ['albums', 'artists'].includes(section)) || (presentation.layout === 'covers' && count > normalised.length), can_back: !sectionRoot && (hierarchy !== 'browse' || Number(list?.level || 0) > 0),
      has_more: !filteredLibrary && presentation.layout !== 'home' && Number(loadedOffset || 0) + normalised.length < count,
      fallback_image_key: fallbackImageKey, message, error: false,
      ...(albumProfile ? {album_profile: albumProfile} : {}),
      action_menu: normalised.length > 0 && normalised.every(item => item.action || item.hint === 'header') && normalised.some(item => /^play now$/i.test(item.title)),
      ...(normalised.some(item => /^play artist(?: radio)?$/i.test(item.title)) && this.artistContexts.has(session + ':' + list.title) ? {artist_profile:this.artistContexts.get(session + ':' + list.title)} : {}),
      ...presentation
    });
  }

  async loadMore(service, session) {
    const state = this.sessions.get(session);
    if (!state || !state.has_more) return state || this._run(session, 'root', {});
    const sorted = this.sortedCollections.get(session);
    if (state.section_root && state.sort_order && sorted) {
      const items = sorted.slice(0, state.items.length + PAGE_SIZE);
      return this.save(session, {...state, items, has_more: items.length < sorted.length});
    }
    const nextOffset = Number(state.offset || 0) + state.items.length;
    const loaded = await request(service, 'load', {hierarchy: state.hierarchy, multi_session_key: session, level: state.level, offset: nextOffset, count: PAGE_SIZE});
    const items = withAlbumArtist([...state.items, ...withFallbackImage((loaded.items || []).map(publicItem), state.fallback_image_key)]);
    const count = Number(loaded.list?.count ?? state.count);
    return this.save(session, {...state, items, count, has_more: Number(state.offset || 0) + items.length < count, message: ''});
  }

  async sortCollection(service, session, order) {
    const state = this.sessions.get(session);
    if (!state?.section_root || state.section !== 'albums') return state;
    if (!['title', 'reverse', 'artist'].includes(order)) throw new Error('Unsupported album sort');
    if (state.count > 10000) throw new Error('This collection is too large to sort safely');
    let items = []; const started = Date.now();
    while (items.length < state.count) {
      if (Date.now() - started > 30000) throw new Error('Album sorting timed out; please retry');
      const loaded = await request(service, 'load', {hierarchy: state.hierarchy, multi_session_key: session, level: state.level, offset: items.length, count: 200});
      if (!loaded.items?.length) throw new Error('Could not load the complete album collection');
      items.push(...loaded.items.map(publicItem));
    }
    const compare = (a, b) => String(a || '').localeCompare(String(b || ''), undefined, {numeric: true, sensitivity: 'base'});
    items.sort((a, b) => (order === 'artist' ? compare(a.subtitle, b.subtitle) : 0) || compare(a.title, b.title) * (order === 'reverse' ? -1 : 1));
    this.sortedCollections.set(session, items);
    return this.save(session, {...state, items: items.slice(0, PAGE_SIZE), offset: 0, sort_order: order, alpha_scrub: true, has_more: items.length > PAGE_SIZE});
  }

  async jumpTo(service, session, letter) {
    const state = this.sessions.get(session);
    if (!state?.alpha_scrub || !state.count) return state || this.openSection(service, this.zone(), session, 'albums');
    const target = String(letter || 'A').toUpperCase().replace(/[^A-Z]/g, '').slice(0, 1) || 'A';
    const sorted = this.sortedCollections.get(session);
    if (state.section_root && state.sort_order && sorted) {
      const field = state.sort_order === 'artist' ? 'subtitle' : 'title';
      const initial = item => {
        const first = String(item?.[field] || '').trim().replace(/^the\s+/i, '').normalize('NFKD').toUpperCase()[0];
        return /^[A-Z]$/.test(first || '') ? first : 'A';
      };
      let offset = sorted.findIndex(item => initial(item) === target);
      if (offset < 0) offset = sorted.findIndex(item => state.sort_order === 'reverse' ? initial(item) <= target : initial(item) >= target);
      if (offset < 0) offset = Math.max(0, sorted.length - PAGE_SIZE);
      const items = sorted.slice(offset, offset + PAGE_SIZE);
      return this.save(session, {...state, offset, items, has_more: offset + items.length < sorted.length, message: ''});
    }
    const cacheKey = `${session}:${state.section}:${state.level}:${state.count}`;
    let index = this.alphabetIndexes.get(cacheKey);
    if (!index) {
      index = new Map();
      // Roon's ordering is not JavaScript locale ordering (punctuation,
      // articles and accented names differ). Index actual offsets instead.
      for (let start = 0; start < state.count; start += 200) {
        const page = await request(service, 'load', {hierarchy: state.hierarchy, multi_session_key: session, level: state.level, offset: start, count: 200});
        (page.items || []).forEach((item, position) => {
          const first = String(item.title || '').trim().replace(/^the\s+/i, '').normalize('NFKD').toUpperCase()[0];
          const key = /^[A-Z]$/.test(first || '') ? first : 'A';
          if (!index.has(key)) index.set(key, start + position);
        });
      }
      this.alphabetIndexes.set(cacheKey, index);
    }
    const key = [...index.keys()].sort().find(key => key >= target);
    const offset = key ? index.get(key) : Math.max(0, state.count - PAGE_SIZE);
    const loaded = await request(service, 'load', {hierarchy: state.hierarchy, multi_session_key: session, level: state.level, offset, count: PAGE_SIZE});
    const items = withAlbumArtist(withFallbackImage((loaded.items || []).map(publicItem), state.fallback_image_key));
    return this.save(session, {...state, offset, items, count: Number(loaded.list?.count ?? state.count), has_more: offset + items.length < Number(loaded.list?.count ?? state.count), message: ''});
  }

  async loadPrevious(service, session) {
    const state = this.sessions.get(session);
    if (!state?.offset) return state;
    const offset = Math.max(0, state.offset - PAGE_SIZE);
    const loaded = await request(service, 'load', {hierarchy: state.hierarchy, multi_session_key: session, level: state.level, offset, count: state.offset - offset});
    const items = [...withFallbackImage((loaded.items || []).map(publicItem), state.fallback_image_key), ...state.items];
    return this.save(session, {...state, offset, items});
  }

  save(session, state) {
    const origin = this.sessions.get(session)?.search_origin;
    if (origin && !state.search_origin) state = {...state, search_origin: origin};
    this.sessions.set(session, state); return state;
  }

  async completeArtistPage(service, session, state, limit = 500) {
    let complete = state;
    while (complete?.has_more && complete.items.length < limit) complete = await this.loadMore(service, session);
    return complete;
  }

  async completeArtistCatalogue(service, session, state) {
    const overview = await this.completeArtistPage(service, session, state);
    // Roon/TIDAL artist pages commonly expose only four featured albums and a
    // separate Albums/View All action. Follow that collection before merging;
    // otherwise a successful artist lookup silently looks like a tiny catalogue.
    const collection = overview?.items?.find(item => item.item_key && (
      /^(?:view all|more)(?: artist)? albums?$/i.test(item.title.trim()) ||
      (item.action && /^(?:albums?|discography)$/i.test(item.title.trim()))
    ));
    if (!collection) return overview;
    try {
      let expanded = await this._run(session, 'open', {item_key:collection.item_key});
      if (!expanded || expanded.error || expanded.action_menu) return overview;
      expanded = await this.completeArtistPage(service, session, expanded);
      const play = overview.items.find(item => item.action && /^play artist(?: radio)?$/i.test(item.title.trim()));
      const items = play && !expanded.items.some(item => item.action && /^play artist(?: radio)?$/i.test(item.title.trim()))
        ? [play, ...expanded.items] : expanded.items;
      return this.save(session, {
        ...expanded, title:overview.title, artist_profile:overview.artist_profile,
        items, message:'', error:false
      });
    } catch (_) {
      return overview;
    }
  }

  async openExactTidalArtist(service, session, state, name) {
    const sameArtist = candidate => artistCreditMatches(candidate, name) && artistCreditMatches(name, candidate);
    let current = state;
    // TIDAL commonly returns category rows first. Enter Artists explicitly so
    // an album sharing the artist's name can never be mistaken for the artist.
    const category = current.items?.find(item => /^artists?$/i.test(item.title.trim()) && item.item_key);
    if (category) current = await this._run(session, 'open', {item_key:category.item_key});
    let artist = current.items?.find(item => !item.action && item.hint !== 'header' && sameArtist(item.title));
    while (!artist && current.has_more && current.items.length < 500) {
      current = await this.loadMore(service, session);
      artist = current.items?.find(item => !item.action && item.hint !== 'header' && sameArtist(item.title));
    }
    if (!artist?.item_key) return null;
    const opened = await this._run(session, 'open', {item_key:artist.item_key});
    return {session, state:await this.completeArtistCatalogue(service, session, opened)};
  }

  async searchArtistAlbums(service, zone, session, name) {
    const results = await this.search(service, zone, session, name, 'all', 'albums');
    const all = results.items?.find(item => /^view all albums$/i.test(item.title.trim()));
    const route = all?.item_key ? results.search_routes?.[all.item_key] : null;
    const targetSession = route?.session || session;
    let catalogue = route && !route.key ? this.sessions.get(targetSession) : results;
    if (route?.key) catalogue = await this._run(targetSession, 'open', {item_key:route.key});
    if (!catalogue || catalogue.error) return null;
    catalogue = await this.completeArtistPage(service, targetSession, catalogue);
    const sameArtist = credit => artistCreditMatches(credit, name);
    const items = (catalogue.items || []).filter(item =>
      !item.action && item.hint !== 'header' && item.item_key && sameArtist(item.subtitle));
    if (!items.length) return null;
    return {session:targetSession, state:this.save(targetSession, {...catalogue, items, has_more:false})};
  }

  mergeArtistCatalogues(session, name, catalogues) {
    const routes = {}, albums = [], seen = new Set();
    let action = null, profile = null, routeIndex = 0;
    for (const catalogue of catalogues.filter(Boolean)) {
      profile ||= catalogue.state.artist_profile;
      const profileName = catalogue.state.artist_profile?.name;
      const trustedProfile = profileName && artistCreditMatches(profileName, name) && artistCreditMatches(name, profileName);
      for (const item of catalogue.state.items || []) {
        if (!item.item_key || item.hint === 'header') continue;
        const routedKey = `artist-route-${routeIndex++}`;
        routes[routedKey] = {session:catalogue.session, key:item.item_key};
        if (item.action) {
          if (!action && /^play artist(?: radio)?$/i.test(item.title.trim())) action = {...item, item_key:routedKey};
          continue;
        }
        const creditedArtist = item.subtitle?.trim();
        const matchingCredit = creditedArtist && artistCreditMatches(creditedArtist, name);
        if (!matchingCredit && !(trustedProfile && !creditedArtist)) continue;
        const identity = item.title.trim().toLocaleLowerCase().replace(/\s+/g, ' ');
        if (!identity || seen.has(identity)) continue;
        seen.add(identity); albums.push({...item, item_key:routedKey});
      }
    }
    const base = catalogues.find(Boolean)?.state || {status:'ready', hierarchy:'search', level:0};
    return this.save(session, {
      ...base, title:name, artist_profile:profile || {name, image_key:null},
      items:[...(action ? [action] : []), ...albums], count:albums.length,
      offset:0, has_more:false, search_routes:routes, layout:'list', show_labels:true,
      message:'', error:false
    });
  }

  async openArtist(baseSession, name) {
    const service = this.service(), zone = this.zone();
    if (!service || !name) return {status:'unavailable', items:[], can_back:false};
    // Resolve a fresh core-owned artist through the same global Search used by
    // the Search screen. Opening that artist result is the Roon-supported path
    // to its library-first, connected-catalogue album list.
    const prefix = `${baseSession}-artist-link-`;
    for (const collection of [this.sessions, this.sections, this.searchSources]) {
      for (const key of collection.keys()) if (key.startsWith(prefix)) collection.delete(key);
    }
    const request = ++this.artistRequestId;
    const session = `${prefix}${request}-catalogue`;
    const mergedSession = `${prefix}${request}-merged`;
    this.sections.set(session, 'search'); this.activeSessions.set(baseSession, mergedSession);
    const results = await this.search(service, zone, session, name, 'all', 'artists');
    const sameArtist = candidate => artistCreditMatches(candidate, name) && artistCreditMatches(name, candidate);
    let group = '';
    const artist = results.items.find(item => {
      if (item.hint === 'header') { group = item.title; return false; }
      return group === 'ARTISTS' && sameArtist(item.title);
    });
    let library = null;
    if (artist) {
      const route = results.search_routes?.[artist.item_key];
      const target = route?.session || session;
      const opened = await this._run(target, 'open', {item_key:route?.key || artist.item_key});
      library = {session:target, state:await this.completeArtistCatalogue(service, target, opened)};
    }
    let globalAlbums = null;
    const albumSearchSession = `${prefix}${request}-albums`;
    this.sections.set(albumSearchSession, 'search');
    try {
      globalAlbums = await this.searchArtistAlbums(service, zone, albumSearchSession, name);
    } catch (_) {
      // The artist overview remains usable if global connected-service search
      // is temporarily unavailable.
    }
    let tidal = null;
    const tidalSession = `${prefix}${request}-tidal`;
    this.sections.set(tidalSession, 'search');
    try {
      const tidalResults = await this.search(service, zone, tidalSession, name, 'tidal');
      if (!tidalResults.error) tidal = await this.openExactTidalArtist(service, tidalSession, tidalResults, name);
    } catch (_) {
      // A disconnected or temporarily unavailable TIDAL service must not hide
      // albums already resolved from My Catalog.
    }
    if (!library && !globalAlbums && !tidal) return this.save(mergedSession, {
      ...results, title:name, artist_profile:{name,image_key:artist?.image_key || null},
      items:[], count:0, offset:0, has_more:false, search_routes:{}, layout:'list',
      show_labels:true, message:'No albums were returned for this artist.', error:false
    });
    this.activeSessions.set(baseSession, mergedSession);
    return this.mergeArtistCatalogues(mergedSession, name, [library, globalAlbums, tidal]);
  }

  async openLibraryArtist(baseSession, name, session) {
    const service = this.service(), zone = this.zone();
    this.activeSessions.set(baseSession, session);
    let artists = await this.openSection(service, zone, session, 'artists');
    if (artists.error) return artists;
    const wanted = name.trim().toLocaleLowerCase();
    let artist = artists.items.find(item => !item.action && item.title.trim().toLocaleLowerCase() === wanted);
    // The library can contain thousands of artists and the first Browse page
    // is only 30 rows. Scan the same level in bounded chunks to obtain the
    // exact key owned by this fresh session.
    for (let offset = 0; !artist && offset < Math.min(artists.count, 10000); offset += 200) {
      const loaded = await request(service, 'load', {hierarchy:'browse', multi_session_key:session, level:artists.level, offset, count:200});
      const match = (loaded.items || []).find(item => String(item.title || '').trim().toLocaleLowerCase() === wanted);
      if (match) artist = publicItem(match);
    }
    if (!artist?.item_key) return this.save(session, {
      ...artists, items:[], count:0, has_more:false, error:true,
      message:`${name} is not available in Library Artists.`
    });
    // _run derives the profile from the selected row, so retain just the exact
    // library item in the current section state before opening its key.
    artists = this.save(session, {...artists, items:[artist], offset:0, has_more:false});
    const opened = await this._run(session, 'open', {item_key:artist.item_key});
    if (opened?.artist_profile?.name?.trim().toLocaleLowerCase() !== wanted) {
      return this.save(session, {...opened, items:[], count:0, has_more:false, error:true,
        message:'Roon did not open the selected artist. Please try again.'});
    }
    return opened;
  }

  async openArtistAlbum(baseSession, artistName, selected) {
    // Album keys inherit the artist browse session. Resolve the artist again
    // before opening an album so a stale Roon stack can never pair a new artist
    // heading with an old artist's album key.
    let artist = await this.openArtist(baseSession, artistName);
    const session = this.activeSessions.get(baseSession);
    if (!session || artist?.error) return artist;
    const sameAlbum = item => !item.action && item.title === selected.title &&
      (!selected.image_key || !item.image_key || item.image_key === selected.image_key);
    let album = artist.items?.find(sameAlbum);
    while (!album && artist.has_more) {
      artist = await this.loadMore(this.service(), session);
      album = artist.items?.find(sameAlbum);
    }
    if (!album?.item_key) return this.save(session, {...artist, error:true, message:'That album is no longer available for this artist.'});
    const route = artist.search_routes?.[album.item_key];
    if (route?.session) this.activeSessions.set(baseSession, route.session);
    const opened = route?.key
      ? await this._run(route.session, 'open', {item_key:route.key})
      : await this._run(session, 'open', {item_key:album.item_key});
    const actual = String(opened?.album_profile?.name || opened?.title || '').trim();
    if (actual && actual !== selected.title) {
      const openedSession = route?.session || session;
      const restored = await this._run(openedSession, 'back', {});
      return this.save(openedSession, {...restored, error:true, message:'Roon returned a different album. Please try again.'});
    }
    return opened;
  }
}

module.exports = {BrowseManager, artistCreditMatches, browserLayout, formatDuration, isActionItem, libraryItems, publicItem, rootItems, safeSession, withAlbumArtist, withFallbackImage};
