#!/usr/bin/env python3
"""Report the spacing each page really gets in each display mode (no GTK needed).

The native display builds its GTK CSS in Python from several overlapping layers
(base rules, per-page rules, display-mode rules and a few runtime-templated
values). This script evaluates those same CSS statements without GTK, works out
which rule wins for each page and display mode, and prints the effective
horizontal and vertical insets of the shared header and navigation row.

It is a *model*: it understands descendant selectors made of class names and
applies specificity then source order. It does not model pseudo-classes,
state classes toggled at runtime, or margins set from Python. Use
``tools/check screen layout`` for real GTK measurements.

Usage: python3 tools/css_cascade_report.py [viewport-id ...]
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "native-display" / "pi_bus_native.py"
MATRIX = ROOT / "tools" / "viewports.json"

PAGES = {
    "bus-page": {"header": ["page-header"], "nav": ["nav"]},
    "roon-page": {"header": ["roon-header", "page-header"], "nav": ["nav"]},
    "home-page": {"header": ["page-header"], "nav": ["nav"]},
    "settings-page": {"header": ["settings-header"], "nav": []},
}


def window_classes(width: int, height: int) -> set[str]:
    """Mirror Display.adapt_display and configure_settings_layout class choices.

    Keep in sync with native-display/pi_bus_native.py when those change.
    """
    portrait = height > width
    original = not portrait and width <= 820 and height <= 500
    compact_landscape = not portrait and (height <= 600 or width < 1000)
    classes = {"portrait" if portrait else "display-landscape"}
    if compact_landscape:
        classes.add("compact-landscape")
    if original:
        classes.add("original-landscape")
    if portrait and width < 600:
        classes.add("compact-portrait")
    if max(width, height) >= 1200:
        classes.add("high-resolution")
    if width >= 1200 and not portrait:
        classes.add("touch-landscape")
    if not portrait and 1200 <= width < 1500 and 650 <= height < 850:
        classes.add("touch2-7-landscape")
    if min(width, height) >= 1000:
        classes.add("large-display")
    if portrait and width >= 1000:
        classes.add("large-portrait")
    if original or (not portrait and 1000 <= width < 1500 and height <= 850):
        classes.add("seven-inch-settings")
    return classes


def load_css() -> list[tuple[str, str]]:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    namespace: dict = {"Path": Path, "re": re, "json": json, "__file__": str(SOURCE)}
    for node in tree.body:
        is_css = (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "CSS"
        ) or (isinstance(node, ast.AugAssign) and getattr(node.target, "id", "") == "CSS")
        is_constant = (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id.isupper()
            and isinstance(node.value, ast.Constant)
        )
        if is_css or is_constant:
            exec(compile(ast.Module([node], []), str(SOURCE), "exec"), namespace)
    css = re.sub(r"/\*.*?\*/", "", namespace["CSS"].decode(), flags=re.S)
    css = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    return [
        (selector.strip(), match.group(2))
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
        for selector in match.group(1).split(",")
    ]


def px(value: str | None) -> int:
    match = re.match(r"-?\d+", value or "")
    return int(match.group()) if match else 0


def declarations(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for declaration in body.split(";"):
        if ":" not in declaration:
            continue
        name, value = (part.strip() for part in declaration.split(":", 1))
        if name in ("padding", "margin"):
            parts = value.split()
            if len(parts) == 1:
                parts *= 4
            elif len(parts) == 2:
                parts = [parts[0], parts[1], parts[0], parts[1]]
            elif len(parts) == 3:
                parts = [parts[0], parts[1], parts[2], parts[1]]
            for side, part in zip(("top", "right", "bottom", "left"), parts[:4]):
                out[f"{name}-{side}"] = part
        else:
            out[name] = value
    return out


def resolve(rules, window: set[str], page: str, element: str) -> dict[str, str]:
    """Winning declarations for ``element`` inside ``page`` for a window mode."""
    allowed_ancestors = window | {page, "page"}
    element_classes = {element}
    if element == page:
        element_classes = {"page", page}
    winners: dict[str, tuple[tuple[int, int], str]] = {}
    for order, (selector, body) in enumerate(rules):
        tokens = [set(re.findall(r"\.([\w-]+)", part)) for part in selector.split()]
        if not tokens or not tokens[-1] or not tokens[-1] <= element_classes:
            continue
        if any(not token or not token <= allowed_ancestors for token in tokens[:-1]):
            continue
        specificity = sum(len(token) for token in tokens)
        for name, value in declarations(body).items():
            if name not in winners or (specificity, order) >= winners[name][0]:
                winners[name] = ((specificity, order), value)
    return {name: value for name, (_, value) in winners.items()}


def report(rules, viewport: dict) -> None:
    width, height = viewport["width"], viewport["height"]
    window = window_classes(width, height)
    print(f"\n=== {viewport['id']}  {width}x{height}  classes: {', '.join(sorted(window))}")
    print(f"{'page':14} {'pad-top':>7} {'pad-bot':>7} | {'hdr left':>8} {'hdr right':>9} | {'nav left':>8} {'nav right':>9}")
    rows = {}
    for page, parts in PAGES.items():
        padding = resolve(rules, window, page, page)
        left, right = px(padding.get("padding-left")), px(padding.get("padding-right"))
        header_left = left + sum(px(resolve(rules, window, page, e).get("margin-left")) for e in parts["header"])
        header_right = right + sum(px(resolve(rules, window, page, e).get("margin-right")) for e in parts["header"])
        nav_left = nav_right = None
        if parts["nav"]:
            nav = resolve(rules, window, page, parts["nav"][0])
            nav_left, nav_right = left + px(nav.get("margin-left")), right + px(nav.get("margin-right"))
        rows[page] = (px(padding.get("padding-top")), px(padding.get("padding-bottom")), header_left, header_right, nav_left, nav_right)
        fmt = lambda v: "-" if v is None else str(v)
        print(f"{page:14} {rows[page][0]:>7} {rows[page][1]:>7} | {rows[page][2]:>8} {rows[page][3]:>9} | {fmt(rows[page][4]):>8} {fmt(rows[page][5]):>9}")
    shared = [rows[p] for p in ("bus-page", "roon-page", "home-page")]
    notes = []
    if len({r[0] for r in shared}) > 1:
        notes.append("top padding differs between Bus / Now Playing / Home (header will move vertically)")
    if len({(r[2], r[3]) for r in shared}) > 1:
        notes.append("header left/right inset differs between Bus / Now Playing / Home")
    if len({(r[4], r[5]) for r in shared}) > 1:
        notes.append("navigation row inset differs between Bus / Now Playing / Home")
    print("  DRIFT: " + "; ".join(notes) if notes else "  Bus / Now Playing / Home agree on top padding, header inset and nav inset.")


def main() -> None:
    wanted = set(sys.argv[1:])
    rules = load_css()
    print(f"{len(rules)} CSS rules after evaluating the CSS built in {SOURCE.relative_to(ROOT)}")
    for viewport in json.loads(MATRIX.read_text(encoding="utf-8"))["viewports"]:
        if not wanted or viewport["id"] in wanted:
            report(rules, viewport)


if __name__ == "__main__":
    main()
