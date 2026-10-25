# Native display stylesheet

`native-display/styles.py` loads every `*.css` file in this folder in filename
order and joins them into the one stylesheet GTK uses. **Order is the cascade**:
a later file overrides an earlier one with the same specificity, so keep the
numeric prefixes.

Words written between two `@` signs (for example `@LANDSCAPE_PAGE_MARGIN@`) are
placeholders. They are filled from `native-display/layout_constants.py` plus the
background-texture URL, because the GTK on the Pi has no CSS variables.

The files are the original single stylesheet cut at its seven natural joins,
unchanged and in the same order (checked rule for rule). Next step is to regroup
the rules by page and display size, which needs the layout checks below after
each move:

    tools/check screen layout      # real GTK positions at every size
    python3 tools/css_cascade_report.py
