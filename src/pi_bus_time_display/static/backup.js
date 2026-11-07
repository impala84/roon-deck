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

  const nas = id => document.getElementById(id);
  if (!nas('nas-url')) return;
  const nasSay = text => { nas('nas-status').textContent = text; };
  async function post(path, body) {
    const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    if (response.status === 401) { location.href = '/login.html'; throw new Error('Sign in to continue'); }
    const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Something went wrong'); return result;
  }
  const form = () => ({enabled: nas('nas-enabled').checked, url: nas('nas-url').value.trim(), folder: nas('nas-folder').value.trim() || 'RoonDeck', username: nas('nas-user').value.trim(), verify_tls: nas('nas-verify').checked, password: nas('nas-pass').value});
  async function loadNas() {
    try {
      const data = await (await fetch('/api/admin/backup-target', {cache: 'no-store'})).json(), t = data.target;
      nas('nas-enabled').checked = t.enabled; nas('nas-url').value = t.url; nas('nas-folder').value = t.folder; nas('nas-user').value = t.username; nas('nas-verify').checked = t.verify_tls;
      nas('nas-pass').placeholder = data.password_set ? 'Saved — leave blank to keep' : 'Password';
      const s = data.status || {}; nasSay(s.time ? `${s.ok ? 'Last backup' : 'Last attempt failed'} ${s.time}: ${s.message}` : (t.enabled ? 'Waiting for the first backup' : 'Not set up'));
    } catch (_) { nasSay('Could not load the backup settings'); }
  }
  nas('nas-save').onclick = async () => { try { await post('/api/admin/backup-target', form()); nas('nas-pass').value = ''; await loadNas(); nasSay('Saved. ' + nas('nas-status').textContent); } catch (error) { nasSay(error.message); } };
  nas('nas-run').onclick = async () => { nasSay('Backing up…'); try { await post('/api/admin/backup-target', form()); nas('nas-pass').value = ''; const result = await post('/api/admin/backup-run', {}); await loadNas(); nasSay(`Saved ${result.name}`); } catch (error) { nasSay(error.message); } };
  loadNas();
})();
