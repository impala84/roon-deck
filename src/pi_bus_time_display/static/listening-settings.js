/* Listening controls: KEF speakers and listening modes. The Stream Deck designer (deck-designer.js) shares the same settings. */
(() => {
  const root = document.getElementById('listening-settings');
  if (!root) return;
  const SOURCES = [['aux', 'Aux'], ['optical', 'Optical'], ['wifi', 'Wi‑Fi'], ['bluetooth', 'Bluetooth']];
  const TOPPING = [['', 'Keep unchanged (KEF controls only)'], ['usb', 'Mac USB'], ['coaxial', 'Pi coaxial'], ['optical', 'Pi optical'], ['bluetooth', 'Bluetooth']];
  const DEFAULT_MODES = [{id: 'pi', name: 'Roon / LSX', kef_input: 'wifi', topping_input: null, volume: 20}, {id: 'mac', name: 'Mac', kef_input: 'aux', topping_input: 'usb', volume: 20}];
  const listeners = [];
  const api = window.RoonDeckListening = {
    settings: null,
    collectors: [],
    onChange(callback) { listeners.push(callback); },
    notify() { listeners.forEach(callback => callback()); },
    async call(method, body, path = '/api/admin/listening') {
      const response = await fetch(path, {method, headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
      if (response.status === 401) { location.href = '/login.html'; throw new Error('Sign in to continue'); }
      const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Could not save controls');
      return result;
    },
    async save() {
      api.collectors.forEach(collect => collect());
      const result = await api.call('POST', api.settings);
      api.settings = {...api.settings, ...(result.settings || {})};
      return result;
    },
  };

  const h = (tag, props = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (key === 'class') node.className = value; else if (key.startsWith('on')) node[key] = value;
      else if (value !== undefined && value !== null && value !== false) node.setAttribute(key, value === true ? '' : value);
    }
    node.append(...children.flat().filter(child => child !== null && child !== undefined && child !== false));
    return node;
  };
  const labelled = (text, control, hint) => h('label', {class: 'cd-field'}, h('span', {}, text), control, hint ? h('small', {}, hint) : null);
  const selectOf = (options, value) => { const select = h('select'); for (const [id, name] of options) select.add(new Option(name, id)); select.value = value; return select; };
  const slug = (text, taken) => {
    let base = (text || 'mode').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 30) || 'mode', id = base, n = 2;
    while (taken.has(id)) id = `${base}-${n++}`;
    return id;
  };

  async function load() {
    try {
      api.settings = await api.call('GET');
    } catch (error) { root.replaceChildren(h('p', {role: 'status'}, error.message)); return; }
    const settings = api.settings;
    if (!settings.modes?.length) settings.modes = DEFAULT_MODES.map(mode => ({...mode}));
    const message = h('p', {role: 'status', class: 'cd-message'});
    const connection = h('p', {role: 'status', class: 'cd-muted'});

    const enabled = h('input', {type: 'checkbox'}); enabled.checked = !!settings.enabled;
    const host = h('input', {type: 'text', placeholder: '10.12.0.125', autocomplete: 'off', inputmode: 'decimal'}); host.value = settings.kef_host || '';
    const roonOutput = selectOf([['', 'Direct KEF connection only']], settings.kef_roon_output_id || '');
    try {
      const data = await api.call('GET', undefined, '/roon/api/accessory/outputs');
      for (const output of data.outputs || []) roonOutput.add(new Option(`${output.name} (${output.zone})`, output.id));
      if (settings.kef_roon_output_id && ![...roonOutput.options].some(option => option.value === settings.kef_roon_output_id)) {
        roonOutput.add(new Option('Saved output (currently unavailable)', settings.kef_roon_output_id));
      }
      roonOutput.value = settings.kef_roon_output_id || '';
    } catch (_) { if (settings.kef_roon_output_id) roonOutput.add(new Option('Saved output', settings.kef_roon_output_id)); roonOutput.value = settings.kef_roon_output_id || ''; }
    const irRemote = h('input', {type:'text', placeholder:'remote.study'}); irRemote.value = settings.kef_ir_remote || '';
    const maximum = h('input' , {type: 'number', min: 0, max: 100}); maximum.value = settings.maximum_volume ?? 50;

    const speakers = h('section', {class: 'cd-card'},
      h('div', {class: 'cd-card-head'}, h('h3', {}, 'KEF speakers'), h('label', {class: 'cd-switch'}, enabled, h('span', {}, 'Enabled'))),
      h('p', {class: 'cd-muted'}, 'Control original KEF LSX speakers over your network: power, input, volume and mute.'),
      h('div', {class: 'cd-grid two'},
        labelled('Speaker address', host, 'The IP address or hostname of the KEF LSX'),
        labelled('KEF output in Roon', roonOutput, 'Choose this speaker only. Roon handles wake, standby, Wi-Fi, volume and mute; the other inputs require the direct KEF connection.'),
        labelled('Broadlink input remote (optional)', irRemote, 'Home Assistant remote entity in this room. Sends discrete AUX, optical, Bluetooth and Wi-Fi commands; requires a clear infrared path to the speaker.'),
        labelled('Maximum volume (%)', maximum, 'Applies to direct KEF and Roon volume commands')),
      connection);

    // Listening modes: one card per mode, shown directly instead of hidden in a menu.
    const modeList = h('div', {class: 'cd-modes'});
    const rows = [];
    const addMode = mode => {
      const name = h('input', {type: 'text', maxlength: 60}); name.value = mode.name || mode.id;
      const source = selectOf(SOURCES, mode.kef_input || 'aux');
      const volume = h('input', {type: 'number', min: 0, max: 100}); volume.value = mode.volume ?? 20;
      const topping = selectOf(TOPPING, mode.topping_input || '');
      const remove = h('button', {type: 'button', class: 'cd-quiet', 'aria-label': `Remove ${mode.name || mode.id}`, title: 'Remove this mode'}, 'Remove');
      const card = h('div', {class: 'cd-mode'},
        h('div', {class: 'cd-mode-head'}, labelled('Mode name', name), remove),
        h('div', {class: 'cd-grid two'}, labelled('KEF input', source), labelled('Starting volume (%)', volume)),
        labelled('Topping input', topping));
      const row = {mode, name, source, volume, topping, card};
      remove.onclick = () => { rows.splice(rows.indexOf(row), 1); card.remove(); refreshAdd(); };
      rows.push(row); modeList.append(card);
    };
    const add = h('button', {type: 'button', class: 'secondary'}, '+ Add listening mode');
    const refreshAdd = () => { add.disabled = rows.length >= 8; };
    add.onclick = () => { addMode({id: slug('mode', new Set(rows.map(row => row.mode.id))), name: 'New mode', kef_input: 'aux', volume: 20, topping_input: null}); refreshAdd(); };
    settings.modes.forEach(addMode); refreshAdd();
    const modes = h('section', {class: 'cd-card'},
      h('div', {class: 'cd-card-head'}, h('h3', {}, 'Listening modes')),
      h('p', {class: 'cd-muted'}, 'A mode sets the KEF input and starting volume in one go. Assign a mode to a Stream Deck key in the Stream Deck tab. Modes that need the Topping input changed stay unavailable until that control has been verified; KEF-only modes work now.'),
      modeList, h('div', {class: 'cd-actions'}, add));

    api.collectors.push(() => {
      const taken = new Set();
      settings.enabled = enabled.checked;
      settings.kef_host = host.value.trim();
      settings.kef_roon_output_id = roonOutput.value;
      settings.kef_ir_remote = irRemote.value.trim();
      settings.maximum_volume = Number(maximum.value);
      settings.modes = rows.map(row => {
        const id = taken.has(row.mode.id) ? slug(row.name.value, taken) : row.mode.id; taken.add(id);
        return {...row.mode, id, name: row.name.value.trim() || id, kef_input: row.source.value, volume: Number(row.volume.value), topping_input: row.topping.value || null};
      });
    });

    // Saved by the page-wide "Save changes" button.
    window.RoonDeckSaves = window.RoonDeckSaves || {};
    window.RoonDeckSaves.listening = async () => {
      try { await api.save(); message.textContent = 'Listening controls saved.'; api.notify(); }
      catch (error) { message.textContent = error.message; throw error; }
    };
    const touched = () => window.RoonDeckDirty?.('listening', 'Listening & KEF');
    root.replaceChildren(speakers, modes, h('div', {class: 'cd-actions'}, message));
    root.addEventListener('input', touched); root.addEventListener('change', touched);

    async function status() {
      try {
        const response = await fetch('/api/listening/status', {cache: 'no-store'});
        if (!response.ok) return;
        const state = await response.json();
        connection.textContent = `Status: ${state.kef?.connected ? (state.kef.control_path === 'roon' ? (state.ir_available ? 'Connected through Roon · infrared inputs ready' : 'Connected through Roon · direct input control unavailable') : 'Connected directly') : state.enabled ? 'Unavailable' : 'Disabled'}${state.error ? ' · ' + state.error : ''}`;
      } catch (_) { connection.textContent = 'Controls service unavailable'; }
    }
    status(); setInterval(status, 5000);
    api.notify();
  }
  load();
})();
