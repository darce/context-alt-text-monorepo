"""Permanent regression for S4-02 journaled set-atomic promote (gx4).

Pre-fix bare per-file ``os.replace`` loops left a mixed destination after a
mid-promote crash (some files NEW, some OLD). Journaled promote +
``_recover_promote`` guarantees the named set is fully old or fully new after
return or after crash + recover (never mixed).

Heuristics: TEST-15, AUDIT-07, EVAL-23, rg-002, rg-006.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.eval_harness import generate_determinism_anchor as cap
from scripts.eval_harness import generate_face_determinism_anchor as face


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


def test_s4_02_crash_mid_install_recover_yields_all_new(tmp_path: Path) -> None:
    """Crash after first install replace; recovery must converge to all-new."""
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
            mp.setattr(cap.os, "replace", killing_replace)
            cap._atomic_promote(src, dest, list(_NAMES))

    mid = _read_named(dest)
    # Transient mixed is allowed until recover (documented by gx4).
    assert _is_mixed(mid, old, new) or _is_all_new(mid, new), mid

    cap._recover_promote(dest)
    after = _read_named(dest)
    assert _is_all_new(after, new), f"recovery must yield all-new, got {after}"
    assert not _is_mixed(after, old, new)
    assert not (dest / cap._PROMOTE_JOURNAL).exists()
    assert not any(dest.glob(f"{cap._PROMOTE_STAGE_PREFIX}*"))


def test_s4_02_crash_before_install_recover_yields_all_old(tmp_path: Path) -> None:
    """Phase=staged only: recovery abandons stage and leaves all-old."""
    dest = tmp_path / "dest"
    old = _seed_old(dest)
    stage = dest / f"{cap._PROMOTE_STAGE_PREFIX}test-staged"
    stage.mkdir()
    for name in _NAMES:
        (stage / name).write_text(f"NEW_{name}")
    (dest / cap._PROMOTE_JOURNAL).write_text(
        json.dumps(
            {"stage": str(stage), "names": list(_NAMES), "phase": "staged"},
            sort_keys=True,
        )
        + "\n"
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
    (dest / cap._PROMOTE_JOURNAL).write_text(
        json.dumps(
            {"stage": str(stage), "names": list(_NAMES), "phase": "installing"},
            sort_keys=True,
        )
        + "\n"
    )
    mid = _read_named(dest)
    assert _is_mixed(mid, old, new), mid

    cap._recover_promote(dest)
    after = _read_named(dest)
    assert _is_all_new(after, new), after
    assert not _is_mixed(after, old, new)
    assert not (dest / cap._PROMOTE_JOURNAL).exists()


def test_s4_02_clean_promote_leaves_no_journal(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    src = tmp_path / "src"
    old = _seed_old(dest)
    new = _seed_new(src)
    cap._atomic_promote(src, dest, list(_NAMES))
    after = _read_named(dest)
    assert _is_all_new(after, new), after
    assert not _is_all_old(after, old)
    assert not (dest / cap._PROMOTE_JOURNAL).exists()
    assert not any(dest.glob(f"{cap._PROMOTE_STAGE_PREFIX}*"))
    assert not any(dest.glob(".*.promoting"))


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
    (dest / face._PROMOTE_JOURNAL).write_text(
        json.dumps(
            {"stage": str(stage), "names": list(_NAMES), "phase": "installing"},
            sort_keys=True,
        )
        + "\n"
    )
    face._recover_promote(dest)
    after = _read_named(dest)
    assert _is_all_new(after, new), after
    assert not _is_mixed(after, old, new)
