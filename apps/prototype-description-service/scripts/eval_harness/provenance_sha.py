"""Shared HEAD-SHA provenance guard for eval harness producers (fx6 / rg-015).

One implementation of the format + zero-sentinel + git-verify rules so
``describe_baseline.resolve_head_sha`` and ``promote_atomic.validate_live_head_sha``
cannot drift open independently (RV2-04 / RV3-05 / S4-06).

Heuristics: TEST-15, AUDIT-07, EVAL-23, rg-015, sr-007.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

FABRICATED_ZERO_SHA = "0" * 40
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


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
        When True (default for both call sites after fx6), require
        ``git rev-parse --verify <sha>^{commit}`` when git is available **and**
        the cwd is a work tree. Degrades to format-only when git is missing or
        cwd is not a repo (RV3-05). When False, format-only always.
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
    """When git can answer, require a real commit; else format-only (RV3-05)."""
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
    except (OSError, subprocess.SubprocessError):
        # No git binary / spawn failure — format-valid only.
        return sha
    if in_repo.returncode != 0 or (in_repo.stdout or "").strip() != "true":
        # Not a git work tree — format-valid only.
        return sha
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
        raise SystemExit(
            f"{label}={sha!r} git rev-parse --verify failed; refuse to stamp "
            f"fabricated provenance (RV3-05 / S4-06 / rg-015): {exc}"
        ) from exc
    if verified.returncode != 0:
        raise SystemExit(
            f"{label}={sha!r} is not a resolvable commit in this repository "
            f"(git rev-parse --verify failed); pass a real SHA from "
            f"`git rev-parse HEAD` or unset/omit {label} to record null "
            f"(RV3-05 / S4-06 / rg-015)"
        )
    return (verified.stdout or sha).strip().lower()
