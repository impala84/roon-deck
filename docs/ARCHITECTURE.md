# RoonDeck runtime architecture

This document records the runtime boundaries for the v1.0 Stable baseline. It is
intentionally brief: each component should have one clear authority and avoid
duplicating state owned elsewhere.

## Components

| Component | Authority | Update model |
| --- | --- | --- |
| Python service (`:8765`) | configuration, bus data, Home Assistant allow-list, schedule policy, web administration | LTA at the configured interval; Home Assistant every 3 seconds |
| Roon/BluOS controller (`127.0.0.1:8766`) | Roon subscription state, queue, metadata, artwork cache and amplifier state | Roon subscriptions and BluOS long polling |
| Native GTK display | presentation, touch activity and local view selection | compact state refresh every 2 seconds; network and image work off the GTK thread |
| Privileged action broker | backlight, update, systemd services, display setup and Pi LEDs | systemd path activation; no resident privileged process |

The browser dashboard reaches Roon through the Python reverse proxy. The Node
controller remains loopback-only. The GTK display talks to both loopback
services directly.

## Display state

The persisted display mode is one of `auto`, `bus`, `roon`, `home` or `sleep`.
The Python service resolves it to a target using the schedule, recent Roon
playback and the temporary wake deadline. A manual mode expires at the next
schedule-period boundary. Explicit `sleep` is cleared on a backend restart so
an interrupted update cannot strand the panel black.

Daytime inactivity is intentionally local to GTK because it is driven by real
touch activity. Scheduled sleep remains authoritative. A scheduled wake resets
the inactivity clock before the next inactivity decision.

Backlight changes are privileged actions. Each action is stored as its own
atomic queue entry and consumed in filename order. The old single request file
is accepted only for upgrade compatibility.

## Roon and BluOS

Roon owns Now Playing, Queue and artwork. Queue subscription begins when the
zone is established and stays in memory. BluOS owns physical input selection,
amplifier volume and mute. Opening Now Playing or Queue is view-only; selecting
a physical source changes the amplifier. Pressing Play is the explicit action
that may reclaim the Roon source.

## Threading rule

The v1.1 Beta adds `DiscoveryManager` beside (not inside) the official controller. It locates the authorised Core via the existing SOOD announcements, spawns a short-lived protocol worker and supplies cached normalised data to web/GTK. Reads are separate from explicitly requested experimental whole-mix actions; action workers verify exact zone/mix identities and make one native PlayMix call, without per-track mutation loops or automatic retries. The parent never imports the unsupported client. Discovery errors remain local to Discover; they do not replace official Roon transport/queue subscriptions. See [Discovery notes](DISCOVERY.md) for limits and required hardware/audio acceptance. Vendored MIT code has its retained notice under `roon-controller/vendor/roon-research/`.

GTK construction and mutation run only on the GTK main thread. HTTP, image
downloads and raw input reads run in workers and return through `GLib.idle_add`.
The Python web server uses one thread per request. Privileged actions never run
inside either application service.

## Baseline audit — 4 October 2026

Status: v1.0.0 is released at the user's explicit request with local verification.
Running-Pi inspection, fresh-install reproducibility and physical acceptance
remain unverified; no remote installation or restart was performed.

- Removed the unused Chromium kiosk launcher, desktop entry, touch-controls
  extension and iframe display shell. No installed service/startup script
  referenced them; production uses native GTK/Cage. Removed the unreferenced
  icon study and consolidated obsolete stabilization/planning documentation.
- Retained active web dashboards, simulation, fixed-action broker, Roon Bridge
  helper, orientation utilities and existing compatibility configuration.
  Files were not removed merely because their names still mention Pi Bus.
- Python has no pip runtime dependencies. All five direct Node dependencies
  are imported by the controller and pinned to RoonLabs revisions; keep them.
  Locked transitive dependencies: `node-uuid` (MIT) and `ws` (MIT). Official
  Roon modules: Apache-2.0. Installed package licence files remain intact.
  RoonDeck's MIT licence covers its own code, not those dependencies.
  `npm audit --omit=dev` reported zero known vulnerabilities on 4 October 2026;
  that report is point-in-time and does not guarantee all dependencies are safe.
- GTK, Cairo, Cage, fonts, Avahi and other OS dependencies retain distribution
  licences. Roon Bridge is downloaded separately, not copied into this repo.
  Producing an OS image will require a separate redistribution/licence audit.
- Local env/config, build output, pairing state and Node modules are ignored.
  No tracked live `.env`, `config.toml` or Roon pairing `config.json` appeared
  in the Git filename-history check. That is not a substitute for a dedicated
  secret scanner across every historical blob before public distribution.
- Generic new-install configuration disables buses/Home/BluOS; saved personal
  configuration remains outside the repository and is not migrated/reset.
- Installer exports tracked source rather than copying developer secrets,
  ignored dependencies or host-specific virtualenvs. The updater now resolves
  published GitHub release metadata and checks out an exact release tag.

### Verification gates still required

Inspect the known-good Pi's model, OS, package versions, effective units,
display profile/rotation/overlay and non-secret settings. Verify fresh-install
steps against them and record differences. Then test real Roon pairing,
playback/queue/search, GTK touch scroll, sleep/wake, TV/records sleep, optional
modules, capture, saved settings and update/recovery. Local logic/browser
tests must not be presented as proof of hardware behaviour.

Backlight applied-state acknowledgement, mutable-state protection and larger
handler/display module splits remain known future reliability considerations,
not reasons to undertake unrelated architecture changes during this freeze.
