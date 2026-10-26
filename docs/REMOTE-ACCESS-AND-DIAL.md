# 1.1.8 beta: Remote Access and Surface Dial hardware tests

This development series starts from published `v1.1.7-alpine`. Both optional
features are off for existing installations. The existing Beta updater channel
offers these prereleases; there is no additional release channel or branch to
select. Stable users remain on published stable releases.

The first beta implements the control and configuration paths. It does not
claim physical Bluetooth acceptance or successful remote RAAT audio. Haptics
and a cross-subnet discovery relay are not bundled. Keep the normal 1.1.7
installation and its existing Roon Bridge configuration intact while testing.

## Install and find Settings

1. Install the published 1.1.8 beta through Settings → Software → Beta.
2. In web Settings → System → Device & network, open **Network & Remote Access ·
   Bluetooth Accessories**. The touchscreen also has **Remote Access &
   Bluetooth** in its Settings scroll area.
3. Use the backend **Enable optional features** switches to enable WireGuard and/or Surface Dial support, then save. Their touchscreen controls appear only while enabled. Turning support off disconnects the VPN or stops Dial controls while retaining profiles/pairing. Roon Bridge and Netdata controls likewise appear on the touchscreen only while enabled in the backend.
4. Choose **Install optional support** once and wait for the progress message to finish. Beta.2 keeps the page responsive during downloads, installs packages only for the enabled features and starts the Bluetooth service after installation. The Bluetooth service/adapter status is shown separately; a running service without an adapter needs a Pi radio/firmware check before pairing. This installs Alpine's BlueZ,
   Broadcom firmware and WireGuard diagnostic tool, and the disabled Dial
   service. It does not pair anything, enable a VPN, reinstall Roon Bridge,
   change audio settings or change the Mac's network.

The touchscreen cannot enable feature support or install its packages; use authenticated web Settings. Existing installations receive new packages only through this explicit action;
the normal source updater does not install them automatically. The Dial service
is registered on explicit enable. If a Pi has no Bluetooth controller after
starting a scan, inspect the Pi radio, kernel/firmware and any UART Bluetooth
initialisation required by that model before continuing. Do not weaken BlueZ
security or grant world-writable input access as a workaround.

## Test the Surface Dial on the normal home LAN first

1. Put the Dial in pairing mode. Scan, select it and Pair. Check paired,
   connected and battery status (battery is optional).
2. In Roon, select a variable-volume output. Start with low volume. Select
   **Follow the selected Roon zone**, or explicitly select the Pi's Roon Bridge
   output, and save enabled Roon controls. Pairing/enabling never sets volume.
3. Turn slowly in both directions. Check the physical display, Roon and the
   actual DAC volume agree. Fine/Normal/Fast change sensitivity. Each command
   is capped at four numeric volume units or 2 dB, respects the output's step,
   and waits for the existing Roon subscription to confirm the result.
4. Check single press = play/pause, double press = next, long press = mute.
   Single press waits 320 ms to distinguish a double press; long press uses
   750 ms. Confirm no extra pause is triggered by a double or long press.
5. Set a Dial ceiling in the output's Roon units and test it at low volume.
   The ceiling applies to this Dial, not to other Roon controllers. Above the
   ceiling, upward rotation does nothing and downward rotation remains gradual.
6. Select a fixed-volume zone and an unavailable zone. No Pi mixer should
   change. Refresh Settings to read the specific Roon control error.
7. Change volume from another Roon controller, then rotate again. Check the
   Dial starts from the new value, not a stale value. Change selected zones
   while rotating: no pending movements should replay in another room.
8. Remove/reinsert the Dial battery, let it sleep/wake and reboot the Pi.
   Verify pairing/settings persist, BlueZ reconnects, and movement never
   replays after a disconnection. Forget should disable the saved Dial controls.

The reader uses standard Linux input events, matches Microsoft vendor/product
`045e:091b` and the selected Bluetooth address, and ignores events older than
500 ms. Actual device identity, rotation/button events, access permissions and
firmware must be confirmed on the physical Pi. `/var/lib/pi-home/dial-status.json`
reports bounded control errors without music metadata.

## Test WireGuard from the separate home VLAN

Use local touchscreen access throughout the first routing trial.

1. Export a separate UniFi WireGuard client profile for this Pi. Import the
   `.conf` in web Settings. This beta accepts one Interface and one Peer;
   executable hooks, custom Table/SaveConfig directives and DNS search domains
   are rejected. Profile contents and private keys are never returned to Settings.
2. Begin with Full Tunnel and the profile's default-route AllowedIPs. An IPv4
   profile tunnels IPv4; IPv6 also needs an IPv6 tunnel address and `::/0`.
   This beta does not create missing IPv6 routes or an IPv6 kill switch.
3. Add the home gateway and Roon Server addresses for diagnostics. Leave
   connect-on-boot off for the first trial. Import does not connect.
4. Connect. Confirm from the touchscreen and from the original local browser
   URL that local management still works. Check the VPN address, a fresh
   handshake and transfer counters. Choose **Keep this connection** within
   90 seconds only if local access works. Otherwise let it roll back.
5. Explicitly test the timeout once. An independent root watchdog must disable
   the owned VPN profile and disconnect it even if the web page closes.
   Reboot during an unconfirmed trial must leave the profile off.
6. Run diagnostics: gateway/server ping, existing Roon Bridge service, and
   RoonDeck's controller connection. Ping may be blocked by a host firewall;
   it is not an audio acceptance test.
7. In the home Roon Server, check whether the Pi's Roon Bridge appears in Audio.
   Confirm actual playback through its existing DAC, without reinstalling Bridge
   or changing ALSA, resampling or buffering configuration.
8. If the controller or Bridge is missing, record which one, tunnel/return
   routes, VLAN/home subnets and handshake status. This is the discovery gate:
   investigate a narrowly scoped SOOD relay with a home-side helper and return
   routing before adding a larger networking overlay. mDNS reflection alone
   and a working Mac Roon Desktop connection are not proof of Bridge discovery.
9. Only after sustained playback works, test network loss/recovery, Ethernet
   versus Wi-Fi, Pi/server reboot, full versus split routing and the Dial over
   the tunnel. Split subnets must be explicit and may not contain default routes.
10. Reimport while disconnected with connect-on-boot enabled, connect and
    confirm, then test a cold boot. Disconnect turns off automatic connection.

Recovery from the touchscreen: **Disconnect Remote Access**. Local SSH fallback:
`sudo nmcli connection modify roondeck-remote connection.autoconnect no`, then
`sudo nmcli connection down roondeck-remote`. Do not delete unrelated profiles.

## Persistence and implementation map

| Responsibility | Location |
|---|---|
| Validated system operations, WG parsing/keyfile generation | `src/pi_bus_time_display/remote_access.py` via the existing setup helper's UID-restricted Unix socket |
| Authenticated HTTP API | `/api/admin/accessories` in `server.py` |
| Protected WireGuard keys | `/etc/NetworkManager/system-connections/roondeck-remote.nmconnection`, root-only |
| Backend enable flags and trial/settings metadata | `/var/lib/roondeck-remote/`, root-only; rollback protected by a process lock |
| Independent rollback | `appliance/alpine/remote_rollback.py` |
| Bluetooth pairing | BlueZ; persistent records in its standard system storage |
| Non-secret Dial settings | `/var/lib/pi-home/accessories.json` |
| Optional input service | `roondeck-dial`, running as the existing unprivileged appliance user with input-group access |
| Safe Roon commands | `roon-controller/accessory-control.js`, using the existing transport connection |
| Native/web settings | `native-display/accessories_page.py`, `static/accessories.html/js/css` |

No VPN keys belong in `config.toml`, the application tree, logs or HTTP status.
Normal source updates preserve system profiles and saved settings. The updater
restarts an enabled Dial service to avoid leaving it on old application code.
Both features must also be tested disabled, with the normal touchscreen,
library, existing audio and custom Home colours unchanged.

## Local verification

`tools/check fast` includes profile rejection, secret redaction, file permissions,
rollback, authentication, gesture timing and Roon volume safety tests. The
Settings screen matrix renders both the existing Settings and the new accessory
page using `tools/viewports.json`. `tools/check candidate` also parses generated
full/split IPv4/IPv6 profiles with the appliance's real NetworkManager in offline
mode. These checks do not replace the physical tests above.
