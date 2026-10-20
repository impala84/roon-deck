# RoonDeck

Alpine testing release: **1.1.3-beta.45**, refining final play actions, one-percent volume steps, and the portrait and compact-landscape album detail layout. Select Beta explicitly to test; Stable remains 1.1.2.

The current Alpine stable release is **1.1.2**: an in-place correction for 10-inch Touch Display 2 touch rotation. Update through System → Software on the Stable channel, then reboot manually to apply input calibration. Physical touch acceptance is still required. The 1.1.1 full image remains available for fresh installs. Raspberry Pi OS releases remain separate.

Beta updates are normally source-only releases; full images are built for stable releases and explicit fresh-install requests. Automated backend, controller, update-safety and native layout checks run, followed by complete image validation with **build_image** enabled. The Alpine updater requires a successful verification run for the exact release commit.

RoonDeck is an independent Raspberry Pi touchscreen interface for Roon, with optional Singapore bus arrivals, Home Assistant controls and Roon Bridge. It runs a native GTK4 display in Cage/Wayland, alongside a phone/desktop web interface. Chromium is not required.

The Raspberry Pi OS stable baseline remains **v1.0.0**. **RoonDeck 1.1.0 Alpine** is the first separately published Alpine release (`v1.1.0-alpine`), with first-run setup, optional Roon Bridge/Netdata installation, shared display settings and responsive GTK layouts. Existing Alpine devices retain their verified updater, while Raspberry Pi OS devices stay on their own distribution. Native discovery uses bounded artwork cards and configurable two/three-column portrait grids; Diagnostics captures the live GTK touchscreen, including artwork. Automated release checks do not replace testing on the physical display.

## Features

The [Alpine appliance](docs/ALPINE.md) retains the `alpine-beta` branch name for updater compatibility.
The old `alpine-appliance-prototype` branch is retained temporarily only so
beta.14 and older appliances can cross to the renamed channel safely.

- Roon artwork, lead artist, track information, progress, playback, mute and volume.
- Queue, library browsing, combined library/connected TIDAL search and Surprise playback, through Roon's official extension API. Catalogue availability depends on the connected Roon Server.
- Optional BluOS amplifier/source controls, separate from Roon playback.
- Optional Singapore LTA arrivals: up to four service rows and three arrivals per service.
- Optional Home Assistant controls for up to eight allow-listed `fan`, `light`, `switch` and `input_boolean` entities.
- Fresh Mint and Roon-inspired themes, shared across touchscreen and web.
- Shared Landscape/Portrait display settings with panel-aware rotation and responsive native GTK layouts from 480×800 through 1920×1200.
- Scheduled sleep, touch wake, brightness/orientation controls and playback-aware wake behaviour. TV/record inputs do not independently hold the display awake.
- Password-protected web settings, diagnostics, actual display capture and controlled system actions.
- Published-release updates with Stable/Beta selection, preserving appliance configuration and credentials.
- In v1.1 Beta: artwork-led Recent, personalised mixes and Daily Picks, New Releases for You, with existing Browse/Surprise Me under Discover. Its five tabs are Recent, Browse, Daily Mixes, New Releases and Surprise Me (Mixes/New on phones). Mix detail offers experimental Play This Mix and Queue This Mix controls above its visible bounded track preview.

RoonDeck is an independent project and is not affiliated with or endorsed by Roon Labs. Roon Server and a Roon subscription are separate requirements. Roon Bridge is optional: it turns the Pi into a RAAT audio endpoint, but is not needed to control an existing Roon zone.

## Hardware and runtime

The personal installation uses a Raspberry Pi and an official Touch Display 2 in landscape (1280×720). The exact Pi model, OS image and saved rotation have not been audited remotely; the fresh-install procedure below is documented but not proven by a clean hardware rebuild. Original Touch Display (800×480) and Touch Display 2 profiles exist, but that does not mean every panel/model combination has been hardware-tested.

Use **Raspberry Pi OS with desktop, 64-bit**, with Python 3.11 or newer, systemd, NetworkManager and working official-display drivers. Initial setup uses the desktop; appliance mode then boots only Cage and GTK. Keep Ethernet or SSH available as a recovery path.

Required system components are installed by `scripts/install-pi.sh`: Python/venv, PyGObject/GTK4/Cairo, Node.js/npm, Git, Inter fonts, Avahi tools, `wlr-randr`, `grim`, curl and OpenSSL. Appliance mode installs Cage. Python application code has no pip runtime dependencies; native GTK bindings come from the OS. Node dependencies are locked to specific official Roon API revisions and transitive versions.

## Architecture and repository

| Directory | Responsibility |
| --- | --- |
| `src/pi_bus_time_display/` | Python HTTP service package (legacy import name): configuration, schedules, optional LTA/Home, admin, release selection and Roon proxy |
| `roon-controller/` | Official Roon API integration, subscriptions, browse/search, queue, artwork, metadata and optional BluOS |
| `native-display/` | GTK4 touchscreen and local SVG assets |
| `scripts/` | Installation, tagged-release updates, appliance setup and privileged action broker |
| `systemd/` | Production service/path definitions |
| `tests/` | Python regression tests; controller tests live beside the JavaScript modules |
| `tools/` | Local-first verification, native screen rendering and development tools |
| `docs/ARCHITECTURE.md` | Runtime boundaries and audit/verification notes |

The Python service listens on port **8765**. The Node controller listens only on **127.0.0.1:8766**; web clients reach it through `/roon/` on the Python service. GTK talks to the local services directly. A path-activated privileged broker permits a fixed set of system actions; neither application has general sudo access.

Roon owns transport, zones, playback, queue and library/catalogue data. Optional bus/Home failures do not replace that integration. Beta augments the official API with an isolated worker for unsupported discovery data and explicitly requested whole-mix operations. Normal playback, queue subscriptions and album/track actions retain the official API; whole-mix controls use an unsupported experimental call and remain audio-unverified. No RoonMCP dependency is used or planned. [Discovery notes](docs/DISCOVERY.md) cover the pinned MIT client, unsupported-protocol risks, bounded caching and beta limitations.

## Fresh Raspberry Pi installation

Do not run these production commands on a development Mac.

1. Flash Raspberry Pi OS with desktop, 64-bit using Raspberry Pi Imager. Set a normal user, network, SSH and timezone. Connect the official display and verify touch works in the desktop.
2. From that normal user's terminal, clone a published tag. For the current release:

   ```sh
   git clone --branch v1.0.0 https://github.com/impala84/roon-deck.git roon-deck
   cd roon-deck
   sudo ./scripts/install-pi.sh
   ```

3. Configure `/etc/pi-home/config.toml` and `/etc/pi-home/secrets.env`. The installer prints a generated web-admin password once. Do not commit these files. New configuration is music-first; enable optional modules explicitly. Existing installations retain their saved settings.
4. If the Pi should also be a RAAT audio endpoint, run `sudo ./scripts/install-roon-bridge.sh`. This downloads Roon's official architecture-specific installer; Roon Bridge is separately distributed and not bundled in RoonDeck.
5. Enable appliance mode from the same normal user:

   ```sh
   sudo pi-bus-appliance-mode enable
   sudo reboot
   ```

6. In Roon, open **Settings → Extensions**, enable **RoonDeck**, then select the desired zone in RoonDeck. If you installed Roon Bridge, separately enable the Pi's RAAT output under Roon **Settings → Audio**.
7. Open `http://<pi-address>:8765/admin` on a trusted local network. Sign in with `admin` and the installer-generated password. Configure display profile/orientation under **Display → Screen hardware**. Touch Display 2 overlay changes require one reboot; select the exact panel rather than using an assumed rotation.

For a frozen v1.0 rebuild, use the `v1.0.0` tag, not an untagged `main` checkout. Back up the configuration/state listed below; Git alone cannot recreate private credentials, Roon authorisation or local display choices.

### Production files

| Path | Purpose |
| --- | --- |
| `/opt/pi-home/` | Git checkout, Node modules and `.venv` |
| `/etc/pi-home/config.toml` | Non-secret application configuration |
| `/etc/pi-home/secrets.env` | LTA, Home Assistant, OpenObserve and admin credentials |
| `/etc/pi-home/roon.env` | Optional Node environment overrides |
| `/etc/pi-home/display-user`, `display-profile`, `display-transform` | Saved native-session user, panel and orientation |
| `/var/lib/pi-home/` | Persistent display preferences, action queue, update status and Roon pairing state |

Use encrypted/off-device backups for `/etc/pi-home/` and `/var/lib/pi-home/`. These contain secrets and personal state. Do not put them in the public repository.

New repository, package and command names use `roon-deck`. Installed `pi-home`
paths and service aliases remain temporarily for updater, configuration and
Roon-pairing compatibility; see [the naming migration policy](docs/NAMING.md).

## Configuration

`config.example.toml` documents the application settings. Configuration persists across updates. Use the web admin to save settings; manual edits require `sudo systemctl restart pi-bus-time-display.service`.

Required for Roon: a reachable Roon Server on the local network and extension authorisation. `roon_zone_name` may be blank to follow the active zone. Do not expose ports 8765/8766 directly to the Internet. HTTP admin is intended for a trusted LAN. The backend trusts loopback requests for native control: any local reverse proxy must enforce its own authentication/access restrictions. HTTPS alone does not make that proxy safe. Prefer a restricted VPN for remote access.

Optional integrations:

- **Bus Times:** enable **Services → Bus → Show Bus Times**, choose an actual LTA five-digit stop code/service list, and set an LTA AccountKey. Disabling buses hides navigation, stops polling and prevents automatic bus-page selection. LTA outages retain last successful arrivals and mark them stale.
- **Home:** enable Home Assistant, supply its base URL/token and entity allow-list. Sensitive domains such as locks and alarms are deliberately rejected. Disabling Home hides its navigation.
- **BluOS:** enable it, discover or enter the player address, and choose visible inputs/names. Opening Now Playing is view-only; pressing Play explicitly reclaims the Roon source.
- **Logging:** optional OpenObserve connection. It is not required for music or bus/Home operation.

Secrets/environment variables belong in `secrets.env`, not TOML:

| Variable | Requirement |
| --- | --- |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_AUTH_ENABLED` | Web authentication; installer creates a unique password |
| `LTA_ACCOUNT_KEY` | Only for live Singapore buses |
| `HOME_ASSISTANT_TOKEN` | Only for Home Assistant |
| `OPENOBSERVE_PASSWORD` | Only for authenticated OpenObserve logging |

Node overrides in `roon.env`: `ROON_ZONE_NAME`, `CONFIG_PATH`, `PORT`. Keep the production port at 8766 because GTK/proxy routes expect it. Roon pairing is saved in `/var/lib/pi-home/roon/`, not an environment variable.

## Updates and release channels

Under **System → Software**, choose **Release Channel: Stable or Beta**, save, then check availability. The page shows installed version, selected channel, latest published version and whether an update exists.

- Stable excludes draft/prerelease releases and semantic prerelease tags.
- Beta includes published Stable and prerelease releases, selecting the highest semantic version.
- `v1.1.0-beta.10` is newer than `v1.1.0-beta.2`; `v1.1.0` supersedes both.
- Beta → Stable never silently downgrades. If the installed beta is newer than the latest Stable, it stays installed and reports that state until a newer Stable appears.
- Failed/offline release checks report **unavailable**, not **up to date**.

The new updater installs exact published GitHub release tags, not development `main`. Start it in Settings or with:

```sh
sudo pi-bus-update
```

It stashes local checkout changes for recovery, installs dependencies only when needed, retains private configuration, reapplies display settings and verifies service startup. A normal app update does not reboot the Pi. Never edit live application source as a substitute for configuration.

Pre-v1.0 updaters follow `main`; the first update to the baseline installs the channel-aware updater. Do not put Discover or experimental code on `main` before that transition. Downgrades/rollback require an explicit maintenance procedure and a compatible backup; automatic updates never perform them.

## Troubleshooting and recovery

Use **System → Diagnostics** and **Capture display** first. A captured native display shows actual GTK rendering; a desktop browser simulation does not.

```sh
systemctl status pi-bus-time-display.service pi-bus-roon-controller.service pi-bus-native.service
journalctl -u pi-bus-time-display.service -u pi-bus-roon-controller.service -u pi-bus-native.service -n 100 --no-pager
curl --fail http://127.0.0.1:8765/api/status
curl --fail http://127.0.0.1:8766/api/state
sudo systemctl restart pi-bus-time-display.service pi-bus-roon-controller.service
sudo systemctl restart pi-bus-native.service
```

Restarting the display does not restart Roon Server; Roon Bridge is independent. If the touchscreen is unusable, use SSH to restore the desktop:

```sh
sudo pi-bus-appliance-mode disable
sudo reboot
```

Rotation setup keeps backups of the boot command line and managed Touch Display 2 boot configuration. Do not apply a second manual input rotation on top of the saved device-tree configuration.

## Development (not production installation)

Use Python 3.11+, Node.js and npm. A browser simulation does not need GTK or an LTA key:

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
cp config.example.toml config.toml
cp .env.example .env
# Set a local admin password; optionally enable simulated bus display.
.venv/bin/pi-home --simulate --config config.toml --env .env
```

For the controller, in another terminal:

```sh
npm --prefix roon-controller ci
mkdir -p .state/roon
cd .state/roon
CONFIG_PATH=../../config.toml node ../../roon-controller/server.js
```

Authorise the development extension in Roon if testing against a real server. This is not an offline Roon simulation. Native GTK requires a supported Linux graphics/input environment; actual backlight/rotation/touch acceptance requires the Pi.

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
npm --prefix roon-controller test
bash -n scripts/install-pi.sh scripts/install-roon-bridge.sh scripts/pi-bus-update scripts/pi-bus-appliance-mode scripts/pi-bus-cage-launch
```

## Licence and next phase

RoonDeck's own code is [MIT](LICENSE). The official Roon Node libraries are Apache-2.0; their MIT/BSD-style transitive dependencies retain separate notices in installed packages. System packages have their own licences. Roon Bridge is proprietary and installed separately. See [architecture and audit notes](docs/ARCHITECTURE.md); this repository is not yet a distributable OS image.

[CHANGELOG.md](CHANGELOG.md) records releases. [ROADMAP.md](ROADMAP.md) defines the gated v1.1 Discover work and later public-appliance goals. No unsupported Roon protocol is part of the v1.0 baseline.
