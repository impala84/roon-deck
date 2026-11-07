/* Home Assistant settings as tabs: Settings, Layout (screen designer) and Colours. */
(() => {
  const panel = document.querySelector('[data-service-panel="home"]');
  const options = document.getElementById('home-options');
  const textarea = document.querySelector('textarea[name="home_assistant_entities"]');
  if (!panel || !options || !textarea) return;
  const form = textarea.form;
  const ICONS = window.DeckIcons || {};
  const LIMIT = 8;
  const DEFAULT_COLOURS = {light: '#fb923c', fan: '#60a5fa', switch: '#9868f9', scene: '#a3e635'};
  const SWATCHES = ['#fb923c', '#60a5fa', '#9868f9', '#a3e635', '#e85d3a', '#d94f8c', '#3fc7a0', '#e9e4da'];
  const lineArt = body => body.replace(/fill="#fff"/g, 'fill="none"');
  const ICON_STYLE = 'stroke="#fff" stroke-width="0.75" stroke-linecap="round" stroke-linejoin="round" fill="none"';
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
  let catalog = [], states = {}, art = [], layout = {tiles: {}}, system = {}, selected = -1, query = '', kind = 'All', dirty = false, dragId = null, dragIndex = null, dragTile = null, live = null, devicesOpen = null, snapshot = null;
  const ids = () => textarea.value.split(',').map(item => item.trim()).filter(Boolean);
  const nameOf = id => catalog.find(item => item.entity_id === id)?.name || states[id]?.name || id;
  const tileOf = id => layout.tiles[id] || {};
  const markDirty = () => { dirty = true; window.RoonDeckDirty?.('homelayout', 'Home layout'); };
  function setIds(list) {
    textarea.value = list.join(', ');
    textarea.dispatchEvent(new Event('input', {bubbles: true}));
    render();
  }
  function patchTile(id, patch) {
    const next = {...tileOf(id), ...patch};
    for (const key of Object.keys(next)) if (next[key] === '' || next[key] === undefined || next[key] === null) delete next[key];
    if (Object.keys(next).length) layout.tiles[id] = next; else delete layout.tiles[id];
    markDirty(); render();
  }
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
  // The same placement rules as the touchscreen. Tiles the owner placed (col/row) keep their cell; the rest take the first free space.
  const hasPlace = id => Number.isInteger(tileOf(id).col) && Number.isInteger(tileOf(id).row);
  function place(list, portrait) {
    const positioned = list.some(hasPlace);
    const custom = positioned || list.some(id => (tileOf(id).size && tileOf(id).size !== 'auto') || tileOf(id).rows === 2);
    if (!custom) {
      if (portrait) return {columns: 1, rows: Math.max(1, list.length), cells: list.map((id, i) => ({id, column: 0, row: i, span: 1, height: 1})), custom, positioned, rowMode: true, taken: new Set()};
      if (list.length === 6) return {columns: 4, rows: 2, custom, positioned, rowMode: false, taken: new Set(), cells: list.map((id, i) => i < 2 ? {id, column: i, row: 0, span: 1, height: 2} : {id, column: 2 + (i - 2) % 2, row: Math.floor((i - 2) / 2), span: 1, height: 1})};
      return {columns: 4, rows: Math.max(1, Math.ceil(list.length / 4)), custom, positioned, rowMode: false, taken: new Set(), cells: list.map((id, i) => ({id, column: i % 4, row: Math.floor(i / 4), span: 1, height: 1}))};
    }
    const columns = portrait ? 2 : 4, spans = {quarter: 1, half: portrait ? 1 : 2, full: columns};
    const taken = new Set(), at = new Map();
    const spots = (column, row, span, height) => { const out = []; for (let dx = 0; dx < span; dx += 1) for (let dy = 0; dy < height; dy += 1) out.push(`${column + dx},${row + dy}`); return out; };
    const dims = id => ({span: Math.min(columns, spans[tileOf(id).size] || 1), height: tileOf(id).rows === 2 ? 2 : 1});
    for (const id of list) {
      const {span, height} = dims(id), tile = tileOf(id);
      if (hasPlace(id) && tile.col + span <= columns && !spots(tile.col, tile.row, span, height).some(spot => taken.has(spot))) { spots(tile.col, tile.row, span, height).forEach(spot => taken.add(spot)); at.set(id, {id, column: tile.col, row: tile.row, span, height}); }
    }
    for (const id of list) {
      if (at.has(id)) continue;
      const {span, height} = dims(id); let done = false;
      for (let row = 0; !done; row += 1) for (let column = 0; column + span <= columns && !done; column += 1) {
        const here = spots(column, row, span, height); if (here.some(spot => taken.has(spot))) continue;
        here.forEach(spot => taken.add(spot)); at.set(id, {id, column, row, span, height}); done = true;
      }
    }
    const cells = list.map(id => at.get(id));
    const used = Math.max(1, ...cells.map(cell => cell.row + cell.height));
    return {columns, rows: Math.max(used, Math.ceil(LIMIT / columns)), cells, custom, positioned, rowMode: false, taken};
  }
  // Would the owner's tiles all keep their cells if this tile took on these settings?
  function fitsAfter(id, patch) {
    const portrait = screen().portrait, before = place(ids(), portrait); if (!before.positioned) return true;
    const old = layout.tiles[id], next = {...tileOf(id), ...patch}; for (const key of Object.keys(next)) if (next[key] === '' || next[key] === undefined) delete next[key];
    layout.tiles[id] = next; const after = place(ids(), portrait); if (old) layout.tiles[id] = old; else delete layout.tiles[id];
    return before.cells.every(cell => { const now = after.cells.find(item => item.id === cell.id); return now && now.column === cell.column && now.row === cell.row && now.row + now.height <= after.rows; });
  }
  // Give every tile an explicit cell, so moving one never shuffles the others.
  function pin(cells) { for (const cell of cells) layout.tiles[cell.id] = {...tileOf(cell.id), col: cell.column, row: cell.row, ...(cell.height === 2 ? {rows: 2} : {})}; }

  /* ------------------------------------------------------------ preview */
  function tileView(cell, rowMode) {
    const id = cell.id, tile = tileOf(id), colour = accent(id), on = states[id] ? ['on', 'open', 'playing'].includes(states[id].state) : true, scene = domainOf(id) === 'scene';
    const lit = on || scene;
    const node = h('div', {class: `hd-tile${selected === ids().indexOf(id) ? ' selected' : ''}${rowMode ? ' row' : ''}`, draggable: 'true', tabindex: '0', role: 'button', 'data-id': id, 'aria-label': `${tile.label || nameOf(id)}, ${tile.size || 'quarter'}${tile.rows === 2 ? ', tall' : ''}`,
      style: `grid-column:${cell.column + 1} / span ${cell.span};grid-row:${cell.row + 1} / span ${cell.height};background:${blend(colour, '#232228', lit ? .34 : .18)};border-color:${lit ? colour : blend(colour, '#44414c', .58)}`});
    if (tile.image) node.append(h('img', {class: 'hd-art', src: artUrl(tile.image), alt: ''}));
    if (tile.icon) node.append(h('img', {class: 'hd-icon', src: artUrl(tile.icon), alt: '', style: `opacity:${lit ? 1 : .5}`}));
    else node.append(h('span', {class: 'hd-dot', style: `background:${colour};opacity:${lit ? 1 : .45}`}));
    node.append(h('span', {class: 'hd-name'}, tile.label || nameOf(id)));
    for (const axis of ['x', 'y']) {
      const handle = h('span', {class: `hd-stretch hd-stretch-${axis}`, 'data-axis': axis, draggable: 'false', title: axis === 'x' ? 'Drag to make this tile wider or narrower' : 'Drag to make this tile taller or shorter', 'aria-hidden': 'true'});
      handle.onpointerdown = event => stretch(event, id, axis, node);
      handle.ondragstart = event => event.preventDefault();
      node.append(handle);
    }
    const open = () => { selected = ids().indexOf(id); devicesOpen = false; render(); };
    node.onclick = open;
    node.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } };
    node.ondragstart = event => { dragIndex = ids().indexOf(id); dragTile = id; dragId = null; live = null; event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', id); setTimeout(() => { node.classList.add('dragging'); openGrid(); }, 0); };
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
    const move = moveEvent => {
      let patch = null;
      if (axis === 'x') { const size = sizeFor(Math.max(1, Math.min(columns, Math.round(cell.span + (moveEvent.clientX - startX) / unitX)))); if (size !== current()) patch = {size}; }
      else { const rows = Math.max(1, Math.min(2, Math.round(cell.height + (moveEvent.clientY - startY) / unitY))); if (rows !== (tileOf(id).rows === 2 ? 2 : 1)) patch = {rows: rows === 2 ? 2 : ''}; }
      if (!patch || !fitsAfter(id, patch)) return;   // a neighbour is in the way: the tile stays as it is
      selected = ids().indexOf(id); patchTile(id, patch);
      document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', done);
      const fresh = document.querySelector(`.hd-tile.selected .hd-stretch-${axis}`);
      if (fresh) fresh.dispatchEvent(new PointerEvent('pointerdown', {clientX: moveEvent.clientX, clientY: moveEvent.clientY, bubbles: true}));
    };
    const done = () => { document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', done); document.querySelectorAll('.hd-tile[data-id]').forEach(tile => { tile.draggable = true; }); };
    document.addEventListener('pointermove', move); document.addEventListener('pointerup', done);
  }
  // Move the dragged tile to an empty cell, or swap it with the tile under it, without redrawing so the drag is not interrupted.
  function liveTo(cellAt, targetId) {
    const info = place(ids(), screen().portrait), me = info.cells.find(item => item.id === dragTile); if (!me) return;
    const moves = {};
    if (targetId) { const there = info.cells.find(item => item.id === targetId); if (!there) return; moves[dragTile] = {column: there.column, row: there.row}; moves[targetId] = {column: me.column, row: me.row}; }
    else moves[dragTile] = {column: Math.min(cellAt.column, info.columns - me.span), row: cellAt.row};
    const final = info.cells.map(item => ({...item, ...(moves[item.id] || {})}));
    const sound = final.every(item => item.column >= 0 && item.column + item.span <= info.columns && item.row >= 0 && item.row + item.height <= info.rows)
      && final.every((item, i) => final.every((other, j) => j <= i || item.column + item.span <= other.column || other.column + other.span <= item.column || item.row + item.height <= other.row || other.row + other.height <= item.row));
    if (!sound) return;
    live = final;
    const grid = document.querySelector('.hd-grid'); if (!grid) return;
    const nodes = [...grid.querySelectorAll('.hd-tile[data-id]')], before = new Map(nodes.map(node => [node, node.getBoundingClientRect()]));
    for (const item of final) { const node = grid.querySelector(`.hd-tile[data-id="${CSS.escape(item.id)}"]`); if (node) { node.style.gridColumn = `${item.column + 1} / span ${item.span}`; node.style.gridRow = `${item.row + 1} / span ${item.height}`; } }
    for (const node of nodes) {
      const was = before.get(node), now = node.getBoundingClientRect(), dx = was.left - now.left, dy = was.top - now.top;
      if ((dx || dy) && node.animate) node.animate([{transform: `translate(${dx}px,${dy}px)`}, {transform: 'none'}], {duration: 200, easing: 'ease-out'});
    }
    // The cells the tiles left behind become drop targets again, and the ones they now cover stop being so.
    const taken = new Set(); for (const item of final) for (let dx = 0; dx < item.span; dx += 1) for (let dy = 0; dy < item.height; dy += 1) taken.add(`${item.column + dx},${item.row + dy}`);
    grid.querySelectorAll('.hd-empty').forEach(node => node.remove());
    for (let row = 0; row < info.rows; row += 1) for (let column = 0; column < info.columns; column += 1) if (!taken.has(`${column},${row}`)) grid.append(emptySlot({column, row}));
  }
  function commitLive() {
    const id = dragTile, final = live; live = null; dragTile = null; dragIndex = null;
    if (!final) { closeGrid(); render(); return; }
    snapshot = null;
    pin(final); selected = ids().indexOf(id); markDirty(); render();
  }
  // A device dragged in from the list, dropped on a cell (cellAt) or on a tile (index to go before).
  function dropDevice(cellAt, index) {
    const list = ids(); const id = dragId; dragId = null;
    if (!id || list.includes(id) || list.length >= LIMIT) { if (closeGrid()) render(); return; }
    snapshot = null;
    const info = place(list, screen().portrait); if (info.positioned || cellAt) pin(info.cells);
    if (cellAt) { list.push(id); const span = Math.min(info.columns, ({half: info.columns > 2 ? 2 : 1, full: info.columns}[tileOf(id).size]) || 1); layout.tiles[id] = {...tileOf(id), col: Math.min(cellAt.column, info.columns - span), row: cellAt.row}; selected = list.length - 1; }
    else { list.splice(index, 0, id); selected = index; }
    devicesOpen = false; markDirty(); setIds(list);
  }
  function emptySlot(spot) {
    const slot = h('div', {class: 'hd-empty', 'data-col': spot.column, 'data-row': spot.row, style: `grid-column:${spot.column + 1};grid-row:${spot.row + 1}`}, 'Drop here');
    slot.ondragover = event => { if (dragTile) { event.preventDefault(); liveTo(spot, null); } else if (dragId && ids().length < LIMIT) { event.preventDefault(); slot.classList.add('over'); } };
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
  function preview() {
    const shape = screen(), list = ids(), info = place(list, shape.portrait);
    const grid = h('div', {class: 'hd-grid', style: `grid-template-columns:repeat(${info.columns},minmax(0,1fr));grid-template-rows:repeat(${info.rows},minmax(0,1fr))`});
    for (const cell of info.cells) grid.append(tileView(cell, info.rowMode));
    // A drop that lands between cells, or on a cell that has just changed, still counts.
    grid.ondragover = event => { if (dragTile) event.preventDefault(); };
    grid.ondrop = event => { if (dragTile) { event.preventDefault(); commitLive(); } };
    // Every free cell is a place a tile can be dropped.
    const free = [];
    if (info.custom) { for (let row = 0; row < info.rows; row += 1) for (let column = 0; column < info.columns; column += 1) if (!info.taken.has(`${column},${row}`)) free.push({column, row}); }
    else if (list.length < LIMIT) {
      const last = info.cells[info.cells.length - 1]; let column = last ? last.column + last.span : 0, row = last ? last.row : 0, left = Math.min(info.columns * info.rows - list.length, LIMIT - list.length);
      while (left > 0 && row < info.rows) { if (column >= info.columns) { column = 0; row += 1; if (row >= info.rows) break; } free.push({column, row}); column += 1; left -= 1; }
    }
    if (info.rowMode) free.length = 0;
    for (const spot of free) grid.append(emptySlot(spot));
    const title = form.elements.home_assistant_title?.value;
    const screenBox = h('div', {class: `hd-screen${shape.portrait ? ' portrait' : ''}`, style: `aspect-ratio:${shape.width} / ${shape.height}`}, title ? h('div', {class: 'hd-title'}, title) : null, grid);
    return h('div', {class: 'hd-preview'}, screenBox, h('p', {class: 'cd-muted'}, `Preview of your ${shape.label}, ${shape.portrait ? 'portrait' : 'landscape'}. ${list.length} of ${LIMIT} tiles. Drag a tile anywhere on the grid, drag its right edge to make it wider or its bottom edge to make it taller, or drag a device in from the list.`), h('p', {class: 'cd-muted hd-note'}, 'The screen size and orientation come from Display › Screen hardware. If this preview does not match your touchscreen, set them there.'));
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
        const name = `icon-${key}-hd5.png`;
        if (art.includes(name)) return name;
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="240" viewBox="0 0 120 120"><g transform="translate(34,20) scale(2.2)" ${ICON_STYLE}>${lineArt(ICONS[key][1])}</g></svg>`;
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
  function inspector() {
    const list = ids(), id = list[selected];
    if (!id) return h('div', {class: 'hd-group'}, h('h4', {}, 'Selected tile'), h('p', {class: 'cd-muted'}, 'Select a tile in the preview to change its size, label, icon, image or colour.'));
    const tile = tileOf(id), size = tile.size && tile.size !== 'auto' ? tile.size : 'quarter';
    const segmented = h('div', {class: 'hd-seg', role: 'group', 'aria-label': 'Tile size'}, [['quarter', 'Quarter'], ['half', 'Half'], ['full', 'Full width']].map(([value, text]) => {
      const button = h('button', {type: 'button', 'aria-pressed': String(size === value)}, text); button.onclick = () => { if (fitsAfter(id, {size: value})) { message.textContent = ''; patchTile(id, {size: value}); } else message.textContent = 'There is no room for that next to the neighbouring tile.'; }; return button;
    }));
    const label = h('input', {type: 'text', maxlength: 40, placeholder: nameOf(id)}); label.value = tile.label || '';
    label.oninput = () => { const value = label.value.trim(); if (value) layout.tiles[id] = {...tileOf(id), label: value}; else if (layout.tiles[id]) { delete layout.tiles[id].label; if (!Object.keys(layout.tiles[id]).length) delete layout.tiles[id]; } markDirty(); const text = document.querySelector('.hd-tile.selected .hd-name'); if (text) text.textContent = value || nameOf(id); };
    const categories = window.DeckIconCategories || [];
    const icons = h('div', {class: 'dd-icons', role: 'group', 'aria-label': 'Icons'});
    const fill = () => icons.replaceChildren(...Object.entries(ICONS).filter(([, [, , category]]) => category === iconCategory).map(([key, [name, body]]) => {
      const choice = h('button', {type: 'button', title: name, 'aria-label': name, 'aria-pressed': tile.icon === `icon-${key}-hd5.png` ? 'true' : 'false'});
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
    const remove = h('button', {type: 'button', class: 'secondary'}, 'Remove tile'); remove.onclick = () => { const next = ids().filter(other => other !== id); selected = -1; setIds(next); };
    return h('div', {class: 'hd-group'}, h('h4', {}, `Selected tile · ${nameOf(id)}`),
      field('Width', segmented, 'Sizes snap to the screen grid. Drag a tile\u2019s right edge to change its width, or its bottom edge to make it taller.'),
      field('Label', label), field('Icon', h('div', {class: 'hd-stack'}, chips, icons, clearIcon)),
      h('div', {class: 'hd-actions'}, upload, clearImage, h('small', {}, 'An image fills the tile behind the icon and label.')), file,
      field(tile.color ? 'Colour when on (set for this tile)' : 'Colour when on (standard for this kind of device)', h('div', {class: 'hd-stack'}, swatches, tile.color ? useDefault : null)),
      h('div', {class: 'hd-actions'}, remove), message);
  }

  /* ------------------------------------------------------------ device list */
  function devices() {
    const list = ids();
    const search = h('input', {type: 'search', placeholder: 'Search your Home Assistant devices', autocomplete: 'off', 'aria-label': 'Search Home Assistant'}); search.value = query;
    const results = h('ul', {class: 'hd-results'});
    const filters = {All: () => true, Lights: item => item.domain === 'light', Fans: item => item.domain === 'fan', Switches: item => ['switch', 'input_boolean'].includes(item.domain), Scenes: item => item.domain === 'scene', Scripts: item => item.domain === 'script'};
    const chips = h('div', {class: 'dd-chips', role: 'group', 'aria-label': 'Device type'}, Object.keys(filters).map(name => {
      const chip = h('button', {type: 'button', class: 'dd-chip', 'aria-pressed': String(kind === name)}, name);
      chip.onclick = () => { kind = name; chips.querySelectorAll('.dd-chip').forEach(node => node.setAttribute('aria-pressed', String(node === chip))); fillResults(); }; return chip;
    }));
    function fillResults() {
      const needle = query.trim().toLowerCase(), current = ids();
      const matches = catalog.filter(item => !current.includes(item.entity_id) && filters[kind](item) && (!needle || item.name.toLowerCase().includes(needle) || item.entity_id.includes(needle))).slice(0, 40);
      results.replaceChildren(...(matches.length ? matches.map(item => {
        const add = h('button', {type: 'button', class: 'secondary hd-add', 'aria-label': `Add ${item.name}`}, 'Add'); add.disabled = current.length >= LIMIT;
        add.onclick = () => { selected = current.length; devicesOpen = false; setIds([...ids(), item.entity_id]); };
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
    const box = h('details', {class: 'hd-accordion'}, h('summary', {}, h('span', {}, 'Add devices'), h('small', {}, `${list.length} of ${LIMIT} tiles used`)), h('div', {class: 'hd-accordion-body'}, search, chips, results,
      h('p', {class: 'cd-muted'}, 'Drag a device onto the preview, or press Add.')));
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
  for (const name of ['home_assistant_title', 'home_assistant_url', 'home_assistant_token']) { const label = labelOf(name); if (label) settingsText.append(label); }
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
  // The old introduction under the heading is replaced by the cards below it.
  for (const small of [...options.children].filter(node => node.tagName === 'SMALL')) small.hidden = true;

  function render() {
    // Status panel (Settings tab)
    const icon = h('div', {class: 'hd-status-icon'});
    icon.innerHTML = '<svg width="120" height="120" viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 56 60 18l44 38"/><path d="M26 50v48h68V50"/><path d="M50 98V70h20v28"/></svg>';
    statusArt.replaceChildren(icon, h('div', {class: 'hd-status-title'}, catalog.length ? 'Connected' : 'Not connected yet'),
      h('div', {class: 'hd-status-note'}, catalog.length ? `${catalog.length} devices found in Home Assistant` : 'Save the address and token, then reload to browse your devices.'));
    if (!layoutPane.hidden) {
      if (!catalog.length) {
        layoutPane.replaceChildren(h('div', {class: 'hd-group'}, h('h4', {}, 'Devices'), h('p', {class: 'cd-muted'}, 'Home Assistant is not reachable yet, so devices cannot be browsed. Enter entity IDs, separated by commas, or save the address and token first.'), entitiesLabel));
        entitiesLabel.hidden = false;
      } else {
        entitiesLabel.hidden = true;
        layoutPane.className = 'dd-pane hd-layout hd-two';
        layoutPane.replaceChildren(h('div', {class: 'hd-text'}, devices(), inspector()), h('div', {class: 'hd-side'}, preview()));
      }
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
    const response = await fetch('/api/admin/home-layout', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({tiles: Object.fromEntries(Object.entries(layout.tiles).filter(([id]) => ids().includes(id)))})});
    const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Could not save the Home layout');
    layout = result.layout; dirty = false;
  };

  async function load() {
    const json = async (url) => { try { const response = await fetch(url, {cache: 'no-store'}); return response.ok ? await response.json() : null; } catch (_) { return null; } };
    const [cat, status, art_, saved, sys] = await Promise.all([json('/api/admin/home-catalog'), json('/api/home/status'), json('/api/admin/listening/art'), json('/api/admin/home-layout'), json('/api/admin/system')]);
    catalog = (cat?.entities) || [];
    states = Object.fromEntries([...(status?.entities || []), ...(status?.deck_entities || [])].map(item => [item.entity_id, item]));
    art = art_?.art || []; if (saved?.tiles && !dirty) layout = {tiles: saved.tiles}; system = sys || {};
    render();
  }
  // Home settings load after the page opens; refresh when the Home Assistant tab is shown or saved.
  document.addEventListener('click', event => { if (event.target.closest?.('[data-service-tab="home"], #save-settings')) setTimeout(load, 1200); });
  load();
})();
