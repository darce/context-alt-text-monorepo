"""Review 1306 P2: an existing score-directory mkdir error must not skip refusal publication.

Causal RED for score_report._publish_score_refusal. A healthy scoring run leaves numerical
score/frames.json and score/report.html on disk. A later refusal must still attempt both
refusal writers when only the publication-path score_dir.mkdir raises OSError, and the
caller must receive the original BenchError with identity, code, message, cause, context
and traceback origin frozen at the scorer boundary (before publication runs).

Scope is deliberately narrow: the fault is confined to the publication-path mkdir of the
existing score directory. The scorer's own pre-scoring mkdir, healthy writers and
production code are untouched. The no-fault and single-writer controls must stay GREEN on
the current tree; the two mkdir-fault cases are the RED causal probes.

TEST-15, Prove the green can go red (The Pragmatic Programmer, ch. 9).
"""

from __future__ import annotations

import errno
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from scripts.bench import score_report
from scripts.bench.stack_pair import BenchError
from scripts.bench.tests.test_gtmr_refusal_publication import (
    HTML_ARTIFACT,
    JSON_ARTIFACT,
    WRITER_ERRORS,
    _attempt_failures,
    _attempt_score,
    _html_refusal_failures,
    _json_refusal_failures,
    _notes,
    _preflights,
    _publication_writers,
    _recovery_failures,
    _restore_legs,
)
from scripts.bench.tests.test_gtmr_refused_rescore import _assert_healthy, _refresh_query
from scripts.bench.tests.test_gtmr_unknown_query import _run
from scripts.bench.tests.test_score_head_to_head import A_STACK

MKDIR_MARK = "PUBLICATION-MKDIR-DIAG-6b2d"
# A recoverable OSError from the mkdir of an already-existing score directory.
MKDIR_ERROR = (errno.EIO, MKDIR_MARK)


@dataclass(frozen=True)
class _Refusal:
    code: str
    # Expected type of the original exception's __cause__ (None when the scorer raises bare).
    cause_type: type[BaseException] | None
    arrange: Callable[[Path], Callable[[], None]]


def _arrange_pin_decode(run_dir: Path) -> Callable[[], None]:
    """Early refusal: a non-ASCII byte makes manifest.sha undecodable, before any score mkdir."""
    pin = run_dir / "manifest.sha"
    pinned = pin.read_bytes()
    pin.write_bytes(b"\xff" + pinned)
    return lambda: pin.write_bytes(pinned)


def _arrange_query(run_dir: Path) -> Callable[[], None]:
    """Late refusal: a failed identity query, raised after the scorer's own score mkdir."""
    preflights = _preflights(run_dir)
    _refresh_query(run_dir, A_STACK, "failed_query")
    return lambda: _restore_legs(run_dir, preflights)


REFUSALS: dict[str, _Refusal] = {
    "manifest_pin_decode": _Refusal("manifest_sha_invalid", UnicodeDecodeError, _arrange_pin_decode),
    "query_unknown": _Refusal("identity_query_unknown", None, _arrange_query),
}


@dataclass(frozen=True)
class _Frozen:
    exc: BaseException
    code: str
    message: str
    cause: BaseException | None
    context: BaseException | None
    suppress_context: bool
    frames: tuple[tuple[str, int | None, str], ...]


def _frames(exc: BaseException) -> tuple[tuple[str, int | None, str], ...]:
    return tuple((f.filename, f.lineno, f.name) for f in traceback.extract_tb(exc.__traceback__))


def _freeze(exc: BaseException) -> _Frozen:
    return _Frozen(
        exc=exc,
        code=str(getattr(exc, "code", type(exc).__name__)),
        message=str(exc),
        cause=exc.__cause__,
        context=exc.__context__,
        suppress_context=exc.__suppress_context__,
        frames=_frames(exc),
    )


def _watch_frozen(monkeypatch: pytest.MonkeyPatch) -> list[_Frozen]:
    """Freeze the scorer exception at the scorer boundary, before any publication runs."""
    real = score_report._score_head_to_head
    captured: list[_Frozen] = []

    def capturing(root: Path) -> Path:
        try:
            return real(root)
        except Exception as exc:
            captured.append(_freeze(exc))
            raise

    monkeypatch.setattr(score_report, "_score_head_to_head", capturing)
    return captured


@contextmanager
def _score_dir_mkdir_fault(score_dir: Path, hits: list[str]) -> Iterator[None]:
    """Fail only mkdir of score_dir; every other mkdir call passes through unchanged."""
    real_mkdir = Path.mkdir

    def mkdir(self: Path, *args: Any, **kwargs: Any) -> None:
        if self == score_dir:
            hits.append(self.name)
            raise OSError(*MKDIR_ERROR)
        real_mkdir(self, *args, **kwargs)

    with mock.patch.object(Path, "mkdir", mkdir):
        yield


@dataclass
class _Attempt:
    failure: Exception | None
    frozen: list[_Frozen]
    writer_attempts: list[str]
    mkdir_faults: list[str]


def _refuse(
    run_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    spec: _Refusal,
    *,
    mkdir_fault: bool,
    failing_writers: frozenset[str] = frozenset(),
) -> _Attempt:
    """Arrange one refusal over a healthy run, then score it under the requested faults.

    The mkdir fault is installed only around _publish_score_refusal, so the scorer's own
    pre-scoring mkdir of score/ is never affected.
    """
    frozen = _watch_frozen(monkeypatch)
    restore = spec.arrange(run_dir)
    mkdir_hits: list[str] = []
    real_publish = score_report._publish_score_refusal

    def publish(root: Path, error: Exception) -> None:
        if not mkdir_fault:
            real_publish(root, error)
            return
        with _score_dir_mkdir_fault(root / "score", mkdir_hits):
            real_publish(root, error)

    monkeypatch.setattr(score_report, "_publish_score_refusal", publish)
    try:
        with _publication_writers(set(failing_writers)) as writer_attempts:
            failure = _attempt_score(run_dir)
    finally:
        restore()
    return _Attempt(failure, frozen, list(writer_attempts), mkdir_hits)


def _healthy(tmp_path: Path) -> tuple[Path, dict, str]:
    run_dir = _run(tmp_path, (), "successful_empty")
    healthy_frames, healthy_html = _assert_healthy(run_dir)
    return run_dir, healthy_frames, healthy_html


def _frozen_failures(attempt: _Attempt, spec: _Refusal) -> list[str]:
    if attempt.failure is None:
        return [f"refused run returned success instead of {spec.code}"]
    if len(attempt.frozen) != 1:
        return [f"scorer exception for {spec.code} was not frozen exactly once"]
    failure = attempt.failure
    original = attempt.frozen[0]
    problems: list[str] = []
    if not isinstance(original.exc, BenchError) or original.code != spec.code:
        problems.append(f"frozen scorer exception is not BenchError {spec.code}")
    cause_ok = original.cause is None if spec.cause_type is None else isinstance(original.cause, spec.cause_type)
    if not cause_ok:
        problems.append(
            f"scenario precondition: frozen cause is {type(original.cause).__name__}, "
            f"expected {spec.cause_type.__name__ if spec.cause_type else 'None'}"
        )
    if failure is not original.exc:
        problems.append(f"caller received {type(failure).__name__} instead of the frozen original identity")
    if str(failure) != original.message:
        problems.append("original BenchError message changed during publication")
    if failure.__cause__ is not original.cause:
        problems.append("original cause was replaced during publication")
    if failure.__context__ is not original.context:
        problems.append("original context was replaced during publication")
    if failure.__suppress_context__ != original.suppress_context:
        problems.append("original suppress-context flag changed during publication")
    if _frames(failure)[-len(original.frames) :] != original.frames:
        problems.append("original traceback origin was not preserved")
    return problems


def _artifact_failures(run_dir: Path, code: str, healthy_frames: dict, healthy_html: str) -> list[str]:
    score = run_dir / "score"
    return _json_refusal_failures(score / JSON_ARTIFACT, code) + _html_refusal_failures(
        score / HTML_ARTIFACT, code, healthy_frames, healthy_html
    )


@pytest.mark.parametrize("refusal", sorted(REFUSALS))
def test_control_refusal_without_fault_retires_both_reports_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refusal: str
) -> None:
    spec = REFUSALS[refusal]
    run_dir, healthy_frames, healthy_html = _healthy(tmp_path)
    attempt = _refuse(run_dir, monkeypatch, spec, mkdir_fault=False)

    failures = _frozen_failures(attempt, spec)
    failures += _attempt_failures(attempt.writer_attempts)
    if _notes(attempt.failure):
        failures.append("unfaulted publication attached a publication note")
    failures += _artifact_failures(run_dir, spec.code, healthy_frames, healthy_html)
    failures += _recovery_failures(run_dir, healthy_frames, healthy_html)
    assert not failures, "; ".join(failures)


@pytest.mark.parametrize(
    "failing",
    [JSON_ARTIFACT, HTML_ARTIFACT],
    ids=["json_writer_only", "html_writer_only"],
)
def test_control_single_writer_fault_keeps_its_diagnostic_and_retires_survivor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    spec = REFUSALS["manifest_pin_decode"]
    run_dir, healthy_frames, healthy_html = _healthy(tmp_path)
    attempt = _refuse(run_dir, monkeypatch, spec, mkdir_fault=False, failing_writers=frozenset({failing}))

    failures = _frozen_failures(attempt, spec)
    failures += _attempt_failures(attempt.writer_attempts)
    marker = WRITER_ERRORS[failing][1]
    if marker not in _notes(attempt.failure):
        failures.append(f"original exception lost the {failing} publication diagnostic")
    score = run_dir / "score"
    if failing == JSON_ARTIFACT:
        failures += _html_refusal_failures(score / HTML_ARTIFACT, spec.code, healthy_frames, healthy_html)
    else:
        failures += _json_refusal_failures(score / JSON_ARTIFACT, spec.code)
    failures += _recovery_failures(run_dir, healthy_frames, healthy_html)
    assert not failures, "; ".join(failures)


@pytest.mark.parametrize("refusal", sorted(REFUSALS))
def test_score_dir_mkdir_fault_still_attempts_both_writers_and_retires_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refusal: str
) -> None:
    spec = REFUSALS[refusal]
    run_dir, healthy_frames, healthy_html = _healthy(tmp_path)
    attempt = _refuse(run_dir, monkeypatch, spec, mkdir_fault=True)

    failures = _frozen_failures(attempt, spec)
    if attempt.mkdir_faults != ["score"]:
        failures.append(
            f"injected score-dir mkdir fault fired {attempt.mkdir_faults!r}; expected exactly once for score"
        )
    failures += _attempt_failures(attempt.writer_attempts)
    if MKDIR_MARK not in _notes(attempt.failure):
        failures.append("original exception lost the score-dir mkdir publication diagnostic")
    failures += _artifact_failures(run_dir, spec.code, healthy_frames, healthy_html)
    failures += _recovery_failures(run_dir, healthy_frames, healthy_html)
    assert not failures, "; ".join(failures)
