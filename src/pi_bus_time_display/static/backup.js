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
  if (!$('nas-url')) return;
  async function post(path, body) {
    const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    if (response.status === 401) { location.href = '/login.html'; throw new Error('Sign in to continue'); }
    const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Something went wrong'); return result;
  }
  const form = () => ({enabled: $('nas-enabled').checked, url: $('nas-url').value.trim(), folder: $('nas-folder').value.trim() || 'RoonDeck', username: $('nas-user').value.trim(), verify_tls: $('nas-verify').checked, password: $('nas-pass').value,
    google_enabled: $('g-enabled').checked, google_client_id: $('g-id').value.trim(), google_folder: $('g-folder').value.trim() || 'RoonDeck', google_secret: $('g-secret').value,
    rsync_enabled: $('rs-enabled').checked, rsync_host: $('rs-host').value.trim(), rsync_port: Number($('rs-port').value) || 22, rsync_user: $('rs-user').value.trim(), rsync_path: $('rs-path').value.trim()});
  const save = async () => { await post('/api/admin/backup-target', form()); $('nas-pass').value = ''; $('g-secret').value = ''; };
  async function load() {
    try {
      const data = await (await fetch('/api/admin/backup-target', {cache: 'no-store'})).json(), t = data.target;
      $('nas-enabled').checked = t.enabled; $('nas-url').value = t.url; $('nas-folder').value = t.folder; $('nas-user').value = t.username; $('nas-verify').checked = t.verify_tls;
      $('nas-pass').placeholder = data.password_set ? 'Saved — leave blank to keep' : 'Password';
      $('rs-enabled').checked = t.rsync_enabled; $('rs-host').value = t.rsync_host; $('rs-port').value = t.rsync_port; $('rs-user').value = t.rsync_user; $('rs-path').value = t.rsync_path;
      $('rs-key').hidden = !data.ssh_key; $('rs-key').value = data.ssh_key || ''; $('rs-keybtn').textContent = data.ssh_key ? 'Show key' : 'Create key';
      $('g-enabled').checked = t.google_enabled; $('g-id').value = t.google_client_id; $('g-folder').value = t.google_folder;
      $('g-secret').placeholder = data.google_secret_set ? 'Saved — leave blank to keep' : 'Client secret';
      $('g-status').textContent = data.google_connected ? 'Connected' : 'Not connected';
      $('g-connect').textContent = data.google_connected ? 'Reconnect…' : 'Connect…';
      const s = data.status || {}; $('auto-status').textContent = s.time ? `${s.ok ? 'Last backup' : 'Last attempt failed'} ${s.time}: ${s.message}` : (t.enabled || t.google_enabled || t.rsync_enabled ? 'Waiting for the first backup' : 'Not set up');
    } catch (_) { $('auto-status').textContent = 'Could not load the backup settings'; }
  }
  const run = (which, label) => async () => {
    label.textContent = 'Backing up…';
    try { await save(); const result = await post('/api/admin/backup-run', {which}); await load(); label.textContent = result.saved.join('; '); }
    catch (error) { label.textContent = error.message; }
  };
  $('auto-save').onclick = async () => { try { await save(); await load(); $('auto-status').textContent = 'Saved. ' + $('auto-status').textContent; } catch (error) { $('auto-status').textContent = error.message; } };
  $('nas-run').onclick = run('synology', $('nas-status'));
  $('rs-run').onclick = run('rsync', $('rs-status'));
  $('rs-keybtn').onclick = async () => {
    try { const result = await post('/api/admin/backup-rsync-key', {}); $('rs-key').hidden = false; $('rs-key').value = result.public_key; $('rs-keybtn').textContent = 'Show key'; $('rs-status').textContent = 'Add this key to the NAS user\u2019s authorized_keys, then press Back up now.'; $('rs-key').select(); }
    catch (error) { $('rs-status').textContent = error.message; }
  };
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
  async function serverLoad() {
    const response = await fetch('/api/admin/backup-server', {cache: 'no-store'});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Could not reach backup server');
    $('bs-paired').hidden = !data.paired;
    if (!data.paired) { $('bs-status').textContent = 'Not paired'; return; }
    $('bs-url').value = data.url; $('bs-name').value = data.name;
    $('bs-status').textContent = data.error || (data.last_success ? 'Last backup: ' + new Date(data.last_success * 1000).toLocaleString() : 'Paired. Waiting for the first backup.');
    if (data.local_status && !data.local_status.ok) $('bs-status').textContent = data.local_status.message;
    $('bs-policy').textContent = 'Managed on server: ' + (data.policy.enabled ? 'daily at ' + data.policy.time + ' ' + data.policy.timezone : 'paused') + ', keeping ' + data.policy.keep + ' backups. ' + (data.policy.include_secrets ? 'Encrypted credentials enabled. ' + (data.encryption_password_set ? 'Recovery password saved.' : 'Set your recovery password below.') : 'Credentials excluded.');
    $('bs-backups').replaceChildren();
    for (const backup of data.backups) { const option = document.createElement('option'); option.value = backup.name; option.textContent = new Date(backup.created * 1000).toLocaleString() + ' · ' + backup.app_version + (backup.encrypted ? ' · encrypted' : ''); option.dataset.encrypted = backup.encrypted ? '1' : ''; $('bs-backups').append(option); }
    $('bs-restore').disabled = !data.backups.length;
  }
  const serverAction = fn => async () => { try { await fn(); await serverLoad(); } catch (error) { $('bs-status').textContent = error.message; } };
  $('bs-pair').onclick = serverAction(async () => { await post('/api/admin/backup-server/pair', {url: $('bs-url').value, code: $('bs-code').value, name: $('bs-name').value}); $('bs-code').value = ''; });
  $('bs-refresh').onclick = serverAction(async () => {});
  $('bs-run').onclick = serverAction(async () => { $('bs-status').textContent = 'Backing up…'; await post('/api/admin/backup-server/run', {}); });
  $('bs-password-save').onclick = serverAction(async () => { await post('/api/admin/backup-server/password', {password: $('bs-password').value}); $('bs-password').value = ''; });
  $('bs-disconnect').onclick = serverAction(async () => { if (confirm('Disconnect this Pi? Server backups will be kept.')) await post('/api/admin/backup-server/disconnect', {}); });
  $('bs-restore').onclick = serverAction(async () => {
    const option = $('bs-backups').selectedOptions[0]; if (!option) return;
    if (!confirm('Restore this recovery point? It replaces settings, Home layout and Stream Deck designs. Hardware, Wi-Fi and Roon authorisation may need setting up again.')) return;
    let password = '';
    if (option.dataset.encrypted) { password = prompt('Enter the recovery password used for this backup.'); if (password === null) return; }
    $('bs-status').textContent = 'Restoring…';
    await post('/api/admin/backup-server/restore', {name: option.value, password});
    $('bs-status').textContent = 'Restored. Reloading…'; setTimeout(() => location.reload(), 1200);
  });
  serverLoad().catch(error => { $('bs-status').textContent = error.message; });
  load();
})();
