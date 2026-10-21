# Changelog

## 1.1.5 Alpine — 21 October 2026

- Restore the dominant 540px Now Playing cover on 1280-wide landscape touchscreens without changing the Original Display's 320px cover allocation.
- Apply the saved 180° calibration matrix to both Original Touch Display driver variants (`raspberrypi-ts` and `ft5x06`) instead of targeting only Touch Display 2 hardware.
- Add a visible **Next** key to the first-run on-screen keyboard; it advances through the current page's fields and dismisses the keyboard after the last field.
- Add an Original Display-specific compact pass: smaller settings and clock controls, denser four-column Browse and three-column Discover artwork grids, and a larger Surprise Me preview.

## 1.1.4 Alpine — 21 October 2026

- Restore the intended Now Playing cover scale at every 7-inch landscape resolution: 320px at 800×480, 360px at 1024×600 and 440px at 1280×720, while retaining the fixed no-reflow artwork stage.
- Allow the first-run wizard to apply 180° rotation to the Original Touch Display instead of rejecting it with the obsolete Alpine Beta restriction.

## 1.1.3 Alpine — 21 October 2026

- Promote the complete 1.1.3 touchscreen and controller refinement cycle to Stable, including responsive 7-inch landscape and 10-inch portrait layouts, consistent Roon violet styling, corrected navigation widths and improved touch targets.
- Add richer Recent, Browse, Daily, New Releases and Surprise workflows with preserved browsing state, configurable return-to-Now-Playing behaviour and stable alphabet scrubbing.
- Rework Album & Artist details for portrait and landscape, with clearer typography, balanced metadata, artwork-based close targets and a single fixed Browse Artist Albums action.
- Add prominent, consistent final Play actions; one-percent volume steps; larger brightness interaction; optional touchscreen Bus Times controls; and better settings layouts at every supported viewport.
- Stabilise Now Playing artwork allocation while restoring its intended scale, retain the painted square until a replacement cover is ready, prevent transport reflow and artwork flashes during loading, and extend the startup wordmark hold.
- Publish a fully verified ARM64 Alpine image for clean installations, including the Original Touch Display profile requested for Raspberry Pi 3 B+ acceptance testing.

## 1.1.3-beta.49 Alpine — 21 October 2026

- Rebalance primary Play pills with less space before the triangle, retained trailing space, larger text and clearer separation from album metadata.
- Increase prominent Play action sizing modestly on larger displays.
- Give Surprise Me and Play Now matching circular controls with more space between each symbol and caption.
- Hold the RoonDeck startup wordmark for at least 2.5 seconds before showing the ready interface.

## 1.1.3-beta.48 Alpine — 21 October 2026

- Restore the 7-inch landscape Now Playing cover to a responsive square up to 440px while retaining a fixed pre-load allocation that prevents transport controls from jumping.
- Give the 10-inch portrait Now Playing cover and artist line more breathing room before the metadata and seek controls.
- Let either artwork panel close Album & Artist details, matching the existing close X behaviour.
- Enlarge definitive Play glyphs and track-row Play targets, with slightly wider primary-action pills.
- Restore action-menu Play Now to the original rectangular menu geometry while preserving its purple primary treatment and leaving Queue, Add Next and Start Radio unchanged.

## 1.1.3-beta.47 Alpine — 21 October 2026

- Apply the selected soft-pill treatment to prominent playback actions: filled Roon purple for Play and a quiet outlined treatment for Queue.
- Replace the outlined Play glyph with a larger solid black triangle on Play Album, Play Artist, Play This Mix and Surprise Me.
- Carry the pill geometry into final Play commands in action menus while retaining the existing hierarchy of secondary actions.
- Tighten the 7-inch landscape Album & Artist header—especially below the heading—and enlarge the album write-up for easier reading.

## 1.1.3-beta.46 Alpine — 21 October 2026

- Reserve the Now Playing artwork square before a cover has downloaded or decoded so the transport controls no longer jump when returning from another input.
- Use identical title-to-write-up spacing in both Album & Artist columns and suppress empty subtitle rows that previously offset the album copy.
- Increase the close X inside its existing purple circle and restore it to white for clearer contrast without changing the touch target.

## 1.1.3-beta.45 Alpine — 21 October 2026

- Change the Now Playing volume step buttons to one-percent increments.
- Give conclusive Play Album, Play Artist, Play This Mix, Play Now and equivalent action-menu commands a purple primary treatment with black iconography and text.
- Align artist and album detail copy as title, write-up, source and then recessed facts, while removing the repeated artist line from the portrait album column.
- Enlarge and rebalance the Album & Artist header, retaining a larger touch target around a smaller gray close glyph.
- Carry the identity and typography improvements into 7-inch landscape, including a larger album label/title and the artist beneath it.

## 1.1.3-beta.44 Alpine — 20 October 2026

- Keep the alphabet scrubber visible and usable after sorting Albums by title or artist.
- Resume the last Discover/Browse screen instead of resetting to Recently Added.
- Apply the configured browsing timeout consistently while album and artist details are open.
- Restore the aligned Album & Artist heading, simplify the sort menu treatment, and highlight the selected sort.
- Add accessible two-percent volume-down and volume-up touch targets beside the Now Playing volume slider.

## 1.1.3-beta.43 Alpine — 19 October 2026

- Fix Discover and Browse returning to Now Playing immediately when the display inherited an older general inactivity timestamp.
- Start a dedicated browsing inactivity countdown whenever browsing opens and reset it on every touchscreen contact.
- Add the independent **Return browsing to Now Playing after** setting to Web Admin → Automation, including an option to keep browsing open.
- Compact landscape touchscreen settings by removing the redundant Bus Times heading and shortening its visibility control.

## 1.1.3-beta.42 Alpine — 19 October 2026

- Reworked album and artist details to use the available touchscreen space, remove redundant headings, rules, repeated artist text and track snippets, and improve portrait and 7-inch landscape readability.
- Enlarged the fixed **Browse Artist Albums** action and artist-album rows, with a transparent outlined close control and more legible album copy and metadata.
- Retry temporarily missing artist biographies, return an idle browser to Now Playing after one minute without discarding its browse position, and group native Bus Times controls together below Daily Controls.

## 1.1.3-beta.41 Alpine — 18 October 2026

- Rebuilt the 7-inch landscape Album & Artist sheet around one large album cover and a readable album-and-artist write-up, removing the cramped duplicate artist column.
- Made the close control truly circular, aligned artwork and headings to the same content margins, and gave the fixed action button a consistent bottom inset.
- Made every visible bottom-navigation destination occupy an equal share of the row, including the three-item layout.
- Added the Bus Times visibility control to the physical touchscreen's Settings → Display section while retaining the existing web-admin service controls.

## 1.1.3-beta.40 Alpine — 18 October 2026

- Keep Now Playing, Discover, Bus Times and Home in equal-width touchscreen navigation slots, including the three-item layout when Bus Times is hidden.
- Move the optional Bus Times visibility control to Display settings while retaining stop and service configuration under Services.
- Refine the Album & Artist sheet with balanced portrait columns, a dedicated compact landscape layout, a prominent circular close control and one fixed Browse Artist Albums action.
- Increase the brightness slider's physical touch target for larger portrait touchscreens.

## 1.1.3-beta.39 Alpine — 12 October 2026

- Reads Wi-Fi signal and link speed from NetworkManager on every supported image and removes the low-value interface card from Settings.
- Adds a non-installing release check at 03:00 each day; available updates remain user-controlled in Settings.
- Restores the homepage hardware artwork, improves the inset mobile hero crop and gives mobile setup steps their own number-heading row.
- Turns Supported hardware and Technical details into compact accordions, moves the optimisation note above them and removes the first-boot section.
- Uses the configured Resend recipient for feedback notifications and records delivery failures in deployment logs.

## 1.1.3-beta.38 Alpine — 11 October 2026

- Shows a running or boot-enabled AirPlay receiver in Diagnostics and adds interface, address, signal and link-speed details for the connected network.
- Tightens the Settings masthead, gives the AirPlay-name action breathing room, and expands the mode controls to two equal columns when Bus Times is disabled.
- Renames the display backgrounds to Purple Gradient and Pure Black.
- Removes the redundant homepage hero buttons and moves the Getting Started number spine to 25% of the content width.
- Connects the website feedback form to a small production Neon database so messages can be submitted reliably.

## 1.1.3-beta.37 Alpine — 11 October 2026

- Split web Settings → Services into focused Roon Display, BluOS, Roon Bridge and AirPlay panels, and lighten the Settings title weight.
- Add a guided playback and endpoint section to the website with white Roon, BluOS and AirPlay marks.
- Align the extra-feature screenshots, tighten the setup-step columns and keep the hardware headline on a cleaner desktop line.
- Preserve the full landscape-and-portrait hero composition on mobile and centre its calls to action.
- Add a quiet, spam-resistant suggestions form backed by a small Neon table, with optional email delivery.
- Match the microSD illustration outline weight to the Raspberry Pi and touchscreen drawings.

## 1.1.3-beta.36 Alpine — 11 October 2026

- Reframe the mobile hero to keep the complete landscape RoonDeck visible alongside a clear crop of the portrait unit.

## 1.1.3-beta.35 Alpine — 11 October 2026

- Enlarge and recrop the mobile hero so the complete landscape RoonDeck is the dominant product while the portrait unit is cropped away.

## 1.1.3-beta.34 Alpine — 11 October 2026

- Reverse the mobile hero crop so the landscape RoonDeck remains fully visible and the portrait display crops at the right edge.
- Restore the complete Home Assistant tree mark without relying on an SVG mask that fails in mobile Safari.
- Show the supplied album-cover grid for Browse your library and remove the duplicate divider below AirPlay.

## 1.1.3-beta.33 Alpine — 11 October 2026

- Run the mobile hero image full width while preserving the copy, image and action sequence.
- Remove the duplicate divider below Display & settings.
- Shorten the mobile hardware headline, keep setup headings plain with quiet links in their copy, and remove the glyph from the Roon URL.

## 1.1.3-beta.32 Alpine — 11 October 2026

- Recompose the mobile website hero into a clear copy, product image and action sequence.
- Centre the hardware plus connectors precisely between stacked mobile cards.
- Present only the Pi 4-or-newer recommended setup, with Pi 3 and 1GB retained as minimum support details rather than buying guidance.

## 1.1.3-beta.31 Alpine — 11 October 2026

- Replace the repeated website feature gallery and summary cards with one accessible, interactive journey ordered from Now Playing through browsing and discovery.
- Separate the optional Roon Bridge and AirPlay endpoint choices into their own section.
- Give the public website a distinct white favicon with a purple “r” and black “D”, while retaining the existing web Settings favicon.

## 1.1.3-beta.30 Alpine — 11 October 2026

- Add an optional classic AirPlay audio endpoint using Alpine's maintained Shairport Sync package, with install, naming and service controls in onboarding and web Settings.
- Align the web Settings wordmark, title and version on one compact baseline to match the touchscreen interface.
- Restructure the website around browsing, optional audio endpoints, hardware and a clearer linked setup sequence.
- Strengthen the experimental Roon warning, correct the Home Assistant mark, recommend 16GB+ storage and add the current Settings screenshot.
- Refresh the website with the latest Daily, Genres, Now Playing, album-detail and Surprise Me captures, and distinguish its white favicon from the purple web Settings icon.
- Keep the three remaining bottom-navigation items exactly centred and equally weighted when Bus Times is disabled.

## 1.1.3-beta.29 Alpine — 11 October 2026

- Tighten the space above and below Settings diagnostics in every supported layout.
- Restore breathing room between the landscape Background controls and bottom action row.
- Reduce the Settings title to a medium weight that better matches the supplied Deck wordmark.

## 1.1.3-beta.28 Alpine — 11 October 2026

- Fix Screen Preview captures racing the display wake-up and page navigation sequence.
- Wake and redraw the physical display before capture, then retry transient blank frames across later GTK frames.
- Preserve the previous good preview until a visible replacement has been captured.

## 1.1.3-beta.27 Alpine — 11 October 2026

- Place the RoonDeck wordmark, Settings title and version on one explicit shared text baseline across portrait and landscape layouts.
- Add a compact vertical gap between the identity row and diagnostics on 7-inch layouts, with slightly more room on larger displays.
- Add native visual assertions for exact title/version baseline equality and wordmark baseline alignment at every tested settings viewport.

## 1.1.3-beta.26 Alpine — 11 October 2026

- Retries interrupted verified-source downloads and reports the actual network or archive failure instead of a generic preparation message.
- Repairs the native Settings smoke check for GTK's supported size-request API.
- Runs real application staging and rollback immediately after the appliance runtime check, before slower visual review steps.

## 1.1.3-beta.25 Alpine — 11 October 2026

- Consolidates RoonDeck’s Roon-theme accent colour around the approved brand violet (`#9868F9`) across the native touchscreen, web settings, Screen Preview, sign-in, Home controls, setup wizard, Roon controller and public website.
- Keeps dark tonal surfaces for depth while removing competing violet accents from links, selected tabs, controls, icons and focus states.
- Refreshes web asset versions so browsers do not retain the older purple palette.
- Constrains the Settings wordmark to its true SVG width, tightens its gap to the title, and aligns the wordmark, title and version on one visual baseline.

## 1.1.3-beta.24 Alpine — 11 October 2026

- Applies the final supplied RoonDeck SVG identity consistently to the appliance, Settings, setup wizard, web GUI, website, favicons and launcher icon.
- Constrains the native Settings wordmark to the original title area, aligned with and visually matched to the Settings heading across supported display layouts.
- Refines the website information architecture: Roon Bridge/RAAT now sits with the Roon features; Home Assistant and Netdata use linked white brand marks; and the Roon feature summary becomes a full-width purple gradient band.
- Simplifies the hardware introduction to “Everything you need to build a RoonDeck.” and improves the API notice and feature-band responsive layouts.
- Replaces download glyphs with a consistent SVG icon and labels download actions with the current stable image version.

## 1.1.3-beta.23 Alpine — 10 October 2026

- Rolls out the supplied RoonDeck vector identity across the touchscreen, first-run setup, web settings, browser pages, launch metadata, favicons and public website.
- Adds the approved independent-project descriptor and legal disclaimer, while preserving existing internal service and configuration paths for upgrade compatibility.
- Documents optional Roon Bridge support as a RAAT endpoint and renames the Roon extension to RoonDeck without changing its pairing identifier.
- Compacts landscape Settings by using `THEME` and `BACKGROUND` as the only appearance headings, eliminating the duplicated labels that could overflow the viewport.

## 1.1.3-beta.22 Alpine — 10 October 2026

- Rebrands the touchscreen Settings header from Pi Home to RoonDeck.

## 1.1.3-beta.21 Alpine — 10 October 2026

- Render Screen Preview captures into an independent Cairo image surface before attempting GPU/KMS readback, avoiding Raspberry Pi fullscreen capture stalls, and expose the precise renderer failure when capture still fails.

## 1.1.3-beta.20 Alpine — 10 October 2026

- Makes Screen Preview resilient across GTK/KMS renderer combinations by falling back from the live parent snapshot to a fresh widget snapshot and a capture-only Cairo renderer.
- Keeps the previous preview unchanged when every validated rendering path genuinely fails, rather than replacing it with an empty or black frame.

## 1.1.3-beta.19 Alpine — 9 October 2026

- Reworks the native Album & Artist fact sheet into a clean full-screen two-column layout with larger headings, circular SVG close control, richer artist facts and direct Browse Artist / Artist Albums actions.
- Adds a deliberately reduced fact-sheet layout for 800×480 landscape displays, keeping both artworks, useful facts, short summaries and actions readable without the previous oversized crop.
- Corrects the track play menu anchor and touch sizing on compact landscape screens, keeps its cursor hidden, aligns its grays with the shared palette and prevents album art flashing when it closes.
- Improves metadata coverage by following safe Wikipedia redirects, handling initialled artist names, trying artist-qualified album pages, accepting decisively ranked duplicate-name artists and allowing more realistic lookup times; blank artist results are no longer cached after transient failures.
- Keeps Browse’s secondary navigation in exactly the same position when Search opens.
- Moves Background beside Theme under Appearance on every settings layout.
- Extends Screen Preview to open Settings, Album & Artist, Search and deeper Browse categories before capturing the physical display.

## Unreleased Alpine

- Disables Wi-Fi power saving in the Alpine image and on Wi-Fi profiles created by setup, preventing the severe local-network latency spikes observed with Roon Discover.
- Keeps album write-ups to a concise two-sentence preview with Wikipedia attribution and Bandcamp fallback.

## 1.1.3-beta.18 Alpine — 8 October 2026

- Implements the full-screen artist-and-album fact sheet in the native GTK touchscreen actually used by Alpine, rather than only in the separate browser interface.
- Adds a fixed close button, solid black full-screen takeover, independent artist and album artwork, the full album write-up, artist biography, release facts and track list.
- Adds a 1200×1920 native visual acceptance check that verifies the fact sheet covers the physical display edge to edge and exposes its close control.

## 1.1.3-beta.17 Alpine — 8 October 2026

- Makes the album-and-artist fact sheet a true full-screen view with an explicit close button, two balanced information columns and no hidden navigation behind it.
- Adds compact touchscreen controls for Netdata and the gradient/black background alongside Roon Bridge, with roomier settings spacing, a larger brightness target and dark dropdown menus.
- Restores the portrait bus `ROUTE` label to white and enlarges the muted `min` labels beside later arrivals.

## 1.1.3-beta.16 Alpine — 8 October 2026

- Verifies that the separately served Roon controller is running the exact staged revision before an update can report success.
- Prevents the touchscreen browser from reusing an earlier artwork page, script or stylesheet after an application update.
- Makes Netdata Cloud reconnection use the installed Agent instead of unnecessarily running the full Agent installer again.
- Enlarges portrait route and later-arrival numerals, quietens supporting time labels, and omits empty arrival placeholders.

## 1.1.3-beta.15 Alpine — 8 October 2026

- Adds a standalone Netdata installer to Tools when the Agent is absent, with live progress and failure text; Cloud connection remains an optional second step.
- Reworks the tapped Now Playing artwork view into a responsive fact sheet with separate artist portrait and biography plus album cover, full album write-up, release facts and track list.

## 1.1.3-beta.14 Alpine — 8 October 2026

- Loads identity-checked Wikipedia album summaries before the slower MusicBrainz enrichment path, so a MusicBrainz timeout cannot suppress a valid summary.
- Stops caching blank album-summary responses, allowing transient network failures to recover on the next album view instead of persisting until restart.

## 1.1.3-beta.13 Alpine — 8 October 2026

- Retrieves album summaries directly from a matching Wikipedia album page when MusicBrainz has no explicit article link, while rejecting unrelated and disambiguation results. This covers `(What's the Story) Morning Glory?` and other well-known albums that previously showed an unavailable message.
- Refines the album sort popover with sentence-case labels, no broken arrow glyph or sticky selection, an immediate sorting state, inset spacing and consistent menu styling.
- Offsets track-action popovers from the play tile so they align cleanly with track text and do not leave a focused action highlighted.
- Correctly migrates Alpine's packaged Netdata agent to the official stable static agent before claiming it, using the current installer flags, explicit reinstalls for upgrades and package rollback when migration fails.

## 1.1.3-beta.12 Alpine — 8 October 2026

- Replaces the unreliable native album sort dropdown with the same high-contrast popover styling used by track actions. Offers full-library title A–Z, title Z–A and artist A–Z sorting on large portrait displays.
- Keeps the Browse secondary navigation visible above the on-screen search keyboard, so another section is always one tap away.
- Shows a visible loading, sourced summary or explicit unavailable state on album and artist pages. Retries common remaster, deluxe and anniversary titles against their base album names.
- Clears an opened Daily mix when switching to For You, so the selected tab and displayed content cannot disagree.
- Matches Home Controls card corners to Bus Times and increases the spacing between Home panels.
- Keeps the last valid touchscreen settings during the API/display boot race and retries both display and backend settings loads automatically instead of temporarily applying defaults.
- Release-date sorting remains unavailable because Roon's public Browse album rows do not expose release dates.

## 1.1.3-beta.11 Alpine — 8 October 2026

- Adds optional per-device RGB white balance to the main GTK touchscreen window, with persistent configuration outside application releases. Missing or invalid profiles preserve original colours.
- Adds measured-gain activation/reset instructions and real GTK pixel checks. Uses the first practical correction selected by the owner; no claim of full ICC calibration.
- Includes beta.10 UI improvements. Physical V3D/touchscreen acceptance remains required.

## 1.1.3-beta.10 Alpine — 8 October 2026

- Enlarges Home control labels and states, with a white Home Controls heading.
- Aligns portrait music headers with Bus Times and prevents Back from shifting Browse tabs.
- Uses finer strokes for large genre/playlist icons and top-aligned square genre navigation cards.
- Adds full-collection title and artist sorting on large portrait album browsers; Roon does not expose date sorting.
- Loads source-labelled Wikipedia/Bandcamp album notes asynchronously through MusicBrainz links when available.
- Makes the touch spring slightly stronger while retaining clipping and exact settling.
- Highlights only the playing queue track, with a larger filled play marker that adapts to artwork brightness.

## 1.1.3-beta.9 Alpine — 8 October 2026

- Adds Display → Appearance → Screen background: Current or Pure black across all physical display pages, with no reboot required.
- Uses a 1200px loading-disc placeholder on Now Playing instead of magnifying the 256px thumbnail asset.

- Sizes genre and playlist icons to their cards, adds genre caption padding and consistent space below Browse tabs.
- Refines track action pop-up alignment, shadow and action spacing; strengthens static gradient dithering.
- Artist links search only artist results and use the same response deadline as other multi-step Browse operations.
- Refines portrait route badge weight and arrival spacing without changing landscape bus layouts.
- Album reviews remain optional: displayed only when Roon supplies review metadata.

## 1.1.3-beta.8 Alpine — 8 October 2026

- Implements the approved portrait-only bus layout: coloured route badge, prominent next arrival, divider and THEN with two following arrivals.
- Fits text to portrait screen/card budgets, bounds Due and long arrival values, and displays dashes for missing predictions. Keeps the existing landscape bus layout unchanged.
- No changes to display capture, touch, GPU or network configuration. Physical touchscreen acceptance remains required.

## 1.1.3-beta.7 Alpine — 8 October 2026

- Captures the current page through its parent and exports with the live display renderer instead of a separate Cairo renderer, preserving GPU-backed content.
- Rejects black or transparent captures with an inline error instead of reporting successful preview updates. Keeps the previous successful screenshot.
- Adds an OpenGL capture regression check alongside native layout verification. Physical Pi acceptance remains required; no boot, rotation or network changes.

## 1.1.3-beta.6 Alpine — 8 October 2026

- Replaces the confusing Diagnostics preview controls with a dedicated Screen Preview page. Section buttons and a Discover-view dropdown lead to searchable browse results; tap an album/track to open it without separate Load/Open steps.
- Waits for a request-matched native display acknowledgement before updating results and automatically capturing the screen. Shows loading/errors inline rather than in the settings save banner.
- Uses asynchronous screenshot tickets and short status requests. Keeps the last successful image and timestamp when capture fails, with a download link and manual refresh.
- Separates playback actions from browsing and requests explicit confirmation before running them. Protects preview APIs with settings authentication and restricts display acknowledgements to local, non-forwarded requests.
- Beta only; no changes to bus sizing, live GPU acceleration, rotation or network configuration. Physical-Pi screenshot acceptance remains required.

## 1.1.3-beta.5 Alpine — 8 October 2026

- Doubles arrival numeral sizing on large portrait bus layouts while preserving the compact-screen limits.
- Replaces the backend's browse button grid with a dropdown and explicit Open button; adds Albums, Artists, Genres and Playlists section buttons.
- Uses a dedicated Cairo screenshot renderer, leaving live display GPU acceleration unchanged. Extends capture/delivery timeouts and logs delivery errors rather than silently dropping them. Physical-Pi acceptance remains required.
- Beta only; does not alter boot configuration, touch rotation or Wi-Fi.

## 1.1.3-beta.4 Alpine — 8 October 2026

- Restores rounded gray track play tiles with purple triangles and anchors dark, themed playback menus beside the selected row.
- Adds backend album/browse preview navigation and a six-image screenshot history under System → Diagnostics. Captures remain in browser memory, with downloadable PNGs; opening playback actions still requires an explicit click.
- Includes the visible track popover in GTK display capture.
- Replaces the short repeating dither pattern with a larger irregular static texture. Banding still requires physical-panel validation; this is not a confirmed hardware fix.
- Beta only; working GPU, touch rotation, and network settings are unchanged.

## 1.1.3-beta.3 Alpine — 8 October 2026

- Adds a subtle static dither over the existing Roon gradient to reduce colour banding; physical-panel acceptance is still required.
- Fixes overwritten portrait bus-route sizing, enlarges route/due numerals on 10-inch displays and uses lighter large route and Watch TV numerals.
- Uses white, larger plus/minus glyphs in round gray Watch TV buttons.
- Clips elastic paint nodes to their damage bounds and resets springs when replacing content, addressing possible stale animation strips. Adds a 10px clearance below browser/Discover scrollers.
- Removes unused alphabet-rail space in search cover grids; shifts the scrubber right and enlarges its 10-inch letter. Reduces large Back buttons about 10–12% while retaining label size.
- Enlarges Artist Albums and Daily recommendation labels.
- Adds one album cover/header with artist navigation and track play icons instead of repeated artwork. Shows the core's playback-action menu in a touch popover. Displays review text only if actually supplied by the core; the public Browse contract does not guarantee reviews.
- Adds exact-match artist-link resolution and album/action metadata tests. Wi-Fi throughput remains under hardware diagnosis; no unverified network changes are applied.
- Beta only. Does not change the user's working boot GPU configuration or touch rotation.

## 1.1.3-beta.2 Alpine — 7 October 2026

- Fetches Surprise Me artwork at 900px instead of stretching the shared 256px thumbnail; keeps the scrolling cache small.
- Corrects settings font specificity: larger title, version, diagnostics, Back/Sleep, bus labels and theme choices on 10-inch displays.
- Adds 5px menu-label padding, slightly enlarges cog/clock and nudges the 10-inch music header up 3px.
- Enlarges Watch TV volume numerals and Mute, with purple-on-gray Roon increment controls.
- Preserves the enlarged play/pause icon through playback refreshes; retains a record-cover placeholder even after repeated artwork failures.
- Centers portrait volume at 88% width, with more spacing above volume and below it before Mute.
- Decodes scrolling thumbnails and large preview artwork in workers rather than blocking touch frames. Synchronizes elastic springs to the widget frame clock, avoids rebuilding unchanged play icons and throttles alphabetical scroll scans. Actual Pi rendering performance still requires hardware diagnosis; no refresh-rate or gradient-banding fix is claimed.
- Beta only; stable and working touch rotation remain unchanged.

## 1.1.3-beta.1 Alpine — 7 October 2026

- Connects authenticated web Wi-Fi/name controls to the Alpine helper; permits validated network/name changes after onboarding and allows time for Wi-Fi association.
- Enlarges 10-inch labels, transport controls, mute/back/settings buttons, album-track artwork and artist portrait. Moves portrait mute below the volume slider and separates top-menu items.
- Removes excess expansion above artist albums and enlarges the 10-inch Surprise Me artwork/actions while preserving smaller display sizes.
- Bounds artwork visibility scans during scrolling instead of running them on every motion event; no panel refresh-rate claim is made.
- Retains the user-confirmed 10-inch touch correction from 1.1.2. Beta only pending physical layout, Wi-Fi and scrolling acceptance.

## 1.1.2 Alpine — 7 October 2026

- Corrects rotated touch on the 10-inch Touch Display 2: target its Ilitek `ili_v3` input device, not only the Goodix controller used by the smaller panels.
- Preserves existing 7-inch calibration, clears compositor output mapping to avoid double rotation, and logs input names for hardware diagnosis.
- Apply the update, then reboot manually to reload touch calibration before Cage starts. Physical finger-input acceptance remains required.

## 1.1.1 Alpine Stable — 7 October 2026

- Promotes the verified beta.18 application and full Raspberry Pi 5 ARM64 appliance image to the Stable channel, without further UI or interaction changes.
- Includes unified iconography, button-local library/favourite pulse feedback, 30 previous queue tracks, responsive layout refinements and elastic touch-scroll boundaries.
- Existing Alpine installations update through the Stable updater without reflashing; a full image with checksum and source/package manifests is provided for fresh installs.

## 1.1.1-beta.18 — 7 October 2026

- Packages the beta.17 application as a full ARM64 Alpine appliance image for fresh Raspberry Pi 5 flashing, with checksum and exact source/package manifests.
- Updates fresh-image Daily validation to check aligned heading/title context without the intentionally removed duplicate seed cover, plus the 30px carousel trailing margin.
- Preserves the application UI, 30-track history, library-button pulse and prior display refinements.

## 1.1.1-beta.17 — 7 October 2026

- Replaces the native library/favourite “Updating Roon…” row with a softly pulsing accent ring around the button; keeps confirmed results, errors and duplicate-request protection.
- Adds equivalent web library-button feedback and accessible busy state; reduced-motion users get a steady ring.
- Retains 30 previously played tracks, bounded by a shared controller history limit. Current/upcoming subscription remains 100 and artwork cache limits are unchanged.
- Includes beta.16 scroll springs, stronger action icons and 30px keyboard margins on both platforms. Source-only beta.

## 1.1.1-beta.16 — 7 October 2026

- Slightly increases resisted boundary pull to 26px with a gentler 550ms spring; adds the same paint-only return to vertical lists, Home and Settings.
- Removes vertical overshoot/undershoot highlight lines without changing resting positions or ordinary kinetic scrolling.
- Enlarges album/library and Surprise Me action icons from 34px to 42px; brings shuffle into the thicker touchscreen control family.
- Sets search keyboard margins to 30px on both sides across display sizes and orientations.
- Leaves queue history at 10 previous tracks and upcoming subscription at 100. Source-only beta.

## 1.1.1-beta.15 — 7 October 2026

- Restores the original smaller neutral album/artist loading placeholders and increases native playback/library/cog strokes from 2 to 3 units, keeping the new shapes.
- Corrects horizontal Daily carousel end space to exactly 30px, not the leading screen coordinate.
- Removes GTK overshoot/undershoot highlight lines.
- Adds a capped 18px resisted touch pull and a 450ms damped spring-back at both ends; paint-only offsets leave the first-card resting position unchanged.
- Preserves ordinary kinetic scrolling, vertical gestures and all beta.14 icon/layout refinements. Native geometry and animation checks added; source-only beta.

## 1.1.1-beta.14 — 7 October 2026

- Establishes one bespoke currentColor SVG family across native and web controls, with a central catalogue and reusable adapters.
- Redraws all 21 genres from the final reference concepts, including trumpet Blues, palm-tree Reggae and Comedy.
- Consolidates browse, playback, queue/library, settings and Home icons; retains existing interactions, colour states, touch targets and live clock hands.
- Adds asset-generation/vector validation and all-genre native visual fixtures. Preserves beta.13 layout polish. Source-only beta, no disk image.

## 1.1.1-beta.13 — 7 October 2026

- Adds trailing breathing room to landscape Daily carousels equal to their leading content margin; preserves first-card position.
- Restores subtle native GTK touch overscroll feedback at both horizontal boundaries.
- Removes empty Home status space and grid-top padding; Home and Bus Times share content-top offsets and page margins.
- Uses the Home 2px large-panel stroke for Home and Bus Times, retaining colours and radii.
- Consolidates shared layout constants and adds native start/end, panel-top and stroke checks. Source-only beta, no disk image.

## 1.1.1-beta.12 — 7 October 2026

- Aligns landscape Daily recommendation headings and uppercase album names with the artwork left edge.
- Lets landscape Daily artwork rows bleed to the right screen edge, without changing other page margins.
- Adds native geometry assertions for both boundaries. Source-only beta; no disk image.

## 1.1.1-beta.11 — 7 October 2026

- Adds Display → Landscape music clock: icon or full digital clock when space permits.
- Centres music menus between balanced utility areas; aligns Bus Times and Home clocks.
- Uses text-only Daily recommendation context in landscape as well as portrait, with uppercase white album names.
- Lowers landscape Recent, Daily and New Releases content by 5px and balances New Releases outer margins and column gaps.
- Preserves portrait refinements and Browse sizing. Source-only beta, no disk image.

## 1.1.1-beta.10 — 7 October 2026

- Keeps the same settings cog and analogue sleep clock visible on music pages in both landscape and portrait.
- Adds the settings cog to Bus Times and Home while retaining their full digital clocks and bus stop information.
- Retains all beta.9 refinements. Source-only beta; no disk image rebuild.

## 1.1.1-beta.9 — 7 October 2026

- Enlarges portrait settings title, version, diagnostics and Back/Sleep controls; adds more separation below the title row.
- Uses the web GUI orange reboot treatment across backend reboot buttons, touchscreen settings and restart confirmation.
- Lowers the shared portrait music header by 3px, retaining cog/clock alignment and 30px side margins.
- Adds another 5px above portrait New Releases and a purple play triangle to Play This Mix.
- Retains beta.8 navigation/loading safeguards and adds native settings screenshot coverage. Source-only beta, no disk image rebuild.

## 1.1.1-beta.8 — 7 October 2026

- Restores all beta.6 portrait refinements: consistent 30px margins/gaps, compact menu spacing, revised Surprise layout, bottom-docked search and single-column previews, right-aligned Back, full-width playlists and artist album spacing.
- Fixes the 24px three-column overflow: portrait card requests now match the artwork width rather than adding the obsolete 8px padding allowance.
- Cancels delayed/queued searches when leaving the keyboard. Bounds Roon Browse callbacks so a missing response cannot indefinitely block later requests; read-only navigation allows time for multi-step responses.
- Preserves controller error messages rather than misrepresenting failures as an empty library; render exceptions release the navigation lock.
- Uses smaller solid route-coloured numerals, retaining two larger arrivals in portrait and three in landscape.
- Adds loaded-artwork width and asynchronous search/navigation checks. Source-only beta, no image rebuild.

## 1.1.1-beta.7 — 7 October 2026

- Restores the beta.5 native music-screen navigation, search lifecycle and artwork sizing after beta.6 regressions. The beta.6 search docking and cosmetic refinements are withdrawn for this recovery release.
- Keeps two larger arrivals in portrait and three in landscape; restores solid-white route numbers with less portrait prominence.
- Prevents a missing Roon subscription-close payload from crashing the controller.
- Checks window width after Discover artwork loads. Source-only beta; no disk image is rebuilt.

## 1.1.1-beta.6 — 7 October 2026

- Standardises portrait outer margins and artwork column gaps at 30px; lowers the primary underline by 2px and makes playlists full-width.
- Matches the revised Surprise composition, keeps drill-down Back at the right, and adds breathing room between artist albums.
- Docks the portrait search keyboard below one scrollable results column, adds debounced search while typing and limits artist previews to three plus View All.
- Outlines route numbers and enlarges portrait arrival times: two arrivals in portrait, three in landscape.
- Adds native search, playlist and arrival-count checks. This is a source-only beta; no disk image is rebuilt.

## 1.1.1-beta.5 — 7 October 2026

- Refines portrait margins, menu spacing, Browse/genre grids and the search keyboard; keeps the current navigation hierarchy.
- Moves artist information beside its image with albums below, reorders Surprise Again/artwork/metadata/Play Now, and replaces portrait recommendation seed artwork with a text heading.
- Preserves genre SVG keyline detail instead of loading outlines as solid symbolic masks. Removes the duplicate diagnostics divider.
- Adds real GTK capture coverage and useful capture-failure logging.
- Beta commits run backend, controller, update-safety and native layout checks without creating a disk image. Full image construction is an explicit workflow option for stable releases or image testing; existing updater verification remains compatible.

## 1.1.1-beta.3 — 6 October 2026

- Fixes portrait source-menu labels touching when amplifier inputs arrive after the screen layout. Source buttons now use the same expanding slots as existing tabs, with a consistent minimum gap.
- Tests the real late-loading order in native GTK screenshot checks.

## 1.1.1-beta.2 — 6 October 2026

- Applies the sketch-aligned portrait header consistently across Now Playing, Queue, sources and Discover: Settings, contextual menu and Sleep clock on one row.
- Makes the analogue clock show the live local time, redrawing only when the minute changes.
- Corrects the displayed application version and release-availability comparison. Adds automated checks keeping displayed, Python and controller versions in sync.

## 1.1.1-beta.1 — 6 October 2026

- Matches the portrait Discover sketch: Settings and Sleep icons flank the primary tabs on one row; subsections remain directly below, with larger three-column Browse artwork and a compact alphabet rail.
- Adds theme-coloured pulsing loading dots for Browse/Discover. Animation runs only while the loading view is visible.
- Retains the 1.1.0 responsive display, configurable discovery grids, library/favourites, diagnostics, mobile bus, Home-icon and lightweight Netdata improvements. Stable releases remain unchanged.

## 1.1.0 Alpine — 6 October 2026

- First separately published Alpine release, retaining the verified Alpine updater and optional-software setup.
- Adds Stable/Beta selection in System → Software. Fresh Alpine installs default to Stable; existing beta appliances retain Beta. Updates use published Alpine tags with successful image verification, never Raspberry Pi OS releases or automatic downgrades.
- Reduces Home device icons by 25%, without changing cards or controls.
- Mobile portrait bus cards show a large centred route number above full-width, evenly spaced arrival columns. Longer route lists scroll naturally.

## 1.1.0-beta.45 Alpine Beta — 6 October 2026

- Adds a persisted 2/3-column portrait Discover grid setting in backend Display → Appearance, shared by Recent, Daily and New Releases.
- Portrait Daily uses separate Mixes and For You grids with vertical scrolling; landscape keeps horizontal swipe tracks.
- Applies the saved web theme before first paint, avoiding the Mint flash on Settings, Bus Times and Home.
- Makes bus live/update footer text a slightly darker grey.

## 1.1.0-beta.44 Alpine Beta — 6 October 2026

- Adds consistent space below portrait music navigation and asymmetric breathing room around Now Playing artwork.
- Keeps bus live/update status directly beneath the final panel, scrolling with the panels when necessary.
- Hides unconfigured Roon diagnostics and deliberately stopped optional endpoints, while retaining configured service failures. Labels the shared backend accurately when buses are disabled.
- Adds Home and Bus Times shortcuts to physical-screen capture controls and wraps backend action buttons on mobile.

## 1.1.0-beta.43 Alpine Beta — 6 October 2026

- Compacts portrait music headers, enlarges and spaces top navigation text, and brings the underline closer to its label. Now Playing uses centred artwork 20% smaller with metadata beneath it.
- Bounds loaded Browse artwork and complete cards, preventing real covers and artist names from widening the window and pushing the clock or alphabet scrubber off-screen. Adds loaded-artwork allocation regression checks.
- Entering Recent selects Added; explicitly choosing Listened still works. Aligns portrait Daily swipe clipping with the common left margin.
- Stacks portrait Surprise Me above the cover and Play Now below it. Gives bus cards natural heights, larger route numbers, smaller arrival text and a smaller stop heading.

## 1.1.0-beta.42 Alpine Beta — 6 October 2026

- Gives portrait music pages a player/clock header followed by a separate underlined navigation row; removes vertically expanding horizontal menus and wasted browse space.
- Uses full-width two-column Recent/New Releases covers, three-column Browse and larger swipeable Daily cards. Recent opens Added first in both orientations.
- Stacks portrait bus route numbers above arrivals and rearranges Home into horizontal icon/control rows with horizontal level sliders.
- Shows Mixes loading/unavailable state even when For You succeeds, rather than silently hiding a failed mix request.
- Apply Display saves the profile, orientation and mounting then automatically reboots, applying the output and touch calibration together. Brightness/theme changes do not reboot.
- Raises the reboot confirmation slightly above visual centre in both orientations.

## 1.1.0-beta.41 Alpine Beta — 6 October 2026

- Removes the obsolete Alpine rejection of the local touchscreen Roon Bridge start/stop endpoint and routes it through the existing privileged service helper. Remote requests remain blocked.
- Shows the touchscreen Bridge checkbox only for installed services, disables it during mutations, restores state with visible failure feedback and promptly refreshes actual service status.
- Restores visible update stages and failures beside the Settings title, including the queued/requesting stage, without expanding the header beyond the viewport.

## 1.1.0-beta.40 Alpine Beta — 6 October 2026

- Aligns the installed version with the Pi Home Settings title baseline.
- Gives Display Brightness its own accent subheading and separate slider, and Theme its own subheading with two equal-width, larger Mint/Roon choices.
- Reorders bottom actions to Install Update, Apply Display, Reboot, retaining equal widths and margins.

## 1.1.0-beta.39 Alpine Beta — 6 October 2026

- Rebuilds touchscreen Settings to the supplied layout: left-aligned Pi Home Settings title with inline version, compact metrics underneath, Back/Sleep at the top right, common outer margins and equal-height control rows.
- Uses three equal-width bottom actions with consistent spacing and responsive landscape/portrait grouping. Shows update details as the version tooltip rather than a full-width paragraph.
- Shortens backend Netdata guidance to concise resource-saving and automatic-update descriptions.
- Adds real GTK Settings allocation checks and a native review capture to the Alpine image workflow.

## 1.1.0-beta.38 Alpine Beta — 6 October 2026

- Shows running Netdata and its collector processes in backend Diagnostics with combined RSS memory and CPU usage; hides the row when stopped.
- Renames the backend System Services tab to Tools, leaving the main Services menu unchanged.
- Uses the tested lightweight plugin selection: disables netflow, otel, scripts.d, nfacct, network-viewer and debugfs; keeps apps and go.d enabled. Turning lightweight mode off restores the original plugin overrides.
- Adds a persisted Lightweight monitoring option to first-boot software selection and backend Services. New official installations default to three-second sampling and disabled ML anomaly detection, retaining alerts, dashboard, database and Cloud connectivity.
- Explains that installation downloads the latest official stable Agent, not Alpine's package, with Netdata's daily updater maintaining it independently of Pi Home updates. Existing installations remain unchanged until the option is selected; disabling it restores one-second sampling and automatic ML.
- Backs up Netdata configuration before managing only its ML and sampling settings, and restarts a running Agent to apply changes.

## 1.1.0-beta.37 Alpine Beta — 5 October 2026

- Replaces the non-working browse-based library action with the exact private Roon calls observed from the official client. Resolves the playing album and profile through the selected zone, and confirms library membership from Roon's pushed state.
- Uses Roon's + / outline heart / filled heart behaviour, including separate favourite and unfavourite actions on the canonical library edition. Keeps status work asynchronous and cached, rejects stale album actions and shows unconfirmed-action errors.
- Stops the library button stretching vertically and adds real Alpine GTK square-allocation checks at six landscape/portrait viewport sizes.
- Verifies Add to Library for Judas Priest's Rocka Rolla on the live Core, plus favourite/unfavourite with the original state restored. Final physical Pi acceptance remains an appliance test.

## 1.1.0-beta.36 Alpine Beta — 5 October 2026

- Gives native GTK settings dropdown popups an explicit light-gray surface, dark text and a pale-purple selection so their options remain legible under the Pi Home dark theme.

## 1.1.0-beta.35 Alpine Beta — 5 October 2026

- Adds a first-boot optional software step for Roon Bridge and the official stable Netdata Agent, with progress, retry and skip controls.
- Keeps storage expansion, diagnostics, curl, certificates and time sync in every fresh image. Removes the obsolete Alpine Netdata package from new images and system-tools repair.
- Enables Netdata's official daily updater and the cron service. Existing installations remain outside Pi Home's application update directories; a reflash starts fresh.
- Verifies an actual official Netdata installation from the fresh ARM64 image, including its managed boot service and daily updater.

## 1.1.0-beta.34 Alpine Beta — 5 October 2026

- Replaces the dead-end “Not installed” Roon Bridge controls with an explicit appliance-managed **Install Roon Bridge** action and live installation progress.
- Downloads Roon’s fixed official ARM64 package without executing its incompatible Debian/systemd installer wrapper, validates every archive path and required executable, and preserves Roon’s separate distribution model.
- Installs the Alpine glibc compatibility, ICU, C++, ALSA and bzip2 dependencies, verifies Roon’s own compatibility check, and creates the managed OpenRC service before starting the endpoint.
- Keeps Start, Stop and Restart available after installation and directs the owner to enable the new endpoint in Roon’s Audio settings.

## 1.1.0-beta.33 Alpine Beta — 5 October 2026

- Detects Netdata's official static installation under `/opt/netdata` instead of incorrectly reporting it as missing when Alpine's packaged binary and OpenRC service are absent.
- Reads the official Agent's real version and Cloud status, and treats a responsive local dashboard as a running Agent.
- Adopts the official installation with a managed OpenRC service so Run/Stop controls and startup after reboot work without reinstalling Netdata.

## 1.1.0-beta.32 Alpine Beta — 5 October 2026

- Replaces raw display rotation degrees with one persisted Landscape or Portrait setting shared by touchscreen and web Settings.
- Applies orientation through the panel-aware Cage/Wayland and touch-calibration path, then reloads the Alpine display without requiring a full reboot when the selected screen hardware is unchanged.
- Makes the native GTK interface respond to its real viewport: Now Playing stacks artwork above metadata and transport in portrait, while settings, Browse, Discover, Queue, navigation and the Add to Library heart reflow or resize through shared responsive rules.
- Preserves the current 7-inch landscape arrangement while adding compact portrait and high-resolution 10-inch behaviour without separate per-screen page implementations.

## 1.1.0-beta.31 Alpine Beta — 5 October 2026

- Routes Roon Bridge Start, Stop and Restart through Alpine's privileged OpenRC helper instead of rejecting them as Raspberry Pi OS-only controls.
- Reports the real Alpine Bridge state and creates a native OpenRC service around an existing official `/opt/RoonBridge/start.sh` installation; absent Bridge files now report as not installed rather than unknown.

## 1.1.0-beta.30 Alpine Beta — 5 October 2026

- Keeps the three Netdata actions on one responsive desktop/tablet row, with a mobile-only vertical fallback.
- Gives appliance system tools their own labelled subsection and suppresses stale failed-operation copy after Netdata reports a live Cloud connection.
- Replaces the legacy packaged-Agent claim guidance with Netdata’s official installation flow and installs curl automatically before launching the validated official installer.

## 1.1.0-beta.29 Alpine Beta — 5 October 2026

- Restores true centred Now Playing title and artist layout on the native touchscreen.
- Replaces the hidden conditional library plus with an always-visible SVG heart whenever an album is playing. The outline fills immediately after Roon confirms Add to Library, and existing library state is shown only when Roon exposes its real Remove from Library action.

## 1.1.0-beta.28 Alpine Beta — 5 October 2026

- Install the `openssl` command required by Alpine Netdata's claim helper when
  connecting an existing appliance, before stopping the local Agent.
- Include both OpenSSL and curl in newly built appliance images and verify them
  explicitly in the image workflow, while retaining the detailed claim errors
  introduced in beta.27.

## 1.1.0-beta.27 Alpine Beta — 5 October 2026

- Add an asynchronous Now Playing library button backed by Roon's own library
  state and Add to Library action, without a separate Pi Home favourites store.
- Fix Netdata Cloud connection on Alpine by invoking the version-matched claim
  helper bundled with the installed Agent and reading its actual ACLK state.
- Report Netdata's precise claim failure, run the helper in stopped-daemon mode,
  and recover once from a stale node identity left by an interrupted claim.
- Remove the misleading official-Agent replacement path, which could report
  success while Alpine's packaged Agent remained installed.
- Brighten the Roon-theme favicon accent without changing the interface palette.

## 1.1.0-beta.26 Alpine Beta — 5 October 2026

- Fix the Netdata official-Agent button being rejected as an unknown system
  action by using one shared API/helper action allowlist and forwarding its
  validated Cloud connection command correctly.
- Report progress when applying Cloud settings to the existing Agent instead
  of leaving the connection attempt visually silent.
- Move Browse's alphabet scrubber another 4 px left on both the physical GTK
  display and browser interface.

## 1.1.0-beta.25 Alpine Beta — 5 October 2026

- Increase only the New Releases four-column gap so its final tile aligns with
  the header clock boundary while retaining the larger artwork size.
- Give Browse's alphabet scrubber its own 14 px physical-edge inset without
  restoring the right padding that previously broke Daily's edge bleed.

## 1.1.0-beta.24 Alpine Beta — 5 October 2026

- Expand the flashed root partition and ext4 filesystem to the available SD-card
  capacity before normal Pi Home services start, using the detected root device
  rather than a hard-coded MMC path.
- Include Alpine's `growpart` and `resize2fs` packages in the factory image, make
  expansion idempotent, and keep boot recoverable with a dedicated storage log
  and backend status if expansion fails.
- Replace the updater's fixed 400 MB free-space gate with a requirement derived
  from the installed application footprint plus a bounded staging reserve.
- Add an explicit official-Netdata fallback for Cloud connections rejected by
  Alpine's older packaged Agent. Pi Home downloads only Netdata's fixed HTTPS
  installer, reconstructs validated arguments instead of executing pasted
  shell, and reports installation progress or failure in Settings.

## 1.1.0-beta.23 Alpine Beta — 5 October 2026

- Replaced the separate Netdata token and Room fields with one paste box for
  the complete official Netdata Cloud connection command.
- Parse only the claim token, Rooms and official Cloud URL from that command;
  pasted shell is never executed, logged or retained.
- Configure the already-installed Agent through Netdata's current private
  `claim.conf` method and restart only Netdata, avoiding the obsolete helper
  that was rejecting otherwise valid claims.

## 1.1.0-beta.22 Alpine Beta — 5 October 2026

- Added authenticated physical-screen view controls to Diagnostics so Recent,
  Daily, New Releases, Browse and Now Playing can be opened on the actual GTK
  touchscreen before capturing it for visual verification.
- Made the Pi Home favicon follow the selected Fresh Mint or Roon theme across
  Settings, sign-in, Bus Times, Home and the Roon controller.
- Renamed the global updater action to “Check and install” so its immediate
  installation behaviour is explicit.

## 1.1.0-beta.21 Alpine Beta — 5 October 2026

- Render diagnostic screenshots from the live GTK touchscreen tree, including loaded album artwork, so Cage/DRM direct scan-out cannot silently produce a valid but completely black image.
- Schedule capture on GTK's main loop and return a clear error when the application cannot produce a drawable frame.

## 1.1.0-beta.20 Alpine Beta — 5 October 2026

- Moved Daily recommendation context out of the cover artwork and into a clear
  all-caps section heading. The source album is now the first ordinary card in
  that section, retaining the purple duotone treatment without an overlay.
- Enforced a hard viewport around every complete discovery card, preventing an
  unusually long album title from changing column width or breaking the grid.
- Retuned Recent and New Releases independently after device review: Recent is
  larger again without returning to its crowded size, while New Releases uses
  more of the available canvas.
- Removed the final Browse-view right inset from the touchscreen discovery
  canvas and now test both inner Daily swipe rows against the display edge.

## 1.1.0-beta.19 Alpine Beta — 5 October 2026

- Extended the native Discover viewport through the touchscreen page's 28 px
  right inset, so Daily's horizontal rows now clip at the physical display
  edge while the header clock and bottom navigation retain their alignment.
- Added a real Alpine GTK allocation assertion for that edge-to-edge behaviour.

## 1.1.0-beta.18 Alpine Beta — 5 October 2026

- Rebalanced the touchscreen discovery canvas against Browse: Recent now uses
  smaller four-column covers with more breathing room, while New Releases is
  reduced slightly so neither grid crowds the clock or right edge.
- Replaced the variable Daily recommendation banner with a fixed-size seed
  album card. Its real cover receives the same purple duotone treatment as
  mixes, “Inspired by” is overlaid on the art, and the album and artist remain
  in fixed two-line ellipsized slots below it.
- Added the bundled record-cover placeholder to Now Playing immediately at
  startup and whenever the track artwork changes, preserving the square layout
  while the real cover downloads instead of briefly widening the transport.

## 1.1.0-beta.17 Alpine Beta — 5 October 2026

- Turned first-run credentials into an appliance-owned flow: the owner chooses
  the device/SSH username and a confirmed 8–128 character password. Simple
  passwords receive a warning but remain allowed, using the BusyBox `chpasswd`
  path confirmed in the Alpine image rather than interactive `passwd` policy.
  No universal password is shipped, and credentials are excluded from progress
  data and command output.
- Added Netdata appliance management to System → Services for the already
  installed Agent: running state, version, local dashboard, Cloud claim state,
  Connect/Reconnect and Disconnect. The root helper selects the claim interface
  supplied by the installed Netdata version and restarts only Netdata; it does
  not replace or rerun the Agent installation.
- Added System → Access controls for changing the local device/SSH account from
  Pi Home, preserving the separate web-access controls and leaving room for
  additional appliance settings without exposing Alpine administration.
- Reworked touchscreen discovery geometry: Daily recommendation context is a
  square in-flow tile, horizontal rows bleed cleanly to the right edge, Recent
  and New Releases use larger fixed-size four-column cards, and long titles get
  a stable text slot. New Release details now show their track list with a
  dedicated Back rail instead of the Browse/Search sidebar.
- Reduced horizontal swipe jank by loading artwork only for cards close to the
  horizontal viewport, avoiding unnecessary downloads and repaints for the
  entire off-screen row.

## 1.1.0-beta.16 Alpine Beta — 5 October 2026

- Enables actual kinetic touch scrolling for Recent, Daily and New Releases while keeping their scrollbars visually hidden.
- Gives discovery artwork, titles and credits fixed slots so sparse results do not expand and one-line/two-line titles do not shift cover positions.
- Clears the previous Browse rail and grid immediately when opening Surprise Me, showing one discreet loading state until its preview arrives.

## 1.1.0-beta.15 Alpine Beta — 5 October 2026

- Standardises the appliance, updater, workflow and image names on **Alpine Beta**.
- Moves ongoing Alpine work to `alpine-beta` while retaining `alpine-appliance-prototype` as a compatibility bridge for devices running beta.14 and earlier.
- Removes internal branch terminology from the web settings update status.

## 1.1.0-beta.14 Alpine — 5 October 2026

- Resets seatd between stopping and starting Cage during an application update, clearing the broken DRM-session pipe observed on the physical touchscreen.
- Removes the old display revision marker immediately before launch so health checks accept only a marker published by the newly started GTK process.

## 1.1.0-beta.13 Alpine — 4 October 2026

- Repairs touchscreen updates on the small Alpine filesystem: remove inactive managed releases before staging, remove failed staging trees, and prevent repeated taps from launching overlapping updater processes.
- Waits visibly for a trustworthy Pi clock before HTTPS update checks instead of failing against certificates while the clock is still at the Unix epoch.
- Seeds a usable clock before networking on Pi hardware without an RTC, saves it at shutdown, enables Chrony burst requests and permits an immediate step whenever network time becomes available.

## 1.1.0-beta.12 Alpine — 4 October 2026

- Replaces Daily's arrow overlays and paging with roomy, kinetic horizontal swipe tracks.
- Centres the restart confirmation card within its full-screen dimmed backdrop.
- Fetches touchscreen Discover independently of the general device refresh and cancels obsolete Daily work when another page is selected, avoiding a private-API backlog.
- Bounds Recent history more tightly so its first useful view arrives sooner.
- Connects Alpine sleep and brightness requests to the root-owned backlight helper, extinguishing the panel backlight while keeping touch available to wake it.

## 1.1.0-beta.11 Alpine — 4 October 2026

- Makes an unchanged update self-repair a stale touchscreen process instead of incorrectly returning “unchanged”.

## 1.1.0-beta.10 Alpine — 4 October 2026

- Replaces Daily pagination with compact swipeable carousels and a continuous Mixes → For You feed.
- Loads bounded Roon previews progressively instead of waiting for complete private graphs.
- Replaces unreliable genre glyphs with a coherent bundled SVG icon set.
- Adds a full-screen dimmed restart confirmation and hides Discover scrollbars.
- Verifies the exact source revision running on the physical GTK display before an update is accepted.

## 1.1.0-beta.9 Alpine — 4 October 2026

- Fix updater restart ordering: stop the display once, restart backends with
  OpenRC dependency cascades disabled, then start the display once. Avoid the
  display service lock conflict observed on the physical Pi during beta.8 update.
- Retain the activation failure reason in rollback status. Existing beta.7/8
  updater processes need the one-time SSH restart override for this update.

## 1.1.0-beta.8 Alpine — 4 October 2026

- Rename Dailies to Daily, with Mixes and For You. Show four larger cards per
  page in mixes and recommendations; keep remaining selections accessible via
  Previous/Next and leave the full mix track list unchanged.
- Replace font-dependent genre, playlist and discovery fallback symbols with
  bundled SVG icons shared by native GTK and web views. Keep Roon purple and
  Fresh Mint colouring, including unknown genres, without extra fonts.

## Alpine prototype — unreleased experiment

- Rebuild with all accepted Alpine fixes. Keep private updater command logs,
  separate dependency preparation progress stages and explain TLS clock failures.
  Hide epoch-era clock values while network time arrives; log the GTK renderer
  so graphics performance can be diagnosed without guessing.
- Fix diagnostics to read OpenRC service names on Alpine. Add an explicit system
  tools installer for existing images, a confirmed native touchscreen reboot
  action and a transparent Cage cursor theme alongside child-widget cursor hiding.
- Identify Alpine builds explicitly in Software version labels. Setup and web
  password changes accept eight characters minimum; confirmation remains required.
- Include automatic network time, screenshot capture tooling and optional OpenRC
  Netdata controls. Recover late Goodix startup and persist tested touch mapping.
- Fix bare-metal exports retaining Docker identity: remove container markers and
  reset injected hostname/DNS files before creating the disk image. Verify OpenRC
  detects a physical system, not Docker. Enable boot/service logs and include
  filesystem check tools; do not silently abandon crashed services after five retries.
- Alpine prototype and new installers use Pi Home installation/configuration/state paths, with legacy compatibility links preserving existing settings and pairing.
- Add a native first-boot setup wizard with device naming, Ethernet/Wi-Fi,
  Roon authorisation and zone selection, display/theme/timezone, a web settings
  password and completion restart. Include a touch keyboard and resumable setup.
- Restrict privileged onboarding to a local account-checked Unix socket helper;
  validate input, preserve boot settings and lock setup mutations after Finish.

- Add an isolated ARM64 Alpine image factory, OpenRC service definitions,
  Ethernet-first native Cage/GTK boot path and unique first-boot credentials.
- Reject unsupported privileged OS actions rather than queue them to a missing
  systemd worker. Normal Raspberry Pi OS behaviour is unchanged.
- Keep the prototype outside application update channels. Hardware boot,
  touchscreen acceptance, Wi-Fi onboarding and safe OS updates remain pending.

## 1.1.0-beta.7 — 4 October 2026

- Focus on the native touchscreen: use Browse-style left secondary navigation for Recent (Added/Listened) and Dailies (Mixes/Recommendations); remove the competing top-row controls and More Recommendations button there. Web layout remains unchanged.
- Rename the native Daily Mixes tab to Dailies. Keep recommendations on demand, rather than loading them before mixes.
- Reuse Browse's landscape grid sizing for Recent/Dailies, with four columns at 1280px and compact covers capped at 172px. Keep rounded artwork, centred two-line titles and lazy thumbnails.
- Show mix selections in Browse-style playlist rows with fixed 84px thumbnails, title and artist; keep Play This Mix/Queue This Mix above the rows and Back pinned at bottom left outside scrolling content.
- Keep section navigation and a context-restoring Back when opening album/track actions from Recent/Dailies. Loading stays inside the right content pane; stop polling Discover while viewing those action pages.
- Preserve native New Releases and Surprise Me layouts and all web layouts. No new API calls or playback behaviour.

Verification: 128 Python and 91 Node checks pass, including widget-construction/navigation tests for the sidebar, loading placement, playlist rows, context-preserving Back and four-column sizing. These tests do not perform real GTK allocation or prove physical touch/scroll behaviour; touchscreen acceptance is still required. No remote installation, restart or playback.

## 1.1.0-beta.6 — 4 October 2026

- Load Daily Mixes independently; fetch Daily Picks only when More Recommendations is requested, on web and touchscreen. Keep mix tracks and whole-mix controls.
- Replace fixed read-only connection/graph sleeps with bounded readiness checks. Skip obsolete queued page requests per client without dropping another device's work; retain cache/coalescing, read serialization and isolated playback safeguards.
- Add Recently Listened and Recently Added modes under Recent. Added uses an actual import-date-descending library query, retains only the first 20-album page and releases/disposes it. Web mode URLs support Back/Forward.
- Fetch native Discover artwork only for visible/nearby cards; web artwork remains lazy-loaded.
- Show player/zone names rather than a hard-coded BluOS label on external-input screens.
- Use consistent 14px desktop music/Discover menus and larger, centred portrait Browse categories, with a narrower-phone adjustment. Native menu sizes remain unchanged.

Verification: 122 Python and 91 Node checks pass. Read-only live Core checks returned five mixes, 20 Added albums, 20 recent albums, 20 New Releases and five recommendation groups. One measured run: Mixes 0.51s, Added 0.42s, Recent 0.68s, Picks 0.70s, New Releases 2.05s; these are local reader timings, not guaranteed end-to-end UI timings. New Releases still fetches Roon's full data response because its API lacks page arguments. Local browser fixtures verify phone/desktop navigation and labels; physical GTK/audio acceptance remains pending. No remote installation, restart or playback during verification.

## 1.1.0-beta.5 — 4 October 2026

- Optimise portrait web Browse with a horizontal category row above two wider artwork columns; preserve landscape/native Browse.
- Hide the phone clock and centre a compact Discover menu beside the settings cog. Phone labels use Playing, Mixes and New; desktop/native retain their full labels.
- Rename Surprise to Surprise Me, including its reroll caption.
- Show mix tracks immediately again, retaining prominent Play This Mix and Queue This Mix controls.
- Replace differing music-page loading banners with one discreet Loading… status. Discover Back is in normal layout flow, preventing overlap with loading content. Queue status changes now refresh even while the queue is empty.

Verification: 120 Python and 83 Node checks pass. Browser-verification skills checked synthetic preview layouts at 320×740, 390×844 and 1280×720, including menu fit, larger Browse artwork, visible mix tracks and non-overlapping loading/Back. No browser errors detected. Native GTK acceptance remains pending; no remote installation/restart or audio playback.

## 1.1.0-beta.4 — 4 October 2026

- Keep music and Discover menus mutually exclusive across native periodic settings refreshes; remove Browse from Now Playing.
- Use the full New Releases label and remove redundant Recent, Daily Mixes and New Releases page headings.
- Add rounded clipping to native Discover artwork, larger fixed-size covers, centred two-line title space and theme-matched light scrollbars.
- Replace the full-width mix Back control with compact Back, use “Loading your mix…”, and collapse track previews behind View Tracks.
- Add explicit Play This Mix / Queue This Mix buttons using one experimental native Roon PlayMix call, exact zone/mix matching, bounded duplicate-request receipts and no automatic playback retries. Normal controls retain the official API.

Verification: 120 Python and 80 Node checks pass. Real-server read-only preflight verified the selected zone and mix identity; no playback call was executed. Local browser checks cover full navigation, card layout and collapsed mix controls at 1280×720 and 390×844. Whole-mix audio acceptance and physical GTK rendering remain pending. Stable remains v1.0.0; no remote installation/restart.

## 1.1.0-beta.3 — 4 October 2026

- Recent shows unique albums rather than repeated tracks, newest listen first, and opens album controls on both interfaces. Inspect up to 100 history events to produce up to 20 recent albums; skip entries without an album.
- Hide the Browse sidebar on Surprise in web and native displays, centring the album and its controls across the available width.
- Replace the remaining green loading-message background with a purple tint in the Roon web theme; keep Fresh Mint unchanged.

Verification: 117 Python and 76 Node checks pass, including album grouping/order/artwork and production asset serving. Mobile layout verified using synthetic preview data and the browser-check skills; actual GTK acceptance remains pending. No remote installation/restart.

## 1.1.0-beta.2 — 4 October 2026

- Serve the Discover JavaScript and stylesheet through the production controller asset allow-list. Their missing routes previously stopped web initialisation, leaving the default Mint theme, three-section navigation and a misleading Waiting for Roon message even when Roon was authorised.
- Refresh web asset versions and add regression checks against the production static handler for every referenced script/stylesheet and dynamically loaded Discover CSS.

Verification: 117 Python and 74 Node checks pass. No pairing identity, saved configuration or authentication changes; no remote installation or restart.

## 1.1.0-beta.1 — 4 October 2026

- Add Discover to web and native navigation, with Recent, Browse, Daily Mixes, NEW and Surprise; move existing exploration out of Now Playing without changing clock placement.
- Retrieve actual Roon listening history, personalised mixes, Daily Picks with seed/context, and New Releases for You through a pinned MIT research client. Preserve the official API for playback and queue actions; no RoonMCP.
- Isolate private-protocol reads in short-lived, memory-limited workers with a 20-second deadline, serial/coalesced requests, five-minute successful cache and one-minute failure backoff. Unpairing clears personal discovery data.
- Proxy registered artwork references locally, keep signed URLs/internal object references out of public responses, and retain neutral artwork placeholders on failure.
- Match selections by exact title/artist/category into official Roon controls. Ambiguous editions require manual selection; simply opening a result never selects Play.
- Give Discover tabs distinct routes with Back/Forward restoration, explicit loading/unavailable states, four-column landscape cards and two-column mobile cards. Shorten New Releases to NEW and prevent mobile navigation overlap.
- Apply matching black-to-purple duotone to Daily Mix artist portraits in the Roon theme only, using a web presentation filter and native GTK colour matrix; keep Fresh Mint portraits, album covers and shared artwork in full colour.

Verification: 117 Python and 72 Node checks passed; real-server read-only data and sample official action menus resolved; local browser checks passed at 1280×720 and 390×844. Physical GTK/touch acceptance and audio-confirmed play/queue are pending. Whole-mix play/queue is not implemented; this beta offers bounded mix-track previews and individual-track controls. Stable remains v1.0.0; no remote installation/restart was performed.

## 1.0.0 — 4 October 2026

- Consolidate current installation/configuration/recovery documentation; remove superseded Chromium kiosk and unused design/planning artefacts.
- Use generic music-first new-install configuration and ignore private/runtime/build state; preserve saved appliance settings.
- Add persisted Stable/Beta release-channel selection and an authenticated release-availability endpoint; select exact published GitHub tags by semantic version and never silently downgrade.
- Display installed version, selected channel, latest release and update availability in Software settings; distinguish unavailable release checks from up-to-date status.
- Harden installer source copying, include missing capture/download dependencies and add CI checks.
- Keep the official Roon API as the v1.0 foundation and document gated Discover research separately.

Verification limits: the running-Pi audit, fresh-install rebuild and physical touchscreen acceptance remain unverified. Publication proceeds at the user's explicit request without changing the running Pi.

## 0.11.35 — 4 October 2026

- Give native search results two directly allocated scroll areas instead of nesting them inside the ordinary browser viewport; load all bounded preview artwork independently of that hidden viewport.
- Simplify search to Top Results and Artists in the left column, Albums and Tracks in the right. Remove Works, Composers and Playlists from search previews on both interfaces.
- Open search album results directly into their track list when Roon returns a redundant single-album preview, and skip that preview on Back without triggering playback.
- Remove the search-field focus outline on desktop, mobile and native touchscreen.

## 0.11.34 — 4 October 2026

- Give Browse sections, queries and result drill-downs distinct URLs with safe Back/Forward restoration using fresh Roon keys rather than replaying playback actions.
- Show search loading immediately, skip stale responses, and load independent category previews in parallel.
- Show desktop results in three columns, with neutral missing-artwork icons; use two independently scrolling touchscreen columns with four previews per group and larger headings.
- Remove pressed-row tint and native search focus decoration; accent the touchscreen Search button in the selected theme.
- Add Services → Bus → Show Bus Times, enabled by default. Disabling it hides bus navigation, stops arrival polling, and prevents automatic bus-page selection for music-only installations.

## 0.11.33 — 4 October 2026

- Web search preserves the selected theme background instead of covering the page in gray.
- Shared Roon search shows up to five actual matches per category, plus View all, with independent category sessions for reliable opening and returning on web and native displays.
- Web music views and settings tabs now have URL fragments, browser Back/Forward support, and settings sub-tab deep links.

## 0.11.32 — 4 October 2026

- Simplify desktop and mobile web search to a large input with Search and Cancel, using the device keyboard instead of a custom on-screen keyboard.
- Support Enter-to-search and Escape-to-cancel, with clearer library/TIDAL placeholder text. Leave native touchscreen search unchanged.

## 0.11.31 — 4 October 2026

- Slightly reduce desktop browser clocks without changing mobile or native clock sizing.
- Separate the missing-artist silhouette's head and shoulders.
- Add neutral local SVG artwork fallbacks to native artist cards and profiles, retained when artwork fetching or decoding fails.

## 0.11.30 — 4 October 2026

- Align the clock at identical upper-right offsets across Home, Bus Times and every music view; add a live Singapore clock to Now Playing, browsing and external inputs.
- Match the Rune bus background to the Home and music gradient, and align the bus heading with Home.
- Reserve a separate mobile navigation row so music tabs do not overlap the clock.

## 0.11.29 — 4 October 2026

- Theme-coloured Pop/Rock symbol and centred genre labels with more bottom padding.
- Add the Singapore clock to Home; retain transparent navigation in both themes.
- Strengthen bus card borders and group the live-data footer directly beneath the cards, retaining compact mobile layouts.

## 0.11.28 — 4 October 2026

- Remove navigation and settings-cog backplates in both web themes and provide hand-pointer cursors on the top menu.
- Align browse navigation and alphabet scrubber with consistent outer margins; remove the repeated amplifier name on external-input screens.
- Show neutral artist silhouettes or record icons for missing and failed browse artwork, including the artist profile.

## 0.11.27 — 3 October 2026

- Fix mobile portrait bus cards: put each route number beside the arrivals, reduce spacing and typography, and keep all arrival times inside their cards.
- Reserve room for footer and bottom navigation, with vertical scrolling on especially short portrait screens rather than clipping the data. Leave native touchscreen and landscape styling unchanged.

## 0.11.26 — 3 October 2026

- Add System → Diagnostics → Capture display, with an image preview and timestamped PNG download.
- Capture the actual Wayland touchscreen output from the native session using grim, installed by the updater. Do not change display mode or write screenshot files to disk.
- Keep the capture behind web-settings authentication, limit image size and request duration, reject overlapping or unmatched captures, and show clear failures if the display is unavailable or capture is unsupported. No image is sent to central logging.

## 0.11.25 — 3 October 2026

- Active Roon playback keeps Automatic mode on Roon even during scheduled sleep hours. Explicit manual display modes, including Sleep, remain respected.
- Exclude active playback from native inactivity sleep, wake into Now Playing when playback begins or resumes a sleeping panel, and restart the inactivity countdown after playback stops. Keep browsing available during playback.

## 0.11.24 — 3 October 2026

- Make ARTIST ALBUMS uppercase and slightly larger (16px) on the native and web displays, without changing album rows or other headings.

## 0.11.23 — 3 October 2026

- Keep artist album rows and square thumbnails at a consistent size instead of expanding with available space or artwork dimensions.
- Move the existing Play Artist action beneath the artist portrait and name, and label the adjacent album list Artist albums. Preserve the original Roon action rather than relabelling it Shuffle.
- Apply the same layout to the native touchscreen and web display. Leave the artist portrait/name panel and other browsing sections intact.

## 0.11.22 — 3 October 2026

- Use theme-specific purple Home icons in the Roon palette, including refreshing them when the theme changes.
- Make the bottom-left Back button taller with white text on its borderless grey background.
- Put a compact Mint/Roon button choice beneath Daily Controls instead of a full-width theme dropdown. Improve remaining settings-dropdown text contrast.
- Complete album playback and switch to Now Playing even when Roon returns an updated track list after Play Now. Preserve the album artwork through action menus.
- Replace the Library/TIDAL search dropdown with one combined Roon search, retaining the core's result order and removing catalogue link markup from artist names. Source badges are omitted because the browse API does not reliably identify the source.

## 0.11.21 — 3 October 2026

- Add Library / TIDAL search selection on native and web displays. Discover Roon's TIDAL search prompt dynamically, retain its browse session for result navigation and playback, and report clearly when the service or search prompt is unavailable. TIDAL requires a connected subscription in Roon.
- Highlight Surprise itself and hide its redundant Back button. Align the browse rail with the zone heading and move a smaller, borderless grey Back button to the bottom-left, with theme-coloured text.
- Show the lead artist instead of the full contributor list in Now Playing and Queue, preserving artist names such as AC/DC and Earth, Wind & Fire. Keep the artist portrait and name panel.
- Add a touchscreen theme selector above Daily Controls and move the controls upward. Synchronise the selected theme across touchscreen, web settings, Roon, Bus Times and Home, including checkboxes, action buttons, playback controls and queue highlights. Keep bus route colours unchanged.
- Remove the circle behind the current-track play marker. Use the active theme's accent for the triangle and neutral or violet-tinted surfaces for the Roon palette.

## 0.11.20 — 3 October 2026

- Restore the artist portrait and name column on native and web displays. Remove only the biography and its unavailable-information message; retain all other v0.11.19 changes.

## 0.11.19 — 3 October 2026

- Left-align the browse section names and highlight the selected text in the accent colour, with no underline or filled button.
- Put a rounded gray Back button below the left menu, restoring the full artwork browsing height; recognise native rightward Back gestures by distance rather than velocity.
- Complete Roon's nested Play Album → Play Now action and switch to Now Playing after successful playback, without the small playing notification.
- Remove the unreliable artist biography column so unavailable information no longer takes up browsing space.
- Restore separate white bus-stop names and gray stop codes in the top row, and give the clock a lighter, brighter-gray cut.
- Add Display → Appearance → Display style: Fresh Mint (default) or a Roon-inspired charcoal/violet palette. Changes apply without rebooting and preserve the bus route colours.

## 0.11.18 — 3 October 2026

- Enlarge Surprise artwork and album/artist text, separate the reroll and play controls from the artwork, and add Surprise and Play Now captions.
- Move the bus stop title alongside the clock, widen the route rows and enlarge three-route arrivals while preserving space for the bottom navigation.
- Use a tighter section rail with an accent underline rather than rounded selected buttons.
- Disable horizontal gallery scrolling and side overshoot; add swipe-right Back with a visible, non-overlapping fallback control.
- Add an artist overview column with the selected Roon portrait and name plus asynchronously loaded, cached biographies matched through MusicBrainz and linked Wikipedia articles. Ambiguous names show no biography.

## 0.11.17 — 3 October 2026

- Constrain native artwork grids to the physical display width so the clock and alphabetical scrubber remain on-screen.
- Keep Surprise! available from every browsing section, with larger centred artwork between reroll and play symbols; Back returns to the originating section.
- Switch successful Play Now and Surprise album playback straight to Roon Now Playing, without the small playback notification.
- Replace System accordions with compact Device, Services, Logging, Diagnostics, Software and Password tabs, including keyboard navigation.
- Keep bus routes ordered 40, 42, 401 and use stable blue, green and purple colours on web and touchscreen regardless of the reporting day.

## 0.11.16 — 3 October 2026

- Install the required Python GI Cairo bridge on upgrades as well as fresh installations, fixing the missing gi._gi_cairo startup crash.
- Verify GTK/Cairo imports before restarting services, and check that the touchscreen stays active without restarting before reporting update success.
- Add regression coverage keeping installer graphics dependencies in sync with the updater.
- Rename the sidebar and album-preview reroll controls to Surprise! on both web and touchscreen.

## 0.11.15 — 3 October 2026

- Match Surprise Me / Again to the other mobile sidebar labels and centre the top navigation in the space beside Settings.
- Make Surprise Me a dedicated album preview takeover on web and touchscreen, with large centred square artwork, album title and artist.
- Keep playback unchanged until Play Album is pressed; Surprise Again chooses a different album without interrupting the current music.
- Restore the existing album browse page and scroll position when leaving the preview.
- Add regression coverage for preview-only selection, explicit playback and returning to browsing.

## 0.11.14 — 3 October 2026

- Make Search a full-size sidebar menu item on both displays.
- Size native artwork squares from the available width, reduce column gaps, and increase row spacing while keeping five genre columns where they fit.
- Draw the native alphabet dot and letter together using one centre; use the same shared geometry on the web display, including resized layouts.
- Keep separate in-memory Roon browsing stacks and saved scroll positions for Albums, Artists, Genres, Playlists and Search.
- Finish scroll restoration before dispatching queued navigation so older callbacks cannot reposition a newer page.
- Expose Roon's native Shuffle Genre action directly on a genre page.
- Add Surprise Me and Surprise Again to Albums: play a randomly selected whole library album, avoid immediate repeats, and keep the current browse position intact.
- Include the Cairo integration dependency required by the native scrubber drawing.

## 0.11.13 — 3 October 2026

- Submit search text directly to Roon's search hierarchy, instead of looking for an input prompt in the empty results.
- Correct the same search-request bug in album and artist detail lookups.
- Add regression coverage for prompt-free search, repeated queries, and opening results through to playback actions in the selected zone.
- Leave the display layout unchanged while the search fix is verified on the device.

## 0.11.12 — 3 October 2026

- Add a small Search button beneath Playlists, opening a large search field and on-screen keyboard on the touchscreen and web display.
- Make the top-left Pi Home heading return to Overview; remove redundant settings links from panel headings.
- Remove gallery hover effects and increase the spacing between tile rows and columns.
- Keep the alphabet letter aligned with the live thumb geometry and prevent results from moving it during a drag.
- Prioritise visible artwork, reset scroll position on Back, retain more cached thumbnails, and retry temporary image failures.
- Enlarge the queue playing symbol and durations, with more right-hand padding.
- Run external album enrichment independently of Roon search failures, bound stalled Roon lookups, and retry temporary enrichment failures twice.

## 0.11.11 — 3 October 2026

- Index actual Roon alphabet offsets instead of assuming browser sort order; cache the index for subsequent jumps.
- Support backward paging after alphabet jumps and retain the visible position when earlier results arrive.
- Keep the latest requested letter when a browse request is already running; avoid scrubber updates during layout rebuilds.
- Position the touchscreen letter from the actual slider bounds and track visible artwork rows.
- Restore square play/action icons and square artwork, with a tighter five-column genre grid.
- Hide disc/track numbering prefixes in album track titles without stripping genuinely numeric song names.

## 0.11.10 — 3 October 2026

- Correct the touchscreen alphabet thumb direction so it follows the current letter.
- Remove genre label gradients and restore smaller playlist names beneath their tiles.
- Hide browsing loading text while retaining error messages.
- Match play-action containers to track thumbnails and align the sidebar and Back margins.
- Fix the web genre label renderer referencing artwork outside its scope.

## 0.11.9 — 3 October 2026

- Measure daytime inactivity from the latest raw touchscreen contact, including scrolling gestures that GTK consumes without a normal button press.
- Turn the Overview software status into a useful version summary and a direct link to the opened Software section.
- Add compact System section anchors, a Pi Home settings return link, roomier main tabs and animated disclosure chevrons.
- Restyle the Albums and Artists A–Z control as a subdued fixed rail with only its thumb and tracking letter highlighted.
- Put wrapped Genre and Playlist names inside fixed-size artwork tiles and expand genre-specific iconography.
- Move Back to one consistent top-right position, match play-action artwork to track thumbnails and reduce album track credits to the album artist.

## 0.11.8 — 3 October 2026

- Prevent the four-column browser grid from widening the touchscreen beyond the physical panel and clipping the clock, selectors and rightmost artwork.
- Remove the browser breadcrumb row and divider, tighten the left section rail, and anchor Back at the rail's bottom only when it is needed.
- Present Genres and Playlists as visual tiles, with genre-specific symbols, playlist placeholders, larger names and no redundant item counts.
- Standardise Play Album and other action artwork to the same footprint as track thumbnails.
- Enlarge Queue artwork, titles, metadata and durations, remove the cyan current-item edge, and overlay a play marker on the current track.

## 0.11.7 — 2 October 2026

- Replace the growing browser scrollbar with a fixed A–Z scrubber for Albums and Artists, including a floating current-letter indicator and direct paged jumps into the Roon library.
- Add a persistent left section rail for Albums, Artists, Genres and Playlists on both the touchscreen and web player.
- Remove TIDAL and the non-functional touchscreen search interface to give the artwork and track lists more usable height.
- Keep album collections artwork-first while opened albums use full-width track rows with duration metadata where Roon supplies it.
- Compact the browser breadcrumb and adapt the new rail and scrubber for portrait web screens.

## 0.11.6 — 2 October 2026

- Restore the Albums library to the artwork-first tile grid.
- Force an opened album's contents into track rows, including when Roon reports Play Album as an `action_list` rather than a plain action.
- Replace the undersized A–Z index with a conventional visible scrollbar in both the touchscreen and web browser views.

## 0.11.5 — 2 October 2026

- Mount the touchscreen search keyboard inside the browser layout so it is visibly allocated whenever Search receives focus.
- Present album collections and album contents as readable lists rather than dense artwork grids.
- Replace browser chevrons with track durations when Roon supplies duration metadata, leaving a clean edge when it does not.
- Remove the blue-green selection keyline from Play, Add Next and other browser action rows.
- Use the standard play symbol for Play Album and Play Playlist actions.
- Add an A–Z quick index to the right edge of Albums and Artists, backed by direct paged jumps rather than loading the entire library.

## 0.11.4 — 2 October 2026

- Reuse the selected album's artwork for child track rows when Roon omits redundant per-track image keys, without applying artwork to action rows.

## 0.11.3 — 2 October 2026

- Reduced Library to four useful destinations—Artists, Albums, Tracks and Composers—by removing the redundant Search and Tags cards.
- Made touchscreen search reliably open its built-in keyboard when either the field or an empty Search action is tapped.
- Simplified browser headers with a smaller Back control, vertically aligned single-line titles and no duplicate artist subtitle.
- Kept playlists and their tracks in readable list layouts while preserving artwork grids for albums and artists.
- Replaced generic blank action artwork and repeated PLAY labels with purpose-specific play, play-from-here, add-next, queue and shuffle icons.
- Replaced manual Load More controls with automatic incremental loading near the end of the scroll area.
- Increased touchscreen artwork fetching from one worker to three so visible grids populate promptly without blocking the interface.

## 0.11.2 — 2 October 2026

- Prevented the touchscreen and web interface from queuing duplicate update jobs, and discard duplicate requests left behind by an older release.
- Added a single-instance updater lock, bounded network and installation timeouts, and an explicit terminal failure status instead of an endless Working state.
- Skip operating-system and Roon dependency installation when the installed dependencies already match, substantially reducing routine update work and device load.
- Capped the privileged updater to one CPU core at low CPU and I/O priority while keeping the display responsive.
- Improved update progress handling in both interfaces, including a clear already-running state and a client-side safety timeout.

## 0.11.1 — 2 October 2026

- Reworked the Browse root into four large visual destinations: Library, Playlists, Genres and TIDAL.
- Added artwork-first grids for image-heavy Roon levels, hiding album captions while retaining useful artist labels.
- Enlarged browser typography, touch targets, list artwork and navigation controls throughout the touchscreen view.
- Added a built-in touchscreen QWERTY keyboard for Roon search, including Space, Backspace, Clear, Close and Search actions.
- Replaced the heavy search-field keyline with a restrained underline and increased fetched artwork resolution for sharp large covers.

## 0.11.0 — 2 October 2026

- Added a native Roon Browse view to both the touchscreen and web player, including Roon library navigation, search, album artwork and action rows.
- Reused Queue's bounded kinetic-scrolling layout so long browser lists cannot displace the fixed top selector or bottom navigation.
- Kept independent Roon browsing sessions for the touchscreen and each browser, with hierarchy Back navigation and incremental loading for long lists.
- Added an optional **Show Browse view** setting under Roon & BluOS; disabling it removes Browse from both interfaces.

## 0.10.8 — 2 October 2026

- Make an explicit manual Sleep cancel any earlier temporary tap-to-wake allowance.
- Hold the local sleep screen while the controller confirms the new mode, preventing a stale poll from switching the backlight on again.
- Retry a failed manual sleep request and log each transition for targeted diagnostics.

## 0.10.7 — 2 October 2026

- Return the web update control to normal page flow so it cannot obscure settings content.
- Place View display directly beneath the update control in the masthead.

## 0.10.6 — 2 October 2026

- Align the fixed web update control with the centred settings wrapper instead of the browser window edge.

## 0.10.5 — 2 October 2026

- Added an always-visible Check for updates control at the top-right of web settings.
- Unified both web update controls so they share disabled/progress state and cannot queue overlapping installations.
- Reloaded web settings automatically after the updated Pi Home services come back, making the newly installed version immediately visible.

## 0.10.4 — 2 October 2026

- Fixed manual Sleep immediately waking again when the low-level copy of the Sleep-button touch reached GTK after the panel had gone dark.
- Wake handling now compares the original kernel contact time with the moment sleep began, so only a genuinely new touch can wake the display.
- Applied the same fresh-contact guard when entering daytime inactivity sleep.

## 0.10.3 — 2 October 2026

- Added overflow-aware Now Playing text movement for long track and artist/album names: pause for ten seconds, scroll at a readable speed, pause at the end, then return.
- Kept short text static, recalculated movement after viewport changes and respected reduced-motion preferences without polling.
- Added opt-in OpenObserve logging with a bounded background queue, compact batching, retry backoff and a connection test in System settings.
- Logged operational state changes without sending listening history, Home Assistant entity IDs, artwork or credentials.

## 0.10.2 — 2 October 2026

- Added a safe compilation fallback for album enrichment: when Roon's track artists are not the album artist, Pi Home accepts MusicBrainz metadata only if the album search has exactly one exact-title match.
- Continued to reject ambiguous album titles rather than showing potentially incorrect information.

## 0.10.1 — 2 October 2026

- Collapsed the mobile Roon selector to the last word of each configured label so inputs fit as compact uppercase names such as TV, LP, ROON and QUEUE.
- Fixed album enrichment when Roon reports track collaborators instead of the album artist, while retaining exact album-and-artist validation.

## 0.10.0 — 2 October 2026

- Removed the redundant Back button from album details; tapping the large artwork now returns to Now Playing.
- Added an automatic, cached album-enrichment pass when the playing album changes, with no polling or touchscreen-thread work.
- Added confidently matched MusicBrainz release date, genre, album type, country, label, format, edition count and track count.
- Added a concise album write-up from a MusicBrainz-linked Wikipedia article, falling back to the artist's own Bandcamp album notes, with the source shown in the interface.
- Kept enrichment failure-safe: unmatched albums retain the Roon artwork, titles and track list without guessed metadata.

## 0.9.9 — 2 October 2026

- Fixed the main touchscreen Now Playing artwork at a genuinely smaller centred size instead of relying on a minimum-size rule that GTK could expand.
- Vertically centred the album/artist information while retaining the Back control at the bottom margin.
- Made the large detail artwork itself return to Now Playing when tapped, on both touchscreen and web.
- Shortened the native page heading from “Touchscreen settings” to “Settings”.
- Added deliberate spacing between every Settings checkbox and its label, including Roon Bridge and bus services.

## 0.9.8 — 2 October 2026

- Reduced the main touchscreen Now Playing artwork by 10% without expanding surrounding content.
- Doubled the album/artist Back target and anchored it at the bottom of the information column.
- Enlarged playback glyphs, elapsed/remaining times and the volume value without materially increasing their control circles.

## 0.9.7 — 2 October 2026

- Clarified the Roon naming fields as bottom navigation, top navigation play screen and top navigation queue names.
- Corrected the Home touchscreen header to “Pi Home” and aligned it vertically with Bus Times.
- Moved the album/artist Back control beneath the information column and made it smaller on both touchscreen and web.

## 0.9.6 — 2 October 2026

- Made the NAD/BluOS volume step controls truly circular by preventing GTK from stretching them with the volume row, and enlarged the volume readout with a lighter weight.
- Restricted Settings and Sleep header actions to their visible labels instead of broad invisible regions across the top row.
- Moved the Roon source indicator closer to the top edge and enlarged Home panel names and status text again.
- Simplified Touchscreen Settings into a flatter layout without the redundant tinted outer card, while restoring deliberate outer margins above and below it.
- Applied the configured Roon navigation name consistently across every web view and the web Settings screen.
- Stopped the example “Display settings applied” message from being reconstructed indefinitely from an old reboot marker.

## 0.9.5 — 2 October 2026

- Added separate editable names for the Roon Now Playing and Queue selectors, shared by the touchscreen and web player.
- Enlarged the external-input volume, circular step controls and mute target, while adding more space between source selectors.
- Rebalanced Touchscreen Settings spacing to keep its bottom actions fully visible within the 1280×720 display.
- Moved Bus Times content upward, softened secondary bus/footer text and enlarged Home tile labels for better distance legibility.

## 0.9.4 — 2 October 2026

- Fixed NAD/BlueOS source switching by preventing already encoded Capture URLs from being encoded a second time before the M33 `/Play` request.
- Removed the routine Debian package-index refresh from ordinary updates when every required system component is already installed, and made Node installation prefer its local cache.
- Added a quiet black appliance boot followed by a centred mint Pi Home startup mark, suppressing incorrectly oriented firmware and console graphics.
- Refined the 1280×720 touchscreen: stronger bus and Home borders, more separation between bus rows, a smaller stop heading, better header alignment and tighter Roon secondary navigation.
- Increased padding throughout Touchscreen Settings, separated its controls and condensed health information onto one line.

## 0.9.3 — 2 October 2026

- Fixed manual-sleep wake detection for the Goodix Touch Display 2 by accepting native multitouch contact-start events as well as legacy `BTN_TOUCH` events.
- Made native touchscreen logging unbuffered so the active low-level wake listener and each wake event are visible immediately in the service journal.
- Stopped unchanged Touch Display 2 configuration from generating another reboot requirement during every software update.
- Restored the web settings action bar's green keyline and made display/reboot messages temporary rather than permanently pinned.

## 0.9.2 — 2 October 2026

- Replaced ineffective generic Touch Display 2 input matrices with Raspberry Pi's supported Device Tree `swapxy`/axis-inversion calibration for non-desktop rotation.
- Split the 5-inch and 7-inch Touch Display 2 profiles so each uses its correct hardware overlay, while migrating the legacy combined profile to 7-inch.
- Added a persistent web action bar that follows the user across settings tabs, saves every dirty section together, shows centred status messages and keeps Reboot immediately available.
- Made display calibration explicitly report that a reboot is required and retain that prompt only for the current boot.
- Gave touchscreen Settings more vertical and horizontal breathing room.
- Matched the BluOS player refresh button to its field height, widened it and prevented its label from wrapping.

## 0.9.1 — 2 October 2026

- Corrected Touch Display 2 landscape input by using the inverse Wayland quarter-turn once, fixing the remaining 180° touch offset without changing picture orientation.
- Added a dedicated 1280×720 touchscreen layout with larger Settings controls, Roon selectors and touch targets while reserving room for both fixed navigation rows.
- Enlarged and vertically centred bus service numbers and arrival groups on the high-resolution landscape display.
- Added a configurable name for the Roon section in the touchscreen bottom navigation.

## 0.9.0 — 1 October 2026

- Reorganised web settings into Overview, Display, Automation, Services and System, with a compact responsive hierarchy on desktop and mobile.
- Added isolated section saves, persistent unsaved-change state, a fixed save bar and visible toast feedback so one page cannot overwrite unrelated settings.
- Moved common screen controls to Overview, display hardware to Display, behavioural rules to Automation and all maintenance actions into one System location.
- Added conditional Home Assistant and BluOS options, collapsible advanced groups and human-readable minute inputs for timeouts.
- Separated software-update progress from unrelated system actions and stopped routine web refreshes from collecting expensive diagnostics.
- Fixed Touch Display 2 landscape input calibration by applying the documented libinput rotation once, without a second compositor output mapping.

## 0.8.6 — 1 October 2026

- Added a confirmed **Reboot Pi** control to the web System settings.
- Routed reboot through Pi Home's existing fixed-action privileged broker without exposing arbitrary commands or broader sudo access.

## 0.8.5 — 1 October 2026

- Fixed Touch Display 2 touch coordinates after landscape rotation by applying the matching libinput calibration as well as binding touch to the DSI output.
- Corrected the opposing clockwise conventions used by Raspberry Pi settings and Wayland output transforms.
- Restored boot-console rotation so the new display is landscape from the beginning of startup.
- Scaled the native touchscreen typography, controls, artwork and Home icons for the denser 720p 7-inch panel.
- Stopped display changes and updates from causing multiple mid-install restarts; a display change now restarts only the touchscreen application.

## 0.8.4 — 1 October 2026

- Fixed Touch Display 2 rotation at the Cage/Wayland output layer, where the GTK application is actually rendered, instead of relying on kernel console rotation.
- Kept the original Touch Display on its established kernel rotation path to avoid reintroducing double rotation.
- Mapped Touch Display 2 input to the transformed DSI output so landscape picture and touch coordinates remain aligned.
- Added the lightweight `wlr-randr` output-management client to installation and update dependencies.

## 0.8.3 — 1 October 2026

- Replaced the lossy single-file privileged action handoff with an ordered atomic queue, preventing rapid sleep/wake, brightness or service requests from overwriting one another.
- Made the privileged broker continue draining later actions after an individual request fails and retained legacy request compatibility during updates.
- Kept the web Queue and album/artist detail views current while an external BluOS input is displayed.
- Reduced synchronous controller configuration reads to at most one per second without adding polling or a background process.
- Kept BluOS status and volume available when a player does not support Capture input browsing.
- Added a concise runtime architecture map and a prioritised V8 stabilization audit for subsequent reliability work.

## 0.8.2 — 1 October 2026

- Separated Roon views from BluOS inputs: Now Playing and Queue never change the amplifier source.
- Made Play explicitly reclaim Roon only when a physical input is active.
- Kept physical-input buttons responsible only for selecting their corresponding BluOS source.
- Added a dedicated full-screen GTK wake gesture plus a blocking Linux touchscreen event listener, removing reliance on GTK window events for manual wake.

## 0.8.1 — 1 October 2026

- Replaced the BluOS source dropdown with enabled inputs beside Now Playing and Queue.
- Added optional Pi Home display names for amplifier inputs.
- Fixed returning from a physical input to Roon by forcing a clean playback transition when BluOS left Roon reporting an already-playing state.
- Added a dedicated physical-input display with a large live volume number, large minus/plus controls and a compact mute button.
- Fixed manual touchscreen sleep becoming permanently unwakeable when its delayed wake-arm callback did not complete; fresh touches are now accepted using a deterministic gesture-tail guard.

## 0.8.0 — 1 October 2026

- Added lightweight NAD/BluOS amplifier discovery and configuration.
- Subscribed to the selected player using BluOS long polling, without a background polling loop.
- Added real amplifier input selection on both the touchscreen and web interface.
- Made the Roon screen pivot to a simplified external-input display with native amplifier volume control.
- Kept Roon metadata, queue and transport authoritative whenever Roon is the active source.

## 0.7.19 — 1 October 2026

- Fixed touchscreen sleep at the native backlight layer: sleep now writes brightness `0` while leaving panel power and the touch controller active, and wake restores the saved brightness.
- Added real updater progress stages covering version checks, download, dependencies, application files, services, readiness checks and touchscreen restart.
- Added a compact live update history to the web System page that reconnects through service restarts and highlights the current installation stage.
- Made touchscreen Settings refresh and display the current updater stage throughout installation instead of stopping at a generic queued or working message.

## 0.7.18 — 1 October 2026

- Prevented a manually selected Sleep override from surviving a Pi Home service restart or Raspberry Pi reboot and immediately blacking the touchscreen again.
- Startup now safely returns only an explicit Sleep override to Automatic; visible manual selections such as Roon, Bus Times and Home remain unchanged.

## 0.7.17 — 1 October 2026

- Added automatic recovery for a display pipeline left disabled by an earlier release, allowing this update to restore an already-dark panel without a reboot.
- The pipeline is enabled when waking but remains active during all future sleeps; only the native backlight is switched off.

## 0.7.16 — 1 October 2026

- Fixed the underlying touchscreen wake failure by keeping the Raspberry Pi display pipeline active while the panel sleeps.
- Sleep now switches off only the native Linux backlight, leaving GTK and the touch device able to receive the wake contact; no software dimming overlay or polling was added.

## 0.7.15 — 1 October 2026

- Made sleeping-screen wake detection accept both the start and end of a deliberate touch, covering panels that consume the first contact while restoring hardware power.
- Kept the guarded arming period after entering sleep, so accepting touch releases cannot revive the display from the gesture that put it to sleep.
- Added event-specific touchscreen wake logging to make any remaining hardware-path issue directly diagnosable.

## 0.7.14 — 1 October 2026

- Fixed the scheduled morning wake being immediately cancelled by the daytime inactivity timeout after a full night asleep.
- Reset the daytime inactivity clock when the overnight schedule ends, giving the newly awakened display its configured daytime interval from that point.

## 0.7.13 — 1 October 2026

- Restored reliable one-tap waking after manual or scheduled sleep by ignoring only the remainder of the initiating sleep gesture, then arming the next fresh touchscreen press.
- Unified manual-sleep waking with the global touchscreen activity path already used successfully by daytime inactivity sleep.

## 0.7.12 — 1 October 2026

- Made manual and scheduled sleep resistant to initiating releases and intermittent touchscreen ghost touches by requiring a deliberate double-tap to wake.
- Reset the wake gesture whenever the backend transitions into scheduled sleep and log only a confirmed wake, making unexpected transitions easier to distinguish from schedule-boundary resumes.

## 0.7.11 — 1 October 2026

- Kept the touchscreen update button in its in-progress state after a request is queued and surfaced the privileged updater's real status instead of immediately implying completion.
- Made the updater re-launch the newly fetched updater before installation so updater and system-component changes take effect during the same run.
- Prevented an unsupported status-light device from aborting an otherwise successful Pi Home application update.

## 0.7.10 — 1 October 2026

- Fixed a manual top-right sleep tap being immediately treated as a wake gesture by ignoring the release from the initiating tap.
- Changed the touchscreen artwork detail into a full-display takeover with near full-height artwork, information alongside it, and the normal interface heavily tinted behind it.
- Added a persistent System toggle for the Raspberry Pi ACT/PWR status lights. The restricted helper manages only recognised Pi LED devices, and the lights default to off after installation or update.
- Added a boot-time oneshot service that reapplies the saved Pi status-light preference without running a background process.

## 0.7.9 — 30 September 2026

- Fixed daytime inactivity sleep being immediately cancelled by incidental pointer, window or display events; only deliberate touch, click or key input now resets the timer and wakes the panel.
- Removed the outlined container around the fixed web dashboard navigation.

## 0.7.8 — 30 September 2026

- Added a configurable daytime touchscreen inactivity timeout that uses native panel power, wakes on touch, and leaves the overnight schedule authoritative.
- Added a lightweight album-and-artist panel to the touchscreen and web Roon views, opened by tapping the current artwork and populated asynchronously through Roon Browse with cached artwork and graceful metadata fallbacks.
- Renamed the main Music tab to Roon throughout the touchscreen, web dashboard, and display selector.

## 0.7.7 — 30 September 2026

- Made scheduled sleep take precedence over an open touchscreen Settings panel and stopped transient backend timeouts from incorrectly waking a sleeping display or forcing Bus Times.
- Replaced the malformed browser settings symbol with a clean stroked cog and added the Pi Home favicon to every display, sign-in, fallback and Roon page.
- Restored the browser navigation order to Music, Bus Times, Home on every page and gave the desktop navigation a taller inset panel with comfortable bottom spacing.
- Slightly enlarged the desktop bus-stop name and clock while preserving the compact portrait treatment.

## 0.7.6 — 30 September 2026

- Added the subscribed Roon Queue to the web Music view with instant Now Playing / Queue navigation, cached thumbnails and bounded touch scrolling.
- Retained up to ten recently departed queue entries in memory, shown dimmed above the current track on web and touchscreen, with best-effort replay through Roon's queue item IDs.
- Replaced the prominent web Settings pills with a fixed, understated cog and fixed the three-section bottom navigation consistently across Bus Times, Music and Home.
- Compacted the portrait Music view so artwork, transport and volume controls fit inside the available mobile viewport without page scrolling.

## 0.7.5 — 30 September 2026

- Increased the consistently rendered Home icon box from 48 to 72 pixels and restored balanced switch proportions, retaining sharp scalable SVG output and full-size touch targets.
- Routine application updates now restart the backend, Roon controller and native touchscreen services instead of rebooting the Pi; display profile and orientation changes continue to reboot when required.
- Rebuilt portrait web layouts: Music now isolates smaller artwork above non-overlapping controls, Bus Times uses a route-number headline above three arrivals, Settings uses a consistent rounded rectangle, and the bottom navigation has more breathing room.

## 0.7.4 — 30 September 2026

- Load Home SVG artwork through GTK's scalable icon path instead of the file-image path that ignored the requested pixel size and stretched wide symbols.
- Standardised Home icons on a centred 48-pixel optical box with consistent source stroke weight, and reduced the visual size of switch controls without shrinking their touch targets.
- Load current Roon state immediately in the web player and disable reverse-proxy buffering for subsequent live events, fixing a false “Waiting for Roon” screen behind Nginx without adding polling.
- Reflow the web Music view on portrait phones with album artwork above centred track details and playback controls.

## 0.7.3 — 30 September 2026

- Matched the web screen selector to the touchscreen hierarchy: Automatic/Sleep Now above Music/Bus Times/Home.
- Inset the Now Playing / Queue cyan indicator from the top edge to match the breathing room beneath the bottom navigation.

## 0.7.2 — 30 September 2026

- Hard-bounded the Queue scroller to the available central viewport so large queues cannot displace either fixed navigation bar.
- Disabled natural-size propagation from queue contents while retaining kinetic, scrollbar-free touch scrolling and tap-to-play rows.
- Moved the Music sub-navigation closer to the physical top edge, renamed the main Now Playing destination to Music and added breathing room inside the touchscreen brightness control.

## 0.7.1 — 30 September 2026

- Fixed the Queue viewport so it is height-bounded, touch-scrollable and does not hide the fixed bottom navigation.
- Prevented Queue's natural height from resizing the Now Playing, Bus Times and Home pages after switching views.
- Moved the Now Playing / Queue selector into the fixed top header so it no longer consumes album-art space.
- Arranged the web screen selector as Automatic/Sleep above Now Playing/Bus Times/Home, and forced admin assets to revalidate so the Home option appears immediately after updating.

## 0.7.0 — 30 September 2026

- Added a fixed, understated Now Playing / Queue selector within the Roon section while retaining the existing main navigation.
- Added a touch-scrollable, in-memory Roon queue with current-track treatment, compact metadata and tap-to-play-from-here navigation.
- Subscribe to the selected Roon zone's bounded queue as soon as it becomes available, rather than loading it on first view.
- Added a bounded thumbnail cache and background 96-pixel artwork loading so queue scrolling and GTK input remain responsive.
- Added a Roon setting to hide Queue and stop its subscription when the feature is disabled.
- Manual Bus Times, Now Playing, Home or Sleep choices now return to Automatic at the next schedule boundary; Home is also available in the web screen selector.

## 0.6.0 — 30 September 2026

- Removed full system diagnostics from the touchscreen startup path, delivered core Bus/Home/Roon state before artwork downloads, and pre-measured dynamic hidden views so their first tab switch does not pay deferred GTK layout costs.
- Added bounded startup/navigation timing traces to the system journal for evidence-based performance diagnosis without ongoing logging.
- Added a shared, persistent 10–100% hardware display-brightness control to touchscreen and web System settings; wake restores the chosen brightness rather than forcing full output.
- Added lightweight Netdata service detection and enable/start or disable/stop control using the existing fixed-action privileged broker, with no new daemon or background polling.

## 0.5.5 — 29 September 2026

- Replaced saved-brightness restoration with deterministic hardware behaviour: sleep only blanks panels that expose a power switch, while wake explicitly unblanks every detected panel and sets it to maximum hardware brightness.
- This also repairs low brightness left behind by earlier releases on the first wake after updating.

## 0.5.4 — 29 September 2026

- Made the touchscreen Roon Bridge switch persist by enabling or disabling its system service, rather than only starting or stopping the current process.
- Made touch wake force and confirm a physical backlight-on request, with a safe maximum-brightness fallback if the saved brightness is zero or invalid.
- Added stricter mobile Safari input containment and removed the non-editable Home touchscreen-layout summary.

## 0.5.3 — 29 September 2026

- Refined the mobile admin layout with a full-width final tab and Save button, constrained fields and aligned diagnostic values.
- Added web navigation between Bus Times, Now Playing and Home, with the Roon controller safely proxied through the main Pi Home address.
- Fixed View display so it preserves the public or reverse-proxied hostname instead of opening the appliance's loopback address.
- Added a compact browser Home dashboard and slightly increased spacing between touchscreen bus rows and Home controls.

## 0.5.2 — 29 September 2026

- Renamed the user-facing appliance from Pi Bus Time Display to **Pi Home**, while retaining existing repository, service, configuration and update paths for compatibility.
- Restored evenly centred arrival columns inside each bus row while retaining the subdued stop code without a separator dot.
- Corrected vertical Home controls so zero is at the bottom and 100% is at the top.
- Reworked fan, light and switch icons into a consistent rounded SVG family with grey hollow inactive and mint active states.
- Added left/right switch swipes in addition to tap-to-toggle.

## 0.5.1 — 29 September 2026

- Corrected the web sign-in focus order so username is selected before password.
- Replaced cramped touchscreen switches with clear checkbox controls and aligned the Daily Controls and Display rows.
- Left-aligned bus arrivals into consistent fixed columns and reduced the visual prominence of the stop code.
- Added purpose-drawn fan, light and switch SVGs to Home controls, with labels anchored beneath each device.
- Added vertical touch adjustment for light brightness and supported fan speeds, with debounced Home Assistant updates.

## 0.5.0 — 29 September 2026

- Redesigned touchscreen Settings with a balanced daily-controls and display layout plus fixed, equal-width actions at the bottom.
- Added touchscreen Roon Bridge and configured-bus visibility switches while retaining protected structural settings in web administration.
- Added an optional Home Assistant integration with protected URL, token and allow-listed entity configuration in a dedicated web Home section.
- Added a non-scrolling, state-aware 4×2 Home touchscreen panel for up to eight fans, lights, switches or input booleans.
- Kept Home Assistant credentials in the appliance secrets file and restricted touchscreen actions to explicitly configured, low-risk entities.

## 0.4.3 — 29 September 2026

- Added original and Touch Display 2 profile selection to the non-scrolling touchscreen Settings page.
- Added all four orientation choices with an explicit Apply & Reboot action.
- Added a compact touchscreen health summary for memory, load, temperature, Roon controller and Roon Bridge.
- Kept Wi-Fi, credentials and detailed configuration protected in web administration.

## 0.4.2 — 29 September 2026

- Corrected diagnostics that attributed the Roon controller process to the generic bus data service.
- Use systemd state as a fallback when a running component's process metrics are not visible.
- Explicitly enable and start the Roon controller during every update before readiness checks.
- Stop rebuilding unchanged GTK bus rows and re-selecting the visible page every two seconds.
- Make the Roon controller an explicit boot prerequisite of the native touchscreen service.
- Show the active Wi-Fi profile's real SSID instead of Netplan's generated connection-profile name.
- Move consistent dropdown chevrons in from the field edge and reserve appropriate text padding.

## 0.4.1 — 29 September 2026

- Removed expensive System and Wi-Fi diagnostics from the touchscreen's two-second display loop.
- Refresh configuration once per minute and System status only while touchscreen Settings is open.
- Replaced repeated Wi-Fi network listings with a lightweight active-connection query.
- Added swap use, SoC temperature and Raspberry Pi throttling state to diagnostics.

## 0.4.0 — 29 September 2026

- Added Automatic-mode Roon playback takeover with a configurable stopped-playing return delay.
- Added a configurable temporary wake timeout outside regular waking hours.
- Added adaptive two-, three- and four-service bus layouts without display scrolling.
- Added read-only live memory, load, uptime and per-component process diagnostics to System settings.
- Added selectable original Touch Display and Touch Display 2 resolution profiles with all four orientations.
- Added higher-resolution GTK scaling for Touch Display 2 while preserving the known-good original-display path.

## 0.3.0-rc.13 — 29 September 2026

- Removed the duplicate Wayland output transform that flipped the final display after the kernel had already rotated it.
- Made the kernel the sole picture-orientation authority and kept touchscreen calibration as a separate, matching libinput matrix.
- Hid the pointer directly in the native GTK display instead of disabling mouse-class input devices.

## 0.3.0-rc.12 — 29 September 2026

- Kept the last valid album cover through brief incomplete Roon metadata updates between tracks.
- Clear stale artwork only after five consecutive polls genuinely contain no artwork.

## 0.3.0-rc.11 — 29 September 2026

- URL-encoded Roon image keys so artwork containing reserved URL characters loads reliably.
- Reset the native artwork cache when playback or artwork disappears, allowing the same cover to load again when playback resumes.

## 0.3.0-rc.10 — 29 September 2026

- Made updates automatically reapply the saved display and touchscreen orientation before rebooting.

## 0.3.0-rc.9 — 29 September 2026

- Rotated touchscreen coordinates alongside the 180° display using libinput's calibration matrix.
- Suppressed non-touch pointer devices in appliance mode so Cage removes the mouse cursor.
- Strengthened physical display sleep with repeated backlight requests and the Raspberry Pi display-power fallback.

## 0.3.0-rc.8 — 29 September 2026

- Extended the display-orientation setting to the Raspberry Pi kernel console so the boot splash and GTK kiosk share the same orientation.
- Preserve the original kernel command line as `cmdline.txt.pi-bus-backup` before changing it.

## 0.3.0-rc.7 — 29 September 2026

- Added persistent appliance-mode display rotation with a simple 180° switch under System → Display.
- Added a command-line rotation recovery option and made 180° the initial appliance-mode orientation for this touchscreen mounting.

## 0.3.0-rc.6 — 29 September 2026

- Made software updates reboot automatically after successful service verification.
- Made sleep physically power down the official touchscreen backlight, while retaining touch-to-wake and the optional clock mode.
- Added a reversible Cage-based appliance mode that boots Pi Bus without loading the Raspberry Pi desktop.
- Replaced bottom navigation panels with understated active-view underlines.
- Reduced and re-centred album artwork and improved spacing around the transport controls.

## 0.3.0-rc.5 — 29 September 2026

- Distinguished the Now Playing controller from the Roon Bridge audio endpoint in web administration.
- Added clear Roon authorisation guidance and separate unavailable, unauthorised and idle states on the touchscreen.
- Refined the Now Playing split layout, artwork spacing, circular transport controls and bottom navigation emphasis.
- Made the native progress timeline touch-seekable, with debouncing and automatic disabling for non-seekable material.
- Added a Pi Bus favicon to web administration.

## 0.3.0-rc.4 — 29 September 2026

- Replaced raw command exceptions on touchscreen system actions with concise, useful failure messages while retaining full output in the service log.

## 0.3.0-rc.3 — 29 September 2026

- Made appliance updates preserve local checkout differences automatically instead of failing when an installed file has changed.
- Made installed appliances follow the supported `main` branch after the native GTK build became the primary release.

## 0.3.0-rc.2 — 29 September 2026

- Matched the native display typography to the Inter-based web administration and installed Inter automatically.
- Replaced visible main-screen utility buttons with large invisible title and clock touch targets.
- Removed page-transition animation and softened borders, status text and navigation chrome.
- Aligned and enlarged bus service and arrival figures on a shared baseline.
- Restored circular symbolic Roon transport controls and improved connected-but-idle wording.
- Added an optional completely black sleep screen while retaining tap-anywhere wake.

## 0.3.0-rc.1 — 29 September 2026

- Replaced the Chromium kiosk with a lightweight native GTK4 touchscreen.
- Added persistent Bus Times and Now Playing navigation, corner Settings and Sleep actions, and tap-anywhere wake.
- Added a restricted touchscreen settings screen with safe, one-tap software updates.
- Restored native Roon artwork, progress, playback and volume controls.
- Reorganised web administration into Schedule, Bus Stop, Roon and System sections.
- Added authenticated Roon Bridge controls, hostname, Wi-Fi and software-update actions.
- Added configurable web username/password management and optional authentication.

## 0.2.1 — 28 September 2026

- Prevented Chromium from launching before the main display service responds.
- Changed Chromium's initial background to black so startup cannot flash a white page.
- Made the updater wait for and verify both HTTP services, printing their logs on failure.

## 0.2.0 — 28 September 2026

- Replaced the bus summary panel with two much larger service rows.
- Added a proper password-manager-compatible admin login page.
- Added a persistent display shell for seamless Bus, Roon and Sleep switching.
- Added a dark, automatically recovering screen when the Roon controller is unavailable.
- Made the Roon service create its own working directory and report startup failures during updates.
- Changed Roon dependencies to immutable public HTTPS downloads.
- Added optional sleep while Roon is idle, waking automatically for playback.
- Refined Roon typography, transport icons and control shapes.

## 0.1.0 — 28 September 2026

- Initial Raspberry Pi bus display, web settings, kiosk service and Roon integration.
