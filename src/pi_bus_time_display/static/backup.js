/* Download and restore a backup of all RoonDeck settings. */
(() => {
  const status = document.getElementById('backup-status'), file = document.getElementById('backup-file');
  const download = document.getElementById('backup-download'), restore = document.getElementById('backup-restore');
  if (!status || !file) return;
  const say = text => { status.textContent = text; };
  download.onclick = async () => {
    say('Preparing…');
    try {
      const secrets = document.getElementById('backup-secrets').checked;
      const response = await fetch(`/api/admin/backup${secrets ? '?secrets=1' : ''}`, {cache: 'no-store'});
      if (response.status === 401) { location.href = '/login.html'; return; }
      if (!response.ok) throw new Error('Could not create the backup');
      const link = document.createElement('a');
      link.href = URL.createObjectURL(await response.blob());
      link.download = `roondeck-backup-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(link.href), 4000);
      say(secrets ? 'Downloaded, including passwords and tokens. Keep it private.' : 'Downloaded.');
    } catch (error) { say(error.message); }
  };
  restore.onclick = () => file.click();
  file.onchange = async () => {
    const chosen = file.files[0]; file.value = '';
    if (!chosen) return;
    if (!confirm('Restore this backup? It replaces your current settings, Stream Deck designs and Home layout.')) return;
    say('Restoring…');
    try {
      let body = await chosen.text();
      const bundle = JSON.parse(body);
      if (bundle.format === 'roondeck-encrypted-backup') {
        const password = prompt('Enter the recovery password used for this backup.');
        if (password === null) { say('Restore cancelled.'); return; }
        body = JSON.stringify({encrypted: bundle, password});
      }
      const response = await fetch('/api/admin/restore', {method: 'POST', headers: {'Content-Type': 'application/json'}, body});
      if (response.status === 401) { location.href = '/login.html'; return; }
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not restore that file');
      say('Restored. Reloading…'); setTimeout(() => location.reload(), 1200);
    } catch (error) { say(error.message); }
  };

  const $ = id => document.getElementById(id);
  const when = seconds => seconds ? new Date(seconds * 1000).toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'}) : 'Never';
  async function post(path, body) {
    const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    if (response.status === 401) { location.href = '/login.html'; throw new Error('Sign in to continue'); }
    const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Something went wrong'); return result;
  }
  const getJson = async path => { const response = await fetch(path, {cache: 'no-store'}); const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Request failed'); return data; };
  const el = (tag, cls, ...kids) => { const node = document.createElement(tag); if (cls) node.className = cls; node.append(...kids.filter(k => k !== null && k !== undefined)); return node; };
  const tick = '<svg width="120" height="120" viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M60 12 20 28v28c0 28 18 44 40 52 22-8 40-24 40-52V28z"/><path d="M42 60l13 13 25-28"/></svg>';
  const cloudIcon = '<svg width="120" height="120" viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M34 90a22 22 0 0 1-2-44 28 28 0 0 1 54 6 19 19 0 0 1-2 38z"/><path d="M58 40v34M44 54l14-14 14 14"/></svg>';
  function artCard(target, icon, title, lines, good) {
    const picture = el('div', 'hd-status-icon'); picture.innerHTML = icon;
    target.replaceChildren(picture, el('div', 'hd-status-title', title), ...lines.map(line => el('div', 'hd-status-note', line)), good ? el('div', 'hd-status-good', '● ' + good) : null);
  }

  /* ---- Tabs ---- */
  const tabs = [...document.querySelectorAll('[data-sw-tab]')], panes = [...document.querySelectorAll('[data-sw-pane]')];
  function showTab(name) {
    tabs.forEach(tab => tab.setAttribute('aria-selected', String(tab.dataset.swTab === name)));
    panes.forEach(pane => { pane.hidden = pane.dataset.swPane !== name; });
    try { sessionStorage.setItem('roondeck-software-tab', name); } catch (_) {}
  }
  tabs.forEach(tab => { tab.onclick = () => showTab(tab.dataset.swTab); });
  try { showTab(sessionStorage.getItem('roondeck-software-tab') || 'updates'); } catch (_) { showTab('updates'); }

  /* ---- Backup Server ---- */
  let server = {paired: false}, cloud = null;
  async function serverLoad() {
    try { server = await getJson('/api/admin/backup-server'); } catch (error) { server = {paired: false, failure: error.message}; }
    const paired = !!server.paired;
    $('bs-form').hidden = paired; $('bs-paired').hidden = !paired;
    if (!paired) {
      $('bs-status').textContent = server.failure || 'Not paired';
      artCard($('bs-art'), cloudIcon, 'Not paired yet', ['On the server press Pair a device.', 'It shows a code for ten minutes.']);
    } else {
      const p = server.policy || {};
      $('bs-title').textContent = 'Paired with Backup Server · ' + server.name;
      $('bs-policy').textContent = (p.enabled ? `Daily at ${p.time} ${p.timezone} · ` : 'Automatic backups paused · ') + `keeps ${p.keep} · ` + (p.include_secrets ? 'credentials included, encrypted' : 'credentials not included');
      const failed = server.local_status && !server.local_status.ok ? server.local_status.message : (server.error || '');
      artCard($('bs-art'), cloudIcon, server.name, ['Connected to ' + server.url.replace(/^https?:\/\//, ''), server.last_success ? 'Last backup ' + when(server.last_success) : 'Waiting for the first backup', failed], failed ? '' : 'Paired');
      const list = $('bs-backups'); list.replaceChildren();
      const points = [...(server.backups || [])].sort((a, b) => b.created - a.created);
      if (!points.length) list.append(el('li', 'bs-none', 'No recovery points yet. Press Back up now.'));
      for (const point of points) {
        const c = point.contents, parts = ['Settings'];
        if (c) { if (c.streamdeck) parts.push('Stream Deck designs'); if (c.home_layout) parts.push('Home layout'); if (c.images) parts.push(c.images + (c.images === 1 ? ' image' : ' images')); if (c.credentials) parts.push('credentials (encrypted)'); } else if (point.encrypted) parts.push('credentials (encrypted)');
        const restore = el('button', 'secondary', 'Restore'); restore.type = 'button';
        restore.onclick = () => restorePoint(point, restore);
        const row = el('li', 'bs-point', el('div', '', el('b', '', when(point.created)), el('small', '', parts.join(' · ') + ' · ' + Math.max(1, Math.round(point.size / 1024)) + ' KB')), restore);
        row.title = parts.join(' · '); list.append(row);
      }
      $('bs-password-note').textContent = server.encryption_password_set ? 'A recovery password is saved on this Pi, so encrypted recovery points restore without asking.' : $('bs-password-note').textContent;
    }
    summary();
  }
  async function restorePoint(point, button) {
    if (!confirm('Restore this recovery point? It replaces settings, Home layout and Stream Deck designs. Hardware, Wi-Fi and Roon authorisation may need setting up again.')) return;
    let password = '';
    if (point.encrypted && !server.encryption_password_set) { password = prompt('Enter the recovery password used for this backup.'); if (password === null) return; }
    button.disabled = true; $('bs-policy').textContent = 'Restoring…';
    try { await post('/api/admin/backup-server/restore', {name: point.name, password}); $('bs-policy').textContent = 'Restored. Reloading…'; setTimeout(() => location.reload(), 1200); }
    catch (error) { $('bs-policy').textContent = error.message; button.disabled = false; }
  }
  $('bs-pair').onclick = async () => {
    const button = $('bs-pair'), say = text => { $('bs-status').textContent = text; };
    button.disabled = true; say('Pairing…');
    try {
      await post('/api/admin/backup-server/pair', {url: $('bs-url').value, code: $('bs-code').value, name: $('bs-name').value});
      $('bs-code').value = ''; say('Paired. Taking the first backup…'); await serverLoad();
      $('bs-title').textContent = 'Paired. Taking the first backup…';
      try { await post('/api/admin/backup-server/run', {}); } catch (error) { $('bs-policy').textContent = 'Paired, but the first backup failed: ' + error.message; }
      await serverLoad();
    } catch (error) { say(error.message); } finally { button.disabled = false; }
  };
  $('bs-run').onclick = async () => {
    const button = $('bs-run'); button.disabled = true; button.textContent = 'Backing up…';
    try { await post('/api/admin/backup-server/run', {}); await serverLoad(); button.textContent = 'Backed up ✓'; setTimeout(() => { button.textContent = 'Back up now'; }, 2500); }
    catch (error) { $('bs-policy').textContent = error.message; button.textContent = 'Back up now'; } finally { button.disabled = false; }
  };
  $('bs-disconnect').onclick = async () => {
    if (!confirm('Disconnect this Pi from the backup server? Recovery points on the server are kept.')) return;
    try { await post('/api/admin/backup-server/disconnect', {}); } catch (error) { $('bs-policy').textContent = error.message; }
    await serverLoad();
  };
  $('bs-password-save').onclick = async () => {
    try { await post('/api/admin/backup-server/password', {password: $('bs-password').value}); $('bs-password').value = ''; await serverLoad(); }
    catch (error) { $('bs-password-note').textContent = error.message; }
  };

  /* ---- Cloud backups (saved with Save changes) ---- */
  const form = () => ({enabled: $('nas-enabled').checked, url: $('nas-url').value.trim(), folder: $('nas-folder').value.trim() || 'RoonDeck', username: $('nas-user').value.trim(), verify_tls: $('nas-verify').checked, password: $('nas-pass').value,
    google_enabled: $('g-enabled').checked, google_client_id: $('g-id').value.trim(), google_folder: $('g-folder').value.trim() || 'RoonDeck', google_secret: $('g-secret').value});
  const saveCloud = async () => { await post('/api/admin/backup-target', form()); $('nas-pass').value = ''; $('g-secret').value = ''; };
  async function cloudLoad() {
    try {
      const data = await getJson('/api/admin/backup-target'), t = data.target; cloud = data;
      $('nas-enabled').checked = t.enabled; $('nas-url').value = t.url; $('nas-folder').value = t.folder; $('nas-user').value = t.username; $('nas-verify').checked = t.verify_tls;
      $('nas-pass').placeholder = data.password_set ? 'Saved — leave blank to keep' : 'Password';
      $('g-enabled').checked = t.google_enabled; $('g-id').value = t.google_client_id; $('g-folder').value = t.google_folder;
      $('g-secret').placeholder = data.google_secret_set ? 'Saved — leave blank to keep' : 'Client secret';
      $('g-status').textContent = data.google_connected ? 'Connected' : 'Not connected';
      $('g-connect').textContent = data.google_connected ? 'Reconnect…' : 'Connect…';
      const s = data.status || {}; $('auto-status').textContent = s.time ? `${s.ok ? 'Last backup' : 'Last attempt failed'} ${s.time}: ${s.message}` : (t.enabled || t.google_enabled ? 'Waiting for the first backup' : 'Not set up');
    } catch (_) { $('auto-status').textContent = 'Could not load the backup settings'; }
    summary();
  }
  const run = (which, label) => async () => {
    label.textContent = 'Backing up…';
    try { await saveCloud(); const result = await post('/api/admin/backup-run', {which}); await cloudLoad(); label.textContent = result.saved.join('; '); }
    catch (error) { label.textContent = error.message; }
  };
  $('nas-run').onclick = run('synology', $('nas-status'));
  $('g-run').onclick = run('google', $('g-status'));
  $('g-connect').onclick = async () => {
    const box = $('g-code'), status = $('g-status');
    try {
      await saveCloud(); const flow = await post('/api/admin/backup-google-start', {});
      box.hidden = false; box.textContent = '';
      const link = document.createElement('a'); link.href = flow.url; link.target = '_blank'; link.rel = 'noopener'; link.textContent = flow.url;
      box.append('Open ', link, ' and enter the code ', Object.assign(document.createElement('strong'), {textContent: flow.user_code}), '. Waiting for you to approve…');
      const wait = ms => new Promise(resolve => setTimeout(resolve, ms)); const delay = (flow.interval || 5) * 1000;
      for (let attempt = 0; attempt < 120; attempt++) {
        await wait(delay);
        const result = await post('/api/admin/backup-google-poll', {});
        if (result.connected) { box.hidden = true; await cloudLoad(); status.textContent = 'Connected'; return; }
      }
      box.textContent = 'The code expired. Press Connect to try again.';
    } catch (error) { box.hidden = false; box.textContent = error.message; }
  };
  window.RoonDeckSaves = window.RoonDeckSaves || {};
  window.RoonDeckSaves.cloudbackups = async () => { await saveCloud(); await cloudLoad(); };
  const cloudPane = document.querySelector('[data-sw-pane="cloud"]');
  cloudPane.addEventListener('input', () => window.RoonDeckDirty?.('cloudbackups', 'Cloud backups'));
  cloudPane.addEventListener('change', () => window.RoonDeckDirty?.('cloudbackups', 'Cloud backups'));

  /* ---- Summary card on the first tab ---- */
  function summary() {
    const target = $('sw-summary'); if (!target) return;
    const points = server.paired ? (server.backups || []).length : 0;
    if (server.paired && server.last_success) artCard(target, tick, 'Backed up', ['Last backup ' + when(server.last_success), 'to your Backup Server', `${points} recovery ${points === 1 ? 'point' : 'points'} kept`], 'Everything is protected');
    else if (cloud && cloud.status && cloud.status.ok) artCard(target, tick, 'Backed up', [cloud.status.time, cloud.status.message], 'Cloud copy saved');
    else {
      artCard(target, tick, 'No automatic backup yet', ['Set up the Backup Server or a cloud copy so a damaged SD card never loses your settings.']);
      const go = el('button', 'secondary', 'Set up Backup Server'); go.type = 'button'; go.onclick = () => showTab('server'); target.append(go);
    }
  }
  serverLoad(); cloudLoad();
})();
