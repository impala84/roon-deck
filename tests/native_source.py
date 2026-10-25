"""Text of the native display: the Python source plus its stylesheet files.

Many tests assert on layout rules. The stylesheet used to live inside
pi_bus_native.py; it is now native-display/css/*.css, so those tests read both.
"""
from pathlib import Path

NATIVE = Path(__file__).resolve().parents[1] / "native-display"


def native_text() -> str:
    parts = [(NATIVE / "pi_bus_native.py").read_text(encoding="utf-8")]
    parts += [path.read_text(encoding="utf-8") for path in sorted((NATIVE / "css").glob("*.css"))]
    return "\n".join(parts)
