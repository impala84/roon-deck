#!/usr/bin/env python3
"""Audit the embedded GTK stylesheet without importing GTK.

The current limit is a ratchet, not a target.  It records the known-good
release's existing cascade debt so cleanup may reduce it while preventing new
conflicting selectors from being added unnoticed.
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NATIVE_SOURCE = ROOT / "native-display" / "pi_bus_native.py"
MAX_CONFLICTING_SELECTORS = 58


def embedded_css(source: str) -> str:
    """Return literal CSS fragments assigned or appended to ``CSS``."""
    fragments = re.findall(
        r"CSS\s*(?:\+?=)\s*\(?\s*b?(?:'''|\"\"\")([\s\S]*?)(?:'''|\"\"\")",
        source,
    )
    return "\n".join(fragments)


def strip_nested_at_rules(css: str) -> str:
    """Remove keyframe bodies so frame declarations are not read as selectors."""
    start = re.compile(r"@(?:keyframes|-gtk-keyframes)\b")
    while match := start.search(css):
        opening = css.find("{", match.end())
        if opening < 0:
            return css[: match.start()]
        depth = 1
        cursor = opening + 1
        while cursor < len(css) and depth:
            depth += (css[cursor] == "{") - (css[cursor] == "}")
            cursor += 1
        css = css[: match.start()] + css[cursor:]
    return css


def selector_declarations(css: str) -> dict[str, list[dict[str, str]]]:
    css = re.sub(r"/\*[\s\S]*?\*/", "", strip_nested_at_rules(css))
    rules: dict[str, list[dict[str, str]]] = defaultdict(list)
    for selector_group, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        declarations = {}
        for declaration in body.split(";"):
            if ":" not in declaration:
                continue
            prop, value = declaration.split(":", 1)
            declarations[prop.strip()] = value.strip()
        if not declarations:
            continue
        for selector in selector_group.split(","):
            normalized = " ".join(selector.split())
            if normalized and not normalized.startswith("@"):
                rules[normalized].append(declarations)
    return rules


def conflicting_selectors(rules: dict[str, list[dict[str, str]]]) -> dict[str, dict[str, set[str]]]:
    conflicts = {}
    for selector, appearances in rules.items():
        if len(appearances) < 2:
            continue
        values: dict[str, set[str]] = defaultdict(set)
        for declarations in appearances:
            for prop, value in declarations.items():
                values[prop].add(value)
        changed = {prop: options for prop, options in values.items() if len(options) > 1}
        if changed:
            conflicts[selector] = changed
    return conflicts


def audit(path: Path = NATIVE_SOURCE) -> tuple[dict[str, list[dict[str, str]]], dict[str, dict[str, set[str]]]]:
    rules = selector_declarations(embedded_css(path.read_text()))
    return rules, conflicting_selectors(rules)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if cascade debt increases")
    parser.add_argument("--verbose", action="store_true", help="list every conflicting selector")
    args = parser.parse_args()
    rules, conflicts = audit()
    duplicates = sum(len(appearances) > 1 for appearances in rules.values())
    print(
        f"Native CSS: {sum(map(len, rules.values()))} selector entries, "
        f"{len(rules)} unique, {duplicates} duplicated, "
        f"{len(conflicts)} with conflicting properties."
    )
    if args.verbose:
        for selector, properties in sorted(conflicts.items()):
            print(f"  {selector}: {', '.join(sorted(properties))}")
    if args.check and len(conflicts) > MAX_CONFLICTING_SELECTORS:
        print(
            f"CSS cascade debt increased from the allowed {MAX_CONFLICTING_SELECTORS} "
            f"conflicting selectors to {len(conflicts)}."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
