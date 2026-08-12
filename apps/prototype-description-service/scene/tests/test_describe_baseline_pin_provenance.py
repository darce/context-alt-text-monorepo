"""Permanent regression for S4-04 pin-mode null provenance + S4-06 zero-SHA refuse.

S4-04: pin mode nulls ``provenance.head_sha`` and ``provenance.started_at`` while
keeping typed sentinels in ``fixture_revision`` / ``canonical_timestamp``.

S4-06: ``describe_baseline.resolve_head_sha()`` refuses the fabricated 40-zero
sentinel with SystemExit so a pinned fixture cannot be attributed to a non-
existent commit.

fx2: generator CLI ``--live-head-sha`` must share the same refuse rules (RV2-04)
and pin mode must be an explicit ``--pin``/``--no-pin`` flag so empty-string
``--live-head-sha`` cannot silently exit pin mode (RV2-05).

Heuristics: TEST-15, AUDIT-07, EVAL-23, rg-008, rg-015, sr-006.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness import describe_baseline as db
from scripts.eval_harness import generate_determinism_anchor as gen
from scripts.eval_harness.generate_determinism_anchor import (
    _DEFAULT_CANONICAL_TIMESTAMP,
    _DEFAULT_FIXTURE_REVISION,
    write_anchor,
)
from scripts.eval_harness.generate_face_determinism_anchor import (
    build_face_anchor_run_record,
)
from scripts.eval_harness.promote_atomic import validate_live_head_sha

_GOLDEN = Path(__file__).resolve().parent / "seed" / "golden.json"
_ZERO_SHA = "0" * 40
_REAL_SHA = "a" * 40
_CANONICAL_TS = "2026-08-11T00:00:00Z"


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
    """Guard must not reject everything — genuine resolvable SHA still passes."""
    assert db.resolve_head_sha(_REAL_SHA) == _REAL_SHA
    assert db.resolve_head_sha(_REAL_SHA.upper()) == _REAL_SHA  # lowercased


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


# --- RV2-04 / RV2-05: generator CLI live-head-sha + explicit pin flag ------------


@pytest.mark.parametrize(
    "bad",
    [
        _ZERO_SHA,
        "deadbeef",
        "None",
        "not-a-sha-at-all!!!",
        "0000000000000000000000000000000000000000",
    ],
)
def test_rv2_04_validate_live_head_sha_refuses_fabrications(bad: str) -> None:
    """Generator CLI path refuses the same fabrication class as S4-06 (RV2-04)."""
    with pytest.raises(SystemExit) as excinfo:
        validate_live_head_sha(bad)
    msg = str(excinfo.value)
    assert "live-head-sha" in msg.lower() or "40" in msg or "sentinel" in msg.lower()


def test_rv2_04_validate_live_head_sha_accepts_real_hex() -> None:
    assert validate_live_head_sha(_REAL_SHA) == _REAL_SHA
    assert validate_live_head_sha(_REAL_SHA.upper()) == _REAL_SHA


def test_rv2_05_empty_live_head_sha_refused() -> None:
    """Empty string must not silently exit pin mode (RV2-05 / S4-04 reentry)."""
    with pytest.raises(SystemExit, match="must not be empty"):
        validate_live_head_sha("")
    with pytest.raises(SystemExit, match="must not be empty"):
        validate_live_head_sha("   ")


def test_rv2_05_pin_mode_gated_on_flag_not_none_sentinel(tmp_path: Path) -> None:
    """pin_live_provenance=True nulls clocks even if live_* were somehow passed.

    Pre-fix gated on ``live_* is None``, so empty-string live_head_sha exited
    pin mode and injected wall-clock started_at. Explicit flag is the gate.
    """
    run_path, report_json, _md, _sha = write_anchor(
        manifest_path=_GOLDEN,
        out_dir=tmp_path,
        stem="pin-flag",
        pin_live_provenance=True,
        # Deliberately pass a value: pin flag must win (API ignores live under pin).
        live_head_sha=_REAL_SHA,
        live_started_at="2026-03-15T12:00:00Z",
    )
    for path in (run_path, report_json):
        prov = json.loads(path.read_text())["provenance"]
        assert prov["head_sha"] is None
        assert prov["started_at"] is None


def test_rv2_04_cli_refuses_bad_live_head_sha(tmp_path: Path) -> None:
    """CLI main refuses fabricated --live-head-sha before any promote (RV2-04)."""
    with pytest.raises(SystemExit) as excinfo:
        gen.main(
            [
                "--manifest",
                str(_GOLDEN),
                "--out-dir",
                str(tmp_path),
                "--stem",
                "cli-bad-sha",
                "--no-pin",
                "--live-head-sha",
                _ZERO_SHA,
            ]
        )
    assert "sentinel" in str(excinfo.value).lower() or "40-zero" in str(excinfo.value)


def test_rv2_05_cli_refuses_empty_live_head_sha(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="must not be empty"):
        gen.main(
            [
                "--manifest",
                str(_GOLDEN),
                "--out-dir",
                str(tmp_path),
                "--stem",
                "cli-empty-sha",
                "--no-pin",
                "--live-head-sha",
                "",
            ]
        )


def test_rv2_05_cli_live_head_requires_no_pin(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="requires --no-pin"):
        gen.main(
            [
                "--manifest",
                str(_GOLDEN),
                "--out-dir",
                str(tmp_path),
                "--stem",
                "cli-pin-conflict",
                "--live-head-sha",
                _REAL_SHA,
            ]
        )
