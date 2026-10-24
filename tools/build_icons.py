#!/usr/bin/env python3
"""Canonical RoonDeck monoline family. Generated assets are checked in for appliances."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICONS = {
    'rock': '<path d="M39 19 49 9l5 5-10 10-3-3-16 18c5-1 8 2 6 6l-7 9c-5 6-13 2-17-3s-4-11 1-15l8-5c4-3 8-1 7 4L39 19Z M23 39l18-18 M16 43l4 4 M48 9l3-3 5 5-2 3"/>',
    'classical': '<rect x="12" y="8" width="40" height="7" rx="3.5"/><path d="M16 22h32 M20 22v34 M28 28v28 M36 28v28 M44 22v34"/>',
    'electronic': '<rect x="5" y="16" width="54" height="32" rx="3"/><path d="M10 24h3 M18 24h3 M26 24h3 M10 34v14 M18 34v14 M26 34v14 M34 34v14 M42 34v14 M50 34v14 M14 40v8 M22 40v8 M30 40v8 M38 40v8 M46 40v8 M54 40v8"/><circle cx="43" cy="24" r="2"/><circle cx="52" cy="24" r="2"/>',
    'jazz': '<path d="M10 13h7c1-10 15-9 15 2v33c0 5 7 7 9 0l3-15 9-8 7 5-7 3-4 17c-4 17-24 14-24 0V15c0-4-6-6-8-2 M22 27h8 M22 36h8 M24 44h7 M47 23l13 7"/>',
    'stage': '<path d="m4 17 25-8 5 19c3 15-8 24-18 13-6-7-8-15-12-24Z M12 22q3-5 6-1 M23 18q3-5 6-1 M16 31q6 6 11-1 m12-11 22 7-6 19c-5 13-16 14-22 1 M43 31q3-3 5 1 M51 33q3-3 5 1 M40 44q5-3 9 1"/>',
    'world': '<circle cx="32" cy="32" r="24"/><ellipse cx="32" cy="32" rx="11" ry="24"/><path d="M8 32h48 M13 17q19 9 38 0 M13 47q19-9 38 0"/>',
    'vocal': '<rect x="23" y="5" width="18" height="38" rx="9"/><path d="M23 16h18 M23 23h6 M35 23h6 M23 30h6 M35 30h6 M16 31v4a16 16 0 0 0 32 0v-4 M32 51v8 M23 59h18"/>',
    'blues': '<path d="M5 30h36q11 0 18-13l1 29q-9-11-19-11H15c-7 0-7 10 0 10h24c8 0 8-13 0-13 M4 28v6 M9 30v5 M25 24v21 M31 24v21 M37 24v21 M23 24h4 M29 24h4 M35 24h4 M23 48h4 M29 48h4 M35 48h4"/>',
    'easy': '<path d="M11 34v-6a21 21 0 0 1 42 0v6"/><rect x="6" y="32" width="11" height="22" rx="5"/><rect x="47" y="32" width="11" height="22" rx="5"/>',
    'rb': '<circle cx="32" cy="32" r="25"/><circle cx="32" cy="32" r="7"/><circle cx="32" cy="32" r="1"/><path d="M13 27a20 20 0 0 1 14-14 M18 28a15 15 0 0 1 10-10 M37 46a15 15 0 0 0 9-10 M37 51a20 20 0 0 0 14-15"/>',
    'rap': '<rect x="3" y="8" width="58" height="47" rx="2"/><circle cx="27" cy="32" r="18"/><circle cx="27" cy="32" r="4"/><circle cx="53" cy="18" r="3"/><path d="m52 21-9 22-5-2 2-5 5 2"/>',
    'avant': '<path d="M5 22h18 M5 32h28 M11 42h22l17-8h13 M43 6v50"/><circle cx="56" cy="23" r="2"/><circle cx="54" cy="46" r="1"/>',
    'folk': '<path d="m37 20 12-14 7 5-12 14-4-3-12 14c7 0 9 5 4 12-6 10-14 11-21 4S4 37 14 31c7-5 12-3 12 4l12-14 M26 37l14-15 M19 40l4 4-4 4-4-4Z M49 6l3-3 6 5-2 3"/>',
    'ambient': '<path d="M3 40h58 M6 47h52 M17 55h30 M16 40a16 16 0 0 1 32 0 M32 9v10 M18 13l4 8 M7 23l8 5 M46 13l-4 8 M57 23l-8 5"/>',
    'reggae': '<path d="M29 28 25 59h11l-4-31 M31 27C22 9 9 11 6 20c12-2 19 0 25 7 M31 27C40 9 53 11 58 20c-13-2-20 0-27 7 M31 27C17 19 7 30 6 43c9-8 15-13 25-16 M31 27c14-8 24 3 26 16-10-8-16-13-26-16"/>',
    'country': '<path d="m16 36 5-22c1-5 5-4 8-1 3 3 5 3 8 0 3-3 7-4 8 1l5 22 M16 36q16 8 34 0c10-9 17 2 3 13-13 11-33 11-46-1-13-11-4-21 9-12Z"/>',
    'latin': '<ellipse cx="17" cy="18" rx="10" ry="13" transform="rotate(-30 17 18)"/><ellipse cx="46" cy="23" rx="10" ry="13" transform="rotate(30 46 23)"/><path d="m20 31 7 12c3 5 7 2 4-2l-7-13 M39 34 28 53c-3 5 3 8 5 3l11-19 M7 17l17-9 M9 25l19-10 M38 14l18 11 M36 22l17 11"/>',
    'religious': '<path d="M12 57V33l20-21 20 21v24 M7 57h50 M27 57V43a5 5 0 0 1 10 0v14 M32 2v18 M26 8h12"/><circle cx="32" cy="31" r="3"/>',
    'holiday': '<path d="M32 5v54 M9 18l46 28 M9 46l46-28 M25 9l7 7 7-7 M25 55l7-7 7 7 M10 27l3-10 10-2 M41 49l10-2 3-10 M10 37l3 10 10 2 M41 15l10 2 3 10"/>',
    'children': '<circle cx="32" cy="34" r="21"/><path d="M11 29c-10-4-10 14 0 10 M53 29c10-4 10 14 0 10 M26 14c-4-9 9-2 12-9 1 7-9 6-9 11 M23 41q9 10 18 0"/><circle cx="25" cy="29" r="1"/><circle cx="39" cy="29" r="1"/>',
    'comedy': '<rect x="23" y="9" width="18" height="34" rx="9"/><path d="M23 21h18 M23 28h6 M35 28h6 M17 34v3a15 15 0 0 0 30 0v-3 M32 52v8 M24 60h16 M5 18l7 4 M3 30h7 M5 42l7-4 M59 18l-7 4 M61 30h-7 M59 42l-7-4"/>',
    'album': '<rect x="12" y="9" width="40" height="46" rx="1"/><circle cx="32" cy="32" r="15"/><circle cx="32" cy="32" r="4"/>',
    'artist': '<circle cx="29" cy="18" r="9"/><path d="M11 51a18 18 0 0 1 28-15 M48 48V31h8"/><circle cx="43" cy="48" r="5"/>',
    'music': '<path d="M23 45V16l24-7v32 M23 27l24-7"/><circle cx="17" cy="45" r="6"/><circle cx="41" cy="41" r="6"/>',
    'playlist': '<path d="M8 16h29 M8 30h25 M8 44h25 m9-23 16 11-16 11Z"/>',
    'search': '<circle cx="27" cy="27" r="17"/><path d="m40 40 16 16"/>',
    'play': '<path d="m23 14 27 18-27 18Z"/>',
    'pause': '<path d="M24 15v34 M40 15v34"/>',
    'previous': '<path d="M16 15v34 m31-34-24 17 24 17Z"/>',
    'next': '<path d="M48 15v34 M17 15l24 17-24 17Z"/>',
    'add': '<path d="M32 13v38 M13 32h38"/>',
    'remove': '<path d="M13 32h38"/>',
    'back': '<path d="m38 14-18 18 18 18"/>',
    'forward': '<path d="m26 14 18 18-18 18"/>',
    'close': '<path d="m17 17 30 30 M17 47l30-30"/>',
    'refresh': '<path d="M51 23a21 21 0 1 0 0 19 M51 11v12H39"/>',
    'shuffle': '<path d="M10 18h8c14 0 14 28 28 28h8 M10 46h8c5 0 9-4 12-9 M38 23c3-3 5-5 8-5h8 m-7-7 7 7-7 7 m0 14 7 7-7 7"/>',
    'heart': '<path d="M32 52 11 32C-3 16 17 3 32 20 47 3 67 16 53 32Z"/>',
    'folder': '<path d="M6 20V13h19l7 7h26v33H6Z"/>',
    'clock': '<circle cx="32" cy="32" r="23"/><path d="M32 16v16l12 7"/>',
    'settings': '<path d="m27 7 10 0 2 8 5 3 8-2 5 9-6 6v6l6 6-5 9-8-2-5 3-2 8H27l-2-8-5-3-8 2-5-9 6-6v-6l-6-6 5-9 8 2 5-3Z"/><circle cx="32" cy="34" r="9"/>',
    'fan': '<circle cx="32" cy="32" r="4"/><circle cx="32" cy="32" r="24"/><path d="M30 28c-11-17 1-22 7-17 6 4 6 13-3 17 M36 30c17-11 22 1 17 7-4 6-13 6-17-3 M34 36c11 17-1 22-7 17-6-4-6-13 3-17 M28 34c-17 11-22-1-17-7 4-6 13-6 17 3"/>',
    'light': '<path d="M24 47h16 M26 54h12 M24 41c0-6-9-10-9-20a17 17 0 0 1 34 0c0 10-9 14-9 20Z M32 2v-1 M5 21H1 M63 21h-4 M12 5l-3-3 M52 5l3-3"/>',
    'switch': '<rect x="8" y="21" width="48" height="24" rx="12"/><circle cx="21" cy="33" r="8"/>',
    'switchon': '<rect x="8" y="21" width="48" height="24" rx="12"/><circle cx="43" cy="33" r="8"/>',
    'brightness': '<circle cx="32" cy="32" r="12"/><path d="M32 4v8 M32 52v8 M4 32h8 M52 32h8 M12 12l6 6 M46 46l6 6 M12 52l6-6 M46 18l6-6"/>',
    'home': '<path d="m7 29 25-21 25 21 M14 24v32h36V24 M26 56V37h12v19"/>',
    'bus': '<rect x="13" y="7" width="38" height="46" rx="6"/><path d="M13 33h38 M13 18h38 M21 53v5 M43 53v5"/><circle cx="22" cy="43" r="2"/><circle cx="42" cy="43" r="2"/>',
    'discover': '<circle cx="32" cy="32" r="24"/><path d="m42 22-6 14-14 6 6-14Z"/>',
    'overflow': '<circle cx="15" cy="32" r="2"/><circle cx="32" cy="32" r="2"/><circle cx="49" cy="32" r="2"/>',
    'power': '<path d="M32 6v23 M20 12a23 23 0 1 0 24 0"/>',
    'orientation': '<rect x="19" y="8" width="26" height="48" rx="3"/><path d="M8 24a25 25 0 0 1 9-13 M8 14v10h10 M56 40a25 25 0 0 1-9 13 M56 50V40H46"/>',
    'check': '<path d="m14 32 12 12 25-25"/>',
    'erase': '<path d="M24 15h34v34H24L7 32Z M32 24l16 16 M32 40l16-16"/>',
}

def svg(name):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" '
            'viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round">' + ICONS[name] + '</svg>\n')

def outputs():
    files = {'roon-controller/static/icons/' + name + '-symbolic.svg': svg(name) for name in ICONS}
    js = ('/* Generated by tools/build_icons.py; edit the canonical family, not this file. */\n'
          'globalThis.PiHomeIcons = Object.freeze({\n'
          '  paths: Object.freeze(' + json.dumps(ICONS, separators=(',', ':')) + '),\n'
          '  svg(name, className = "pi-icon") { return `<svg class="${className}" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${this.paths[name] || this.paths.music}</svg>`; },\n'
          '  element(name, className = "pi-icon") { const template = document.createElement("template"); template.innerHTML = this.svg(name, className); return template.content.firstElementChild; }\n'
          '});\n')
    files['roon-controller/static/icons.js'] = js
    files['src/pi_bus_time_display/static/icons.js'] = js
    # Neutral artwork placeholders are intentionally the pre-upgrade designs,
    # not the prominent catalogue/navigation symbols.
    files['native-display/icons/missing-album.svg'] = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="256" height="256"><g transform="translate(50 50)" fill="none" stroke="#505453" stroke-width="4"><circle cx="50" cy="50" r="31"/><circle cx="50" cy="50" r="8"/></g></svg>\n'
    files['native-display/icons/missing-artist.svg'] = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="256" height="256"><g transform="translate(50 50)" fill="none" stroke="#505453" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"><circle cx="50" cy="30" r="14"/><path d="M22 88v-8a28 28 0 0 1 56 0v8"/></g></svg>\n'
    return files

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    stale = []
    for name, content in outputs().items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_text() != content: stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content)
    if stale: raise SystemExit('Stale icon assets: ' + ', '.join(stale))
