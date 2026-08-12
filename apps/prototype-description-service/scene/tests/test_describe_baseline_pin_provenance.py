"""Permanent regression for S4-04 pin-mode null provenance + S4-06 zero-SHA refuse.

S4-04: pin mode nulls ``provenance.head_sha`` and ``provenance.started_at`` while
keeping typed sentinels in ``fixture_revision`` / ``canonical_timestamp``.

S4-06: ``describe_baseline.resolve_head_sha()`` refuses the fabricated 40-zero
sentinel with SystemExit so a pinned fixture cannot be attributed to a non-
existent commit.

RV3-05: when git is available and the cwd is a work tree, an explicit SHA must
also resolve via ``git rev-parse --verify <sha>^{commit}`` — arbitrary 40-hex
is not enough.

HARM-03 / RV2-06: unresolvable HEAD is ``None`` everywhere (cli / fusion_runner /
describe_baseline); never ``\"unknown\"`` or forty zeros.

Heuristics: TEST-15, AUDIT-07, EVAL-23, rg-008, rg-015, sr-006, sr-007.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.eval_harness import describe_baseline as db
from scripts.eval_harness.generate_determinism_anchor import (
    _DEFAULT_CANONICAL_TIMESTAMP,
    _DEFAULT_FIXTURE_REVISION,
    write_anchor,
)
from scripts.eval_harness.generate_face_determinism_anchor import (
    build_face_anchor_run_record,
)

_GOLDEN = Path(__file__).resolve().parent / "seed" / "golden.json"
_ZERO_SHA = "0" * 40
_CANONICAL_TS = "2026-08-11T00:00:00Z"


def _worktree_head_sha() -> str:
    """Canonical 40-char HEAD from the active worktree (never invent)."""
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert len(out) == 40 and all(c in "0123456789abcdef" for c in out.lower())
    assert out != _ZERO_SHA
    return out.lower()


def test_s4_04_pin_mode_nulls_head_sha_and_started_at(tmp_path: Path) -> None:
    """Pin mode: contract clocks are null; fixture_* sentinels remain."""
    run_path, report_json, _md, _sha = write_anchor(
        manifest_path=_GOLDEN,
        out_dir=tmp_path,
        stem="pin-prov",
        # default pin_live_provenance=True
        fixture_revision=_DEFAULT_FIXTURE_REVISION,
        canonical_timestamp=_DEFAULT_CANONICAL_TIMESTAMP,
    )
    for path in (run_path, report_json):
        prov = json.loads(path.read_text())["provenance"]
        assert prov["head_sha"] is None, f"{path.name}: head_sha must be null in pin mode"
        assert prov["started_at"] is None, f"{path.name}: started_at must be null in pin mode"
        assert prov["fixture_revision"] == _ZERO_SHA
        assert prov["canonical_timestamp"] == _CANONICAL_TS


def test_s4_04_non_pin_does_not_null_live_provenance(tmp_path: Path) -> None:
    """Negative: non-pinned run keeps real head_sha / started_at (not unconditional null)."""
    live_sha = "b" * 40
    live_ts = "2026-03-15T12:00:00Z"
    run_path, report_json, _md, _sha = write_anchor(
        manifest_path=_GOLDEN,
        out_dir=tmp_path,
        stem="live-prov",
        pin_live_provenance=False,
        live_head_sha=live_sha,
        live_started_at=live_ts,
    )
    for path in (run_path, report_json):
        prov = json.loads(path.read_text())["provenance"]
        assert prov["head_sha"] == live_sha, f"{path.name}: live head_sha must not be nulled"
        assert prov["started_at"] == live_ts, f"{path.name}: live started_at must not be nulled"
        # Sentinels still present for byte-stability fields
        assert prov["fixture_revision"] == _ZERO_SHA
        assert prov["canonical_timestamp"] == _CANONICAL_TS


def test_s4_04_face_pin_nulls_contract_clocks() -> None:
    """Face anchor run-record also nulls contract clocks; sentinels only in fixture_*."""
    record = build_face_anchor_run_record(
        manifest_sha256="c" * 64,
        fixture_revision=_ZERO_SHA,
        canonical_timestamp=_CANONICAL_TS,
    )
    prov = record["provenance"]
    assert prov["head_sha"] is None
    assert prov["started_at"] is None
    assert prov["fixture_revision"] == _ZERO_SHA
    assert prov["canonical_timestamp"] == _CANONICAL_TS


def test_s4_06_resolve_head_sha_refuses_forty_zero_sentinel() -> None:
    with pytest.raises(SystemExit, match="fabricated 40-zero sentinel") as excinfo:
        db.resolve_head_sha(_ZERO_SHA)
    msg = str(excinfo.value)
    assert _ZERO_SHA in msg or "40-zero" in msg or "forty" in msg.lower() or "0" * 8 in msg
    # Operator-facing: names the sentinel so this is not an ordinary bad-SHA reject.
    assert "sentinel" in msg.lower() or "fabricated" in msg.lower()


def test_s4_06_resolve_head_sha_accepts_real_sha() -> None:
    """RV3-05 (a): genuine worktree HEAD passes git rev-parse --verify.

    Pre-fix used ``\"a\"*40`` and only checked format round-trip — that documented
    the weak contract. This pins the tightened contract against a real commit.
    """
    real = _worktree_head_sha()
    assert db.resolve_head_sha(real) == real
    assert db.resolve_head_sha(real.upper()) == real  # lowercased + verified


def test_rv3_05_resolve_head_sha_refuses_arbitrary_40_hex() -> None:
    """RV3-05: format-valid but non-existent commit is refused when git can answer."""
    fake = "a" * 40
    # Sanity: worktree HEAD is not the fabricated hex (or test is vacuous).
    assert fake != _worktree_head_sha()
    with pytest.raises(SystemExit, match="not a resolvable commit") as excinfo:
        db.resolve_head_sha(fake)
    assert fake in str(excinfo.value)


def test_rv3_05_resolve_head_sha_degrades_without_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When git binary is missing, format-valid SHA is accepted (sane degrade)."""
    import scripts.eval_harness.describe_baseline as db_mod

    def _no_git(*_a, **_k):
        raise OSError("git missing")

    monkeypatch.setattr(db_mod.subprocess, "run", _no_git)
    fake = "deadbeef" * 5
    assert db.resolve_head_sha(fake) == fake


def test_s4_06_resolve_head_sha_unset_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEAD_SHA", raising=False)
    monkeypatch.setattr(db, "HEAD_SHA", None)
    assert db.resolve_head_sha(None) is None
    assert db.resolve_head_sha("") is None


def test_s4_06_module_head_sha_default_is_not_forty_zeros() -> None:
    """Module default must not be the fabricated sentinel (pre-fix RED)."""
    assert db.HEAD_SHA != _ZERO_SHA
    assert db.HEAD_SHA is None or (
        isinstance(db.HEAD_SHA, str) and db.HEAD_SHA != _ZERO_SHA
    )


def test_rv2_06_cli_head_sha_returns_none_on_git_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cli._head_sha: git failure → None (never \"unknown\" or forty zeros)."""
    from scripts.eval_harness import cli as cli_mod

    def _boom(*_a, **_k):
        raise OSError("git missing")

    monkeypatch.setattr(cli_mod.subprocess, "run", _boom)
    got = cli_mod._head_sha()
    assert got is None
    assert got != "unknown"
    assert got != _ZERO_SHA


def test_rv2_06_fusion_head_sha_returns_none_on_git_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fusion_runner._head_sha: git failure → None (never forty zeros)."""
    from scripts.eval_harness import fusion_runner as fr

    def _boom(*_a, **_k):
        raise FileNotFoundError("git missing")

    monkeypatch.setattr(fr.subprocess, "check_output", _boom)
    got = fr._head_sha()
    assert got is None
    assert got != _ZERO_SHA


def test_rv2_06_no_head_sha_path_emits_forty_zeros(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-module: unresolvable HEAD never travels as the fabricated sentinel."""
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness import fusion_runner as fr

    def _cli_boom(*_a, **_k):
        raise OSError("no git")

    def _fr_boom(*_a, **_k):
        raise FileNotFoundError("no git")

    monkeypatch.setattr(cli_mod.subprocess, "run", _cli_boom)
    monkeypatch.setattr(fr.subprocess, "check_output", _fr_boom)
    monkeypatch.delenv("HEAD_SHA", raising=False)
    monkeypatch.setattr(db, "HEAD_SHA", None)

    for value in (cli_mod._head_sha(), fr._head_sha(), db.resolve_head_sha(None)):
        assert value is None or value != _ZERO_SHA
        assert value != _ZERO_SHA
        # And never the pre-fix string encodings of "absent".
        assert value not in ("unknown", "")
