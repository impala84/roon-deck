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
})();
