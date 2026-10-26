"""Find names the native display uses but never defines.

The display is GTK code that unit tests cannot run, so a misspelt or out-of-scope
name only fails on the touchscreen, when that line finally executes (for example
when album notes arrive). This reads every function's scope and reports any
name that is neither local, enclosing, module-level, imported nor built in.
"""
import builtins
import symtable
import unittest
from pathlib import Path

NATIVE = Path(__file__).resolve().parents[1] / "native-display"
ALWAYS = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}


def module_names(path):
    table = symtable.symtable(path.read_text(encoding="utf-8"), str(path), "exec")
    return {s.get_name() for s in table.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}, table


def undefined(table, known, where):
    found = []
    for child in table.get_children():
        label = f"{where}.{child.get_name()}"
        if child.get_type() in {"function", "class"}:
            for symbol in child.get_symbols():
                name = symbol.get_name()
                if symbol.is_global() and symbol.is_referenced() and name not in known and name not in ALWAYS:
                    found.append(f"{label}: {name}")
        found += undefined(child, known, label)
    return found


class NativeUndefinedNameTests(unittest.TestCase):
    def test_every_name_the_display_uses_is_defined(self):
        common, _ = module_names(NATIVE / "native_common.py")
        problems = []
        for path in sorted(NATIVE.glob("*.py")):
            known, table = module_names(path)
            if path.name == "roondeck_native.py":
                known |= common  # it re-exports everything in native_common
            problems += undefined(table, known, path.name)
        self.assertEqual(problems, [], "Names used but never defined (they would raise NameError on the display)")


if __name__ == "__main__":
    unittest.main()
