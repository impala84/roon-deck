# RoonDeck roadmap

## v1.0 Stable baseline — first gate

The `v1.0.0` baseline includes repository cleanup, documented installation/recovery, published Stable/Beta channels and automated regression checks. At the user's request, publication proceeds without remote Pi access. A known-good Pi audit, clean hardware rebuild and physical acceptance remain outstanding and are not claimed as completed. No Discover or unsupported protocol work belongs in this release.

`1.0.x` is reserved for small fixes/refinements; `1.1.0` is the next meaningful feature release. Later meaningful features increment the minor version. Fundamental product/architecture changes warrant `2.0.0`.

## v1.1 Discover — separate branch after v1.0

Augment the official Roon API; do not replace it. Investigate Arthur Soares' reverse-engineered Roon client project, initially read-only and isolated. Do not integrate RoonMCP. Unsupported discovery failures must leave official playback, zones, queue and browse/search working.

Live research on `discover-v1.1` has proven all four read-only data sources, including current Daily Picks compatibility and nested mix metadata. See [the actual-server proof findings](docs/DISCOVERY.md). Sample albums/tracks resolve to official playback/queue menus without playing audio. Worker isolation, artwork/action delivery and native/web UI implementation remain; this is not a completed beta.

Before UI work, prove against the actual Roon Server that Daily Mixes, Daily Picks/equivalent recommendations, New Releases for You and recent listening/history are accessible. Document title, artist, album, artwork, descriptions/context, source/availability and playback references. Prove whether the existing official playback/queue integration can consume those references. Stop and report unavailable/unreliable data instead of building UI around assumptions.

Once proven:

- Bottom navigation: Now Playing | Discover | Bus Times | Home, respecting optional modules.
- Discover tabs: Recent | Browse | Daily Mixes | New Releases | Surprise.
- Move existing Browse and Surprise intact; keep Now Playing focused on the current listening experience.
- Daily Mixes is the umbrella for daily personalised recommendations, including Daily Picks.
- Keep clocks/status where they are. Preserve visual language, legibility and touch targets.
- Test five tabs at the real display resolution and on hardware; report a fit problem before changing navigation patterns.
- Prefer official playback/queue APIs for all actionable discovery content.

Release usable test builds as `v1.1.0-beta.1`, `v1.1.0-beta.2`, etc. Beta-channel hardware testing precedes promotion to Stable `v1.1.0`.

## After stable v1.1 — public appliance roadmap, not current scope

Maintain one codebase: personal installs can enable Bus Times/Home, while public installs are Roon-focused. Do not generalise Singapore buses into a global transport product.

Explore a Raspberry Pi OS-based image: download → flash with Raspberry Pi Imager → boot → touchscreen setup → use. Keep an advanced manual-install path. First-run setup could cover welcome, network and Roon discovery/authorisation. The supplied brief ended during this first-run section; remaining detail must be confirmed before that phase.

Before image distribution: audit all redistributed package licences/notices, supported hardware, recovery, credentials, security updates and reproducible image tooling. RoonDeck remains independent of Roon and does not redistribute proprietary Roon Bridge without permission.

## Retained reliability considerations

- Hardware-test additional Touch Display profiles; do not infer support from profiles alone.
- Improve backlight applied-state acknowledgements and test sleep/wake/brightness/update transitions on real hardware.
- Keep GTK mutation on its main thread; keep optional integrations/future protocol work isolated.
- Avoid unrelated large file/module refactors during the v1.0 freeze.
