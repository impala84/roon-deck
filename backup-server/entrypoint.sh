#!/bin/sh
set -eu
: "${ADMIN_PASSWORD:?Set ADMIN_PASSWORD to at least 16 characters}"
mkdir -p /data/ssh /data/incoming /data/archives /run/sshd
if [ ! -f /data/ssh/ssh_host_ed25519_key ]; then
    ssh-keygen -q -t ed25519 -N '' -f /data/ssh/ssh_host_ed25519_key
fi
# Root retains the SSH host identity; the application and isolated upload
# account share a UID but SSH is confined by rrsync to individual inboxes.
chown backup:backup /data /data/incoming /data/archives
for item in /data/registry.json /data/authorized_keys; do
    if [ -f "$item" ]; then chown backup:backup "$item"; fi
done
chmod 700 /data/ssh
cat > /run/roondeck-sshd.conf <<'EOF'
Port 2222
ListenAddress 0.0.0.0
HostKey /data/ssh/ssh_host_ed25519_key
PidFile /run/roondeck-sshd.pid
AuthorizedKeysFile /data/authorized_keys
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers backup
AllowTcpForwarding no
AllowAgentForwarding no
X11Forwarding no
PermitTTY no
PermitUserEnvironment no
Subsystem sftp internal-sftp
EOF
# Expose only the public host key to the web process.
chmod 755 /data/ssh
chmod 600 /data/ssh/ssh_host_ed25519_key
/usr/sbin/sshd -D -e -f /run/roondeck-sshd.conf &
ssh_pid=$!
export PYTHONPATH=/app
setpriv --reuid=backup --regid=backup --init-groups python /app/backup-server/server.py &
web_pid=$!
trap 'kill "$ssh_pid" "$web_pid" 2>/dev/null || true; wait' TERM INT EXIT
# Stop the container if either service fails, so restart policy can recover it.
while kill -0 "$ssh_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do sleep 2; done
exit 1
