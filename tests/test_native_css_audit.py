import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("audit_native_css", ROOT / "tools" / "audit_native_css.py")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class NativeCssAuditTests(unittest.TestCase):
    def test_extracts_all_literal_css_appends(self):
        source = 'CSS = b""".one { color: red; }"""\nCSS += (""".two { color: blue; }""" % 4).encode()'
        css = AUDIT.embedded_css(source)
        self.assertIn(".one", css)
        self.assertIn(".two", css)

    def test_finds_conflicting_redeclarations(self):
        rules = AUDIT.selector_declarations(
            ".same { color: red; padding: 1px; }\n"
            ".same { color: blue; padding: 1px; }\n"
            ".stable { color: red; }\n.stable { color: red; }"
        )
        conflicts = AUDIT.conflicting_selectors(rules)
        self.assertEqual({"color": {"red", "blue"}}, conflicts[".same"])
        self.assertNotIn(".stable", conflicts)

    def test_known_good_stylesheet_stays_within_conflict_budget(self):
        _rules, conflicts = AUDIT.audit()
        self.assertLessEqual(len(conflicts), AUDIT.MAX_CONFLICTING_SELECTORS)


if __name__ == "__main__":
    unittest.main()
