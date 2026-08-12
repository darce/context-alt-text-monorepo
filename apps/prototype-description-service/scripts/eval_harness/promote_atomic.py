"""Journaled set-atomic promote for determinism-anchor freezes (S4-02 / rg-002).

Both caption and face generators share this module so durability fixes land once
(HARM-02). Each generator passes a distinct ``PromoteNamespace`` so journals and
stage directories never collide (RV2-03).

Guarantee: after return, or after crash + ``recover_promote``, every named path
is fully old or fully new — never mixed. A crash mid-install may leave a
transient mixed tree until recovery runs.

Crash+recover converges: journal unlink is dir-fsynced before stage removal so
power-loss cannot leave a ghost ``phase=installing`` journal with a missing
stage (VLM6-R2-B-04). Unknown journal phases refuse and preserve evidence
(VLM6-R2-B-03). Legacy pre-namespace journals refuse rather than silent no-op
(VLM6-R2-B-01). Per-namespace exclusive flock serializes promote/recover/scavenge
(VLM6-R2-B-02).

Heuristics: TEST-15, AUDIT-07, EVAL-23, rg-002, rg-006, rg-008, sr-006.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import shutil
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

# Default age for orphan stage scavenging (RV2-07): 1 hour.
DEFAULT_ORPHAN_STAGE_MAX_AGE_SEC = 3600.0

# Pre-namespace-split journal (both generators shared one name). Present → refuse.
LEGACY_PROMOTE_JOURNAL = ".vlm-anchor-promote.journal"

# Allow-listed recovery phases only (VLM6-R2-B-03). Anything else preserves evidence.
_KNOWN_PHASES = frozenset({"staged", "installing"})


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


def _lock_path(dest_dir: Path, ns: PromoteNamespace) -> Path:
    return dest_dir / f".vlm-{ns.generator}-promote.lock"


@contextmanager
def _namespace_lock(dest_dir: Path, ns: PromoteNamespace) -> Iterator[None]:
    """Exclusive per-namespace flock across scavenge + recover + promote + cleanup.

    Held for the full critical section so concurrent promoters cannot overwrite
    each other's journal mid-install, and scavengers cannot rmtree a live stage
    (VLM6-R2-B-02). Heartbeat (pid + wall time) is written while held so
    scavengers that somehow run without the lock can still refuse to delete
    stages newer than the last heartbeat.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = _lock_path(dest_dir, ns)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        payload = f"{os.getpid()}\n{time.time():.6f}\n".encode()
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, payload)
        os.fsync(fd)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _check_legacy_journal(dest_dir: Path) -> None:
    """Refuse silently ignoring a pre-namespace-split promote journal (VLM6-R2-B-01)."""
    legacy = dest_dir / LEGACY_PROMOTE_JOURNAL
    if legacy.is_file():
        raise PromoteError(
            f"legacy promote journal present at {legacy}; refuse to proceed — "
            f"operator must reconcile pre-namespace-split crash state "
            f"(recover under the old layout, then remove the legacy journal). "
            f"Silent ignore of a present promote journal is forbidden (VLM6-R2-B-01)."
        )


def _write_promote_journal(
    dest_dir: Path, ns: PromoteNamespace, payload: dict[str, Any]
) -> None:
    body = dict(payload)
    body["generator"] = ns.generator
    path = _journal_path(dest_dir, ns)
    # Unique tmp name so concurrent writers cannot clobber each other's journal body
    # even if flock is bypassed (VLM6-R2-B-02).
    token = f"{os.getpid():x}-{uuid.uuid4().hex[:12]}"
    tmp = dest_dir / f".{ns.journal_name}.{token}.tmp"
    try:
        tmp.write_text(json.dumps(body, sort_keys=True) + "\n")
        _fsync_path(tmp)
        os.replace(tmp, path)
        _fsync_path(dest_dir)
    finally:
        # If replace succeeded tmp is gone; if write failed, drop the unique tmp.
        if tmp.exists():
            tmp.unlink(missing_ok=True)


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


def _finish_cleanup(dest_dir: Path, journal_path: Path, stage: Path | None) -> None:
    """Clear journal durably, then drop stage (VLM6-R2-B-04).

    Order matters for power-loss safety:
    1. fsync dest (install already durable, or staged abandon left dest alone)
    2. unlink journal
    3. fsync dest dir so journal clear is durable before stage deletion
    4. remove stage

    Reversing 2–4 can leave a ghost ``phase=installing`` journal with no stage,
    which hard-blocks every subsequent ``atomic_promote`` (recover raises).
    """
    _fsync_path(dest_dir)
    journal_path.unlink(missing_ok=True)
    _fsync_path(dest_dir)
    if stage is not None and stage.is_dir():
        for child in stage.iterdir():
            child.unlink(missing_ok=True)
        stage.rmdir()


def _recover_promote_unlocked(dest_dir: Path, ns: PromoteNamespace) -> None:
    """Recover under an already-held namespace lock. See :func:`recover_promote`."""
    _check_legacy_journal(dest_dir)
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
    # Allow-list only exact known phases. Never tear down on unknown/None/typo
    # (VLM6-R2-B-03) — mixed dest must keep recovery evidence.
    if phase not in _KNOWN_PHASES:
        raise PromoteError(
            f"promote journal at {journal_path} has unknown phase={phase!r} "
            f"(allowed={sorted(_KNOWN_PHASES)}); refuse to tear down journal/stage "
            f"(generator={ns.generator!r} dest={dest_dir}); operator must reconcile"
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
        # Install durable; journal clear + stage drop via ordered cleanup below.
    # phase=staged: leave live paths alone → all-old after cleanup.
    _finish_cleanup(dest_dir, journal_path, stage)


def recover_promote(dest_dir: Path, ns: PromoteNamespace) -> None:
    """Finish or abandon an interrupted set-promote so dest is never left mixed.

    Phase ``staged``: no live paths touched → drop stage + journal (all-old).
    Phase ``installing``: stage holds the full durable new set → complete every
    name from stage (all-new). A missing staged artifact in ``installing`` is
    fatal — never tear down journal/stage and never report success (RV2-02).

    Any phase outside ``{"staged", "installing"}`` raises :class:`PromoteError`
    and preserves journal + stage (VLM6-R2-B-03). A present legacy pre-namespace
    journal is refused, never silently ignored (VLM6-R2-B-01).

    Either successful outcome is a consistent set (S4-02). Unparseable journals
    raise :class:`PromoteError` and leave evidence intact (RV2-01).
    """
    if not dest_dir.is_dir():
        return
    with _namespace_lock(dest_dir, ns):
        _recover_promote_unlocked(dest_dir, ns)


def atomic_promote(
    src_dir: Path, dest_dir: Path, names: list[str], ns: PromoteNamespace
) -> None:
    """Promote a named freeze artifact *set* as one unit (rg-002 / VLM6-F-05 / S4-02).

    Per-file ``os.replace`` is atomic, but a bare loop is not: a kill after the
    first replace leaves a new artifact paired with stale siblings.

    *dest_dir* is a shared bakeoff-results tree, so a whole-directory rename of
    the destination is not workable. Instead:

    1. Acquire exclusive per-namespace lock (VLM6-R2-B-02).
    2. Recover any prior interrupted promote (journal) for *this* namespace only.
    3. Stage the complete new set under a unique sibling dir and fsync it.
    4. Journal ``phase=installing`` (durable intent) with ``generator`` stamped.
    5. Install each name from the durable stage via ``os.replace``.
    6. Unlink journal, fsync dest dir, then drop stage (VLM6-R2-B-04).

    Guarantee: after return, or after crash + ``recover_promote`` (automatic on
    the next promote for the same namespace), every named path is fully old or
    fully new — never mixed. A crash mid-install may leave a transient mixed
    tree until recovery runs.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    with _namespace_lock(dest_dir, ns):
        _recover_promote_unlocked(dest_dir, ns)

        token = f"{os.getpid():x}-{id(names):x}-{len(names):x}-{uuid.uuid4().hex[:8]}"
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

            # Ordered cleanup: journal clear durable before stage removal (B-04).
            _finish_cleanup(dest_dir, _journal_path(dest_dir, ns), stage)
        except BaseException:
            # Leave journal + stage for recover_promote; re-raise.
            raise


def _lock_heartbeat_mtime(dest_dir: Path, ns: PromoteNamespace) -> float | None:
    """Best-effort read of lock file mtime / embedded heartbeat for scavenge gates."""
    path = _lock_path(dest_dir, ns)
    if not path.is_file():
        return None
    try:
        text = path.read_text()
        lines = text.strip().splitlines()
        if len(lines) >= 2:
            return float(lines[1])
    except (OSError, ValueError):
        pass
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _scavenge_orphan_stages_unlocked(
    dest_dir: Path,
    ns: PromoteNamespace,
    *,
    max_age_sec: float,
    now: float,
) -> list[str]:
    """Scavenge under an already-held namespace lock."""
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

    # If a legacy journal is present, protect everything — refuse silent reclaim
    # that could destroy the only recovery evidence for a pre-split crash.
    if (dest_dir / LEGACY_PROMOTE_JOURNAL).is_file():
        for p in dest_dir.glob(f"{ns.stage_prefix}*"):
            if p.is_dir():
                protected.add(p.resolve())
        # Also protect legacy stage prefix dirs.
        for p in dest_dir.glob(".vlm-promote-stage-*"):
            if p.is_dir():
                protected.add(p.resolve())

    # Heartbeat gate (VLM6-R2-B-02): never delete stages newer than the last
    # lock heartbeat. Under exclusive flock this is belt-and-suspenders against
    # clock skew / callers that bypass the lock wrapper.
    heartbeat = _lock_heartbeat_mtime(dest_dir, ns)

    reclaimed: list[str] = []
    for path in dest_dir.glob(f"{ns.stage_prefix}*"):
        if not path.is_dir():
            continue
        if path.resolve() in protected:
            continue
        try:
            mtime = path.stat().st_mtime
            age = now - mtime
        except OSError:
            continue
        if age < max_age_sec:
            continue
        # Refuse stages newer than lock heartbeat (live or just-released).
        if heartbeat is not None and mtime > heartbeat:
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

    Runs under the exclusive per-namespace flock so a concurrent promote's live
    stage cannot be reclaimed mid-flight (VLM6-R2-B-02). Stages newer than the
    lock heartbeat are also protected.
    """
    if not dest_dir.is_dir():
        return []
    clock = time.time() if now is None else now
    with _namespace_lock(dest_dir, ns):
        return _scavenge_orphan_stages_unlocked(
            dest_dir, ns, max_age_sec=max_age_sec, now=clock
        )


def validate_live_head_sha(
    raw: str | None,
    *,
    git_cwd: Path | None = None,
) -> str | None:
    """Validate ``--live-head-sha`` (S4-06 / RV2-04 / RV2-05).

    Thin delegating wrapper over ``provenance_sha.normalize_head_sha`` — name
    retained so generators keep importing this symbol.

    - ``None`` → ``None`` (caller omitted the flag)
    - empty / whitespace-only → refuse (RV2-05: do not silently exit pin mode)
    - forty-zero sentinel → refuse (S4-06)
    - must be 40 lowercase hex chars (uppercased input accepted + lowercased)
    - git verify is **always on** with degrade when git is missing / not a repo
      (fx6 reconciliation with ``resolve_head_sha``; RV3-05 / rg-015). Callers
      cannot opt out — the ``verify_git`` parameter was removed (VLM6-R2-B-04 /
      cx3 delegated cleanup for cx4 VLM6-R2-D-03) so fabricated SHAs cannot slip
      through a false flag.
    """
    from scripts.eval_harness.provenance_sha import normalize_head_sha

    return normalize_head_sha(
        raw,
        empty_policy="refuse",
        verify_git=True,
        git_cwd=git_cwd,
        label="--live-head-sha",
    )
