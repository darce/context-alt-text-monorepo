"""RV-EVAL-RETIRE-PUB-01/02: refusal publication must not mask the scorer exception.

Causal regressions for the publication path behind score_report._publish_score_refusal.
Each scenario runs healthy score -> refusal -> refusal artifacts -> healthy recovery.

TEST-15, Prove the green can go red (The Pragmatic Programmer, ch. 9): the
surrogate-path and simultaneous-writer scenarios are the RED causal probes for the
current production tree; single-writer, escaping, and recovery controls must stay GREEN.
Production code and existing tests are intentionally left untouched.
"""

from __future__ import annotations

import errno
import json
import re
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from scripts.bench import score_report
from scripts.bench.score_report import score_head_to_head
from scripts.bench.stack_pair import BenchError
from scripts.bench.tests.test_gtmr_refused_rescore import _assert_healthy, _refresh_query
from scripts.bench.tests.test_gtmr_unknown_query import MEDIA_IDS, _run
from scripts.bench.tests.test_score_head_to_head import A_STACK, B_STACK, _pred, _write_leg

STACKS = (A_STACK, B_STACK)
JSON_ARTIFACT = "frames.json"
HTML_ARTIFACT = "report.html"
JSON_MARK = "PUBLICATION-JSON-DIAG-91be"
HTML_MARK = "PUBLICATION-HTML-DIAG-7f3a"
# Distinct OSError causes, each carrying a unique diagnostic token.
WRITER_ERRORS = {
    JSON_ARTIFACT: (errno.ENOSPC, JSON_MARK),
    HTML_ARTIFACT: (errno.EIO, HTML_MARK),
}
# A lone surrogate is a legal Linux file-name byte (0xff) that UTF-8 cannot encode.
SURROGATE_ROOT = "linux-\udcff-run-root"
MANIFEST_CODE = "manifest_sha_mismatch"
QUERY_CODE = "identity_query_unknown"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _frame_names(exc: BaseException) -> list[str]:
    return [frame.name for frame in traceback.extract_tb(exc.__traceback__)]


def _notes(exc: BaseException | None) -> str:
    return "\n".join(getattr(exc, "__notes__", ()))


def _watch_original(monkeypatch: pytest.MonkeyPatch) -> list[tuple[BaseException, list[str]]]:
    """Record the exact scorer exception and its traceback origin at the scorer boundary."""
    real = score_report._score_head_to_head
    captured: list[tuple[BaseException, list[str]]] = []

    def capturing(root: Path) -> Path:
        try:
            return real(root)
        except Exception as exc:
            captured.append((exc, _frame_names(exc)))
            raise

    monkeypatch.setattr(score_report, "_score_head_to_head", capturing)
    return captured


def _attempt_score(run_dir: Path) -> Exception | None:
    try:
        score_head_to_head(run_dir)
    except Exception as exc:  # Keep the escaped exception for assertions.
        return exc
    return None


def _preflights(run_dir: Path) -> dict[str, bytes]:
    return {s: (run_dir / "legs" / s / "preflight.json").read_bytes() for s in STACKS}


def _restore_legs(run_dir: Path, preflights: dict[str, bytes]) -> None:
    for stack in STACKS:
        _write_leg(run_dir, stack, [_pred(mid) for mid in MEDIA_IDS], MEDIA_IDS)
        assert (run_dir / "legs" / stack / "preflight.json").read_bytes() == preflights[stack]


@contextmanager
def _publication_writers(failing: set[str]) -> Iterator[list[str]]:
    """Fail only the named refusal artifacts; record every attempted publication write."""
    real_write_text = Path.write_text
    attempts: list[str] = []

    def write_text(self: Path, data: str, *args: Any, **kwargs: Any) -> int:
        if self.parent.name == "score" and self.name in WRITER_ERRORS:
            attempts.append(self.name)
            if self.name in failing:
                code, marker = WRITER_ERRORS[self.name]
                raise OSError(code, marker)
        return real_write_text(self, data, *args, **kwargs)

    with mock.patch.object(Path, "write_text", write_text):
        yield attempts


def _original_failures(
    failure: Exception | None, captured: list[tuple[BaseException, list[str]]], code: str
) -> list[str]:
    if failure is None:
        return [f"refused run returned success instead of {code}"]
    if len(captured) != 1:
        return [f"scorer exception for {code} was not observed exactly once"]
    original, original_frames = captured[0]
    problems: list[str] = []
    if failure is not original:
        problems.append(
            f"caller received {type(failure).__name__} instead of the original "
            f"{type(original).__name__} identity"
        )
    if not isinstance(original, BenchError) or original.code != code:
        problems.append(f"original scorer exception is not BenchError {code}")
    if failure.__cause__ is not original.__cause__ or failure.__context__ is not original.__context__:
        problems.append("original cause/context chain was replaced")
    if _frame_names(failure)[-len(original_frames):] != original_frames:
        problems.append("original traceback origin was not preserved")
    return problems


def _attempt_failures(attempts: list[str]) -> list[str]:
    if set(attempts) != {JSON_ARTIFACT, HTML_ARTIFACT}:
        return [f"publication did not attempt both writers: {sorted(set(attempts))}"]
    return []


def _json_refusal_failures(path: Path, code: str) -> list[str]:
    if not path.is_file():
        return [f"{path.name} refusal artifact missing"]
    try:
        frames = _json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [f"{path.name} is not a readable JSON refusal header"]
    if frames.get("pr_cells_emitted") is not False or frames.get("cells") != [] or frames.get("error_code") != code:
        return [f"{path.name} retains numerical cells or lacks original refusal code {code}"]
    return []


def _html_refusal_failures(path: Path, code: str, healthy_frames: dict, healthy_html: str) -> list[str]:
    if not path.is_file():
        return [f"{path.name} refusal artifact missing"]
    try:
        html = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [f"{path.name} is not valid UTF-8 refusal output"]
    metric_names = {cell["cell"] for cell in healthy_frames["cells"]}
    numeric_rows = [
        row for row in re.findall(r"<tr\b[^>]*>.*?</tr>", html, re.I | re.S)
        if any(name in row for name in metric_names)
        and re.search(r"<td\b[^>]*>\s*[+-]?\d+(?:\.\d+)?\s*</td>", row, re.I)
    ]
    problems: list[str] = []
    if html == healthy_html or "refus" not in html.lower():
        problems.append(f"{path.name} lacks refusal output")
    if code not in html:
        problems.append(f"{path.name} lacks original refusal code {code}")
    if numeric_rows:
        problems.append(f"{path.name} retains numerical metric rows")
    return problems


def _recovery_failures(run_dir: Path, healthy_frames: dict, healthy_html: str) -> list[str]:
    try:
        recovered_frames, recovered_html = _assert_healthy(run_dir)
    except Exception as exc:  # repr() escapes surrogates, keeping the report printable.
        return [f"healthy recovery failed: {type(exc).__name__}: {exc!r}"]
    problems: list[str] = []
    if recovered_frames["cells"] != healthy_frames["cells"]:
        problems.append("recovered cells differ from the healthy baseline")
    if recovered_html != healthy_html:
        problems.append("recovered report differs from the healthy baseline")
    return problems


def test_surrogate_path_manifest_refusal_preserves_original_and_retires_both_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / SURROGATE_ROOT
    root.mkdir()
    run_dir = _run(root, (), "successful_empty")
    healthy_frames, healthy_html = _assert_healthy(run_dir)
    manifest_path = run_dir / "manifest.json"
    pinned_manifest = manifest_path.read_bytes()
    captured = _watch_original(monkeypatch)

    # Same JSON content, different bytes: the run-dir manifest.sha pin no longer matches.
    manifest_path.write_bytes(pinned_manifest + b"\n")
    try:
        failure = _attempt_score(run_dir)
    finally:
        manifest_path.write_bytes(pinned_manifest)

    score = run_dir / "score"
    failures = _original_failures(failure, captured, MANIFEST_CODE)
    failures += _json_refusal_failures(score / JSON_ARTIFACT, MANIFEST_CODE)
    failures += _html_refusal_failures(score / HTML_ARTIFACT, MANIFEST_CODE, healthy_frames, healthy_html)
    failures += _recovery_failures(run_dir, healthy_frames, healthy_html)
    assert not failures, "; ".join(failures)


def test_simultaneous_publication_writer_failures_retain_both_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _run(tmp_path, (), "successful_empty")
    healthy_frames, healthy_html = _assert_healthy(run_dir)
    preflights = _preflights(run_dir)
    _refresh_query(run_dir, A_STACK, "failed_query")
    captured = _watch_original(monkeypatch)

    with _publication_writers({JSON_ARTIFACT, HTML_ARTIFACT}) as attempts:
        failure = _attempt_score(run_dir)

    failures = _original_failures(failure, captured, QUERY_CODE) + _attempt_failures(attempts)
    for name, (_, marker) in WRITER_ERRORS.items():
        if marker not in _notes(failure):
            failures.append(f"original exception lost the {name} publication diagnostic")
    _restore_legs(run_dir, preflights)
    failures += _recovery_failures(run_dir, healthy_frames, healthy_html)
    assert not failures, "; ".join(failures)


@pytest.mark.parametrize(
    "failing",
    [JSON_ARTIFACT, HTML_ARTIFACT],
    ids=["json_writer_only", "html_writer_only"],
)
def test_single_publication_writer_failure_keeps_its_diagnostic_and_retires_survivor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    run_dir = _run(tmp_path, (), "successful_empty")
    healthy_frames, healthy_html = _assert_healthy(run_dir)
    preflights = _preflights(run_dir)
    _refresh_query(run_dir, A_STACK, "failed_query")
    captured = _watch_original(monkeypatch)

    with _publication_writers({failing}) as attempts:
        failure = _attempt_score(run_dir)

    failures = _original_failures(failure, captured, QUERY_CODE) + _attempt_failures(attempts)
    marker = WRITER_ERRORS[failing][1]
    if marker not in _notes(failure):
        failures.append(f"original exception lost the {failing} publication diagnostic")
    score = run_dir / "score"
    if failing == JSON_ARTIFACT:
        failures += _html_refusal_failures(score / HTML_ARTIFACT, QUERY_CODE, healthy_frames, healthy_html)
    else:
        failures += _json_refusal_failures(score / JSON_ARTIFACT, QUERY_CODE)
    _restore_legs(run_dir, preflights)
    failures += _recovery_failures(run_dir, healthy_frames, healthy_html)
    assert not failures, "; ".join(failures)


def test_refusal_html_escapes_untrusted_run_path_text(tmp_path: Path) -> None:
    root = tmp_path / 'esc <img src=x onerror=1> & "q"'
    root.mkdir()
    run_dir = _run(root, (), "successful_empty")
    healthy_frames, healthy_html = _assert_healthy(run_dir)
    manifest_path = run_dir / "manifest.json"
    pinned_manifest = manifest_path.read_bytes()

    manifest_path.write_bytes(pinned_manifest + b"\n")
    try:
        failure = _attempt_score(run_dir)
    finally:
        manifest_path.write_bytes(pinned_manifest)

    failures: list[str] = []
    if not (isinstance(failure, BenchError) and failure.code == MANIFEST_CODE):
        failures.append(f"refusal did not surface BenchError {MANIFEST_CODE}")
    score = run_dir / "score"
    failures += _json_refusal_failures(score / JSON_ARTIFACT, MANIFEST_CODE)
    failures += _html_refusal_failures(score / HTML_ARTIFACT, MANIFEST_CODE, healthy_frames, healthy_html)
    html_path = score / HTML_ARTIFACT
    html = html_path.read_text(encoding="utf-8") if html_path.is_file() else ""
    # The untrusted path is embedded in the refusal message, so it must be escaped.
    if "&lt;img src=x onerror=1&gt; &amp; &quot;q&quot;" not in html:
        failures.append("refusal HTML does not escape untrusted run-path text")
    if "<img src=x onerror=1>" in html:
        failures.append("refusal HTML emits raw run-path markup")
    failures += _recovery_failures(run_dir, healthy_frames, healthy_html)
    assert not failures, "; ".join(failures)
