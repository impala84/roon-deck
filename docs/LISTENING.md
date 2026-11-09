# Stream Deck + and listening controls

The dashboard API owns listening commands. The native Home page, web Home page,
and optional USB Stream Deck + worker share that API. The worker starts with the
dashboard process, retries missing/unplugged devices, and serializes USB events.
Elgato desktop software and the Mac are not required.

## Status and limits

- **KEF LSX:** controlled through **Roon** and **Home Assistant infrared** only.
  The speaker's own network control port (50001) is not used. Roon handles
  wake, standby, volume (0-100) and mute. A Broadlink remote in Home Assistant
  switches the input (Wi-Fi, AUX, optical, Bluetooth) with KEF's published
  infrared codes.
- Roon starts and controls playback on the KEF zone as usual (play, pause,
  previous, next).
- Infrared has no acknowledgement: RoonDeck says an input was **sent** and never
  claims to know which input is selected.
- Stream Deck +: buttons, encoder turns/presses, short strip taps, custom
  artwork and state feedback are implemented using python-elgato-streamdeck.
- Listening modes and the Topping E50 II controls were removed in beta.134.

## KEF control (beta.134)

Under **Controls -> Listening & KEF**, enable the speaker, select the KEF under
**KEF output in Roon** (for this installation, **Study**, the LSX at
`10.12.0.125`; not the Pi's Roon Bridge output) and set **Broadlink input
remote** to the Home Assistant remote entity in the room (here
`remote.wi_fi_universal_remote`, an RM4 Mini). Home Assistant must be enabled.

Roon commands wait for Roon's readback before reporting success. Waking the
speaker does not start music. The infrared path needs a clear line to the LSX.
**Input preset:** set the input on the **KEF input** tile itself in Settings → Home → Layout (with an optional second input to toggle between). One tap switches to it; a speaker in standby is woken through Roon first, because infrared is ignored in standby. The Broadlink remote is picked under Listening & KEF from a list found in Home Assistant, with manual entry as a fallback.

Volume over infrared is not implemented; add it only after its codes have been
captured and checked.

References: <https://assets.kef.com/pdf_doc/LSX/LSX-IRcode-INT.pdf> and
<https://www.home-assistant.io/integrations/broadlink/#sending-commands>.

## Enable on a Pi

Use web **Settings → Controls → Listening & Stream Deck +** to save the KEF
Roon output, infrared remote, maximum volume and button/dial mappings. Both support
switches are off by default. Saved controls load automatically, and the page
shows the connection state.

For operator-managed configuration, copy `listening.example.json` to `listening.json` in the dashboard's existing
`--state-dir` (normally `/var/lib/pi-home` on Alpine). Keep it owned by the
dashboard account. Set `enabled` to true. Settings are reread during polling;
Stream Deck bindings reconnect automatically after settings change. Set
`streamdeck_enabled` to true only after installing the optional dependencies:

On the Alpine appliance, an operator installs USB support over SSH as root:

```sh
apk add --no-cache libusb hidapi py3-pillow py3-pip
python3 -m pip install --no-deps \
  --target "$(python3 -c 'import sysconfig; print(sysconfig.get_path("purelib"))')" \
  'streamdeck>=0.9.5,<1'
install -d /etc/udev/rules.d
cat > /etc/udev/rules.d/70-roondeck-streamdeck.rules <<'RULE'
SUBSYSTEM=="usb", ATTR{idVendor}=="0fd9", GROUP="morningbus", MODE="0660"
RULE
udevadm control --reload-rules
```

Then unplug/replug the Deck and enable it in web Settings. The API continues
to run as `morningbus`; the rule grants its group access only to Elgato USB
devices. The library is installed in system site-packages because the source
updater recreates the application virtual environment. Existing Alpine venvs
use `--system-site-packages`, so this survives source updates. A future OS
Python major-version upgrade will require reinstalling the library.

Alpine container checks confirm imports, HIDAPI startup and USB enumeration
with these packages; physical USB access and reconnect still need hardware
acceptance. Package manager and group names differ on Debian installations.

Maximum volume is operator configurable (default 50%).

## Bindings and artwork

Eight `buttons` and four `dials` use these actions:

| Action | Value / option |
| --- | --- |
| `power` | Boolean `value` |
| `input` | `wifi`, `aux`, `optical`, `bluetooth` |
| `volume` / `volume_delta` | Integer `value`; dials use `step` |
| `mute` | Toggle KEF mute |
| `previous`, `playpause`, `next` | Existing selected Roon zone |
| `home_scene` | A configured Home Assistant scene `entity_id` |
| `home_toggle` | An allowed Home Assistant `entity_id` |
| `home_level` | Allowed dimmable light/fan `entity_id`; dial `step` |

Dial `press` is another binding and is also invoked by a short strip tap.
Use buttons to select rooms through configured home devices; automatic room
pages are not implemented. Scene buttons can activate only
scenes explicitly allowed in Home Assistant display settings.
Add `"image": "music.png"` to a button and place that image in
`STATE_DIR/deck-art/music.png`. Images are resized to 120×120 and labelled;
artwork paths cannot escape that directory. The strip shows confirmed KEF
volume/mute or home level, plus bounded command errors. Home buttons reflect
Home Assistant state. This is not a general Elgato Marketplace plugin host.

## API

`GET /api/listening/status` returns cached polled status (no hardware access
in the request). `POST /api/listening/command` accepts JSON
`{"action":"volume_delta","value":-2}` or `{"action":"input","value":"aux"}`.
It uses existing dashboard authentication. Forwarded loopback writes are
rejected. Native/USB callers use loopback; trusted LAN browsers log in.
Network errors return 502 and unsupported/disabled commands return 400.

## Verification for 1.2.0 beta

The feature is ported from the earlier local prototype onto published stable
1.1.8. Automated tests verify settings persistence, local command boundaries,
KEF framing and error handling. The native listening smoke renders enabled and
offline states and checks button dispatch at every viewport from
`tools/viewports.json`. Web settings save/reload is checked using a local
simulated instance. These checks do not establish physical device acceptance.

The full candidate command reached the existing `discover_smoke.py` alignment
assertion after updater, accessory, network, setup and icon checks passed. The
same assertion fails against untouched 1.1.8 in the same container. The current
release workflow treats simulated native layout failures as advisory. The
full native review matrix and the new strict listening smoke pass; this does
not represent a completely green candidate-command exit.

## Home tiles

In Settings → Home → Layout → Add tiles → RoonDeck, add **KEF speaker** for combined power, input and volume, or add **KEF power**, **KEF input** and **KEF volume** separately. Both styles can be used together. They use the same grid, placement, sizes, colours, labels and dashboard pages as the other Home tiles. There is no separate control strip above the grid. Enable and configure the speaker under Listening first. Input selections send commands; infrared input feedback reports that it was sent, because the remote cannot confirm the speaker input.
