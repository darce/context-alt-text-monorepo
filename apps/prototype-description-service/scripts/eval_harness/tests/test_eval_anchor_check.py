"""Root eval-anchor-check target must bind every frozen anchor in one call."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path


_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[5]


def _write_uv_stub(tmp_path: Path, *, fail_token: str | None = None) -> tuple[Path, Path]:
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    log_path = tmp_path / "uv-invocations.jsonl"
    uv = stub_dir / "uv"
    stub = (
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"log_path = {str(log_path)!r}\n"
        "argv = sys.argv[1:]\n"
        "with open(log_path, 'a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps(argv) + '\\n')\n"
        "fail_token = os.environ.get('EVAL_ANCHOR_CHECK_FAIL_TOKEN')\n"
        "if fail_token and fail_token in ' '.join(argv):\n"
        "    sys.stderr.write(fail_token + '\\n')\n"
        "    raise SystemExit(1)\n"
    )
    uv.write_text(stub, encoding="utf-8")
    uv.chmod(uv.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub_dir, log_path


_VERIFIER_COMMANDS = ("score", "score-face", "draw-eval-split")
_FAIL_TOKENS = (
    "S2A-determinism-anchor-run",
    "S2A-face-determinism-anchor-run",
    "S1-sealed-eval-split",
)


def _run_eval_anchor_check(
    tmp_path: Path,
    *,
    fail_token: str | None = None,
    makefile: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    stub_dir, log_path = _write_uv_stub(tmp_path, fail_token=fail_token)
    env = os.environ.copy()
    env["PATH"] = f"{stub_dir}{os.pathsep}{env.get('PATH', '')}"
    if fail_token is not None:
        env["EVAL_ANCHOR_CHECK_FAIL_TOKEN"] = fail_token
    cmd = ["make", "-C", str(_REPO_ROOT)]
    if makefile is not None:
        cmd.extend(["-f", str(makefile)])
    cmd.append("eval-anchor-check")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
    )
    calls = []
    if log_path.exists():
        calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return proc, calls


def _verifier_commands(calls: list[list[str]]) -> list[str]:
    found: list[str] = []
    for call in calls:
        try:
            idx = call.index("scripts.eval_harness.cli")
        except ValueError:
            continue
        if idx + 1 < len(call):
            found.append(call[idx + 1])
    return found


def _assert_injected_failure_was_honored(
    proc: subprocess.CompletedProcess[str],
    calls: list[list[str]],
    fail_token: str,
) -> None:
    combined = proc.stdout + proc.stderr
    assert _verifier_commands(calls) == list(_VERIFIER_COMMANDS), (
        f"{fail_token}: expected all three verifiers invoked, got {_verifier_commands(calls)!r}:\n{combined}"
    )
    assert fail_token in combined, (
        f"{fail_token} was not surfaced in verifier output:\n{combined}"
    )
    assert proc.returncode != 0, f"{fail_token} failure was ignored:\n{combined}"


def test_eval_anchor_check_invokes_the_three_literal_verifiers(tmp_path: Path) -> None:
    proc, calls = _run_eval_anchor_check(tmp_path)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert calls == [
        [
            "run",
            "--extra",
            "dev",
            "python",
            "-m",
            "scripts.eval_harness.cli",
            "score",
            "--manifest",
            "../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-manifest-20260811.json",
            "--run-record",
            "../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811.json",
            "--check-determinism",
            "--expect-report",
            "../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811-report.json",
            "--rubric-gate",
            "skip",
            "--freeze-certification",
        ],
        [
            "run",
            "--extra",
            "dev",
            "python",
            "-m",
            "scripts.eval_harness.cli",
            "score-face",
            "--manifest",
            "../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-manifest-20260811.json",
            "--run-record",
            "../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811.json",
            "--check-determinism",
            "--expect-report",
            "../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811-face-report.json",
            "--freeze-certification",
        ],
        [
            "run",
            "--extra",
            "dev",
            "python",
            "-m",
            "scripts.eval_harness.cli",
            "draw-eval-split",
            "--manifest",
            "scene/tests/seed/golden.json",
            "--out",
            "../../docs/tasks/vlm/bakeoff-results/S1-sealed-eval-split-20260818.json",
            "--seed",
            "vlm6-s1-sealed-eval-split-20260818",
            "--held-out-fraction",
            "0.5",
            "--draw-timestamp",
            "2026-08-18T00:00:00Z",
            "--partition-provenance",
            "per-image roster labels on the VLM-2A fixture corpus (golden.json v3); no cluster partition, disjointness computed on present_identities only",
            "--exposure-note",
            "golden.json v3 (37 entries) curated pre-split: present_identities non-empty on 34/37 (empty: media_id 27,34,35), face_boxes=0/37, must_right=34/37, annotation_mode=roster_only; held_out half is model-held-out but NOT selection-held-out",
            "--exposure-note",
            "curation tenant 4ddf8f36 (LocalWP :10018) live with clustered uploads pre-draw",
            "--exposure-note",
            "determinism-anchor runs S0/S2A (bakeoff-results/) scored the 37 pre-split",
            "--check",
        ],
    ]


def test_eval_anchor_check_fails_when_any_single_verifier_fails(tmp_path: Path) -> None:
    for fail_token in _FAIL_TOKENS:
        leg_path = tmp_path / fail_token
        leg_path.mkdir()
        proc, calls = _run_eval_anchor_check(leg_path, fail_token=fail_token)
        _assert_injected_failure_was_honored(proc, calls, fail_token)


_VERIFIER_SHELL = (
    (
        "cd apps/prototype-description-service && "
        "UV_CACHE_DIR=/tmp/acx-eval-anchor-uv-cache uv run --extra dev python -m "
        "scripts.eval_harness.cli score "
        "--manifest ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-manifest-20260811.json "
        "--run-record ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811.json "
        "--check-determinism "
        "--expect-report ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811-report.json "
        "--rubric-gate skip "
        "--freeze-certification"
    ),
    (
        "cd apps/prototype-description-service && "
        "UV_CACHE_DIR=/tmp/acx-eval-anchor-uv-cache uv run --extra dev python -m "
        "scripts.eval_harness.cli score-face "
        "--manifest ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-manifest-20260811.json "
        "--run-record ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811.json "
        "--check-determinism "
        "--expect-report ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811-face-report.json "
        "--freeze-certification"
    ),
    (
        "cd apps/prototype-description-service && "
        "UV_CACHE_DIR=/tmp/acx-eval-anchor-uv-cache uv run --extra dev python -m "
        "scripts.eval_harness.cli draw-eval-split "
        "--manifest scene/tests/seed/golden.json "
        "--out ../../docs/tasks/vlm/bakeoff-results/S1-sealed-eval-split-20260818.json "
        "--seed vlm6-s1-sealed-eval-split-20260818 "
        "--held-out-fraction 0.5 "
        "--draw-timestamp 2026-08-18T00:00:00Z "
        "--partition-provenance "
        '"per-image roster labels on the VLM-2A fixture corpus (golden.json v3); '
        'no cluster partition, disjointness computed on present_identities only" '
        "--exposure-note "
        '"golden.json v3 (37 entries) curated pre-split: present_identities non-empty on 34/37 '
        '(empty: media_id 27,34,35), face_boxes=0/37, must_right=34/37, annotation_mode=roster_only; '
        'held_out half is model-held-out but NOT selection-held-out" '
        "--exposure-note "
        '"curation tenant 4ddf8f36 (LocalWP :10018) live with clustered uploads pre-draw" '
        "--exposure-note "
        '"determinism-anchor runs S0/S2A (bakeoff-results/) scored the 37 pre-split" '
        "--check"
    ),
)


def _write_scratch_makefile(tmp_path: Path, *, mode: str) -> Path:
    path = tmp_path / f"{mode}.mk"
    score, face, split = _VERIFIER_SHELL
    if mode == "absent":
        path.write_text(".PHONY: unrelated\nunrelated:\n\t@true\n", encoding="utf-8")
    elif mode == "stop_at_first":
        path.write_text(
            ".PHONY: eval-anchor-check\n"
            "eval-anchor-check:\n"
            f"\t@{score}\n"
            f"\t@{face}\n"
            f"\t@{split}\n",
            encoding="utf-8",
        )
    elif mode == "swallow":
        path.write_text(
            ".PHONY: eval-anchor-check\n"
            "eval-anchor-check:\n"
            f"\t@({score}) || true\n"
            f"\t@({face}) || true\n"
            f"\t@({split}) || true\n",
            encoding="utf-8",
        )
    else:
        raise ValueError(mode)
    return path


def test_eval_anchor_check_fail_contract_rejects_absent_target(tmp_path: Path) -> None:
    makefile = _write_scratch_makefile(tmp_path, mode="absent")
    fail_token = _FAIL_TOKENS[0]
    leg = tmp_path / "absent-leg"
    leg.mkdir()
    proc, calls = _run_eval_anchor_check(leg, fail_token=fail_token, makefile=makefile)
    combined = proc.stdout + proc.stderr
    assert _verifier_commands(calls) == []
    assert fail_token not in combined
    assert proc.returncode != 0
    assert "No rule to make target" in combined


def test_eval_anchor_check_fail_contract_rejects_stop_at_first(tmp_path: Path) -> None:
    makefile = _write_scratch_makefile(tmp_path, mode="stop_at_first")
    fail_token = _FAIL_TOKENS[0]
    leg = tmp_path / "stop-leg"
    leg.mkdir()
    proc, calls = _run_eval_anchor_check(leg, fail_token=fail_token, makefile=makefile)
    combined = proc.stdout + proc.stderr
    assert _verifier_commands(calls) == ["score"]
    assert fail_token in combined
    assert proc.returncode != 0


def test_eval_anchor_check_fail_contract_rejects_swallowed_exit(tmp_path: Path) -> None:
    makefile = _write_scratch_makefile(tmp_path, mode="swallow")
    fail_token = _FAIL_TOKENS[0]
    leg = tmp_path / "swallow-leg"
    leg.mkdir()
    proc, calls = _run_eval_anchor_check(leg, fail_token=fail_token, makefile=makefile)
    combined = proc.stdout + proc.stderr
    assert _verifier_commands(calls) == list(_VERIFIER_COMMANDS)
    assert fail_token in combined
    assert proc.returncode == 0
