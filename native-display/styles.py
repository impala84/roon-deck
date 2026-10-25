"""Load the native display stylesheet from native-display/css/*.css.

The files are read in filename order and joined, so the cascade is exactly the
order of the numbers in their names. GTK has no variables in the CSS it supports
on older versions, so a few values are written as ``@NAME@`` placeholders and
filled in here: the shared page-grid constants and the background texture URL.
This module needs no GTK, so tools can import it to inspect the stylesheet.
"""
from __future__ import annotations

import re
from pathlib import Path

import layout_constants

CSS_DIR = Path(__file__).resolve().parent / "css"
_PLACEHOLDER = re.compile(r"@([A-Z][A-Z0-9_]*)@")


def css_values() -> dict[str, str]:
    values = {
        name: str(getattr(layout_constants, name))
        for name in dir(layout_constants)
        if name.isupper()
    }
    values["GRADIENT_DITHER_URL"] = (Path(__file__).resolve().parent / "icons" / "gradient-dither.svg").as_uri()
    return values


def css_files() -> list[Path]:
    files = sorted(CSS_DIR.glob("*.css"))
    if not files:
        raise FileNotFoundError(f"No stylesheet files in {CSS_DIR}")
    return files


def load_css() -> bytes:
    """Return the complete stylesheet as bytes, ready for Gtk.CssProvider."""
    values = css_values()

    def fill(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise KeyError(f"Unknown stylesheet placeholder @{name}@")
        return values[name]

    text = "\n".join(_PLACEHOLDER.sub(fill, path.read_text(encoding="utf-8")) for path in css_files())
    return text.encode("utf-8")
