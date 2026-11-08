/* Visual Stream Deck + designer: click a key, strip segment or dial to edit it and see exactly what the device will show. */
(() => {
  // Controls sub-tabs: Listening & KEF, Stream Deck, Surface Dial.
  const tabs = [...document.querySelectorAll('[data-controls-tab]')];
  function showControlsTab(name) {
    tabs.forEach(tab => tab.setAttribute('aria-selected', String(tab.dataset.controlsTab === name)));
    document.querySelectorAll('[data-controls-panel]').forEach(panel => { panel.hidden = panel.dataset.controlsPanel !== name; });
    try { sessionStorage.setItem('controls-tab', name); } catch (_) {}
  }
  tabs.forEach(tab => { tab.onclick = () => showControlsTab(tab.dataset.controlsTab); });
  try { const saved = sessionStorage.getItem('controls-tab'); if (saved) showControlsTab(saved); } catch (_) {}
  const root = document.getElementById('deck-designer');
  if (!root) return;
  const SHARED = () => window.RoonDeckListening;
  const KEY_DEFAULT = '#11201d';
  const SWATCHES = ['#11201d', '#236650', '#1f3a6e', '#6b2d7a', '#8a2f2f', '#8a5a14', '#3a3a3a', '#000000'];
  const KEY_ACTIONS = [
    ['none', 'Unused'], ['power', 'KEF power'], ['input', 'KEF input'], ['mute', 'KEF mute'],
    ['previous', 'Previous track'], ['playpause', 'Play / pause'], ['next', 'Next track'], ['home_toggle', 'Home device on / off'], ['home_scene', 'Home scene'], ['home_script', 'Home script (e.g. IR remote)'],
  ];
  const DIAL_ACTIONS = [['none', 'Unused'], ['volume_delta', 'KEF volume'], ['roon_volume', 'Roon volume (current zone)'], ['home_level', 'Home brightness / fan speed'], ['home_script_dial', 'Home scripts (e.g. IR volume)'], ['remote_steps', 'IR remote steps (e.g. aircon temperature)']];
  const PRESS_ACTIONS = [['none', 'Unused'], ['mute', 'KEF mute'], ['roon_mute', 'Roon mute'], ['playpause', 'Play / pause'], ['home_toggle', 'Toggle a Home device'], ['home_script', 'Run a Home script'], ['remote_toggle', 'IR remote on / off (e.g. aircon power)']];
  // KEF-only actions disappear while the KEF speakers are switched off (a saved binding keeps showing its own action).
  const KEF_ACTIONS = new Set(['power', 'input', 'mute', 'volume_delta']);
  const kefOn = () => !!SHARED().settings.enabled;
  const available = (list, current) => list.filter(([id]) => kefOn() || !KEF_ACTIONS.has(id) || id === current);
  const TEXT_SWATCHES = ['#ffffff', '#a4dcc7', '#6ef0be', '#ffd166', '#f2b991', '#8ecbff', '#ff8fa3', '#000000'];
  const SOURCES = [['aux', 'Aux'], ['optical', 'Optical'], ['wifi', 'Wi‑Fi'], ['bluetooth', 'Bluetooth']];
  const DEFAULT_LABEL = {mode: '', power: '', input: '', mute: 'Mute', previous: 'Previous', playpause: 'Play / Pause', next: 'Next', home_toggle: '', home_scene: '', home_script: ''};
  const DEFAULT_ICON = {mute: 'mute', previous: 'previous', playpause: 'playpause', next: 'next', power: 'power', input: 'input', home_toggle: 'bulb', home_scene: 'scene', home_script: 'input', mode: 'speaker'};
  const ICONS = window.DeckIcons || {};
  // Solid shapes read as chunky on a small key, so every glyph is drawn as a fine outline.
  const lineArt = body => body.replace(/fill="#fff"/g, 'fill="none"');
  const ICON_STYLE = 'stroke="#fff" stroke-width="0.75" stroke-linecap="round" stroke-linejoin="round" fill="none"';
  let iconCategory = "Playback";

  const h = (tag, props = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (key === 'class') node.className = value; else if (key === 'style') node.style.cssText = value; else if (key.startsWith('on')) node[key] = value;
      else if (value !== undefined && value !== null && value !== false) node.setAttribute(key, value === true ? '' : value);
    }
    node.append(...children.flat().filter(child => child !== null && child !== undefined && child !== false));
    return node;
  };
  const selectOf = (options, value) => { const select = h('select'); for (const [id, name] of options) select.add(new Option(name, id)); select.value = options.some(([id]) => id === value) ? value : options[0][0]; return select; };
  const field = (text, control, hint) => h('label', {class: 'cd-field'}, h('span', {}, text), control, hint ? h('small', {}, hint) : null);

  let buttons = [], dials = [], art = [], entities = [], catalog = [], haUrl = '', selection = {type: 'key', index: 0}, dirty = false, built = false, dragFrom = null;
  const status = h('p', {role: 'status', class: 'cd-message'});
  const notice = h('span', {class: 'dd-dirty', hidden: true}, 'Unsaved changes');
  const connection = h('span', {class: 'cd-muted'});
  const stage = h('div', {class: 'dd-stage'});
  const inspector = h('div', {class: 'dd-inspector'});
  let enableBox, sleepBox, revertButton, supportRow, supportNote, supportButton, installTried = false;

  const blankKey = () => ({label: '', action: 'none'});
  const blankDial = () => ({label: '', action: 'none', step: 1, press: {action: 'none'}});
  const clone = value => JSON.parse(JSON.stringify(value));
  const defaultButtons = [
    {label: 'Wi-Fi', action: 'input', value: 'wifi'}, {label: 'AUX', action: 'input', value: 'aux'}, {label: 'Optical', action: 'input', value: 'optical'},
    {label: 'Power on', action: 'power', value: true}, {label: 'Standby', action: 'power', value: false},
    {label: 'Previous', action: 'previous'}, {label: 'Play / Pause', action: 'playpause'}, {label: 'Next', action: 'next'}];

  function adopt() {
    const settings = SHARED().settings;
    const saved = settings.buttons?.length ? settings.buttons : (kefOn() ? defaultButtons : defaultButtons.filter(item => !KEF_ACTIONS.has(item.action)));
    buttons = Array.from({length: 8}, (_, i) => clone(saved[i] || blankKey()));
    const savedDials = settings.dials?.length ? settings.dials : (kefOn() ? [{label: 'KEF volume', action: 'volume_delta', step: 1, press: {action: 'mute'}}] : []);
    dials = Array.from({length: 4}, (_, i) => ({...blankDial(), ...clone(savedDials[i] || {})}));
    dials.forEach(dial => { dial.press = dial.press || {action: 'none'}; });
    onPlay = {...(settings.on_play || {})};
    dirty = false;
  }
  const markDirty = () => { dirty = true; notice.hidden = false; window.RoonDeckDirty?.('streamdeck', 'Stream Deck'); };
  const entityName = id => entities.find(item => item.entity_id === id)?.name || catalog.find(item => item.entity_id === id)?.name || id || '';
  const artUrl = name => `/api/admin/listening/art/${encodeURIComponent(name)}`;

  function describe(binding) {
    switch (binding.action) {
      case 'power': return binding.value === false ? 'Standby' : 'Power on';
      case 'input': return `Input · ${binding.value || '—'}`;
      case 'home_toggle': case 'home_scene': return entityName(binding.entity_id) || 'Choose a device';
      case 'home_script': return entityName(binding.entity_id) || 'Choose a script';
      default: return (KEY_ACTIONS.find(([id]) => id === binding.action) || [])[1] || '';
    }
  }

  /* ------------------------------------------------------------ device preview */
  const GLOW = '#c98a22', GLOW_SWATCHES = ['#c98a22', '#e8c14d', '#e85d3a', '#d94f8c', '#8a5cf0', '#3d8bff', '#3fc7a0', '#e9e4da'];
  const mix = (a, b, t) => { const n = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16)); const x = n(a), y = n(b); return `rgb(${x.map((v, i) => Math.round(v + (y[i] - v) * t)).join(',')})`; };
  function levelOf(id) {
    const item = entities.find(entry => entry.entity_id === id);
    if (!item || item.state !== 'on') return 0;
    return item.percentage ?? Math.round((item.brightness || 0) / 2.55);
  }
  // The same sun the deck draws: more and longer rays, and a warmer background, as the light gets brighter.
  function sunSvg(level) {
    const amount = Math.max(0, Math.min(1, level / 100)), rays = level <= 0 ? 0 : amount < .3 ? 4 : amount < .7 ? 8 : 12;
    const length = 5 + 11 * amount, opacity = .4 + .6 * amount;
    let out = '<circle cx="60" cy="46" r="11" fill="none" stroke="#fff" stroke-width="1.6"/>';
    for (let i = 0; i < rays; i++) {
      const angle = 2 * Math.PI * i / rays + (rays === 4 ? Math.PI / 4 : 0);
      out += `<line x1="${(60 + Math.cos(angle) * 17).toFixed(1)}" y1="${(46 + Math.sin(angle) * 17).toFixed(1)}" x2="${(60 + Math.cos(angle) * (17 + length)).toFixed(1)}" y2="${(46 + Math.sin(angle) * (17 + length)).toFixed(1)}" stroke="#fff" stroke-opacity="${opacity.toFixed(2)}" stroke-width="1.6" stroke-linecap="round"/>`;
    }
    return `<svg class="dd-sun" viewBox="0 0 120 120" aria-hidden="true">${out}</svg>`;
  }
  function keyTile(index) {
    const binding = buttons[index];
    const tile = h('button', {type: 'button', class: 'dd-key', draggable: 'true', 'aria-label': `Key ${index + 1}: ${binding.label || describe(binding) || 'unused'}`,
      'aria-pressed': selection.type === 'key' && selection.index === index ? 'true' : 'false', style: `background:${binding.color || KEY_DEFAULT}`});
    const level = binding.level_entity ? levelOf(binding.level_entity) : null;
    if (level !== null) {
      if (level > 0) tile.style.background = mix(binding.color || KEY_DEFAULT, binding.level_color || GLOW, Math.min(.85, .18 + .67 * level / 100));
      tile.insertAdjacentHTML('beforeend', sunSvg(level));
    } else if (binding.image) tile.append(h('img', {src: artUrl(binding.image), alt: '', draggable: 'false'}));
    if (binding.action === 'none' && !binding.label && !binding.image) tile.append(h('span', {class: 'dd-empty'}, '+'));
    else if (binding.label) tile.append(h('span', {class: `dd-label${binding.image ? ' low' : ''}`}, binding.label));
    tile.append(h('span', {class: 'dd-index'}, index + 1));
    tile.onclick = () => { selection = {type: 'key', index}; render(); };
    tile.ondragstart = event => { dragFrom = index; event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', String(index)); };
    tile.ondragover = event => { if (dragFrom !== null) { event.preventDefault(); tile.classList.add('over'); } };
    tile.ondragleave = () => tile.classList.remove('over');
    tile.ondrop = event => {
      event.preventDefault(); tile.classList.remove('over');
      if (dragFrom === null || dragFrom === index) return;
      [buttons[dragFrom], buttons[index]] = [buttons[index], buttons[dragFrom]];
      selection = {type: 'key', index}; dragFrom = null; markDirty(); render();
    };
    tile.ondragend = () => { dragFrom = null; };
    return tile;
  }
  function segment(index) {
    const dial = dials[index];
    const detail = dial.action === 'volume_delta' || dial.action === 'roon_volume' ? '20%' : dial.action === 'home_level' ? (dial.entity_id ? '60%' : 'Choose device') : dial.action === 'remote_steps' ? `${dial.start ?? ''}${dial.unit || ''}` : '';
    const node = h('button', {type: 'button', class: 'dd-segment', ...(dial.color ? {style: `background:${dial.color}`} : {}), 'aria-label': `Strip ${index + 1}: ${dial.label || 'unused'}`, 'aria-pressed': selection.type === 'dial' && selection.index === index ? 'true' : 'false'},
      h('strong', dial.text_color ? {style: `color:${dial.text_color}`} : {}, dial.label || (dial.action === 'none' ? '' : 'Dial')), h('span', dial.text_color ? {style: `color:${dial.text_color}`} : {}, detail));
    node.onclick = () => { selection = {type: 'dial', index}; render(); };
    return node;
  }
  function knob(index) {
    const node = h('button', {type: 'button', class: 'dd-knob', 'aria-label': `Dial ${index + 1}`, 'aria-pressed': selection.type === 'dial' && selection.index === index ? 'true' : 'false'}, h('span', {}, index + 1));
    node.onclick = () => { selection = {type: 'dial', index}; render(); };
    return node;
  }
  function drawStage() {
    const device = h('div', {class: 'dd-device'},
      h('div', {class: 'dd-keys'}, buttons.map((_, i) => keyTile(i))),
      h('div', {class: 'dd-strip'}, dials.map((_, i) => segment(i))),
      h('div', {class: 'dd-knobs'}, dials.map((_, i) => knob(i))));
    stage.replaceChildren(device, h('p', {class: 'cd-muted dd-hint'}, 'Click a key, strip section or dial to edit it. Drag keys to swap them.'));
  }

  /* ------------------------------------------------------------ inspector */
  function targetEditor(binding, onChange) {
    const settings = SHARED().settings, change = () => { onChange(); };
    switch (binding.action) {
      case 'power': {
        const select = selectOf([['true', 'Power on'], ['false', 'Standby']], String(binding.value !== false)); binding.value = select.value === 'true';
        select.onchange = () => { binding.value = select.value === 'true'; change(); };
        return field('Switch to', select);
      }
      case 'input': {
        const select = selectOf(SOURCES, binding.value); binding.value = select.value;
        select.onchange = () => { binding.value = select.value; change(); };
        return field('KEF input', select);
      }
      case 'home_toggle': case 'home_scene': return withLink(entityPicker(binding, change, binding.action === 'home_scene' ? item => item.domain === 'scene' : item => item.domain !== 'scene' && item.domain !== 'script', binding.action === 'home_scene' ? 'Scene' : 'Home device'), binding.action === 'home_scene' ? 'scene' : null);
      case 'home_script': return withLink(entityPicker(binding, change, item => item.domain === 'script', 'Script'), 'script');
      default: return null;
    }
  }
  // A shortcut to where scripts and scenes are made in Home Assistant, opened in its own tab.
  function haLink(kind) {
    if (!/^https?:\/\//i.test(haUrl)) return null;
    const page = kind === 'scene' ? 'scene' : 'script';
    return h('a', {class: 'dd-ha-link', href: `${haUrl.replace(/\/+$/, '')}/config/${page}/dashboard`, target: '_blank', rel: 'noopener'}, `Create or edit ${page}s in Home Assistant ↗`);
  }
  function withLink(node, kind) { const link = haLink(kind); return link ? h('div', {class: 'dd-linked'}, node, link) : node; }
  function entityPicker(binding, onChange, filter = () => true, labelText = 'Home device', key = 'entity_id') {
    // Everything shared on Home, plus every other device Home Assistant knows about, so a new script appears without extra setup.
    const known = new Set(entities.map(item => item.entity_id));
    const list = [...entities, ...catalog.filter(item => !known.has(item.entity_id))].filter(filter);
    if (binding[key] && !list.some(item => item.entity_id === binding[key])) list.push({entity_id: binding[key], name: entityName(binding[key])});
    if (!list.length) {
      const input = h('input', {type: 'text', placeholder: 'light.living_room', autocomplete: 'off', spellcheck: 'false'}); input.value = binding[key] || '';
      input.oninput = () => { binding[key] = input.value.trim(); onChange(); };
      return field(labelText, input, 'No Home devices are shared with RoonDeck yet, so enter the Home Assistant entity ID.');
    }
    const select = selectOf([['', 'Choose…'], ...list.map(item => [item.entity_id, item.name])], binding[key] || '');
    select.onchange = () => { binding[key] = select.value; onChange(); };
    return field(labelText, select);
  }

  // Square-crop and shrink to a 120×120 PNG in the browser, so only small safe images reach the Pi.
  async function toPng(source, size = 240) {
    const canvas = h('canvas', {width: size, height: size}), context = canvas.getContext('2d');
    const width = source.naturalWidth || source.width, height = source.naturalHeight || source.height, side = Math.min(width, height);
    context.drawImage(source, (width - side) / 2, (height - side) / 2, side, side, 0, 0, size, size);
    return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Could not convert that image')), 'image/png'));
  }
  async function upload(name, blob) {
    const response = await fetch(`/api/admin/listening/art?name=${encodeURIComponent(name)}`, {method: 'POST', headers: {'Content-Type': 'image/png'}, body: blob});
    if (response.status === 401) { location.href = '/login.html'; throw new Error('Sign in to continue'); }
    const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Upload failed');
    if (!art.includes(name)) art = [...art, name].sort();
    return name;
  }
  async function pickFile(file, binding) {
    if (!file) return;
    try {
      const url = URL.createObjectURL(file);
      const image = await new Promise((resolve, reject) => { const node = new Image(); node.onload = () => resolve(node); node.onerror = () => reject(new Error('That file is not an image the browser can read')); node.src = url; });
      const blob = await toPng(image); URL.revokeObjectURL(url);
      const base = (file.name.replace(/\.[^.]+$/, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40) || 'image');
      binding.image = await upload(`${base}-${Math.random().toString(36).slice(2, 6)}.png`, blob);
      status.textContent = 'Image added.'; markDirty(); render();
    } catch (error) { status.textContent = error.message; }
  }
  const iconFile = key => `icon-${key}-hd5.png`;
  async function ensureIcon(key) {
    const name = iconFile(key);
    if (art.includes(name)) return name;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="240" viewBox="0 0 120 120"><g transform="translate(34,20) scale(2.2)" ${ICON_STYLE}>${lineArt(ICONS[key][1])}</g></svg>`;
    const url = URL.createObjectURL(new Blob([svg], {type: 'image/svg+xml'}));
    try {
      const image = await new Promise((resolve, reject) => { const node = new Image(); node.onload = () => resolve(node); node.onerror = () => reject(new Error('Could not draw that icon')); node.src = url; });
      await upload(name, await toPng(image));
    } finally { URL.revokeObjectURL(url); }
    return name;
  }
  async function useIcon(key, binding) {
    try { binding.image = await ensureIcon(key); markDirty(); render(); }
    catch (error) { status.textContent = error.message; }
  }
  // Icons saved by earlier betas were 120 px and looked soft on screen: redraw them at 240 px.
  async function upgradeIcons() {
    let changed = false;
    for (const binding of buttons) {
      const match = /^icon-([a-z0-9]+)(?:-hd\d*)?\.png$/.exec(binding.image || '');
      if (match && ICONS[match[1]]) {
        try { const next = await ensureIcon(match[1]); if (next !== binding.image) { binding.image = next; changed = true; } } catch (_) { /* keep the old image */ }
      }
    }
    if (changed) { markDirty(); render(); }
  }
  async function deleteArt(name) {
    if (!confirm(`Delete ${name}? Keys using it will show no image.`)) return;
    try {
      await SHARED().call('POST', {name}, '/api/admin/listening/art/delete');
      art = art.filter(item => item !== name); buttons.forEach(binding => { if (binding.image === name) delete binding.image; }); markDirty(); render();
    } catch (error) { status.textContent = error.message; }
  }

  function imagePicker(binding) {
    const file = h('input', {type: 'file', accept: 'image/*', hidden: true});
    file.onchange = () => pickFile(file.files[0], binding);
    const upload = h('button', {type: 'button', class: 'secondary'}, 'Upload image…'); upload.onclick = () => file.click();
    const clear = h('button', {type: 'button', class: 'cd-quiet'}, 'No image'); clear.onclick = () => { delete binding.image; markDirty(); render(); };
    const categories = window.DeckIconCategories || [];
    const icons = h('div', {class: 'dd-icons', role: 'group', 'aria-label': 'Built-in icons'});
    const fillIcons = () => icons.replaceChildren(...Object.entries(ICONS).filter(([, [, , category]]) => category === iconCategory).map(([key, [name, body]]) => {
      const choice = h('button', {type: 'button', title: name, 'aria-label': name, 'aria-pressed': binding.image === iconFile(key) ? 'true' : 'false'});
      choice.innerHTML = `<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true" ${ICON_STYLE}>${lineArt(body)}</svg>`;
      choice.onclick = () => useIcon(key, binding); return choice;
    }));
    const chips = h('div', {class: 'dd-chips', role: 'group', 'aria-label': 'Icon categories'}, categories.map(category => {
      const chip = h('button', {type: 'button', class: 'dd-chip', 'aria-pressed': String(iconCategory === category)}, category);
      // Switching groups only swaps the icon grid, like tabs: nothing else on the page is rebuilt.
      chip.onclick = () => { iconCategory = category; chips.querySelectorAll('.dd-chip').forEach(node => node.setAttribute('aria-pressed', String(node === chip))); fillIcons(); };
      return chip;
    }));
    fillIcons();
    const library = art.filter(name => !/^icon-/.test(name));
    const mine = library.length ? h('div', {class: 'dd-library', role: 'group', 'aria-label': 'Your images'}, library.map(name => {
      const thumb = h('button', {type: 'button', class: 'dd-thumb', title: name, 'aria-label': name, 'aria-pressed': binding.image === name ? 'true' : 'false'}, h('img', {src: artUrl(name), alt: ''}));
      thumb.onclick = () => { binding.image = name; markDirty(); render(); };
      const del = h('span', {class: 'dd-del', role: 'button', 'aria-label': `Delete ${name}`, title: 'Delete image'}, '×');
      del.onclick = event => { event.stopPropagation(); deleteArt(name); };
      thumb.append(del); return thumb;
    })) : h('p', {class: 'cd-muted'}, 'Images you upload appear here, ready to reuse.');
    return h('div', {class: 'dd-group'}, h('h4', {}, 'Image'), h('div', {class: 'cd-actions'}, upload, clear, file),
      h('p', {class: 'cd-muted'}, `Built-in icons (${Object.keys(ICONS).length})`), chips, icons, h('p', {class: 'cd-muted'}, 'Your images'), mine,
      h('small', {class: 'cd-muted'}, 'Uploads are cropped to a square and resized automatically (kept at 240 × 240 so they stay sharp; the key shows 120 × 120).'));
  }
  function colourPicker(binding, hint = '', key = 'color', title = 'Colour', palette = SWATCHES, unset = KEY_DEFAULT) {
    const custom = h('input', {type: 'color', value: binding[key] || unset, 'aria-label': 'Custom colour'});
    custom.oninput = () => { binding[key] = custom.value; markDirty(); drawStage(); };
    custom.onchange = () => render();
    const swatches = palette.map(colour => {
      const swatch = h('button', {type: 'button', class: 'dd-swatch', style: `background:${colour}`, title: colour, 'aria-label': `Colour ${colour}`, 'aria-pressed': (binding[key] || unset).toLowerCase() === colour ? 'true' : 'false'});
      swatch.onclick = () => { if (colour === unset) delete binding[key]; else binding[key] = colour; markDirty(); render(); }; return swatch;
    });
    return h('div', {class: 'dd-group'}, h('h4', {}, title), h('div', {class: 'dd-swatches'}, swatches, custom),
      hint ? h('small', {class: 'cd-muted'}, hint) : null);
  }

  const fill = (node, ...kids) => node.replaceChildren(...kids.filter(Boolean));
  function drawKeyInspector() {
    const binding = buttons[selection.index];
    const label = h('input', {type: 'text', maxlength: 40, placeholder: 'Shown on the key'}); label.value = binding.label || '';
    label.oninput = () => { binding.label = label.value; markDirty(); drawStage(); };
    const action = selectOf(available(KEY_ACTIONS, binding.action), binding.action || 'none');
    action.onchange = () => {
      const previous = binding.action;
      binding.action = action.value; delete binding.entity_id; delete binding.value;
      if (action.value === 'power') binding.value = true;
      if ((!binding.label || binding.label === DEFAULT_LABEL[previous]) && action.value in DEFAULT_LABEL) binding.label = DEFAULT_LABEL[action.value];
      if (!binding.image && DEFAULT_ICON[action.value] && ICONS[DEFAULT_ICON[action.value]]) useIcon(DEFAULT_ICON[action.value], binding);
      markDirty(); render();
    };
    const clear = h('button', {type: 'button', class: 'cd-quiet'}, 'Clear this key');
    clear.onclick = () => { buttons[selection.index] = blankKey(); markDirty(); render(); };
    const target = targetEditor(binding, () => { markDirty(); drawStage(); });
    fill(inspector, h('div', {class: 'dd-title'}, h('h3', {}, `Key ${selection.index + 1}`), clear),
      field('Label', label), field('When pressed', action), target, binding.action === 'playpause' ? playFields() : null,
      binding.action && binding.action !== 'none' ? alsoFields(binding) : null,
      colourPicker(binding),
      ['home_script', 'home_toggle', 'home_scene', 'home_level'].includes(binding.action) ? levelFields(binding) : null,
      ['home_toggle', 'home_level'].includes(binding.action) ? colourPicker(binding, 'Used instead of the normal colour while the key is on (a lit Home device or the current listening mode).', 'active_color', 'Colour when on') : null,
      imagePicker(binding));
  }
  function levelFields(binding) {
    const picker = entityPicker(binding, () => { if (!binding.level_entity) delete binding.level_entity; markDirty(); drawStage(); }, item => item.domain === 'light' || item.domain === 'fan', 'Show the brightness of', 'level_entity');
    return h('div', {class: 'dd-group'}, picker, binding.level_entity ? colourPicker(binding, 'The background warms towards this colour as the light gets brighter.', 'level_color', 'Glow colour', GLOW_SWATCHES, GLOW) : null, h('small', {class: 'cd-muted'}, 'The key shows a sun whose rays grow, and a background that warms and brightens, as this light does. It follows the real level, even if you change it elsewhere.'));
  }
  function toggleFields(press) {
    const text = (name, placeholder) => { const input = h('input', {type: 'text', placeholder, autocomplete: 'off', spellcheck: 'false'}); input.value = press[name] ?? ''; input.oninput = () => { press[name] = input.value.trim(); markDirty(); }; return input; };
    const offOnly = h('input', {type: 'checkbox'}); offOnly.checked = !!press.off_only; offOnly.onchange = () => { press.off_only = offOnly.checked; markDirty(); };
    const initial = h('input', {type: 'checkbox'}); initial.checked = !!press.initial_on; initial.onchange = () => { press.initial_on = initial.checked; markDirty(); };
    return h('div', {class: 'dd-group'}, h('h4', {}, 'On / off commands'),
      field('Remote entity', text('entity_id', 'remote.wi_fi_universal_remote')), field('Device name', text('device', 'aircon')),
      h('div', {class: 'cd-grid two'}, field('Command to switch on', text('command_on', 'power_on')), field('Command to switch off', text('command_off', 'power_off'))),
      h('label', {class: 'dd-check'}, offOnly, h('span', {}, 'Always send the off command (turning the dial already switches it on)')),
      h('label', {class: 'dd-check'}, initial, h('span', {}, 'Assume it is on when the Pi starts (toggle mode)')),
      h('small', {class: 'cd-muted'}, 'With the first option off, each press sends the opposite command to the last one. A temperature step counts as switching it on.'));
  }
  function remoteFields(dial) {
    const text = (name, placeholder) => { const input = h('input', {type: 'text', placeholder, autocomplete: 'off', spellcheck: 'false'}); input.value = dial[name] ?? ''; input.oninput = () => { dial[name] = input.value.trim(); markDirty(); drawStage(); }; return input; };
    const number = name => { const input = h('input', {type: 'number', min: -50, max: 200}); input.value = dial[name] ?? ''; input.oninput = () => { dial[name] = input.value === '' ? undefined : Number(input.value); markDirty(); drawStage(); }; return input; };
    return h('div', {class: 'dd-group'}, h('h4', {}, 'Remote steps'),
      field('Remote entity', text('entity_id', 'remote.wi_fi_universal_remote')),
      field('Device name (as taught in Home Assistant)', text('device', 'aircon')),
      field('Command pattern ({n} becomes the value)', text('command', 'cool_{n}')),
      h('div', {class: 'cd-grid two'}, field('Lowest', number('min')), field('Highest', number('max'))),
      h('div', {class: 'cd-grid two'}, field('Starting value (shown until you turn it)', number('start')), field('Unit shown', text('unit', '°'))),
      h('small', {class: 'cd-muted'}, 'Each click sends the learned command for the next value, for example cool_24. The deck cannot read the aircon back, so it shows the last value it sent.'));
  }
  function drawDialInspector() {
    const dial = dials[selection.index], press = dial.press;
    const label = h('input', {type: 'text', maxlength: 40, placeholder: 'Shown on the strip'}); label.value = dial.label || '';
    label.oninput = () => { dial.label = label.value; markDirty(); drawStage(); };
    const turn = selectOf(available(DIAL_ACTIONS, dial.action), dial.action || 'none');
    turn.onchange = () => { dial.action = turn.value; if (turn.value === 'volume_delta' && !dial.label) dial.label = 'KEF volume'; if (turn.value === 'roon_volume' && !dial.label) dial.label = 'Roon volume';
      if (turn.value === 'remote_steps') Object.assign(dial, {entity_id: dial.entity_id?.startsWith('remote.') ? dial.entity_id : 'remote.wi_fi_universal_remote', device: dial.device || 'aircon', command: dial.command || 'cool_{n}', min: dial.min ?? 16, max: dial.max ?? 30, start: dial.start ?? 24, unit: dial.unit ?? '°', label: dial.label || 'Aircon'}); markDirty(); render(); };
    const step = h('input', {type: 'range', min: 1, max: 10, step: 1, value: dial.step ?? 1}); const stepValue = h('output', {}, String(dial.step ?? 1));
    step.oninput = () => { dial.step = Number(step.value); stepValue.textContent = step.value; markDirty(); };
    const tap = selectOf(available(PRESS_ACTIONS, press.action), press.action || 'none');
    tap.onchange = () => { press.action = tap.value; delete press.entity_id; if (tap.value === 'remote_toggle') Object.assign(press, {entity_id: dial.entity_id?.startsWith('remote.') ? dial.entity_id : 'remote.wi_fi_universal_remote', device: dial.device || 'aircon', command_on: 'power_on', command_off: 'power_off', initial_on: false, off_only: true}); markDirty(); render(); };
    const clear = h('button', {type: 'button', class: 'cd-quiet'}, 'Clear this dial');
    clear.onclick = () => { dials[selection.index] = blankDial(); markDirty(); render(); };
    fill(inspector, h('div', {class: 'dd-title'}, h('h3', {}, `Dial ${selection.index + 1}`), clear),
      field('Label', label), field('When turned', turn),
      dial.action === 'home_level' ? entityPicker(dial, () => { markDirty(); drawStage(); }, item => item.supports_level, 'Light or fan') : null,
      dial.action === 'home_script_dial' ? entityPicker(dial, () => { markDirty(); drawStage(); }, item => item.domain === 'script', 'Script when turned up (clockwise)') : null,
      dial.action === 'home_script_dial' ? entityPicker(dial, () => { markDirty(); drawStage(); }, item => item.domain === 'script', 'Script when turned down', 'entity_id_ccw') : null,
      dial.action === 'remote_steps' ? remoteFields(dial) : null,
      dial.action !== 'none' && dial.action !== 'home_script_dial' ? h('label', {class: 'cd-field'}, h('span', {}, 'Step per click'), h('div', {class: 'dd-range'}, step, stepValue)) : null,
      field('When pressed or tapped on the strip', tap),
      press.action === 'home_toggle' ? entityPicker(press, markDirty, item => item.domain !== 'scene' && item.domain !== 'script', 'Device to toggle') : null,
      press.action === 'home_script' ? entityPicker(press, markDirty, item => item.domain === 'script', 'Script to run') : null,
      press.action === 'remote_toggle' ? toggleFields(press) : null,
      colourPicker(dial, 'The colour behind this dial\'s section of the touch strip.'),
      colourPicker(dial, 'The colour of the label and the percentage on the strip.', 'text_color', 'Text colour', TEXT_SWATCHES, '#ffffff'));
  }

  function render() {
    const x = window.scrollX, y = window.scrollY, top = inspector.scrollTop;
    drawStage();
    if (selection.type === 'dial') drawDialInspector(); else drawKeyInspector();
    inspector.scrollTop = top; window.scrollTo(x, y);
  }

  let onPlay = {};
  function alsoFields(binding) {
    const also = binding.also || (binding.also = {action: 'none'});
    const choice = selectOf([['none', 'Nothing'], ['pause', 'Pause Roon'], ['play', 'Play Roon'], ['home_script', 'Run a Home script']], also.action || 'none');
    choice.onchange = () => { also.action = choice.value; if (choice.value !== 'home_script') delete also.entity_id; markDirty(); render(); };
    return h('div', {class: 'dd-group'}, field('Also do this when pressed', choice, 'For example pause Roon when you switch to the Mac.'),
      also.action === 'home_script' ? entityPicker(also, markDirty, item => item.domain === 'script', 'Script to run') : null);
  }
  const deckBrightness = h('input', {type: 'range', min: 10, max: 100, step: 5, 'aria-label': 'Stream Deck brightness'});
  const deckBrightnessValue = h('output', {}, '');
  const brightnessRow = h('label', {class: 'dd-brightness', hidden: true}, h('span', {}, 'Brightness'), deckBrightness, deckBrightnessValue);
  let brightnessTimer = null;
  deckBrightness.oninput = () => {
    deckBrightnessValue.textContent = `${deckBrightness.value}%`; markDirty();
    clearTimeout(brightnessTimer);   // the deck follows the slider as you drag, before anything is saved
    brightnessTimer = setTimeout(() => SHARED().call('POST', {action: 'deck_brightness', value: Number(deckBrightness.value)}, '/api/listening/command').catch(() => {}), 120);
  };
  const wake = {};
  const deckSleepMode = settings => settings.streamdeck_sleep_mode || (settings.streamdeck_sleep_with_display === false ? 'schedule' : 'match');
  function syncWakeFields() { if (wake.times) wake.times.hidden = sleepBox.value !== 'schedule'; }
  function syncWake() {
    const settings = SHARED().settings;
    sleepBox.value = deckSleepMode(settings);
    syncWakeFields();
    wake.start.value = settings.streamdeck_sleep_start || ''; wake.end.value = settings.streamdeck_sleep_end || '';
    wake.awake.value = settings.streamdeck_awake_seconds ?? 30;
    deckBrightness.value = settings.streamdeck_brightness ?? 70; deckBrightnessValue.textContent = `${deckBrightness.value}%`;
  }
  function wakeCard() {
    wake.start = h('input', {type: 'time'}); wake.end = h('input', {type: 'time'});
    wake.awake = h('input', {type: 'number', min: 5, max: 3600, step: 5});
    for (const input of [wake.start, wake.end, wake.awake]) input.oninput = () => markDirty();
    const art = h('div', {class: 'dd-wake-art', 'aria-hidden': 'true'}); art.innerHTML = '<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"><path d="M78 24a38 38 0 1 0 22 62A32 32 0 0 1 78 24z"/><circle cx="92" cy="30" r="1.6" fill="currentColor"/><path d="M26 30v6M23 33h6"/></svg>';
    const text = h('div', {class: 'dd-wake-text'}, h('h3', {}, 'Wake & sleep'),
      h('p', {class: 'cd-muted'}, 'Match RoonDeck to sleep and wake exactly when the touchscreen does, including its idle timeout, or set your own times. While the deck sleeps its backlight is off; touch any key or dial to wake it, and the first touch only wakes it.'),
      h('label', {class: 'cd-field'}, h('span', {}, 'Sleep and wake'), sleepBox),
      wake.times = h('div', {class: 'cd-grid two'}, field('Sleep the deck from', wake.start), field('Wake it again at', wake.end)),
      h('div', {class: 'cd-grid two'}, field('Stay fully awake after a touch (seconds)', wake.awake)));
    const card = h('div', {class: 'dd-wake'}, text, art);
    syncWake();
    return card;
  }
  function playFields() {
    const mark = () => markDirty();
    const picker = entityPicker(onPlay, mark, item => item.entity_id.startsWith('script.'), 'Run this script', 'script');
    const helper = h('input', {type: 'text', placeholder: 'input_select.topping_input', autocomplete: 'off', spellcheck: 'false'}); helper.value = onPlay.helper || '';
    helper.oninput = () => { onPlay.helper = helper.value.trim(); mark(); };
    const value = h('input', {type: 'text', placeholder: 'Optical', autocomplete: 'off'}); value.value = onPlay.value || '';
    value.oninput = () => { onPlay.value = value.value.trim(); mark(); };
    return h('div', {class: 'dd-group'}, h('h4', {}, 'When Roon starts playing'),
      h('p', {class: 'cd-muted'}, 'Run a Home script as soon as playback starts, for example to switch the DAC to its optical input. Add the input helper and its wanted value to skip the script when the input is already right.'),
      withLink(picker, 'script'), field('Input helper (optional)', helper), field('Skip when the helper already equals', value));
  }
  function build() {
    enableBox = h('input', {type: 'checkbox'}); enableBox.checked = !!SHARED().settings.streamdeck_enabled;
    enableBox.onchange = () => markDirty();
    sleepBox = h('select', {'aria-label': 'Stream Deck sleep'}, h('option', {value: 'match'}, 'Match RoonDeck (sleeps and wakes with the screen)'), h('option', {value: 'schedule'}, 'My own schedule'));
    sleepBox.value = deckSleepMode(SHARED().settings);
    sleepBox.onchange = () => { syncWakeFields(); markDirty(); };
    revertButton = h('button', {type: 'button', class: 'secondary'}, 'Discard changes');
    // Saved by the page-wide "Save changes" button, not a button of its own.
    window.RoonDeckSaves = window.RoonDeckSaves || {};
    window.RoonDeckSaves.streamdeck = async () => {
      status.textContent = 'Saving…';
      try {
        const settings = SHARED().settings;
        const invalid = buttons.findIndex(item => item.action === 'power' && typeof item.value !== 'boolean');
        if (invalid >= 0) throw new Error(`Key ${invalid + 1}: choose Power on or Standby`);
        const missing = buttons.findIndex(item => (item.action === 'home_toggle' || item.action === 'home_scene' || item.action === 'home_script') && !item.entity_id);
        if (missing >= 0) throw new Error(`Key ${missing + 1}: choose a Home device`);
        settings.streamdeck_enabled = enableBox.checked;
        settings.streamdeck_sleep_mode = sleepBox.value; settings.streamdeck_sleep_with_display = sleepBox.value === 'match';
        settings.streamdeck_sleep_start = wake.start.value; settings.streamdeck_sleep_end = wake.end.value;
        settings.streamdeck_awake_seconds = Math.max(5, Math.min(3600, Math.round(Number(wake.awake.value) || 30)));
        settings.streamdeck_brightness = Number(deckBrightness.value);
        settings.on_play = Object.fromEntries(Object.entries(onPlay).filter(([, value]) => value));
        settings.buttons = buttons.map(item => { const out = {...item}; if (!out.label) delete out.label; if (!out.image) delete out.image; if (!out.color) delete out.color; if (!out.active_color) delete out.active_color; if (!out.level_entity) { delete out.level_entity; delete out.level_color; } else if (!out.level_color || out.level_color.toLowerCase() === GLOW) delete out.level_color; if (!out.also || out.also.action === 'none') delete out.also; return out; });
        settings.dials = dials.map(item => ({label: item.label || '', action: item.action, entity_id: item.entity_id || '', ...(item.action === 'home_script_dial' ? {entity_id_ccw: item.entity_id_ccw || ''} : {}), step: item.step || 1, ...(item.action === 'remote_steps' ? {device: item.device || '', command: item.command || '', min: item.min, max: item.max, start: item.start, unit: item.unit || ''} : {}), ...(item.color ? {color: item.color} : {}), ...(item.text_color ? {text_color: item.text_color} : {}),
          press: {action: item.press.action, ...(['home_toggle', 'home_script'].includes(item.press.action) ? {entity_id: item.press.entity_id || ''} : {}), ...(item.press.action === 'remote_toggle' ? {entity_id: item.press.entity_id || '', device: item.press.device || '', command_on: item.press.command_on || '', command_off: item.press.command_off || '', initial_on: !!item.press.initial_on, off_only: !!item.press.off_only} : {})}}));
        await SHARED().save();
        dirty = false; notice.hidden = true; status.textContent = 'Stream Deck saved. It updates on the device within a few seconds.';
      } catch (error) { status.textContent = error.message; throw error; }
    };
    revertButton.onclick = () => { window.RoonDeckClean?.('streamdeck'); adopt(); notice.hidden = true; status.textContent = ''; enableBox.checked = !!SHARED().settings.streamdeck_enabled; syncWake(); render(); };
    supportNote = h('span', {class: 'cd-muted', role: 'status'});
    supportButton = h('button', {type: 'button', class: 'secondary'}, 'Install Stream Deck support');
    supportButton.onclick = installSupport;
    supportRow = h('div', {class: 'cd-actions', hidden: true}, supportButton, supportNote);
    const head = h('div', {class: 'cd-card'},
      h('div', {class: 'cd-card-head'}, h('h3', {}, 'Stream Deck +'), h('div', {class: 'dd-head-actions'}, notice, revertButton, h('label', {class: 'cd-switch'}, enableBox, h('span', {}, 'Enabled')))),
      brightnessRow,
      h('p', {class: 'cd-muted'}, 'Design what each key, dial and the touch strip does and shows. The Pi installs the USB support it needs the first time you enable the deck.'), connection, supportRow);
    const layout = h('div', {class: 'dd-layout'}, inspector, stage); layout.classList.add('dd-pane');
    const wakePane = wakeCard(); wakePane.hidden = true; wakePane.classList.add('dd-pane');
    const panes = {design: layout, wake: wakePane};
    const tabButtons = [['design', 'Designer'], ['wake', 'Wake & sleep']].map(([id, name]) => {
      const button = h('button', {type: 'button', role: 'tab', 'aria-selected': id === 'design' ? 'true' : 'false'}, name);
      button.onclick = () => { for (const key of Object.keys(panes)) panes[key].hidden = key !== id; for (const item of tabButtons) item.setAttribute('aria-selected', String(item === button)); };
      return button;
    });
    const tabs = h('nav', {class: 'dd-tabs', role: 'tablist', 'aria-label': 'Stream Deck sections'}, tabButtons);
    const card = h('div', {class: 'cd-card dd-card'}, tabs, h('div', {class: 'dd-body'}, layout, wakePane));
    root.replaceChildren(head, card, status);
    built = true;
  }

  async function installSupport() {
    supportButton.disabled = true; supportNote.textContent = 'Installing… this takes a minute or two.';
    try {
      await SHARED().call('POST', {action: 'install_streamdeck'}, '/api/admin/system-action');
      const started = Date.now();
      while (Date.now() - started < 300000) {
        await new Promise(resolve => setTimeout(resolve, 3000));
        const response = await fetch('/api/admin/system', {cache: 'no-store'}); if (!response.ok) continue;
        const text = (await response.json()).streamdeck_install_status || '';
        if (text.startsWith('Stream Deck support installed') || text.startsWith('Installation failed')) { supportNote.textContent = text; break; }
      }
    } catch (error) { supportNote.textContent = error.message; }
    finally { supportButton.disabled = false; }
  }
  async function status_() {
    try {
      const response = await fetch('/api/listening/status', {cache: 'no-store'}); if (!response.ok) return;
      const state = await response.json(), deck = state.streamdeck || {};
      connection.textContent = `Device: ${deck.connected ? 'Connected' : deck.enabled ? deck.error || 'Waiting for the Stream Deck' : 'Disabled'}`;
      const missing = !!deck.enabled && /install the optional/i.test(deck.error || '');
      supportRow.hidden = !missing;
      brightnessRow.hidden = !deck.connected;   // only offered while a deck is plugged in
      if (missing && !installTried) { installTried = true; installSupport(); }   // enabling the deck sets it up once, no SSH needed
    } catch (_) { connection.textContent = 'Controls service unavailable'; }
  }
  async function loadLibrary() {
    try { art = (await SHARED().call('GET', undefined, '/api/admin/listening/art')).art || []; } catch (_) { art = []; }
    try { const response = await fetch('/api/home/status', {cache: 'no-store'}); if (response.ok) { const body = await response.json(); entities = [...(body.entities || []), ...(body.deck_entities || [])]; } } catch (_) { entities = []; }
    try { const response = await fetch('/api/admin/config', {cache: 'no-store'}); if (response.ok) haUrl = String((await response.json()).home_assistant_url || ''); } catch (_) { haUrl = ''; }
    try { const response = await fetch('/api/admin/home-catalog', {cache: 'no-store'}); if (response.ok) catalog = (await response.json()).entities || []; } catch (_) { catalog = []; }
  }
  async function start() {
    if (built && dirty) return;   // never overwrite unsaved edits when the shared settings reload
    await loadLibrary(); adopt(); upgradeIcons();
    if (!built) { build(); status_(); setInterval(status_, 5000); }
    enableBox.checked = !!SHARED().settings.streamdeck_enabled;
    syncWake();
    render();
  }
  const wait = setInterval(() => { if (window.RoonDeckListening) { clearInterval(wait); window.RoonDeckListening.onChange(start); if (window.RoonDeckListening.settings) start(); } }, 100);
})();
