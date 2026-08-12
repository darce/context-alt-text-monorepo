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
    """Negative: non-pinned run keeps real head_sha / started_at (not unconditional null).

    live_head_sha must be a resolvable commit (fx6: verify_git default-on).
    """
    live_sha = _worktree_head_sha()
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
    """When git binary is missing (FileNotFoundError), format-valid SHA is accepted.

    VLM6-R2-D-02: only a hard no-binary signal degrades; generic OSError must not.
    """
    import scripts.eval_harness.provenance_sha as prov

    def _no_git(*_a, **_k):
        raise FileNotFoundError("git missing")

    # Git probe lives in the shared provenance module (fx6 de-dupe).
    monkeypatch.setattr(prov.subprocess, "run", _no_git)
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
    assert validate_live_head_sha(_worktree_head_sha()) == _worktree_head_sha()
    assert validate_live_head_sha(_worktree_head_sha().upper()) == _worktree_head_sha()


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
        live_head_sha=_worktree_head_sha(),
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
                _worktree_head_sha(),
            ]
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


# --- fx6: resolve_head_sha ↔ validate_live_head_sha must not diverge (rg-015) ---


def _outcome(fn, value):
    """Drive one guard; return ('ok', sha) | ('none', None) | ('refuse', msg)."""
    try:
        out = fn(value)
    except SystemExit as exc:
        return ("refuse", str(exc))
    if out is None:
        return ("none", None)
    return ("ok", out)


def test_fx6_head_sha_entry_points_agree_on_accept_refuse_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fx6 / rg-015 / TEST-15: both entry points share one accept/refuse table.

    Empty-string policy legitimately differs (describe unset→None; CLI refuse),
    so that row is asserted separately. Format / zero / real-HEAD / uppercase
    outcomes must match so the two wrappers cannot drift open independently.
    """
    real = _worktree_head_sha()
    # Shared rows: same accept/refuse class through both entry points.
    shared_cases: list[tuple[object, str]] = [
        (None, "none"),
        (_ZERO_SHA, "refuse"),
        ("deadbeef", "refuse"),
        ("not-a-sha-at-all!!!", "refuse"),
        ("a" * 40, "refuse"),  # format-valid but non-commit when git answers
        (real, "ok"),
        (real.upper(), "ok"),
    ]
    for value, expect_kind in shared_cases:
        r_kind, r_val = _outcome(db.resolve_head_sha, value)
        v_kind, v_val = _outcome(validate_live_head_sha, value)
        assert r_kind == expect_kind, f"resolve_head_sha({value!r}) → {r_kind}, want {expect_kind}"
        assert v_kind == expect_kind, f"validate_live_head_sha({value!r}) → {v_kind}, want {expect_kind}"
        if expect_kind == "ok":
            assert r_val == v_val == real

    # Empty policy is the deliberate call-site difference (documented in fx6 report).
    assert _outcome(db.resolve_head_sha, "")[0] == "none"
    assert _outcome(db.resolve_head_sha, "   ")[0] == "none"
    assert _outcome(validate_live_head_sha, "")[0] == "refuse"
    assert _outcome(validate_live_head_sha, "   ")[0] == "refuse"

    # Degrade only when the git binary is missing (FileNotFoundError/ENOENT).
    # Generic OSError must not open the format-only hatch (VLM6-R2-D-02).
    import scripts.eval_harness.provenance_sha as prov

    def _no_git_binary(*_a, **_k):
        raise FileNotFoundError("git missing")

    monkeypatch.setattr(prov.subprocess, "run", _no_git_binary)
    fake = "deadbeef" * 5
    assert _outcome(db.resolve_head_sha, fake) == ("ok", fake)
    assert _outcome(validate_live_head_sha, fake) == ("ok", fake)


# --- VLM6-R2-D-03: operator-boundary lock (CLI main + no verify_git reentry) ---


def test_vlm6_r2_d03_cli_main_refuses_fabricated_40_hex(tmp_path: Path) -> None:
    """Operator boundary: main([... '--live-head-sha', fake]) must refuse.

    The library-level divergence table alone does not lock CLI wiring — a future
    'cleanup' that reintroduces verify_git=False at the call site reopens the
    hole while defaults-only tests stay green (VLM6-R2-D-03 / TEST-15 / rg-015).
    """
    fake = "a" * 40
    assert fake != _worktree_head_sha()
    with pytest.raises(SystemExit, match="not a resolvable commit") as excinfo:
        gen.main(
            [
                "--manifest",
                str(_GOLDEN),
                "--out-dir",
                str(tmp_path),
                "--stem",
                "cli-fake-hex",
                "--no-pin",
                "--live-head-sha",
                fake,
            ]
        )
    assert fake in str(excinfo.value)


def test_vlm6_r2_d03_validate_live_head_sha_has_no_verify_git_param() -> None:
    """cx3 ships validate_live_head_sha without verify_git; lock that contract.

    Expected-red until lane cx3 removes the parameter (cross-lane). A reintroduced
    parameter is the exact footgun that reopens format-only acceptance.
    """
    import inspect

    sig = inspect.signature(validate_live_head_sha)
    assert "verify_git" not in sig.parameters, (
        "validate_live_head_sha must not expose verify_git= "
        f"(got params {list(sig.parameters)}); cx3 removes it — VLM6-R2-D-03"
    )


def test_vlm6_r2_d03_no_call_site_passes_verify_git() -> None:
    """No eval_harness call site may pass verify_git= into validate_live_head_sha."""
    import re

    harness = Path(__file__).resolve().parents[2] / "scripts" / "eval_harness"
    offenders: list[str] = []
    # Match validate_live_head_sha(...) that includes verify_git= in the same call.
    call_re = re.compile(
        r"validate_live_head_sha\s*\((?:[^)]|\n)*?verify_git\s*=",
        re.MULTILINE,
    )
    for path in sorted(harness.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if call_re.search(text):
            offenders.append(path.name)
    assert not offenders, (
        "call sites pass verify_git= into validate_live_head_sha: "
        f"{offenders} (VLM6-R2-D-03)"
    )


# --- VLM6-R2-D-02: degrade only on hard missing-git-binary (ENOENT) ----------


def _fake_40() -> str:
    return "a" * 40


class _Completed:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_vlm6_r2_d02_poisoned_git_dir_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GIT_DIR pointing at a nonexistent path must refuse, not format-only degrade."""
    monkeypatch.setenv("GIT_DIR", "/nonexistent/path")
    fake = _fake_40()
    with pytest.raises(SystemExit) as excinfo:
        validate_live_head_sha(fake)
    msg = str(excinfo.value).lower()
    assert "not a resolvable commit" in msg or "git" in msg
    assert fake in str(excinfo.value) or "live-head-sha" in msg


def test_vlm6_r2_d02_is_inside_timeout_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """is-inside-work-tree TimeoutExpired must refuse (not silent format-only)."""
    import scripts.eval_harness.provenance_sha as prov

    def _timeout(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd=["git"], timeout=5)

    monkeypatch.setattr(prov.subprocess, "run", _timeout)
    with pytest.raises(SystemExit, match="git"):
        validate_live_head_sha(_fake_40())


def test_vlm6_r2_d02_is_inside_rc128_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """is-inside-work-tree rc=128 (any git fatal) must refuse."""
    import scripts.eval_harness.provenance_sha as prov

    def _rc128(cmd, *_a, **_k):
        if "--is-inside-work-tree" in cmd:
            return _Completed(128, "", "fatal: not a git repository")
        return _Completed(0, _fake_40() + "\n")

    monkeypatch.setattr(prov.subprocess, "run", _rc128)
    with pytest.raises(SystemExit, match="git"):
        validate_live_head_sha(_fake_40())


def test_vlm6_r2_d02_is_inside_empty_stdout_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """is-inside-work-tree stdout empty (not 'true') must refuse."""
    import scripts.eval_harness.provenance_sha as prov

    def _empty(cmd, *_a, **_k):
        if "--is-inside-work-tree" in cmd:
            return _Completed(0, "")
        return _Completed(0, _fake_40() + "\n")

    monkeypatch.setattr(prov.subprocess, "run", _empty)
    with pytest.raises(SystemExit, match="git"):
        validate_live_head_sha(_fake_40())


def test_vlm6_r2_d02_bare_repo_refuses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Bare-repo cwd (is-inside-work-tree → 'false') must refuse fabricated hex."""
    import scripts.eval_harness.provenance_sha as prov

    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

    # Prefer real bare cwd; also cover via monkeypatch if init fails oddly.
    try:
        with pytest.raises(SystemExit, match="git|work.?tree|not a resolvable|not inside"):
            validate_live_head_sha(_fake_40(), git_cwd=bare)
    except TypeError:
        # cx3 may drop kwargs; pass via normalize directly if signature shrinks.
        from scripts.eval_harness.provenance_sha import normalize_head_sha

        with pytest.raises(SystemExit):
            normalize_head_sha(
                _fake_40(), empty_policy="refuse", verify_git=True, git_cwd=bare, label="--live-head-sha"
            )


def test_vlm6_r2_d02_missing_git_binary_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Genuine missing git binary (FileNotFoundError) still format-only accepts."""
    import scripts.eval_harness.provenance_sha as prov

    def _missing(*_a, **_k):
        raise FileNotFoundError(2, "No such file or directory", "git")

    monkeypatch.setattr(prov.subprocess, "run", _missing)
    fake = "deadbeef" * 5
    assert validate_live_head_sha(fake) == fake
    assert db.resolve_head_sha(fake) == fake


def test_vlm6_r2_d02_enoent_oserror_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OSError with errno=ENOENT is the same hard missing-binary signal."""
    import errno as errno_mod

    import scripts.eval_harness.provenance_sha as prov

    def _enoent(*_a, **_k):
        raise OSError(errno_mod.ENOENT, "No such file or directory", "git")

    monkeypatch.setattr(prov.subprocess, "run", _enoent)
    fake = "cafebabe" * 5
    assert validate_live_head_sha(fake) == fake


def test_vlm6_r2_d02_non_enoent_oserror_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-ENOENT OSError on first probe must refuse (aligned with verify probe)."""
    import scripts.eval_harness.provenance_sha as prov

    def _eacces(*_a, **_k):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(prov.subprocess, "run", _eacces)
    with pytest.raises(SystemExit, match="git|refuse|failed"):
        validate_live_head_sha(_fake_40())


def test_vlm6_r2_d02_verify_timeout_still_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second probe (rev-parse --verify) timeout hard-fails — asymmetric no longer."""
    import scripts.eval_harness.provenance_sha as prov

    def _run(cmd, *_a, **_k):
        if "--is-inside-work-tree" in cmd:
            return _Completed(0, "true\n")
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=5)

    monkeypatch.setattr(prov.subprocess, "run", _run)
    with pytest.raises(SystemExit, match="git|failed|refuse"):
        validate_live_head_sha(_fake_40())
