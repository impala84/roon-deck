(() => {
'use strict';
const byId = id => document.getElementById(id);
let snapshot = null;
let busy = false;
let installationTimer = null;
const buttons = () => document.querySelectorAll('.accessory-settings button');
let currentFeature = null;
function message(text, feature = currentFeature) { document.querySelectorAll('[data-accessory-message]').forEach(node => { if (!feature || node.closest('[data-accessory-feature]').dataset.accessoryFeature === feature) node.textContent = text; }); }
document.querySelectorAll('[data-accessory-feature]').forEach(panel => panel.addEventListener('click', () => { currentFeature = panel.dataset.accessoryFeature; }, true));
const actions = {none: 'No action', playpause: 'Play / pause', next: 'Next track', previous: 'Previous track', mute: 'Mute / unmute'};
for (const name of ['single', 'double', 'long']) {
  for (const [value, label] of Object.entries(actions)) byId(name).add(new Option(label, value));
}
async function request(data) {
  const response = await fetch('/api/admin/accessories', data ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data), signal: AbortSignal.timeout(65000)} : {cache: 'no-store', signal: AbortSignal.timeout(65000)});
  if (response.status === 401) { location.href = '/login.html'; throw new Error('Sign in to change settings.'); }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Operation failed.');
  return result;
}
function deviceStatus() {
  const device = snapshot?.devices.find(item => item.address === byId('device').value);
  byId('device-status').textContent = device ? `${device.paired ? 'Paired' : 'Not paired'} · ${device.connected ? 'Connected' : 'Disconnected'}${device.battery === null ? '' : ` · Battery ${device.battery}%`}` : 'No Surface Dial selected.';
}
async function refresh(fill = false) {
  const data = await request();
  const previousInstallation = snapshot?.installation?.status;
  snapshot = data;
  const vpn = data.vpn;
  byId('vpn-section').hidden = !data.features.vpn;
  byId('dial-section').hidden = !data.features.dial;
  const installation = data.installation || {status: 'idle', message: ''};
  document.querySelectorAll('[data-accessory-install]').forEach(button => {
    const feature = button.dataset.accessoryInstall;
    button.hidden = !data.features[feature] || (data.support[feature] && !['installing', 'error'].includes(installation.status));
    button.disabled = installation.status === 'installing';
  });
  document.querySelectorAll('[data-support-status]').forEach(node => { node.textContent = (installation.features || []).includes(node.closest('[data-accessory-feature]').dataset.accessoryFeature) ? installation.message : ''; });
  byId('bluetooth-service').textContent = `Bluetooth service: ${data.bluetooth_service || 'Unknown'}${data.bluetooth_service === 'Running' ? data.bluetooth_adapter ? ' · Adapter available' : ' · No adapter detected; check the Pi Bluetooth radio and firmware.' : ''}`;
  const pairing = data.pairing || {status: 'idle', message: ''};
  if (pairing.status !== 'idle') message(pairing.message, 'dial');
  if ((installation.status === 'installing' || pairing.status === 'pairing') && !installationTimer) {
    installationTimer = setTimeout(async () => {
      installationTimer = null;
      try { await refresh(); }
      catch (error) { message(error.message); }
    }, 2000);
  } else if (installation.status !== 'installing' && pairing.status !== 'pairing' && installationTimer) {
    clearTimeout(installationTimer); installationTimer = null;
  }
  if (previousInstallation === 'installing' && installation.status !== 'installing') (installation.features || []).forEach(feature => message(installation.message, feature));
  byId('vpn-status').textContent = vpn.status + (vpn.pending_token ? ` · Confirm within ${vpn.confirm_seconds} seconds` : '');
  byId('vpn-confirm').hidden = !vpn.pending_token;
  const details = byId('vpn-details'); details.replaceChildren();
  for (const [label, value] of [['Address', vpn.address || '—'], ['Endpoint', vpn.endpoint || '—'], ['Handshake', vpn.handshake_age === null ? 'None yet' : `${vpn.handshake_age} seconds ago`], ['Received / sent', `${vpn.received} / ${vpn.sent} bytes`]]) {
    const term = document.createElement('dt'), description = document.createElement('dd');
    term.textContent = label; description.textContent = value; details.append(term, description);
  }
  const chosen = byId('device').value || data.dial.address;
  byId('device').replaceChildren(new Option('Choose a discovered Dial', ''));
  data.devices.forEach(device => byId('device').add(new Option(`${device.name} · ${device.address}`, device.address)));
  byId('device').value = chosen;
  deviceStatus();
  byId('dial-status').textContent = `Roon controls: ${data.dial_status || 'Not running'}`;
  document.querySelectorAll('[data-operation^="bluetooth_"]').forEach(button => { button.disabled = pairing.status === 'pairing'; });
  if (!fill) return;
  byId('vpn-feature').checked = data.features.vpn;
  byId('dial-feature').checked = data.features.dial;
  byId('routing').value = vpn.mode;
  byId('subnets').value = vpn.subnets;
  byId('home-server').value = vpn.home_server;
  byId('home-gateway').value = vpn.home_gateway;
  byId('auto-connect').checked = vpn.auto_connect;
  const config = data.dial;
  byId('dial-enabled').checked = config.enabled;
  byId('target').value = config.target;
  byId('sensitivity').value = config.sensitivity;
  byId('acceleration').checked = config.acceleration;
  byId('maximum').value = config.maximum_volume ?? '';
  for (const name of ['single', 'double', 'long']) byId(name).value = config[name];
  const response = await fetch('/roon/api/accessory/outputs', {cache: 'no-store'});
  if (response.ok) {
    const {outputs} = await response.json();
    byId('output').replaceChildren(new Option('Choose a Roon output', ''));
    outputs.forEach(output => byId('output').add(new Option(`${output.name} · ${output.zone}`, output.id)));
    byId('output').value = config.output_id;
  }
}
async function perform(work, fill = false) {
  if (busy) return;
  busy = true;
  buttons().forEach(button => { button.disabled = true; });
  message('Working…');
  try {
    const result = await work();
    if (result?.diagnostics) {
      const labels = {home_gateway_reachable: 'Home gateway reachable', home_server_reachable: 'Home server reachable', roon_bridge_running: 'Roon Bridge running', roon_connected: 'Roon controller connected'};
      byId('vpn-diagnostics').textContent = Object.entries(result.diagnostics).map(([key, value]) => `${labels[key] || key}: ${value === null ? 'Not configured' : value ? 'Yes' : 'No'}`).join('\n') + '\n' + result.note;
    }
    await refresh(fill);
    if (!result?.pairing) message(result?.queued === true ? 'Installing optional support. Progress is shown below.' : 'Settings updated. Use Refresh status to check connection progress.');
  } catch (error) { message(error.message); }
  finally {
    busy = false; buttons().forEach(button => { button.disabled = false; });
    document.querySelectorAll('[data-accessory-install]').forEach(button => { button.disabled = snapshot?.installation?.status === 'installing'; });
    document.querySelectorAll('[data-operation^="bluetooth_"]').forEach(button => { button.disabled = snapshot?.pairing?.status === 'pairing'; });
  }
}
document.querySelectorAll('[data-accessory-refresh]').forEach(button => button.addEventListener('click', () => perform(async () => null)));
document.querySelectorAll('[data-save-feature]').forEach(button => button.addEventListener('click', () => {
  const feature = button.dataset.saveFeature;
  perform(() => request({operation: 'features_save', features: {...snapshot.features, [feature]: byId(feature + '-feature').checked}}), true);
}));
document.querySelectorAll('[data-accessory-install]').forEach(button => button.addEventListener('click', () => perform(() => request({operation: 'install', feature: button.dataset.accessoryInstall}))));
byId('device').addEventListener('change', deviceStatus);
byId('vpn-confirm').addEventListener('click', () => perform(() => request({operation: 'vpn_confirm', token: snapshot?.vpn.pending_token})));
document.querySelectorAll('.accessory-settings [data-operation]').forEach(button => button.addEventListener('click', () => {
  if (button.dataset.operation === 'bluetooth_forget' && !confirm('Forget this Surface Dial and turn off its Roon controls?')) return;
  perform(() => request({operation: button.dataset.operation, address: byId('device').value}), ['bluetooth_disconnect', 'bluetooth_forget'].includes(button.dataset.operation));
}));
byId('vpn-profile').addEventListener('submit', event => {
  event.preventDefault();
  perform(async () => {
    const file = byId('profile').files[0];
    if (!file || file.size > 16384) throw new Error('Choose a WireGuard .conf file smaller than 16 KB.');
    const profile = await file.text();
    try {
      return await request({operation: 'vpn_import', profile, mode: byId('routing').value, subnets: byId('subnets').value,
        auto_connect: byId('auto-connect').checked, home_server: byId('home-server').value, home_gateway: byId('home-gateway').value});
    } finally { byId('profile').value = ''; }
  });
});
byId('dial-config').addEventListener('submit', event => {
  event.preventDefault();
  perform(() => request({operation: 'dial_save', config: {enabled: byId('dial-enabled').checked, address: byId('device').value,
    target: byId('target').value, output_id: byId('output').value, sensitivity: byId('sensitivity').value,
    acceleration: byId('acceleration').checked, maximum_volume: byId('maximum').value === '' ? null : Number(byId('maximum').value),
    single: byId('single').value, double: byId('double').value, long: byId('long').value}}));
});
refresh(true).then(() => { message('Settings loaded. Configure each optional feature independently.'); })
  .catch(error => { message(error.message); });

})();
