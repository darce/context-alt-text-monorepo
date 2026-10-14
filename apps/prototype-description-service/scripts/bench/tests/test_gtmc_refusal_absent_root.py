"""GTMC-C78INT-02: refusal publication requires an existing run directory."""

from __future__ import annotations

import errno
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts.bench import score_report
from scripts.bench.stack_pair import BenchError
from scripts.bench.tests.test_gtmr_refusal_mkdir import _frames, _watch_frozen


def _watch_publication_io(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Path]]:
    calls: list[tuple[str, Path]] = []
    real_mkdir = Path.mkdir
    real_write_text = Path.write_text

    def mkdir(path: Path, *args: Any, **kwargs: Any) -> None:
        calls.append(("mkdir", path))
        real_mkdir(path, *args, **kwargs)

    def write_text(path: Path, data: str, *args: Any, **kwargs: Any) -> int:
        calls.append(("write_text", path))
        return real_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(Path, "write_text", write_text)
    return calls


def _refuse_unchanged(root: Path, monkeypatch: pytest.MonkeyPatch) -> BenchError:
    captured = _watch_frozen(monkeypatch)
    with pytest.raises(BenchError) as refusal:
        score_report.score_head_to_head(root)
    assert len(captured) == 1
    original = captured[0]
    error = refusal.value
    assert error is original.exc, "original BenchError identity was replaced"
    assert error.code == original.code
    assert str(error) == original.message
    assert error.__cause__ is original.cause, "original cause chain was replaced"
    assert error.__context__ is original.context, "original context chain was replaced"
    assert error.__suppress_context__ == original.suppress_context
    assert _frames(error)[-len(original.frames):] == original.frames, (
        "original traceback origin was replaced"
    )
    return error


@pytest.mark.parametrize("missing_parents", [False, True], ids=["root-only", "nested-parents"])
def test_absent_run_root_never_creates_refusal_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_parents: bool
) -> None:
    root = tmp_path / "run"
    absent = [root]
    if missing_parents:
        root = tmp_path / "missing-parent" / "nested" / "run"
        absent = [root, root.parent, root.parent.parent]
    assert all(not path.exists() for path in absent)
    calls = _watch_publication_io(monkeypatch)

    error = _refuse_unchanged(root, monkeypatch)

    assert error.code == "manifest_sha_missing"
    assert _frames(error)[-1][2] == "_load_manifest_from_run"
    problems = [
        f"absent run root or parent was created by refusal publication: {path}"
        for path in absent
        if path.exists()
    ]
    if calls:
        problems.append(f"refusal publication attempted mkdir/writers for an absent run root: {calls}")
    assert not problems, "\n".join(problems)
    assert not getattr(error, "__notes__", ())
    assert list(tmp_path.iterdir()) == []


def test_regular_file_run_root_never_attempts_refusal_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "run"
    contents = b"regular file run root\x00\xff"
    root.write_bytes(contents)
    calls = _watch_publication_io(monkeypatch)

    error = _refuse_unchanged(root, monkeypatch)

    assert error.code == "manifest_sha_missing"
    assert _frames(error)[-1][2] == "_load_manifest_from_run"
    assert root.is_file() and root.read_bytes() == contents
    assert set(tmp_path.iterdir()) == {root}, "refusal created an artifact beside the file root"
    assert not calls, f"refusal publication attempted mkdir/writers for a regular-file run root: {calls}"
    assert not getattr(error, "__notes__", ())


def test_existing_run_root_still_publishes_both_refusal_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "run"
    root.mkdir()

    monkeypatch.setattr(score_report, "_scorer_revision", lambda: "unknown")
    error = _refuse_unchanged(root, monkeypatch)

    assert error.code == "manifest_sha_missing"
    score_dir = root / "score"
    assert set(score_dir.iterdir()) == {score_dir / "frames.json", score_dir / "report.html"}
    frames = json.loads((score_dir / "frames.json").read_text(encoding="utf-8"))
    # GTMC-I77-GATE1-F2 adds explicit lineage to the exact refusal header.
    assert frames == {
        "run_id": "unknown",
        "manifest_sha": "unknown",
        "scorer_revision": "unknown",
        "error_code": error.code,
        "license_banner": score_report.LICENSE_BANNER,
        "pr_cells_emitted": False,
        "cells": [],
    }
    html = (score_dir / "report.html").read_text(encoding="utf-8")
    assert "Scoring refused" in html and error.code in html
    assert score_report.LICENSE_BANNER in html


@pytest.mark.parametrize("file_root", [False, True], ids=["absent-root", "file-root"])
def test_invalid_run_root_preserves_chained_error_and_existing_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, file_root: bool
) -> None:
    root = tmp_path / "run"
    if file_root:
        root.write_bytes(b"unchanged")

    def refusing(run_dir: Path) -> Path:
        assert run_dir == root
        try:
            raise ValueError("original upstream failure")
        except ValueError as cause:
            error = BenchError("original_refusal", "original scorer failure")
            error.add_note("original scorer diagnostic")
            raise error from cause

    monkeypatch.setattr(score_report, "_score_head_to_head", refusing)
    calls = _watch_publication_io(monkeypatch)

    error = _refuse_unchanged(root, monkeypatch)

    assert error.code == "original_refusal"
    assert isinstance(error.__cause__, ValueError)
    assert error.__cause__ is error.__context__
    assert _frames(error)[-1][2] == "refusing"
    assert not calls, f"refusal publication attempted mkdir/writers for an invalid run root: {calls}"
    assert error.__notes__ == ["original scorer diagnostic"]
    if file_root:
        assert root.read_bytes() == b"unchanged"
    else:
        assert not root.exists()


@pytest.mark.parametrize("kind", ["long-component", "no-search-parent"])
def test_unstatable_root_preserves_original_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """GTMC-C81R-SAR-M1: real stat errors must not replace a scorer refusal."""
    parent = tmp_path / "locked"
    parent.mkdir()
    root = tmp_path / ("x" * 300) if kind == "long-component" else parent / "run"
    if kind == "no-search-parent":
        root.mkdir()
        parent.chmod(0)
    try:
        with pytest.raises(OSError) as stat_error:
            root.stat()
        assert stat_error.value.errno == (errno.ENAMETOOLONG if kind == "long-component" else errno.EACCES)
        original = BenchError("original_refusal", "original scorer failure")

        def refusing(run_dir: Path) -> Path:
            assert run_dir == root
            raise original

        monkeypatch.setattr(score_report, "_score_head_to_head", refusing)
        calls = _watch_publication_io(monkeypatch)
        error = _refuse_unchanged(root, monkeypatch)
        assert error is original
        assert not calls
        assert not getattr(error, "__notes__", ())

        from scripts.bench import cross_stack_bench
        assert cross_stack_bench.main(["score", "--run-dir", os.fspath(root)]) == 2
    finally:
        parent.chmod(0o700)


def test_removed_root_is_not_recreated_after_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GTMC-C81R-SAR-L1: remove root immediately before publication mkdir."""
    root = tmp_path / "run"
    root.mkdir()
    real_mkdir = Path.mkdir

    removed = False

    def remove_before_mkdir(path: Path, *args: Any, **kwargs: Any) -> None:
        nonlocal removed
        if path == root / "score" and not removed:
            root.rmdir()
            removed = True
        real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", remove_before_mkdir)
    error = _refuse_unchanged(root, monkeypatch)
    assert not root.exists(), "refusal mkdir recreated a concurrently removed run root"
    assert len(error.__notes__) == 3


@pytest.mark.parametrize("known", [False, True], ids=["unknown-lineage", "known-lineage"])
def test_refusal_header_records_available_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, known: bool
) -> None:
    """GTMC-I77-GATE1-F2: refusal artifacts explicitly carry provenance."""
    root = tmp_path / "run"
    root.mkdir()
    if known:
        (root / "run.json").write_text(json.dumps({"run_stamp": "recorded-run", "cli_sha": "a" * 40}))
        (root / "manifest.sha").write_text("b" * 64 + "\n")
    monkeypatch.setattr(score_report, "_scorer_revision", lambda: "a" * 40 if known else "unknown")
    _refuse_unchanged(root, monkeypatch)
    header = json.loads((root / "score" / "frames.json").read_text())
    expected = {
        "run_id": "recorded-run" if known else "unknown",
        "manifest_sha": "b" * 64 if known else "unknown",
        "scorer_revision": "a" * 40 if known else "unknown",
    }
    for key, value in expected.items():
        assert header.get(key) == value, f"refusal header missing {key} lineage"
        assert f"<dt>{key}</dt><dd>{value}</dd>" in (root / "score" / "report.html").read_text()


@pytest.mark.parametrize("fault", ["invalid-json", "non-object", "invalid-utf8"])
def test_unreadable_lineage_stays_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    """GTMC-I77-GATE1-F2: damaged provenance never replaces the refusal."""
    root = tmp_path / "run"
    root.mkdir()
    (root / "run.json").write_bytes({
        "invalid-json": b"{", "non-object": b"[]", "invalid-utf8": b"\xff",
    }[fault])
    (root / "manifest.sha").write_bytes(b"\xff")
    monkeypatch.setattr(score_report, "_scorer_revision", lambda: "unknown")
    _refuse_unchanged(root, monkeypatch)
    header = json.loads((root / "score" / "frames.json").read_text())
    assert {key: header[key] for key in ("run_id", "manifest_sha", "scorer_revision")} == {
        "run_id": "unknown", "manifest_sha": "unknown", "scorer_revision": "unknown",
    }


@pytest.mark.parametrize("response", ["known", "empty", "timeout", "not-a-checkout"])
def test_scorer_revision_is_bounded_and_explicit(
    monkeypatch: pytest.MonkeyPatch, response: str
) -> None:
    """GTMC-I77-GATE1-F2: identify the scorer, never borrow a run's old CLI SHA."""
    calls = []

    def git_revision(command: list[str], **kwargs: Any) -> bytes:
        calls.append((command, kwargs))
        if response == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if response == "not-a-checkout":
            raise subprocess.CalledProcessError(128, command)
        return ("c" * 40 + "\n").encode() if response == "known" else b""

    monkeypatch.setattr(score_report.subprocess, "check_output", git_revision)
    assert score_report._scorer_revision() == ("c" * 40 if response == "known" else "unknown")
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == ["git", "log", "-1", "--format=%H", "--", "apps/prototype-description-service/scripts/bench/score_report.py"]
    assert kwargs["timeout"] == 5
    assert kwargs["cwd"] == Path(score_report.__file__).resolve().parents[4]


def test_bench_readme_documents_identity_query_refusal_recovery() -> None:
    repo = Path(__file__).resolve().parents[5]
    readme = (repo / "apps/prototype-description-service/scripts/bench/README.md").read_text(
        encoding="utf-8"
    )
    rows = [line for line in readme.splitlines() if line.startswith("| `identity_query_unknown` |")]
    assert len(rows) == 1, "operator code table must document identity_query_unknown"
    assert "unknown or failed identity-query state" in rows[0]
    assert "repair the leg query evidence before rescoring" in rows[0]


def test_runbook_documents_refusal_artifacts_are_not_success() -> None:
    repo = Path(__file__).resolve().parents[5]
    runbook = (repo / "docs/runbooks/fir-8-cross-stack-bench.md").read_text(encoding="utf-8")
    score_section = runbook.split("## 6. Score", 1)[1].split("\n## ", 1)[0]
    assert "A refused score exits non-zero (BenchError exits 2)" in score_section
    assert "`score/frames.json` and `score/report.html` with refusal artifacts" in score_section
    assert "`pr_cells_emitted` is false" in score_section
    assert "Scoring refused" in score_section
    assert "File existence alone is not scoring success." in score_section


@pytest.mark.parametrize(
    "pin",
    ["not-a-manifest-sha", "a" * 63, "a" * 65, "g" * 64],
    ids=["invalid-ascii", "too-short", "too-long", "non-hex"],
)
def test_readable_invalid_manifest_pin_stays_unknown_in_both_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pin: str
) -> None:
    root = tmp_path / "run"
    root.mkdir()
    (root / "manifest.sha").write_text(pin + "\n", encoding="ascii")
    monkeypatch.setattr(score_report, "_scorer_revision", lambda: "unknown")

    _refuse_unchanged(root, monkeypatch)

    header = json.loads((root / "score" / "frames.json").read_text(encoding="utf-8"))
    html = (root / "score" / "report.html").read_text(encoding="utf-8")
    assert header["manifest_sha"] == "unknown"
    assert "<dt>manifest_sha</dt><dd>unknown</dd>" in html
