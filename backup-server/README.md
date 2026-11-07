# RoonDeck Backup Server

An optional Docker companion for RoonDeck. Run it on a Synology or another Docker
host. The Pi uses the existing backup format and rsync over SSH; the server owns
schedules, retention, device policies and recovery points. Existing WebDAV,
Google Drive and direct-rsync destinations continue independently.

## Install on Synology

Clone/download this repository on the NAS. From `backup-server/`, create a `.env`:

```dotenv
ADMIN_PASSWORD=replace-with-a-long-unique-password
BACKUP_DATA_DIR=/volume1/docker/roondeck-backup-server
WEB_PORT=8042
SSH_PORT=2222
```

Use at least 16 characters for the server password. Create the data folder, then:

```sh
docker compose up -d --build
```

Open `http://YOUR-NAS:8042` and sign in with that password. Synology Container
Manager Projects can use this Compose file with the repository directory
available as its build context. In Portainer, build the image on the NAS first:

```sh
# Run from the repository root
docker build -f backup-server/Dockerfile -t roondeck-backup-server:local .
```

For a Git-managed Portainer stack, use repository URL
`https://github.com/impala84/roon-deck`, reference `refs/heads/main` and Compose
path `backup-server/compose.yaml`. Enter the environment variables above in
Portainer. `pull_policy: build` rebuilds the application from the checked-out
source when the stack is deployed, even if a local image already exists.

To update, open the stack and choose **Pull and redeploy**. Leave **Re-pull
image** / **Re-pull image and redeploy** OFF: this application image is built
locally and is not published on Docker Hub. Portainer fetches Git, Compose
rebuilds the image and replaces the container while preserving `/data`.
Do not delete the container, stack or mapped data folder before updating.
For a manually prebuilt image without `build:`, use `pull_policy: never` and
rebuild the image yourself before updating the stack.

There is no Docker socket mount, privileged mode,
host network or requirement to enable SSH on DSM. Port 2222 belongs to the
container. The image builds natively for amd64 or arm64; the RS1221+ uses amd64.

All durable data is in the mapped folder: registry, SSH host identity, paired
keys, incoming files and managed archives. Preserve this folder during container
upgrades. Back it up with your existing NAS backup/snapshot system.

## Pair and back up

1. On the server, choose **Pair a device**. The one-use code expires after ten minutes.
2. On the Pi, open web Settings → Software → **RoonDeck Backup Server**.
3. Enter the server address, device name and code, then pair.
4. Choose **Back up now**, or wait for the server's schedule.

Existing Alpine appliances install missing rsync/SSH tools when you first pair;
this needs internet access once. Fresh images include rsync.

The server supplies and the Pi pins the container's SSH host key during pairing.
Keep pairing on a trusted network. The default web connection is HTTP for a
private LAN; it carries authentication tokens and restored settings. Use HTTPS
before using an untrusted network. Either put the web port behind your HTTPS
reverse proxy, or mount certificate/key files read-only and set `TLS_CERT` and
`TLS_KEY`. The Pi validates HTTPS certificates; self-signed certificates need a
trusted CA installation. Do not expose these ports directly to the internet.

## Server management

- Set default policy for all devices; a saved device policy overrides defaults.
- Enable/pause automatic backups, set daily time and timezone, backup-on-change delay,
  maximum count and optional maximum age. Schedules default to UTC; set Asia/Singapore or another IANA timezone as needed. Settings are polled every 30 seconds.
- Change-triggered backups wait until settings have stayed unchanged for the
  chosen delay. Missed daily backups run when a device reconnects after the daily
  time. The first backup is due immediately. Failures retry after one hour.
- Retention is applied after successful uploads, policy changes, hourly and with
  **Apply retention now**. It always preserves the newest recovery point. Manual
  Delete can explicitly remove any recovery point, including the last one.
- Request a backup from the server (including while automatic backups are paused).
- Reset a device policy to follow the current server defaults.
- Download or delete individual recovery points; revoke access while retaining
  history; issue a recovery code for an existing device.
- The dashboard shows paired devices only. Connected/offline is based on
  heartbeat contact, not a scan of every machine on the network.

The Pi offers connection, status, a manual backup and restore. Managed backups
are uploaded individually without `--delete`; no retention mirror is kept on
the Pi. Server policies do not change the beta's separate legacy destinations.

## Encrypted credential backups

Credentials are excluded by default. Enable **Encrypt and include credentials**
on the server, then set a recovery password of at least 12 characters on the Pi.
Keep it in your password manager. The entire backup is encrypted on the Pi using
OpenSSL AES-256-CBC/PBKDF2 with an independent SHA-256 HMAC (encrypt then MAC).
The server never receives the password. It verifies the upload SHA-256 and
structure; only the Pi can authenticate and validate encrypted contents during
restore. Never lose the password: there is no recovery mechanism for it.

Supported credentials are the existing backup allowlist (Home Assistant, LTA,
OpenObserve and supported legacy backup-provider tokens). The OS, Wi-Fi,
WireGuard private keys, SSH private keys, admin password and Roon authorisation
are not included. Backups contain app configuration, listening/Stream Deck
settings, Home layout and uploaded deck art. They are not disk images or Roon
Core backups. Plain settings backups still contain potentially private settings.

## Restore after a failed card

Flash a current compatible RoonDeck image, connect it to the network and finish
basic device/admin setup. In the server dashboard, select the old device and
**Recover onto a replacement Pi**. Pair the fresh Pi using that code from its
web settings; this revokes the previous pairing but preserves its history and
server policy. Select a recovery point and restore, providing its recovery
password if encrypted. A different password can have been used for an older
recovery point. Server pairing and SSH identity are never overwritten by restore.

RoonDeck validates the downloaded file and checks the server's stored checksum
before applying settings, and makes a local safety copy at
`before-server-restore.json` (credentials excluded). Hardware/OS settings and
Roon authorisation must be configured for the replacement hardware separately.
Individual files are replaced atomically; a restore is not a filesystem-wide
transaction. Keep source and target on compatible app versions.

## Implementation and checks

`incoming/<device-id>/` is the only writable SSH destination. OpenSSH forced
commands use distribution-maintained `rrsync -wo -no-del -munge` to prevent
shell access, downloads, deletion and cross-device paths. Only completed,
checksummed uploads are copied into `archives/<device-id>/`; unfinished uploads
are not restore points. Orphan upload files older than one day are cleaned up.
Device API tokens are stored hashed on the server. Passwords/tokens, codes and
backup bodies are not written to web logs. Re-pairing rotates API and SSH access.

Run `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_backup_server*.py'`.
The optional real SSH integration test runs with `ROONDECK_TEST_SSH=1` as root on
a disposable Linux test host. Docker/Synology installation and physical SD-card
recovery still need hardware acceptance.
