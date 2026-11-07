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
      const response = await fetch('/api/admin/restore', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: await chosen.text()});
      if (response.status === 401) { location.href = '/login.html'; return; }
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not restore that file');
      say('Restored. Reloading…'); setTimeout(() => location.reload(), 1200);
    } catch (error) { say(error.message); }
  };

  const $ = id => document.getElementById(id);
  if (!$('nas-url')) return;
  async function post(path, body) {
    const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    if (response.status === 401) { location.href = '/login.html'; throw new Error('Sign in to continue'); }
    const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Something went wrong'); return result;
  }
  const form = () => ({enabled: $('nas-enabled').checked, url: $('nas-url').value.trim(), folder: $('nas-folder').value.trim() || 'RoonDeck', username: $('nas-user').value.trim(), verify_tls: $('nas-verify').checked, password: $('nas-pass').value,
    google_enabled: $('g-enabled').checked, google_client_id: $('g-id').value.trim(), google_folder: $('g-folder').value.trim() || 'RoonDeck', google_secret: $('g-secret').value});
  const save = async () => { await post('/api/admin/backup-target', form()); $('nas-pass').value = ''; $('g-secret').value = ''; };
  async function load() {
    try {
      const data = await (await fetch('/api/admin/backup-target', {cache: 'no-store'})).json(), t = data.target;
      $('nas-enabled').checked = t.enabled; $('nas-url').value = t.url; $('nas-folder').value = t.folder; $('nas-user').value = t.username; $('nas-verify').checked = t.verify_tls;
      $('nas-pass').placeholder = data.password_set ? 'Saved — leave blank to keep' : 'Password';
      $('g-enabled').checked = t.google_enabled; $('g-id').value = t.google_client_id; $('g-folder').value = t.google_folder;
      $('g-secret').placeholder = data.google_secret_set ? 'Saved — leave blank to keep' : 'Client secret';
      $('g-status').textContent = data.google_connected ? 'Connected' : 'Not connected';
      $('g-connect').textContent = data.google_connected ? 'Reconnect…' : 'Connect…';
      const s = data.status || {}; $('auto-status').textContent = s.time ? `${s.ok ? 'Last backup' : 'Last attempt failed'} ${s.time}: ${s.message}` : (t.enabled || t.google_enabled ? 'Waiting for the first backup' : 'Not set up');
    } catch (_) { $('auto-status').textContent = 'Could not load the backup settings'; }
  }
  const run = (which, label) => async () => {
    label.textContent = 'Backing up…';
    try { await save(); const result = await post('/api/admin/backup-run', {which}); await load(); label.textContent = result.saved.join('; '); }
    catch (error) { label.textContent = error.message; }
  };
  $('auto-save').onclick = async () => { try { await save(); await load(); $('auto-status').textContent = 'Saved. ' + $('auto-status').textContent; } catch (error) { $('auto-status').textContent = error.message; } };
  $('nas-run').onclick = run('synology', $('nas-status'));
  $('g-run').onclick = run('google', $('g-status'));
  $('g-connect').onclick = async () => {
    const box = $('g-code'), status = $('g-status');
    try {
      await save(); const flow = await post('/api/admin/backup-google-start', {});
      box.hidden = false; box.textContent = '';
      const link = document.createElement('a'); link.href = flow.url; link.target = '_blank'; link.rel = 'noopener'; link.textContent = flow.url;
      box.append('Open ', link, ' and enter the code ', Object.assign(document.createElement('strong'), {textContent: flow.user_code}), '. Waiting for you to approve…');
      const wait = ms => new Promise(resolve => setTimeout(resolve, ms)); let delay = (flow.interval || 5) * 1000;
      for (let attempt = 0; attempt < 120; attempt++) {
        await wait(delay);
        const result = await post('/api/admin/backup-google-poll', {});
        if (result.connected) { box.hidden = true; await load(); status.textContent = 'Connected'; return; }
      }
      box.textContent = 'The code expired. Press Connect to try again.';
    } catch (error) { box.hidden = false; box.textContent = error.message; }
  };
  load();
})();
