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
  let catalog = [], states = {}, art = [], layout = {tiles: {}}, system = {}, selected = -1, query = '', kind = 'All', dirty = false, dragId = null, dragIndex = null, dragTile = null, live = null, devicesOpen = null;
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
    for (const key of Object.keys(next)) if (!next[key]) delete next[key];
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
  // The same placement rules as the touchscreen: tiles with a chosen size flow along 4 columns (2 in portrait).
  function place(list, portrait) {
    const custom = list.some(id => (tileOf(id).size && tileOf(id).size !== 'auto') || tileOf(id).rows === 2);
    if (!custom) {
      if (portrait) return {columns: 1, rows: Math.max(1, list.length), cells: list.map((id, i) => ({id, column: 0, row: i, span: 1, height: 1})), custom, rowMode: true};
      if (list.length === 6) return {columns: 4, rows: 2, custom, rowMode: false, cells: list.map((id, i) => i < 2 ? {id, column: i, row: 0, span: 1, height: 2} : {id, column: 2 + (i - 2) % 2, row: Math.floor((i - 2) / 2), span: 1, height: 1})};
      return {columns: 4, rows: Math.max(1, Math.ceil(list.length / 4)), custom, rowMode: false, cells: list.map((id, i) => ({id, column: i % 4, row: Math.floor(i / 4), span: 1, height: 1}))};
    }
    const columns = portrait ? 2 : 4, spans = {quarter: 1, half: portrait ? 1 : 2, full: columns};
    // First free place scanning left to right, then down: the touchscreen uses the same rule.
    const taken = new Set(), cells = []; let rows = 1;
    for (const id of list) {
      const span = Math.min(columns, spans[tileOf(id).size] || 1), height = tileOf(id).rows === 2 ? 2 : 1;
      let placed = false;
      for (let row = 0; !placed; row += 1) for (let column = 0; column + span <= columns && !placed; column += 1) {
        const spots = []; for (let dx = 0; dx < span; dx += 1) for (let dy = 0; dy < height; dy += 1) spots.push(`${column + dx},${row + dy}`);
        if (spots.some(spot => taken.has(spot))) continue;
        spots.forEach(spot => taken.add(spot)); cells.push({id, column, row, span, height}); rows = Math.max(rows, row + height); placed = true;
      }
    }
    return {columns, rows, cells, custom, rowMode: false};
  }

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
    const index = ids().indexOf(id);
    for (const axis of ['x', 'y']) {
      const handle = h('span', {class: `hd-stretch hd-stretch-${axis}`, 'data-axis': axis, draggable: 'false', title: axis === 'x' ? 'Drag to make this tile wider or narrower' : 'Drag to make this tile taller or shorter', 'aria-hidden': 'true'});
      handle.onpointerdown = event => stretch(event, id, axis, node);
      handle.ondragstart = event => event.preventDefault();
      node.append(handle);
    }
    const open = () => { selected = ids().indexOf(id); devicesOpen = false; render(); };
    node.onclick = open;
    node.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } };
    node.ondragstart = event => { dragIndex = index; dragTile = id; dragId = null; live = null; event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', id); setTimeout(() => node.classList.add('dragging'), 0); };
    // While a tile is dragged the others slide out of the way, so the drop shows exactly where it will land.
    node.ondragover = event => { if (dragTile) { event.preventDefault(); liveMove(id); } else if (dragId) { event.preventDefault(); node.classList.add('over'); } };
    node.ondragleave = () => node.classList.remove('over');
    node.ondrop = event => { event.preventDefault(); node.classList.remove('over'); if (dragTile) commitLive(); else dropAt(index); };
    node.ondragend = () => { const cancelled = live !== null; dragIndex = null; dragTile = null; live = null; if (cancelled) render(); else node.classList.remove('dragging'); };
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
      if (!patch) return;
      selected = ids().indexOf(id); patchTile(id, patch);
      document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', done);
      const fresh = document.querySelector(`.hd-tile.selected .hd-stretch-${axis}`);
      if (fresh) fresh.dispatchEvent(new PointerEvent('pointerdown', {clientX: moveEvent.clientX, clientY: moveEvent.clientY, bubbles: true}));
    };
    const done = () => { document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', done); document.querySelectorAll('.hd-tile[data-id]').forEach(tile => { tile.draggable = true; }); };
    document.addEventListener('pointermove', move); document.addEventListener('pointerup', done);
  }
  // Slide the tiles into the order of `list` without redrawing them, so a drag in progress is not interrupted.
  function liveMove(targetId) {
    const list = live || ids(), from = list.indexOf(dragTile), to = list.indexOf(targetId);
    if (from < 0 || to < 0 || from === to) return;
    const next = [...list]; const [moved] = next.splice(from, 1); next.splice(to, 0, moved); live = next;
    const grid = document.querySelector('.hd-grid'); if (!grid) return;
    const nodes = [...grid.querySelectorAll('.hd-tile[data-id]')], before = new Map(nodes.map(node => [node, node.getBoundingClientRect()]));
    const info = place(next, screen().portrait);
    for (const cell of info.cells) { const node = grid.querySelector(`.hd-tile[data-id="${CSS.escape(cell.id)}"]`); if (node) { node.style.gridColumn = `${cell.column + 1} / span ${cell.span}`; node.style.gridRow = `${cell.row + 1} / span ${cell.height}`; } }
    for (const node of nodes) {
      const was = before.get(node), now = node.getBoundingClientRect(), dx = was.left - now.left, dy = was.top - now.top;
      if ((dx || dy) && node.animate) node.animate([{transform: `translate(${dx}px,${dy}px)`}, {transform: 'none'}], {duration: 200, easing: 'ease-out'});
    }
  }
  function commitLive() {
    const list = live || ids(), id = dragTile; live = null; dragTile = null; dragIndex = null;
    selected = list.indexOf(id); setIds(list);
  }
  function dropAt(index) {
    const list = ids();
    if (dragTile) commitLive();
    else if (dragId && !list.includes(dragId) && list.length < LIMIT) { list.splice(index, 0, dragId); selected = index; dragId = null; devicesOpen = false; setIds(list); }
  }
  function preview() {
    const shape = screen(), list = ids(), layoutInfo = place(list, shape.portrait);
    const empties = Math.max(0, Math.min(layoutInfo.columns * layoutInfo.rows - list.length, LIMIT - list.length));
    const grid = h('div', {class: 'hd-grid', style: `grid-template-columns:repeat(${layoutInfo.columns},minmax(0,1fr));grid-template-rows:repeat(${layoutInfo.rows + (list.length < LIMIT && !layoutInfo.rowMode ? 0 : 0)},minmax(0,1fr))`});
    for (const cell of layoutInfo.cells) grid.append(tileView(cell, layoutInfo.rowMode));
    if (list.length < LIMIT) {
      const last = layoutInfo.cells[layoutInfo.cells.length - 1];
      let column = last ? last.column + last.span : 0, row = last ? last.row : 0, free = Math.max(1, empties);
      while (free > 0 && row < layoutInfo.rows + 1) {
        if (column >= layoutInfo.columns) { column = 0; row += 1; if (row >= layoutInfo.rows) break; }
        const slot = h('div', {class: 'hd-empty', style: `grid-column:${column + 1};grid-row:${row + 1}`}, 'Drop here');
        slot.ondragover = event => { if (dragId || dragTile) { event.preventDefault(); slot.classList.add('over'); } };
        slot.ondragleave = () => slot.classList.remove('over');
        slot.ondrop = event => { event.preventDefault(); dropAt(ids().length); };
        grid.append(slot); column += 1; free -= 1;
      }
    }
    const title = form.elements.home_assistant_title?.value;
    const screenBox = h('div', {class: `hd-screen${shape.portrait ? ' portrait' : ''}`, style: `aspect-ratio:${shape.width} / ${shape.height}`}, title ? h('div', {class: 'hd-title'}, title) : null, grid);
    return h('div', {class: 'hd-preview'}, screenBox, h('p', {class: 'cd-muted'}, `Preview of your ${shape.label}, ${shape.portrait ? 'portrait' : 'landscape'}. ${list.length} of ${LIMIT} tiles. Drag a tile to reorder it, drag its right edge to make it wider or its bottom edge to make it taller, or drag a device in from the list.`), h('p', {class: 'cd-muted hd-note'}, 'The screen size and orientation come from Display › Screen hardware. If this preview does not match your touchscreen, set them there.'));
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
      const button = h('button', {type: 'button', 'aria-pressed': String(size === value)}, text); button.onclick = () => patchTile(id, {size: value}); return button;
    }));
    const tall = tile.rows === 2 ? 2 : 1;
    const heights = h('div', {class: 'hd-seg two', role: 'group', 'aria-label': 'Tile height'}, [[1, 'Normal'], [2, 'Tall']].map(([value, text]) => {
      const button = h('button', {type: 'button', 'aria-pressed': String(tall === value)}, text); button.onclick = () => patchTile(id, {rows: value === 2 ? 2 : ''}); return button;
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
    const here = ids().indexOf(id);
    const shift = by => { const next = ids(); const [moved] = next.splice(here, 1); next.splice(here + by, 0, moved); selected = here + by; setIds(next); };
    const earlier = h('button', {type: 'button', class: 'secondary'}, '← Move earlier'); earlier.disabled = here <= 0; earlier.onclick = () => shift(-1);
    const later = h('button', {type: 'button', class: 'secondary'}, 'Move later →'); later.disabled = here >= ids().length - 1; later.onclick = () => shift(1);
    const remove = h('button', {type: 'button', class: 'secondary'}, 'Remove tile'); remove.onclick = () => { const next = ids().filter(other => other !== id); selected = -1; setIds(next); };
    return h('div', {class: 'hd-group'}, h('h4', {}, `Selected tile · ${nameOf(id)}`),
      field('Width', segmented, 'Sizes snap to the screen grid. You can also drag a tile\u2019s right edge.'), field('Height', heights, 'A tall tile fills two rows. Drag its bottom edge, or choose here.'),
      field('Label', label), field('Icon', h('div', {class: 'hd-stack'}, chips, icons, clearIcon)),
      h('div', {class: 'hd-actions'}, upload, clearImage, h('small', {}, 'An image fills the tile behind the icon and label.')), file,
      field(tile.color ? 'Colour when on (set for this tile)' : 'Colour when on (standard for this kind of device)', h('div', {class: 'hd-stack'}, swatches, tile.color ? useDefault : null)),
      h('div', {class: 'hd-actions'}, earlier, later, remove), message);
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
        row.ondragstart = event => { dragId = item.entity_id; dragIndex = null; event.dataTransfer.effectAllowed = 'copy'; event.dataTransfer.setData('text/plain', item.entity_id); };
        row.ondragend = () => { dragId = null; };
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
