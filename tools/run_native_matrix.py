#!/usr/bin/env python3
"""Run native GTK checks from the one authoritative viewport matrix."""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "tools" / "viewports.json"


def run(command: list[str], *, environment: dict[str, str] | None = None) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=environment, check=True)


def xvfb(size: str, script: str, environment: dict[str, str]) -> None:
    run(
        [
            "dbus-run-session",
            "xvfb-run",
            "-a",
            "-s",
            f"-screen 0 {size}x24",
            "python3",
            script,
        ],
        environment=environment,
    )


def write_gallery(output: Path) -> None:
    images = sorted(output.rglob("*.png"))
    cards = "\n".join(
        f'<figure><img src="{html.escape(str(path.relative_to(output)))}" loading="lazy">'
        f"<figcaption>{html.escape(str(path.relative_to(output)))}</figcaption></figure>"
        for path in images
    )
    (output / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>RoonDeck native review</title>"
        "<style>body{margin:24px;background:#111;color:#eee;font:14px sans-serif}"
        "main{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:24px}"
        "figure{margin:0}img{display:block;width:100%;height:auto;border:1px solid #444}"
        "figcaption{padding:8px 0;color:#aaa}</style><h1>RoonDeck native review</h1>"
        f"<main>{cards}</main>",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screen", choices=("settings", "discover", "layout", "all"), default="all")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "native-review")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))["viewports"]
    base = {
        **os.environ,
        "GDK_BACKEND": "x11",
        "GSK_RENDERER": "cairo",
    }
    xvfb("800x480", "appliance/common/white_balance_smoke.py", base)

    for viewport in matrix:
        width, height = viewport["width"], viewport["height"]
        size = f"{width}x{height}"
        destination = args.output / viewport["id"]
        destination.mkdir(parents=True, exist_ok=True)
        environment = {
            **base,
            "PI_HOME_SCREEN_WIDTH": str(width),
            "PI_HOME_SCREEN_HEIGHT": str(height),
            "PI_HOME_SCREENSHOT_DIR": str(destination),
        }
        if args.screen in ("discover", "all"):
            xvfb(size, "appliance/alpine/discover_visual_review.py", environment)
        if args.screen == "layout":
            # Report-only by default; not part of "all" until its numbers are trusted.
            xvfb(size, "appliance/alpine/layout_alignment_smoke.py", environment)
        if args.screen in ("settings", "all"):
            xvfb(
                size,
                "appliance/alpine/settings_smoke.py",
                {**environment, "PI_HOME_SETTINGS_VIEWPORT": size},
            )

    write_gallery(args.output)
    print(f"Native review: {args.output / 'index.html'}")


if __name__ == "__main__":
    main()
