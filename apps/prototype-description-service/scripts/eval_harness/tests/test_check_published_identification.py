"""S2R4-14 — published identification scan must catch the S2R3-08 leftover.

The previous audit treated a block as stale only when
``precision is not None``. The leftover reports published
``precision: null`` / ``recall: 0.0`` with a populated per-identity
table, so that scan reported clean.

This module drives the real repo-root script against a scratch git
repo. A leftover uncomputed identification block (not refused, null
precision) is a finding. A numeric identification score is not — the
report does not embed the manifest fields needed to judge honesty.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path


_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[5]
_GUARD_SCRIPT = _REPO_ROOT / "scripts" / "check_published_identification.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location(
        "check_published_identification_under_test", _GUARD_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


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


def _run_guard(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_GUARD_SCRIPT)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def _report(*, ident: dict | None, extra: dict | None = None) -> str:
    payload: dict = {
        "kind": "report",
        "schema": "acx-eval/v1",
        "faces": {},
    }
    if ident is not None:
        payload["faces"]["identification"] = ident
    if extra:
        payload.update(extra)
    return json.dumps(payload)


def test_precision_null_recall_zero_populated_table_is_flagged(tmp_path: Path) -> None:
    """The exact leftover shape the precision-only scan missed (S2R3-08)."""
    repo = _init_repo(tmp_path)
    ident = {
        "precision": None,
        "recall": 0.0,
        "macro_precision": None,
        "macro_recall": 0.0,
        "per_identity": {
            "Caitlin Weaver": {
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
    _track(repo, "docs/tasks/altq/bakeoff-results/run-altq-v1-standard-report.json", _report(ident=ident))
    _commit(repo, "add leftover")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "SCORED" in combined
    assert "run-altq-v1-standard-report.json" in combined
    assert "precision=None" in combined
    assert "recall=0.0" in combined


def test_missing_refused_key_empty_table_is_flagged(tmp_path: Path) -> None:
    """A lazier scan that only looks at a populated table would miss this."""
    repo = _init_repo(tmp_path)
    ident = {
        "precision": None,
        "recall": 0.0,
        "per_identity": {},
    }
    _track(repo, "docs/tasks/vlm/VLM-2B-bakeoff-MiniCPM-V-4.5-report.json", _report(ident=ident))
    _commit(repo, "add empty-table leftover")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "SCORED" in combined
    assert "VLM-2B-bakeoff-MiniCPM-V-4.5-report.json" in combined


def test_refused_false_null_precision_is_flagged(tmp_path: Path) -> None:
    """refused:false is not a refusal. Null precision is the leftover shape."""
    repo = _init_repo(tmp_path)
    ident = {"refused": False, "precision": None, "recall": 0.0, "per_identity": {}}
    _track(repo, "docs/tasks/vlm/scored-report.json", _report(ident=ident))
    _commit(repo, "add refused-false leftover")
    proc = _run_guard(repo)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "SCORED" in proc.stdout + proc.stderr


def test_numeric_identification_score_is_not_flagged(tmp_path: Path) -> None:
    """S2R5-18: a numeric score is not stale; honesty is not in the report."""
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
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "SCORED" not in combined
    assert "ok —" in proc.stdout
    assert "numeric" in proc.stdout


def test_explicit_refusal_is_clean(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ident = {
        "refused": True,
        "invariant": "identification_refuses_unboxed_identity_claims",
        "precision": None,
        "recall": None,
        "per_identity": {},
    }
    _track(repo, "docs/tasks/vlm/VLM-2A-baseline-20260706-report.json", _report(ident=ident))
    _commit(repo, "add refused")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "ok —" in proc.stdout
    assert "SCORED" not in combined


def test_report_without_identification_is_clean(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/tasks/vlm/caption-only-report.json", _report(ident=None))
    _commit(repo, "add caption-only")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "ok —" in proc.stdout


def test_classifier_treats_null_refused_as_scored() -> None:
    """Direct pin: refused is None is not a refusal (the leftover shape)."""
    guard = _load_guard()
    ident = {
        "refused": None,
        "precision": None,
        "recall": 0.0,
        "per_identity": {"Ada": {"precision": None, "recall": 0.0, "tp": 0, "fp": 0, "fn": 1}},
    }
    assert guard.is_refused_identification(ident) is False
    assert guard.is_leftover_uncomputed_identification(ident) is True
    hit = guard.scan_payload("docs/x-report.json", {"faces": {"identification": ident}})
    assert hit is not None
    assert hit.precision is None
    assert hit.recall == 0.0
    assert hit.per_identity_rows == 1


def test_classifier_does_not_flag_numeric_score() -> None:
    """S2R5-18: refused is False + numeric P/R is not leftover."""
    guard = _load_guard()
    ident = {
        "refused": False,
        "precision": 0.5,
        "recall": 0.5,
        "per_identity": {"Ada": {"precision": 0.5, "recall": 0.5, "tp": 1, "fp": 1, "fn": 1}},
    }
    assert guard.is_refused_identification(ident) is False
    assert guard.is_leftover_uncomputed_identification(ident) is False
    assert guard.scan_payload("docs/x-report.json", {"faces": {"identification": ident}}) is None


def test_dated_report_filename_is_scanned(tmp_path: Path) -> None:
    """S0-style ``*-report-YYYYMMDD.json`` must not slip the suffix filter."""
    repo = _init_repo(tmp_path)
    ident = {"precision": None, "recall": 0.0, "per_identity": {"Ada": {}}}
    _track(
        repo,
        "docs/tasks/vlm/bakeoff-results/S0-determinism-anchor-report-20260714.json",
        _report(ident=ident),
    )
    _commit(repo, "add dated leftover")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "SCORED" in combined
    assert "S0-determinism-anchor-report-20260714.json" in combined


def test_no_report_files_is_a_failed_scan(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/README.md", "no reports\n")
    _commit(repo, "docs only")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "no tracked" in combined


def test_precision_only_predicate_would_miss_leftover() -> None:
    """Characterization: the retired filter is exactly why S2R4-14 existed.

    Kept as a pin so a walk-around that restores ``precision is not None``
    cannot satisfy the leftover-shape test by accident. The production
    classifier must not use this predicate.
    """
    leftover = {"precision": None, "recall": 0.0, "per_identity": {"Ada": {}}}
    retired = leftover.get("precision") is not None
    assert retired is False
    guard = _load_guard()
    classifier = inspect.getsource(guard.scan_payload)
    refused_fn = inspect.getsource(guard.is_refused_identification)
    assert "precision is not None" not in classifier
    assert "precision is not None" not in refused_fn
    assert "is_refused_identification" in classifier
