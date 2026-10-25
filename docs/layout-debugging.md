# Debugging layout drift between pages

Symptom: a header, clock, settings button or navigation row sits in a slightly
different place when you switch pages. Two tools help find out why.

## 1. Model the CSS (no GTK, no Docker, seconds)

```sh
python3 tools/css_cascade_report.py                    # every viewport in tools/viewports.json
python3 tools/css_cascade_report.py touch-v2-7-landscape
```

It evaluates the CSS that `native-display/roondeck_native.py` builds, works out
which rule wins for each page and display mode, and prints the effective top
padding and the header/navigation left and right inset for each page. A
`DRIFT:` line means Bus, Now Playing and Home disagree.

Important: Now Playing (including Queue, Browse and Discover) hides the shared
`.page-header` and uses `.discover-toolbar` as its header, while Bus and Home use
`.page-header`. The report cannot tell whether the cog ends up at the same height
in those two different containers; the GTK measurement below can.

Limits: it models class selectors, specificity and source order only. It does
not see pseudo-classes, classes toggled at runtime, or margins set from Python
(`set_margin_*`, `set_size_request`). Keep `window_classes()` in the script in
step with `Display.adapt_display`.

## 2. Measure real GTK positions (needs Docker, like the other screen checks)

```sh
tools/check screen layout
```

For every viewport this builds the real pages, shows each in turn and prints
the x, y, width and height of the header row, settings button, clock and
navigation row. It also writes `layout-alignment.txt` beside the screenshots in
`dist/native-review/layout/<viewport>/`. It reports by default and is not part
of `tools/check screen all`. To make it fail on disagreement
(more than 1px) run the runner directly with
`PI_HOME_LAYOUT_STRICT=1`, or change `PI_HOME_LAYOUT_TOLERANCE`.

Only Bus, Now Playing and Home are compared with each other. Settings has its
own header and is reported for reference.
