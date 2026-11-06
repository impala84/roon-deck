# Stream Deck + and listening controls

The dashboard API owns listening commands. The native Home page, web Home page,
and optional USB Stream Deck + worker share that API. The worker starts with the
dashboard process, retries missing/unplugged devices, and serializes USB events.
Elgato desktop software and the Mac are not required.

## Status and limits

- Original KEF LSX: direct local TCP control on port 50001. Power, source,
  volume, relative volume and mute are implemented, with status readback.
  Hardware acceptance is still required. Protocol references:
  <https://www.home-assistant.io/integrations/kef/> and
  <https://github.com/kraih/kefctl>.
- Stream Deck +: buttons, encoder turns/presses, short strip taps, custom
  artwork and state feedback are implemented using python-elgato-streamdeck.
  Physical USB acceptance, hot unplugging and permissions must be tested on Pi.
- Topping E50 II: **no control commands are implemented or guessed**. A mode
  requiring a Topping input is rejected before KEF power/input/volume changes.
  USB remains connected to the Mac; Pi audio goes over its S/PDIF HAT.
- This release does not claim Bluetooth control during USB/S/PDIF playback.
  BLE discovery is not proof of successful input switching or Classic/SPP
  support. No Bluetooth audio connection is made by the worker.

## Enable on a Pi

Use web **Settings → Controls → Listening & Stream Deck +** to save the KEF
address, maximum volume, listening modes and button/dial mappings. Both support
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
The separate Topping diagnostic also needs the optional `bleak` dependency,
which can be installed in a temporary diagnostic virtual environment.

The example KEF address is the user's `10.12.0.125`. AUX is an **example**, not
a confirmed cable connection. Choose the actual KEF input. Choose `coaxial` or
`optical` for the actual HAT cable. Starting volumes and maximum volume are
operator configurable; default maximum is 50%. Each KEF source has its own
stored volume. Source changes can briefly restore its previous level.

Modes without `topping_input` can control the KEFs alone. Do not remove that
field just to bypass a disabled mode: it would stop configuring the DAC.
The two supplied end-to-end modes deliberately remain unavailable until a
Topping driver has been validated.

## Bindings and artwork

Eight `buttons` and four `dials` use these actions:

| Action | Value / option |
| --- | --- |
| `mode` | Mode ID |
| `power` | Boolean `value` |
| `input` | `wifi`, `aux`, `optical`, `bluetooth` |
| `volume` / `volume_delta` | Integer `value`; dials use `step` |
| `mute` | Toggle KEF mute |
| `previous`, `playpause`, `next` | Existing selected Roon zone |
| `home_scene` | A configured Home Assistant scene `entity_id` |
| `home_toggle` | An allowed Home Assistant `entity_id` |
| `home_level` | Allowed dimmable light/fan `entity_id`; dial `step` |

Dial `press` is another binding and is also invoked by a short strip tap.
Use buttons to select rooms through configured home devices or listening
modes; automatic room pages are not implemented. Scene buttons can activate only
scenes explicitly allowed in Home Assistant display settings.
Add `"image": "music.png"` to a button and place that image in
`STATE_DIR/deck-art/music.png`. Images are resized to 120×120 and labelled;
artwork paths cannot escape that directory. The strip shows confirmed KEF
volume/mute or home level, plus bounded command errors. Home buttons reflect
Home Assistant state. This is not a general Elgato Marketplace plugin host.

## Topping investigation

Official app description confirms Bluetooth input/output switching:
<https://play.google.com/store/apps/details?id=com.topping.home>.
Home Web uses USB/HID and E50 II requires firmware 1.56 or newer:
<https://www.toppingaudio.com/download/topping-home-web-web-control-center>.
Neither confirms an independently usable public Bluetooth protocol.

With Bluetooth enabled on the DAC and the Mac USB connection untouched, run:

```sh
.venv/bin/python tools/topping_probe.py --input coaxial
.venv/bin/python tools/topping_probe.py --input coaxial --address DEVICE_ADDRESS
```

Repeat with USB selected and while audio plays. The tool only scans and lists
GATT services/characteristics; it never writes characteristic values or pairs.
Then use Topping Home to switch USB → S/PDIF → USB and test reconnecting when
the app starts on each input, including with the Mac off. Capture app traffic
on an Android test phone if needed to identify transport, service UUIDs,
command frames and acknowledgements. Confirm direct input selection, readback,
reconnect behaviour and standby before implementing a driver. Do not replay
unidentified firmware/update writes.

## API

`GET /api/listening/status` returns cached polled status (no hardware access
in the request). `POST /api/listening/command` accepts JSON
`{"action":"volume_delta","value":-2}` or `{"action":"mode","value":"pi"}`.
It uses existing dashboard authentication. Forwarded loopback writes are
rejected. Native/USB callers use loopback; trusted LAN browsers log in.
Network errors return 502 and unsupported/disabled commands return 400.
Mode completion is recorded only after KEF state confirms the target values.

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
