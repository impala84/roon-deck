"""Text of the native display: every Python module plus its stylesheet files.

Many tests assert on layout rules. The code used to live in one file, pi_bus_native.py; it is now several modules
plus native-display/css/*.css, so those tests read all of them.
"""
import ast
from pathlib import Path

NATIVE = Path(__file__).resolve().parents[1] / "native-display"
# Separate helper modules that were never part of the single display file.
OTHER_MODULES = {"icon_family.py", "white_balance.py", "styles.py", "layout_constants.py"}


def display_modules() -> list:
    """The entry point first, then every module split out of it."""
    rest = sorted(p for p in NATIVE.glob("*.py") if p.name not in OTHER_MODULES | {"pi_bus_native.py"})
    return [NATIVE / "pi_bus_native.py"] + rest


def native_text() -> str:
    parts = [path.read_text(encoding="utf-8") for path in display_modules()]
    parts += [path.read_text(encoding="utf-8") for path in sorted((NATIVE / "css").glob("*.css"))]
    return "\n".join(parts)


def python_tree() -> ast.Module:
    """One syntax tree holding the top level of every native-display module."""
    body = []
    for path in display_modules():
        body += ast.parse(path.read_text(encoding="utf-8")).body
    return ast.Module(body=body, type_ignores=[])


def method_source(name: str) -> str:
    """Exact source of one method (or function), wherever it now lives."""
    for path in display_modules():
        text = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return ast.get_source_segment(text, node)
    raise LookupError(name)
