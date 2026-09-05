"""Mutation probes for the renderer's fail-closed checks and regeneration boundary."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).with_name("render_ux_maps.py")
spec = importlib.util.spec_from_file_location("renderer", SOURCE)
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class RendererBoundaryTests(unittest.TestCase):
    def test_duplicate_retained_contract_cannot_hide_an_unchecked_table(self):
        text = SOURCE.with_name("febt-1-job-error-states.md").read_text()
        with self.assertRaisesRegex(ValueError, "duplicate retained contract"):
            renderer._extract_kept_text(text + "\n## Detailed reducer and recovery contract\n\n| auth_expired | Retry |\n")

    def test_conditional_primary_actions_fail_closed(self):
        path = SOURCE.with_name("febt-1-job-error-states.uxmap.json")
        renderer._validate_action_conditions(json.loads(path.read_text()))
        for condition in [None, [], ["auth_expired"], ["undeclared"]]:
            doc = json.loads(path.read_text())
            retry = next(action for action in doc["actions"] if action["id"] == "retry-request")
            if condition is None:
                del retry["when"]
            else:
                retry["when"] = condition
            with self.subTest(condition=condition), self.assertRaises(ValueError):
                renderer._validate_action_conditions(doc)

    def test_only_missing_top_level_canvas_package_permits_fallback(self):
        for missing, fallback in [("workbay_canvas_mcp", True), ("pydantic", False), ("workbay_canvas_mcp.ux_map.models", False)]:
            with self.subTest(missing=missing), patch("builtins.__import__", side_effect=ModuleNotFoundError(name=missing)):
                expected = renderer.OptionalRendererUnavailable if fallback else ModuleNotFoundError
                with self.assertRaises(expected):
                    renderer._load_renderer()

    def test_internal_import_error_never_uses_snapshot_fallback(self):
        with patch.object(renderer, "render", side_effect=ImportError("internal dependency broke")), \
                patch.object(renderer, "_check_projection", return_value=("same", "same")) as projection:
            with contextlib.redirect_stderr(io.StringIO()):
                try:
                    status = renderer.check(["dashboard"])
                except ImportError:
                    status = 1
            self.assertEqual(status, 1)
            projection.assert_not_called()

    def test_json_digest_ignores_checkout_line_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "map.json"
            target.write_bytes(b'{\n  "name": "dashboard"\n}\n')
            expected = renderer._source_digest(target)
            target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))
            self.assertEqual(renderer._source_digest(target), expected)

    def test_retained_mutations_cannot_be_blessed_by_normal_regeneration(self):
        ref = "febt-1-job-error-states"
        original = SOURCE.with_name(f"{ref}.md").read_text()
        for before, after in [
            ("No job running", "Xo job running"),
            ("| Reload page |", "| Retry |"),
        ]:
            with self.subTest(before=before), tempfile.TemporaryDirectory() as directory:
                maps = Path(directory)
                shutil.copyfile(SOURCE.with_name(f"{ref}.uxmap.json"), maps / f"{ref}.uxmap.json")
                mutated = original.replace(before, after, 1)
                self.assertNotEqual(mutated, original)
                target = maps / f"{ref}.md"
                target.write_text(mutated)
                snapshot = maps / "visible.json"
                shutil.copyfile(renderer.VISIBLE_PROJECTION_PATH, snapshot)
                original_snapshot = snapshot.read_bytes()
                with patch.object(renderer, "MAPS_DIR", maps), \
                        patch.object(renderer, "VISIBLE_PROJECTION_PATH", snapshot), \
                        patch.object(renderer, "render", return_value=mutated):
                    with self.assertRaisesRegex(ValueError, "retained contract"):
                        renderer._render_and_write([ref])
                self.assertEqual(snapshot.read_bytes(), original_snapshot)
                self.assertEqual(target.read_text(), mutated)

    def test_retained_table_mutation_fails_both_check_paths(self):
        ref = "febt-1-job-error-states"
        with tempfile.TemporaryDirectory() as directory:
            maps = Path(directory)
            shutil.copyfile(SOURCE.with_name(f"{ref}.uxmap.json"), maps / f"{ref}.uxmap.json")
            original = SOURCE.with_name(f"{ref}.md").read_text()
            mutated = original.replace("| Reload page |", "| Retry |", 1)
            self.assertNotEqual(mutated, original)
            (maps / f"{ref}.md").write_text(mutated)
            with patch.object(renderer, "MAPS_DIR", maps):
                for rendered in [None, original]:
                    expected, actual = renderer._check_projection(ref, rendered)
                    self.assertNotEqual(expected, actual)

    def test_render_restores_source_contract_instead_of_reading_mutated_artifact(self):
        ref = "febt-1-job-error-states"
        original = SOURCE.with_name(f"{ref}.md").read_text()
        # A minimal canonical bundle is enough to exercise the real render() restoration.
        bundle = "# Map\n\n## Flows\n\n## Not doing\n"
        class Model:
            @staticmethod
            def model_validate(doc):
                return doc
        with tempfile.TemporaryDirectory() as directory:
            maps = Path(directory)
            shutil.copyfile(SOURCE.with_name(f"{ref}.uxmap.json"), maps / f"{ref}.uxmap.json")
            (maps / f"{ref}.md").write_text(original.replace("No job running", "Xo job running"))
            with patch.object(renderer, "MAPS_DIR", maps), \
                    patch.object(renderer, "_load_renderer", return_value=(Model, lambda _: bundle)):
                rendered = renderer.render(ref)
            self.assertIn("No job running", rendered)
            self.assertNotIn("Xo job running", rendered)
            renderer._validate_retained_contract(ref, rendered)


if __name__ == "__main__":
    unittest.main()
