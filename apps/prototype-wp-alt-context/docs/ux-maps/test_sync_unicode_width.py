"""Exercise the Unicode checker CLI with version and property mutations."""

import contextlib
import io
import json
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).with_name("sync_unicode_width.py")


class UnicodeWidthTests(unittest.TestCase):
    def run_check(self, mutate):
        module = runpy.run_path(str(SOURCE))
        fixture = module["derive"]()
        mutate(fixture)
        output = io.StringIO()
        with patch.object(Path, "read_text", return_value=json.dumps(fixture)), \
                patch.object(sys, "argv", [str(SOURCE), "--check"]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                runpy.run_path(str(SOURCE), run_name="__main__")
            except SystemExit as error:
                return error.code, output.getvalue()
        return 0, output.getvalue()

    def test_version_mismatch_with_identical_ranges_passes_explicitly(self):
        status, output = self.run_check(lambda fixture: fixture.update(unicode_version="different-version"))
        self.assertEqual(status, 0)
        self.assertIn("Unicode version mismatch", output)
        self.assertIn("different-version", output)
        self.assertIn("property ranges match", output)

    def test_real_range_drift_fails_even_with_version_mismatch(self):
        for property_name in ["wide", "marks", "format"]:
            def mutate(fixture):
                fixture["unicode_version"] = "different-version"
                fixture[property_name] = []
            with self.subTest(property_name=property_name):
                status, output = self.run_check(mutate)
                self.assertNotEqual(status, 0)
                self.assertIn("regenerate explicitly", str(status))


if __name__ == "__main__":
    unittest.main()
