"""Tests for the lint ratchet (scripts/lint_ratchet.py).

These exercise the comparison and accept logic against synthetic baselines, so
they are deterministic and do not shell out to eslint or ruff (TEST-08).

The load-bearing property under test is OBS-11: the recorded bar must ratchet
from the best demonstrated result. Every "accept cannot loosen" test below is a
direct assertion of that rule.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import lint_ratchet
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


# --------------------------------------------------------------------------
# ruff-format ratchet (LINTGATE1-NEW-03)
# --------------------------------------------------------------------------


def test_newly_unformatted_file_is_a_regression():
    """The whole point of the format ratchet: new drift must fail the gate."""
    drift = compare(
        mk(tool="ruff-format", counts={"a.py": {"unformatted": 1}}),
        mk(tool="ruff-format", counts={"a.py": {"unformatted": 1}, "b.py": {"unformatted": 1}}),
    )
    assert not drift.clean
    assert drift.regressions == ["b.py: unformatted (new violation)"]


def test_reformatted_file_is_stale_not_clean():
    drift = compare(
        mk(tool="ruff-format", counts={"a.py": {"unformatted": 1}, "b.py": {"unformatted": 1}}),
        mk(tool="ruff-format", counts={"a.py": {"unformatted": 1}}),
    )
    assert not drift.clean
    assert drift.stale


def test_changing_a_ruff_format_option_is_a_suppression():
    """Flipping indent-style to tab would make every baselined file 'pass'
    without a single one being fixed, so redefining "formatted" must fail."""
    problems = compare_config_guard(
        {"format_options": {"indent-style": "space", "quote-style": "double"}},
        {"format_options": {"indent-style": "tab", "quote-style": "double"}},
    )
    assert problems == ["ruff format option 'indent-style' changed 'space' -> 'tab'"]


def test_identical_ruff_format_options_are_clean():
    guard = {"format_options": {"indent-style": "space", "quote-style": "double"}}
    assert compare_config_guard(guard, dict(guard)) == []


def test_dropping_a_ruff_format_option_is_flagged():
    problems = compare_config_guard(
        {"format_options": {"quote-style": "double"}}, {"format_options": {}}
    )
    assert problems == ["ruff format option 'quote-style' changed 'double' -> None"]


def test_format_accept_cannot_add_a_newly_unformatted_file():
    """OBS-11 for the format ratchet: --accept may only shrink the frozen set."""
    base = mk(tool="ruff-format", counts={"a.py": {"unformatted": 1}})
    accepted, refusals = tighten(
        base,
        mk(tool="ruff-format", counts={"a.py": {"unformatted": 1}, "b.py": {"unformatted": 1}}),
    )
    assert refusals == ["b.py: unformatted (new entry)"]
    assert "b.py" not in accepted.counts


def test_format_accept_records_paid_down_debt():
    base = mk(tool="ruff-format", counts={"a.py": {"unformatted": 1}, "b.py": {"unformatted": 1}})
    accepted, refusals = tighten(base, mk(tool="ruff-format", counts={"a.py": {"unformatted": 1}}))
    assert refusals == []
    assert accepted.counts == {"a.py": {"unformatted": 1}}
    assert accepted.total == 1


# --------------------------------------------------------------------------
# Tool resolution must be cwd-independent (LINTGATE1-NEW-03)
# --------------------------------------------------------------------------


def test_ruff_is_resolved_to_an_explicit_path_not_a_bare_name(monkeypatch):
    """A bare `ruff` lands on the pyenv shim, which resolves its version from
    the *caller's* directory. `make lint` from apps/prototype-description-service/
    then died with "ruff: command not found" while the same run from the repo
    root passed. A gate whose verdict depends on the invoking directory is not
    a gate, so the collectors must never shell out to a bare tool name.
    """
    seen: list[list[str]] = []

    def fake_run(cmd, cwd):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr(lint_ratchet, "_run", fake_run)
    lint_ratchet.collect_ruff()
    lint_ratchet.collect_ruff_format()

    assert seen, "collectors did not invoke _run"
    for cmd in seen:
        assert cmd[0] != "ruff", (
            f"collector shelled out to a bare 'ruff' ({cmd}); use _ruff_bin() so the "
            "gate does not depend on the caller's directory"
        )
        assert Path(cmd[0]).is_absolute() or shutil.which(cmd[0]), (
            f"ruff path {cmd[0]!r} is neither absolute nor resolvable"
        )


def test_ruff_bin_prefers_the_repo_venv_over_path(monkeypatch, tmp_path):
    """The repo venv is the deterministic source; PATH is the fallback only."""
    venv_ruff = tmp_path / ".venv" / "bin" / "ruff"
    venv_ruff.parent.mkdir(parents=True)
    venv_ruff.write_text("#!/bin/sh\n")
    monkeypatch.setattr(lint_ratchet, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(shutil, "which", lambda _name: "/somewhere/else/ruff")
    assert lint_ratchet._ruff_bin() == str(venv_ruff)


def test_ruff_bin_errors_when_nothing_is_resolvable(monkeypatch, tmp_path):
    monkeypatch.setattr(lint_ratchet, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(RatchetError, match="not found"):
        lint_ratchet._ruff_bin()


def test_ruff_format_uses_json_output_not_the_human_renderer(monkeypatch):
    """ruff 0.16 replaced the stable "Would reformat: <path>" lines with a rich
    diagnostic block; scraping it would have silently reported zero drift."""
    seen: list[list[str]] = []

    def fake_run(cmd, cwd):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr(lint_ratchet, "_run", fake_run)
    lint_ratchet.collect_ruff_format()
    assert seen[0][1:4] == ["format", "--check", "--output-format"]
    assert seen[0][4] == "json"


def test_ruff_format_drift_without_named_files_is_an_error(monkeypatch):
    """Exit 1 with an empty file list means the output contract changed; that
    must fail loudly rather than bless an empty baseline."""
    monkeypatch.setattr(
        lint_ratchet,
        "_run",
        lambda cmd, cwd: subprocess.CompletedProcess(cmd, 1, stdout="[]", stderr=""),
    )
    with pytest.raises(RatchetError, match="named no files"):
        lint_ratchet.collect_ruff_format()


def test_ruff_format_unexpected_exit_code_is_an_error(monkeypatch):
    monkeypatch.setattr(
        lint_ratchet,
        "_run",
        lambda cmd, cwd: subprocess.CompletedProcess(cmd, 2, stdout="", stderr="boom"),
    )
    with pytest.raises(RatchetError, match="exit 2"):
        lint_ratchet.collect_ruff_format()
