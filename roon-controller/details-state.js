'use strict';

const https = require('https');
const {displayArtist} = require('./artist-name');

let musicBrainzTail = Promise.resolve();
let lastMusicBrainzRequest = 0;

function playingMetadata(zone) {
  const playing = zone?.now_playing || {};
  const lines = playing.three_line || playing.two_line || playing.one_line || {};
  return {
    track: lines.line1 || '', artist: displayArtist(playing), album: lines.line3 || '',
    image_key: playing.image_key || null,
    key: [displayArtist(playing), lines.line3].map(value => String(value || '').trim().toLowerCase()).join('|')
  };
}

const clean = value => String(value || '').trim().toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ');

const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

function musicBrainzJson(path) {
  const run = async () => {
    const wait = Math.max(0, 1100 - (Date.now() - lastMusicBrainzRequest));
    if (wait) await delay(wait);
    lastMusicBrainzRequest = Date.now();
    return new Promise((resolve, reject) => {
      const request = https.get({
        hostname: 'musicbrainz.org', path, timeout: 6000,
        headers: {'Accept': 'application/json', 'User-Agent': 'RoonDeck/1.1.7-beta.4 (https://github.com/impala84/roon-deck)'}
      }, response => {
        let body = '';
        response.setEncoding('utf8');
        response.on('data', chunk => { body += chunk; if (body.length > 1024 * 1024) request.destroy(new Error('MusicBrainz response too large')); });
        response.on('end', () => {
          if (response.statusCode < 200 || response.statusCode >= 300) return reject(new Error(`MusicBrainz HTTP ${response.statusCode}`));
          try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
        });
      });
      request.on('timeout', () => request.destroy(new Error('MusicBrainz timeout')));
      request.on('error', reject);
    });
  };
  const queued = musicBrainzTail.then(run, run);
  musicBrainzTail = queued.catch(() => {});
  return queued;
}

function externalText(url, redirects = 0) {
  const target = new URL(url);
  const allowed = target.hostname === 'wikipedia.org' || target.hostname.endsWith('.wikipedia.org') || target.hostname === 'bandcamp.com' || target.hostname.endsWith('.bandcamp.com') || (target.hostname === 'www.wikidata.org' && /^\/wiki\/Special:EntityData\/Q\d+\.json$/.test(target.pathname));
  if (!allowed || target.protocol !== 'https:') return Promise.reject(new Error('Unsupported metadata source'));
  return new Promise((resolve, reject) => {
    const request = https.get(target, {timeout: 7000, headers: {'Accept': 'text/html,application/json', 'User-Agent': 'RoonDeck/1.1.7-beta.4 (https://github.com/impala84/roon-deck)'}}, response => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', chunk => { body += chunk; if (body.length > 2 * 1024 * 1024) request.destroy(new Error('Metadata response too large')); });
      response.on('end', () => {
        if (response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
          if (redirects >= 3) return reject(new Error('Metadata redirected too many times'));
          let redirected;
          try { redirected = new URL(response.headers.location, target).toString(); } catch (error) { return reject(error); }
          return externalText(redirected, redirects + 1).then(resolve, reject);
        }
        return response.statusCode >= 200 && response.statusCode < 300 ? resolve(body) : reject(new Error(`Metadata HTTP ${response.statusCode}`));
      });
    });
    request.on('timeout', () => request.destroy(new Error('Metadata timeout')));
    request.on('error', reject);
  });
}

function decodeHtml(value) {
  return String(value || '').replace(/<br\s*\/?>/gi, ' ').replace(/<[^>]+>/g, ' ')
    .replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&nbsp;/g, ' ')
    .replace(/&#(\d+);/g, (_, code) => String.fromCodePoint(Number(code))).replace(/\s+/g, ' ').replace(/\s+([.,;:!?])/g, '$1').trim();
}

function clipWriteup(value, limit = 320, sentenceLimit = 2) {
  const text = decodeHtml(value);
  // Do not mistake initials such as R.E.M. for four one-letter sentences.
  const protectedText = text.replace(/\b(?:[A-Za-z]\.){2,}/g, initials => initials.replaceAll('.', '\u2024'));
  const sentences = (protectedText.match(/[^.!?]+(?:[.!?]+(?=\s|$)|$)/g) || []).map(sentence => sentence.replaceAll('\u2024', '.'));
  const brief = sentences.slice(0, sentenceLimit).map(sentence => sentence.trim()).join(' ').trim() || text;
  if (brief.length <= limit) return brief;
  const first = sentences[0]?.trim();
  if (first && first.length <= limit) return first;
  const clipped = brief.slice(0, limit + 1); const sentence = clipped.lastIndexOf('. ');
  return `${clipped.slice(0, sentence > limit * .55 ? sentence + 1 : limit).trim()}…`;
}

function parseBandcampPage(html) {
  const about = html.match(/<div[^>]*class=["'][^"']*tralbum-about[^"']*["'][^>]*>([\s\S]*?)<\/div>/i)?.[1] || '';
  const tags = [...html.matchAll(/<a[^>]*class=["'][^"']*tag[^"']*["'][^>]*>([\s\S]*?)<\/a>/gi)]
    .map(match => decodeHtml(match[1])).filter(Boolean).filter((tag, index, all) => all.indexOf(tag) === index).slice(0, 4);
  return {writeup: clipWriteup(about), tags};
}

function relationResources(...entities) {
  return entities.flatMap(entity => entity?.relations || []).map(relation => relation?.url?.resource).filter(Boolean);
}

async function loadArtistProfile(name, fetchJson = musicBrainzJson, fetchText = externalText) {
  const empty = {name, writeup: '', source: '', type: '', area: '', country: '', formed: '', ended: '', genres: []};
  const escaped = String(name || '').slice(0, 200).replace(/["\\]/g, ' ');
  if (!escaped.trim()) return empty;
  const search = await fetchJson('/ws/2/artist/?query=' + encodeURIComponent('artist:"' + escaped + '"') + '&fmt=json&limit=10');
  const exact = (search.artists || []).filter(artist => clean(artist.name) === clean(name));
  const candidate = chooseArtistCandidate(exact);
  // Do not show the biography of an unrelated same-name artist.
  if (!candidate || !/^[a-f0-9-]{36}$/i.test(candidate.id || '')) {
    const fallback = await loadWikipediaArtistWriteup(name, fetchText);
    return {...empty, ...fallback};
  }
  const artist = await fetchJson('/ws/2/artist/' + candidate.id + '?inc=url-rels+tags&fmt=json');
  const wikiData = relationResources(artist).find(resource=>/^https:\/\/www.wikidata.org\/wiki\/Q\d+$/.test(resource));
  if (wikiData && !relationResources(artist).some(resource=>resource.includes('.wikipedia.org/wiki/'))) {
    try {
      const id = wikiData.split('/').pop();
      const entity = JSON.parse(await fetchText('https://www.wikidata.org/wiki/Special:EntityData/' + id + '.json'));
      const title = entity.entities?.[id]?.sitelinks?.enwiki?.title;
      if (title) artist.relations.push({url:{resource:'https://en.wikipedia.org/wiki/' + encodeURIComponent(title)}});
    } catch (_) {}
  }
  let result = await loadAlbumWriteup(artist, null, fetchText);
  if (!result.writeup) result = await loadWikipediaArtistWriteup(name, fetchText);
  const genres = (artist.tags || []).filter(tag => tag?.name).sort((a,b)=>(b.count||0)-(a.count||0)).map(tag=>tag.name).slice(0,4);
  return {...empty,
    type: artist.type || '', area: artist.area?.name || artist['begin-area']?.name || '', country: artist.country || '',
    formed: artist['life-span']?.begin || '', ended: artist['life-span']?.ended ? (artist['life-span']?.end || '') : '', genres,
    writeup: result.writeup, full_writeup: result.full_writeup || result.writeup, source: result.source};
}

async function loadWikipediaArtistWriteup(name, fetchText = externalText) {
  const empty = {writeup: '', full_writeup: '', source: ''};
  const artistName = String(name || '').trim();
  if (!artistName) return empty;
  const titles = [...new Set([artistName, `${artistName} (band)`, `${artistName} (musician)`, `${artistName} (singer)`])];
  for (const title of titles) {
    try {
      const encoded = encodeURIComponent(title.replace(/\s+/g, '_'));
      const summary = JSON.parse(await fetchText(`https://en.wikipedia.org/api/rest_v1/page/summary/${encoded}`));
      const pageTitle = clean(summary.title || '');
      const wanted = clean(artistName);
      const context = clean(`${summary.description || ''} ${summary.extract || ''}`);
      const musicProfile = /\b(band|musical group|musician|singer|rapper|composer|disc jockey|record producer|recording artist|duo|trio|orchestra)\b/.test(context);
      if (summary.type !== 'disambiguation' && summary.extract && pageTitle.startsWith(wanted) && musicProfile) {
        return {writeup: clipWriteup(summary.extract), full_writeup: decodeHtml(summary.extract), source: 'Wikipedia'};
      }
    } catch (_) {}
  }
  return empty;
}

function chooseArtistCandidate(artists) {
  if ((artists || []).length === 1) return artists[0];
  const ranked = [...(artists || [])].sort((a,b)=>Number(b.score || 0)-Number(a.score || 0));
  // MusicBrainz commonly returns an alias or tribute act with the same exact
  // display name. Accept the canonical result only when its search score is
  // decisively ahead; tied names remain deliberately unresolved.
  if (Number(ranked[0]?.score || 0) >= 95 && Number(ranked[0]?.score || 0) - Number(ranked[1]?.score || 0) >= 5) return ranked[0];
  return null;
}

async function loadAlbumWriteup(group, release, fetchText = externalText) {
  const resources = relationResources(group, release);
  const wikipedia = resources.find(resource => { try { const host = new URL(resource).hostname; return host === 'wikipedia.org' || host.endsWith('.wikipedia.org'); } catch (_) { return false; } });
  if (wikipedia) {
    try {
      const target = new URL(wikipedia); const marker = '/wiki/'; const index = target.pathname.indexOf(marker);
      if (index >= 0) {
        const title = target.pathname.slice(index + marker.length); const summaryUrl = `https://${target.hostname}/api/rest_v1/page/summary/${title}`;
        const summary = JSON.parse(await fetchText(summaryUrl));
        if (summary.type !== 'disambiguation' && summary.extract) return {writeup: clipWriteup(summary.extract), full_writeup: decodeHtml(summary.extract), source: 'Wikipedia', tags: []};
      }
    } catch (_) {}
  }
  const bandcamp = resources.find(resource => { try { const host = new URL(resource).hostname; return host === 'bandcamp.com' || host.endsWith('.bandcamp.com'); } catch (_) { return false; } });
  if (bandcamp) {
    try {
      const parsed = parseBandcampPage(await fetchText(bandcamp));
      if (parsed.writeup || parsed.tags.length) return {...parsed, source: parsed.writeup ? 'Artist notes via Bandcamp' : 'Bandcamp'};
    } catch (_) {}
  }
  return {writeup: '', full_writeup: '', source: '', tags: []};
}

async function loadWikipediaAlbumWriteup(album, artist, fetchText = externalText) {
  const empty = {writeup: '', source: '', tags: []};
  const albumName = String(album || '').trim();
  const artistName = String(artist || '').trim();
  if (!albumName || !artistName) return empty;
  const titles = [...new Set([albumName, `${albumName} (album)`, `${albumName} (${artistName} album)`])];
  for (const title of titles) {
    try {
      const encoded = encodeURIComponent(title.replace(/\s+/g, '_'));
      const summary = JSON.parse(await fetchText(`https://en.wikipedia.org/api/rest_v1/page/summary/${encoded}`));
      const context = clean(`${summary.description || ''} ${summary.extract || ''}`);
      const cleanedArtist = clean(artistName);
      const artistWords = cleanedArtist.split(' ').filter(word => word.length > 1 && !['the','and','with','feat','featuring'].includes(word));
      const compactArtist = cleanedArtist.replace(/\s+/g, '');
      const compactContext = context.replace(/\s+/g, '');
      const artistMatch = (artistWords.length && artistWords.every(word => context.includes(word))) || (compactArtist.length >= 2 && compactContext.includes(compactArtist));
      const albumMatch = /\b(album|record|mixtape|extended play| ep)\b/.test(context);
      if (summary.type !== 'disambiguation' && summary.extract && artistMatch && albumMatch) {
        return {writeup: clipWriteup(summary.extract), full_writeup: decodeHtml(summary.extract), source: 'Wikipedia', tags: []};
      }
    } catch (_) {}
  }
  return empty;
}

async function loadAlbumNotes(album, artist, fetchJson = musicBrainzJson, fetchText = externalText) {
  const empty = {album, artist, writeup: '', source: ''};
  try {
    const direct = await loadWikipediaAlbumWriteup(album, artist, fetchText);
    if (direct.writeup) return {...empty, writeup: direct.writeup, source: direct.source};
  } catch (_) {}
  try {
    const facts = await loadMusicBrainzMetadata(album, artist, 0, fetchJson, false, fetchText);
    return {...empty, writeup: facts.writeup || '', source: facts.writeup_source || ''};
  } catch (_) {
    return empty;
  }
}

function creditedArtist(group) {
  return (group?.['artist-credit'] || []).map(credit => credit?.name || credit?.artist?.name || '').join('');
}

function artistCandidates(artist) {
  const original = String(artist || '').trim();
  if (!original) return [];
  const split = original.split(/\s+(?:\/|feat\.?|featuring)\s+/i).map(value => value.trim()).filter(Boolean);
  return [...new Set([...(split.length > 1 ? split : []), original])];
}

function albumCandidates(album) {
  const original = String(album || '').trim();
  if (!original) return [];
  const base = original.replace(/\s*[\[(](?:(?:\d{4}\s+)?(?:re)?master(?:ed)?(?:\s+\d{4})?|(?:\d+(?:st|nd|rd|th)\s+)?anniversary(?:\s+edition)?|(?:deluxe|expanded|special)\s+edition)[\])]/ig, '').trim();
  return [...new Set([original, base].filter(Boolean))];
}

function chooseMusicBrainzGroup(groups, album, artist) {
  const wantedAlbum = clean(album); const wantedArtists = artistCandidates(artist).map(clean);
  const ranked = (groups || []).map(group => {
    const title = clean(group.title); const credit = clean(creditedArtist(group));
    const exactTitle = title === wantedAlbum; const exactArtist = !wantedArtists.length || wantedArtists.includes(credit);
    const relatedArtist = wantedArtists.some(candidate => candidate && (credit.includes(candidate) || candidate.includes(credit)));
    return {group, score: (exactTitle ? 1000 : title.includes(wantedAlbum) || wantedAlbum.includes(title) ? 200 : 0) + (exactArtist ? 500 : relatedArtist ? 100 : 0) + Number(group.score || 0)};
  }).filter(candidate => candidate.score >= 1400).sort((a, b) => b.score - a.score);
  return ranked[0]?.group || null;
}

function chooseUniqueTitleGroup(groups, album) {
  const wantedAlbum = clean(album);
  const exact = (groups || []).filter(group => clean(group?.title) === wantedAlbum);
  return exact.length === 1 ? exact[0] : null;
}

function preferredMusicBrainzRelease(group) {
  const releases = group?.releases || [];
  return releases.filter(release => release.status === 'Official').sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')))[0] || releases[0] || {};
}

function countryName(code) {
  if (!code) return '';
  if (code === 'XW') return 'Worldwide';
  try { return new Intl.DisplayNames(['en'], {type: 'region'}).of(code) || code; } catch (_) { return code; }
}

function musicBrainzFacts(group, trackCount = 0, releaseDetails = null) {
  const releases = group?.releases || [];
  const preferredRelease = releaseDetails || preferredMusicBrainzRelease(group);
  const genres = (group?.genres?.length ? group.genres : group?.tags || [])
    .filter(item => item?.name).sort((a, b) => Number(b.count || 0) - Number(a.count || 0)).slice(0, 3).map(item => item.name);
  const releaseDate = group?.['first-release-date'] || preferredRelease.date || '';
  const types = [group?.['primary-type'], ...(group?.['secondary-types'] || [])].filter(Boolean);
  return {
    release_date: releaseDate,
    year: /^\d{4}/.test(releaseDate) ? releaseDate.slice(0, 4) : '',
    genres,
    type: types.join(' · '),
    country: countryName(preferredRelease.country),
    label: (preferredRelease?.['label-info'] || []).map(item => item?.label?.name).filter(Boolean).filter((name, index, all) => all.indexOf(name) === index).join(' · '),
    format: (preferredRelease?.media || []).map(item => item?.format).filter(Boolean).filter((format, index, all) => all.indexOf(format) === index).join(' · '),
    edition_count: releases.length || 0,
    track_count: Number(trackCount || (preferredRelease?.media || []).reduce((total, medium) => total + Number(medium?.['track-count'] || 0), 0)),
    source: 'MusicBrainz'
  };
}

async function loadMusicBrainzMetadata(album, artist, trackCount = 0, fetchJson = musicBrainzJson, strictArtist = false, fetchText = externalText) {
  if (!album || !artist) return musicBrainzFacts(null, trackCount);
  let match = null;
  for (const albumName of albumCandidates(album)) {
    for (const candidate of artistCandidates(artist)) {
      const query = `releasegroup:"${albumName.replace(/["\\]/g, ' ')}" AND artist:"${candidate.replace(/["\\]/g, ' ')}"`;
      const search = await fetchJson(`/ws/2/release-group/?query=${encodeURIComponent(query)}&fmt=json&limit=5`);
      match = chooseMusicBrainzGroup(search?.['release-groups'], albumName, artist);
      if (match) break;
    }
    if (match) break;
  }
  if (!match && !strictArtist) {
    const query = `releasegroup:"${album.replace(/["\\]/g, ' ')}"`;
    const search = await fetchJson(`/ws/2/release-group/?query=${encodeURIComponent(query)}&fmt=json&limit=10`);
    match = chooseUniqueTitleGroup(search?.['release-groups'], album);
  }
  if (!match?.id) {
    const writeup = await loadWikipediaAlbumWriteup(album, artist, fetchText);
    return {...musicBrainzFacts(null, trackCount), writeup: writeup.writeup, writeup_source: writeup.source};
  }
  const group = await fetchJson(`/ws/2/release-group/${encodeURIComponent(match.id)}?inc=genres+releases+url-rels&fmt=json`);
  const preferred = preferredMusicBrainzRelease(group);
  let release = null;
  if (preferred?.id) {
    try { release = await fetchJson(`/ws/2/release/${encodeURIComponent(preferred.id)}?inc=labels+recordings+url-rels&fmt=json`); } catch (_) {}
  }
  let writeup = await loadAlbumWriteup(group, release, fetchText);
  if (!writeup.writeup) writeup = await loadWikipediaAlbumWriteup(album, artist, fetchText);
  const facts = musicBrainzFacts(group, trackCount, release);
  facts.genres = [...new Set([...facts.genres, ...writeup.tags])].slice(0, 4);
  return {...facts, writeup: writeup.writeup, full_writeup: writeup.full_writeup || writeup.writeup, writeup_source: writeup.source};
}

function chooseItem(items, title) {
  const wanted = clean(title);
  if (!wanted) return null;
  return (items || []).filter(item => item?.item_key && item.hint !== 'header')
    .map(item => ({item, score: clean(item.title) === wanted ? 3 : clean(item.title).includes(wanted) || wanted.includes(clean(item.title)) ? 2 : 0}))
    .filter(candidate => candidate.score > 0).sort((a, b) => b.score - a.score)[0]?.item || null;
}

const request = (service, method, options) => new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error('Roon metadata lookup timed out')), 8000);
  service[method](options, (error, result) => { clearTimeout(timer); error ? reject(new Error(String(error))) : resolve(result || {}); });
});

async function searchItem(service, zoneId, query, category, title, session) {
  await request(service, 'browse', {hierarchy: 'search', pop_all: true, input: query, multi_session_key: session, zone_or_output_id: zoneId});
  let loaded = await request(service, 'load', {hierarchy: 'search', multi_session_key: session, offset: 0, count: 60});
  let item = chooseItem(loaded.items, title);
  if (item && clean(item.title) === clean(title)) return item;
  const group = chooseItem(loaded.items, category);
  if (!group) return null;
  await request(service, 'browse', {hierarchy: 'search', item_key: group.item_key, multi_session_key: session, zone_or_output_id: zoneId});
  loaded = await request(service, 'load', {hierarchy: 'search', multi_session_key: session, offset: 0, count: 60});
  return chooseItem(loaded.items, title);
}

async function albumContents(service, zoneId, item, session) {
  if (!item?.item_key) return {tracks: [], library_status: 'unknown'};
  await request(service, 'browse', {hierarchy: 'search', item_key: item.item_key, multi_session_key: session, zone_or_output_id: zoneId});
  const loaded = await request(service, 'load', {hierarchy: 'search', multi_session_key: session, offset: 0, count: 40});
  const items = loaded.items || [];
  const add = items.find(candidate => candidate.item_key && /^\+?\s*add to library$/i.test(String(candidate.title || '').trim()));
  const remove = items.find(candidate => candidate.item_key && /^remove from library$/i.test(String(candidate.title || '').trim()));
  return {
    tracks: items.filter(candidate => candidate.hint !== 'header' && candidate.title && candidate.hint !== 'action')
      .slice(0, 30).map(candidate => ({title: candidate.title, subtitle: candidate.subtitle || ''})),
    library_status: add ? 'not_in_library' : remove ? 'in_library' : 'unknown'
  };
}

async function loadDetails(service, zone, enrich = loadMusicBrainzMetadata) {
  const metadata = playingMetadata(zone);
  const base = {status: 'ready', ...metadata, album_image_key: metadata.image_key, artist_image_key: null, subtitle: '', tracks: []};
  if (!service || (!metadata.album && !metadata.artist)) return base;
  const stamp = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const enrichment = Promise.resolve().then(() => enrich(metadata.album, metadata.artist, 0)).catch(() => null);
  const [albumResult, artistResult] = await Promise.allSettled([
    metadata.album ? searchItem(service, zone.zone_id, [metadata.album, metadata.artist].filter(Boolean).join(' '), 'Albums', metadata.album, `${stamp}-album`) : null,
    metadata.artist ? searchItem(service, zone.zone_id, metadata.artist, 'Artists', metadata.artist, `${stamp}-artist`) : null
  ]);
  const album = albumResult.status === 'fulfilled' ? albumResult.value : null;
  const artist = artistResult.status === 'fulfilled' ? artistResult.value : null;
  base.album_image_key = album?.image_key || metadata.image_key;
  base.artist_image_key = artist?.image_key || null;
  base.subtitle = album?.subtitle || artist?.subtitle || '';
  try {
    const contents = await albumContents(service, zone.zone_id, album, `${stamp}-album`);
    base.tracks = contents.tracks; base.library_status = contents.library_status;
  } catch (_) { base.library_status = 'unknown'; }
  base.metadata = musicBrainzFacts(null, base.tracks.length);
  const facts = await enrichment;
  if (facts) base.metadata = {...facts, track_count: facts.track_count || base.tracks.length};
  base.metadata_retryable = !facts;
  return base;
}

module.exports = {clipWriteup, loadArtistProfile, loadWikipediaArtistWriteup, chooseArtistCandidate, playingMetadata, chooseItem, artistCandidates, albumCandidates, chooseMusicBrainzGroup, chooseUniqueTitleGroup, musicBrainzFacts, parseBandcampPage, loadAlbumWriteup, loadWikipediaAlbumWriteup, loadAlbumNotes, loadMusicBrainzMetadata, loadDetails};
