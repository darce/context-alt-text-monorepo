"""S2R4-14 — stale-report scan must flag any scored identification block.

The previous audit treated a block as stale only when
``precision is not None``. Leftover reports published
``precision: null`` / ``recall: 0.0`` with a populated per-identity
table, so that scan reported clean.

This module drives ``scripts.eval_harness.scan_stale_reports`` against
scratch git repos and pins the classifier directly.
"""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.eval_harness.scan_stale_reports import (
    EXIT_CLEAN,
    EXIT_STALE,
    IdentVerdict,
    REFUSED_IDENTIFICATION_KEYS,
    _has_metric_fields,
    classify_identification,
    provenance_contradictions,
    scan_payload,
)


_THIS = Path(__file__).resolve()
_SCANNER = _THIS.parents[1] / "scan_stale_reports.py"


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init"], cwd=repo, check=True, capture_output=True, text=True
    )
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    return repo


def _track(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "--", rel], cwd=repo, check=True, capture_output=True)


def _commit(repo: Path, message: str) -> None:
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _run_scanner(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCANNER)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def _report(
    *,
    ident: dict | None,
    extra: dict | None = None,
    sha: str | None = None,
) -> str:
    payload: dict = {
        "kind": "report",
        "schema": "acx-eval/v1",
        "faces": {},
    }
    if ident is not None:
        payload["faces"]["identification"] = ident
    if sha is not None:
        payload["provenance"] = {"score_manifest_sha256": sha}
    if extra:
        payload.update(extra)
    return json.dumps(payload)


def _leftover_ident() -> dict:
    """Exact leftover shape the precision-only scan missed (S2R3-08)."""
    return {
        "precision": None,
        "recall": 0.0,
        "macro_precision": None,
        "macro_recall": 0.0,
        "per_identity": {
            "Russet Fathom": {
                "precision": None,
                "recall": 0.0,
                "tp": 0,
                "fp": 0,
                "fn": 1,
            }
        },
        "true_rejections": 0,
        "wrong_names": [],
    }


def _refused_ident() -> dict:
    return {
        "refused": True,
        "invariant": "identification_refuses_unboxed_identity_claims",
        "precision": None,
        "recall": None,
        "per_identity": {},
    }


def _greenwashed_ident() -> dict:
    """Refused stamp plus leftover identification metrics (F23-SCAN-01)."""
    return {
        "refused": True,
        "invariant": "identification_refuses_unboxed_identity_claims",
        "precision": None,
        "recall": None,
        "per_identity": {},
        "macro_recall": 0.0,
        "true_rejections": 1,
        "wrong_names": ["Ada was called Bob"],
        "tp": 0,
        "fp": 2,
        "fn": 1,
    }


def _refused_with_macro_precision() -> dict:
    return {
        "refused": True,
        "invariant": "identification_refuses_unboxed_identity_claims",
        "precision": None,
        "recall": None,
        "per_identity": {},
        "macro_precision": 0.75,
    }


def test_precision_null_recall_zero_populated_table_is_flagged(tmp_path: Path) -> None:
    """The exact leftover shape the precision-only scan missed (S2R3-08)."""
    repo = _init_repo(tmp_path)
    _track(
        repo,
        "docs/tasks/altq/bakeoff-results/run-altq-v1-standard-report.json",
        _report(ident=_leftover_ident(), sha="fc7ce548" + "0" * 56),
    )
    _commit(repo, "add leftover")
    proc = _run_scanner(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == EXIT_STALE, combined
    assert "SCORED" in combined
    assert "run-altq-v1-standard-report.json" in combined
    assert "precision=None" in combined
    assert "recall=0.0" in combined


def test_classifier_flags_leftover_as_scored() -> None:
    verdict, reason = classify_identification(_leftover_ident())
    assert verdict is IdentVerdict.SCORED
    assert "scored" in reason
    hit = scan_payload(
        "docs/x-report.json",
        {"faces": {"identification": _leftover_ident()}},
    )
    assert hit is not None
    assert hit.verdict is IdentVerdict.SCORED
    assert hit.precision is None
    assert hit.recall == 0.0
    assert hit.per_identity_rows == 1


def test_explicit_refusal_is_clean(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(
        repo,
        "docs/tasks/vlm/VLM-2A-baseline-20260706-report.json",
        _report(ident=_refused_ident(), sha="fc7ce548" + "0" * 56),
    )
    _commit(repo, "add refused")
    proc = _run_scanner(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == EXIT_CLEAN, combined
    assert "ok —" in proc.stdout
    assert "SCORED" not in combined
    assert "UNRECOGNIZED" not in combined


def test_classifier_accepts_explicit_refusal() -> None:
    verdict, _ = classify_identification(_refused_ident())
    assert verdict is IdentVerdict.REFUSED


def test_numeric_identification_score_is_flagged(tmp_path: Path) -> None:
    """Any scored block is stale here, including a numeric P/R."""
    repo = _init_repo(tmp_path)
    ident = {
        "refused": False,
        "precision": 0.5,
        "recall": 0.5,
        "per_identity": {
            "Ada": {"precision": 0.5, "recall": 0.5, "tp": 1, "fp": 1, "fn": 1}
        },
    }
    _track(repo, "docs/tasks/vlm/scored-report.json", _report(ident=ident))
    _commit(repo, "add numeric score")
    proc = _run_scanner(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == EXIT_STALE, combined
    assert "SCORED" in combined
    assert "precision=0.5" in combined


def test_missing_refused_key_empty_table_is_flagged(tmp_path: Path) -> None:
    """A scanner that only looks at a populated table would miss this."""
    repo = _init_repo(tmp_path)
    ident = {"precision": None, "recall": 0.0, "per_identity": {}}
    _track(
        repo,
        "docs/tasks/vlm/VLM-2B-bakeoff-MiniCPM-V-4.5-report.json",
        _report(ident=ident),
    )
    _commit(repo, "add empty-table leftover")
    proc = _run_scanner(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == EXIT_STALE, combined
    assert "SCORED" in combined


def test_refused_false_null_precision_is_flagged(tmp_path: Path) -> None:
    ident = {"refused": False, "precision": None, "recall": 0.0, "per_identity": {}}
    verdict, _ = classify_identification(ident)
    assert verdict is IdentVerdict.SCORED


def test_unrecognized_shape_is_reported_not_passed(tmp_path: Path) -> None:
    """rg-008: neither refused nor scored → UNRECOGNIZED, exit 1."""
    repo = _init_repo(tmp_path)
    _track(
        repo,
        "docs/tasks/vlm/weird-report.json",
        _report(ident={"refused": True, "precision": 0.9, "recall": 0.1}),
    )
    _commit(repo, "add unrecognized")
    proc = _run_scanner(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == EXIT_STALE, combined
    assert "UNRECOGNIZED" in combined
    assert "weird-report.json" in combined


def test_classifier_fails_closed_on_non_object() -> None:
    verdict, reason = classify_identification(["not", "a", "mapping"])
    assert verdict is IdentVerdict.UNRECOGNIZED
    assert "not an object" in reason


def test_classifier_fails_closed_on_empty_object() -> None:
    verdict, reason = classify_identification({})
    assert verdict is IdentVerdict.UNRECOGNIZED
    assert "no identification metric fields" in reason


def test_invalid_json_report_is_unrecognized(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/tasks/vlm/broken-report.json", "{not json")
    _commit(repo, "add broken")
    proc = _run_scanner(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == EXIT_STALE, combined
    assert "UNRECOGNIZED" in combined
    assert "broken-report.json" in combined


def test_report_without_identification_is_clean(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/tasks/vlm/caption-only-report.json", _report(ident=None))
    _commit(repo, "add caption-only")
    proc = _run_scanner(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == EXIT_CLEAN, combined
    assert "ok —" in proc.stdout


def test_no_report_files_is_a_failed_scan(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/README.md", "no reports\n")
    _commit(repo, "docs only")
    proc = _run_scanner(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == EXIT_STALE, combined
    assert "no tracked" in combined


def test_dated_report_filename_is_scanned(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ident = {"precision": None, "recall": 0.0, "per_identity": {"Ada": {}}}
    _track(
        repo,
        "docs/tasks/vlm/bakeoff-results/S0-determinism-anchor-report-20260714.json",
        _report(ident=ident),
    )
    _commit(repo, "add dated leftover")
    proc = _run_scanner(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == EXIT_STALE, combined
    assert "SCORED" in combined
    assert "S0-determinism-anchor-report-20260714.json" in combined


def test_same_sha_divergent_verdicts_is_a_contradiction(tmp_path: Path) -> None:
    sha = "73cbe113" + "a" * 56
    repo = _init_repo(tmp_path)
    _track(
        repo,
        "docs/tasks/20.0/E20-FUSION-adhoc-report.json",
        _report(ident=_refused_ident(), sha=sha),
    )
    _track(
        repo,
        "docs/tasks/vlm/VLM-2B-bakeoff-MiniCPM-V-4.5-report.json",
        _report(ident=_leftover_ident(), sha=sha),
    )
    _commit(repo, "add contradiction")
    proc = _run_scanner(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == EXIT_STALE, combined
    assert "PROVENANCE CONTRADICTIONS" in combined
    assert sha in combined
    assert "refused=1" in combined
    assert "scored=1" in combined
    assert "E20-FUSION-adhoc-report.json" in combined
    assert "VLM-2B-bakeoff-MiniCPM-V-4.5-report.json" in combined


def test_provenance_helper_groups_mixed_verdicts() -> None:
    sha = "fc7ce548" + "b" * 56
    refused = scan_payload(
        "docs/a-report.json",
        {
            "faces": {"identification": _refused_ident()},
            "provenance": {"score_manifest_sha256": sha},
        },
    )
    scored = scan_payload(
        "docs/b-report.json",
        {
            "faces": {"identification": _leftover_ident()},
            "provenance": {"score_manifest_sha256": sha},
        },
    )
    assert refused is not None and scored is not None
    groups = provenance_contradictions([refused, scored])
    assert sha in groups
    assert len(groups[sha]) == 2


def test_same_sha_all_refused_is_not_a_contradiction(tmp_path: Path) -> None:
    sha = "fc7ce548" + "c" * 56
    repo = _init_repo(tmp_path)
    _track(repo, "docs/tasks/vlm/a-report.json", _report(ident=_refused_ident(), sha=sha))
    _track(repo, "docs/tasks/vlm/b-report.json", _report(ident=_refused_ident(), sha=sha))
    _commit(repo, "add consistent")
    proc = _run_scanner(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == EXIT_CLEAN, combined
    assert "PROVENANCE CONTRADICTIONS" not in combined


def test_has_metric_fields_is_key_presence_not_precision_value() -> None:
    """The leftover shape has a precision key whose value is null."""
    leftover = _leftover_ident()
    assert leftover["precision"] is None
    assert _has_metric_fields(leftover) is True
    assert _has_metric_fields({"refused": True, "invariant": "x"}) is False


def test_greenwashed_refusal_is_unrecognized(tmp_path: Path) -> None:
    """A refused stamp that still names people it got wrong is not clean."""
    repo = _init_repo(tmp_path)
    _track(
        repo,
        "docs/tasks/vlm/greenwash-report.json",
        _report(ident=_greenwashed_ident()),
    )
    _commit(repo, "add greenwash")
    proc = _run_scanner(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == EXIT_STALE, combined
    assert "UNRECOGNIZED" in combined
    assert "greenwash-report.json" in combined
    assert "still publishes" in combined
    assert "macro_recall" in combined
    assert "wrong_names" in combined
    assert "true_rejections" in combined
    assert "tp" in combined


def test_classifier_flags_greenwashed_refusal() -> None:
    verdict, reason = classify_identification(_greenwashed_ident())
    assert verdict is IdentVerdict.UNRECOGNIZED
    assert reason == (
        "refused block still publishes fn, fp, macro_recall, "
        "tp, true_rejections, wrong_names"
    )


def test_refused_with_macro_precision_is_unrecognized(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(
        repo,
        "docs/tasks/vlm/macro-greenwash-report.json",
        _report(ident=_refused_with_macro_precision()),
    )
    _commit(repo, "add macro greenwash")
    proc = _run_scanner(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == EXIT_STALE, combined
    assert "UNRECOGNIZED" in combined
    assert "macro-greenwash-report.json" in combined
    assert "refused block still publishes macro_precision" in combined


def test_classifier_flags_refused_macro_precision() -> None:
    verdict, reason = classify_identification(_refused_with_macro_precision())
    assert verdict is IdentVerdict.UNRECOGNIZED
    assert reason == "refused block still publishes macro_precision"


def test_refused_whitelist_tracks_scorer_emitted_keys() -> None:
    """rg-015: scanner whitelist must match report.py's refused shape."""
    from scripts.eval_harness.report import _refused_identification_metric

    emitted = frozenset(
        _refused_identification_metric(
            "identification_refuses_unboxed_identity_claims"
        )
    )
    expected = frozenset(
        {
            "refused",
            "invariant",
            "precision",
            "recall",
            "macro_precision",
            "macro_recall",
            "per_identity",
            "true_rejections",
            "excluded_images",
            "wrong_names",
            "ignored_wrong_names",
        }
    )
    assert emitted == expected
    assert REFUSED_IDENTIFICATION_KEYS == expected


def test_scorer_emitted_refusal_classifies_clean() -> None:
    from scripts.eval_harness.report import _refused_identification_metric

    block = _refused_identification_metric(
        "identification_refuses_unboxed_identity_claims"
    )
    verdict, reason = classify_identification(block)
    assert verdict is IdentVerdict.REFUSED
    assert reason == "explicit refusal"


def test_absent_manifest_sha_is_not_a_contradiction(tmp_path: Path) -> None:
    """Two reports that both omit score_manifest_sha256 do not share a SHA."""
    repo = _init_repo(tmp_path)
    _track(
        repo,
        "docs/tasks/vlm/a-report.json",
        _report(ident=_refused_ident()),
    )
    _track(
        repo,
        "docs/tasks/vlm/b-report.json",
        _report(ident=_leftover_ident()),
    )
    _commit(repo, "add unprovenanced pair")
    proc = _run_scanner(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == EXIT_STALE, combined
    assert "SCORED" in combined
    assert "PROVENANCE CONTRADICTIONS" not in combined
    assert "sha256=(missing)" not in combined


def test_provenance_helper_does_not_group_missing_sha() -> None:
    refused = scan_payload(
        "docs/a-report.json",
        {"faces": {"identification": _refused_ident()}},
    )
    scored = scan_payload(
        "docs/b-report.json",
        {"faces": {"identification": _leftover_ident()}},
    )
    assert refused is not None and scored is not None
    assert refused.score_manifest_sha256 is None
    assert scored.score_manifest_sha256 is None
    assert provenance_contradictions([refused, scored]) == {}


def test_lazy_precision_predicate_misses_leftover_and_cannot_pass() -> None:
    """Characterization: the retired filter is exactly why S2R4-14 existed.

    A walk-around that restores ``precision is not None`` as the scored
    predicate cannot satisfy the leftover-shape pin.
    """
    leftover = _leftover_ident()
    retired = leftover.get("precision") is not None
    assert retired is False
    verdict, _ = classify_identification(leftover)
    assert verdict is IdentVerdict.SCORED
    metric_src = inspect.getsource(_has_metric_fields)
    classify_src = inspect.getsource(classify_identification)
    assert "precision is not None" not in metric_src
    assert "precision is not None" not in classify_src
    assert "_has_metric_fields" in classify_src
