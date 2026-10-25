"""Create a transparent Xcursor theme for the dedicated touchscreen session."""
from pathlib import Path
import struct


# Every CSS, legacy X11 and Wayland cursor-shape name. Any name missing here falls back to the
# default theme's visible arrow, which is the occasional flash seen on the panel.
CURSOR_NAMES = (
    "left_ptr", "default", "arrow", "pointer", "hand1", "hand2", "text", "xterm", "ibeam", "crosshair", "cross",
    "wait", "watch", "progress", "left_ptr_watch", "grabbing", "grab", "fleur", "move", "all-scroll", "context-menu",
    "help", "question_arrow", "not-allowed", "no-drop", "crossed_circle", "dnd-none", "dnd-move", "dnd-copy", "dnd-link",
    "copy", "alias", "cell", "vertical-text", "zoom-in", "zoom-out", "col-resize", "row-resize", "sb_h_double_arrow",
    "sb_v_double_arrow", "h_double_arrow", "v_double_arrow", "e-resize", "w-resize", "n-resize", "s-resize", "ne-resize",
    "nw-resize", "se-resize", "sw-resize", "ew-resize", "ns-resize", "nesw-resize", "nwse-resize", "top_side",
    "bottom_side", "left_side", "right_side", "top_left_corner", "top_right_corner", "bottom_left_corner",
    "bottom_right_corner", "size_hor", "size_ver", "size_bdiag", "size_fdiag", "X_cursor", "top_left_arrow", "center_ptr",
)


def prepare(base=Path("/run/pi-home/cursors")):
    theme = base / "pi-home-touch"
    cursors = theme / "cursors"
    cursors.mkdir(parents=True, exist_ok=True)
    (theme / "index.theme").write_text("[Icon Theme]\nName=RoonDeck Touch\nInherits=\n")
    # Xcursor file header, one image TOC, one 1×1 fully transparent ARGB image.
    data = struct.pack("<4I", 0x72756358, 16, 0x10000, 1)
    data += struct.pack("<3I", 0xfffd0002, 24, 28)
    data += struct.pack("<9I", 36, 0xfffd0002, 24, 1, 1, 1, 0, 0, 0)
    data += struct.pack("<I", 0)
    for name in CURSOR_NAMES:
        (cursors / name).write_bytes(data)
    return theme


if __name__ == "__main__": prepare()
