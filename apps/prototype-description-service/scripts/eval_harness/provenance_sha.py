"""Shared HEAD-SHA provenance guard for eval harness producers (fx6 / rg-015).

One implementation of the format + zero-sentinel + git-verify rules so
``describe_baseline.resolve_head_sha`` and ``promote_atomic.validate_live_head_sha``
cannot drift open independently (RV2-04 / RV3-05 / S4-06).

Wave E wE2 (refuse-uniform): every unverifiable SHA raises ``SystemExit``.
Missing git, foreign ``GIT_*`` overrides, impostor ``git`` on ``PATH``,
non-hex verify stdout, and ``verify_git=False`` all refuse — never silent
format-only accept (RD-01..06, CDX-02/03, RE-03 / S2-07 / rg-015).

Heuristics: TEST-15, AUDIT-07, EVAL-23, rg-015, sr-007, VLM6-R2-D-02, S2-07.
"""

from __future__ import annotations

import errno
import os
import re
import shutil
import subprocess
from pathlib import Path

FABRICATED_ZERO_SHA = "0" * 40
_HEX40 = re.compile(r"^[0-9a-f]{40}$")

# Repo-retargeting env vars. Inherited values let a foreign repo "verify" a SHA
# that is not in the pinned worktree (RD-03 / CDX-03). Cleared for every probe.
_GIT_REPO_OVERRIDE_ENV = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_INDEX_FILE",
        "GIT_NAMESPACE",
    }
)

# Prefer known system binaries over PATH so an impostor earlier on PATH cannot
# stamp fabricated provenance (RD-04 / CDX-03). Fall back to shutil.which only
# when no system candidate is executable.
_SYSTEM_GIT_CANDIDATES: tuple[str, ...] = (
    "/usr/bin/git",
    "/bin/git",
)


def _is_missing_git_binary(exc: BaseException) -> bool:
    """True only for a hard missing-git-binary signal.

    Retained as a classifier for error messages; missing-binary no longer opens
    a format-only hatch (wE2 refuse-uniform / RD-01).
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
        f"(VLM6-R2-D-02 / RV3-05 / S4-06 / rg-015 / wE2-refuse-uniform)"
    )
    if cause is not None:
        raise SystemExit(msg) from cause
    raise SystemExit(msg)


def _resolve_git_binary() -> str:
    """Absolute path to a real git executable, or raise FileNotFoundError.

    System candidates beat PATH (RD-04). Dangling symlinks and non-files raise
    FileNotFoundError so callers refuse rather than degrade (RD-01).
    """
    for candidate in _SYSTEM_GIT_CANDIDATES:
        path = Path(candidate)
        try:
            if path.is_file() and os.access(path, os.X_OK):
                resolved = path.resolve(strict=True)
                if resolved.is_file() and os.access(resolved, os.X_OK):
                    return str(resolved)
        except (OSError, RuntimeError):
            continue
    found = shutil.which("git")
    if found is None:
        raise FileNotFoundError(errno.ENOENT, "git executable not found on PATH", "git")
    try:
        resolved = Path(found).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise FileNotFoundError(
            errno.ENOENT, "git executable not resolvable", found
        ) from exc
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise FileNotFoundError(
            errno.ENOENT, "git executable not usable", str(resolved)
        )
    return str(resolved)


def _sanitized_subprocess_env() -> dict[str, str]:
    """Copy ``os.environ`` with git repo-override keys removed (RD-03 / CDX-03)."""
    return {k: v for k, v in os.environ.items() if k not in _GIT_REPO_OVERRIDE_ENV}


def _git_cmd(git_bin: str, git_cwd: Path | str | None, *args: str) -> list[str]:
    """Build ``git [-C <abs>] <args>`` — pin the repo explicitly when cwd given."""
    cmd: list[str] = [git_bin]
    if git_cwd is not None:
        cmd.extend(["-C", str(Path(git_cwd).resolve())])
    cmd.extend(args)
    return cmd


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
        Must be True. ``False`` raises ``SystemExit`` — format-only opt-out is
        refused at the library boundary (RD-06 / RE-03 / VLM6-R2-D-03). The
        parameter remains only so wrappers that pass ``verify_git=True`` keep
        working without a cross-lane signature edit.
    git_cwd:
        Optional worktree/repo pin for the git probe (``git -C``). Override env
        vars are scrubbed regardless.
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
        # RD-06 / RE-03: public opt-out is a footgun — refuse, do not format-only.
        raise SystemExit(
            f"{label}: verify_git=False is refused — git verification is mandatory "
            f"for HEAD SHA provenance (RD-06 / RE-03 / VLM6-R2-D-03 / rg-015 / "
            f"wE2-refuse-uniform); remove the opt-out rather than stamping "
            f"unverified hex"
        )
    return _verify_git_commit(sha, git_cwd=git_cwd, label=label)


def _verify_git_commit(
    sha: str,
    *,
    git_cwd: Path | str | None,
    label: str,
) -> str:
    """Require a real commit in the pinned repo; never format-only degrade.

    Both probes share one policy (wE2 refuse-uniform): any failure — missing
    binary, non-zero rc, timeout, poisoned/foreign env, non-hex stdout — raises
    SystemExit. There is no missing-binary hatch (RD-01, RD-02, CDX-02).
    """
    try:
        git_bin = _resolve_git_binary()
    except FileNotFoundError as exc:
        _refuse_git_probe(label, sha, f"git binary missing/unusable: {exc!r}", cause=exc)
        raise  # pragma: no cover — _refuse_git_probe always raises

    env = _sanitized_subprocess_env()

    try:
        in_repo = subprocess.run(
            _git_cmd(git_bin, git_cwd, "rev-parse", "--is-inside-work-tree"),
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        detail = (
            f"is-inside-work-tree missing-binary: {exc!r}"
            if _is_missing_git_binary(exc)
            else f"is-inside-work-tree: {exc!r}"
        )
        _refuse_git_probe(label, sha, detail, cause=exc)
        raise  # pragma: no cover

    if in_repo.returncode != 0 or (in_repo.stdout or "").strip() != "true":
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
            _git_cmd(git_bin, git_cwd, "rev-parse", "--verify", f"{sha}^{{commit}}"),
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        # RD-02 / DIAG-03: after first probe succeeded, never open a missing-binary
        # hatch — second-probe failure always refuses.
        detail = (
            f"rev-parse --verify missing-binary-after-alive: {exc!r}"
            if _is_missing_git_binary(exc)
            else f"rev-parse --verify: {exc!r}"
        )
        _refuse_git_probe(label, sha, detail, cause=exc)
        raise  # pragma: no cover

    if verified.returncode != 0:
        raise SystemExit(
            f"{label}={sha!r} is not a resolvable commit in this repository "
            f"(git rev-parse --verify failed); pass a real SHA from "
            f"`git rev-parse HEAD` or unset/omit {label} to record null "
            f"(RV3-05 / S4-06 / rg-015)"
        )

    out = (verified.stdout or "").strip().lower()
    # RD-05: never trust returncode alone; never fall back to the input candidate.
    if not _HEX40.fullmatch(out):
        raise SystemExit(
            f"{label}={sha!r} git rev-parse --verify returned non-SHA stdout "
            f"{out!r}; refuse to stamp fabricated provenance "
            f"(RD-05 / rg-015 / S2-07 / wE2-refuse-uniform)"
        )
    return out
