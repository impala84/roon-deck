/* Optional controls are configured independently of the main settings form. */
(() => {
  const root = document.getElementById('listening-settings');
  const message = document.createElement('p'); message.setAttribute('role', 'status');
  const fields = {};
  let settings;
  function field(parent, label, type = 'text', value = '') {
    const wrapper = document.createElement('label'); wrapper.textContent = label;
    const input = document.createElement('input'); input.type = type;
    if (type === 'checkbox') { wrapper.className = 'check'; input.checked = !!value; }
    else input.value = value;
    wrapper.append(input); parent.append(wrapper); return input;
  }
  function select(parent, label, options, value) {
    const wrapper = document.createElement('label'); wrapper.textContent = label;
    const input = document.createElement('select');
    for (const [id, name] of options) input.add(new Option(name, id));
    input.value = value; wrapper.append(input); parent.append(wrapper); return input;
  }
  function details(label) {
    const box = document.createElement('details'); const heading = document.createElement('summary');
    heading.textContent = label; box.append(heading); root.append(box); return box;
  }
  async function call(method, body) {
    const response = await fetch('/api/admin/listening', {method,
      headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
    if (response.status === 401) { location.href = '/login.html'; throw new Error('Sign in to continue'); }
    const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Could not save controls');
    return result;
  }
  async function load() {
    try {
      settings = await call('GET');
      root.replaceChildren();
      const title = document.createElement('h3'); title.textContent = 'Listening & Stream Deck +'; root.append(title);
      const intro = document.createElement('p'); intro.textContent = 'Control original KEF LSX speakers and an optional Stream Deck connected to the Pi. Topping input switching is awaiting hardware verification.'; root.append(intro);
      fields.enabled = field(root, 'Enable KEF listening controls', 'checkbox', settings.enabled);
      fields.kef_host = field(root, 'KEF speaker address', 'text', settings.kef_host || ''); fields.kef_host.placeholder = '10.12.0.125';
      fields.maximum_volume = field(root, 'Maximum KEF volume (%)', 'number', settings.maximum_volume ?? 50);
      fields.maximum_volume.min = '0'; fields.maximum_volume.max = '100';
      fields.streamdeck_enabled = field(root, 'Enable USB Stream Deck +', 'checkbox', settings.streamdeck_enabled);
      const support = document.createElement('p'); support.textContent = 'USB support requires the optional Stream Deck packages and device permissions on the Pi. Saved mappings take effect automatically. Custom artwork can be placed in the deck-art folder.'; root.append(support);
      const modes = details('Listening modes'); fields.modes = [];
      const sourceOptions = ['aux', 'optical', 'wifi', 'bluetooth'].map(value => [value, value]);
      for (const mode of (settings.modes?.length ? settings.modes : [{id:"pi",name:"Pi / Roon",kef_input:"aux",topping_input:"coaxial",volume:20},{id:"mac",name:"Mac",kef_input:"aux",topping_input:"usb",volume:20}])) {
        const box = document.createElement('fieldset'); modes.append(box);
        const name = field(box, 'Mode name', 'text', mode.name || mode.id);
        const source = select(box, 'KEF input', sourceOptions, mode.kef_input);
        const volume = field(box, 'Starting volume (%)', 'number', mode.volume); volume.min = '0'; volume.max = '100';
        const topping = select(box, 'Topping input', [['', 'Keep unchanged (KEF controls only)'], ['usb', 'Mac USB'], ['coaxial', 'Pi coaxial'], ['optical', 'Pi optical'], ['bluetooth', 'Bluetooth']], mode.topping_input || '');
        fields.modes.push({mode, name, source, volume, topping});
      }
      const modeHint = document.createElement('p'); modeHint.textContent = 'Modes that require changing the Topping input stay unavailable until that control has been verified. KEF-only modes can be tested now.'; modes.append(modeHint);
      const mappings = details('Stream Deck buttons'); fields.buttons = [];
      const defaults = [
        {label:'Pi / Roon',action:'mode',value:'pi'}, {label:'Mac',action:'mode',value:'mac'},
        {label:'Power on',action:'power',value:true}, {label:'Standby',action:'power',value:false},
        {label:'Previous',action:'previous'}, {label:'Play / Pause',action:'playpause'},
        {label:'Next',action:'next'}, {label:'Mute',action:'mute'}];
      const actions = [['none','Unused'],['mode','Listening mode'],['power','KEF power'],['input','KEF input'],['mute','KEF mute'],['previous','Previous track'],['playpause','Play / pause'],['next','Next track'],['home_toggle','Home toggle'],['home_scene','Home scene']];
      for (let index = 0; index < 8; index++) {
        const binding = (settings.buttons?.length ? settings.buttons : defaults)[index] || {};
        const box = document.createElement('fieldset'); mappings.append(box);
        const legend = document.createElement('legend'); legend.textContent = `Button ${index + 1}`; box.append(legend);
        const label = field(box, 'Label', 'text', binding.label || '');
        const action = select(box, 'Action', actions, binding.action || 'none');
        const value = field(box, 'Target', 'text', binding.entity_id || String(binding.value ?? ''));
        value.placeholder = 'Mode ID, input, true / false, or Home entity ID';
        const image = field(box, 'Artwork filename (optional)', 'text', binding.image || '');
        fields.buttons.push({label, action, value, image});
      }
      const dials = details('Stream Deck dials'); fields.dials = [];
      for (let index = 0; index < 4; index++) {
        const binding = (settings.dials?.length ? settings.dials : [{label:'KEF volume',action:'volume_delta',step:1,press:{action:'mute'}}])[index] || {};
        const box = document.createElement('fieldset'); dials.append(box);
        const label = field(box, `Dial ${index + 1} label`, 'text', binding.label || '');
        const action = select(box, 'Turn action', [['none','Unused'],['volume_delta','KEF volume'],['home_level','Home brightness / fan level']], binding.action || 'none');
        const entity = field(box, 'Home entity (for brightness / fan)', 'text', binding.entity_id || '');
        const step = field(box, 'Step per tick', 'number', binding.step ?? 1); step.min = '1'; step.max = '10';
        const press = select(box, 'Press / strip tap', [['none','Unused'],['mute','KEF mute'],['playpause','Play / pause'],['home_toggle','Toggle this Home device']], binding.press?.action || 'none');
        fields.dials.push({label, action, entity, step, press});
      }
      const save = document.createElement('button'); save.type = 'button'; save.textContent = 'Save listening controls';
      save.onclick = async () => {
        save.disabled = true; message.textContent = 'Saving…';
        try {
          if (fields.buttons.some(item => item.action.value === 'power' && !['true','false'].includes(item.value.value))) throw new Error('Power targets must be true or false');
          const buttons = fields.buttons.map(item => ({label:item.label.value,action:item.action.value,
            ...(item.action.value.startsWith('home_') ? {entity_id:item.value.value} : {value:item.action.value === 'power' ? item.value.value === 'true' : item.value.value}),
            ...(item.image.value ? {image:item.image.value} : {})}));
          const dials = fields.dials.map(item => ({label:item.label.value,action:item.action.value,entity_id:item.entity.value,
            step:Number(item.step.value),press:{action:item.press.value,entity_id:item.entity.value}}));
          const modes = fields.modes.map(item => ({...item.mode,name:item.name.value,kef_input:item.source.value,
            volume:Number(item.volume.value),topping_input:item.topping.value || null}));
          await call('POST', {...settings,enabled:fields.enabled.checked,kef_host:fields.kef_host.value.trim(),
            maximum_volume:Number(fields.maximum_volume.value),streamdeck_enabled:fields.streamdeck_enabled.checked,modes,buttons,dials});
          message.textContent = 'Listening controls saved.';
        } catch (error) { message.textContent = error.message; }
        finally { save.disabled = false; }
      };
      root.append(save, message);
      const connection = document.createElement('p'); connection.setAttribute('role', 'status'); root.append(connection);
      async function status() {
        try {
          const response = await fetch('/api/listening/status', {cache:'no-store'});
          if (!response.ok) return;
          const state = await response.json(); const deck = state.streamdeck || {};
          connection.textContent = `KEF: ${state.kef?.connected ? 'Connected' : state.enabled ? 'Unavailable' : 'Disabled'} · Stream Deck: ${deck.connected ? 'Connected' : deck.enabled ? deck.error || 'Waiting for device' : 'Disabled'}`;
        } catch (_) { connection.textContent = 'Controls service unavailable'; }
      }
      status(); setInterval(status, 5000);
    } catch (error) { message.textContent = error.message; root.append(message); }
  }
  load();
})();
