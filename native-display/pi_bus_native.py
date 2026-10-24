#!/usr/bin/env python3
"""Stable installed launcher for the canonical RoonDeck display module.

Keep this bridge at the historic path used by Cage and OpenRC installations so
application renames never change the supervised touchscreen process contract.
"""

from roondeck_native import Display, publish_display_source


if __name__ == "__main__":
    publish_display_source()
    Display().run(None)
