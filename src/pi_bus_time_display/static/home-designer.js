/* Home Assistant settings as tabs: Settings, Layout (screen designer) and Colours. */
(() => {
  const panel = document.querySelector('[data-service-panel="home"]');
  const options = document.getElementById('home-options');
  const textarea = document.querySelector('textarea[name="home_assistant_entities"]');
  if (!panel || !options || !textarea) return;
  const form = textarea.form;
  const ICONS = window.DeckIcons || {};
  let LIMIT = 8;   // tiles on one page: more on a big screen, which has the room (set from the screen shape in pageLimit)
  const MAX_PAGES = 4;
  const DEFAULT_COLOURS = {light: '#fb923c', fan: '#60a5fa', switch: '#9868f9', scene: '#a3e635'};
  const SWATCHES = ['#fb923c', '#60a5fa', '#9868f9', '#a3e635', '#e85d3a', '#d94f8c', '#3fc7a0', '#e9e4da'];
  const lineArt = body => body.replace(/fill="#fff"/g, 'fill="none"');
  const ICON_STYLE = 'stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" fill="none"';
  // The shape of each touchscreen: width × height as it sits when mounted, from the display profile and orientation.
  const SCREENS = {original: [800, 480, 'Touch Display (7-inch, original)'], 'touch2-5': [720, 1280, '5-inch Touch Display 2'], 'touch2-7': [720, 1280, '7-inch Touch Display 2'], 'touch2-5-7': [720, 1280, 'Touch Display 2'], 'touch2-10': [800, 1280, '10-inch Touch Display 2']};

  const h = (tag, props = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (key === 'class') node.className = value; else if (key === 'style') node.style.cssText = value; else if (key.startsWith('on')) node[key] = value;
      else if (value !== undefined && value !== null && value !== false) node.setAttribute(key, value === true ? '' : value);
    }
    node.append(...children.flat().filter(child => child !== null && child !== undefined && child !== false));
    return node;
  };
  const field = (text, control, hint) => h('label', {class: 'cd-field'}, h('span', {}, text), control, hint ? h('small', {}, hint) : null);
  const blend = (top, base, amount) => {
    const a = [1, 3, 5].map(i => parseInt(top.slice(i, i + 2), 16)), b = [1, 3, 5].map(i => parseInt(base.slice(i, i + 2), 16));
    return `rgb(${a.map((value, i) => Math.round(b[i] + (value - b[i]) * amount)).join(',')})`;
  };

  /* ------------------------------------------------------------ state */
  let roonOutputs = [], catalog = [], states = {}, art = [], layout = {tiles: {}}, system = {}, selected = -1, query = '', addSource = 'own', kind = 'All', dirty = false, dragId = null, dragIndex = null, dragTile = null, live = null, devicesOpen = null, snapshot = null;
  // On the dashboard layout the player and the next bus are tiles on the same grid as the devices.
  const TILE_KEYS = new Set(['size', 'rows', 'col', 'row', 'label', 'icon', 'image', 'color', 'also', 'half', 'sub', 'show', 'art', 'scrubber', 'volume', 'heading', 'align', 'download', 'upload', 'zone', 'with', 'page', 'route', 'border']);   // what the server accepts for a tile
  const CARDS = {'roondeck.player': 'Now Playing', 'roondeck.bus': 'Next bus'};
  const KEF = {'roondeck.kef': 'KEF speaker', 'roondeck.kef_power': 'KEF power', 'roondeck.kef_input': 'KEF input', 'roondeck.kef_volume': 'KEF volume'};
  const LIVE = {...KEF, 'roondeck.cpu': 'CPU', 'roondeck.memory': 'Memory', 'roondeck.network': 'Network', 'roondeck.volume': 'Volume', 'roondeck.update': 'Update', 'roondeck.group': 'Group zones', 'roondeck.group2': 'Group zones 2', 'roondeck.group3': 'Group zones 3'};
  const GROUPS = ['roondeck.group', 'roondeck.group2', 'roondeck.group3'];   // optional live tiles the owner adds
  // The same device or card can be on several pages: the copies are kept as "light.lamp#2" and behave as tiles of their own.
  const B = id => id.split('#')[0];
  const isCard = id => B(id) in CARDS || B(id) in LIVE;
  const liveShown = () => Object.keys(layout.tiles).filter(key => B(key) in LIVE && layout.tiles[key].show);
  const textIds = () => textarea.value.split(',').map(item => item.trim()).filter(Boolean);
  const copiesOf = base => Object.keys(layout.tiles).filter(key => key !== base && B(key) === base).sort();
  const instancesOf = base => [base, ...copiesOf(base)];
  const newCopyKey = base => { for (let n = 1; n <= 3; n += 1) if (!(`${base}#${n}` in layout.tiles)) return `${base}#${n}`; return null; };
  const allDevices = () => dashColumns() ? textIds().flatMap(id => [id, ...copiesOf(id)]) : textIds();
  // The dashboard can have several pages, swiped between on the touchscreen. The builder shows one page at a time.
  let pageNo = 0;
  const pageCount = () => dashColumns() ? Math.max(1, Math.min(MAX_PAGES, layout.pages || 1)) : 1;
  const pageOf = id => Math.min(pageCount() - 1, (layout.tiles[id] || {}).page || 0);
  const onPage = id => pageCount() < 2 || pageOf(id) === Math.min(pageNo, pageCount() - 1);
  const deviceIds = () => allDevices().filter(onPage);
  const allIds = () => dashColumns() ? [...Object.keys(CARDS), ...Object.keys(layout.tiles).filter(key => key.includes('#') && B(key) in CARDS), ...liveShown(), ...allDevices()] : [...liveShown().filter(key => B(key) in KEF), ...allDevices()];
  const ids = () => allIds().filter(onPage);
  const hasOnPage = (base, page) => instancesOf(base).some(key => pageOf(key) === page && (key in layout.tiles || textIds().includes(key) || key in CARDS));
  const withPage = tile => { const next = {...tile}; if (pageNo > 0 && pageCount() > 1) next.page = pageNo; else delete next.page; return next; };
  const nameOf = id => CARDS[B(id)] || LIVE[B(id)] || catalog.find(item => item.entity_id === B(id))?.name || states[B(id)]?.name || B(id);
  // Until the owner has placed either card, the player sits top-left and the bus under it.
  const CARD_HOME = {'roondeck.player': {col: 0, row: 0}, 'roondeck.bus': {col: 0, row: 2}};
  const tileOf = id => {
    const own = layout.tiles[id] || {};
    if (id in CARD_HOME && !Object.keys(CARD_HOME).some(key => Number.isInteger(layout.tiles[key]?.col)) && !Number.isInteger(own.col)) return {...own, ...CARD_HOME[id]};
    return own;
  };
  const markDirty = () => { dirty = true; window.RoonDeckDirty?.('homelayout', 'Home layout'); };
  function setIds(list) {
    const before = allDevices(), kept = [];
    for (const entry of list.filter(id => !isCard(id))) {
      // A device already on another page is added here as a copy.
      const key = before.includes(entry) && !onPage(entry) ? newCopyKey(entry) : entry;
      if (!key) continue;
      if (!before.includes(key) && pageCount() > 1) layout.tiles[key] = withPage(layout.tiles[key] || {});
      kept.push(key);
    }
    const others = before.filter(key => !onPage(key) && !kept.includes(key));
    const keys = pageNo > 0 ? [...others, ...kept] : [...kept, ...others];
    textarea.value = [...new Set(keys.map(B))].join(', ');
    textarea.dispatchEvent(new Event('input', {bubbles: true}));
    render();
  }
  // Takes one tile off its page. A copy simply goes; the main tile hands over to a copy on another page, so the device stays in the list.
  function removeTile(id) {
    selected = -1;
    const others = copiesOf(B(id)).filter(key => key !== id);
    if (id.includes('#')) delete layout.tiles[id];
    else if (others.length) { layout.tiles[id] = layout.tiles[others[0]]; delete layout.tiles[others[0]]; }
    else if (B(id) in LIVE) delete layout.tiles[id];
    else { markDirty(); setIds(ids().filter(other => other !== id)); return; }
    markDirty(); render();
  }
  function patchTile(id, patch) {
    const next = {...tileOf(id), ...patch};
    for (const key of Object.keys(next)) if (next[key] === '' || next[key] === undefined || next[key] === null) delete next[key];
    if (Object.keys(next).length) layout.tiles[id] = next; else delete layout.tiles[id];
    markDirty(); render();
  }
  const rowsPatch = (id, rows) => B(id) === 'roondeck.player' ? {rows} : {rows: rows > 1 ? rows : ''};
  const domainOf = id => { const d = id.split('.')[0]; return d === 'script' || d === 'scene' ? 'scene' : d === 'input_boolean' ? 'switch' : d; };
  const accent = id => {
    if (tileOf(id).color) return tileOf(id).color;
    const single = form.elements.home_assistant_color_mode?.value === 'single';
    return (single ? form.elements.home_assistant_single_color?.value : form.elements[`home_assistant_${domainOf(id)}_color`]?.value) || DEFAULT_COLOURS[domainOf(id)] || '#9868f9';
  };
  const artUrl = name => `/api/admin/listening/art/${encodeURIComponent(name)}`;

  /* ------------------------------------------------------------ screen shape */
  function screen() {
    const [nativeW, nativeH, label] = SCREENS[system.display_profile] || SCREENS.original;
    const portrait = system.display_orientation ? system.display_orientation === 'portrait' : nativeH > nativeW;
    const wide = Math.max(nativeW, nativeH), tall = Math.min(nativeW, nativeH);
    return {portrait, width: portrait ? tall : wide, height: portrait ? wide : tall, label};
  }
  // Landscape displays 1000px wide or more use the card dashboard, which has a choice of 2 or 3 columns.
  const dashColumns = () => { const shape = screen(); if (shape.portrait) return shape.width >= 700 && shape.height >= 1200 ? 2 : 0; return shape.width >= 1000 ? (layout.columns === 2 ? 2 : 3) : 0; };   // tall 7/10-inch panels: always two columns
  const pageLimit = () => { const shape = screen(); return shape.portrait ? (dashColumns() ? 16 : 8) : shape.width >= 1000 && layout.columns !== 2 ? 12 : 8; };
  const isScene = id => domainOf(id) === 'scene';
  // The same placement rules as the touchscreen. Tiles the owner placed (col/row) keep their cell; the rest take the first free space.
  const hasPlace = id => Number.isInteger(tileOf(id).col) && Number.isInteger(tileOf(id).row);
  function place(list, portrait) {
    const dash = dashColumns();
    const positioned = list.some(hasPlace);
    const custom = dash > 0 || positioned || list.some(id => (tileOf(id).size && tileOf(id).size !== 'auto') || tileOf(id).rows === 2);
    if (!custom) {
      if (portrait) return {columns: 1, rows: Math.max(1, list.length), cells: list.map((id, i) => ({id, column: 0, row: i, span: 1, height: 1})), custom, positioned, rowMode: true, taken: new Set()};
      if (list.length === 6) return {columns: 4, rows: 2, custom, positioned, rowMode: false, taken: new Set(), cells: list.map((id, i) => i < 2 ? {id, column: i, row: 0, span: 1, height: 2} : {id, column: 2 + (i - 2) % 2, row: Math.floor((i - 2) / 2), span: 1, height: 1})};
      return {columns: 4, rows: Math.max(1, Math.ceil(list.length / 4)), custom, positioned, rowMode: false, taken: new Set(), cells: list.map((id, i) => ({id, column: i % 4, row: Math.floor(i / 4), span: 1, height: 1}))};
    }
    // On the dashboard the grid is counted in half columns, so a tile can be half a column wide and two of them share a column.
    const fine = dash ? 2 : 1, columns = dash ? dash * 2 : (portrait ? 2 : 4);
    const spans = dash ? {quarter: 2, half: Math.min(4, columns), full: columns} : {quarter: 1, half: portrait ? 1 : 2, full: columns};
    const taken = new Set(), at = new Map();
    const isHalf = id => !!dash && !!tileOf(id).half;
    const spots = (column, row, span, height) => { const out = []; for (let dx = 0; dx < span; dx += 1) for (let dy = 0; dy < height; dy += 1) out.push(`${column + dx},${row + dy}`); return out; };
    const dims = id => ({span: isHalf(id) ? 1 : Math.min(columns, spans[tileOf(id).size] || (dash ? 2 : 1)), height: Math.min(dash ? 3 : 2, Math.max(1, tileOf(id).rows || (B(id) === 'roondeck.player' ? 2 : 1)))});
    const startOf = id => tileOf(id).col * fine + (isHalf(id) && tileOf(id).sub ? 1 : 0);
    for (const id of list) {
      const {span, height} = dims(id), tile = tileOf(id), x = startOf(id);
      if (hasPlace(id) && x + span <= columns && !spots(x, tile.row, span, height).some(spot => taken.has(spot))) { spots(x, tile.row, span, height).forEach(spot => taken.add(spot)); at.set(id, {id, column: x, row: tile.row, span, height}); }
    }
    for (const id of list) {
      if (at.has(id)) continue;
      const {span, height} = dims(id), step = dash && !isHalf(id) ? 2 : 1; let done = false;
      for (let row = 0; !done; row += 1) for (let column = 0; column + span <= columns && !done; column += step) {
        const here = spots(column, row, span, height); if (here.some(spot => taken.has(spot))) continue;
        here.forEach(spot => taken.add(spot)); at.set(id, {id, column, row, span, height}); done = true;
      }
    }
    const cells = list.map(id => ({...at.get(id), id}));
    const used = Math.max(1, ...cells.map(cell => cell.row + cell.height));
    return {columns, rows: Math.max(used, dash ? (screen().portrait ? 6 : 3) : Math.ceil(LIMIT / columns)), cells, custom, positioned, rowMode: false, taken};
  }
  // Would the owner's tiles all keep their cells if this tile took on these settings?
  function fitsAfter(id, patch) {
    const portrait = screen().portrait, before = place(ids(), portrait); if (!before.positioned) return true;
    const old = layout.tiles[id], next = {...tileOf(id), ...patch}; for (const key of Object.keys(next)) if (next[key] === '' || next[key] === undefined) delete next[key];
    layout.tiles[id] = next; const after = place(ids(), portrait); if (old) layout.tiles[id] = old; else delete layout.tiles[id];
    return before.cells.every(cell => { const now = after.cells.find(item => item.id === cell.id); return now && now.column === cell.column && now.row === cell.row && now.row + now.height <= after.rows; });
  }
  // Give every tile an explicit cell, so moving one never shuffles the others.
  function pin(cells) {
    const fine = dashColumns() ? 2 : 1;
    for (const cell of cells) {
      const half = fine === 2 && tileOf(cell.id).half, next = {...tileOf(cell.id), col: Math.floor(cell.column / fine), row: cell.row}; delete next.rows;
      if (half && cell.column % 2) next.sub = 1; else delete next.sub;
      if (cell.height !== (B(cell.id) === 'roondeck.player' ? 2 : 1)) next.rows = cell.height;
      layout.tiles[cell.id] = next;
    }
  }

  /* ------------------------------------------------------------ preview */
  // A small copy of the touchscreen's cards, so the builder reads like the real Home page.
  const svgOf = (key, colour) => { const span = h('span', {class: 'hd-glyph', style: `color:${colour}`}); if (ICONS[key]) span.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true" ${ICON_STYLE.replace('stroke="#fff"', 'stroke="currentColor"')}>${lineArt(ICONS[key][1])}</svg>`; return span; };
  function dashBody(id, tile, colour, lit, height) {
    if (B(id) === 'roondeck.player') {
      const art = tile.art || 'background', short = height === 1, bar = tile.scrubber ? h('span', {class: 'hd-d-bar scrub'}, h('i', {}), h('em', {})) : h('span', {class: 'hd-d-bar'}, h('i', {}));
      return [h('div', {class: `hd-d-player art-${art}${tile.align === 'left' ? ' align-left' : ''}`},
        tile.heading === false || short ? null : h('span', {class: 'hd-d-zone'}, (tile.label || 'ROONDECK').toUpperCase()), h('span', {class: 'hd-d-spacer'}),
        h('span', {class: 'hd-d-headrow'}, art === 'thumb' && !short ? h('span', {class: 'hd-d-thumb'}) : null, h('span', {class: 'hd-d-words'}, h('b', {}, 'Track title'), h('small', {}, 'Artist'))), bar,
        h('span', {class: 'hd-d-transport'}, svgOf('previous', '#f4f0e6'), h('span', {class: 'hd-d-play'}, svgOf('play', '#17151d')), svgOf('next', '#f4f0e6')),
        tile.volume === false || short ? null : h('span', {class: 'hd-d-bar vol'}, h('i', {})))];
    }
    if (B(id) === 'roondeck.bus') return [h('div', {class: 'hd-d-bus'}, h('span', {class: 'hd-d-chip'}, (() => { const bus = h('span', {class: 'hd-glyph', style: 'color:#d3dcec'}); bus.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="3" width="14" height="15" rx="3"/><path d="M5 11h14"/><circle cx="9" cy="14.5" r=".8"/><circle cx="15" cy="14.5" r=".8"/><path d="M8 18v2M16 18v2"/></svg>'; return bus; })()), h('span', {class: 'hd-d-route'}, h('b', {}, tileOf(id).route || '42'), h('small', {}, 'then 11 min')), h('span', {class: 'hd-d-minutes'}, h('b', {}, '7'), h('small', {}, 'min')))];
    if (B(id) === 'roondeck.update' || GROUPS.includes(B(id))) {
      const upd = B(id) === 'roondeck.update', zones = [tile.zone, tile.with].filter(Boolean);
      const chip = h('span', {class: 'hd-d-achip'}); chip.innerHTML = upd
        ? '<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"><path d="M32 10v31M19 29l13 13 13-13M11 47v7h42v-7"/></svg>'
        : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>';
      return [h('div', {class: 'hd-d-live hd-d-action' + (upd ? ' alert' : '')}, h('span', {class: 'hd-d-livetext hd-d-actiontext'}, h('span', {class: 'hd-d-head'}, chip, h('b', {class: 'hd-d-big'}, upd ? 'Update' : zones.length === 2 ? 'Group' : 'Set zones')),
        h('span', {class: 'hd-d-spacer'}),
        h('small', {class: 'hd-d-livefoot'}, upd ? 'v1.2.0 is ready. Tap to install' : zones.length === 2 ? zones[0] + '\n+ ' + zones[1] : 'Choose them in the tile options')))];
    }
    if (B(id) === 'roondeck.volume') return [h('div', {class: 'hd-d-live hd-d-volume'}, h('span', {class: 'hd-d-title'}, 'VOLUME'), h('span', {class: 'hd-d-volrow'}, h('i', {}, '\u2212'), h('b', {}, '42'), h('i', {}, '+')))];
    if (B(id) in KEF) {
      const kind = B(id), full = kind === 'roondeck.kef';
      return [h('div', {class: 'hd-d-live'}, h('b', {}, tile.label || KEF[kind]), h('small', {}, 'On · Wi-Fi · 20%'),
        full || kind.endsWith('_power') ? h('span', {}, 'On   ·   Standby') : null,
        full || kind.endsWith('_input') ? h('span', {}, 'Choose input ▾') : null,
        full || kind.endsWith('_volume') ? h('span', {}, '−   20   +   Mute') : null)];
    }
    if (B(id) in LIVE) {
      const cpu = B(id) === 'roondeck.cpu', mem = B(id) === 'roondeck.memory', net = !cpu && !mem;
      const values = mem ? [48, 49, 49, 50, 50, 51, 51, 51, 52, 52, 52, 53, 53, 53, 54] : cpu ? [22, 30, 26, 41, 35, 28, 52, 44, 31, 24, 38, 29, 33, 47, 36] : [8, 12, 30, 22, 55, 40, 18, 62, 35, 20, 44, 28, 16, 38, 24];
      const line = values.map((value, i) => `${(i * 100 / (values.length - 1)).toFixed(1)},${(37 - value * .24).toFixed(1)}`).join(' ');
      const tint = cpu ? '#6ed9ae' : '#6aa8ff';
      const spark = h('span', {class: 'hd-d-spark'}); spark.innerHTML = `<svg viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true"><polygon points="0,40 ${line} 100,40" fill="${tint}" fill-opacity=".16"/><polyline points="${line}" fill="none" stroke="${tint}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`;
      const down = tile.download !== false;
      return [h('div', {class: 'hd-d-live'}, spark, h('span', {class: 'hd-d-livetext'},
        h('span', {class: 'hd-d-livehead'}, h('small', {}, cpu ? 'CPU' : mem ? 'MEMORY' : 'NETWORK'), cpu ? h('small', {}, '52 \u00b0C') : null),
        h('b', {class: 'hd-d-big'}, mem ? '54%' : cpu ? '36%' : (down ? '12.4 Mbit/s' : '0.3 Mbit/s')),
        net ? h('small', {class: 'hd-d-livefoot'}, down ? (tile.upload === false ? '' : 'up 0.3 Mbit/s') : 'upload') : null))];
    }
    const domain = domainOf(id), info = states[B(id)] || {}, scene = domain === 'scene';
    const level = ['light', 'fan', 'climate'].includes(domain) && (info.supports_level !== false);
    const pct = Number.isFinite(info.percentage) ? info.percentage : Number.isFinite(info.brightness) ? Math.round(info.brightness * 100 / 255) : 50;
    const name = tile.label || nameOf(id);
    const chip = h('span', {class: 'hd-d-chip', style: `opacity:${lit ? 1 : .6}`}, tile.icon ? h('span', {class: 'hd-icon hd-icon-tint', style: `background:${colour};-webkit-mask-image:url(${artUrl(tile.icon)});mask-image:url(${artUrl(tile.icon)})`}) : svgOf(scene ? 'scene' : domain === 'light' ? 'bulb' : domain === 'fan' ? 'fan' : domain === 'climate' ? 'snow' : 'switch', colour));
    if (scene) return [h('div', {class: 'hd-d-scene'}, chip, h('span', {class: 'hd-d-text'}, h('b', {}, name), h('small', {}, 'TAP TO ACTIVATE')))];
    const text = h('span', {class: 'hd-d-text'}, h('b', {}, name), h('small', {}, level ? (lit ? `${pct}%` : 'OFF') : (lit ? 'ON' : 'OFF')));
    if (tile.half) {
      const switchOf = !level ? h('span', {class: `hd-d-switch${lit ? ' on' : ''}`, style: lit ? `background:${colour}` : ''}, h('i', {})) : null;
      return [h('div', {class: 'hd-d-device hd-d-half'}, h('span', {class: 'hd-d-row'}, chip, h('span', {class: 'hd-d-fill'}), switchOf), text,
        level ? h('span', {class: 'hd-d-slider'}, h('i', {style: `width:${lit ? pct : 0}%;background:${colour}`})) : null)];
    }
    if (level) return [h('div', {class: 'hd-d-device'}, h('span', {class: 'hd-d-row'}, chip, text), h('span', {class: 'hd-d-slider'}, h('i', {style: `width:${lit ? pct : 0}%;background:${colour}`})))];
    return [h('div', {class: 'hd-d-device'}, h('span', {class: 'hd-d-row'}, chip, text, h('span', {class: `hd-d-switch${lit ? ' on' : ''}`, style: lit ? `background:${colour}` : ''}, h('i', {}))))];
  }
  function tileView(cell, rowMode) {
    const id = cell.id, tile = tileOf(id), colour = accent(id), on = states[B(id)] ? ['on', 'open', 'playing'].includes(states[B(id)].state) : true, scene = domainOf(id) === 'scene';
    const lit = on || scene;
    const node = h('div', {class: `hd-tile${selected === ids().indexOf(id) ? ' selected' : ''}${rowMode ? ' row' : ''}`, draggable: 'true', tabindex: '0', role: 'button', 'data-id': id, 'aria-label': `${tile.label || nameOf(id)}, ${tile.size || 'quarter'}${tile.rows === 2 ? ', tall' : ''}`,
      style: `grid-column:${cell.column + 1} / span ${cell.span};grid-row:${cell.row + 1} / span ${cell.height};background:${blend(colour, '#232228', lit ? .34 : .18)};border-color:${lit ? colour : blend(colour, '#44414c', .58)}`});
    if (tile.image) node.append(h('img', {class: 'hd-art', src: artUrl(tile.image), alt: ''}));
    if (dashColumns() || B(id) in KEF) { node.classList.add('hd-dash'); if (cell.span >= 4) node.classList.add('hd-wide'); node.append(...dashBody(id, tile, colour, lit, cell.height)); }
    else if (tile.icon) node.append(h('span', {class: 'hd-icon hd-icon-tint', style: `background:${colour};opacity:${lit ? 1 : .5};-webkit-mask-image:url(${artUrl(tile.icon)});mask-image:url(${artUrl(tile.icon)})`}));
    else node.append(h('span', {class: 'hd-dot', style: `background:${colour};opacity:${lit ? 1 : .45}`}));
    if (!dashColumns()) node.append(h('span', {class: 'hd-name'}, tile.label || nameOf(id)));
    if (isCard(id) && !tile.color) { node.style.background = '#232228'; node.style.borderColor = tile.border || '#44414c'; }   // the standard card look, unless the owner picked a colour
    for (const axis of dashColumns() ? ['x', 'y', 'w', 'n', 'se', 'sw', 'ne', 'nw'] : ['x', 'y']) {
      const handle = h('span', {class: `hd-stretch hd-stretch-${axis}`, 'data-axis': axis, draggable: 'false', title: 'Drag to resize this tile', 'aria-hidden': 'true'});
      handle.onpointerdown = event => stretch(event, id, axis, node);
      handle.ondragstart = event => event.preventDefault();
      node.append(handle);
    }
    if (!(id in CARDS)) {   // a small x to take the tile off this page; the two main cards stay
      const x = h('button', {type: 'button', class: 'hd-x', 'aria-label': `Remove ${tile.label || nameOf(id)}`, title: 'Remove tile', draggable: 'false'}, '\u00d7');
      x.onclick = event => { event.stopPropagation(); removeTile(id); };
      x.onpointerdown = event => event.stopPropagation(); x.ondragstart = event => { event.preventDefault(); event.stopPropagation(); };
      node.append(x);
    }
    const open = () => { selected = ids().indexOf(id); devicesOpen = false; render(); };
    node.onclick = open;
    node.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } };
    node.ondragstart = event => { dragIndex = ids().indexOf(id); dragTile = id; dragId = null; live = null; event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', id); dragGhost(event, node); setTimeout(() => { node.classList.add('dragging'); openGrid(); }, 0); };
    // While a tile is dragged the others make room, so the drop shows exactly where it will land.
    node.ondragover = event => { if (dragTile) { event.preventDefault(); if (id !== dragTile) liveTo(null, id); } else if (dragId) { event.preventDefault(); node.classList.add('over'); } };
    node.ondragleave = () => node.classList.remove('over');
    node.ondrop = event => { event.preventDefault(); node.classList.remove('over'); if (dragTile) commitLive(); else dropDevice(null, ids().indexOf(id)); };
    node.ondragend = () => { const reverted = closeGrid(), cancelled = live !== null || reverted; dragIndex = null; dragTile = null; live = null; if (cancelled) render(); else node.classList.remove('dragging'); };
    return node;
  }
  function stretch(event, id, axis, node) {
    event.preventDefault(); event.stopPropagation();
    const portrait = screen().portrait, info = place(ids(), portrait), cell = info.cells.find(item => item.id === id); if (!cell) return;
    const columns = info.columns, box = node.getBoundingClientRect(), unitX = node.parentElement.getBoundingClientRect().width / columns, unitY = box.height / cell.height;
    const startX = event.clientX, startY = event.clientY; node.draggable = false;
    const sizeFor = span => span >= columns ? 'full' : span >= 2 && !portrait ? 'half' : 'quarter';
    const current = () => tileOf(id).size && tileOf(id).size !== 'auto' ? tileOf(id).size : 'quarter';
    const dash = dashColumns(), allowed = [...new Set([1, 2, 4, columns])].filter(value => value <= columns), maxRows = dash ? 3 : 2;
    const snap = want => allowed.reduce((best, value) => Math.abs(value - want) < Math.abs(best - want) ? value : best);
    const widthPatch = units => units === 1 ? {half: true, size: ''} : {half: '', sub: '', size: units >= columns ? 'full' : units === 4 ? 'half' : ''};
    const east = axis === 'x' || axis.includes('e'), south = axis === 'y' || axis.includes('s'), west = axis === 'w' || axis.includes('w'), north = axis === 'n' || axis.includes('n');
    const move = moveEvent => {
      const dxu = (moveEvent.clientX - startX) / unitX, dyu = (moveEvent.clientY - startY) / unitY;
      if (!dash) {
        let patch = null;
        if (east && dash) { const units = snap(cell.span + dxu); if (units !== cell.span) patch = widthPatch(units); }
        else if (east) { const size = sizeFor(Math.max(1, Math.min(columns, Math.round(cell.span + dxu)))); if (size !== current()) patch = {size}; }
        if (south) { const rows = Math.max(1, Math.min(maxRows, Math.round(cell.height + dyu))); if (rows !== cell.height) patch = {...(patch || {}), ...rowsPatch(id, rows)}; }
        if (!patch || !fitsAfter(id, patch)) return;   // a neighbour is in the way: the tile stays as it is
        selected = ids().indexOf(id); patchTile(id, patch);
      } else {
        // The edge opposite the one being dragged stays put; the tile grows towards the finger, pushing neighbours down if they are in the way.
        let units = cell.span, rows = cell.height;
        if (east) units = snap(cell.span + dxu); else if (west) units = snap(cell.span - dxu);
        if (south) rows = Math.max(1, Math.min(maxRows, Math.round(cell.height + dyu))); else if (north) rows = Math.max(1, Math.min(maxRows, Math.round(cell.height - dyu)));
        const column = west ? cell.column + cell.span - units : cell.column, row = north ? cell.row + cell.height - rows : cell.row;
        if (units === cell.span && rows === cell.height) return;
        if (column < 0 || row < 0) return;
        const saved = layout.tiles[id], patch = {...(units !== cell.span ? widthPatch(units) : {}), ...(rows !== cell.height ? rowsPatch(id, rows) : {})};
        const next = {...tileOf(id), ...patch}; for (const key of Object.keys(next)) if (next[key] === '' || next[key] === undefined) delete next[key];
        layout.tiles[id] = next;
        const after = place(ids(), portrait), mine = after.cells.find(item => item.id === id);
        const trial = makeRoom(info.cells.map(item => item.id === id ? {...item, span: mine ? mine.span : units, height: rows} : item), id, {column, row}, info);
        if (saved) layout.tiles[id] = saved; else delete layout.tiles[id];
        if (!trial) return;
        layout.tiles[id] = next; pin(trial); selected = ids().indexOf(id); markDirty(); render();
      }
      document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', done);
      const fresh = document.querySelector(`.hd-tile.selected .hd-stretch-${axis}`);
      if (fresh) fresh.dispatchEvent(new PointerEvent('pointerdown', {clientX: moveEvent.clientX, clientY: moveEvent.clientY, bubbles: true}));
    };
    const done = () => { document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', done); document.querySelectorAll('.hd-tile[data-id]').forEach(tile => { tile.draggable = true; }); };
    document.addEventListener('pointermove', move); document.addEventListener('pointerup', done);
  }
  // Put one tile where it is wanted and push any tile it lands on out of the way (down, in turn pushing the ones below), so there is no need to clear a space first.
  function makeRoom(cells, id, want, info) {
    const out = cells.map(item => item.id === id ? {...item, ...want} : {...item}), overlap = (a, b) => a.column < b.column + b.span && b.column < a.column + a.span && a.row < b.row + b.height && b.row < a.row + a.height;
    for (let guard = 0; guard < 80; guard += 1) {
      let moved = false;
      for (const a of out) for (const b of out) {
        if (a === b || !overlap(a, b)) continue;
        const loser = a.id === id ? b : b.id === id ? a : (a.row > b.row || (a.row === b.row && a.column > b.column) ? a : b), winner = loser === a ? b : a;
        loser.row = winner.row + winner.height; moved = true;
      }
      if (!moved) break;
    }
    const fine = dashColumns() ? 2 : 1;
    const ok = out.every(item => item.column >= 0 && item.column + item.span <= info.columns && item.row >= 0 && item.row + item.height <= info.rows) && out.every((a, i) => out.every((b, j) => j <= i || !overlap(a, b)));
    return ok && !(fine === 2 && out.some(item => !tileOf(item.id).half && item.column % 2)) ? out : null;
  }
  // The picture that follows the pointer: a clean rounded copy of the tile, without the remove button, resize handles or selection outline that made a square box.
  function dragGhost(event, node) {
    if (!event.dataTransfer.setDragImage || !node.parentNode) return;
    const rect = node.getBoundingClientRect(), ghost = node.cloneNode(true);
    ghost.querySelectorAll('.hd-x,.hd-stretch').forEach(item => item.remove());
    ghost.classList.remove('selected', 'dragging', 'over'); ghost.removeAttribute('draggable');
    ghost.style.cssText = `position:fixed;left:-9999px;top:0;width:${rect.width}px;height:${rect.height}px;margin:0;grid-area:auto;outline:none;box-shadow:none;opacity:.92;pointer-events:none`;
    node.parentNode.append(ghost);
    event.dataTransfer.setDragImage(ghost, Math.max(0, event.clientX - rect.left), Math.max(0, event.clientY - rect.top));
    setTimeout(() => ghost.remove(), 0);
  }
  // Put the dragged tile where it is wanted and move each tile it covers to the nearest free spot (the dragged tile's old place first), so tiles of different sizes still trade places on a full page.
  function displace(cells, id, want, info) {
    const mine = cells.find(item => item.id === id); if (!mine) return null;
    const hit = (a, b) => a.column < b.column + b.span && b.column < a.column + a.span && a.row < b.row + b.height && b.row < a.row + a.height;
    const dragged = {...mine, ...want}, inside = item => item.column >= 0 && item.column + item.span <= info.columns && item.row >= 0 && item.row + item.height <= info.rows;
    if (!inside(dragged)) return null;
    const out = [dragged, ...cells.filter(item => item.id !== id && !hit(item, dragged)).map(item => ({...item}))];
    const moved = cells.filter(item => item.id !== id && hit(item, dragged)).sort((a, b) => b.span * b.height - a.span * a.height);
    const aligned = item => !(dashColumns() && !tileOf(item.id).half && item.column % 2);
    for (const item of moved) {
      let best = null, bestDistance = Infinity;
      for (let row = 0; row < info.rows; row += 1) for (let column = 0; column < info.columns; column += 1) {
        const trial = {...item, column, row};
        if (!inside(trial) || !aligned(trial) || out.some(other => hit(other, trial))) continue;
        const distance = Math.abs(column - mine.column) + Math.abs(row - mine.row) * 2;
        if (distance < bestDistance) { best = trial; bestDistance = distance; }
      }
      if (!best) return null;
      out.push(best);
    }
    return cells.map(item => out.find(other => other.id === item.id));
  }
  // Move the dragged tile to an empty cell, or swap it with the tile under it, without redrawing so the drag is not interrupted.
  function liveTo(cellAt, targetId) {
    const info = place(ids(), screen().portrait), me = info.cells.find(item => item.id === dragTile); if (!me) return;
    const moves = {};
    if (targetId) { const there = info.cells.find(item => item.id === targetId); if (!there) return; moves[dragTile] = {column: there.column, row: there.row}; moves[targetId] = {column: me.column, row: me.row}; }
    else { let column = Math.min(cellAt.column, info.columns - me.span); if (dashColumns() && !tileOf(me.id).half) column -= column % 2; moves[dragTile] = {column, row: cellAt.row}; }
    const final = info.cells.map(item => ({...item, ...(moves[item.id] || {})}));
    const sound = final.every(item => item.column >= 0 && item.column + item.span <= info.columns && item.row >= 0 && item.row + item.height <= info.rows)
      && final.every((item, i) => final.every((other, j) => j <= i || item.column + item.span <= other.column || other.column + other.span <= item.column || item.row + item.height <= other.row || other.row + other.height <= item.row));
    let result = final;
    if (!sound || (dashColumns() && final.some(item => !tileOf(item.id).half && item.column % 2))) {
      // No clean swap or empty cell: drop it there anyway and shuffle the others down to make room.
      const spot = targetId ? info.cells.find(item => item.id === targetId) : cellAt; if (!spot) return;
      let column = Math.min(spot.column, info.columns - me.span); if (dashColumns() && !tileOf(me.id).half) column -= column % 2;
      result = displace(info.cells, dragTile, {column, row: spot.row}, info) || makeRoom(info.cells, dragTile, {column, row: spot.row}, info); if (!result) return;
    }
    live = result;
    const grid = document.querySelector('.hd-grid'); if (!grid) return;
    const nodes = [...grid.querySelectorAll('.hd-tile[data-id]')], before = new Map(nodes.map(node => [node, node.getBoundingClientRect()]));
    for (const item of result) { const node = grid.querySelector(`.hd-tile[data-id="${CSS.escape(item.id)}"]`); if (node) { node.style.gridColumn = `${item.column + 1} / span ${item.span}`; node.style.gridRow = `${item.row + 1} / span ${item.height}`; } }
    for (const node of nodes) {
      const was = before.get(node), now = node.getBoundingClientRect(), dx = was.left - now.left, dy = was.top - now.top;
      if ((dx || dy) && node.animate) node.animate([{transform: `translate(${dx}px,${dy}px)`}, {transform: 'none'}], {duration: 200, easing: 'ease-out'});
    }
    // The cells the tiles left behind become drop targets again, and the ones they now cover stop being so.
    const taken = new Set(); for (const item of result) for (let dx = 0; dx < item.span; dx += 1) for (let dy = 0; dy < item.height; dy += 1) taken.add(`${item.column + dx},${item.row + dy}`);
    grid.querySelectorAll('.hd-empty').forEach(node => node.remove());
    for (const spot of freeSpots(taken, info.columns, info.rows)) grid.append(emptySlot(spot));
  }
  function commitLive() {
    const id = dragTile, final = live; live = null; dragTile = null; dragIndex = null;
    if (!final) { closeGrid(); render(); return; }
    snapshot = null;
    pin(final); selected = ids().indexOf(id); markDirty(); render();
  }
  // A device dragged in from the list, dropped on a cell (cellAt) or on a tile (index to go before).
  function dropDevice(cellAt, index) {
    const list = deviceIds(), off = ids().length - list.length; const dropped = dragId; dragId = null;
    const id = dropped && allDevices().includes(dropped) && !onPage(dropped) ? newCopyKey(dropped) : dropped;   // a device already on another page is dropped as a copy
    if (!id || deviceIds().includes(dropped) || list.length >= LIMIT) { if (closeGrid()) render(); return; }
    snapshot = null;
    const info = place(ids(), screen().portrait); if (info.positioned || cellAt) pin(info.cells);
    if (cellAt) { list.push(id); const fine = dashColumns() ? 2 : 1, span = fine === 2 ? 2 : Math.min(info.columns, ({half: info.columns > 2 ? 2 : 1, full: info.columns}[tileOf(id).size]) || 1); let x = Math.min(cellAt.column, info.columns - span); if (fine === 2) x -= x % 2; layout.tiles[id] = {...tileOf(id), col: Math.floor(x / fine), row: cellAt.row}; selected = list.length - 1 + off; }
    else { const at = Math.max(0, index - off); list.splice(at, 0, id); selected = at + off; }
    devicesOpen = false; markDirty(); setIds(list);
  }
  // Free cells to drop on. On the dashboard a fully free column is one wide cell and a half-free one is a half cell.
  function freeSpots(taken, columns, rows) {
    const fine = dashColumns() ? 2 : 1, out = [];
    for (let row = 0; row < rows; row += 1) for (let column = 0; column < columns; column += 1) {
      if (taken.has(`${column},${row}`)) continue;
      if (fine === 2 && column % 2 === 0 && !taken.has(`${column + 1},${row}`)) { out.push({column, row, span: 2}); column += 1; } else out.push({column, row, span: 1});
    }
    return out;
  }
  function emptySlot(spot) {
    const slot = h('div', {class: 'hd-empty', 'data-col': spot.column, 'data-row': spot.row, style: `grid-column:${spot.column + 1} / span ${spot.span || 1};grid-row:${spot.row + 1}`}, spot.span === 1 && dashColumns() ? '' : 'Drop here');
    slot.ondragover = event => { if (dragTile) { event.preventDefault(); liveTo(spot, null); } else if (dragId && deviceIds().length < LIMIT) { event.preventDefault(); slot.classList.add('over'); } };
    slot.ondragleave = () => slot.classList.remove('over');
    slot.ondrop = event => { event.preventDefault(); slot.classList.remove('over'); if (dragTile) commitLive(); else dropDevice(spot, null); };
    return slot;
  }
  // The first time a tile or device is picked up, the whole screen becomes the grid: every free cell is a place to drop.
  function openGrid() {
    const portrait = screen().portrait, info = place(ids(), portrait), grid = document.querySelector('.hd-grid');
    if (info.custom || info.rowMode || !grid) return;
    snapshot = JSON.parse(JSON.stringify(layout)); pin(info.cells);
    const full = place(ids(), portrait); grid.style.gridTemplateRows = `repeat(${full.rows},minmax(0,1fr))`;
    grid.querySelectorAll('.hd-empty').forEach(node => node.remove());
    for (let row = 0; row < full.rows; row += 1) for (let column = 0; column < full.columns; column += 1) if (!full.taken.has(`${column},${row}`)) grid.append(emptySlot({column, row}));
  }
  function closeGrid() { if (snapshot) { layout = snapshot; snapshot = null; return true; } return false; }
  // A Now Playing tile much wider than it is tall puts the artwork on its left half and the track details, left-aligned, on its right.
  function markWide() {
    document.querySelectorAll('.hd-d-player').forEach(node => { const box = node.getBoundingClientRect(); const wide = !node.classList.contains('art-thumb') && !node.classList.contains('art-off') && box.height > 40 && box.width >= box.height * 1.5; node.classList.toggle('split', wide && !node.classList.contains('art-fade')); node.classList.toggle('fadewide', wide && node.classList.contains('art-fade')); });
  }
  function preview() {
    LIMIT = pageLimit();
    const shape = screen(), list = ids(), info = place(list, shape.portrait);
    const grid = h('div', {class: 'hd-grid', style: `grid-template-columns:repeat(${info.columns},minmax(0,1fr));grid-template-rows:repeat(${info.rows},minmax(0,1fr))`});
    for (const cell of info.cells) grid.append(tileView(cell, info.rowMode));
    // A drop that lands between cells, or on a cell that has just changed, still counts.
    grid.ondragover = event => { if (dragTile) event.preventDefault(); };
    grid.ondrop = event => { if (dragTile) { event.preventDefault(); commitLive(); } };
    // Every free cell is a place a tile can be dropped.
    const free = [];
    if (info.custom) free.push(...freeSpots(info.taken, info.columns, info.rows));
    else if (list.length < LIMIT) {
      const last = info.cells[info.cells.length - 1]; let column = last ? last.column + last.span : 0, row = last ? last.row : 0, left = Math.min(info.columns * info.rows - list.length, LIMIT - list.length);
      while (left > 0 && row < info.rows) { if (column >= info.columns) { column = 0; row += 1; if (row >= info.rows) break; } free.push({column, row}); column += 1; left -= 1; }
    }
    if (info.rowMode) free.length = 0;
    for (const spot of free) grid.append(emptySlot(spot));
    const title = form.elements.home_assistant_title?.value;
    const navBar = dashColumns() ? h('div', {class: 'hd-nav'}, ['Now Playing', 'Discover', 'Bus Times', 'Home'].map(name => h('span', {class: name === 'Home' ? 'on' : ''}, name))) : null;
    const screenBox = h('div', {class: `hd-screen${shape.portrait ? ' portrait' : ''}${navBar ? ' hd-dash-screen' : ''}`, style: `aspect-ratio:${shape.width} / ${shape.height};--k:${shape.portrait ? (1280 / shape.width).toFixed(3) : 1}`}, dashColumns() ? h('div', {class: 'hd-head'}, h('span', {class: 'hd-title'}, title || 'Home Controls'), h('span', {class: 'hd-clock'}, new Date().toTimeString().slice(0, 5))) : (title ? h('div', {class: 'hd-title'}, title) : null), grid, navBar);
    const dash = dashColumns();
    const columnPicker = dash && !shape.portrait ? h('div', {class: 'hd-columns'}, h('span', {}, 'Columns'), h('div', {class: 'hd-seg two', role: 'group', 'aria-label': 'Home columns'}, [2, 3].map(count => {
      const button = h('button', {type: 'button', 'aria-pressed': String(dash === count)}, `${count} columns`);
      button.onclick = () => { if (dash === count) return; layout.columns = count; markDirty(); render(); }; return button;
    }))) : null;
    const dots = pageCount() > 1 ? h('div', {class: 'hd-dots'}, Array.from({length: pageCount()}, (_, number) => h('i', {class: number === Math.min(pageNo, pageCount() - 1) ? 'on' : ''}))) : null;
    if (dots) { const head = screenBox.querySelector('.hd-head'); if (head) head.insertBefore(dots, head.lastChild); }   // in the header row, so the tiles keep their place
    return h('div', {class: 'hd-preview'}, dash ? pageBar() : null, screenBox, columnPicker, h('p', {class: 'cd-muted'}, `Preview of your ${shape.label}, ${shape.portrait ? 'portrait' : 'landscape'}. ${list.length} of ${LIMIT} tiles. Drag a tile anywhere on the grid, drag its right edge to make it wider or its bottom edge to make it taller, or drag a device in from the list.`), h('p', {class: 'cd-muted hd-note'}, 'The screen size and orientation come from Display › Screen hardware. If this preview does not match your touchscreen, set them there.'));
  }

  /* ------------------------------------------------------------ inspector */
  function iconTools() {
    async function toPng(source) {
      const canvas = h('canvas', {width: 240, height: 240}), context = canvas.getContext('2d');
      const side = Math.min(source.naturalWidth || source.width, source.naturalHeight || source.height), width = source.naturalWidth || source.width, height = source.naturalHeight || source.height;
      context.drawImage(source, (width - side) / 2, (height - side) / 2, side, side, 0, 0, 240, 240);
      return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Could not convert that image')), 'image/png'));
    }
    async function upload(name, blob) {
      const response = await fetch(`/api/admin/listening/art?name=${encodeURIComponent(name)}`, {method: 'POST', headers: {'Content-Type': 'image/png'}, body: blob});
      if (response.status === 401) { location.href = '/login.html'; throw new Error('Sign in to continue'); }
      const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Upload failed');
      if (!art.includes(name)) art = [...art, name].sort();
      return name;
    }
    const image = url => new Promise((resolve, reject) => { const node = new Image(); node.onload = () => resolve(node); node.onerror = () => reject(new Error('That file is not an image the browser can read')); node.src = url; });
    return {
      async icon(key) {
        const name = `icon-${key}-hm7.png`;
        if (art.includes(name)) return name;
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="240" viewBox="0 0 120 120"><g transform="translate(14,14) scale(3.8)" ${ICON_STYLE}>${lineArt(ICONS[key][1])}</g></svg>`;
        const url = URL.createObjectURL(new Blob([svg], {type: 'image/svg+xml'}));
        try { await upload(name, await toPng(await image(url))); } finally { URL.revokeObjectURL(url); }
        return name;
      },
      async file(file) {
        const url = URL.createObjectURL(file);
        try {
          const blob = await toPng(await image(url));
          const base = file.name.replace(/\.[^.]+$/, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40) || 'image';
          return await upload(`${base}-${Math.random().toString(36).slice(2, 6)}.png`, blob);
        } finally { URL.revokeObjectURL(url); }
      },
    };
  }
  const tools = iconTools();
  let iconCategory = 'Lights';
  const message = h('p', {class: 'cd-muted', role: 'status'});
  // Which page a tile is on, and which other pages it can be copied to. Copies are tiles of their own, so each keeps its own place and look.
  function pageField(id) {
    const count = pageCount(); if (count < 2) return null;
    const base = B(id), free = Array.from({length: count}, (_, number) => number).filter(number => !hasOnPage(base, number));
    const move = h('div', {class: 'hd-seg', role: 'group', 'aria-label': 'Page'}, Array.from({length: count}, (_, number) => {
      const button = h('button', {type: 'button', 'aria-pressed': String(pageOf(id) === number)}, `Page ${number + 1}`);
      button.disabled = pageOf(id) !== number && !free.includes(number);
      button.onclick = () => { if (pageOf(id) === number) return; selected = -1; patchTile(id, {page: number || '', col: '', row: '', sub: ''}); pageNo = number; render(); }; return button;
    }));
    const copy = free.length && newCopyKey(base) ? h('div', {class: 'hd-seg', role: 'group', 'aria-label': 'Copy to page'}, free.map(number => {
      const button = h('button', {type: 'button'}, `Page ${number + 1}`);
      button.onclick = () => { const key = newCopyKey(base); if (!key) return; layout.tiles[key] = {...tileOf(id), page: number || undefined}; if (!number) delete layout.tiles[key].page; pageNo = number; selected = -1; markDirty(); render(); selected = ids().indexOf(key); render(); }; return button;
    })) : null;
    return h('div', {class: 'hd-stack'}, field('Page', move, 'Move the tile to another page. It lands in the first free place there.'), copy ? field('Also show on', copy, 'Adds a copy on that page, which you can then move, resize and restyle on its own.') : null);
  }
  // The bus route a Next-bus tile shows first. Tapping the tile still steps through the other routes.
  function busRoute(id) {
    const routes = String(form.elements.services?.value || '').split(',').map(item => item.trim()).filter(Boolean), tile = tileOf(id);
    const select = h('select', {}, h('option', {value: ''}, 'Automatic (42, or the first route)'), (tile.route && !routes.includes(tile.route) ? [tile.route, ...routes] : routes).map(route => h('option', {value: route}, `Route ${route}`)));
    select.value = tile.route || ''; select.onchange = () => patchTile(id, {route: select.value});
    return field('Route shown', select, 'Add the bus tile more than once to keep an eye on several routes at the same time.');
  }
  // A small picture of the grid with the tile's width filled in: half a column, one, two, or all of them.
  function widthIcon(value, columns) {
    const gap = 3, total = 56, colWidth = (total - gap * (columns - 1)) / columns, fill = {'half-column': colWidth / 2, quarter: colWidth, half: colWidth * 2 + gap, full: total}[value] || colWidth;
    const track = Array.from({length: columns}, (_, n) => `<rect x="${(n * (colWidth + gap)).toFixed(1)}" y="1" width="${colWidth.toFixed(1)}" height="22" rx="3" fill="none" stroke="currentColor" stroke-opacity=".35"/>`).join('');
    const span = document.createElement('span'); span.className = 'hd-widthicon';
    span.innerHTML = `<svg viewBox="0 0 ${total} 24" width="56" height="24" aria-hidden="true">${track}<rect x="0" y="1" width="${fill.toFixed(1)}" height="22" rx="3" fill="currentColor"/></svg>`; return span;
  }
  // Page actions as icons; the words stay as the tooltip and the screen-reader label.
  function pageIcon(kind, text) {
    const paths = {add: '<path d="M12 5v14M5 12h14"/>', copy: '<rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M5 15V6.5A2.5 2.5 0 0 1 7.5 4H15"/>', trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12.5A2 2 0 0 0 9 21h6a2 2 0 0 0 2-1.5L18 7M9 7V4.5A1.5 1.5 0 0 1 10.5 3h3A1.5 1.5 0 0 1 15 4.5V7"/>'};
    const button = h('button', {type: 'button', class: 'secondary hd-iconbtn', title: text, 'aria-label': text});
    button.innerHTML = `<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${paths[kind]}</svg>`; return button;
  }
  function pageBar() {
    const count = pageCount(), here = Math.min(pageNo, count - 1), tabs = Array.from({length: count}, (_, number) => {
      const button = h('button', {type: 'button', 'aria-pressed': String(number === here)}, `Page ${number + 1}`);
      button.onclick = () => { pageNo = number; selected = -1; render(); }; return button;
    });
    const actions = [];
    if (count < MAX_PAGES) {
      const add = pageIcon('add', 'Add page'); add.onclick = () => { layout.pages = count + 1; pageNo = count; selected = -1; markDirty(); render(); }; actions.push(add);
      // A copy of this page: every tile on it is copied onto a new page, where each can be changed on its own.
      const dup = pageIcon('copy', 'Duplicate page');
      dup.onclick = () => {
        const copies = {};
        for (const key of ids()) { const target = newCopyKey(B(key)); if (!target) continue; layout.tiles[target] = {...tileOf(key), page: count}; copies[target] = true; }
        layout.pages = count + 1; pageNo = count; selected = -1; markDirty(); render();
      };
      actions.push(dup);
    }
    if (count > 1) {
      const del = pageIcon('trash', 'Delete page');
      del.title = 'Tiles that are only on this page move to page 1';
      del.onclick = () => {
        for (const id of [...textIds(), ...Object.keys(CARDS)]) if (!(id in layout.tiles)) layout.tiles[id] = {};   // tiles on the first page have no record until now
        const groups = {};
        for (const key of Object.keys(layout.tiles)) (groups[B(key)] = groups[B(key)] || []).push(key);
        const result = {};
        for (const [base, keys] of Object.entries(groups)) {
          const stay = keys.filter(key => (layout.tiles[key].page || 0) !== here).map(key => ({key, tile: {...layout.tiles[key]}}));
          for (const item of stay) { const page = item.tile.page || 0; if (page > here) { if (page - 1 > 0) item.tile.page = page - 1; else delete item.tile.page; } }
          if (!stay.length) { const tile = {...layout.tiles[keys[0]]}; for (const name of ['page', 'col', 'row', 'sub']) delete tile[name]; stay.push({key: keys[0], tile}); }   // the only copy moves to page 1
          if (!stay.some(item => item.key === base)) stay[0].key = base;   // the main tile is always the one without a number
          for (const item of stay) result[item.key] = item.tile;
        }
        layout.tiles = result;
        if (count - 1 > 1) layout.pages = count - 1; else delete layout.pages;
        pageNo = Math.max(0, here - 1); selected = -1; markDirty(); render();
      };
      actions.push(del);
    }
    return h('div', {class: 'hd-pages'}, h('div', {class: 'hd-seg', role: 'group', 'aria-label': 'Home pages'}, tabs), h('div', {class: 'hd-page-actions'}, ...actions));
  }
  function inspector() {
    const list = ids(), id = list[selected];
    if (!id) return h('div', {class: 'hd-group'}, h('h4', {}, 'Selected tile'), h('p', {class: 'cd-muted'}, 'Select a tile in the preview to change its size, label, icon, image or colour.'));
    const tile = tileOf(id), size = tile.size && tile.size !== 'auto' ? tile.size : 'quarter';
    const dash = dashColumns(), widths = dash ? [['half-column', 'Half column'], ['quarter', 'One column'], ...(dash === 3 ? [['half', 'Two columns']] : []), ['full', 'Full width']] : [['quarter', 'Quarter'], ['half', 'Half'], ['full', 'Full width']];
    const current = dash && tile.half ? 'half-column' : size;
    const segmented = h('div', {class: 'hd-seg', role: 'group', 'aria-label': 'Tile size'}, widths.map(([value, text]) => {
      const patch = value === 'half-column' ? {half: true, size: ''} : {half: '', sub: '', size: value === 'quarter' && dash ? '' : value};
      const button = h('button', {type: 'button', class: dash ? 'hd-widthbtn' : '', title: text, 'aria-label': text, 'aria-pressed': String(current === value)}, dash ? [widthIcon(value, dash), h('small', {}, text)] : text); button.onclick = () => { if (fitsAfter(id, patch)) { message.textContent = ''; patchTile(id, patch); } else message.textContent = 'There is no room for that next to the neighbouring tile.'; }; return button;
    }));
    const label = h('input', {type: 'text', maxlength: 40, placeholder: nameOf(id)}); label.value = tile.label || '';
    label.oninput = () => { const value = label.value.trim(); if (value) layout.tiles[id] = {...tileOf(id), label: value}; else if (layout.tiles[id]) { delete layout.tiles[id].label; if (!Object.keys(layout.tiles[id]).length) delete layout.tiles[id]; } markDirty(); const text = document.querySelector('.hd-tile.selected .hd-name'); if (text) text.textContent = value || nameOf(id); };
    const categories = window.DeckIconCategories || [];
    const icons = h('div', {class: 'dd-icons', role: 'group', 'aria-label': 'Icons'});
    const fill = () => icons.replaceChildren(...Object.entries(ICONS).filter(([, [, , category]]) => category === iconCategory).map(([key, [name, body]]) => {
      const choice = h('button', {type: 'button', title: name, 'aria-label': name, 'aria-pressed': tile.icon === `icon-${key}-hm7.png` ? 'true' : 'false'});
      choice.innerHTML = `<svg viewBox="0 0 24 24" width="44" height="44" aria-hidden="true" ${ICON_STYLE}>${lineArt(body)}</svg>`;
      choice.onclick = async () => { try { patchTile(id, {icon: await tools.icon(key)}); } catch (error) { message.textContent = error.message; } };
      return choice;
    }));
    const chips = h('div', {class: 'dd-chips', role: 'group', 'aria-label': 'Icon categories'}, categories.map(category => {
      const chip = h('button', {type: 'button', class: 'dd-chip', 'aria-pressed': String(iconCategory === category)}, category);
      chip.onclick = () => { iconCategory = category; chips.querySelectorAll('.dd-chip').forEach(node => node.setAttribute('aria-pressed', String(node === chip))); fill(); };
      return chip;
    }));
    fill();
    const file = h('input', {type: 'file', accept: 'image/*', hidden: true});
    file.onchange = async () => { if (!file.files[0]) return; try { patchTile(id, {image: await tools.file(file.files[0])}); message.textContent = ''; } catch (error) { message.textContent = error.message; } };
    const upload = h('button', {type: 'button', class: 'secondary'}, 'Upload image…'); upload.onclick = () => file.click();
    const clearImage = h('button', {type: 'button', class: 'secondary'}, 'No image'); clearImage.onclick = () => patchTile(id, {image: ''});
    const clearIcon = h('button', {type: 'button', class: 'secondary'}, 'Default icon'); clearIcon.onclick = () => patchTile(id, {icon: ''});
    const custom = h('input', {type: 'color', value: tile.color || accent(id), 'aria-label': 'Custom colour'});
    custom.onchange = () => patchTile(id, {color: custom.value});
    const swatches = h('div', {class: 'hd-swatches', role: 'group', 'aria-label': 'Tile colour'}, SWATCHES.map(colour => {
      const button = h('button', {type: 'button', style: `background:${colour}`, title: colour, 'aria-label': `Colour ${colour}`, 'aria-pressed': String((tile.color || '').toLowerCase() === colour)}); button.onclick = () => patchTile(id, {color: colour}); return button;
    }), custom);
    const useDefault = h('button', {type: 'button', class: 'secondary'}, 'Use the standard colour'); useDefault.onclick = () => patchTile(id, {color: ''});
    // A tile with no colour of its own can still have a brighter border; once a colour is chosen the border simply follows it.
    const borderCustom = h('input', {type: 'color', value: tile.border || '#9868f9', 'aria-label': 'Custom border colour'}); borderCustom.onchange = () => patchTile(id, {border: borderCustom.value});
    const borderSwatches = h('div', {class: 'hd-swatches', role: 'group', 'aria-label': 'Border colour'}, SWATCHES.map(colour => {
      const button = h('button', {type: 'button', style: `background:${colour}`, title: colour, 'aria-label': `Border ${colour}`, 'aria-pressed': String((tile.border || '').toLowerCase() === colour)}); button.onclick = () => patchTile(id, {border: colour}); return button;
    }), borderCustom);
    const noBorder = h('button', {type: 'button', class: 'secondary'}, 'Standard border'); noBorder.onclick = () => patchTile(id, {border: ''});
    const also = tile.also || [];
    const linkSet = (next) => patchTile(id, {also: next.length ? next : ''});
    const alsoChips = h('div', {class: 'dd-chips', role: 'group', 'aria-label': 'Devices switched together'}, also.map(other => {
      const chip = h('button', {type: 'button', class: 'dd-chip', 'aria-label': `Stop switching ${nameOf(other)} with this tile`}, `${nameOf(other)} \u00d7`); chip.onclick = () => linkSet(also.filter(item => item !== other)); return chip;
    }));
    const alsoPick = h('select', {'aria-label': 'Switch another device together with this tile'}, h('option', {value: ''}, also.length >= 4 ? 'Four is the most' : 'Add a device\u2026'),
      ...(also.length >= 4 ? [] : catalog.filter(item => ['switch', 'input_boolean', 'light', 'fan', 'climate'].includes(item.domain) && item.entity_id !== B(id) && !also.includes(item.entity_id) && !ids().includes(item.entity_id)).map(item => h('option', {value: item.entity_id}, item.name))));
    alsoPick.onchange = () => { if (alsoPick.value) linkSet([...also, alsoPick.value]); };
    const linkField = isScene(id) ? null : field('Switch together with', h('div', {class: 'hd-stack'}, alsoChips, alsoPick), 'One tap switches this device and the ones added here on or off together, for example two Pi-holes. The tile shows how many are on.');
    if (isCard(id)) {
      const drop = id in CARDS ? null : h('button', {type: 'button', class: 'secondary'}, 'Remove tile');
      if (drop) drop.onclick = () => removeTile(id);
      const check = (text, checked, patch) => { const box = h('input', {type: 'checkbox'}); box.checked = checked; box.onchange = () => patchTile(id, patch(box.checked)); return h('label', {class: 'dd-check'}, box, h('span', {}, text)); };
      const artwork = h('div', {class: 'hd-seg', role: 'group', 'aria-label': 'Artwork'}, [['background', 'Background'], ['fade', 'Fade'], ['thumb', 'Thumbnail'], ['off', 'None']].map(([value, text]) => {
        const button = h('button', {type: 'button', 'aria-pressed': String((tile.art || 'background') === value)}, text); button.onclick = () => patchTile(id, {art: value === 'background' ? '' : value}); return button;
      }));
      const alignment = h('div', {class: 'hd-seg two', role: 'group', 'aria-label': 'Text alignment'}, [['center', 'Centred'], ['left', 'Left']].map(([value, text]) => {
        const button = h('button', {type: 'button', 'aria-pressed': String((tile.align === 'left' ? 'left' : 'center') === value)}, text); button.onclick = () => patchTile(id, {align: value === 'left' ? 'left' : ''}); return button;
      }));
      const playerFields = B(id) !== 'roondeck.player' ? [] : [field('Title', label, 'Shown above the track. Leave it blank to show the zone name.'), check('Show the title', tile.heading !== false, on => ({heading: on ? '' : false})),
        field('Artwork', artwork), field('Text alignment', alignment), check('Track scrubber (drag to seek)', !!tile.scrubber, on => ({scrubber: on ? true : ''})), check('Volume slider', tile.volume !== false, on => ({volume: on ? '' : false}))];
      const netFields = B(id) !== 'roondeck.network' ? [] : (() => {
        const down = tile.download !== false, up = tile.upload !== false;
        const one = (text, on, other, key) => { const box = h('input', {type: 'checkbox'}); box.checked = on; box.disabled = on && !other; box.onchange = () => patchTile(id, {[key]: box.checked ? '' : false}); return h('label', {class: 'dd-check'}, box, h('span', {}, text)); };
        return [field('Show', h('div', {class: 'hd-stack'}, one('Download', down, up, 'download'), one('Upload', up, down, 'upload')), 'Switch either direction off. One must stay on.')];
      })();
      const groupFields = !GROUPS.includes(B(id)) ? [] : (() => {
        const names = [...new Set(roonOutputs.map(item => item.name))];
        const pick = (key, empty) => { const select = h('select', {}, h('option', {value: ''}, empty), names.concat(tile[key] && !names.includes(tile[key]) ? [tile[key]] : []).map(name => h('option', {value: name}, name))); select.value = tile[key] || ''; select.onchange = () => patchTile(id, {[key]: select.value}); return select; };
        return [field('Zone', pick('zone', names.length ? 'Choose a zone' : 'No Roon zones found'), 'The zone that joins the group.'), field('Group with', pick('with', 'Choose a zone'), 'The zone to group it with. Tap the tile to group; tap again to ungroup.')];
      })();
      return h('div', {class: 'hd-group'}, h('h4', {}, `Selected tile \u00b7 ${nameOf(id)}`), ...(B(id) in KEF ? [field('Title', label)] : []), ...playerFields, ...netFields, ...groupFields,
        B(id) === 'roondeck.bus' ? h('div', {class: 'hd-stack'}, busRoute(id), h('p', {class: 'cd-muted'}, 'The tile takes the colour of the route it shows. Choose route colours and their strength under Services \u203a Bus.')) : field('Colour', h('div', {class: 'hd-stack'}, swatches, tile.color ? useDefault : null)), (isCard(id) && B(id) !== 'roondeck.bus' && !tile.color) ? field('Border', h('div', {class: 'hd-stack'}, borderSwatches, tile.border ? noBorder : null), 'A brighter border for a tile that has no colour. Choose a colour above and the border follows it.') : null,
        field('Width', segmented, 'Drag the tile to move it, its right edge to change the width (down to half a column), or its bottom edge to change the height.'), pageField(id), drop ? h('div', {class: 'hd-actions'}, drop) : null, message);
    }
    const remove = h('button', {type: 'button', class: 'secondary'}, 'Remove tile'); remove.onclick = () => removeTile(id);
    return h('div', {class: 'hd-group'}, h('h4', {}, `Selected tile · ${nameOf(id)}`),
      field('Width', segmented, 'Sizes snap to the screen grid. Drag a tile\u2019s right edge to change its width, or its bottom edge to make it taller.'), pageField(id),
      field('Label', label), linkField, field('Icon', h('div', {class: 'hd-stack'}, chips, icons, clearIcon)),
      h('div', {class: 'hd-actions'}, upload, clearImage, h('small', {}, 'An image fills the tile behind the icon and label.')), file,
      field(tile.color ? 'Colour when on (set for this tile)' : 'Colour when on (standard for this kind of device)', h('div', {class: 'hd-stack'}, swatches, tile.color ? useDefault : null)),
      h('div', {class: 'hd-actions'}, remove), message);
  }

  /* ------------------------------------------------------------ device list */
  function devices() {
    const list = deviceIds();
    const search = h('input', {type: 'search', placeholder: 'Search your Home Assistant devices', autocomplete: 'off', 'aria-label': 'Search Home Assistant'}); search.value = query;
    const results = h('ul', {class: 'hd-results'});
    const filters = {All: () => true, Lights: item => item.domain === 'light', Fans: item => item.domain === 'fan', Switches: item => ['switch', 'input_boolean'].includes(item.domain), Scenes: item => item.domain === 'scene', Scripts: item => item.domain === 'script'};
    const chips = h('div', {class: 'dd-chips', role: 'group', 'aria-label': 'Device type'}, Object.keys(filters).map(name => {
      const chip = h('button', {type: 'button', class: 'dd-chip', 'aria-pressed': String(kind === name)}, name);
      chip.onclick = () => { kind = name; chips.querySelectorAll('.dd-chip').forEach(node => node.setAttribute('aria-pressed', String(node === chip))); fillResults(); }; return chip;
    }));
    function fillResults() {
      const needle = query.trim().toLowerCase(), current = deviceIds(), taken = deviceIds().map(B);
      const matches = catalog.filter(item => !taken.includes(item.entity_id) && filters[kind](item) && (!needle || item.name.toLowerCase().includes(needle) || item.entity_id.includes(needle))).slice(0, 40);
      results.replaceChildren(...(matches.length ? matches.map(item => {
        const add = h('button', {type: 'button', class: 'secondary hd-add', 'aria-label': `Add ${item.name}`}, 'Add'); add.disabled = current.length >= LIMIT;
        add.onclick = () => { selected = ids().length; devicesOpen = false; setIds([...deviceIds(), item.entity_id]); };
        const row = h('li', {draggable: 'true'}, h('span', {class: 'hd-grip', 'aria-hidden': 'true'}, '⋮⋮'), h('span', {class: 'hd-label'}, item.name, h('small', {}, item.entity_id)), add);
        row.ondragstart = event => { dragId = item.entity_id; dragIndex = null; event.dataTransfer.effectAllowed = 'copy'; event.dataTransfer.setData('text/plain', item.entity_id); setTimeout(openGrid, 0); };
        row.ondragend = () => { dragId = null; if (closeGrid()) render(); };
        return row;
      }) : [h('li', {class: 'hd-none'}, 'No devices match.')]));
    }
    search.oninput = () => { query = search.value; fillResults(); };
    fillResults();
    // Closed once the tiles are chosen, so the controls for the selected tile stay in view.
    const isOpen = devicesOpen === null ? list.length === 0 : devicesOpen;
    // Two sources of tiles, switched at the top: RoonDeck's own (first, as they are the quickest to add) and Home Assistant devices.
    const dash = !!dashColumns();
    const haPanel = h('div', {class: 'hd-add-panel'}, search, chips, results, h('p', {class: 'cd-muted'}, 'Drag a device onto the preview, or press Add.'));
    const OWN = [['roondeck.player', 'Now Playing', 'Artwork, track, transport and volume'], ['roondeck.bus', 'Bus times', 'Next arrivals for your stop'], ...Object.entries(LIVE).map(([key, name]) => [key, name, key in KEF ? (key === 'roondeck.kef' ? 'Power, input and volume together' : key === 'roondeck.kef_power' ? 'Wake for Roon or put the speaker in standby' : key === 'roondeck.kef_input' ? 'Wi-Fi, AUX, optical and Bluetooth' : 'Speaker volume and mute') : key === 'roondeck.cpu' ? 'Load, temperature and a live graph' : key === 'roondeck.memory' ? 'RAM in use, with a live graph' : key === 'roondeck.volume' ? 'A large volume number with minus and plus' : key === 'roondeck.update' ? 'Check for and install the latest RoonDeck' : GROUPS.includes(key) ? 'Group or ungroup one Roon zone with another' : 'Throughput with a live graph'])];
    const ownPanel = h('ul', {class: 'hd-results hd-own'}, OWN.filter(([key]) => dash || key in KEF).map(([key, name, note]) => {
      const here = ids().some(other => B(other) === key && (!(key in LIVE) || layout.tiles[other]?.show)), more = key === 'roondeck.bus' && here && !!newCopyKey(key);   // the bus tile can be added again, once per route
      const add = h('button', {type: 'button', class: 'secondary hd-add'}, more ? 'Add another' : here ? (key in LIVE ? 'Added' : 'On screen') : 'Add'); add.disabled = here && !more;
      add.onclick = () => {
        // A tile that is already on another page is added here as a copy with its own place.
        const elsewhere = key in LIVE ? !!layout.tiles[key]?.show : true, target = elsewhere && (key in CARDS || layout.tiles[key]) ? newCopyKey(key) : key;
        if (!target) return;
        layout.tiles[target] = withPage({...(target === key ? layout.tiles[key] || {} : {}), ...(key in LIVE ? {show: true} : {}), ...(key === 'roondeck.kef' ? {rows: 2, size: 'half'} : {})});
        devicesOpen = false; markDirty(); render(); selected = ids().indexOf(target); render();
      };
      return h('li', {}, h('span', {class: 'hd-label'}, name, h('small', {}, note)), add);
    }));
    let source = addSource === 'ha' ? 'ha' : 'own';
    const body = h('div', {class: 'hd-accordion-body'});
    const switcher = h('div', {class: 'hd-seg two', role: 'group', 'aria-label': 'Tile source'}, [['own', 'RoonDeck'], ['ha', 'Home Assistant']].map(([value, text]) => {
      const button = h('button', {type: 'button', 'aria-pressed': String(source === value)}, text);
      button.onclick = () => { addSource = value; source = value; fillBody(); }; return button;
    }));
    function fillBody() { switcher?.querySelectorAll('button').forEach((node, i) => node.setAttribute('aria-pressed', String(source === ['own', 'ha'][i]))); body.replaceChildren(...[switcher, source === 'own' ? ownPanel : haPanel].filter(Boolean)); }
    fillBody();
    const box = h('details', {class: 'hd-accordion'}, h('summary', {}, h('span', {}, 'Add tiles'), h('small', {}, `${ids().length} of ${LIMIT} tiles used`)), body);
    if (isOpen) box.setAttribute('open', '');
    box.ontoggle = () => { devicesOpen = box.open; };
    return box;
  }

  /* ------------------------------------------------------------ colours preview */
  function coloursPreview() {
    const sample = [['light.sample_light', 'Light', true], ['fan.sample_fan', 'Fan', false], ['switch.sample_switch', 'Switch', true], ['scene.sample_scene', 'Scene', false]];
    const grid = h('div', {class: 'hd-grid hd-sample', style: 'grid-template-columns:repeat(2,minmax(0,1fr))'});
    for (const [id, name, on] of sample) {
      const colour = accent(id);
      grid.append(h('div', {class: 'hd-tile', style: `background:${blend(colour, '#232228', on ? .34 : .18)};border-color:${on ? colour : blend(colour, '#44414c', .58)}`}, h('span', {class: 'hd-dot', style: `background:${colour};opacity:${on ? 1 : .45}`}), h('span', {class: 'hd-name'}, name)));
    }
    return h('div', {class: 'hd-preview'}, h('div', {class: 'hd-screen', style: 'aspect-ratio:auto;padding:18px'}, grid), h('p', {class: 'cd-muted'}, 'The standard colour for each kind of device. A single tile can override its colour in Layout.'));
  }

  /* ------------------------------------------------------------ structure */
  const layoutPane = h('div', {class: 'dd-pane hd-layout'});
  const coloursArt = h('div', {class: 'hd-side'});
  const statusArt = h('div', {class: 'hd-side hd-status'});
  const settingsText = h('div', {class: 'hd-text'});
  const coloursText = h('div', {class: 'hd-text'});
  const settingsPane = h('div', {class: 'dd-pane dd-wake hd-two', hidden: true}, settingsText, statusArt);
  const coloursPane = h('div', {class: 'dd-pane dd-wake hd-two', hidden: true}, coloursText, coloursArt);
  const labelOf = name => form.elements[name]?.closest('label');
  for (const name of ['home_assistant_url', 'home_assistant_token']) { const label = labelOf(name); if (label) settingsText.append(label); }
  const entitiesLabel = textarea.closest('label');
  entitiesLabel.hidden = true; settingsText.append(entitiesLabel);
  const deckField = form.elements.home_assistant_deck_entities; if (deckField) deckField.hidden = true;
  // Everything from the colours heading onwards moves, as it is, into the Colours tab so the existing controls keep working.
  const heading = [...options.querySelectorAll('h4')].find(node => /colours/i.test(node.textContent));
  if (heading) { let node = heading.nextSibling; heading.remove(); const moving = []; while (node) { moving.push(node); node = node.nextSibling; } coloursText.append(h('div', {class: 'hd-eyebrow'}, 'TILE COLOURS'), ...moving); }
  const tabNames = [['layout', 'Layout', layoutPane], ['colours', 'Colours', coloursPane], ['setup', 'Setup', settingsPane]];
  const buttons = tabNames.map(([id, text]) => h('button', {type: 'button', role: 'tab', 'aria-selected': String(id === 'layout')}, text));
  function show(index) {
    tabNames.forEach(([, , pane], i) => { pane.hidden = i !== index; buttons[i].setAttribute('aria-selected', String(i === index)); });
    render();
  }
  buttons.forEach((button, index) => { button.onclick = () => show(index); });
  const tabs = h('nav', {class: 'dd-tabs', role: 'tablist', 'aria-label': 'Home sections'}, buttons);
  const card = h('div', {class: 'cd-card dd-card hd-card'}, tabs, h('div', {class: 'dd-body'}, layoutPane, coloursPane, settingsPane));
  options.prepend(card);
  // The page heading sits before the "Show Home on the touchscreen" switch, where it is easy to find.
  const enabledLabel = labelOf('home_assistant_enabled'), titleLabel = labelOf('home_assistant_title');
  if (enabledLabel && titleLabel) { const row = h('div', {class: 'hd-headrow-set'}); enabledLabel.before(row); row.append(titleLabel, enabledLabel); }
  // The old introduction under the heading is replaced by the cards below it.
  for (const small of [...options.children].filter(node => node.tagName === 'SMALL')) small.hidden = true;

  function render() {
    // Status panel (Settings tab)
    const icon = h('div', {class: 'hd-status-icon'});
    icon.innerHTML = '<svg width="120" height="120" viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 56 60 18l44 38"/><path d="M26 50v48h68V50"/><path d="M50 98V70h20v28"/></svg>';
    statusArt.replaceChildren(icon, h('div', {class: 'hd-status-title'}, catalog.length ? 'Connected' : 'Not connected yet'),
      h('div', {class: 'hd-status-note'}, catalog.length ? `${catalog.length} devices found in Home Assistant` : 'Save the address and token, then reload to browse your devices.'));
    if (!layoutPane.hidden) {
        entitiesLabel.hidden = true;
        layoutPane.className = 'dd-pane hd-layout hd-two';
        LIMIT = pageLimit();
        layoutPane.replaceChildren(h('div', {class: 'hd-text'}, devices(), inspector()), h('div', {class: 'hd-side'}, preview()));
        markWide();
    }
    if (!coloursPane.hidden) coloursArt.replaceChildren(coloursPreview());
  }
  // Live colour previews while the colour boxes are edited.
  options.addEventListener('input', event => { if (event.target.closest?.('[data-colour-panel], .home-colour-row') && !coloursPane.hidden) coloursArt.replaceChildren(coloursPreview()); });
  options.addEventListener('click', () => setTimeout(() => { if (!coloursPane.hidden) coloursArt.replaceChildren(coloursPreview()); }, 0));
  // The title and the list also change from the other tabs and when settings load: refresh after those edits.
  let lastIds = null;
  setInterval(() => { const now = `${textarea.value}|${form.elements.home_assistant_title?.value}`; if (now !== lastIds) { lastIds = now; if (!layoutPane.hidden || !coloursPane.hidden) render(); } }, 500);

  window.RoonDeckSaves = window.RoonDeckSaves || {};
  window.RoonDeckSaves.homelayout = async () => {
    const response = await fetch('/api/admin/home-layout', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({tiles: Object.fromEntries(Object.entries(layout.tiles).filter(([id, tile]) => (isCard(id) || allIds().includes(id)) && /^[a-z_]+\.[a-z0-9_]{1,100}(#[1-3])?$/.test(id) && tile && typeof tile === 'object').map(([id, tile]) => [id, Object.fromEntries(Object.entries(tile).filter(([key, value]) => TILE_KEYS.has(key) && value !== null && value !== undefined))])), ...(layout.columns ? {columns: layout.columns} : {}), ...(pageCount() > 1 ? {pages: pageCount()} : {})})});
    const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Could not save the Home layout');
    layout = result.layout; dirty = false;
  };

  async function load() {
    const json = async (url) => { try { const response = await fetch(url, {cache: 'no-store'}); return response.ok ? await response.json() : null; } catch (_) { return null; } };
    const [cat, status, art_, saved, sys, outs] = await Promise.all([json('/api/admin/home-catalog'), json('/api/home/status'), json('/api/admin/listening/art'), json('/api/admin/home-layout'), json('/api/admin/system'), json('/roon/api/accessory/outputs')]);
    roonOutputs = outs?.outputs || [];
    catalog = (cat?.entities) || [];
    states = Object.fromEntries([...(status?.entities || []), ...(status?.deck_entities || [])].map(item => [item.entity_id, item]));
    art = art_?.art || []; if (saved?.tiles && !dirty) layout = {tiles: saved.tiles, ...(saved.columns ? {columns: saved.columns} : {}), ...(saved.pages ? {pages: saved.pages} : {})}; system = sys || {};
    render();
    // Icons made by earlier versions are small in their tile: redraw them at the full size.
    for (const [id, tile] of Object.entries(layout.tiles)) {
      const old = /^icon-(.+)-(?:hd5|hm6)\.png$/.exec(tile.icon || '');
      if (old && ICONS[old[1]]) { try { layout.tiles[id] = {...tile, icon: await tools.icon(old[1])}; markDirty(); } catch (_) { /* keep the old icon */ } }
    }
    render();
  }
  // Home settings load after the page opens; refresh when the Home Assistant tab is shown or saved.
  document.addEventListener('click', event => { if (event.target.closest?.('[data-service-tab="home"], #save-settings')) setTimeout(load, 1200); });
  load();
})();
