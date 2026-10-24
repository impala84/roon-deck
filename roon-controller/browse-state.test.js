'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {BrowseManager, artistCreditMatches, browserLayout, formatDuration, libraryItems, publicItem, rootItems, safeSession, withAlbumArtist, withFallbackImage} = require('./browse-state');

test('artist album credits tolerate ampersands, conjunctions and leading articles', () => {
  assert.equal(artistCreditMatches('Tommy James and The Shondells', 'Tommy James & the Shondells'), true);
  assert.equal(artistCreditMatches('Guest Singer, The Example Band', 'Example Band'), true);
  assert.equal(artistCreditMatches('Third Eye Blind • 1997', 'Third Eye Blind'), true);
  assert.equal(artistCreditMatches('Someone Else', 'Example Band'), false);
  assert.equal(artistCreditMatches("Junior Wells' Chicago Blues Band/Buddy Guy", 'Chicago'), false);
  assert.equal(artistCreditMatches('Chicago Symphony Orchestra/Sir Georg Solti', 'Chicago'), false);
  assert.equal(artistCreditMatches('Chicago, Guest Artist', 'Chicago'), true);
  assert.equal(artistCreditMatches('Chicago Transit Authority', 'Chicago'), false);
});

test('album sorting loads the whole collection and paginates owned keys without playback', async () => {
  const albums = Array.from({length:65}, (_, i) => ({title:`Album ${65-i}`, subtitle:`Artist ${i%3}`, item_key:`key-${i}`}));
  const service = {load(options, callback) {callback(null, {items:albums.slice(options.offset, options.offset+options.count)});}};
  const manager = new BrowseManager(() => service, () => ({}));
  manager.sections.set('albums', 'albums');
  manager.store('albums', 'browse', {title:'Albums', level:1, count:65}, albums.slice(0,30), '');
  const sorted = await manager.sortCollection(service, 'albums', 'title');
  assert.equal(sorted.items[0].title, 'Album 1');
  assert.equal(sorted.alpha_scrub, true);
  const jumped = await manager.jumpTo(service, 'albums', 'A');
  assert.equal(jumped.items[0].title, 'Album 1');
  assert.equal(jumped.sort_order, 'title');
  const more = await manager.loadMore(service, 'albums');
  assert.equal(more.items.length,60);
  assert.equal(new Set(more.items.map(item=>item.item_key)).size,60);
  await assert.rejects(manager.sortCollection(service, 'albums', 'date'), /Unsupported/);
});

test('album detail exposes one cover and honest optional metadata without altering track keys', () => {
  const manager = new BrowseManager(() => ({}), () => ({}));
  const state = manager.store('album', 'browse', {title:'Example Album', level:3, count:3}, [
    {title:'Play Album', hint:'action', item_key:'play'},
    {title:'1. First', subtitle:'Example Artist', item_key:'first'},
    {title:'2. Second', subtitle:'Example Artist', item_key:'second'},
  ], '', 'cover');
  assert.deepEqual(state.album_profile, {name:'Example Album', artist:'Example Artist', image_key:'cover', review:''});
  assert.equal(state.items[1].item_key, 'first');
  assert.equal(state.action_menu, false);
  const menu = manager.store('album', 'browse', {title:'First', level:4}, [
    {title:'Play Now', hint:'action', item_key:'now'}, {title:'Add Next', hint:'action', item_key:'next'},
  ], '');
  assert.equal(menu.action_menu, true);
  assert.equal(menu.album_profile, undefined);
});

test('artist links open the exact global Search artist and retain its core-owned catalogue', async () => {
  const calls = [], paths = new Map();
  const service = {
    browse(options, done) {
      calls.push({...options});
      assert.equal(options.hierarchy, 'search');
      if (options.pop_all) { assert.equal(options.input, 'Example Artist'); paths.set(options.multi_session_key, 'root'); return done(false, {action:'list',list:{title:'Search',level:0,count:2}}); }
      if (options.item_key === 'artists-category') { paths.set(options.multi_session_key, 'artists'); return done(false, {action:'list',list:{title:'Artists',level:1,count:1}}); }
      if (options.item_key === 'albums-category') { paths.set(options.multi_session_key, 'albums'); return done(false, {action:'list',list:{title:'Albums',level:1,count:3}}); }
      assert.equal(options.item_key, 'catalogue-artist'); paths.set(options.multi_session_key, 'artist');
      done(false, {action:'list', list:{title:'Example Artist', level:3,count:1}});
    },
    load(options, done) {
      const path = paths.get(options.multi_session_key);
      if (path === 'root') return done(false, {list:{title:'Search',level:0,count:2},items:[{title:'Artists',item_key:'artists-category'},{title:'Albums',item_key:'albums-category'}]});
      if (path === 'artists') return done(false, {list:{title:'Artists',level:1,count:1},items:[{title:'Example Artist',item_key:'catalogue-artist',image_key:'portrait'}]});
      if (path === 'albums') return done(false, {list:{title:'Albums',level:1,count:3},items:[
        {title:'Catalogue Album',subtitle:'',item_key:'catalogue-album'},
        {title:'Collaboration',subtitle:'Guest, Example Artist',item_key:'collaboration'},
        {title:'Wrong Artist Album',subtitle:'Someone Else',item_key:'wrong-album'}]});
      done(false, {list:{title:'Example Artist', level:3,count:3}, items:[
        {title:'Play Artist',hint:'action',item_key:'play'},
        {title:'Catalogue Album',subtitle:'Example Artist',item_key:'catalogue-album',image_key:'cover'},
        {title:'Collaboration',subtitle:'Guest, Example Artist',item_key:'collaboration',image_key:'other'}]});
    },
  };
  const manager = new BrowseManager(() => service, () => ({zone_id:'zone'}));
  const result = await manager.run('links', 'artist', {name:'Example Artist'});
  assert.deepEqual(result.artist_profile, {name:'Example Artist', image_key:'portrait'});
  assert.equal(result.search_routes[result.items.find(item => item.title === 'Catalogue Album').item_key].key, 'catalogue-album');
  assert.equal(result.search_routes[result.items.find(item => item.title === 'Collaboration').item_key].key, 'collaboration');
  assert.equal(result.items.some(item => item.title === 'Wrong Artist Album'), false);
  assert.ok(calls.some(call => call.hierarchy === 'search'));
  assert.ok(calls.some(call => call.hierarchy === 'browse'), 'the connected TIDAL catalogue is queried separately');
  await manager.run('links', 'artist', {name:'Example Artist'});
  const artistSessions = [...manager.sessions.keys()].filter(key => key.startsWith('pihome-links-artist-link-'));
  assert.equal(artistSessions.length, 6, 'only the current artist, global album search, TIDAL and merged hierarchies remain');
  assert.ok(artistSessions.every(key => /-2(?:-|$)/.test(key)), 'the previous artist hierarchies are discarded');
});

test('artist links never replace a missing global result with a library-only catalogue', async () => {
  const hierarchies = [];
  const service = {
    browse(options, done) {
      hierarchies.push(options.hierarchy);
      if (options.hierarchy === 'search') return done(false, {action:'list',list:{title:'Search',level:0,count:0}});
      if (options.pop_all) return done(false, {action:'list',list:{title:'Browse',level:0,count:1}});
      if (options.item_key === 'library') return done(false, {action:'list',list:{title:'Library',level:1,count:1}});
      if (options.item_key === 'artists') return done(false, {action:'list',list:{title:'Artists',level:2,count:1}});
      return done(false, {action:'list',list:{title:'Known Artist',level:3,count:2}});
    },
    load(options, done) {
      if (options.hierarchy === 'search') return done(false, {list:{title:'Search',level:0,count:0},items:[]});
      if (options.level === 0) return done(false, {items:[{title:'Library',item_key:'library'}]});
      if (options.level === 1) return done(false, {items:[{title:'Artists',item_key:'artists'}]});
      if (options.level === 2) return done(false, {list:{title:'Artists',level:2,count:1},items:[{title:'Known Artist',item_key:'known',image_key:'portrait'}]});
      return done(false, {list:{title:'Known Artist',level:3,count:2},items:[{title:'Play Artist',hint:'action',item_key:'play'},{title:'Album',item_key:'album'}]});
    }
  };
  const manager = new BrowseManager(() => service, () => ({zone_id:'zone'}));
  const result = await manager.run('fallback', 'artist', {name:'Known Artist'});
  assert.deepEqual(result.artist_profile, {name:'Known Artist',image_key:null});
  assert.deepEqual(result.items, [], 'raw search hits must never masquerade as the selected artist catalogue');
  assert.equal(hierarchies[0], 'search');
  assert.equal(hierarchies.includes('browse'), true, 'TIDAL is queried explicitly rather than falling back to Library Artists');
});

test('artist links merge My Catalog before an explicit TIDAL catalogue and remove duplicates', async () => {
  const manager = new BrowseManager(() => ({}), () => ({zone_id:'zone'}));
  manager.search = async (_service, _zone, session, _name, source, category) => {
    if (source === 'tidal') return manager.save(session, {
      hierarchy:'browse', level:2, items:[{title:'Artists',item_key:'tidal-artists'}], has_more:false
    });
    if (category === 'albums') {
      manager.save('global-albums', {hierarchy:'search',level:1,title:'Albums',has_more:false,
        items:[{title:'Astral Weeks',subtitle:'Van Morrison',item_key:'global-astral'},
          {title:'Veedon Fleece',subtitle:'Van Morrison',item_key:'global-veedon'},
          {title:'Van Morrison Tribute',subtitle:'Someone Else',item_key:'wrong-artist'}]});
      return manager.save(session, {hierarchy:'search',level:0,has_more:false,
        items:[{title:'ALBUMS',hint:'header'},{title:'View all albums',item_key:'all-albums'}],
        search_routes:{'all-albums':{session:'global-albums'}}});
    }
    return manager.save(session, {
      hierarchy:'search', level:0,
      items:[{title:'ARTISTS',hint:'header'},{title:'Van Morrison',item_key:'library-preview'}],
      search_routes:{'library-preview':{session:'library-artist',key:'library-van'}}, has_more:false
    });
  };
  manager._run = async (session, _command, data) => {
    if (session === 'library-artist') return manager.save(session, {
      hierarchy:'search', level:3, artist_profile:{name:'Van Morrison',image_key:'library-portrait'}, has_more:false,
      items:[{title:'Play Artist Radio',action:true,item_key:'library-play'},
        {title:'Astral Weeks',subtitle:'Van Morrison',item_key:'library-astral'},
        {title:'Moondance',subtitle:'Van Morrison',item_key:'library-moondance'},
        {title:"What's the Story Morning Glory",subtitle:'Oasis',item_key:'wrong-library-album'}]
    });
    if (data.item_key === 'tidal-artists') return manager.save(session, {
      hierarchy:'browse', level:3, items:[{title:'Van Morrison',item_key:'tidal-van'}], has_more:false
    });
    return manager.save(session, {
      hierarchy:'browse', level:4, artist_profile:{name:'Van Morrison',image_key:'tidal-portrait'}, has_more:false,
      items:[{title:'Play Artist Radio',action:true,item_key:'tidal-play'},
        {title:'Astral Weeks',subtitle:'Van Morrison',item_key:'tidal-astral'},
        {title:'Latest Record',subtitle:'Van Morrison',item_key:'tidal-latest'}]
    });
  };
  const result = await manager.run('merged', 'artist', {name:'Van Morrison'});
  assert.deepEqual(result.items.map(item => item.title), ['Play Artist Radio', 'Astral Weeks', 'Moondance', 'Veedon Fleece', 'Latest Record']);
  assert.deepEqual(result.artist_profile, {name:'Van Morrison',image_key:'library-portrait'});
  assert.equal(result.count, 4);
  assert.equal(Object.values(result.search_routes).some(route => route.session === 'library-artist' && route.key === 'library-astral'), true);
  assert.equal(Object.values(result.search_routes).some(route => /-tidal$/.test(route.session) && route.key === 'tidal-latest'), true);
  assert.equal(Object.values(result.search_routes).some(route => route.session === 'global-albums' && route.key === 'global-veedon'), true);
  assert.equal(result.items.some(item => item.title === 'Van Morrison Tribute'), false);
  assert.equal(result.items.some(item => item.title === "What's the Story Morning Glory"), false);
});

test('artist catalogue follows the full Albums action instead of keeping four featured releases', async () => {
  const manager = new BrowseManager(() => ({}), () => ({zone_id:'zone'}));
  const overview = manager.save('artist', {
    hierarchy:'browse', level:4, title:'Creedence Clearwater Revival', has_more:false,
    artist_profile:{name:'Creedence Clearwater Revival',image_key:'portrait'},
    items:[{title:'Play Artist Radio',action:true,item_key:'play'},
      {title:"Cosmo's Factory",item_key:'cosmo'}, {title:'Bayou Country',item_key:'bayou'},
      {title:'View All Albums',hint:'action',action:true,item_key:'all-albums'}]
  });
  manager._run = async (_session, command, data) => {
    assert.equal(command, 'open'); assert.equal(data.item_key, 'all-albums');
    return manager.save('artist', {hierarchy:'browse',level:5,title:'Albums',has_more:false,
      items:[{title:"Cosmo's Factory",item_key:'cosmo-full'}, {title:'Bayou Country',item_key:'bayou-full'},
        {title:'Green River',item_key:'green-river'}, {title:'Willy and the Poor Boys',item_key:'willy'}]});
  };
  const result = await manager.completeArtistCatalogue({}, 'artist', overview);
  assert.deepEqual(result.items.map(item => item.title), [
    'Play Artist Radio', "Cosmo's Factory", 'Bayou Country', 'Green River', 'Willy and the Poor Boys'
  ]);
  assert.deepEqual(result.artist_profile, overview.artist_profile);
});

test('artist catalogue identity treats ampersand and and as the same artist name', async () => {
  const manager = new BrowseManager(() => ({}), () => ({zone_id:'zone'}));
  manager.search = async (_service, _zone, session, _name, source) => {
    if (source === 'tidal') throw new Error('not connected');
    return manager.save(session, {
      hierarchy:'search', level:0,
      items:[{title:'ARTISTS',hint:'header'},{title:'Crosby, Stills and Nash',item_key:'artist-preview'}],
      search_routes:{'artist-preview':{session:'csn-result',key:'csn'}}, has_more:false
    });
  };
  manager._run = async session => manager.save(session, {
    hierarchy:'search', level:3, artist_profile:{name:'Crosby, Stills and Nash',image_key:'portrait'}, has_more:false,
    items:[{title:'Play Artist Radio',action:true,item_key:'play'},{title:'CSN',subtitle:'Crosby, Stills & Nash',item_key:'album'}]
  });
  const result = await manager.run('punctuation', 'artist', {name:'Crosby, Stills & Nash'});
  assert.equal(result.items.some(item => item.title === 'CSN'), true);
  assert.equal(result.artist_profile.name, 'Crosby, Stills and Nash');
});

test('artist album clicks resolve a fresh routed session before opening the exact album', async () => {
  const calls = [];
  const service = {
    browse(options, done) { calls.push(options.item_key); done(false, {action:'list', list:{title:'Wanted Album', level:4}}); },
    load(_options, done) { done(false, {list:{title:'Wanted Album',level:4},items:[{title:'Play Album',hint:'action',item_key:'play'},{title:'Song',subtitle:'Artist',item_key:'song'}]}); }
  };
  const manager = new BrowseManager(() => service, () => ({zone_id:'zone'}));
  manager.sessions.set('stale-artist', {hierarchy:'search', level:3, artist_profile:{name:'Artist'}, items:[{title:'Wanted Album',image_key:'cover',item_key:'stale-album'}]});
  manager.activeSessions.set(safeSession('touch'), 'stale-artist');
  manager.openArtist = async base => {
    manager.activeSessions.set(base, 'fresh-artist');
    manager.save('fresh-albums', {hierarchy:'search',level:1,title:'Albums',items:[{title:'Wanted Album',image_key:'cover',item_key:'fresh-album'}],has_more:false});
    return manager.save('fresh-artist', {hierarchy:'search',level:3,artist_profile:{name:'Artist'},items:[{title:'Wanted Album',image_key:'cover',item_key:'artist-album-0'}],has_more:false,search_routes:{'artist-album-0':{session:'fresh-albums',key:'fresh-album'}}});
  };
  const result = await manager.run('touch', 'open', {item_key:'stale-album'});
  assert.equal(calls[0], 'fresh-album');
  assert.equal(manager.activeSessions.get(safeSession('touch')), 'fresh-albums');
  assert.equal(result.album_profile.name, 'Wanted Album');
});

test('Play Artist Radio executes Start Radio without exposing the intermediate menu', async () => {
  const calls = [];
  const service = {
    browse(options, done) {
      calls.push(options.item_key);
      if (options.item_key === 'play-artist') return done(false, {action:'list', list:{title:'Play Artist',level:4,count:2}});
      if (options.item_key === 'start-radio') return done(false, {action:'message',message:'Radio started'});
      done('unexpected action');
    },
    load(_options, done) { done(false, {items:[
      {title:'Shuffle',hint:'action',item_key:'shuffle'},
      {title:'Start Radio',hint:'action',item_key:'start-radio'}
    ]}); }
  };
  const manager = new BrowseManager(() => service, () => ({zone_id:'zone'}));
  manager.sessions.set('pihome-radio', {hierarchy:'search',level:3,title:'Artist',items:[{title:'Play Artist Radio',action:true,item_key:'play-artist'}],artist_profile:{name:'Artist'}});
  const result = await manager.run('radio', 'open', {item_key:'play-artist'});
  assert.deepEqual(calls, ['play-artist', 'start-radio']);
  assert.equal(result.navigate, 'now');
  assert.equal(result.items[0].title, 'Play Artist Radio');
});

test('successful queue actions return from the popup to album tracks without replaying the action', async () => {
  const calls = [];
  const service = {
    browse(options, done) { calls.push(options); done(false, options.item_key ? {action:'message',message:'Queued'} : {action:'list',list:{title:'Album',level:3}}); },
    load(options, done) { done(false, {list:{title:'Album',level:3},items:[{title:'Play Album',hint:'action',item_key:'album-play'},{title:'Track',subtitle:'Artist',item_key:'track'}]}); },
  };
  const manager = new BrowseManager(() => service, () => ({zone_id:'zone'}));
  manager.sessions.set('pihome-queue', {hierarchy:'browse', level:4, action_menu:true, fallback_image_key:'cover', items:[{title:'Queue',action:true,item_key:'queue-once'}]});
  const result = await manager.run('queue', 'open', {item_key:'queue-once'});
  assert.equal(calls.filter(call => call.item_key).length, 1);
  assert.equal(calls[1].pop_levels, 1);
  assert.equal(result.action_menu, false);
  assert.equal(result.album_profile.name, 'Album');
  assert.equal(result.message, 'Added to queue.');
});

test('a missing Roon callback has a deadline and releases the serialized queue', async () => {
  const fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
  const source = fs.readFileSync(path.join(__dirname, 'browse-state.js'), 'utf8');
  const start = source.indexOf('function request('), end = source.indexOf('\nfunction safeSession', start);
  let deadline;
  const request = vm.runInNewContext(source.slice(start, end) + '\nrequest', {
    setTimeout(callback) { deadline = callback; return 1; }, clearTimeout() {}
  });
  let calls = 0;
  const manager = new BrowseManager(() => ({}), () => ({}));
  manager._run = () => ++calls === 1 ? request({browse() {}}, 'browse', {}) : Promise.resolve({status: 'ready', items: [{title: 'Recovered'}]});
  const stalled = manager.run('deadline', 'current');
  await new Promise(resolve => setImmediate(resolve));
  deadline();
  await assert.rejects(stalled, /timed out/);
  const recovered = await manager.run('deadline', 'current');
  assert.equal(recovered.items[0].title, 'Recovered');
});

test('grouped search previews keep independent keys, show five matches, and return to groups', async () => {
  const paths = new Map();
  const service = {
    browse(options, done) {
      let path = options.pop_all ? '' : paths.get(options.multi_session_key) || '';
      if (options.item_key) {
        assert.ok(options.item_key.startsWith(options.multi_session_key + ':'), 'keys belong to the correct Roon session');
        path = options.item_key.split(':')[1];
      }
      if (options.pop_levels) path = path.startsWith('album') ? 'Albums' : '';
      paths.set(options.multi_session_key, path);
      done(false, {action: 'list', list: {title: path || 'Search', level: !path ? 0 : path.startsWith('album') ? 2 : 1}});
    },
    load(options, done) {
      const path = paths.get(options.multi_session_key);
      const titles = !path ? ['Works', 'Artists', 'Composers', 'Albums', 'Playlists'] : path.startsWith('album') ? ['Play Album'] : Array.from({length: 8}, (_, i) => `${path === 'Albums' ? 'album' : 'artist'} ${i}`);
      done(false, {list: {title: path || 'Search', level: !path ? 0 : path.startsWith('album') ? 2 : 1, count: titles.length}, items: titles.map(title => ({title, item_key: `${options.multi_session_key}:${title}`, ...(title === 'Play Album' ? {hint: 'action'} : {})}))});
    }
  };
  const manager = new BrowseManager(() => service, () => ({zone_id: 'zone'}));
  const root = await manager.run('group-test', 'search', {query: 'Example', source: 'all'});
  assert.equal(root.layout, 'list');
  assert.deepEqual(root.items.filter(item => item.hint === 'header').map(item => item.title), ['ARTISTS', 'ALBUMS']);
  assert.equal(root.items.filter(item => /^album /.test(item.title)).length, 5);
  const album = root.items.find(item => item.title === 'album 0');
  assert.equal((await manager.run('group-test', 'open', {item_key: album.item_key})).title, 'album 0');
  await manager.run('group-test', 'back');
  assert.equal((await manager.run('group-test', 'back')).items[0].title, 'ARTISTS');
  const all = root.items.find(item => item.title === 'View all albums');
  assert.equal((await manager.run('group-test', 'open', {item_key: all.item_key})).items.length, 8);
  assert.equal((await manager.run('group-test', 'back')).layout, 'list');
  const restored = await manager.run('group-test', 'route', {query: 'Example', steps: [{title: 'album 0', occurrence: 0}]});
  assert.equal(restored.title, 'album 0');
  const safe = await manager.run('group-test', 'route', {query: 'Example', steps: [{title: 'album 0'}, {title: 'Play Album'}]});
  assert.match(safe.message, /no longer available/);
  assert.equal(safe.title, 'album 0', 'history must not trigger playback');
});

test('search album wrappers open the tracks directly and Back skips the wrapper without playing', async () => {
  const paths = new Map(); let played = false;
  const service = {
    browse(options, done) {
      let stack = options.pop_all ? ['Search'] : [...(paths.get(options.multi_session_key) || ['Search'])];
      if (options.pop_levels) stack.splice(-options.pop_levels);
      if (options.item_key === 'albums') stack.push('Albums');
      if (options.item_key === 'album-hit') stack.push('Preview');
      if (options.item_key === 'album-details') stack.push('Tracks');
      if (options.item_key === 'play') played = true;
      paths.set(options.multi_session_key, stack);
      done(false, {action: 'list', list: {title: stack.at(-1), level: stack.length - 1}});
    },
    load(options, done) {
      const stack = paths.get(options.multi_session_key), title = stack.at(-1);
      const items = title === 'Search' ? [{title:'Albums',item_key:'albums'}] : title === 'Albums' ? [{title:'Example',item_key:'album-hit',image_key:'cover'}] : title === 'Preview' ? [{title:'Example (Album)',item_key:'album-details',image_key:'cover'}] : [{title:'Play Album',hint:'action',item_key:'play'},{title:'Song',item_key:'song'}];
      done(false, {list:{title,level:stack.length-1,count:items.length},items});
    }
  };
  const manager = new BrowseManager(() => service, () => ({zone_id:'zone'}));
  const results = await manager.run('wrapper', 'search', {query:'Example'});
  const album = await manager.run('wrapper', 'open', {item_key:results.items.find(item => item.title === 'Example').item_key});
  assert.equal(album.title, 'Tracks'); assert.equal(album.skipped_album_preview, true); assert.equal(played, false);
  assert.equal((await manager.run('wrapper', 'back')).title, 'Albums');
  assert.equal((await manager.run('wrapper', 'back')).items[0].title, 'ALBUMS');
});

test('a real one-track album is not mistaken for a search wrapper', async () => {
  const calls = [];
  const service = {
    browse(options, done) { calls.push(options.item_key); done(false, {action:'list',list:{title:'Album',level:3}}); },
    load(_options, done) { done(false, {list:{title:'Album',level:3,count:2},items:[{title:'Play Album',hint:'action',item_key:'play'},{title:'Only Song',item_key:'song'}]}); }
  };
  const manager = new BrowseManager(() => service, () => ({zone_id:'zone'}));
  manager.sessions.set('pihome-single', {hierarchy:'search',title:'Albums',level:2,items:[{title:'Single',item_key:'album'}]});
  const result = await manager.run('single', 'open', {item_key:'album'});
  assert.deepEqual(calls, ['album']);
  assert.equal(result.items.find(item => item.title === 'Only Song').item_key, 'song');
});

function fakeService() {
  const sessions = new Map();
  const levels = {
    '': [{title: 'Library', item_key: 'library'}, {title: 'Playlists', item_key: 'playlists'}, {title: 'Genres', item_key: 'genres'}],
    library: [{title: 'Albums', item_key: 'albums'}, {title: 'Artists', item_key: 'artists'}],
    albums: [{title: 'A Moon Shaped Pool', subtitle: 'Radiohead', image_key: 'moon', item_key: 'album-a'}, {title: 'Blue Train', subtitle: 'John Coltrane', image_key: 'blue', item_key: 'album-b'}, {title: 'Kind of Blue', subtitle: 'Miles Davis', image_key: 'kind', item_key: 'album-k'}, {title: 'Zooropa', subtitle: 'U2', image_key: 'zoo', item_key: 'album-z'}],
    artists: [{title: 'Björk', image_key: 'bjork', item_key: 'artist-b'}, {title: 'Miles Davis', image_key: 'miles', item_key: 'artist-m'}],
    genres: [{title: 'Jazz', item_key: 'genre-jazz'}],
    playlists: [{title: 'Evening', item_key: 'playlist-evening'}],
    'albums/album-a': [{title: 'Play Album', hint: 'action', item_key: 'play-a'}, {title: 'Burn the Witch', duration: 220, item_key: 'track-a1'}]
  };
  return {
    browse(options, callback) {
      const previous = sessions.get(options.multi_session_key) || {path: '', hierarchy: options.hierarchy};
      let path = options.pop_all ? '' : previous.path;
      if (options.pop_levels) path = path.split('/').slice(0, -options.pop_levels).join('/');
      if (options.item_key && options.hierarchy === 'browse') {
        if (['library', 'playlists', 'genres'].includes(options.item_key)) path = options.item_key;
        else if (['albums', 'artists'].includes(options.item_key)) path = options.item_key;
        else if (options.item_key.startsWith('album-')) path = `albums/${options.item_key}`;
      }
      if (options.input) path = 'results';
      const hierarchy = options.hierarchy; sessions.set(options.multi_session_key, {path, hierarchy});
      const items = hierarchy === 'search' ? [] : (levels[path] || []);
      const title = hierarchy === 'search' ? (path === 'results' ? 'Search results' : 'Search') : (path ? path.split('/').at(-1).replace(/^./, value => value.toUpperCase()) : 'Browse');
      callback(false, {action: 'list', list: {level: path ? path.split('/').length : 0, title, count: items.length}});
    },
    load(options, callback) {
      const current = sessions.get(options.multi_session_key) || {path: '', hierarchy: options.hierarchy};
      const items = current.hierarchy === 'search' && current.path !== 'results'
        ? [{title: 'No Results', item_key: 'empty'}]
        : current.hierarchy === 'search' ? [{title: 'Blue Train', subtitle: 'John Coltrane', image_key: 'blue', item_key: 'album-b'}]
        : (levels[current.path] || []);
      const title = current.hierarchy === 'search' ? (current.path === 'results' ? 'Search results' : 'Search') : (current.path ? current.path.split('/').at(-1).replace(/^./, value => value.toUpperCase()) : 'Browse');
      callback(false, {offset: options.offset, list: {level: current.path ? current.path.split('/').length : 0, title, count: items.length}, items: items.slice(options.offset, options.offset + options.count)});
    }
  };
}

test('browser opens the album section directly and returns to it from an album', async () => {
  const manager = new BrowseManager(() => fake, () => ({zone_id: 'zone'})); const fake = fakeService();
  const root = await manager.run('touch', 'root');
  assert.equal(root.title, 'Albums'); assert.equal(root.items[0].title, 'A Moon Shaped Pool'); assert.equal(root.can_back, false); assert.equal(root.alpha_scrub, true);
  const album = await manager.run('touch', 'open', {item_key: 'album-a'});
  assert.equal(album.title, 'Album-a'); assert.equal(album.items[0].action, true); assert.equal(album.can_back, true);
  const back = await manager.run('touch', 'back'); assert.equal(back.title, 'Albums'); assert.equal(back.can_back, false);
});

test('browser search submits input directly without requiring a prompt and keeps sessions separate', async () => {
  const fake = fakeService(); const manager = new BrowseManager(() => fake, () => ({zone_id: 'zone'}));
  const result = await manager.run('phone', 'search', {query: 'Blue'});
  assert.equal(result.title, 'Search results'); assert.equal(result.items[0].title, 'Blue Train');
  const searchRoot = await manager.run('phone', 'back'); assert.equal(searchRoot.title, 'Search');
  const browseRoot = await manager.run('phone', 'back'); assert.equal(browseRoot.title, 'Albums');
  const touch = await manager.run('touch', 'root'); assert.equal(touch.items[0].title, 'A Moon Shaped Pool');
  assert.notEqual(safeSession('phone!?'), safeSession('touch'));
});

test('search results retain the hierarchy and zone when opened for playback', async () => {
  const calls = [];
  const service = {
    browse(options, callback) {
      calls.push(options);
      if (options.item_key === 'play') return callback(false, {action: 'none'});
      callback(false, {action: 'list', list: {title: options.input ? 'Search' : 'Blue Train', level: options.input ? 0 : 1, count: 1}});
    },
    load(options, callback) {
      assert.equal(options.hierarchy, 'search');
      callback(false, {list: {title: options.level ? 'Blue Train' : 'Search', level: options.level, count: 1}, items: options.level
        ? [{title: 'Play Album', hint: 'action', item_key: 'play'}]
        : [{title: 'Blue Train', item_key: 'album', hint: 'list'}]});
    }
  };
  const manager = new BrowseManager(() => service, () => ({zone_id: 'zone'}));
  await manager.run('test', 'search', {query: 'Blue'});
  const album = await manager.run('test', 'open', {item_key: 'album'});
  assert.equal(album.items[0].action, true);
  await manager.run('test', 'open', {item_key: 'play'});
  await manager.run('test', 'search', {query: 'Oasis'});
  assert.deepEqual(calls.map(call => call.input || call.item_key), ['Blue', 'album', 'play', 'Oasis']);
  assert.ok(calls.every(call => call.hierarchy === 'search' && call.zone_or_output_id === 'zone'));
  assert.ok(calls.filter(call => call.input).every(call => call.pop_all && !call.item_key));
});

test('browsing remains available offline and playback waits for the selected zone', async () => {
  let zone = null;
  const calls = [];
  const service = {
    browse(options, callback) { calls.push(options); callback(false, {action:'none'}); },
    load(_options, callback) { callback(false, {items:[]}); }
  };
  const manager = new BrowseManager(() => service, () => zone);
  manager.sessions.set('pihome-offline', {
    status:'ready', hierarchy:'browse', level:3, title:'Album',
    items:[{title:'Play Album', action:true, item_key:'play'}]
  });
  manager.activeSessions.set('pihome-offline', 'pihome-offline');
  const queued = await manager.run('offline', 'open', {item_key:'play'});
  assert.equal(calls.length, 0, 'an absent endpoint must not redirect playback elsewhere');
  assert.match(queued.message, /Playback queued/);
  assert.equal(queued.navigate, 'now');
  zone = {zone_id:'ls50w'};
  await manager.resumePendingPlayback();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].item_key, 'play');
  assert.equal(calls[0].zone_or_output_id, 'ls50w');
});

test('library browsing omits the playback target while the configured zone is offline', async () => {
  const calls = [], paths = new Map();
  const service = {
    browse(options, callback) {
      calls.push(options);
      let path = options.pop_all ? 'root' : paths.get(options.multi_session_key);
      if (options.item_key === 'library') path = 'library';
      if (options.item_key === 'albums') path = 'albums';
      paths.set(options.multi_session_key, path);
      callback(false, {action:'list', list:{title:path || 'root', level:path === 'albums' ? 2 : path === 'library' ? 1 : 0, count:1}});
    },
    load(options, callback) {
      const path = paths.get(options.multi_session_key);
      const items = path === 'root' ? [{title:'Library',item_key:'library'}]
        : path === 'library' ? [{title:'Albums',item_key:'albums'}]
        : [{title:'Offline Album',subtitle:'Artist',item_key:'album'}];
      callback(false, {list:{title:path,level:path === 'albums' ? 2 : path === 'library' ? 1 : 0,count:items.length},items});
    }
  };
  const manager = new BrowseManager(() => service, () => null);
  const result = await manager.run('offline-library', 'root', {section:'albums'});
  assert.equal(result.items[0].title, 'Offline Album');
  assert.ok(calls.every(call => !Object.hasOwn(call, 'zone_or_output_id')));
});

test('TIDAL search discovers its prompt and retains fresh keys through playback and pagination', async () => {
  const paths = new Map(), calls = [];
  const lists = {
    root: [{title:'TIDAL',item_key:'tidal-root'}],
    tidal: [{title:'Search',item_key:'tidal-prompt',input_prompt:{prompt:'Search'}}],
    results: Array.from({length:31}, (_,i)=>({title:'TIDAL Album '+i,item_key:'tidal-album-'+i,image_key:'cover'})),
    album: [{title:'Play Album',item_key:'tidal-play',hint:'action_list'}],
    actions: [{title:'Play Now',item_key:'tidal-now',hint:'action'}]
  };
  const service = {
    browse(options, cb) {
      calls.push(options);
      assert.equal(options.hierarchy,'browse'); assert.equal(options.zone_or_output_id,'zone');
      let path = options.pop_all ? 'root' : paths.get(options.multi_session_key);
      if(options.item_key==='tidal-root') path='tidal';
      if(options.item_key==='tidal-prompt') {assert.equal(options.input,'Radiohead'); path='results';}
      if(options.item_key==='tidal-album-0') path='album';
      if(options.item_key==='tidal-play') path='actions';
      if(options.item_key==='tidal-now') return cb(false,{action:'none'});
      paths.set(options.multi_session_key,path);
      cb(false,{action:'list',list:{level:2,title:path,count:lists[path].length}});
    },
    load(options,cb) {
      const path=paths.get(options.multi_session_key), items=lists[path];
      cb(false,{offset:options.offset,list:{level:2,title:path,count:items.length},items:items.slice(options.offset,options.offset+options.count)});
    }
  };
  const manager = new BrowseManager(()=>service,()=>({zone_id:'zone'}));
  const results=await manager.run('phone','search',{query:'Radiohead',source:'tidal'});
  assert.equal(results.search_source,'tidal'); assert.equal(results.section,'search'); assert.equal(results.items.length,30);
  const more=await manager.run('phone','more'); assert.equal(more.items.length,31);
  await manager.run('phone','open',{item_key:results.items[0].item_key});
  const played=await manager.run('phone','open',{item_key:'tidal-play'});
  assert.equal(played.navigate,'now'); assert.equal(calls.at(-1).item_key,'tidal-now');
});

test('missing TIDAL connection reports the limitation without presenting library results as TIDAL', async () => {
  const manager = new BrowseManager(()=>fakeService(),()=>({zone_id:'zone'}));
  const result=await manager.run('phone','search',{query:'Blue',source:'tidal'});
  assert.equal(result.error,true); assert.equal(result.search_source,'tidal');
  assert.deepEqual(result.items,[]); assert.match(result.message,/TIDAL is not available/);
  const library=await manager.run('phone','search',{query:'Blue',source:'library'});
  assert.equal(library.items[0].title,'Blue Train'); assert.equal(library.search_source,'library');
});

test('browser root removes TIDAL and keeps the remaining destinations in order', () => {
  const items = ['My Live Radio', 'TIDAL', 'Genres', 'Library', 'Playlists'].map(title => ({title, item_key: title}));
  assert.deepEqual(rootItems(items).map(item => item.title), ['Library', 'Playlists', 'Genres']);
  assert.equal(browserLayout('browse', 0, {title: 'Explore'}, items).layout, 'home');
});

test('section rail switches directly and alphabet jumps replace the loaded page', async () => {
  const fake = fakeService(); const manager = new BrowseManager(() => fake, () => ({zone_id: 'zone'}));
  const artists = await manager.run('touch', 'section', {section: 'artists'});
  assert.equal(artists.section, 'artists'); assert.equal(artists.items[0].title, 'Björk'); assert.equal(artists.alpha_scrub, true);
  const albums = await manager.run('touch', 'section', {section: 'albums'});
  const jumped = await manager.run('touch', 'jump', {letter: 'K'});
  assert.equal(jumped.offset, 2); assert.equal(jumped.items[0].title, 'Kind of Blue'); assert.equal(albums.section_root, true);
});

test('sections retain their pages and navigation stacks without invalidating item keys', async () => {
  const service = fakeService(); const manager = new BrowseManager(() => service, () => ({zone_id: 'zone'}));
  await manager.run('touch', 'section', {section: 'albums'});
  const album = await manager.run('touch', 'open', {item_key: 'album-a'});
  const artists = await manager.run('touch', 'section', {section: 'artists'});
  const artistPage = await manager.run('touch', 'jump', {letter: 'M'});
  assert.equal(artistPage.offset, 1);
  assert.deepEqual(await manager.run('touch', 'section', {section: 'albums'}), album);
  assert.equal((await manager.run('touch', 'back')).title, 'Albums');
  assert.deepEqual(await manager.run('touch', 'section', {section: 'artists'}), artistPage);
  assert.notEqual(manager.activeSessions.get(safeSession('touch')), safeSession('touch') + '-albums');
  assert.equal(artists.title, 'Artists');
  manager.clear(); assert.equal(manager.activeSessions.size, 0);
});

test('Shuffle Genre executes only the native Shuffle action in the chosen zone', async () => {
  const calls = []; let menu = false;
  const service = {
    browse(options, callback) {
      calls.push(options); menu = !options.pop_levels;
      callback(false, options.item_key === 'shuffle' ? {action: 'none'} : {action: 'list', list: {title: menu ? 'Play Genre' : 'Jazz', level: menu ? 3 : 2, count: 1}});
    },
    load(options, callback) { callback(false, {list: {title: menu ? 'Play Genre' : 'Jazz', level: menu ? 3 : 2, count: 1}, items: menu ? [{title: 'Shuffle', item_key: 'shuffle', hint: 'action'}] : [{title: 'Play Genre', item_key: 'play-genre', hint: 'action_list'}]}); }
  };
  const manager = new BrowseManager(() => service, () => ({zone_id: 'zone'}));
  const session = safeSession('touch'); manager.sections.set(session, 'genres');
  const genre = manager.store(session, 'browse', {title: 'Jazz', level: 2, count: 1}, [{title: 'Play Genre', item_key: 'play-genre', hint: 'action_list'}]);
  assert.equal(genre.items[0].title, 'Shuffle Genre'); assert.equal(calls.length, 0);
  const result = await manager.run('touch', 'open', {item_key: 'play-genre'});
  assert.match(result.message, /Shuffling Jazz/);
  assert.deepEqual(calls.map(call => call.item_key || 'back'), ['play-genre', 'shuffle', 'back']);
  assert.ok(calls.every(call => call.zone_or_output_id === 'zone'));
});

test('Surprise Me previews artwork without playback, rerolls, and plays only on confirmation', async () => {
  const manager = new BrowseManager(() => service, () => ({zone_id: 'zone'}));
  const offsets = []; const played = []; const browsed = []; let stage = 'albums';
  const service = {
    browse(options, callback) {
      assert.equal(options.zone_or_output_id, 'zone');
      browsed.push(options.item_key);
      if (options.item_key?.startsWith('album-')) stage = 'tracks';
      else if (options.item_key === 'play-album') stage = 'actions';
      else if (options.item_key === 'play-now') { played.push(options); return callback(false, {action: 'none'}); }
      callback(false, {action: 'list', list: {level: 2}});
    },
    load(options, callback) {
      if (options.count === 1) { offsets.push(options.offset); stage = 'albums'; }
      const items = stage === 'albums' ? [{title: `Album ${options.offset}`, subtitle: 'Album artist', image_key: 'cover', item_key: `album-${options.offset}`}]
        : stage === 'tracks' ? [{title: 'Play Album', item_key: 'play-album', hint: 'action_list'}]
        : [{title: 'Play Now', item_key: 'play-now', hint: 'action'}];
      callback(false, {items});
    }
  };
  manager.openSection = async () => ({count: 5, level: 2});
  const original = {section: 'albums', items: [{title: 'Unchanged browse page'}]}; manager.sessions.set(`${safeSession('touch')}-albums`, original);
  const first = await manager.run('touch', 'surprise');
  const second = await manager.run('touch', 'surprise');
  assert.notEqual(offsets[0], offsets[1]); assert.equal(played.length, 0); assert.equal(browsed.length, 0);
  assert.equal(first.surprise_preview, true); assert.equal(second.items[0].image_key, 'cover');
  assert.equal(second.items[0].subtitle, 'Album artist'); assert.equal(second.has_more, false);
  const result = await manager.run('touch', 'surprise_play');
  assert.equal(played.length, 1); assert.equal(result.navigate, 'now'); assert.equal(result.message, '');
  assert.equal((await manager.run('touch', 'current')).navigate, undefined);
  assert.equal(result.surprise_preview, true); assert.equal(result.surprise_album, second.surprise_album);
  assert.equal(await manager.run('touch', 'back'), original);
  await assert.rejects(manager.run('touch', 'surprise_play'), /Choose a surprise album first/);
});

test('Surprise returns to the originating Artists section', async () => {
  const original = {section:'artists', items:[{title:'My artist'}]};
  const service = {load:(_options, callback)=>callback(false,{items:[{title:'Album', item_key:'album'}]})};
  const manager = new BrowseManager(()=>service, ()=>({zone_id:'zone'}));
  manager.openSection = async ()=>({count:2,level:2});
  manager.sessions.set('pihome-touch-artists', original);
  manager.activeSessions.set('pihome-touch', 'pihome-touch-artists');
  const preview = await manager.run('touch', 'surprise');
  assert.equal(preview.return_section, 'artists');
  assert.equal(await manager.run('touch','back'), original);
});

test('Play Now navigates only after successful playback, not action menus or errors', async () => {
  for (const [reply, title, navigate] of [
    [{action:'none'}, 'Play Now', 'now'],
    [{action:'none'}, ' Play Album ', 'now'],
    [{action:'none'}, 'Play from here', 'now'],
    [{action:'none'}, 'Play', 'now'],
    [{action:'none'}, 'Add Next', undefined],
    [{action:'list',list:{level:3,count:0}}, 'Play Album', undefined],
    [{action:'none',is_error:true,message:'Not available'}, 'Play Now', undefined]
  ]) {
    const service = {browse:(_options,cb)=>cb(false,reply),load:(_options,cb)=>cb(false,{items:[]})};
    const manager = new BrowseManager(()=>service,()=>({zone_id:'zone'}));
    manager.sessions.set('pihome-test', {hierarchy:'browse',section:'albums',level:2,items:[{title,hint:'action',action:true,item_key:'play'}]});
    const result = await manager.run('test','open',{item_key:'play'});
    assert.equal(result.navigate,navigate);
    assert.equal((await manager.run('test','current')).navigate,undefined);
    if (navigate) assert.equal((await manager.run('test','current')).message,'');
    if (reply.is_error) assert.equal(result.error,true);
  }
});

test('Play Album completes its nested Play Now menu and hands off only on success', async () => {
  for (const failure of [false, true]) {
    const calls = [];
    const service = {
      browse:(options,cb)=>{calls.push(options.item_key); cb(false,options.item_key==='album-play'?{action:'list',list:{level:3,count:1}}:{action:'none',is_error:failure,message:failure?'Unavailable':''});},
      load:(_options,cb)=>cb(false,{items:[{title:'Play Now',item_key:'now'}]})
    };
    const manager = new BrowseManager(()=>service,()=>({zone_id:'zone'}));
    manager.sessions.set('pihome-test',{hierarchy:'browse',section:'albums',level:2,items:[{title:'Play Album',action:true,item_key:'album-play'}]});
    const result = await manager.run('test','open',{item_key:'album-play'});
    assert.deepEqual(calls,['album-play','now']);
    assert.equal(result.navigate,failure?undefined:'now');
    assert.equal((await manager.run('test','current')).navigate,undefined);
  }
});

test('Play Album dropdown exposes its native action menu without starting playback', async () => {
  const calls = [];
  const service = {
    browse:(options,cb)=>{calls.push(options.item_key); cb(false,{action:'list',list:{title:'Play Album',level:3,count:4}});},
    load:(_options,cb)=>cb(false,{list:{title:'Play Album',level:3,count:4},items:[
      {title:'Play Now',hint:'action',item_key:'now'},
      {title:'Add Next',hint:'action',item_key:'next'},
      {title:'Queue',hint:'action',item_key:'queue'},
      {title:'Start Radio',hint:'action',item_key:'radio'}
    ]})
  };
  const manager = new BrowseManager(()=>service,()=>({zone_id:'zone'}));
  manager.sessions.set('pihome-test',{hierarchy:'browse',section:'albums',level:2,items:[{title:'Play Album',action:true,item_key:'album-play'}]});
  const result = await manager.run('test','open',{item_key:'album-play',menu_only:true});
  assert.deepEqual(calls,['album-play']);
  assert.equal(result.action_menu,true);
  assert.deepEqual(result.items.map(item=>item.title),['Play Now','Add Next','Queue','Start Radio']);
  assert.equal(result.navigate,undefined);
});

test('successful Play Now returning a track list hands off and retains album artwork', async () => {
  const service = {browse:(_options,cb)=>cb(false,{action:'list',list:{title:'Album',level:2,count:1}}),load:(_options,cb)=>cb(false,{items:[{title:'Song',item_key:'song',hint:'action_list'}]})};
  const manager = new BrowseManager(()=>service,()=>({zone_id:'zone'}));
  manager.sessions.set('pihome-test',{hierarchy:'browse',section:'albums',level:3,fallback_image_key:'cover',items:[{title:'Play Now',action:true,item_key:'now'}]});
  const result = await manager.run('test','open',{item_key:'now'});
  assert.equal(result.navigate,'now');
  assert.equal(result.items[0].image_key,'cover');
});

test('search display removes Roon catalogue link markup', () => {
  assert.equal(publicItem({title:'Air',subtitle:'[[109178|Air]]'}).subtitle,'Air');
});

test('artist overview retains the selected portrait when returning from an album', async () => {
  const service = {browse:(_options,cb)=>cb(false,{action:'list',list:{title:'Band',level:3,count:2}}),load:(_options,cb)=>cb(false,{items:[{title:'Play Artist',hint:'action',item_key:'play'}, {title:'Album',image_key:'album-cover',item_key:'album'}]})};
  const manager = new BrowseManager(()=>service,()=>({zone_id:'zone'}));
  manager.sessions.set('pihome-test', {hierarchy:'browse',section:'artists',section_root:true,level:2,items:[{title:'Band',image_key:'portrait',item_key:'band'}]});
  manager.sections.set('pihome-test','artists');
  const opened = await manager.run('test','open',{item_key:'band'});
  assert.deepEqual(opened.artist_profile,{name:'Band',image_key:'portrait'});
  const restored = manager.store('pihome-test','browse',{title:'Band',level:3},[{title:'Play Artist',hint:'action'},{title:'Album',image_key:'album-cover'}],'','album-cover');
  assert.deepEqual(restored.artist_profile,{name:'Band',image_key:'portrait'});
  manager.clear(); assert.equal(manager.artistContexts.size,0);
});

test('alphabet indexing respects Roon offsets and can load previous results', async () => {
  const titles = ["(What's the Story) Morning Glory?", ...Array.from({length: 35}, (_, i) => `A album ${i}`), 'The Beatles', 'Écho', 'Foxtrot', 'Tango', 'Zulu'];
  let loads = 0;
  const service = {load(options, callback) { loads++; callback(false, {list: {count: titles.length}, items: titles.slice(options.offset, options.offset + options.count).map(title => ({title}))}); }};
  const manager = new BrowseManager(() => service, () => ({zone_id: 'zone'}));
  manager.sessions.set(safeSession('test'), {alpha_scrub: true, count: titles.length, section: 'albums', hierarchy: 'browse', level: 2, offset: 0, items: []});
  const echo = await manager.run('test', 'jump', {letter: 'E'});
  assert.equal(echo.items[0].title, 'Écho');
  const previous = await manager.run('test', 'previous');
  assert.ok(previous.offset < echo.offset); assert.equal(previous.items.at(-1).title, 'Zulu');
  const before = loads;
  const beatles = await manager.run('test', 'jump', {letter: 'B'});
  assert.equal(beatles.items[0].title, 'The Beatles'); assert.equal(loads, before + 1);
  const first = await manager.run('test', 'jump', {letter: 'A'});
  assert.equal(first.offset, 0);
});

test('album track titles hide disc and track prefixes without changing names', () => {
  const items = withAlbumArtist([{title: 'Play Album', action: true}, {title: '1-1 Hello'}, {title: '2. Wonderful'}, {title: '99 Luftballons'}]);
  assert.equal(items[1].title, 'Hello'); assert.equal(items[2].title, 'Wonderful');
  assert.equal(items[3].title, '99 Luftballons');
});

test('album and artist collections retain artwork grids', () => {
  const items = [{title: 'One', image_key: '1'}, {title: 'Two', image_key: '2'}];
  assert.deepEqual(browserLayout('browse', 2, {title: 'Albums'}, items), {layout: 'covers', show_labels: false});
  assert.deepEqual(browserLayout('browse', 2, {title: 'Artists'}, items), {layout: 'covers', show_labels: true});
});

test('album contents with a play action use track rows and preserve supplied durations', () => {
  const items = [publicItem({title: 'Play Album', hint: 'action_list'}), {title: 'Track', image_key: 'cover'}];
  assert.equal(items[0].action, true);
  assert.equal(browserLayout('browse', 3, {title: 'An Album'}, items).layout, 'list');
  assert.equal(publicItem({title: 'Track', duration: 245}).duration, '4:05');
  assert.equal(publicItem({title: 'Track', length: '3:09'}).duration, '3:09');
  assert.equal(formatDuration(null), '');
});

test('album track rows use the album artist rather than a long credits list', () => {
  const items = withAlbumArtist([
    publicItem({title: 'Play Album', hint: 'action'}),
    publicItem({title: 'Track one', subtitle: 'Justice, Xavier de Rosnay, Gaspard Augé'}),
    publicItem({title: 'Track two', subtitle: 'Justice, Featured Singer'})
  ]);
  assert.equal(items[1].subtitle, 'Justice');
  assert.equal(items[2].subtitle, 'Justice');
});

test('library is reduced to four useful destinations', () => {
  const list = {title: 'Library'};
  const items = ['Search', 'Artists', 'Albums', 'Tracks', 'Composers', 'Tags'].map(title => ({title, item_key: title}));
  assert.deepEqual(libraryItems(list, items).map(item => item.title), ['Artists', 'Albums', 'Tracks', 'Composers']);
  assert.equal(browserLayout('browse', 1, list, libraryItems(list, items)).layout, 'menu');
});

test('genre and playlist collections use tiles while playlist tracks stay in rows', () => {
  const pictured = [{title: 'One', image_key: '1'}, {title: 'Two', image_key: '2'}];
  assert.deepEqual(browserLayout('browse', 1, {title: 'Genres'}, pictured), {layout: 'tiles', show_labels: true, show_subtitles: false});
  assert.deepEqual(browserLayout('browse', 1, {title: 'Playlists'}, pictured), {layout: 'tiles', show_labels: true, show_subtitles: false});
  assert.equal(browserLayout('browse', 2, {title: 'Evening vibes', subtitle: '437 Tracks'}, pictured).layout, 'list');
});

test('album artwork fills child track rows when Roon omits redundant image keys', () => {
  const items = withFallbackImage([
    {title: 'Play Album', hint: 'action'},
    {title: 'Track One', image_key: null},
    {title: 'Track Two', image_key: 'specific'}
  ], 'album-cover');
  assert.equal(items[0].image_key, undefined);
  assert.equal(items[1].image_key, 'album-cover');
  assert.equal(items[2].image_key, 'specific');
});
