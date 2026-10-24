"""Causal offline tests. SNAPSHOT_CALLER_ORIGINAL=1 exposes the original RED."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import textwrap
from types import SimpleNamespace
import unittest

from snapshot_cursor import (
    RESULT_LIMIT_BYTES, ResultLimitExceeded, SnapshotTransaction,
    encode, synthetic_history, transport,
)
from snapshot_source import check, project_authority
from verify_inputs import INPUT_ROOT, baseline_contract, verify


BASELINE = baseline_contract()


def patched_excerpt(patch=None):
    """Read the complete one-hunk patch and verify its exact source context."""
    if patch is None:
        patch = Path(__file__).with_name("caller.patch").read_text()
    lines = patch.splitlines(keepends=True)
    assert lines[:3] == [
        "--- a/caller_excerpt.txt\n", "+++ b/caller_excerpt.txt\n",
        "@@ -1,3 +1,5 @@\n",
    ]
    assert all(line[0] in " +-" for line in lines[3:])
    before = "".join(line[1:] for line in lines[3:] if line[0] in " -")
    after = "".join(line[1:] for line in lines[3:] if line[0] in " +")
    assert before == (INPUT_ROOT / "caller_excerpt.txt").read_text()
    assert len(before.splitlines()) == 3 and len(after.splitlines()) == 5
    return after


class CallerHarness:
    """Only in-memory stand-ins: no native controller or service is loaded.

    view() evaluates the exact baseline return expression, so callers see the
    actual nested dict(authority=..., publications=..., loads=..., deferred=...)
    shape. native_job() applies the exact baseline encoding and strict
    `len(encoded) < 60000` predicate; nothing effectful is compiled or run.
    """

    def __init__(self, raw):
        self.raw = raw
        self.calls = []
        self.sealed = []
        self.jobs = []

    def view(self, paths, action, floor):
        self.calls.append(floor)
        return eval(BASELINE["view_return"], {
            "a": project_authority(self.raw, floor), "pubs": {}, "loads": [],
            "paths": SimpleNamespace(store=PurePosixPath("/synthetic-only")),
            "bounded_json": lambda *args, **kwargs: None,
        })

    def native_job(self, operation, timeout):
        assert timeout == 5
        encoded = json.dumps(operation()).encode()
        self.jobs.append(len(encoded))
        try:
            eval(BASELINE["transport_check"], {"encoded": encoded, "check": check})
        except RuntimeError:
            return 71 << 8, None
        return 0, json.loads(encoded)

    def preflight(self, excerpt, previous=None):
        namespace = {
            "previous": previous, "paths": None, "plan": {"action": "offline"},
            "ofd": None, "native_job": self.native_job, "view": self.view,
            "check": check,
            "seal": lambda ofd, name, value: self.sealed.append((name, value)),
        }
        exec(compile(textwrap.dedent(excerpt), "<supplied-caller-excerpt>", "exec"), namespace)
        return namespace

    def subsequent(self, floor):
        status, value = self.native_job(lambda: self.view(None, "offline", floor), 5)
        check(status == 0 and value is not None, "read-only preflight unknown")
        return value


class SnapshotTests(unittest.TestCase):
    def test_verified_source_and_exact_codemap(self):
        report = verify()
        self.assertEqual(len(report["files"]), 9)
        self.assertTrue(report["vendored_pure_source_identical"])
        self.assertTrue(report["exact_ast_codemap_verified"])

    def test_initial_caller_fits(self):
        # The same acceptance test runs on either exact original or exact patch.
        excerpt = ((INPUT_ROOT / "caller_excerpt.txt").read_text()
                   if os.environ.get("SNAPSHOT_CALLER_ORIGINAL") == "1"
                   else patched_excerpt())
        harness = CallerHarness(synthetic_history())
        result = harness.preflight(excerpt)
        self.assertLessEqual(len(encode(result["v"])), RESULT_LIMIT_BYTES)
        self.assertEqual(result["floor"], 258)
        self.assertEqual(type(result["floor"]), int)
        self.assertEqual(result["v"]["authority"]["intent_count"], 258)
        self.assertEqual(len(result["v"]["authority"]["intents"]), 1)
        self.assertEqual(harness.sealed, [("preflight.json", result["v"])])

    def test_original_large_case_fails_before_seal(self):
        harness = CallerHarness(synthetic_history())
        with self.assertRaisesRegex(RuntimeError, "read-only preflight unknown"):
            harness.preflight((INPUT_ROOT / "caller_excerpt.txt").read_text())
        self.assertEqual(harness.calls, [0])
        self.assertEqual(harness.sealed, [])
        self.assertGreater(len(encode(project_authority(harness.raw, 0))), 60000)

    def test_small_cause_removal_control_uses_unchanged_original(self):
        harness = CallerHarness(synthetic_history(2))
        result = harness.preflight((INPUT_ROOT / "caller_excerpt.txt").read_text())
        self.assertEqual(harness.calls, [0])
        self.assertEqual(len(result["v"]["authority"]["intents"]), 2)
        self.assertLess(len(encode(result["v"])), 60000)

    def test_pinned_floor_across_consecutive_observations(self):
        harness = CallerHarness(synthetic_history())
        first = harness.preflight(patched_excerpt())
        tx = SnapshotTransaction()
        self.assertEqual(tx.read(harness.raw), first["v"]["authority"])
        for high in (259, 260):
            data = json.loads(harness.raw)
            data["highest_sequence"] = high
            data["intents"]["synthetic-0258"]["metadata"] = f"changed at {high}"
            data["intents"][f"synthetic-{high:04d}"] = {"sequence": high}
            harness.raw = encode(data)
            value = harness.subsequent(first["floor"])["authority"]
            self.assertEqual(tx.read(harness.raw), value)
            self.assertEqual(first["floor"], 258)
            self.assertEqual(tx.floor, 258)
            self.assertEqual(value["highest_sequence"], high)
            self.assertEqual(value["intent_count"], high)
            self.assertEqual(
                {record["sequence"] for record in value["intents"].values()},
                set(range(258, high + 1)),
            )
            moving = project_authority(harness.raw, None)
            self.assertNotIn("synthetic-0258", moving["intents"])
            self.assertIn("synthetic-0258", value["intents"])
        self.assertEqual(harness.calls, [None, 258, 258])

    def test_older_unreturned_mutation_changes_full_digest(self):
        raw = synthetic_history()
        tx = SnapshotTransaction()
        before = tx.read(raw)
        data = json.loads(raw)
        data["intents"]["synthetic-0001"]["metadata"] = "older record changed"
        changed_raw = encode(data)
        after = tx.read(changed_raw)
        self.assertEqual(before["intents"], after["intents"])
        self.assertNotIn("synthetic-0001", after["intents"])
        self.assertEqual(before["intent_count"], after["intent_count"])
        self.assertEqual(before["highest_sequence"], after["highest_sequence"])
        self.assertNotEqual(before["sha256"], after["sha256"])
        self.assertEqual(before["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(after["sha256"], hashlib.sha256(changed_raw).hexdigest())
        self.assertEqual(raw, synthetic_history())  # no history was rewritten

    def test_digest_covers_exact_bytes_even_whitespace(self):
        raw = synthetic_history()
        spaced_raw = b" \n" + raw + b"\n"
        before = project_authority(raw, None)
        after = project_authority(spaced_raw, None)
        self.assertEqual(before["intents"], after["intents"])
        self.assertNotEqual(before["sha256"], after["sha256"])
        self.assertEqual(after["sha256"], hashlib.sha256(spaced_raw).hexdigest())

    def test_explicit_predecessor_is_inclusive_and_stays_pinned(self):
        previous = {"sequence": 257}
        raw = synthetic_history()
        tx = SnapshotTransaction(previous)
        value = tx.read(raw)
        harness = CallerHarness(raw)
        result = harness.preflight(patched_excerpt(), previous)
        self.assertEqual(value, result["v"]["authority"])
        self.assertEqual(result["floor"], 257)
        self.assertEqual(tx.floor, 257)
        self.assertEqual({v["sequence"] for v in value["intents"].values()}, {257, 258})
        self.assertEqual(previous, {"sequence": 257})

    def test_explicit_zero_still_means_full_history_and_can_exceed_limit(self):
        tx = SnapshotTransaction({"sequence": 0})
        with self.assertRaises(ResultLimitExceeded):
            tx.read(synthetic_history())
        self.assertEqual(tx.floor, 0)
        with self.assertRaisesRegex(RuntimeError, "read-only preflight unknown"):
            CallerHarness(synthetic_history()).preflight(patched_excerpt(), {"sequence": 0})

    def test_invalid_explicit_predecessor_refused(self):
        for floor in (None, True, False, -1, 1.5, "258", [], {}):
            with self.subTest(floor=floor):
                with self.assertRaisesRegex(RuntimeError, "unknown authority floor"):
                    SnapshotTransaction({"sequence": floor})
                with self.assertRaisesRegex(RuntimeError, "unknown authority floor"):
                    CallerHarness(synthetic_history()).preflight(
                        patched_excerpt(), {"sequence": floor}
                    )

    def test_empty_observation_pins_numeric_zero(self):
        tx = SnapshotTransaction()
        first = tx.read(synthetic_history(0))
        self.assertEqual(first["intents"], {})
        self.assertEqual(tx.floor, 0)
        self.assertEqual(tx.read(synthetic_history(1))["intent_count"], 1)
        self.assertEqual(tx.floor, 0)

    def test_equal_high_sequences_and_rejected_sequences_are_preserved(self):
        data = json.loads(synthetic_history(2))
        data["intents"]["tied"] = {"sequence": 2}
        data["rejected_sequences"] = [1]
        value = SnapshotTransaction().read(encode(data))
        self.assertEqual(set(value["intents"]), {"synthetic-0002", "tied"})
        self.assertEqual(value["intent_count"], 3)
        self.assertEqual(value["highest_sequence"], 2)
        self.assertEqual(value["rejected_sequences"], [1])

    def test_invalid_authority_and_unreturned_records_refused(self):
        invalid = [None, [], {}, {"intents": []}, {"intents": {}, "highest_sequence": -1}]
        for high in (None, True, False, "2", 2.0):
            invalid.append({"intents": {}, "highest_sequence": high})
        for record in (None, [], {}, {"sequence": True}, {"sequence": "1"}, {"sequence": 1.0}):
            data = json.loads(synthetic_history(2))
            data["intents"]["synthetic-0001"] = record
            invalid.append(data)
        for data in invalid:
            with self.subTest(data=data):
                tx = SnapshotTransaction()
                with self.assertRaises((RuntimeError, KeyError)):
                    tx.read(encode(data))
                self.assertIsNone(tx.floor)
        for raw in (b"{", b"\xff", b"null"):
            with self.subTest(raw=raw):
                with self.assertRaises((ValueError, RuntimeError)):
                    SnapshotTransaction().read(raw)

    def test_invalid_numeric_floor_checks_unchanged_in_pure_source(self):
        for floor in (True, False, -1, 1.0, "1", [], {}):
            with self.subTest(floor=floor):
                with self.assertRaisesRegex(RuntimeError, "unknown authority floor"):
                    project_authority(synthetic_history(2), floor)

    def test_fixed_transport_boundary_and_oversized_newest_refused(self):
        self.assertEqual(RESULT_LIMIT_BYTES, 60000)
        self.assertEqual(len(transport("x" * 59998)), 60000)
        with self.assertRaises(ResultLimitExceeded):
            transport("x" * 59999)
        data = json.loads(synthetic_history(1))
        data["intents"]["synthetic-0001"]["metadata"] = "x" * 60000
        tx = SnapshotTransaction()
        with self.assertRaises(ResultLimitExceeded):
            tx.read(encode(data))
        self.assertIsNone(tx.floor)


class ActualViewShapeTests(unittest.TestCase):
    """Regression for review 1659 / F-01: the caller sees view()'s nested shape."""

    def test_actual_view_shape_is_nested(self):
        value = CallerHarness(synthetic_history(2)).view(None, "auto", None)
        self.assertEqual(set(value), {"authority", "publications", "loads", "deferred"})
        self.assertNotIn("highest_sequence", value)
        self.assertEqual(value["authority"]["highest_sequence"], 2)

    def test_r3_seed_patch_raises_keyerror_on_actual_shape(self):
        # Retained RED control: the reviewed seed lookup fails before seal.
        seed = patched_excerpt(BASELINE["seed_patch"])
        for count in (0, 258):
            with self.subTest(records=count):
                harness = CallerHarness(synthetic_history(count))
                with self.assertRaisesRegex(KeyError, "highest_sequence"):
                    harness.preflight(seed)
                self.assertEqual(harness.calls, [None])
                self.assertEqual(harness.sealed, [])

    def test_empty_first_observation_pins_numeric_zero(self):
        harness = CallerHarness(synthetic_history(0))
        result = harness.preflight(patched_excerpt())
        self.assertEqual(result["floor"], 0)
        self.assertIs(type(result["floor"]), int)
        self.assertEqual(harness.calls, [None])
        self.assertEqual(harness.sealed, [("preflight.json", result["v"])])
        self.assertEqual(result["v"]["authority"]["intents"], {})
        harness.raw = synthetic_history(1)
        later = harness.subsequent(result["floor"])["authority"]
        self.assertEqual(set(later["intents"]), {"synthetic-0001"})
        self.assertEqual(harness.calls, [None, 0])

    def test_258_first_observation_pins_newest_for_later_reads(self):
        raw = synthetic_history()
        harness = CallerHarness(raw)
        result = harness.preflight(patched_excerpt())
        authority = result["v"]["authority"]
        self.assertEqual(result["floor"], 258)
        self.assertIs(type(result["floor"]), int)
        self.assertEqual(harness.sealed, [("preflight.json", result["v"])])
        self.assertLess(harness.jobs[0], 60000)
        self.assertEqual(authority["highest_sequence"], 258)
        self.assertEqual(authority["intent_count"], 258)
        self.assertEqual(authority["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(set(authority["intents"]), {"synthetic-0258"})
        # Unchanged bytes re-read at the pinned floor equal the sealed preflight,
        # as the later publication comparison (baseline line 421) requires.
        self.assertEqual(harness.subsequent(result["floor"]), result["v"])
        for high in (259, 260):
            data = json.loads(harness.raw)
            data["highest_sequence"] = high
            data["intents"][f"synthetic-{high:04d}"] = {"sequence": high}
            harness.raw = encode(data)
            later = harness.subsequent(result["floor"])["authority"]
            self.assertEqual({r["sequence"] for r in later["intents"].values()},
                             set(range(258, high + 1)))
            self.assertEqual(later["intent_count"], high)
            self.assertEqual(later["sha256"], hashlib.sha256(harness.raw).hexdigest())
        self.assertEqual(result["floor"], 258)
        self.assertEqual(harness.calls, [None, 258, 258, 258])

    def test_baseline_transport_predicate_is_strict(self):
        harness = CallerHarness(synthetic_history(0))
        self.assertEqual(harness.native_job(lambda: "x" * 59997, 5), (0, "x" * 59997))
        self.assertEqual(harness.native_job(lambda: "x" * 59998, 5), (71 << 8, None))
        self.assertEqual(harness.jobs, [59999, 60000])


if __name__ == "__main__":
    unittest.main()
