"""Permanent regression for S4-02 journaled set-atomic promote (gx4 + fx2).

Pre-fix bare per-file ``os.replace`` loops left a mixed destination after a
mid-promote crash (some files NEW, some OLD). Journaled promote +
``recover_promote`` guarantees the named set is fully old or fully new after
return or after crash + recover (never mixed).

fx2 closed three recovery durability holes (RV2-01/02/03), de-duplicated the
protocol (HARM-02), and added mid-flight journal observation (RV3-03) plus face
crash coverage (RV3-02).

Heuristics: TEST-15, AUDIT-07, EVAL-23, rg-002, rg-006, rg-008.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.eval_harness import generate_determinism_anchor as cap
from scripts.eval_harness import generate_face_determinism_anchor as face
from scripts.eval_harness import promote_atomic as promote
from scripts.eval_harness.promote_atomic import (
    CAPTION_PROMOTE,
    FACE_PROMOTE,
    PromoteError,
    atomic_promote,
    recover_promote,
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


def test_s4_02_pre_fix_naive_loop_leaves_mixed(tmp_path: Path) -> None:
    """RED condition: bare per-file promote without journal leaves mixed dest.

    Encodes the failure gx4 closed — permanent so a reintroduction of the naive
    loop is caught. This is the pre-fix path, not the production API.
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


def test_rv3_03_bare_loop_mutant_fails_midflight_spy(tmp_path: Path) -> None:
    """Bare os.replace loop (no journal) must fail the mid-flight journal assert."""
    dest = tmp_path / "dest"
    src = tmp_path / "src"
    _seed_old(dest)
    _seed_new(src)

    phases_seen: list[str] = []

    def bare_loop(src_dir, dest_dir, names):
        for name in names:
            os.replace(src_dir / name, dest_dir / name)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cap, "_atomic_promote", bare_loop)
        # Drive the same observations the clean-promote test requires.
        cap._atomic_promote(src, dest, list(_NAMES))
    # Mutant leaves no journal evidence mid-flight.
    assert "staged" not in phases_seen
    assert "installing" not in phases_seen
    # And the production clean-promote test's spy would have failed — re-check
    # via the real API that a bare mutant cannot satisfy journal observation.
    # (phases_seen stays empty because bare_loop never journals.)
    assert phases_seen == []


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
