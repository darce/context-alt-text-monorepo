"""Mutation probes for the renderer's fail-closed checks and regeneration boundary."""

import contextlib
import importlib.util
import io
import json
import re
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
    def test_markdown_newlines_pass_both_check_paths(self):
        ref = "workbench-operator-loop"
        original = SOURCE.with_name(f"{ref}.md").read_text()
        with tempfile.TemporaryDirectory() as directory:
            maps = Path(directory)
            shutil.copyfile(SOURCE.with_name(f"{ref}.uxmap.json"), maps / f"{ref}.uxmap.json")
            with patch.object(renderer, "MAPS_DIR", maps):
                for available in [False, True]:
                    with patch.object(renderer, "render", return_value=original,
                                      side_effect=None if available else renderer.OptionalRendererUnavailable()):
                        for newline in ["\n", "\r\n"]:
                            with self.subTest(available=available, newline=repr(newline)):
                                (maps / f"{ref}.md").write_bytes(original.replace("\n", newline).encode("utf8"))
                                output = io.StringIO()
                                with contextlib.redirect_stderr(output), contextlib.redirect_stdout(io.StringIO()):
                                    self.assertEqual(renderer.check([ref]), 0, output.getvalue())

    def test_declaration_variants_fail_both_check_paths(self):
        ref = "febt-1-job-error-states"
        original = SOURCE.with_name(f"{ref}.md").read_text()
        fixtures = renderer.REPO_ROOT / "apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-render-parity.fixtures"
        fixture = json.loads((fixtures / "declaration-mutations.json").read_text())
        # Supply optional declarations so every consumed key participates.
        states = ", ".join(json.loads(SOURCE.with_name(f"{ref}.uxmap.json").read_text())["screens"][0]["states"])
        original = original.replace("Purpose:", f"url_params: `probe`\n\nScreen states: {states}\n\nPurpose:", 1)
        with tempfile.TemporaryDirectory() as directory:
            maps = Path(directory)
            shutil.copyfile(SOURCE.with_name(f"{ref}.uxmap.json"), maps / f"{ref}.uxmap.json")
            target = maps / f"{ref}.md"
            with patch.object(renderer, "MAPS_DIR", maps):
                for available in [False, True]:
                    with patch.object(renderer, "render", return_value=original,
                                      side_effect=None if available else renderer.OptionalRendererUnavailable()):
                        for field in fixture["keys"]:
                            row = re.search(rf"^{field}: .*$", original, re.MULTILINE)[0]
                            # TypeScript covers the full Cartesian product in-process.
                            # Exercise every format/key through both process boundaries,
                            # distributing case, value and order across these probes.
                            for index, template in enumerate(fixture["variants"]):
                                key = [field, field.upper(), field.lower()][index % 3]
                                value = row.split(": ", 1)[1] if index % 2 else "retired_state"
                                duplicate = template.format(key=key, value=value)
                                rows = [duplicate, row] if index % 2 else [row, duplicate]
                                with self.subTest(available=available, field=field, duplicate=duplicate):
                                    mutant = original.replace(row, "\n\n".join(rows), 1)
                                    target.write_text(mutant)
                                    output = io.StringIO()
                                    with contextlib.redirect_stderr(output), contextlib.redirect_stdout(io.StringIO()):
                                        self.assertEqual(renderer.check([ref]), 1)
                                    first = mutant[:mutant.index("\n\n".join(rows))].count("\n") + 1
                                    self.assertIn(f"duplicate {field} declarations at lines {first} and {first + 2}", output.getvalue())

    def test_duplicate_screen_metadata_fails_both_check_paths(self):
        ref = "workbench-operator-loop"
        original = SOURCE.with_name(f"{ref}.md").read_text()
        with tempfile.TemporaryDirectory() as directory:
            maps = Path(directory)
            shutil.copyfile(SOURCE.with_name(f"{ref}.uxmap.json"), maps / f"{ref}.uxmap.json")
            target = maps / f"{ref}.md"
            with patch.object(renderer, "MAPS_DIR", maps):
                for available in [False, True]:
                    with patch.object(renderer, "render", return_value=original,
                                      side_effect=None if available else renderer.OptionalRendererUnavailable()):
                        target.write_text(original)
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(renderer.check([ref]), 0)
                        for field in ["Purpose", "url_params"]:
                            row = re.search(rf"^{field}: .*$", original, re.MULTILINE)[0]
                            for duplicate in [row, f"{field}: contradictory metadata"]:
                                for rows in [f"{row}\n\n{duplicate}", f"{duplicate}\n\n{row}"]:
                                    with self.subTest(available=available, field=field, rows=rows):
                                        target.write_text(original.replace(row, rows, 1))
                                        output = io.StringIO()
                                        with contextlib.redirect_stderr(output), contextlib.redirect_stdout(io.StringIO()):
                                            self.assertEqual(renderer.check([ref]), 1)
                                        self.assertIn(f"screen workbench-shell has duplicate {field} declarations", output.getvalue())

    def test_duplicate_screen_states_fail_both_check_paths(self):
        ref = "describe-gpu-tier"
        original = SOURCE.with_name(f"{ref}.md").read_text()
        source = json.loads(SOURCE.with_name(f"{ref}.uxmap.json").read_text())
        row = "Screen states: " + ", ".join(source["screens"][0]["states"])
        original = original.replace("Purpose:", row + "\n\nPurpose:", 1)
        fixtures = renderer.REPO_ROOT / "apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-render-parity.fixtures"
        mutations = json.loads((fixtures / "screen-state-mutations.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            maps = Path(directory)
            shutil.copyfile(SOURCE.with_name(f"{ref}.uxmap.json"), maps / f"{ref}.uxmap.json")
            target = maps / f"{ref}.md"
            with patch.object(renderer, "MAPS_DIR", maps):
                for available in [False, True]:
                    with patch.object(renderer, "render", return_value=original,
                                      side_effect=None if available else renderer.OptionalRendererUnavailable()):
                        target.write_text(original)
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(renderer.check([ref]), 0)
                        for mutation in mutations:
                            duplicate = row if mutation["value"] is None else "Screen states: " + mutation["value"]
                            rows = [duplicate, row] if mutation["before"] else [row, duplicate]
                            with self.subTest(available=available, mutation=mutation["name"]):
                                target.write_text(original.replace(row, "\n\n".join(rows), 1))
                                output = io.StringIO()
                                with contextlib.redirect_stderr(output), contextlib.redirect_stdout(io.StringIO()):
                                    self.assertEqual(renderer.check([ref]), 1)
                                self.assertIn("has duplicate Screen states declarations", output.getvalue())

    def test_duplicate_action_states_fail_both_check_paths(self):
        ref = "febt-1-job-error-states"
        original = SOURCE.with_name(f"{ref}.md").read_text()
        row = re.search(r"^Action states: .*$", original, re.MULTILINE)[0]
        fixtures = renderer.REPO_ROOT / "apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-render-parity.fixtures"
        mutations = json.loads((fixtures / "action-state-mutations.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            maps = Path(directory)
            shutil.copyfile(SOURCE.with_name(f"{ref}.uxmap.json"), maps / f"{ref}.uxmap.json")
            target = maps / f"{ref}.md"
            with patch.object(renderer, "MAPS_DIR", maps):
                for available in [False, True]:
                    with patch.object(renderer, "render", return_value=original,
                                      side_effect=None if available else renderer.OptionalRendererUnavailable()):
                        target.write_text(original)
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(renderer.check([ref]), 0)
                        for mutation in mutations:
                            duplicate = row if mutation["value"] is None else "Action states: " + mutation["value"]
                            rows = [duplicate, row] if mutation["before"] else [row, duplicate]
                            with self.subTest(available=available, mutation=mutation["name"]):
                                target.write_text(original.replace(row, "\n\n".join(rows), 1))
                                output = io.StringIO()
                                with contextlib.redirect_stderr(output), contextlib.redirect_stdout(io.StringIO()):
                                    self.assertEqual(renderer.check([ref]), 1)
                                self.assertIn("has duplicate Action states declarations", output.getvalue())

    def test_action_rows_and_duplicate_sections_fail_both_check_paths(self):
        ref = "febt-1-job-error-states"
        original = SOURCE.with_name(f"{ref}.md").read_text()
        row = re.search(r"^\| `reload` \|.*$", original, re.MULTILINE)[0]
        conflicting = row.replace("Reload page", "Retry")
        mutations = [
            (original.replace(row, bad + "\n" + row), "noncanonical Actions table row: " + bad)
            for bad in [conflicting.replace("`reload`", "reload"), "  " + conflicting]
        ]
        mutations.append((original.replace(row, conflicting + "\n" + row), "action reload has duplicate Actions table rows"))
        for heading in ["Goals", "Jobs", "Screens", "Actions", "Flows", "Parity index", "Not doing"]:
            mutations.append((original + f"\n## {heading}\n\n" + conflicting + "\n", f"duplicate machine-owned section: {heading}"))
        for heading in ["## Actions ", "  ## Actions", "## Actions ##"]:
            mutations.append((original + f"\n{heading}\n\n" + conflicting + "\n", "duplicate machine-owned section: Actions"))
        with tempfile.TemporaryDirectory() as directory:
            maps = Path(directory)
            shutil.copyfile(SOURCE.with_name(f"{ref}.uxmap.json"), maps / f"{ref}.uxmap.json")
            target = maps / f"{ref}.md"
            with patch.object(renderer, "MAPS_DIR", maps):
                for available in [False, True]:
                    with patch.object(renderer, "render", return_value=original,
                                      side_effect=None if available else renderer.OptionalRendererUnavailable()):
                        target.write_text(original)
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(renderer.check([ref]), 0)
                        for mutant, error in mutations:
                            with self.subTest(renderer_available=available, error=error):
                                target.write_text(mutant)
                                output = io.StringIO()
                                with contextlib.redirect_stderr(output), contextlib.redirect_stdout(io.StringIO()):
                                    self.assertEqual(renderer.check([ref]), 1)
                                self.assertIn(error, output.getvalue())

    def test_regeneration_with_omitted_optional_action_fields(self):
        ref = "workbench-operator-loop"
        doc = json.loads(SOURCE.with_name(f"{ref}.uxmap.json").read_text())
        original = SOURCE.with_name(f"{ref}.md").read_text()
        for action in doc["actions"]:
            for field in ["costly", "irreversible", "preview_required"]:
                if action.get(field) is False:
                    del action[field]
            if action.get("screen_id") is None:
                del action["screen_id"]
        with tempfile.TemporaryDirectory() as directory:
            maps = Path(directory)
            (maps / f"{ref}.uxmap.json").write_text(json.dumps(doc))
            snapshot = maps / "visible.json"
            shutil.copyfile(renderer.VISIBLE_PROJECTION_PATH, snapshot)
            with patch.object(renderer, "MAPS_DIR", maps), patch.object(renderer, "VISIBLE_PROJECTION_PATH", snapshot):
                # Defaults preserve the committed output; exercise the real action
                # renderer and snapshot writer without requiring the canvas package.
                regenerated = re.sub(r"## Actions\n[\s\S]*?(?=\n## )", "\n".join(renderer._action_table(doc)), original)
                with patch.object(renderer, "render", return_value=regenerated), contextlib.redirect_stdout(io.StringIO()):
                    renderer._render_and_write([ref])
                for rendered in [None, regenerated]:
                    expected, actual = renderer._check_projection(ref, rendered)
                    self.assertEqual(expected, actual)

    def test_noncanonical_screen_rows_fail_both_check_paths_with_row_text(self):
        ref = "workbench-operator-loop"
        original = SOURCE.with_name(f"{ref}.md").read_text()
        row = re.search(r"^\| `workbench-shell` \|.*$", original, re.MULTILINE)[0]
        fixtures = renderer.REPO_ROOT / "apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-render-parity.fixtures"
        mutations = json.loads((fixtures / "screen-summary-mutations.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            maps = Path(directory)
            shutil.copyfile(SOURCE.with_name(f"{ref}.uxmap.json"), maps / f"{ref}.uxmap.json")
            target = maps / f"{ref}.md"
            with patch.object(renderer, "MAPS_DIR", maps):
                for renderer_available in [False, True]:
                    # Exercise the real check/projection in both branches; only the
                    # optional canvas renderer is replaced with its committed output.
                    with patch.object(renderer, "render", return_value=original,
                                      side_effect=None if renderer_available else renderer.OptionalRendererUnavailable()):
                        target.write_text(original)
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(renderer.check([ref]), 0)
                        for mutation in mutations:
                            with self.subTest(renderer_available=renderer_available, mutation=mutation["name"]):
                                target.write_text(original.replace(row, mutation["row"] + "\n" + row, 1))
                                output = io.StringIO()
                                with contextlib.redirect_stderr(output), contextlib.redirect_stdout(io.StringIO()):
                                    status = renderer.check([ref])
                                self.assertEqual(status, 1)
                                self.assertIn("noncanonical Screens table row: " + mutation["row"], output.getvalue())

    def test_domain_state_rows_fail_both_check_paths(self):
        ref = "workbench-operator-loop"
        original = SOURCE.with_name(f"{ref}.md").read_text()
        row = re.search(r"^\| `unavailable` \|.*$", original, re.MULTILINE)[0]
        fixtures = renderer.REPO_ROOT / "apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-render-parity.fixtures"
        mutations = json.loads((fixtures / "domain-state-mutations.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            maps = Path(directory)
            shutil.copyfile(SOURCE.with_name(f"{ref}.uxmap.json"), maps / f"{ref}.uxmap.json")
            target = maps / f"{ref}.md"
            with patch.object(renderer, "MAPS_DIR", maps):
                for renderer_available in [False, True]:
                    # Exercise the real check/projection in both branches; only the
                    # optional canvas renderer is replaced with its committed output.
                    with patch.object(renderer, "render", return_value=original,
                                      side_effect=None if renderer_available else renderer.OptionalRendererUnavailable()):
                        target.write_text(original)
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(renderer.check([ref]), 0)
                        for mutation in mutations:
                            with self.subTest(renderer_available=renderer_available, mutation=mutation["name"]):
                                target.write_text(original.replace(row, mutation["row"] + "\n" + row, 1))
                                output = io.StringIO()
                                with contextlib.redirect_stderr(output), contextlib.redirect_stdout(io.StringIO()):
                                    status = renderer.check([ref])
                                self.assertEqual(status, 1)
                                self.assertIn("Domain state mapping", output.getvalue())

    def test_unrecognized_screen_headings_fail_both_check_paths(self):
        ref = "workbench-operator-loop"
        original = SOURCE.with_name(f"{ref}.md").read_text()
        row = re.search(r"^\| `workbench-shell` \|.*$", original, re.MULTILINE)[0].replace("workbench-shell", "retired-screen")
        screen_end = original.index("\n## ", original.index("## Screens\n") + 1) + 1
        boundaries = [match.start() for match in re.finditer(r"^### .+$", original[:screen_end], re.MULTILINE)]
        boundaries.append(screen_end)
        with tempfile.TemporaryDirectory() as directory:
            maps = Path(directory)
            shutil.copyfile(SOURCE.with_name(f"{ref}.uxmap.json"), maps / f"{ref}.uxmap.json")
            target = maps / f"{ref}.md"
            with patch.object(renderer, "MAPS_DIR", maps):
                for available in [False, True]:
                    with patch.object(renderer, "render", return_value=original,
                                      side_effect=None if available else renderer.OptionalRendererUnavailable()):
                        for heading in ["### Retired screen inventory", "  ### Retired screen inventory"]:
                            inventory = f"{heading}\n\n| id | kind | route | title |\n| --- | --- | --- | --- |\n{row}\n\n"
                            for boundary in boundaries:
                                with self.subTest(available=available, heading=heading, boundary=boundary):
                                    target.write_text(original[:boundary] + inventory + original[boundary:])
                                    output = io.StringIO()
                                    with contextlib.redirect_stderr(output), contextlib.redirect_stdout(io.StringIO()):
                                        self.assertEqual(renderer.check([ref]), 1)
                                    self.assertIn("noncanonical Screens detail heading: " + heading, output.getvalue())

    def test_optional_zone_states_and_empty_extensions_match_both_check_paths(self):
        ref = "workbench-operator-loop"
        original = SOURCE.with_name(f"{ref}.md").read_text()
        for field in ["zone.states", "slices", "domain_state_mappings"]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                doc = json.loads(SOURCE.with_name(f"{ref}.uxmap.json").read_text())
                regenerated = original
                if field == "zone.states":
                    screen = doc["screens"][0]
                    before = "\n".join(renderer._screen_block(screen))
                    del screen["zones"][0]["states"]
                    after = "\n".join(renderer._screen_block(screen))
                    # Older artifacts omit the explicit screen-states line. Replace
                    # the zone row emitted by the real Python screen renderer.
                    before_row = next(line for line in before.splitlines() if line.startswith("| `z-tabs`"))
                    after_row = next(line for line in after.splitlines() if line.startswith("| `z-tabs`"))
                    regenerated = regenerated.replace(before_row, after_row)
                    self.assertNotEqual(regenerated, original)
                else:
                    doc[field] = []
                    heading = "Suggested task-slice decomposition (from map)" if field == "slices" else "Domain state mapping"
                    regenerated = re.sub(r"^## " + re.escape(heading) + r"\n[\s\S]*?(?=^## |\Z)", "", regenerated, flags=re.MULTILINE)
                    self.assertEqual(renderer._slice_section(doc) if field == "slices" else renderer._domain_state_mapping(doc), [])
                maps = Path(directory)
                (maps / f"{ref}.uxmap.json").write_text(json.dumps(doc))
                (maps / f"{ref}.md").write_text(regenerated)
                snapshot = maps / "visible.json"
                with patch.object(renderer, "MAPS_DIR", maps), patch.object(renderer, "VISIBLE_PROJECTION_PATH", snapshot):
                    snapshot.write_text(renderer._updated_visible_snapshot({ref: regenerated}))
                    for available in [False, True]:
                        with patch.object(renderer, "render", return_value=regenerated,
                                          side_effect=None if available else renderer.OptionalRendererUnavailable()), \
                                contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(renderer.check([ref]), 0)

    def test_duplicate_retained_contract_cannot_hide_an_unchecked_table(self):
        text = SOURCE.with_name("febt-1-job-error-states.md").read_text()
        heading = "## Detailed reducer and recovery contract"
        for variant in [heading, heading + " ##", "  " + heading, heading + " \t", "   " + heading + " ### \t"]:
            with self.subTest(heading=variant), self.assertRaisesRegex(ValueError, "duplicate retained contract"):
                renderer._extract_kept_text(text + f"\n{variant}\n\n| auth_expired | Retry |\n")

    def test_retained_heading_variants_and_zone_rows_fail_both_check_paths(self):
        ref = "febt-1-job-error-states"
        original = SOURCE.with_name(f"{ref}.md").read_text()
        heading = "## Detailed reducer and recovery contract"
        variants = [heading + " ##", "  " + heading, heading + " \t", "   " + heading + " ### \t"]
        mutations = [
            (original + f"\n{variant}\n\n| auth_expired | Retry |\n", "duplicate retained contract")
            for variant in variants
        ]
        # A variant must also be detected when it replaces the only contract heading.
        for variant in variants:
            before, contract = original.split(heading, 1)
            mutant = before + variant + contract.replace("Reload page", "Incorrect recovery")
            mutations.append((mutant, "retainedContracts"))
        row = re.search(r"^\| `error-action` \|.*$", original, re.MULTILINE)[0]
        fixtures = renderer.REPO_ROOT / "apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-render-parity.fixtures"
        for mutation in json.loads((fixtures / "zone-row-mutations.json").read_text()):
            bad = mutation["row"]
            mutations.append((original.replace(row, bad + "\n" + row), "noncanonical Zones table row: " + bad))
        for duplicate in [row, "| `error-action` | Incorrect recovery | form | error |"]:
            mutations.append((original.replace(row, duplicate + "\n" + row), "zone error-action has duplicate Zones table rows"))
        with tempfile.TemporaryDirectory() as directory:
            maps = Path(directory)
            shutil.copyfile(SOURCE.with_name(f"{ref}.uxmap.json"), maps / f"{ref}.uxmap.json")
            target = maps / f"{ref}.md"
            with patch.object(renderer, "MAPS_DIR", maps):
                for available in [False, True]:
                    with patch.object(renderer, "render", return_value=original,
                                      side_effect=None if available else renderer.OptionalRendererUnavailable()):
                        target.write_text(original)
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(renderer.check([ref]), 0)
                        for mutant, error in mutations:
                            with self.subTest(available=available, error=error):
                                target.write_text(mutant)
                                output = io.StringIO()
                                with contextlib.redirect_stderr(output), contextlib.redirect_stdout(io.StringIO()):
                                    self.assertEqual(renderer.check([ref]), 1)
                                self.assertIn(error, output.getvalue())

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
