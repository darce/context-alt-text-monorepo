"""GTMC-C78INT-02: refusal publication requires an existing run directory."""

from __future__ import annotations

import json
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

    error = _refuse_unchanged(root, monkeypatch)

    assert error.code == "manifest_sha_missing"
    score_dir = root / "score"
    assert set(score_dir.iterdir()) == {score_dir / "frames.json", score_dir / "report.html"}
    frames = json.loads((score_dir / "frames.json").read_text(encoding="utf-8"))
    assert frames == {
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
