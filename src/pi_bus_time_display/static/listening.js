/* KEF controls are optional Home grid tiles, configured in the Home builder. */
(() => {
  const grid = document.getElementById('entities');
  const names = {'roondeck.kef':'KEF speaker','roondeck.kef_power':'KEF power','roondeck.kef_input':'KEF input','roondeck.kef_volume':'KEF volume'};
  let busy = false, state = {}, cards = {}, error = '';
  async function command(action, value) {
    if (busy) return;
    busy = true; paint();
    try {
      const response = await fetch('/api/listening/command', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action,value})});
      if (response.status === 401) { location.href='/login.html'; return; }
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Speaker command failed');
      error = '';
    } catch (failure) { error = failure.message; }
    finally { busy=false; await load(); }
  }
  function paint() {
    grid.querySelectorAll('.kef-tile').forEach(node=>node.remove());
    for (const [key,tile] of Object.entries(cards)) {
      const kind=key.split('#')[0];
      if (!names[kind] || !tile.show || tile.page) continue;
      const card=document.createElement('article'); card.className='entity kef-tile'; card.dataset.id=key;
      card.style.cssText='display:flex;flex-direction:column;gap:8px;min-width:0;overflow:auto;padding:14px';
      if (tile.color) { card.style.background=tile.color+'44'; card.style.borderColor=tile.color; }
      else if (tile.border) card.style.borderColor=tile.border;
      const title=document.createElement('strong'); title.textContent=tile.label || names[kind]; card.append(title);
      const speaker=state.kef || {}, connected=!!(state.enabled && speaker.connected), full=kind==='roondeck.kef';
      const status=document.createElement('small'); status.textContent=!state.enabled?'Not enabled':connected?`${speaker.powered?'On':'Standby'} · ${speaker.volume}%`:'Offline'; card.append(status);
      function button(row,label,action,value,enabled=connected) {
        const node=document.createElement('button'); node.type='button'; node.textContent=label; node.style.cssText='min-height:44px;flex:1;padding:6px'; node.disabled=busy || !enabled;
        node.onclick=()=>command(action,value); row.append(node);
      }
      function row() { const node=document.createElement('div'); node.style.cssText='display:flex;gap:6px'; card.append(node); return node; }
      if (full || kind.endsWith('_power')) { const controls=row(); button(controls,'On','power',true); button(controls,'Standby','power',false); }
      if (full || kind.endsWith('_input')) {
        const pick=document.createElement('select'); pick.setAttribute('aria-label','KEF input'); pick.style.minHeight='44px';
        const choices=[['','Choose input…'],['wifi','Wi-Fi / Roon']];
        if (state.ir_available || speaker.direct_inputs_available!==false) choices.push(['aux','AUX'],['optical','Optical'],['bluetooth','Bluetooth']);
        for (const [value,label] of choices) { const option=document.createElement('option'); option.value=value; option.textContent=label; pick.append(option); }
        pick.disabled=busy || !state.enabled || !(connected || state.ir_available); pick.onchange=()=>{ if(pick.value) command('input',pick.value); }; card.append(pick);
      }
      if (full || kind.endsWith('_volume')) { const controls=row(); button(controls,'−','volume_delta',-2); button(controls,'+','volume_delta',2); button(controls,speaker.muted?'Unmute':'Mute','mute',null); }
      const message=document.createElement('small'); message.setAttribute('role','status'); message.textContent=error || state.error || state.notice || ''; card.append(message);
      grid.append(card);
    }
  }
  document.addEventListener('home-rendered', event=>{ cards=event.detail.cards || {}; paint(); });
  async function load() {
    if (busy) return;
    try { const response=await fetch('/api/listening/status',{cache:'no-store'}); if(!response.ok) throw new Error('Speaker service unavailable'); state=await response.json(); }
    catch (failure) { error=failure.message; }
    paint();
  }
  load(); setInterval(load,3000);
})();
