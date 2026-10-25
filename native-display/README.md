# Native display

The GTK4 touchscreen app. `roondeck_native.py` starts it.

| File | What lives there |
|---|---|
| `roondeck_native.py` | The `Display` class: start-up, the status poll, applying new state, headers and navigation. It inherits everything below. |
| `native_common.py` | Shared imports, constants, small helpers and the scrolling/mix widgets. |
| `bus_page.py` | Bus Times page |
| `home_page.py` | Home page (Home Assistant) |
| `now_playing_page.py` | Now Playing: transport, volume, details, queue |
| `discover_page.py` | Discover: daily sections, mixes, recent plays, artist profiles |
| `browse_page.py` | Albums, artists, genres, search, scrubber, album headers |
| `settings_page.py` | Settings page and the actions behind it |
| `sleep_and_touch.py` | Screen sleep and wake, touch wake-up, cursor hiding |
| `artwork.py` | Artwork loading, decoding and thumbnails |
| `screen_preview.py` | Remote screen preview and view requests |
| `css/` | The stylesheet, loaded in filename order by `styles.py` |
| `layout_constants.py` | Page-grid numbers shared by Python and CSS |

Each page file holds a mixin class (for example `BusPageMixin`). `Display` lists
them as base classes, so methods still call each other as `self.render_bus()`.
Add new methods to the page they belong to.

Rules: only one agent edits the native layout at a time, and a layout change is
checked with `tools/check screen layout` before release.
