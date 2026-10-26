(() => {
'use strict';
const byId = id => document.getElementById(id);
let snapshot = null, timer = null, loading = false, busy = false;
const selectors = [...document.querySelectorAll('[data-connection-select]'), byId('save-wifi')];
selectors.forEach(button => { button.disabled = true; });
async function request(data) {
  const response = await fetch('/api/admin/network', data ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data),signal:AbortSignal.timeout(65000)} : {cache:'no-store',signal:AbortSignal.timeout(65000)});
  if (response.status === 401) { location.href='/login.html'; throw new Error('Sign in to change network settings.'); }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Network controls are unavailable.');
  return result;
}
function describe(devices, kind) {
  const items = devices.filter(item => item.kind === kind);
  if (!items.length) return 'No adapter detected';
  return items.map(item => `${item.connected ? 'Connected' : !item.managed ? 'Off' : 'Disconnected'} · ${item.interface}${item.name && item.name !== '--' ? '\n'+item.name : ''}${item.address ? '\n'+item.address : ''}`).join('\n');
}
async function refresh() {
  if (loading) return;
  loading = true;
  try {
    const data = await request(); snapshot = data;
    const pending = Boolean(data.trial.token);
    const hostname = data.hostname || byId('hostname').value;
    if (/^[a-zA-Z0-9-]+(?:\.local)?$/.test(hostname)) {
      const address = new URL('/admin.html#network/current', location.href); address.hostname = hostname.endsWith('.local') ? hostname : hostname+'.local';
      byId('connection-reopen').href = address.href; byId('connection-reopen').textContent = hostname.endsWith('.local') ? hostname : hostname+'.local';
    }
    for (const kind of ['ethernet','wifi']) {
      let description = describe(data.devices, kind);
      if (kind === 'wifi' && !data.wifi_enabled && data.devices.some(item => item.kind === kind)) description = 'Radio off';
      byId(kind+'-summary').textContent = description;
      byId(kind+'-detail').textContent = description;
    }
    const connected = data.devices.filter(item => item.connected);
    byId('wifi-status').textContent = connected.map(item => (item.kind === 'wifi' ? 'Wi-Fi' : 'Ethernet') + (item.name && item.name !== '--' ? ' · '+item.name : '')).join(' + ') || 'Not connected';
    byId('network-details').hidden = !connected.length;
    byId('network-type').textContent = connected.map(item => item.kind === 'wifi' ? 'Wi-Fi' : 'Ethernet').join(' + ') || '—';
    byId('network-address').textContent = connected.map(item => item.address).filter(Boolean).join(' · ') || '—';
    byId('network-signal').textContent = connected.map(item => item.signal).filter(Boolean).join(' · ') || '—';
    byId('network-signal').parentElement.hidden = !connected.some(item => item.signal);
    byId('network-speed').parentElement.hidden = !connected.some(item => item.speed);
    byId('network-speed').textContent = connected.map(item => item.speed).filter(Boolean).join(' · ') || '—';
    byId('connection-message').textContent = data.message || 'Choose Ethernet or Wi-Fi. The other connection will be completely off.';
    byId('connection-trial').hidden = !pending;
    byId('network-trial-link').hidden = !pending;
    byId('connection-countdown').textContent = `${data.status === 'switching' ? 'Switching connection' : 'Connection trial'} · ${data.trial.seconds} seconds remaining`;
    byId('connection-confirm').disabled = busy || data.status !== 'trial' || data.trial.seconds <= 0;
    selectors.forEach(button => {
      const kind = button.dataset.connectionSelect || 'wifi';
      button.disabled = busy || pending || !data.devices.some(item => item.kind === kind);
    });
    if (timer) clearTimeout(timer);
    timer = pending ? setTimeout(refresh, 2000) : null;
  } catch (error) {
    byId('connection-message').textContent = snapshot?.trial?.token ? 'Waiting for the connection. Reopen this page using the device name or new address. An unconfirmed switch will restore the previous connection.' : error.message;
    if (snapshot?.trial?.token) timer = setTimeout(refresh, 3000);
  } finally { loading = false; }
}
async function perform(data) {
  if (busy) return;
  busy = true; selectors.forEach(button => { button.disabled = true; });
  byId('connection-message').textContent = data.operation === 'select' ? 'Starting a 90-second connection trial…' : 'Applying network setting…';
  try {
    const result = await request(data);
    if (result.token) snapshot = {...snapshot,trial:{token:result.token}};
    if (data.operation === 'select') { showNetworkTab('current'); byId('network-trial-link').hidden = false; }
    await refresh();
  } catch (error) { byId('connection-message').textContent = error.message; }
  finally { busy = false; if(snapshot) selectors.forEach(button => {const kind=button.dataset.connectionSelect||'wifi';button.disabled=Boolean(snapshot.trial.token)||!snapshot.devices.some(item=>item.kind===kind);}); }
}
document.querySelectorAll('[data-connection-select]').forEach(button => button.addEventListener('click',()=>perform({operation:'select',target:button.dataset.connectionSelect})));
byId('save-wifi').addEventListener('click',()=>{
  const ssid=byId('wifi-ssid').value.trim(),password=byId('wifi-password').value;
  byId('wifi-password').value='';
  perform({operation:'select',target:'wifi',ssid,password});
});
byId('connection-confirm').addEventListener('click',()=>perform({operation:'confirm',token:snapshot?.trial?.token || ''}));
byId('connection-restore').addEventListener('click',()=>perform({operation:'restore'}));
byId('connection-refresh').addEventListener('click',refresh);
window.addEventListener('admin-network-open',refresh);
refresh();
})();
