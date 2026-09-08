"""Permanent regression for S4-02 journaled set-atomic promote (gx4 + fx2 + cx3).

Pre-fix bare per-file ``os.replace`` loops left a mixed destination after a
mid-promote crash (some files NEW, some OLD). Journaled promote +
``recover_promote`` guarantees the named set is fully old or fully new after
return or after crash + recover (never mixed).

fx2 closed three recovery durability holes (RV2-01/02/03), de-duplicated the
protocol (HARM-02), and added mid-flight journal observation (RV3-03) plus face
crash coverage (RV3-02).

cx3 Wave C: unknown-phase refuse (B-03), legacy journal refuse (B-01),
per-namespace flock + unique journal tmp (B-02), journal-clear dir-fsync (B-04),
and a non-tautology bare-loop mutant against the real mid-flight spy (E-01).

Heuristics: TEST-15, AUDIT-07, EVAL-23, rg-002, rg-006, rg-008, sr-001.
"""

from __future__ import annotations

import inspect
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from scripts.eval_harness import generate_determinism_anchor as cap
from scripts.eval_harness import generate_face_determinism_anchor as face
from scripts.eval_harness import promote_atomic as promote
from scripts.eval_harness.promote_atomic import (
    CAPTION_PROMOTE,
    FACE_PROMOTE,
    LEGACY_PROMOTE_JOURNAL,
    PromoteError,
    atomic_promote,
    recover_promote,
    scavenge_orphan_stages,
    validate_live_head_sha,
)


_NAMES = ("man.json", "run.json", "rep.json")


def _seed_old(dest: Path) -> dict[str, str]:
    dest.mkdir(parents=True, exist_ok=True)
    contents: dict[str, str] = {}
    for name in _NAMES:
        body = f"OLD_{name}"
        (dest / name).write_text(body)
        contents[name] = body
    return contents


def _seed_new(src: Path) -> dict[str, str]:
    src.mkdir(parents=True, exist_ok=True)
    contents: dict[str, str] = {}
    for name in _NAMES:
        body = f"NEW_{name}"
        (src / name).write_text(body)
        contents[name] = body
    return contents


def _read_named(dest: Path, names: tuple[str, ...] = _NAMES) -> dict[str, str]:
    return {name: (dest / name).read_text() for name in names if (dest / name).is_file()}


def _is_all_new(state: dict[str, str], new: dict[str, str]) -> bool:
    return all(state.get(n) == new[n] for n in new)


def _is_all_old(state: dict[str, str], old: dict[str, str]) -> bool:
    return all(state.get(n) == old[n] for n in old)


def _is_mixed(state: dict[str, str], old: dict[str, str], new: dict[str, str]) -> bool:
    has_old = any(state.get(n) == old[n] for n in old)
    has_new = any(state.get(n) == new[n] for n in new)
    return has_old and has_new


def _naive_per_file_promote(src: Path, dest: Path, names: list[str], *, kill_after: int) -> None:
    """Pre-S4-02 bare loop: crash mid-replace leaves mixed dest permanently."""
    replaced = 0
    for name in names:
        os.replace(src / name, dest / name)
        replaced += 1
        if replaced >= kill_after:
            raise KeyboardInterrupt(f"kill after replace #{replaced}")


def _write_journal(dest: Path, ns: promote.PromoteNamespace, payload: dict) -> None:
    body = dict(payload)
    body.setdefault("generator", ns.generator)
    (dest / ns.journal_name).write_text(json.dumps(body, sort_keys=True) + "\n")


def test_naive_per_file_replace_is_mixed_documents_why_journaling_is_needed(
    tmp_path: Path,
) -> None:
    """Pins the MOTIVATING FAILURE MODE, not production behaviour.

    Real S4-02 guards: test_s4_02_crash_mid_install_recover_yields_all_new,
    test_s4_02_crash_before_install_recover_yields_all_old,
    test_s4_02_hand_built_installing_journal_recover_all_new,
    test_s4_02_clean_promote_leaves_no_journal,
    test_s4_02_face_twin_recover_installing_all_new.
    A bare per-file os.replace loop leaves dest mixed after a mid-loop crash;
    this documents why journaled promote is required.
    """
    dest = tmp_path / "dest"
    src = tmp_path / "src"
    old = _seed_old(dest)
    new = _seed_new(src)
    with pytest.raises(KeyboardInterrupt, match="kill after replace"):
        _naive_per_file_promote(src, dest, list(_NAMES), kill_after=1)
    state = _read_named(dest)
    assert _is_mixed(state, old, new), f"RED expects mixed after bare-loop crash: {state}"
    assert not _is_all_new(state, new)
    assert not _is_all_old(state, old)


def test_harm02_caption_and_face_share_promote_impl() -> None:
    """Structural share assert: both generators resolve to the same core functions."""
    assert cap._atomic_promote_core is face._atomic_promote_core
    assert cap._recover_promote_core is face._recover_promote_core
    assert cap._atomic_promote_core is atomic_promote
    assert face._recover_promote_core is recover_promote
    # Namespaces must differ (RV2-03).
    assert cap._PROMOTE_JOURNAL != face._PROMOTE_JOURNAL
    assert cap._PROMOTE_STAGE_PREFIX != face._PROMOTE_STAGE_PREFIX
    assert CAPTION_PROMOTE.generator != FACE_PROMOTE.generator


@pytest.mark.parametrize(
    "mod,ns",
    [
        (cap, CAPTION_PROMOTE),
        (face, FACE_PROMOTE),
    ],
    ids=["caption", "face"],
)
def test_s4_02_crash_mid_install_recover_yields_all_new(tmp_path: Path, mod, ns) -> None:
    """Crash after first install replace; recovery must converge to all-new.

    Parametrized over caption + face wrappers so a bare-loop mutant on either
    path goes red (RV3-02). Shared core is asserted separately (HARM-02).
    """
    dest = tmp_path / "dest"
    src = tmp_path / "src"
    old = _seed_old(dest)
    new = _seed_new(src)

    real_replace = os.replace
    calls = {"n": 0}

    def killing_replace(a, b):
        # Journal writes also use os.replace; only count installs of named artifacts.
        dest_name = Path(b).name
        if dest_name in _NAMES:
            calls["n"] += 1
            real_replace(a, b)
            if calls["n"] >= 1:
                raise KeyboardInterrupt(f"kill after artifact replace #{calls['n']}")
        else:
            real_replace(a, b)

    with pytest.raises(KeyboardInterrupt, match="kill after artifact replace"):
        with pytest.MonkeyPatch.context() as mp:
            # Patch at the shared module — both generators install via it.
            mp.setattr(promote.os, "replace", killing_replace)
            mod._atomic_promote(src, dest, list(_NAMES))

    mid = _read_named(dest)
    # Transient mixed is allowed until recover (documented by gx4).
    assert _is_mixed(mid, old, new) or _is_all_new(mid, new), mid

    mod._recover_promote(dest)
    after = _read_named(dest)
    assert _is_all_new(after, new), f"recovery must yield all-new, got {after}"
    assert not _is_mixed(after, old, new)
    assert not (dest / ns.journal_name).exists()
    assert not any(dest.glob(f"{ns.stage_prefix}*"))


def test_s4_02_crash_before_install_recover_yields_all_old(tmp_path: Path) -> None:
    """Phase=staged only: recovery abandons stage and leaves all-old."""
    dest = tmp_path / "dest"
    old = _seed_old(dest)
    stage = dest / f"{cap._PROMOTE_STAGE_PREFIX}test-staged"
    stage.mkdir()
    for name in _NAMES:
        (stage / name).write_text(f"NEW_{name}")
    _write_journal(
        dest,
        CAPTION_PROMOTE,
        {"stage": str(stage), "names": list(_NAMES), "phase": "staged"},
    )

    cap._recover_promote(dest)
    after = _read_named(dest)
    assert _is_all_old(after, old), f"staged-only recover must leave all-old, got {after}"
    assert not _is_mixed(after, old, {n: f"NEW_{n}" for n in _NAMES})
    assert not (dest / cap._PROMOTE_JOURNAL).exists()
    assert not stage.exists()


def test_s4_02_hand_built_installing_journal_recover_all_new(tmp_path: Path) -> None:
    """Drive _recover_promote against a hand-built mid-install state → all-new."""
    dest = tmp_path / "dest"
    old = _seed_old(dest)
    # Simulate crash after first replace: one NEW, two OLD still live.
    (dest / "man.json").write_text("NEW_man.json")
    stage = dest / f"{cap._PROMOTE_STAGE_PREFIX}hand-built"
    stage.mkdir()
    new = {name: f"NEW_{name}" for name in _NAMES}
    for name, body in new.items():
        (stage / name).write_text(body)
    _write_journal(
        dest,
        CAPTION_PROMOTE,
        {"stage": str(stage), "names": list(_NAMES), "phase": "installing"},
    )
    mid = _read_named(dest)
    assert _is_mixed(mid, old, new), mid

    cap._recover_promote(dest)
    after = _read_named(dest)
    assert _is_all_new(after, new), after
    assert not _is_mixed(after, old, new)
    assert not (dest / cap._PROMOTE_JOURNAL).exists()


def test_s4_02_clean_promote_leaves_no_journal(tmp_path: Path) -> None:
    """Clean promote succeeds AND journals mid-flight (RV3-03).

    Post-state alone is satisfied by a bare replace loop; spy on journal writes
    so dropping journaling from the happy path goes red.
    """
    dest = tmp_path / "dest"
    src = tmp_path / "src"
    old = _seed_old(dest)
    new = _seed_new(src)

    phases_seen: list[str] = []
    real_write = promote._write_promote_journal

    def spy_write(dest_dir, ns, payload):
        phases_seen.append(str(payload.get("phase")))
        # Journal file must exist on disk mid-flight after the write.
        real_write(dest_dir, ns, payload)
        jpath = dest_dir / ns.journal_name
        assert jpath.is_file(), "journal must be durable mid-flight (RV3-03)"
        body = json.loads(jpath.read_text())
        assert body.get("generator") == ns.generator
        assert body.get("phase") in {"staged", "installing"}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(promote, "_write_promote_journal", spy_write)
        cap._atomic_promote(src, dest, list(_NAMES))

    after = _read_named(dest)
    assert _is_all_new(after, new), after
    assert not _is_all_old(after, old)
    assert not (dest / cap._PROMOTE_JOURNAL).exists()
    assert not any(dest.glob(f"{cap._PROMOTE_STAGE_PREFIX}*"))
    assert not any(dest.glob(".*.promoting"))
    # Mid-flight evidence: both phase transitions must have been journaled.
    assert "staged" in phases_seen, f"journal must record phase=staged mid-flight; saw {phases_seen}"
    assert "installing" in phases_seen, (
        f"journal must record phase=installing mid-flight; saw {phases_seen}"
    )


def _observe_midflight_journal_phases(
    promote_fn, src: Path, dest: Path, names: list[str]
) -> list[str]:
    """Shared RV3-03 spy used by clean-promote and bare-mutant tests.

    Replaces ``_write_promote_journal`` with a spy that asserts the journal is
    durable on disk after each write, then invokes *promote_fn*. Returns the
    list of phases observed. A bare ``os.replace`` loop never calls the writer,
    so the caller sees ``[]`` and the post-condition asserts go red.
    """
    phases_seen: list[str] = []
    real_write = promote._write_promote_journal

    def spy_write(dest_dir, ns, payload):
        phases_seen.append(str(payload.get("phase")))
        real_write(dest_dir, ns, payload)
        jpath = dest_dir / ns.journal_name
        assert jpath.is_file(), "journal must be durable mid-flight (RV3-03)"
        body = json.loads(jpath.read_text())
        assert body.get("generator") == ns.generator
        assert body.get("phase") in {"staged", "installing"}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(promote, "_write_promote_journal", spy_write)
        promote_fn(src, dest, names)
    return phases_seen


def test_rv3_03_bare_loop_mutant_fails_midflight_spy(tmp_path: Path) -> None:
    """Bare os.replace mutant must fail the *real* mid-flight journal spy (E-01).

    Prior version asserted on a local ``phases_seen`` list that production never
    touches — always green under any mutant. Drive the same spy observations as
    ``test_s4_02_clean_promote_leaves_no_journal`` against a deliberately bare
    promote and require the post-condition to fail (TEST-15).
    """
    dest = tmp_path / "dest"
    src = tmp_path / "src"
    _seed_old(dest)
    _seed_new(src)

    def bare_loop(src_dir, dest_dir, names, ns=None):
        for name in names:
            os.replace(src_dir / name, dest_dir / name)

    phases_seen = _observe_midflight_journal_phases(
        bare_loop, src, dest, list(_NAMES)
    )
    with pytest.raises(AssertionError, match="journal must"):
        assert "staged" in phases_seen, (
            f"journal must record phase=staged mid-flight; saw {phases_seen}"
        )
    with pytest.raises(AssertionError, match="journal must"):
        assert "installing" in phases_seen, (
            f"journal must record phase=installing mid-flight; saw {phases_seen}"
        )
    assert phases_seen == [], "bare mutant must never touch the journal writer"


def test_rv2_01_corrupt_journal_refuses_and_preserves_evidence(tmp_path: Path) -> None:
    """Unparseable journal must raise and never unlink evidence (RV2-01)."""
    dest = tmp_path / "dest"
    dest.mkdir()
    old = _seed_old(dest)
    journal_path = dest / cap._PROMOTE_JOURNAL
    journal_path.write_text("{not-json truncated")
    with pytest.raises(PromoteError, match="unparseable promote journal"):
        cap._recover_promote(dest)
    assert journal_path.is_file(), "must not delete corrupt journal evidence"
    assert journal_path.read_text() == "{not-json truncated"
    # Dest untouched.
    assert _is_all_old(_read_named(dest), old)


def test_rv2_02_incomplete_stage_installing_is_fatal(tmp_path: Path) -> None:
    """phase=installing with a missing staged artifact must abort (RV2-02)."""
    dest = tmp_path / "dest"
    old = _seed_old(dest)
    (dest / "man.json").write_text("NEW_man.json")  # partial install
    stage = dest / f"{cap._PROMOTE_STAGE_PREFIX}incomplete"
    stage.mkdir()
    # Only two of three artifacts in stage — third missing.
    (stage / "man.json").write_text("NEW_man.json")
    (stage / "run.json").write_text("NEW_run.json")
    # rep.json deliberately absent
    _write_journal(
        dest,
        CAPTION_PROMOTE,
        {"stage": str(stage), "names": list(_NAMES), "phase": "installing"},
    )
    with pytest.raises(PromoteError, match="incomplete stage") as excinfo:
        cap._recover_promote(dest)
    assert "rep.json" in str(excinfo.value)
    # Evidence preserved.
    assert (dest / cap._PROMOTE_JOURNAL).is_file()
    assert stage.is_dir()
    # Dest still mixed — recovery correctly refused to tear down.
    assert _is_mixed(_read_named(dest), old, {n: f"NEW_{n}" for n in _NAMES})


def test_rv2_03_foreign_generator_journal_refused(tmp_path: Path) -> None:
    """Caption recover must refuse a face journal (and vice versa) (RV2-03)."""
    dest = tmp_path / "dest"
    old = _seed_old(dest)
    stage = dest / f"{face._PROMOTE_STAGE_PREFIX}face-only"
    stage.mkdir()
    for name in _NAMES:
        (stage / name).write_text(f"NEW_{name}")
    # Face journal in dest; caption recover must not act on it.
    _write_journal(
        dest,
        FACE_PROMOTE,
        {"stage": str(stage), "names": list(_NAMES), "phase": "installing"},
    )
    # Caption recover looks for caption journal only → no-op (face journal ignored).
    cap._recover_promote(dest)
    assert _is_all_old(_read_named(dest), old), "caption recover must not touch face journal state"
    assert (dest / face._PROMOTE_JOURNAL).is_file()
    assert stage.is_dir()

    # Explicit foreign-generator payload under caption journal name → hard refuse.
    _write_journal(
        dest,
        CAPTION_PROMOTE,
        {
            "stage": str(stage),
            "names": list(_NAMES),
            "phase": "installing",
            "generator": FACE_PROMOTE.generator,  # wrong
        },
    )
    # Overwrite generator field after helper set caption's default:
    (dest / cap._PROMOTE_JOURNAL).write_text(
        json.dumps(
            {
                "stage": str(stage),
                "names": list(_NAMES),
                "phase": "installing",
                "generator": "face",
            },
            sort_keys=True,
        )
        + "\n"
    )
    with pytest.raises(PromoteError, match="generator mismatch"):
        cap._recover_promote(dest)
    assert (dest / cap._PROMOTE_JOURNAL).is_file()


def test_s4_02_face_twin_recover_installing_all_new(tmp_path: Path) -> None:
    """Face generator shares the same journaled recover contract (S4-02)."""
    dest = tmp_path / "dest"
    old = _seed_old(dest)
    (dest / "man.json").write_text("NEW_man.json")
    stage = dest / f"{face._PROMOTE_STAGE_PREFIX}face-hand"
    stage.mkdir()
    new = {name: f"NEW_{name}" for name in _NAMES}
    for name, body in new.items():
        (stage / name).write_text(body)
    _write_journal(
        dest,
        FACE_PROMOTE,
        {"stage": str(stage), "names": list(_NAMES), "phase": "installing"},
    )
    face._recover_promote(dest)
    after = _read_named(dest)
    assert _is_all_new(after, new), after
    assert not _is_mixed(after, old, new)


def test_rv2_07_scavenge_removes_old_orphan_stages(tmp_path: Path) -> None:
    """Orphan stage dirs older than max age with no journal are reclaimed (RV2-07)."""
    dest = tmp_path / "dest"
    dest.mkdir()
    orphan = dest / f"{CAPTION_PROMOTE.stage_prefix}orphan-old"
    orphan.mkdir()
    (orphan / "man.json").write_text("stale")
    # Make it old.
    old_mtime = 1_000_000.0
    os.utime(orphan, (old_mtime, old_mtime))
    # Protected stage referenced by journal must survive.
    protected = dest / f"{CAPTION_PROMOTE.stage_prefix}protected"
    protected.mkdir()
    (protected / "man.json").write_text("keep")
    _write_journal(
        dest,
        CAPTION_PROMOTE,
        {"stage": str(protected), "names": ["man.json"], "phase": "staged"},
    )
    # Fresh orphan must not be reclaimed yet.
    fresh = dest / f"{CAPTION_PROMOTE.stage_prefix}fresh"
    fresh.mkdir()
    (fresh / "man.json").write_text("new")

    reclaimed = promote.scavenge_orphan_stages(
        dest, CAPTION_PROMOTE, max_age_sec=3600.0, now=old_mtime + 7200.0
    )
    assert str(orphan) in reclaimed
    assert not orphan.exists()
    assert protected.exists(), "journal-referenced stage must not be scavenged"
    assert fresh.exists(), "fresh orphan below age threshold must stay"
    assert (dest / CAPTION_PROMOTE.journal_name).is_file()


def test_rv2_07_scavenge_skips_when_journal_corrupt(tmp_path: Path) -> None:
    """Corrupt journal → protect all stages (never destroy recovery evidence)."""
    dest = tmp_path / "dest"
    dest.mkdir()
    stage = dest / f"{CAPTION_PROMOTE.stage_prefix}maybe"
    stage.mkdir()
    (dest / CAPTION_PROMOTE.journal_name).write_text("{truncated")
    os.utime(stage, (1_000_000.0, 1_000_000.0))
    reclaimed = promote.scavenge_orphan_stages(
        dest, CAPTION_PROMOTE, max_age_sec=1.0, now=1_000_000.0 + 10_000.0
    )
    assert reclaimed == []
    assert stage.exists()


# ---------------------------------------------------------------------------
# cx3 Wave C — VLM6-R2-B-01/02/03/04 + E-01 + verify_git signature cleanup
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phase",
    ["INSTALLING", None, "unknown", "staged "],
    ids=["INSTALLING", "None", "unknown", "staged_trailing_space"],
)
def test_vlm6_r2_b03_unknown_phase_preserves_evidence(tmp_path: Path, phase) -> None:
    """Unknown phase must raise and preserve journal+stage (VLM6-R2-B-03).

    Pre-fix: only exact ``"installing"`` was special-cased; every other value
    fell through to abandon cleanup and destroyed recovery evidence on a mixed
    dest. RED: LEFT_MIXED + journal_gone + stage_gone.
    """
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "man.json").write_text("NEW_man.json")
    (dest / "run.json").write_text("OLD_run.json")
    (dest / "rep.json").write_text("OLD_rep.json")
    stage = dest / f"{CAPTION_PROMOTE.stage_prefix}probe"
    stage.mkdir()
    for name in _NAMES:
        (stage / name).write_text(f"NEW_{name}")
    journal_path = dest / CAPTION_PROMOTE.journal_name
    payload = {
        "stage": str(stage),
        "names": list(_NAMES),
        "phase": phase,
        "generator": "caption",
    }
    journal_path.write_text(json.dumps(payload) + "\n")

    with pytest.raises(PromoteError, match="unknown phase"):
        recover_promote(dest, CAPTION_PROMOTE)

    after = _read_named(dest)
    old = {n: f"OLD_{n}" for n in _NAMES}
    new = {n: f"NEW_{n}" for n in _NAMES}
    # man was already NEW; run/rep OLD — still mixed.
    assert after["man.json"] == "NEW_man.json"
    assert after["run.json"] == "OLD_run.json"
    assert after["rep.json"] == "OLD_rep.json"
    assert _is_mixed(after, old, new)
    assert journal_path.is_file(), "must preserve journal on unknown phase"
    assert stage.is_dir(), "must preserve stage on unknown phase"


def test_vlm6_r2_b01_legacy_journal_refused(tmp_path: Path) -> None:
    """Present legacy journal must raise — never silent no-op (VLM6-R2-B-01)."""
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "man.json").write_text("NEW_man.json")
    (dest / "run.json").write_text("OLD_run.json")
    (dest / "rep.json").write_text("OLD_rep.json")
    stage = dest / ".vlm-promote-stage-legacy"
    stage.mkdir()
    for name in _NAMES:
        (stage / name).write_text(f"NEW_{name}")
    legacy = dest / LEGACY_PROMOTE_JOURNAL
    legacy.write_text(
        json.dumps(
            {
                "stage": str(stage),
                "names": list(_NAMES),
                "phase": "installing",
                "generator": "caption",
            }
        )
        + "\n"
    )
    before = _read_named(dest)

    with pytest.raises(PromoteError, match="legacy promote journal"):
        recover_promote(dest, CAPTION_PROMOTE)

    assert _read_named(dest) == before
    assert legacy.is_file(), "must not delete legacy journal evidence"
    assert stage.is_dir(), "must not delete legacy stage"


def test_vlm6_r2_b01_legacy_blocks_atomic_promote(tmp_path: Path) -> None:
    """atomic_promote must refuse when a legacy journal is present."""
    dest = tmp_path / "dest"
    src = tmp_path / "src"
    _seed_old(dest)
    _seed_new(src)
    legacy = dest / LEGACY_PROMOTE_JOURNAL
    legacy.write_text('{"phase":"installing","generator":"caption","stage":"x","names":[]}\n')
    with pytest.raises(PromoteError, match="legacy promote journal"):
        atomic_promote(src, dest, list(_NAMES), CAPTION_PROMOTE)
    assert legacy.is_file()


def test_vlm6_r2_b04_cleanup_fsyncs_dest_after_journal_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Journal clear must dir-fsync before stage removal (VLM6-R2-B-04).

    Spies ``_fsync_path`` order around journal unlink so a regression that
    drops the post-unlink fsync (or reorders stage-before-journal) goes red.
    """
    dest = tmp_path / "dest"
    src = tmp_path / "src"
    _seed_old(dest)
    _seed_new(src)

    events: list[str] = []
    real_fsync = promote._fsync_path
    real_unlink = Path.unlink

    def spy_fsync(path: Path) -> None:
        events.append(f"fsync:{Path(path).name}")
        real_fsync(path)

    def spy_unlink(self: Path, *args, **kwargs):
        events.append(f"unlink:{self.name}")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(promote, "_fsync_path", spy_fsync)
    monkeypatch.setattr(Path, "unlink", spy_unlink)

    atomic_promote(src, dest, list(_NAMES), CAPTION_PROMOTE)

    # Locate journal unlink in the event stream; the next dest-dir fsync must
    # precede any stage-dir teardown (rmdir of stage shows up as later events).
    journal_name = CAPTION_PROMOTE.journal_name
    try:
        j_idx = next(i for i, e in enumerate(events) if e == f"unlink:{journal_name}")
    except StopIteration as exc:
        raise AssertionError(f"journal never unlinked; events={events}") from exc
    post = events[j_idx + 1 :]
    assert any(e == f"fsync:{dest.name}" for e in post), (
        f"dest dir must be fsynced after journal unlink; post={post} all={events}"
    )
    # Stage removal (child unlinks under stage prefix) must come *after* that fsync.
    fsync_after = next(i for i, e in enumerate(post) if e == f"fsync:{dest.name}")
    stage_teardown = [
        i
        for i, e in enumerate(post)
        if e.startswith("unlink:") and CAPTION_PROMOTE.stage_prefix.lstrip(".") in e
        or (e.startswith("unlink:") and e.endswith(".json") and i > fsync_after)
    ]
    # At least: no stage-prefix child unlinks before the post-journal fsync.
    for i, e in enumerate(post):
        if "promote-stage-" in e and e.startswith("unlink:"):
            assert i > fsync_after, (
                f"stage teardown {e} before post-journal fsync; post={post}"
            )


def test_vlm6_r2_b04_recover_cleanup_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """recover_promote installing path also fsyncs dest after journal unlink."""
    dest = tmp_path / "dest"
    old = _seed_old(dest)
    (dest / "man.json").write_text("NEW_man.json")
    stage = dest / f"{CAPTION_PROMOTE.stage_prefix}hand"
    stage.mkdir()
    new = {name: f"NEW_{name}" for name in _NAMES}
    for name, body in new.items():
        (stage / name).write_text(body)
    _write_journal(
        dest,
        CAPTION_PROMOTE,
        {"stage": str(stage), "names": list(_NAMES), "phase": "installing"},
    )

    events: list[str] = []
    real_fsync = promote._fsync_path
    real_unlink = Path.unlink

    def spy_fsync(path: Path) -> None:
        events.append(f"fsync:{Path(path).name}")
        real_fsync(path)

    def spy_unlink(self: Path, *args, **kwargs):
        events.append(f"unlink:{self.name}")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(promote, "_fsync_path", spy_fsync)
    monkeypatch.setattr(Path, "unlink", spy_unlink)

    recover_promote(dest, CAPTION_PROMOTE)
    assert _is_all_new(_read_named(dest), new)
    assert not _is_all_old(_read_named(dest), old)

    j_idx = next(
        i for i, e in enumerate(events) if e == f"unlink:{CAPTION_PROMOTE.journal_name}"
    )
    post = events[j_idx + 1 :]
    assert any(e == f"fsync:{dest.name}" for e in post), (
        f"recover must fsync dest after journal unlink; post={post}"
    )


def test_vlm6_r2_b02_concurrent_promotes_consistent(tmp_path: Path) -> None:
    """50 concurrent atomic_promotes must leave a consistent dest (VLM6-R2-B-02).

    Pre-fix: consistent=0 with_errors=50 (no flock). Post-fix: every trial
    either wins cleanly or serializes; dest is always all-from-one-writer.
    """
    dest = tmp_path / "dest"
    dest.mkdir()
    for name in _NAMES:
        (dest / name).write_text(f"OLD_{name}")

    n_workers = 50
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(i: int) -> str:
        src = tmp_path / f"src{i}"
        src.mkdir(exist_ok=True)
        for name in _NAMES:
            (src / name).write_text(f"W{i:02d}_{name}")
        atomic_promote(src, dest, list(_NAMES), CAPTION_PROMOTE)
        return f"W{i:02d}"

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futs = [pool.submit(worker, i) for i in range(n_workers)]
        for fut in as_completed(futs):
            try:
                fut.result()
            except BaseException as exc:  # noqa: BLE001 — collect all for report
                with lock:
                    errors.append(exc)

    assert errors == [], f"concurrent promote errors: {errors[:5]!r} (n={len(errors)})"
    state = _read_named(dest)
    prefixes = {state[n].rsplit("_", 1)[0] for n in _NAMES}
    assert len(prefixes) == 1, f"hybrid dest after concurrent promote: {state}"
    # Clean residue.
    assert not (dest / CAPTION_PROMOTE.journal_name).exists()
    assert not any(dest.glob(f"{CAPTION_PROMOTE.stage_prefix}*"))


def test_vlm6_r2_b02_lock_absence_goes_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEST-15: the concurrency assert must go RED if flock is neutered.

    A lock test that still passes with the lock deleted is worthless.
    """
    dest = tmp_path / "dest"
    dest.mkdir()
    for name in _NAMES:
        (dest / name).write_text(f"OLD_{name}")

    @contextmanager
    def no_lock(_dest_dir: Path, _ns: promote.PromoteNamespace) -> Iterator[None]:
        yield

    monkeypatch.setattr(promote, "_namespace_lock", no_lock)

    n_workers = 30
    error_count = 0
    hybrid = False
    barrier = threading.Barrier(n_workers)

    def worker(i: int) -> None:
        nonlocal error_count, hybrid
        src = tmp_path / f"src-nolock-{i}"
        src.mkdir(exist_ok=True)
        for name in _NAMES:
            (src / name).write_text(f"N{i:02d}_{name}")
        try:
            barrier.wait(timeout=5)
            atomic_promote(src, dest, list(_NAMES), CAPTION_PROMOTE)
        except BaseException:
            error_count += 1

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    state = _read_named(dest)
    prefixes = {state.get(n, "").rsplit("_", 1)[0] for n in _NAMES if n in state}
    if len(prefixes) > 1:
        hybrid = True

    # Without the lock we must observe either errors or a hybrid dest (or both).
    # If neither fires, the test itself is worthless — fail loudly.
    assert error_count > 0 or hybrid, (
        f"lock-absence probe stayed clean (errors={error_count} hybrid={hybrid} "
        f"state={state}); concurrency test cannot validate the lock"
    )


def test_vlm6_r2_b02_scavenge_does_not_reclaim_under_live_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scavenge must not rmtree a stage while promote holds the namespace lock."""
    dest = tmp_path / "dest"
    dest.mkdir()
    stage_live = dest / f"{CAPTION_PROMOTE.stage_prefix}live"
    stage_live.mkdir()
    (stage_live / "man.json").write_text("live")
    # Age the stage so max_age would allow reclaim if scavenge raced.
    old_mtime = 1_000_000.0
    os.utime(stage_live, (old_mtime, old_mtime))

    hold = threading.Event()
    release = threading.Event()
    reclaimed_holder: list[list[str]] = []

    real_lock = promote._namespace_lock

    @contextmanager
    def holding_lock(dest_dir: Path, ns: promote.PromoteNamespace) -> Iterator[None]:
        with real_lock(dest_dir, ns):
            hold.set()
            # Stay inside the lock until the scavenger has blocked or timed out.
            release.wait(timeout=5)
            yield

    # Thread A: hold the promote lock (simulates mid-promote).
    def holder() -> None:
        with holding_lock(dest, CAPTION_PROMOTE):
            pass

    t = threading.Thread(target=holder)
    t.start()
    assert hold.wait(timeout=5), "holder failed to acquire lock"

    # Thread B: scavenge should block on flock, not delete the live stage.
    def scavenger() -> None:
        # Short timeout path: try non-blocking by racing — we just call scavenge
        # which blocks. Release the holder after a brief moment so the test ends.
        time.sleep(0.2)
        reclaimed_holder.append(
            scavenge_orphan_stages(
                dest, CAPTION_PROMOTE, max_age_sec=1.0, now=old_mtime + 10_000.0
            )
        )

    s = threading.Thread(target=scavenger)
    s.start()
    time.sleep(0.5)
    # While holder still has the lock, stage must still exist.
    assert stage_live.is_dir(), "scavenge must not delete under live lock"
    release.set()
    t.join(timeout=5)
    s.join(timeout=5)
    # After release, scavenge may reclaim the true orphan (no journal) — that's fine.
    # The invariant under test is mid-lock survival, already asserted above.


def test_vlm6_r2_b02_journal_tmp_is_unique_behavioural(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrent journal writers must use distinct tmp paths (RE-02 / TEST-15).

    Replaces the source-string greptest that stayed green under a concat fixed-tmp
    mutant (``dest_dir / ("." + ns.journal_name + ".tmp")``). Observe the real
    tmp paths written at runtime; a fixed-tmp regression collides and goes red.
    """
    dest = tmp_path / "dest"
    dest.mkdir()
    tmp_paths: list[str] = []
    lock = threading.Lock()
    real_write_text = Path.write_text

    def spy_write_text(self: Path, data, *args, **kwargs):  # noqa: ANN001
        if str(self).endswith(".tmp"):
            with lock:
                tmp_paths.append(str(self.resolve()))
        return real_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", spy_write_text)

    n_writers = 8
    barrier = threading.Barrier(n_writers)
    errors: list[BaseException] = []

    def writer(i: int) -> None:
        try:
            barrier.wait(timeout=5)
            promote._write_promote_journal(
                dest,
                CAPTION_PROMOTE,
                {
                    "stage": str(dest / f"{CAPTION_PROMOTE.stage_prefix}{i}"),
                    "names": ["man.json"],
                    "phase": "staged",
                },
            )
        except BaseException as exc:  # noqa: BLE001 — collect for assertion
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(n_writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == [], f"journal writers raised: {errors!r}"
    assert len(tmp_paths) == n_writers, (
        f"expected {n_writers} tmp writes, got {len(tmp_paths)}: {tmp_paths}"
    )
    assert len(set(tmp_paths)) == n_writers, (
        f"journal tmp paths must be unique per writer; collisions in {tmp_paths}"
    )


def test_vlm6_r2_b02_journal_tmp_fixed_mutant_goes_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEST-15 control: fixed journal tmp must fail the uniqueness contract."""
    dest = tmp_path / "dest"
    dest.mkdir()
    tmp_paths: list[str] = []
    lock = threading.Lock()
    real_write_text = Path.write_text

    def spy_write_text(self: Path, data, *args, **kwargs):  # noqa: ANN001
        if str(self).endswith(".tmp"):
            with lock:
                tmp_paths.append(str(self.resolve()))
        return real_write_text(self, data, *args, **kwargs)

    def fixed_tmp_write(
        dest_dir: Path, ns: promote.PromoteNamespace, payload: dict
    ) -> None:
        body = dict(payload)
        body["generator"] = ns.generator
        path = dest_dir / ns.journal_name
        # Concat form that defeats the old source greptest (RE-02 mutant).
        tmp = dest_dir / ("." + ns.journal_name + ".tmp")
        tmp.write_text(json.dumps(body, sort_keys=True) + "\n")
        os.replace(tmp, path)

    monkeypatch.setattr(Path, "write_text", spy_write_text)
    monkeypatch.setattr(promote, "_write_promote_journal", fixed_tmp_write)

    n_writers = 6
    barrier = threading.Barrier(n_writers)

    def writer(i: int) -> None:
        try:
            barrier.wait(timeout=5)
            promote._write_promote_journal(
                dest,
                CAPTION_PROMOTE,
                {
                    "stage": str(dest / f"{CAPTION_PROMOTE.stage_prefix}{i}"),
                    "names": ["man.json"],
                    "phase": "staged",
                },
            )
        except OSError:
            # Clobber races are expected under the fixed-tmp mutant.
            pass

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(n_writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    # Fixed tmp → every writer shares one path → uniqueness contract fails.
    assert tmp_paths, "mutant must still write at least one tmp"
    assert len(set(tmp_paths)) < n_writers, (
        f"fixed-tmp mutant must collide; paths={tmp_paths}"
    )


def test_vlm6_cx3_validate_live_head_sha_no_verify_git_param() -> None:
    """verify_git removed from signature — callers cannot opt out (cx3/cx4)."""
    sig = inspect.signature(validate_live_head_sha)
    assert "verify_git" not in sig.parameters, (
        f"verify_git must be removed from validate_live_head_sha; got {sig}"
    )
    # Positional + git_cwd only.
    assert list(sig.parameters) == ["raw", "git_cwd"]


# ---------------------------------------------------------------------------
# wE3 Wave E — journal trust + lock scope (RC-01..05, CDX-04/05, RE-02)
# ---------------------------------------------------------------------------


def test_rc01_hostile_stage_refuses_and_preserves_external(tmp_path: Path) -> None:
    """RC-01: journal stage outside dest must not install or delete external trees."""
    dest = tmp_path / "dest"
    dest.mkdir()
    old = _seed_old(dest)
    victim = tmp_path / "important_data"
    victim.mkdir()
    for name in _NAMES:
        (victim / name).write_text(f"EVIL_{name}")
    (victim / "precious.txt").write_text("KEEPME")
    _write_journal(
        dest,
        CAPTION_PROMOTE,
        {
            "stage": str(victim),
            "names": list(_NAMES),
            "phase": "installing",
        },
    )

    with pytest.raises(PromoteError, match="stage escapes dest|does not match namespace"):
        recover_promote(dest, CAPTION_PROMOTE)

    assert victim.is_dir(), "must not delete external stage tree"
    assert (victim / "precious.txt").read_text() == "KEEPME"
    assert _is_all_old(_read_named(dest), old), "must not install from external stage"
    assert (dest / CAPTION_PROMOTE.journal_name).is_file(), "preserve journal evidence"


def test_rc01_stage_wrong_prefix_refused(tmp_path: Path) -> None:
    """RC-01: stage under dest but wrong prefix is refused."""
    dest = tmp_path / "dest"
    dest.mkdir()
    old = _seed_old(dest)
    stage = dest / "not-a-stage-prefix"
    stage.mkdir()
    for name in _NAMES:
        (stage / name).write_text(f"NEW_{name}")
    _write_journal(
        dest,
        CAPTION_PROMOTE,
        {"stage": str(stage), "names": list(_NAMES), "phase": "installing"},
    )
    with pytest.raises(PromoteError, match="does not match namespace prefix"):
        recover_promote(dest, CAPTION_PROMOTE)
    assert stage.is_dir()
    assert _is_all_old(_read_named(dest), old)


def test_rc02_unhashable_phase_is_promote_error(tmp_path: Path) -> None:
    """RC-02: list/dict phase must raise PromoteError, never TypeError."""
    dest = tmp_path / "dest"
    dest.mkdir()
    stage = dest / f"{CAPTION_PROMOTE.stage_prefix}phase"
    stage.mkdir()
    for name in _NAMES:
        (stage / name).write_text(f"NEW_{name}")
        (dest / name).write_text(f"OLD_{name}")
    journal_path = dest / CAPTION_PROMOTE.journal_name
    journal_path.write_text(
        json.dumps(
            {
                "stage": str(stage),
                "names": list(_NAMES),
                "phase": ["installing"],
                "generator": "caption",
            }
        )
        + "\n"
    )
    with pytest.raises(PromoteError, match="unknown phase"):
        recover_promote(dest, CAPTION_PROMOTE)
    assert journal_path.is_file()
    assert stage.is_dir()


def test_rc04_journal_names_must_remain_a_list(tmp_path: Path) -> None:
    """RC-04: a scalar names field must not be coerced into character names."""
    dest = tmp_path / "dest"
    dest.mkdir()
    stage = dest / f"{CAPTION_PROMOTE.stage_prefix}scalar-names"
    stage.mkdir()
    # Before the shape check, ``list(\"abc\")`` was accepted and each character
    # could be installed as an artifact name.
    for name in "abc":
        (stage / name).write_text(f"NEW_{name}")
    _write_journal(
        dest,
        CAPTION_PROMOTE,
        {"stage": str(stage), "names": "abc", "phase": "installing"},
    )
    with pytest.raises(PromoteError, match="names must be a list"):
        recover_promote(dest, CAPTION_PROMOTE)
    assert (dest / CAPTION_PROMOTE.journal_name).is_file()
    assert stage.is_dir()


def test_unreadable_journal_is_promote_error_and_preserves_evidence(tmp_path: Path) -> None:
    """RV2-01: undecodable journal bytes must fail closed as PromoteError."""
    dest = tmp_path / "dest"
    dest.mkdir()
    journal = dest / CAPTION_PROMOTE.journal_name
    journal.write_bytes(b"{\xff\n")
    with pytest.raises(PromoteError, match="unparseable promote journal"):
        recover_promote(dest, CAPTION_PROMOTE)
    assert journal.read_bytes() == b"{\xff\n"


def test_scavenge_malformed_stage_shape_protects_all_orphans(tmp_path: Path) -> None:
    """RV2-07: a typed-but-invalid stage field must never crash or delete evidence."""
    dest = tmp_path / "dest"
    dest.mkdir()
    orphan = dest / f"{CAPTION_PROMOTE.stage_prefix}malformed-journal"
    orphan.mkdir()
    (orphan / "evidence.json").write_text("keep")
    old_mtime = 1_000_000.0
    os.utime(orphan, (old_mtime, old_mtime))
    (dest / CAPTION_PROMOTE.journal_name).write_text(
        json.dumps({"stage": 123, "names": ["evidence.json"], "phase": "staged", "generator": "caption"})
    )
    reclaimed = scavenge_orphan_stages(
        dest, CAPTION_PROMOTE, max_age_sec=1.0, now=old_mtime + 10_000.0
    )
    assert reclaimed == []
    assert orphan.is_dir()


def test_rc03_legacy_message_names_real_clear_path(tmp_path: Path) -> None:
    """RC-03: legacy refuse must name a real clearable path, not a fake recover API."""
    dest = tmp_path / "dest"
    dest.mkdir()
    legacy = dest / LEGACY_PROMOTE_JOURNAL
    legacy.write_text('{"phase":"installing"}\n')
    with pytest.raises(PromoteError, match="legacy promote journal") as excinfo:
        recover_promote(dest, CAPTION_PROMOTE)
    msg = str(excinfo.value)
    assert str(legacy) in msg
    assert "recover under the old layout" not in msg
    assert "remove" in msg.lower()
    assert "no automated recovery" in msg.lower() or "manual" in msg.lower()
    # Clearable: after operator removes legacy, promote proceeds.
    legacy.unlink()
    src = tmp_path / "src"
    _seed_new(src)
    _seed_old(dest)
    atomic_promote(src, dest, list(_NAMES), CAPTION_PROMOTE)
    assert _is_all_new(_read_named(dest), {n: f"NEW_{n}" for n in _NAMES})


def test_rc04_pathlike_names_refuse_promote_error(tmp_path: Path) -> None:
    """RC-04: path-like journal names must raise PromoteError, not FileNotFoundError."""
    dest = tmp_path / "dest"
    dest.mkdir()
    stage = dest / f"{CAPTION_PROMOTE.stage_prefix}escape"
    stage.mkdir()
    name = "sub/../../escape_target.json"
    # Plant a file where stage/name would resolve so incomplete-stage is not the gate.
    target = stage / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("ESCAPE")
    _write_journal(
        dest,
        CAPTION_PROMOTE,
        {"stage": str(stage), "names": [name], "phase": "installing"},
    )
    with pytest.raises(PromoteError, match="unsafe promote name"):
        recover_promote(dest, CAPTION_PROMOTE)
    assert (dest / CAPTION_PROMOTE.journal_name).is_file()
    assert stage.is_dir()


def test_rc04_pathlike_names_refuse_on_atomic_promote(tmp_path: Path) -> None:
    """RC-04: atomic_promote also rejects path-like caller names."""
    dest = tmp_path / "dest"
    src = tmp_path / "src"
    dest.mkdir()
    src.mkdir()
    bad = "sub/file.json"
    (src / "sub").mkdir()
    (src / bad).write_text("x")
    with pytest.raises(PromoteError, match="unsafe promote name"):
        atomic_promote(src, dest, [bad], CAPTION_PROMOTE)


def test_rc05_ghost_installing_names_journal_and_clear_path(tmp_path: Path) -> None:
    """RC-05: ghost installing+missing stage error must name journal + clear steps."""
    dest = tmp_path / "dest"
    dest.mkdir()
    old = _seed_old(dest)
    ghost = dest / f"{CAPTION_PROMOTE.stage_prefix}ghost"
    journal_path = dest / CAPTION_PROMOTE.journal_name
    _write_journal(
        dest,
        CAPTION_PROMOTE,
        {
            "stage": str(ghost),
            "names": list(_NAMES),
            "phase": "installing",
        },
    )
    with pytest.raises(PromoteError, match="stage dir missing") as excinfo:
        recover_promote(dest, CAPTION_PROMOTE)
    msg = str(excinfo.value)
    assert str(journal_path) in msg or CAPTION_PROMOTE.journal_name in msg
    assert "remove" in msg.lower()
    assert _is_all_old(_read_named(dest), old)
    # Clearable after operator removes journal.
    journal_path.unlink()
    src = tmp_path / "src"
    new = _seed_new(src)
    atomic_promote(src, dest, list(_NAMES), CAPTION_PROMOTE)
    assert _is_all_new(_read_named(dest), new)


def test_cdx04_promoting_tmp_is_namespace_scoped(tmp_path: Path) -> None:
    """CDX-04: caption and face install temps must not share .<stem>.promoting."""
    name = "shared-stem.json"
    cap_tmp = promote._promoting_tmp(tmp_path, CAPTION_PROMOTE, name)
    face_tmp = promote._promoting_tmp(tmp_path, FACE_PROMOTE, name)
    assert cap_tmp != face_tmp
    assert CAPTION_PROMOTE.generator in cap_tmp.name
    assert FACE_PROMOTE.generator in face_tmp.name
    assert cap_tmp.name != f".{name}.promoting"
    assert face_tmp.name != f".{name}.promoting"


def test_cdx04_concurrent_caption_face_same_stem_no_hybrid(tmp_path: Path) -> None:
    """CDX-04: concurrent caption+face promote of same stem must not hybridize bytes."""
    dest = tmp_path / "dest"
    dest.mkdir()
    name = "shared-stem.json"
    (dest / name).write_text("OLD")
    # Distinct payloads large enough that interleaved writes would hybridize.
    caption_body = ("C" * 64 + "\n") * 64
    face_body = ("F" * 64 + "\n") * 64
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(ns: promote.PromoteNamespace, body: str) -> None:
        src = tmp_path / f"src-{ns.generator}"
        src.mkdir(exist_ok=True)
        (src / name).write_text(body)
        try:
            barrier.wait(timeout=5)
            atomic_promote(src, dest, [name], ns)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    t1 = threading.Thread(target=worker, args=(CAPTION_PROMOTE, caption_body))
    t2 = threading.Thread(target=worker, args=(FACE_PROMOTE, face_body))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert errors == [], f"cross-namespace promote errors: {errors!r}"
    final = (dest / name).read_text()
    assert final in {caption_body, face_body}, (
        f"dest hybridized or corrupt (len={len(final)}); "
        f"head={final[:40]!r}"
    )
    # No leftover shared-stem promoting temps.
    residue = [p.name for p in dest.iterdir() if "promoting" in p.name]
    assert residue == [], f"promoting residue left: {residue}"


def test_cdx05_reserved_lock_name_refused(tmp_path: Path) -> None:
    """CDX-05: atomic_promote must refuse names that replace the lock pathname."""
    dest = tmp_path / "dest"
    src = tmp_path / "src"
    dest.mkdir()
    src.mkdir()
    lock_name = f".vlm-{CAPTION_PROMOTE.generator}-promote.lock"
    (src / lock_name).write_text("NEWLOCKBODY")
    # Seed lock inode so we can detect replacement if refusal regresses.
    lock_path = dest / lock_name
    lock_path.write_text("ORIGINAL")
    inode_before = lock_path.stat().st_ino

    with pytest.raises(PromoteError, match="reserved promote name"):
        atomic_promote(src, dest, [lock_name], CAPTION_PROMOTE)

    assert lock_path.read_text() == "ORIGINAL"
    assert lock_path.stat().st_ino == inode_before


def test_cdx05_reserved_journal_name_refused(tmp_path: Path) -> None:
    """CDX-05: journal filename must not be installable as an artifact name."""
    dest = tmp_path / "dest"
    src = tmp_path / "src"
    dest.mkdir()
    src.mkdir()
    jname = CAPTION_PROMOTE.journal_name
    (src / jname).write_text("{}")
    with pytest.raises(PromoteError, match="reserved promote name"):
        atomic_promote(src, dest, [jname], CAPTION_PROMOTE)


def _stamped_run_record(generator_module: str, marker: str) -> str:
    """Minimal acx-eval-shaped run-record body with provenance.generator stamp."""
    return json.dumps(
        {
            "schema": "acx-eval/v1",
            "kind": "run_record",
            "provenance": {
                "generator": generator_module,
                "marker": marker,
            },
            "items": [],
        },
        sort_keys=True,
    ) + "\n"


def test_wf3_foreign_namespace_stamped_dest_refused(tmp_path: Path) -> None:
    """wF3 / wE3 residual: stamped foreign dest basename must refuse, not LWW.

    Caption and face both emit ``{stem}.json``. After caption installs a
    provenance-stamped run-record, face promote of the same basename must raise
    PromoteError and leave caption bytes intact (fail-closed; TEST-15).
    """
    dest = tmp_path / "dest"
    src_face = tmp_path / "src-face"
    dest.mkdir()
    src_face.mkdir()
    name = "shared-stem.json"
    caption_body = _stamped_run_record(
        "scripts.eval_harness.generate_determinism_anchor", "CAPTION"
    )
    face_body = _stamped_run_record(
        "scripts.eval_harness.generate_face_determinism_anchor", "FACE"
    )
    (dest / name).write_text(caption_body)
    (src_face / name).write_text(face_body)

    with pytest.raises(PromoteError, match="foreign generator namespace"):
        atomic_promote(src_face, dest, [name], FACE_PROMOTE)

    assert (dest / name).read_text() == caption_body


def test_wf3_same_namespace_regen_allowed(tmp_path: Path) -> None:
    """Same-namespace regeneration of a stamped basename must still succeed."""
    dest = tmp_path / "dest"
    src = tmp_path / "src"
    dest.mkdir()
    src.mkdir()
    name = "shared-stem.json"
    old = _stamped_run_record(
        "scripts.eval_harness.generate_determinism_anchor", "OLD"
    )
    new = _stamped_run_record(
        "scripts.eval_harness.generate_determinism_anchor", "NEW"
    )
    (dest / name).write_text(old)
    (src / name).write_text(new)
    atomic_promote(src, dest, [name], CAPTION_PROMOTE)
    assert (dest / name).read_text() == new


def test_wf3_unstamped_dest_still_last_writer_wins(tmp_path: Path) -> None:
    """Unstamped plain files remain LWW so CDX-04 concurrent hybrid guard holds."""
    dest = tmp_path / "dest"
    src = tmp_path / "src"
    dest.mkdir()
    src.mkdir()
    name = "plain.json"
    (dest / name).write_text("CAPTION_PLAIN")
    (src / name).write_text("FACE_PLAIN")
    atomic_promote(src, dest, [name], FACE_PROMOTE)
    assert (dest / name).read_text() == "FACE_PLAIN"


def test_wf3_caption_face_generators_same_stem_refuse(tmp_path: Path) -> None:
    """End-to-end: both generators + identical stem → second promote refuses.

    Drives real write_anchor / write_face_anchor into one out_dir (TEST-15).
    """
    out = tmp_path / "out"
    out.mkdir()
    stem = "shared-stem-collision"
    man = Path(__file__).resolve().parent / "seed" / "golden.json"

    cap.write_anchor(manifest_path=man, out_dir=out, stem=stem)
    caption_run = (out / f"{stem}.json").read_text()
    cap_gen = json.loads(caption_run)["provenance"]["generator"]
    assert "generate_determinism_anchor" in cap_gen
    assert "generate_face_determinism_anchor" not in cap_gen

    with pytest.raises(PromoteError, match="foreign generator namespace"):
        face.write_face_anchor(
            out_dir=out, stem=stem, manifest_stem=f"{stem}-manifest"
        )

    # Caption run-record bytes preserved; no silent face clobber.
    assert (out / f"{stem}.json").read_text() == caption_run
    assert not (out / f"{stem}-face-report.json").is_file()

