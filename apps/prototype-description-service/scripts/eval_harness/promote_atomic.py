"""Journaled set-atomic promote for determinism-anchor freezes (S4-02 / rg-002).

Both caption and face generators share this module so durability fixes land once
(HARM-02). Each generator passes a distinct ``PromoteNamespace`` so journals and
stage directories never collide (RV2-03).

Guarantee: after return, or after crash + ``recover_promote``, every named path
is fully old or fully new — never mixed. A crash mid-install may leave a
transient mixed tree until recovery runs.

Heuristics: TEST-15, AUDIT-07, EVAL-23, rg-002, rg-006, rg-008, sr-006.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FABRICATED_ZERO_SHA = "0" * 40
_HEX40 = re.compile(r"^[0-9a-f]{40}$")

# Default age for orphan stage scavenging (RV2-07): 1 hour.
DEFAULT_ORPHAN_STAGE_MAX_AGE_SEC = 3600.0


@dataclass(frozen=True, slots=True)
class PromoteNamespace:
    """Per-generator journal/stage identity so concurrent promotes cannot cross-recover."""

    generator: str
    journal_name: str
    stage_prefix: str


# Distinct namespaces — never share journal filename or stage prefix (RV2-03).
CAPTION_PROMOTE = PromoteNamespace(
    generator="caption",
    journal_name=".vlm-caption-anchor-promote.journal",
    stage_prefix=".vlm-caption-promote-stage-",
)
FACE_PROMOTE = PromoteNamespace(
    generator="face",
    journal_name=".vlm-face-anchor-promote.journal",
    stage_prefix=".vlm-face-promote-stage-",
)


class PromoteError(RuntimeError):
    """Fatal promote/recover failure; journal + stage left for operator reconciliation."""


def _fsync_path(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _journal_path(dest_dir: Path, ns: PromoteNamespace) -> Path:
    return dest_dir / ns.journal_name


def _write_promote_journal(
    dest_dir: Path, ns: PromoteNamespace, payload: dict[str, Any]
) -> None:
    body = dict(payload)
    body["generator"] = ns.generator
    path = _journal_path(dest_dir, ns)
    tmp = dest_dir / f".{ns.journal_name}.tmp"
    tmp.write_text(json.dumps(body, sort_keys=True) + "\n")
    _fsync_path(tmp)
    os.replace(tmp, path)
    _fsync_path(dest_dir)


def _load_journal(journal_path: Path, *, dest_dir: Path, ns: PromoteNamespace) -> dict[str, Any]:
    """Parse journal or refuse. Never unlink unparseable evidence (RV2-01)."""
    try:
        raw = journal_path.read_text()
        journal = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise PromoteError(
            f"unparseable promote journal at {journal_path} for generator={ns.generator!r} "
            f"dest={dest_dir}; refuse to proceed — reconcile by hand (do not delete evidence). "
            f"parse_error={exc}"
        ) from exc
    if not isinstance(journal, dict):
        raise PromoteError(
            f"promote journal at {journal_path} is not a JSON object "
            f"(generator={ns.generator!r} dest={dest_dir}); refuse to proceed"
        )
    declared = journal.get("generator")
    if declared is not None and declared != ns.generator:
        raise PromoteError(
            f"promote journal generator mismatch: journal declares {declared!r} but caller is "
            f"{ns.generator!r} (path={journal_path} dest={dest_dir}); refuse to act on foreign journal"
        )
    if declared is None:
        raise PromoteError(
            f"promote journal at {journal_path} missing required 'generator' field "
            f"(caller={ns.generator!r} dest={dest_dir}); refuse to proceed"
        )
    return journal


def recover_promote(dest_dir: Path, ns: PromoteNamespace) -> None:
    """Finish or abandon an interrupted set-promote so dest is never left mixed.

    Phase ``staged``: no live paths touched → drop stage + journal (all-old).
    Phase ``installing``: stage holds the full durable new set → complete every
    name from stage (all-new). A missing staged artifact in ``installing`` is
    fatal — never tear down journal/stage and never report success (RV2-02).

    Either successful outcome is a consistent set (S4-02). Unparseable journals
    raise :class:`PromoteError` and leave evidence intact (RV2-01).
    """
    journal_path = _journal_path(dest_dir, ns)
    if not journal_path.is_file():
        return
    journal = _load_journal(journal_path, dest_dir=dest_dir, ns=ns)
    names = list(journal.get("names") or [])
    stage = Path(journal["stage"]) if journal.get("stage") else None
    phase = journal.get("phase")
    if stage is None or not names:
        # Incomplete journal metadata — leave evidence, refuse silent success.
        raise PromoteError(
            f"promote journal at {journal_path} missing stage/names "
            f"(generator={ns.generator!r} dest={dest_dir}); refuse to proceed"
        )
    if phase == "installing":
        if not stage.is_dir():
            raise PromoteError(
                f"phase=installing but stage dir missing: {stage} "
                f"(generator={ns.generator!r} dest={dest_dir}); refuse to tear down journal"
            )
        missing = [name for name in names if not (stage / name).is_file()]
        if missing:
            raise PromoteError(
                f"phase=installing incomplete stage at {stage}: missing {missing!r} "
                f"(generator={ns.generator!r} dest={dest_dir}); refuse to leave dest mixed "
                f"or delete evidence"
            )
        for name in names:
            src = stage / name
            dest = dest_dir / name
            tmp = dest_dir / f".{name}.promoting"
            tmp.write_bytes(src.read_bytes())
            _fsync_path(tmp)
            os.replace(tmp, dest)
        _fsync_path(dest_dir)
    # staged (or installing after full install): leave live paths alone when staged → all-old
    if stage.is_dir():
        for child in stage.iterdir():
            child.unlink(missing_ok=True)
        stage.rmdir()
    journal_path.unlink(missing_ok=True)


def atomic_promote(
    src_dir: Path, dest_dir: Path, names: list[str], ns: PromoteNamespace
) -> None:
    """Promote a named freeze artifact *set* as one unit (rg-002 / VLM6-F-05 / S4-02).

    Per-file ``os.replace`` is atomic, but a bare loop is not: a kill after the
    first replace leaves a new artifact paired with stale siblings.

    *dest_dir* is a shared bakeoff-results tree, so a whole-directory rename of
    the destination is not workable. Instead:

    1. Recover any prior interrupted promote (journal) for *this* namespace only.
    2. Stage the complete new set under a unique sibling dir and fsync it.
    3. Journal ``phase=installing`` (durable intent) with ``generator`` stamped.
    4. Install each name from the durable stage via ``os.replace``.
    5. Drop journal + stage.

    Guarantee: after return, or after crash + ``recover_promote`` (automatic on
    the next promote for the same namespace), every named path is fully old or
    fully new — never mixed. A crash mid-install may leave a transient mixed
    tree until recovery runs.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    recover_promote(dest_dir, ns)

    token = f"{os.getpid():x}-{id(names):x}-{len(names):x}"
    stage = dest_dir / f"{ns.stage_prefix}{token}"
    n = 0
    while stage.exists():
        n += 1
        stage = dest_dir / f"{ns.stage_prefix}{token}-{n}"
    stage.mkdir()
    try:
        for name in names:
            target = stage / name
            target.write_bytes((src_dir / name).read_bytes())
            _fsync_path(target)
        _fsync_path(stage)

        _write_promote_journal(
            dest_dir,
            ns,
            {"stage": str(stage), "names": list(names), "phase": "staged"},
        )
        _write_promote_journal(
            dest_dir,
            ns,
            {"stage": str(stage), "names": list(names), "phase": "installing"},
        )

        for name in names:
            dest = dest_dir / name
            tmp = dest_dir / f".{name}.promoting"
            tmp.write_bytes((stage / name).read_bytes())
            _fsync_path(tmp)
            os.replace(tmp, dest)
        _fsync_path(dest_dir)

        _journal_path(dest_dir, ns).unlink(missing_ok=True)
        for child in stage.iterdir():
            child.unlink(missing_ok=True)
        stage.rmdir()
    except BaseException:
        # Leave journal + stage for recover_promote; re-raise.
        raise


def scavenge_orphan_stages(
    dest_dir: Path,
    ns: PromoteNamespace,
    *,
    max_age_sec: float = DEFAULT_ORPHAN_STAGE_MAX_AGE_SEC,
    now: float | None = None,
) -> list[str]:
    """Remove stage dirs older than *max_age_sec* that have no matching journal (RV2-07).

    Stage dirs that a journal still references (or any stage when the journal is
    unparseable) are left alone — those are recoverable state.
    """
    if not dest_dir.is_dir():
        return []
    clock = time.time() if now is None else now
    journal_path = _journal_path(dest_dir, ns)
    protected: set[Path] = set()
    if journal_path.is_file():
        try:
            journal = json.loads(journal_path.read_text())
            if isinstance(journal, dict) and journal.get("stage"):
                protected.add(Path(journal["stage"]).resolve())
            else:
                # Unknown shape: protect all stages for this namespace.
                for p in dest_dir.glob(f"{ns.stage_prefix}*"):
                    if p.is_dir():
                        protected.add(p.resolve())
        except (OSError, json.JSONDecodeError):
            # Corrupt journal: never scavenge — operator must reconcile (RV2-01).
            for p in dest_dir.glob(f"{ns.stage_prefix}*"):
                if p.is_dir():
                    protected.add(p.resolve())

    reclaimed: list[str] = []
    for path in dest_dir.glob(f"{ns.stage_prefix}*"):
        if not path.is_dir():
            continue
        if path.resolve() in protected:
            continue
        try:
            age = clock - path.stat().st_mtime
        except OSError:
            continue
        if age < max_age_sec:
            continue
        try:
            shutil.rmtree(path)
            reclaimed.append(str(path))
            logger.info(
                "scavenged orphan promote stage dir age=%.0fs generator=%s path=%s",
                age,
                ns.generator,
                path,
            )
        except OSError as exc:
            logger.warning("failed to scavenge orphan stage %s: %s", path, exc)
    return reclaimed


def validate_live_head_sha(
    raw: str | None,
    *,
    verify_git: bool = False,
    git_cwd: Path | None = None,
) -> str | None:
    """Validate ``--live-head-sha`` (S4-06 / RV2-04 / RV2-05).

    Mirrors ``describe_baseline.resolve_head_sha`` format rules (local copy —
    lane fx4 owns describe_baseline; cross-lane de-dupe requested in report):

    - ``None`` → ``None`` (caller omitted the flag)
    - empty / whitespace-only → refuse (RV2-05: do not silently exit pin mode)
    - forty-zero sentinel → refuse (S4-06)
    - must be 40 lowercase hex chars
    - optional ``git rev-parse --verify <sha>^{commit}`` when *verify_git*
    """
    if raw is None:
        return None
    sha = str(raw).strip().lower()
    if not sha:
        raise SystemExit(
            "--live-head-sha must not be empty; omit the flag (and use --pin) for "
            "byte-stable pin mode, or pass a real 40-char git SHA with --no-pin "
            "(RV2-05 / S4-04)"
        )
    if sha == _FABRICATED_ZERO_SHA:
        raise SystemExit(
            "--live-head-sha is the fabricated 40-zero sentinel; pass a real 40-char "
            "git SHA or omit the flag for pin mode (S4-06 / RV2-04 / rg-015 / VLM6-F-04)"
        )
    if not _HEX40.fullmatch(sha):
        raise SystemExit(
            f"--live-head-sha must be a 40-char lowercase hex git SHA (got {raw!r}); "
            "omit the flag for pin mode rather than fabricating a value (RV2-04 / S4-06)"
        )
    if verify_git:
        cwd = str(git_cwd) if git_cwd is not None else None
        try:
            subprocess.check_output(
                ["git", "rev-parse", "--verify", f"{sha}^{{commit}}"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
                cwd=cwd,
            )
        except (subprocess.SubprocessError, OSError, FileNotFoundError) as exc:
            raise SystemExit(
                f"--live-head-sha {sha} does not resolve as a git commit "
                f"(git rev-parse --verify failed); refuse to stamp fabricated provenance "
                f"(RV2-04 / S4-06): {exc}"
            ) from exc
    return sha
