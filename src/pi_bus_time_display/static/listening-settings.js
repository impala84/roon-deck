/* Listening controls: the KEF speaker (Roon for volume, Home Assistant infrared for input). The Stream Deck designer (deck-designer.js) shares the same settings. */
(() => {
  const root = document.getElementById('listening-settings');
  if (!root) return;
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

  async function load() {
    try {
      api.settings = await api.call('GET');
    } catch (error) { root.replaceChildren(h('p', {role: 'status'}, error.message)); return; }
    const settings = api.settings;
    const message = h('p', {role: 'status', class: 'cd-message'});
    const connection = h('p', {role: 'status', class: 'cd-muted'});

    const enabled = h('input', {type: 'checkbox'}); enabled.checked = !!settings.enabled;
    const roonOutput = selectOf([['', 'Choose the KEF output']], settings.kef_roon_output_id || '');
    try {
      const data = await api.call('GET', undefined, '/roon/api/accessory/outputs');
      for (const output of data.outputs || []) roonOutput.add(new Option(`${output.name} (${output.zone})`, output.id));
      if (settings.kef_roon_output_id && ![...roonOutput.options].some(option => option.value === settings.kef_roon_output_id)) {
        roonOutput.add(new Option('Saved output (currently unavailable)', settings.kef_roon_output_id));
      }
      roonOutput.value = settings.kef_roon_output_id || '';
    } catch (_) { if (settings.kef_roon_output_id) roonOutput.add(new Option('Saved output', settings.kef_roon_output_id)); roonOutput.value = settings.kef_roon_output_id || ''; }
    // Remotes found in Home Assistant; typing the entity id by hand stays available as a fallback.
    const irRemote = h('select'); irRemote.add(new Option('Search Home Assistant…', ''));
    const irManual = h('input', {type: 'text', placeholder: 'remote.study (or type any remote entity)'}); irManual.value = settings.kef_ir_remote || '';
    const irHint = h('small', {class: 'cd-muted'}, 'Looking for remotes in Home Assistant…');
    (async () => {
      try {
        const data = await api.call('GET', undefined, '/api/admin/home-remotes');
        for (const remote of data.remotes || []) irRemote.add(new Option(`${remote.name} (${remote.entity_id})`, remote.entity_id));
        irHint.textContent = (data.remotes || []).length ? `Found ${data.remotes.length} remote${data.remotes.length === 1 ? '' : 's'} in Home Assistant.` : 'No remotes found in Home Assistant. Type the entity id below.';
        if ([...irRemote.options].some(option => option.value === irManual.value)) irRemote.value = irManual.value;
      } catch (error) { irHint.textContent = `Could not search Home Assistant (${error.message}). Type the entity id below.`; }
    })();
    irRemote.onchange = () => { if (irRemote.value) irManual.value = irRemote.value; };
    const inputNames = [['wifi', 'Wi-Fi'], ['bluetooth', 'Bluetooth'], ['aux', 'AUX'], ['optical', 'Optical']];
    const presetMain = selectOf([['', 'Not set'], ...inputNames], settings.kef_input_preset || '');
    const presetAlt = selectOf([['', 'None (always use the main input)'], ...inputNames], settings.kef_input_alt || '');
    const maximum = h('input' , {type: 'number', min: 0, max: 100}); maximum.value = settings.maximum_volume ?? 50;

    const speakers = h('section', {class: 'cd-card'},
      h('div', {class: 'cd-card-head'}, h('h3', {}, 'KEF speaker'), h('label', {class: 'cd-switch'}, enabled, h('span', {}, 'Enabled'))),
      h('p', {class: 'cd-muted'}, 'Roon controls power, volume, mute and playback. A Broadlink remote in Home Assistant switches the speaker input with its infrared codes.'),
      h('div', {class: 'cd-grid two'},
        labelled('KEF output in Roon', roonOutput, 'Choose the KEF speaker itself (not the Pi). Roon handles wake, standby, volume and mute.'),
        labelled('Broadlink input remote', irRemote, 'Pick the Broadlink remote Home Assistant found. It needs a clear infrared path to the speaker.'),
        labelled('…or enter it manually', irManual, 'Fallback if the search finds nothing, for example remote.wi_fi_universal_remote.'),
        labelled('Input preset', presetMain, 'The home screen KEF input tile switches to this input with one tap. If the speaker is in standby it is woken first.'),
        labelled('Alternate preset (optional)', presetAlt, 'Set this to make the tile toggle between the two inputs instead.'),
        labelled('Maximum volume (%)', maximum, 'The highest volume the touchscreen, Stream Deck and remote can set')),
      irHint, connection);

    api.collectors.push(() => {
      const taken = new Set();
      settings.enabled = enabled.checked;
      settings.kef_roon_output_id = roonOutput.value;
      settings.kef_ir_remote = irManual.value.trim();
      settings.kef_input_preset = presetMain.value;
      settings.kef_input_alt = presetAlt.value;
      settings.maximum_volume = Number(maximum.value);
    });

    // Saved by the page-wide "Save changes" button.
    window.RoonDeckSaves = window.RoonDeckSaves || {};
    window.RoonDeckSaves.listening = async () => {
      try { await api.save(); message.textContent = 'Listening controls saved.'; api.notify(); }
      catch (error) { message.textContent = error.message; throw error; }
    };
    const touched = () => window.RoonDeckDirty?.('listening', 'Listening & KEF');
    root.replaceChildren(speakers, h('div', {class: 'cd-actions'}, message));
    root.addEventListener('input', touched); root.addEventListener('change', touched);

    async function status() {
      try {
        const response = await fetch('/api/listening/status', {cache: 'no-store'});
        if (!response.ok) return;
        const state = await response.json();
        connection.textContent = `Status: ${state.kef?.connected ? (state.ir_available ? 'Connected through Roon · infrared inputs ready' : 'Connected through Roon · add a Broadlink remote to switch inputs') : state.enabled ? 'Unavailable' : 'Disabled'}${state.error ? ' · ' + state.error : ''}`;
      } catch (_) { connection.textContent = 'Controls service unavailable'; }
    }
    status(); setInterval(status, 5000);
    api.notify();
  }
  load();
})();
