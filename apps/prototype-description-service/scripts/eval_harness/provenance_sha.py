"""Shared HEAD-SHA provenance guard for eval harness producers (fx6 / rg-015).

One implementation of the format + zero-sentinel + git-verify rules so
``describe_baseline.resolve_head_sha`` and ``promote_atomic.validate_live_head_sha``
cannot drift open independently (RV2-04 / RV3-05 / S4-06).

Heuristics: TEST-15, AUDIT-07, EVAL-23, rg-015, sr-007, VLM6-R2-D-02.
"""

from __future__ import annotations

import errno
import re
import subprocess
from pathlib import Path

FABRICATED_ZERO_SHA = "0" * 40
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


def _is_missing_git_binary(exc: BaseException) -> bool:
    """True only for a hard missing-git-binary signal (VLM6-R2-D-02).

    FileNotFoundError / errno.ENOENT means the ``git`` executable is absent.
    Timeouts, GIT_DIR fatals, bare repos, and other OSError/SubprocessError
    answers are **not** missing-binary and must not open format-only accept.
    """
    if isinstance(exc, FileNotFoundError):
        return True
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == errno.ENOENT:
        return True
    return False


def _refuse_git_probe(label: str, sha: str, detail: str, *, cause: BaseException | None = None) -> None:
    """Raise SystemExit: git answered unhappily — never silent format-only degrade."""
    msg = (
        f"{label}={sha!r} git provenance probe failed ({detail}); refuse to stamp "
        f"fabricated provenance — pass a real SHA from `git rev-parse HEAD` in a "
        f"normal worktree or unset/omit {label} "
        f"(VLM6-R2-D-02 / RV3-05 / S4-06 / rg-015)"
    )
    if cause is not None:
        raise SystemExit(msg) from cause
    raise SystemExit(msg)


def normalize_head_sha(
    raw: str | None,
    *,
    empty_policy: str = "none",
    verify_git: bool = True,
    git_cwd: Path | str | None = None,
    label: str = "HEAD_SHA",
) -> str | None:
    """Normalise an explicit HEAD SHA or refuse fabrications.

    Parameters
    ----------
    raw:
        Candidate SHA, or ``None`` when the caller omitted the value.
    empty_policy:
        ``\"none\"`` — empty / whitespace after strip returns ``None`` (unset;
        describe_baseline env/module resolution).
        ``\"refuse\"`` — empty / whitespace raises ``SystemExit`` (CLI flag must
        not silently exit pin mode; RV2-05).
    verify_git:
        When True (default), require ``git rev-parse --verify <sha>^{commit}``.
        Degrades to format-only **only** when the git binary is missing
        (``FileNotFoundError`` / ``ENOENT``). Any other git answer — non-zero
        rc, timeout, poisoned ``GIT_DIR``, bare repo, permission errors —
        refuses (VLM6-R2-D-02). When False, format-only always (callers should
        not opt out; CLI always-on via wrappers).
    git_cwd:
        Optional cwd for the git probe (promote generators may pin a worktree).
    label:
        Operator-facing name for the field in error messages.
    """
    if raw is None:
        return None
    sha = str(raw).strip().lower()
    if not sha:
        if empty_policy == "refuse":
            raise SystemExit(
                f"{label} must not be empty; omit the flag (and use --pin) for "
                "byte-stable pin mode, or pass a real 40-char git SHA with --no-pin "
                "(RV2-05 / S4-04)"
            )
        if empty_policy == "none":
            return None
        raise ValueError(f"empty_policy must be 'none' or 'refuse' (got {empty_policy!r})")
    if sha == FABRICATED_ZERO_SHA:
        raise SystemExit(
            f"{label} is the fabricated 40-zero sentinel; pass a real 40-char git "
            "SHA or unset/omit it to record null (S4-06 / RV2-04 / rg-015 / VLM6-F-04)"
        )
    if not _HEX40.fullmatch(sha):
        raise SystemExit(
            f"{label} must be a 40-char lowercase hex git SHA (got {raw!r}); "
            "unset/omit rather than fabricating a value (RV2-04 / S4-06 / RV3-05)"
        )
    if not verify_git:
        return sha
    return _verify_git_commit_or_degrade(sha, git_cwd=git_cwd, label=label)


def _verify_git_commit_or_degrade(
    sha: str,
    *,
    git_cwd: Path | str | None,
    label: str,
) -> str:
    """Require a real commit when git can answer; degrade only if binary missing.

    Both probes share one exception policy (VLM6-R2-D-02): missing binary →
    format-only accept; every other failure → SystemExit refuse.
    """
    cwd = str(git_cwd) if git_cwd is not None else None
    try:
        in_repo = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        if _is_missing_git_binary(exc):
            return sha
        _refuse_git_probe(label, sha, f"is-inside-work-tree: {exc!r}", cause=exc)
        raise  # pragma: no cover — _refuse_git_probe always raises
    if in_repo.returncode != 0 or (in_repo.stdout or "").strip() != "true":
        # Git present but unhappy / bare / not a work tree — refuse (not degrade).
        detail = (in_repo.stderr or in_repo.stdout or "").strip() or f"rc={in_repo.returncode}"
        _refuse_git_probe(
            label,
            sha,
            f"is-inside-work-tree rc={in_repo.returncode} stdout="
            f"{(in_repo.stdout or '').strip()!r}: {detail}",
        )
        raise  # pragma: no cover
    try:
        verified = subprocess.run(
            ["git", "rev-parse", "--verify", f"{sha}^{{commit}}"],
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        if _is_missing_git_binary(exc):
            return sha
        _refuse_git_probe(label, sha, f"rev-parse --verify: {exc!r}", cause=exc)
        raise  # pragma: no cover
    if verified.returncode != 0:
        raise SystemExit(
            f"{label}={sha!r} is not a resolvable commit in this repository "
            f"(git rev-parse --verify failed); pass a real SHA from "
            f"`git rev-parse HEAD` or unset/omit {label} to record null "
            f"(RV3-05 / S4-06 / rg-015)"
        )
    return (verified.stdout or sha).strip().lower()
