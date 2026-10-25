# v1.1 Discover beta — 4 October 2026

Development branch: `discover-v1.1`. Production `main` and `v1.0.0` remain unchanged.
This branch contains the separately published RoonDeck 1.1.0 Alpine release, not the Raspberry Pi OS distribution. Native Daily is a single vertically continuous feed: Mixes render first and For You follows when ready, while each roomy row is an arrow-free kinetic horizontal swipe track whose inner viewport is tested at the physical display edge. Recommendation reasons are compact all-caps section headings; the source album then appears as the first normal card in the row using the same purple duotone treatment as mixes. Recent and New Releases use independently tuned four-column sizes. Every complete card is enclosed in a hard fixed-width viewport, so sparse results and even exceptionally long album names cannot resize a column or move neighbouring artwork. Release details return through a dedicated Back rail instead of displaying Browse/Search navigation. Horizontal artwork is loaded only as its card approaches the viewport, reducing network/decode work during a swipe. Now Playing installs its local record-cover placeholder before asynchronous artwork arrives so its transport geometry cannot collapse. Surprise Me clears stale Browse structure before loading. Touchscreen discovery requests no longer wait behind the general device poll, and leaving Daily invalidates its obsolete queued private-API work. Recent history, added albums, Daily groups and releases request bounded previews rather than complete private Roon graphs. Genre tiles use bundled symbolic SVGs instead of font glyphs. Diagnostics renders its image from the live GTK widget tree, including artwork, rather than relying on compositor screencopy during direct scan-out. Regression coverage includes the production asset handler and a real Alpine GTK/Xvfb Discover smoke test with strict card-width and inner-row edge-allocation assertions.

## Starting point and isolation

### Current portrait layout

Backend **Display → Appearance → Portrait Discover grid** selects 2 or 3 columns for Recent, Daily and New Releases. Two columns is the default. Daily's Mixes and For You tabs switch between separate vertically scrolling grids in portrait; landscape retains the continuous feed and horizontal swipe tracks described above. The preference persists in `portrait_discovery_columns` and takes effect on the touchscreen's next settings refresh without rebooting.

Beta.7 is touchscreen-focused; web layout remains beta.6. Native Recent uses a Browse-style Added/Listened rail, and the renamed Dailies tab uses Mixes/Recommendations. Both use compact Browse-derived grids (four columns at 1280px, covers capped at 172px). Mix detail uses playlist-style rows with 84px artwork; whole-mix actions stay at the top of the right pane. Back stays at bottom left outside that pane, including when opening official album/track actions from Discover. Loading belongs to the right content pane and does not replace the left navigation. New Releases retains its full-width grid; Surprise Me remains centred. Verification: 128 Python and 91 Node tests, including native widget-construction and navigation tests. No real GTK allocation, physical touchscreen test, remote installation or playback occurred during this update.

Inspected [Arthur Soares' MIT-licensed research client](https://github.com/arthursoares/roon-api-reverse-engineering), pinned research revision `8b67208f640e760f3b18431140e17469a059e90c`. Its TypeScript build and 145 upstream tests passed locally. Generated method wrappers are not evidence of live compatibility.

The beta bundles only the client's protocol facade and history exporter in `roon-controller/vendor/roon-research/sdk.cjs`, with its MIT notice alongside it. The official controller never imports this bundle: a short-lived child worker performs one discovery read or explicit whole-mix operation, closes its socket and exits. The parent imposes a 128 MiB heap ceiling and 20-second deadline, serialises/coalesces reads, caches successful results for five minutes and failures for one minute, and clears cached personal discovery content on unpairing. History uses upstream retain/release/dispose. Longer-running server-resource validation is still pending. No RoonMCP integration is involved.

Local official SOOD discovery located the user's actual Roon Server without SSH. A first private handshake using UUID text byte order was rejected; .NET GUID mixed-endian conversion succeeded. The root object graph and active profile were readable. Do not hard-code the user's server address, broker/profile IDs or listening history in the public repository.

## Actual-server findings

| Area | Live result | Metadata and remaining gap |
| --- | --- | --- |
| TIDAL Daily Mixes | Received ten playlist references; inspected first five | Names such as My Daily Discovery/My Mix, opaque playlist IDs, source and availability. Artwork has HTTPS TIDAL URLs. These are TIDAL mixes, not Roon mixes; signed artwork URLs must not be committed or logged by production. |
| Roon personalised mixes | Received six; normalised first five and one detail/track-list call | Inline performer descriptions, five artist touchstones per mix, avatar/photo artwork, opaque mix IDs. The first mix has 22 track groups; five sampled tracks have title, artist, album, source, internal IDs and artwork. Initial inspection incorrectly omitted nested descriptions and image URL fields; corrected decoding recovered them. |
| Daily Picks | Old generated call returns `MissingMethod`; current call repeatedly succeeds | Read the installed `Roon.Broker.Api.dll` metadata without launching or altering Roon. Current signature uses `(System.Sooid, DailyPicksParameters, callback)` with LocalTime, OverrideCache, RecentlyAddedOnly, NewReleasesOnly fields. Retrieved five personalised groups with 30 albums per group, seed album, reason (`recent`, `added`, `all_time`), category and generated date. Normalised five albums per group with artwork and artist. |
| New Releases for You | Received a collection advertising 180 entries; inspected first five | Album title, performer credit, Roon album/release IDs, source and artwork image IDs. Some contextual extras are not yet normalised. Numeric sources remain uninterpreted until their upstream enum mapping is verified. |
| Recent listening | Received a bounded history preview | Timestamp, track, album, artist, completion percentage and Roon track reference. The beta hydrates unique album artwork from the same fresh object graph; all 20 preview images loaded in the local browser. Missing art remains a neutral placeholder. |

These numbers reflect one server at one point in time, not a guarantee across Roon versions/accounts. Partial methods returning data do not establish reliable end-to-end discovery.

## Official API bridge

A real New Releases album was searched by exact title in a separate official browse session. The matching title/artist returned an official artwork key and browse item key. Opening it produced its track list and Play Album action without starting audio. Thus an exact title/artist search bridge is feasible for this sample; opaque internal IDs are **not** interchangeable with official `item_key`/`image_key` values.

Playback and queue actions were not executed. Atomic whole-mix playback and audio-confirmed play/queue remain unverified. Exact title/artist/category matching refuses ambiguous editions and leaves manual selection to the user. Never automatically play the first fuzzy search hit or reuse an expired session key.

Further live bridge checks resolved an exact Daily Pick album into its official track list and Play Album entry. An exact Recent track and an exact track from the Roon mix resolved through `action_list` previews into official Play Now, Add Next, Queue and Start Radio menus. None of those actions was selected. This establishes metadata-to-official-action resolution for album/track samples, not audio-confirmed playback or an atomic whole-mix queue. Never pretend a private mix ID is an official playlist key.

Beta.4 adds explicit whole-mix buttons via the unsupported native Transport.PlayMix operation, not a loop of individual track mutations. Its Now=0 and Queue=4 enum values were checked against the installed Roon assembly; the pinned generated API supplies the signature. A read-only preflight verified an exact 18-byte ZoneId match to the selected official zone, GetMix and exact MixId matching on the real server. No PlayMix call was sent during development. Success requires positive ItemCount feedback without DidLimitItemCount; failures/timeouts instruct the user to inspect the Roon queue before retrying. Requests are serialised against discovery reads and the last 64 nonce receipts (including uncertain failures) are retained in memory; these are not durable across controller restarts. Neither GET polling nor opening a mix starts playback. This is an explicitly requested private-protocol write path, not a read-only integration, and requires live audio/queue acceptance before stable release.

## Current gate

The four-source **read-only data proof passed**, including repeated current Daily Picks calls. A decoder omission and actual signature drift were diagnosed and corrected rather than removing those features. Worker isolation, caching/timeouts, local registered-artwork delivery, exact-match official action resolution and web/native Discover screens are implemented. Browser verification with live read-only data passed at 1280×720 and 390×844, including Recent artwork, mix previews and new-release artwork, with no detected JavaScript errors. Automated checks: 117 Python and 72 Node. These do not establish physical GTK acceptance or audio-confirmed playback.

Daily Mix artist portraits use black/purple duotone only in the Roon theme. Fresh Mint retains full-colour portraits; album covers remain full colour in both themes. Web rendering applies grayscale/multiply compositing, while native GTK uses a luminance colour matrix. Actual native rendering still requires touchscreen acceptance.

The five tabs are Recent | Browse | Daily Mixes | New Releases | Surprise Me. Phones use one row of Recent | Browse | Mixes | New | Surprise Me beside the cog, with 44-pixel-high targets; the dashboard label is Playing. Native landscape uses existing 18-pixel/54-pixel navigation styles. Browse and Surprise Me retain their official API behaviour. Successful content caches are bounded to 24 sections/mixes, artwork registrations to 256. Recent/New show the first 20 selections; Daily first shows five mixes, with five groups of five picks fetched only via More Recommendations. Mix detail shows its bounded track preview directly below experimental Play/Queue This Mix controls. Automated beta.6 checks: 122 Python and 91 Node; physical GTK and audio acceptance remain pending.

Beta.6 removes fixed read-only connection/graph sleeps in favour of bounded readiness polling (playback worker settling is unchanged). A per-client latest-page interest skips obsolete queued reads, retains other clients' work, and does not interrupt already-running requests or mix actions. Native artwork loads within the viewport plus a 160px margin, matching the web's lazy image approach. Live reader timings in one run: Mixes 506ms, Added 418ms, Picks 702ms, Recent 679ms, New Releases 2049ms. These are not a benchmark or promised UI latency. New Releases' API has no offset/limit: bounding the displayed cards and lazy artwork does not make that response server-paginated. Added's VirtualAlbumQuery is genuinely paged; it uses installed API enum metadata ImportDate=1/Descending=2 and harvests only fresh ordered VirtualQueryElement<AlbumLite> entries from its single retained page, not incidental AlbumLite graph objects. Unsupported-protocol compatibility must still be accepted on future Core versions.

The user explicitly requested continuing the full Discover integration. Do not narrow it to Recent/New Releases. Physical five-tab testing and Beta acceptance remain separate gates, not replaced by a local browser fixture. Do not publish stable v1.1 before those gates are satisfied.

## Reproduce the manual proof

Use a Roon Server you own on a trusted LAN. This unsupported protocol can affect server resources even when calls are read-only. Do not schedule the spike or run an automatic retry loop.

```sh
# In the RoonDeck development checkout:
npm --prefix roon-controller ci --omit=dev --no-audit --no-fund
node tools/find-roon-core.cjs
node --test tools/discovery-wire.test.cjs

# Separate research checkout (not production /opt):
git clone https://github.com/arthursoares/roon-api-reverse-engineering.git roon-research
git -C roon-research checkout 8b67208f640e760f3b18431140e17469a059e90c
npm --prefix roon-research/roon-internal-api ci --ignore-scripts --no-audit --no-fund
npm --prefix roon-research/roon-internal-api run build
npm --prefix roon-research/roon-internal-api test -- --runInBand

# Substitute your own discovered values and absolute research dist path:
ROON_HOST='<your-server>' ROON_SERVER_BROKER_ID='<wire-order-32-hex>' \
ROON_RESEARCH_CLIENT='/absolute/path/roon-research/roon-internal-api/dist' \
node --max-old-space-size=256 tools/discovery-spike.cjs
```

Exit 3 means the calls completed but the requested data gate remains incomplete. Exit 2 is the watchdog limit; other nonzero exits indicate setup/connection failure. `uiGatePassed` and `playbackVerified` remain false. Output can contain personal listening metadata: inspect locally and do not commit it. No raw object graph, credentials, pairing state or captured server data is checked in.

The helper code is original RoonDeck code under its existing MIT licence. The pinned upstream bundle retains Arthur Soares' MIT notice in `roon-controller/vendor/roon-research/LICENSE`. Rebuild it from the pinned research checkout's compiled `dist` using:

```sh
npm exec --yes --package=esbuild@0.25.5 -- esbuild tools/discovery-sdk-entry.cjs \
  --bundle --platform=node --target=node20 --minify \
  --alias:pi-home-roon-research=/absolute/path/roon-research/roon-internal-api/dist \
  --outfile=roon-controller/vendor/roon-research/sdk.cjs
```

No extra npm runtime dependency, Roon credentials, personal host address or captured history is included. The manual spike's 90-second watchdog is separate from the production worker's shorter deadline. Before stable promotion: test all five tabs, touch/scroll behaviour and artwork on the actual Pi; exercise explicit Play/Queue with the intended zone; validate optional-module navigation and repeated discovery use across reconnects/Roon updates.
