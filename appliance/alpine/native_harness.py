"""Test helper: patch a function in every native-display module that uses it.

The display code is split across several modules, and each one that calls a
helper such as post_json holds its own reference to it. Patching only the entry
module would miss the others, so the review scripts patch them all.
"""
import sys
from pathlib import Path

NATIVE_DIR = Path(__file__).resolve().parents[2] / "native-display"
if str(NATIVE_DIR) not in sys.path:
    sys.path.insert(0, str(NATIVE_DIR))  # so scripts can import layout_constants, styles, ...


def native_modules(entry):
    modules = [entry]
    for module in list(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if module is not entry and path and Path(path).resolve().parent == NATIVE_DIR:
            modules.append(module)
    return modules


def patch_native(entry, name, value):
    """Replace `name` wherever it is defined or imported; returns a function that restores it."""
    previous = [(module, getattr(module, name)) for module in native_modules(entry) if hasattr(module, name)]
    for module, _ in previous:
        setattr(module, name, value)
    def restore():
        for module, original in previous:
            setattr(module, name, original)
    return restore
