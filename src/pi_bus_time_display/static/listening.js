/* Shared listening commands; device text is rendered as text, never markup. */
(() => {
  const root = document.getElementById('listening');
  let busy = false;
  let signature = '';
  const message = document.createElement('p');
  async function command(action, value) {
    if (busy) return;
    busy = true;
    root.querySelectorAll('button').forEach(button => { button.disabled = true; });
    try {
      const response = await fetch('/api/listening/command', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action, value})
      });
      if (response.status === 401) { location.href = '/login.html'; return; }
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Listening command failed');
      message.textContent = '';
    } catch (error) { message.textContent = error.message; }
    finally { busy = false; signature = ''; await load(); }
  }
  async function load() {
    if (busy) return;
    try {
      const response = await fetch('/api/listening/status', {cache: 'no-store'});
      if (!response.ok) throw new Error('Listening service unavailable');
      const state = await response.json();
      root.hidden = !state.enabled;
      const current = JSON.stringify(state);
      if (!state.enabled || current === signature) return;
      signature = current;
      root.replaceChildren();
      const speaker = state.kef || {};
      const heading = document.createElement('h2'); heading.textContent = 'Listening'; root.append(heading);
      const status = document.createElement('p');
      status.textContent = speaker.connected
        ? `KEF LSX · ${speaker.powered ? 'On' : 'Standby'} · ${speaker.input} · ${speaker.volume}%${speaker.muted ? ' · Muted' : ''}`
        : 'KEF LSX · Offline';
      root.append(status);
      const controls = document.createElement('div');
      controls.style.cssText = 'display:flex;flex-wrap:wrap;gap:12px;margin:12px 0';
      function button(label, action, value, enabled = true, reason = '') {
        const node = document.createElement('button'); node.type = 'button'; node.textContent = label;
        node.style.cssText = 'min-height:48px;padding:10px 16px';
        node.disabled = !speaker.connected || !enabled; node.title = reason;
        node.onclick = () => command(action, value); controls.append(node);
      }
      button('Power on', 'power', true); button('Standby', 'power', false);
      button('− Volume', 'volume_delta', -2); button('+ Volume', 'volume_delta', 2); button('Mute', 'mute');
      for (const input of ['wifi', 'aux', 'optical', 'bluetooth']) button(input, 'input', input);
      for (const mode of state.modes || []) button(mode.name, 'mode', mode.id, mode.available, mode.reason);
      root.append(controls);
      if (state.error) message.textContent = state.error;
      else if ((state.modes || []).some(mode => !mode.available)) message.textContent = "Topping input switching is not available yet.";
      message.setAttribute('role', 'status'); root.append(message);
    } catch (error) {
      if (!root.hidden) { message.textContent = error.message; root.append(message); }
    }
  }
  load(); setInterval(load, 3000);
})();
