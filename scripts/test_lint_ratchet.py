"""Tests for the lint ratchet (scripts/lint_ratchet.py).

These exercise the comparison and accept logic against synthetic baselines, so
they are deterministic and do not shell out to eslint or ruff (TEST-08).

The load-bearing property under test is OBS-11: the recorded bar must ratchet
from the best demonstrated result. Every "accept cannot loosen" test below is a
direct assertion of that rule.
"""

from __future__ import annotations

import json

import pytest
from lint_ratchet import (
    Baseline,
    RatchetError,
    compare,
    compare_config_guard,
    load_baseline,
    tighten,
    write_baseline,
)


def mk(tool: str = "ruff", counts=None, guard=None) -> Baseline:
    return Baseline(tool=tool, counts=counts or {}, config_guard=guard or {})


# --------------------------------------------------------------------------
# compare(): the gate itself
# --------------------------------------------------------------------------


def test_identical_tree_is_clean():
    base = mk(counts={"a.py": {"E501": 2}})
    assert compare(base, mk(counts={"a.py": {"E501": 2}})).clean


def test_count_increase_is_a_regression():
    drift = compare(mk(counts={"a.py": {"E501": 2}}), mk(counts={"a.py": {"E501": 3}}))
    assert not drift.clean
    assert drift.regressions == ["a.py: E501 (2 -> 3)"]
    assert drift.stale == []


def test_new_file_with_a_violation_is_a_regression():
    drift = compare(mk(counts={"a.py": {"E501": 1}}), mk(counts={"a.py": {"E501": 1}, "b.py": {"F401": 1}}))
    assert drift.regressions == ["b.py: F401 (new violation)"]


def test_new_rule_in_an_already_dirty_file_is_a_regression():
    drift = compare(mk(counts={"a.py": {"E501": 1}}), mk(counts={"a.py": {"E501": 1, "F401": 1}}))
    assert drift.regressions == ["a.py: F401 (new violation)"]


def test_count_decrease_is_stale_not_clean():
    """OBS-11: an unrecorded improvement must not leave the bar sitting high."""
    drift = compare(mk(counts={"a.py": {"E501": 3}}), mk(counts={"a.py": {"E501": 1}}))
    assert not drift.clean
    assert drift.stale == ["a.py: E501 (3 -> 1)"]
    assert drift.regressions == []


def test_fully_fixed_entry_is_stale():
    drift = compare(mk(counts={"a.py": {"E501": 3}}), mk(counts={}))
    assert drift.stale == ["a.py: E501 (fixed)"]


def test_regression_and_improvement_are_reported_separately():
    drift = compare(
        mk(counts={"a.py": {"E501": 3}, "b.py": {"F401": 1}}),
        mk(counts={"a.py": {"E501": 1}, "b.py": {"F401": 4}}),
    )
    assert drift.regressions == ["b.py: F401 (1 -> 4)"]
    assert drift.stale == ["a.py: E501 (3 -> 1)"]


# --------------------------------------------------------------------------
# compare_config_guard(): the anti-suppression guard (sr-001)
# --------------------------------------------------------------------------


def test_disabling_a_baselined_eslint_rule_is_a_suppression():
    problems = compare_config_guard(
        {"enabled_rules": ["func-style", "quotes"]}, {"enabled_rules": ["quotes"]}
    )
    assert problems == ["rule 'func-style' was enabled in the baseline but is now off/absent"]


def test_enabling_more_eslint_rules_is_allowed():
    assert compare_config_guard({"enabled_rules": ["quotes"]}, {"enabled_rules": ["quotes", "eqeqeq"]}) == []


def test_dropping_a_ruff_select_code_is_a_suppression():
    assert compare_config_guard({"select": ["E", "W"]}, {"select": ["E"]}) == ["ruff select lost 'W'"]


def test_growing_the_ruff_ignore_list_is_a_suppression():
    assert compare_config_guard({"ignore": ["E501"]}, {"ignore": ["E501", "W191"]}) == [
        "ruff ignore gained 'W191'"
    ]


def test_growing_per_file_ignores_is_a_suppression():
    problems = compare_config_guard(
        {"per_file_ignores": {"tests/**": ["F401"]}},
        {"per_file_ignores": {"tests/**": ["F401", "W191"]}},
    )
    assert problems == ["ruff per-file-ignores['tests/**'] gained 'W191'"]


def test_suppression_alone_fails_the_gate_even_with_matching_counts():
    """A rule can be switched off in files that carry no violation today."""
    drift = compare(
        mk(counts={"a.py": {"E501": 1}}, guard={"enabled_rules": ["func-style"]}),
        mk(counts={"a.py": {"E501": 1}}, guard={"enabled_rules": []}),
    )
    assert not drift.clean
    assert drift.suppressions
    assert drift.regressions == [] and drift.stale == []


# --------------------------------------------------------------------------
# tighten(): accept can only ratchet down (OBS-11)
# --------------------------------------------------------------------------


def test_accept_records_a_genuine_improvement():
    accepted, refusals = tighten(mk(counts={"a.py": {"E501": 3}}), mk(counts={"a.py": {"E501": 1}}))
    assert refusals == []
    assert accepted.counts == {"a.py": {"E501": 1}}
    assert accepted.total == 1


def test_accept_drops_entries_that_reached_zero():
    accepted, refusals = tighten(mk(counts={"a.py": {"E501": 3}}), mk(counts={}))
    assert refusals == []
    assert accepted.counts == {}


def test_accept_refuses_to_raise_a_count():
    accepted, refusals = tighten(mk(counts={"a.py": {"E501": 1}}), mk(counts={"a.py": {"E501": 9}}))
    assert refusals == ["a.py: E501 (1 -> 9)"]
    assert "a.py" not in accepted.counts


def test_accept_refuses_to_add_a_new_entry():
    _, refusals = tighten(mk(counts={}), mk(counts={"b.py": {"F401": 1}}))
    assert refusals == ["b.py: F401 (new entry)"]


def test_accept_refuses_a_weakened_config_guard():
    _, refusals = tighten(
        mk(counts={}, guard={"ignore": []}),
        mk(counts={}, guard={"ignore": ["W191"]}),
    )
    assert refusals == ["ruff ignore gained 'W191'"]


def test_accept_keeps_untouched_entries_and_refuses_only_the_bad_one():
    accepted, refusals = tighten(
        mk(counts={"a.py": {"E501": 3}, "b.py": {"F401": 2}}),
        mk(counts={"a.py": {"E501": 1}, "b.py": {"F401": 5}}),
    )
    assert refusals == ["b.py: F401 (2 -> 5)"]
    assert accepted.counts == {"a.py": {"E501": 1}}


# --------------------------------------------------------------------------
# Baseline (de)serialisation and tamper detection
# --------------------------------------------------------------------------


def test_roundtrip_preserves_counts_and_guard(tmp_path):
    original = mk(counts={"a.py": {"E501": 2}}, guard={"select": ["E"]})
    write_baseline(original, tmp_path)
    loaded = load_baseline("ruff", tmp_path)
    assert loaded.counts == original.counts
    assert loaded.config_guard == original.config_guard
    assert loaded.total == 2


def test_missing_baseline_loads_as_empty(tmp_path):
    assert load_baseline("ruff", tmp_path).counts == {}


def test_hand_edited_count_without_total_is_tamper(tmp_path):
    write_baseline(mk(counts={"a.py": {"E501": 2}}), tmp_path)
    path = tmp_path / "ruff.json"
    payload = json.loads(path.read_text())
    payload["counts"]["a.py"]["E501"] = 99  # inflate the bar, leave total alone
    path.write_text(json.dumps(payload))
    with pytest.raises(RatchetError, match="TAMPER"):
        load_baseline("ruff", tmp_path)


def test_malformed_baseline_is_rejected(tmp_path):
    (tmp_path / "ruff.json").write_text('{"tool": "ruff", "version": 1}')
    with pytest.raises(RatchetError, match="missing required key"):
        load_baseline("ruff", tmp_path)


def test_negative_count_is_rejected(tmp_path):
    (tmp_path / "ruff.json").write_text(
        json.dumps({"tool": "ruff", "version": 1, "total": 0, "counts": {"a.py": {"E501": -1}}})
    )
    with pytest.raises(RatchetError, match="positive int"):
        load_baseline("ruff", tmp_path)


def test_tool_mismatch_is_rejected(tmp_path):
    write_baseline(mk(tool="eslint"), tmp_path)
    (tmp_path / "ruff.json").write_text((tmp_path / "eslint.json").read_text())
    with pytest.raises(RatchetError, match="declares tool"):
        load_baseline("ruff", tmp_path)
