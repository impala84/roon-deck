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
      const speaker=state.kef || {}, connected=!!(state.enabled && speaker.connected), full=kind==='roondeck.kef';
      const names2={wifi:'Wi-Fi',bluetooth:'Bluetooth',aux:'AUX',optical:'Optical'};
      const button=(text,onclick,enabled=true,style='')=>{ const node=document.createElement('button'); node.type='button'; node.textContent=text; node.disabled=busy||!enabled; node.style.cssText='min-height:44px;padding:4px 12px;border-radius:12px;font-weight:600;'+style; node.onclick=onclick; return node; };
      const last=state.presets?.last||'', primary=tile.input||'', next=tile.input_alt&&last===primary?tile.input_alt:primary;
      const inputReady=!!(state.enabled&&primary&&state.ir_available);
      const pressInput=()=>command('preset',{primary,alt:tile.input_alt||''});
      const note=error||state.error||state.notice||(!state.enabled?'Not enabled':!connected?'Offline':speaker.powered===false?'Standby':'');
      const small=document.createElement('small'); small.setAttribute('role','status'); small.textContent=note; small.style.opacity='.7';
      if (kind==='roondeck.kef_input' || kind==='roondeck.kef_power') {
        // A tap tile: the input it will switch to, or the power state it will switch.
        const power=kind==='roondeck.kef_power', on=connected&&!!speaker.powered;
        const big=document.createElement('strong'); big.style.cssText='font-size:1.8rem;line-height:1.1'; big.textContent=power?(on?'Standby':connected?'Wake':'KEF'):(inputReady?(names2[next]||next):'KEF input');
        const tap=button('',power?()=>command('power',!on):pressInput,power?connected:inputReady,'text-align:left;display:grid;gap:4px;min-height:96px;width:100%'); tap.replaceChildren(big,(()=>{const d=document.createElement('small'); d.style.opacity='.75'; d.textContent=tile.label||(power?(on?'KEF is on · tap for standby':'KEF is in standby · tap to wake'):(inputReady?'Tap to switch KEF input':'Set the input in the tile options')); return d;})());
        card.append(tap); if (note) card.append(small);
        grid.append(card); continue;
      }
      const head=document.createElement('strong'); head.textContent=tile.label||names[kind]; head.style.cssText='font-size:.85rem;letter-spacing:.08em;text-transform:uppercase;opacity:.7'; card.append(head);
      const row=document.createElement('div'); row.style.cssText='display:flex;align-items:center;justify-content:space-between;gap:8px;flex:1';
      const number=document.createElement('strong'); number.textContent=connected&&Number.isFinite(speaker.volume)?String(Math.round(speaker.volume)):'\u2014'; number.style.cssText='font-size:3rem;line-height:1;cursor:pointer;'+(speaker.muted?'opacity:.4':''); number.title='Tap to mute or unmute'; number.onclick=()=>connected&&command('mute',null);
      const step=(text,value)=>button(text,()=>command('volume_delta',value),connected,'width:44px;height:44px;border-radius:22px;padding:0;font-size:1.4rem');
      row.append(step('\u2212',-2),number,step('+',2)); card.append(row);
      if (full) { const pills=document.createElement('div'); pills.style.cssText='display:flex;gap:8px'; pills.append(button(connected&&speaker.powered?'Standby':'Wake',()=>command('power',!(connected&&speaker.powered)),connected,'flex:1'),button(inputReady?(names2[next]||next):'Input',pressInput,inputReady,'flex:1')); card.append(pills); }
      if (note) card.append(small);
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
