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
    ['none', 'Unused'], ['mode', 'Listening mode'], ['power', 'KEF power'], ['input', 'KEF input'], ['mute', 'KEF mute'],
    ['previous', 'Previous track'], ['playpause', 'Play / pause'], ['next', 'Next track'], ['home_toggle', 'Home device on / off'], ['home_scene', 'Home scene'],
  ];
  const DIAL_ACTIONS = [['none', 'Unused'], ['volume_delta', 'KEF volume'], ['home_level', 'Home brightness / fan speed']];
  const PRESS_ACTIONS = [['none', 'Unused'], ['mute', 'KEF mute'], ['playpause', 'Play / pause'], ['home_toggle', 'Toggle a Home device']];
  const SOURCES = [['aux', 'Aux'], ['optical', 'Optical'], ['wifi', 'Wi‑Fi'], ['bluetooth', 'Bluetooth']];
  const DEFAULT_LABEL = {mode: '', power: '', input: '', mute: 'Mute', previous: 'Previous', playpause: 'Play / Pause', next: 'Next', home_toggle: '', home_scene: ''};
  const DEFAULT_ICON = {mute: 'mute', previous: 'previous', playpause: 'playpause', next: 'next', power: 'power', input: 'input', home_toggle: 'bulb', home_scene: 'scene', mode: 'speaker'};
  const ICONS = window.DeckIcons || {};
  const ICON_STYLE = 'stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"';
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

  let buttons = [], dials = [], art = [], entities = [], selection = {type: 'key', index: 0}, dirty = false, built = false, dragFrom = null;
  const status = h('p', {role: 'status', class: 'cd-message'});
  const notice = h('span', {class: 'dd-dirty', hidden: true}, 'Unsaved changes');
  const connection = h('span', {class: 'cd-muted'});
  const stage = h('div', {class: 'dd-stage'});
  const inspector = h('div', {class: 'dd-inspector'});
  let enableBox, saveButton, revertButton;

  const blankKey = () => ({label: '', action: 'none'});
  const blankDial = () => ({label: '', action: 'none', step: 1, press: {action: 'none'}});
  const clone = value => JSON.parse(JSON.stringify(value));
  const defaultButtons = [
    {label: 'Pi / Roon', action: 'mode', value: 'pi'}, {label: 'Mac', action: 'mode', value: 'mac'},
    {label: 'Power on', action: 'power', value: true}, {label: 'Standby', action: 'power', value: false},
    {label: 'Previous', action: 'previous'}, {label: 'Play / Pause', action: 'playpause'}, {label: 'Next', action: 'next'}, {label: 'Mute', action: 'mute'}];

  function adopt() {
    const settings = SHARED().settings;
    const saved = settings.buttons?.length ? settings.buttons : defaultButtons;
    buttons = Array.from({length: 8}, (_, i) => clone(saved[i] || blankKey()));
    const savedDials = settings.dials?.length ? settings.dials : [{label: 'KEF volume', action: 'volume_delta', step: 1, press: {action: 'mute'}}];
    dials = Array.from({length: 4}, (_, i) => ({...blankDial(), ...clone(savedDials[i] || {})}));
    dials.forEach(dial => { dial.press = dial.press || {action: 'none'}; });
    dirty = false;
  }
  const markDirty = () => { dirty = true; notice.hidden = false; };
  const entityName = id => entities.find(item => item.entity_id === id)?.name || id || '';
  const artUrl = name => `/api/admin/listening/art/${encodeURIComponent(name)}`;

  function describe(binding) {
    const modes = SHARED().settings.modes || [];
    switch (binding.action) {
      case 'mode': return modes.find(mode => mode.id === binding.value)?.name || 'Listening mode';
      case 'power': return binding.value === false ? 'Standby' : 'Power on';
      case 'input': return `Input · ${binding.value || '—'}`;
      case 'home_toggle': case 'home_scene': return entityName(binding.entity_id) || 'Choose a device';
      default: return (KEY_ACTIONS.find(([id]) => id === binding.action) || [])[1] || '';
    }
  }

  /* ------------------------------------------------------------ device preview */
  function keyTile(index) {
    const binding = buttons[index];
    const tile = h('button', {type: 'button', class: 'dd-key', draggable: 'true', 'aria-label': `Key ${index + 1}: ${binding.label || describe(binding) || 'unused'}`,
      'aria-pressed': selection.type === 'key' && selection.index === index ? 'true' : 'false', style: `background:${binding.color || KEY_DEFAULT}`});
    if (binding.image) tile.append(h('img', {src: artUrl(binding.image), alt: '', draggable: 'false'}));
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
    const detail = dial.action === 'volume_delta' ? '20%' : dial.action === 'home_level' ? (dial.entity_id ? '60%' : 'Choose device') : '';
    const node = h('button', {type: 'button', class: 'dd-segment', 'aria-label': `Strip ${index + 1}: ${dial.label || 'unused'}`, 'aria-pressed': selection.type === 'dial' && selection.index === index ? 'true' : 'false'},
      h('strong', {}, dial.label || (dial.action === 'none' ? '' : 'Dial')), h('span', {}, detail));
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
      case 'mode': {
        const modes = (settings.modes || []).map(mode => [mode.id, mode.name || mode.id]);
        if (!modes.length) return h('p', {class: 'cd-muted'}, 'Add a listening mode in the Listening & KEF tab first.');
        const select = selectOf(modes, binding.value); binding.value = select.value;
        select.onchange = () => { binding.value = select.value; change(); };
        return field('Mode', select);
      }
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
      case 'home_toggle': case 'home_scene': return entityPicker(binding, change, binding.action === 'home_scene' ? item => item.domain === 'scene' : item => item.domain !== 'scene', binding.action === 'home_scene' ? 'Scene' : 'Home device');
      default: return null;
    }
  }
  function entityPicker(binding, onChange, filter = () => true, labelText = 'Home device') {
    const list = entities.filter(filter);
    if (!list.length) {
      const input = h('input', {type: 'text', placeholder: 'light.living_room', autocomplete: 'off', spellcheck: 'false'}); input.value = binding.entity_id || '';
      input.oninput = () => { binding.entity_id = input.value.trim(); onChange(); };
      return field(labelText, input, 'No Home devices are shared with RoonDeck yet, so enter the Home Assistant entity ID.');
    }
    const select = selectOf([['', 'Choose…'], ...list.map(item => [item.entity_id, item.name])], binding.entity_id || '');
    select.onchange = () => { binding.entity_id = select.value; onChange(); };
    return field(labelText, select);
  }

  // Square-crop and shrink to a 120×120 PNG in the browser, so only small safe images reach the Pi.
  async function toPng(source, size = 120) {
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
  async function useIcon(key, binding) {
    const name = `icon-${key}.png`;
    try {
      if (!art.includes(name)) {
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120"><g transform="translate(30,12) scale(2.5)" ${ICON_STYLE}>${ICONS[key][1]}</g></svg>`;
        const url = URL.createObjectURL(new Blob([svg], {type: 'image/svg+xml'}));
        const image = await new Promise((resolve, reject) => { const node = new Image(); node.onload = () => resolve(node); node.onerror = () => reject(new Error('Could not draw that icon')); node.src = url; });
        const blob = await toPng(image); URL.revokeObjectURL(url);
        await upload(name, blob);
      }
      binding.image = name; markDirty(); render();
    } catch (error) { status.textContent = error.message; }
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
      const choice = h('button', {type: 'button', title: name, 'aria-label': name, 'aria-pressed': binding.image === `icon-${key}.png` ? 'true' : 'false'});
      choice.innerHTML = `<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true" ${ICON_STYLE}>${body}</svg>`;
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
      h('small', {class: 'cd-muted'}, 'Uploads are cropped to a square and shrunk to 120 × 120 automatically.'));
  }
  function colourPicker(binding) {
    const custom = h('input', {type: 'color', value: binding.color || KEY_DEFAULT, 'aria-label': 'Custom colour'});
    custom.oninput = () => { binding.color = custom.value; markDirty(); drawStage(); };
    custom.onchange = () => render();
    const swatches = SWATCHES.map(colour => {
      const swatch = h('button', {type: 'button', class: 'dd-swatch', style: `background:${colour}`, title: colour, 'aria-label': `Colour ${colour}`, 'aria-pressed': (binding.color || KEY_DEFAULT).toLowerCase() === colour ? 'true' : 'false'});
      swatch.onclick = () => { if (colour === KEY_DEFAULT) delete binding.color; else binding.color = colour; markDirty(); render(); }; return swatch;
    });
    return h('div', {class: 'dd-group'}, h('h4', {}, 'Colour'), h('div', {class: 'dd-swatches'}, swatches, custom),
      h('small', {class: 'cd-muted'}, 'Keys that are switched on (the current listening mode or a Home device that is on) get a green outline.'));
  }

  const fill = (node, ...kids) => node.replaceChildren(...kids.filter(Boolean));
  function drawKeyInspector() {
    const binding = buttons[selection.index];
    const label = h('input', {type: 'text', maxlength: 40, placeholder: 'Shown on the key'}); label.value = binding.label || '';
    label.oninput = () => { binding.label = label.value; markDirty(); drawStage(); };
    const action = selectOf(KEY_ACTIONS, binding.action || 'none');
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
      field('Label', label), field('When pressed', action), target, colourPicker(binding), imagePicker(binding));
  }
  function drawDialInspector() {
    const dial = dials[selection.index], press = dial.press;
    const label = h('input', {type: 'text', maxlength: 40, placeholder: 'Shown on the strip'}); label.value = dial.label || '';
    label.oninput = () => { dial.label = label.value; markDirty(); drawStage(); };
    const turn = selectOf(DIAL_ACTIONS, dial.action || 'none');
    turn.onchange = () => { dial.action = turn.value; if (turn.value === 'volume_delta' && !dial.label) dial.label = 'KEF volume'; markDirty(); render(); };
    const step = h('input', {type: 'range', min: 1, max: 10, step: 1, value: dial.step ?? 1}); const stepValue = h('output', {}, String(dial.step ?? 1));
    step.oninput = () => { dial.step = Number(step.value); stepValue.textContent = step.value; markDirty(); };
    const tap = selectOf(PRESS_ACTIONS, press.action || 'none');
    tap.onchange = () => { press.action = tap.value; delete press.entity_id; markDirty(); render(); };
    const clear = h('button', {type: 'button', class: 'cd-quiet'}, 'Clear this dial');
    clear.onclick = () => { dials[selection.index] = blankDial(); markDirty(); render(); };
    fill(inspector, h('div', {class: 'dd-title'}, h('h3', {}, `Dial ${selection.index + 1}`), clear),
      field('Label', label), field('When turned', turn),
      dial.action === 'home_level' ? entityPicker(dial, () => { markDirty(); drawStage(); }, item => item.supports_level, 'Light or fan') : null,
      dial.action !== 'none' ? h('label', {class: 'cd-field'}, h('span', {}, 'Step per click'), h('div', {class: 'dd-range'}, step, stepValue)) : null,
      field('When pressed or tapped on the strip', tap),
      press.action === 'home_toggle' ? entityPicker(press, markDirty, item => item.domain !== 'scene', 'Device to toggle') : null);
  }

  function render() {
    const x = window.scrollX, y = window.scrollY, top = inspector.scrollTop;
    drawStage();
    if (selection.type === 'dial') drawDialInspector(); else drawKeyInspector();
    saveButton.disabled = false;
    inspector.scrollTop = top; window.scrollTo(x, y);
  }

  function build() {
    enableBox = h('input', {type: 'checkbox'}); enableBox.checked = !!SHARED().settings.streamdeck_enabled;
    enableBox.onchange = () => markDirty();
    saveButton = h('button', {type: 'button'}, 'Save Stream Deck');
    revertButton = h('button', {type: 'button', class: 'secondary'}, 'Discard changes');
    saveButton.onclick = async () => {
      saveButton.disabled = true; status.textContent = 'Saving…';
      try {
        const settings = SHARED().settings;
        const invalid = buttons.findIndex(item => item.action === 'power' && typeof item.value !== 'boolean');
        if (invalid >= 0) throw new Error(`Key ${invalid + 1}: choose Power on or Standby`);
        const missing = buttons.findIndex(item => (item.action === 'home_toggle' || item.action === 'home_scene') && !item.entity_id);
        if (missing >= 0) throw new Error(`Key ${missing + 1}: choose a Home device`);
        settings.streamdeck_enabled = enableBox.checked;
        settings.buttons = buttons.map(item => { const out = {...item}; if (!out.label) delete out.label; if (!out.image) delete out.image; if (!out.color) delete out.color; return out; });
        settings.dials = dials.map(item => ({label: item.label || '', action: item.action, entity_id: item.entity_id || '', step: item.step || 1,
          press: {action: item.press.action, ...(item.press.action === 'home_toggle' ? {entity_id: item.press.entity_id || ''} : {})}}));
        await SHARED().save();
        dirty = false; notice.hidden = true; status.textContent = 'Stream Deck saved. It updates on the device within a few seconds.';
      } catch (error) { status.textContent = error.message; }
      finally { saveButton.disabled = false; }
    };
    revertButton.onclick = () => { adopt(); notice.hidden = true; status.textContent = ''; enableBox.checked = !!SHARED().settings.streamdeck_enabled; render(); };
    const head = h('div', {class: 'cd-card'},
      h('div', {class: 'cd-card-head'}, h('h3', {}, 'Stream Deck +'), h('label', {class: 'cd-switch'}, enableBox, h('span', {}, 'Enabled'))),
      h('p', {class: 'cd-muted'}, 'Design what each key, dial and the touch strip does and shows. USB support needs the optional Stream Deck packages and device permissions on the Pi.'), connection);
    const layout = h('div', {class: 'dd-layout'}, stage, inspector);
    root.replaceChildren(head, layout, h('div', {class: 'cd-actions dd-bar'}, saveButton, revertButton, notice), status);
    built = true;
  }

  async function status_() {
    try {
      const response = await fetch('/api/listening/status', {cache: 'no-store'}); if (!response.ok) return;
      const state = await response.json(), deck = state.streamdeck || {};
      connection.textContent = `Device: ${deck.connected ? 'Connected' : deck.enabled ? deck.error || 'Waiting for the Stream Deck' : 'Disabled'}`;
    } catch (_) { connection.textContent = 'Controls service unavailable'; }
  }
  async function loadLibrary() {
    try { art = (await SHARED().call('GET', undefined, '/api/admin/listening/art')).art || []; } catch (_) { art = []; }
    try { const response = await fetch('/api/home/status', {cache: 'no-store'}); if (response.ok) entities = (await response.json()).entities || []; } catch (_) { entities = []; }
  }
  async function start() {
    if (built && dirty) return;   // never overwrite unsaved edits when the shared settings reload
    await loadLibrary(); adopt();
    if (!built) { build(); status_(); setInterval(status_, 5000); }
    enableBox.checked = !!SHARED().settings.streamdeck_enabled;
    render();
  }
  const wait = setInterval(() => { if (window.RoonDeckListening) { clearInterval(wait); window.RoonDeckListening.onChange(start); if (window.RoonDeckListening.settings) start(); } }, 100);
})();
