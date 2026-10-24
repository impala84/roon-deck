#!/usr/bin/env python3
"""Compatibility launcher for installations using the former display name.

New services launch :mod:`roondeck_native` directly. Keep this small bridge so
an older service definition can still start the display during an update.
"""

from roondeck_native import Display, publish_display_source


if __name__ == "__main__":
    publish_display_source()
    Display().run(None)
