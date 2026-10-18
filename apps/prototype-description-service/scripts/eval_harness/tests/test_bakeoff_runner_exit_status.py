"""Bakeoff runner shell must fail closed on fetch or scorer gate failures."""

from __future__ import annotations

import os
import stat
import subprocess
import json
from pathlib import Path

from scripts.eval_harness.bakeoff_runner import CandidatePlan, emit_shell


def _plan(tmp_path: Path, candidate_id: str) -> CandidatePlan:
    model_dir = tmp_path / candidate_id
    out_dir = tmp_path / "out"
    return CandidatePlan(
        candidate_id=candidate_id,
        model_id=f"model-{candidate_id}",
        serve_argv=(
            "llama-server",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--model",
            str(model_dir / "model.gguf"),
            "--mmproj",
            str(model_dir / "mmproj.gguf"),
            "-c",
            "4096",
            "--image-max-tokens",
            "512",
            "-np",
            "1",
        ),
        run_argv=(
            "python3",
            "-m",
            "scripts.eval_harness.bakeoff",
            "--endpoint",
            "http://127.0.0.1:8000",
            "--model-id",
            f"model-{candidate_id}",
            "--model-version",
            "q4",
            "--manifest",
            "scripts/eval_harness/corpus646-interleave-manifest-20260716.json",
            "--prompt-variant",
            "baseline",
            "--two-pass",
            "--out",
            str(out_dir / f"run-bakeoff-{candidate_id}.json"),
            "--warmup",
            "1",
        ),
        out_path=str(out_dir / f"run-bakeoff-{candidate_id}.json"),
        total_gb=1.0,
        repo="repo/example",
        revision="deadbeef",
        models_dir=str(tmp_path),
    )


def _write_stub(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_shell(
    tmp_path: Path,
    *,
    fail_token: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "python3-calls.jsonl"
    _write_stub(
        bin_dir / "llama-server",
        "#!/bin/sh\n"
        "exec sleep 30\n",
    )
    _write_stub(
        bin_dir / "curl",
        "#!/bin/sh\n"
        "exit 0\n",
    )
    _write_stub(
        bin_dir / "python3",
        "#!/usr/bin/python3\n"
        "import json, os, sys\n"
        f"log_path = {str(log_path)!r}\n"
        "argv = sys.argv[1:]\n"
        "with open(log_path, 'a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps(argv) + '\\n')\n"
        "fail = os.environ.get('BAKEOFF_RUNNER_FAIL_TOKEN')\n"
        "if argv[:1] == ['-c']:\n"
        "    print('0.1')\n"
        "    raise SystemExit(0)\n"
        "joined = ' '.join(argv)\n"
        "if '-m scripts.eval_harness.bakeoff' in joined:\n"
        "    out = argv[argv.index('--out') + 1]\n"
        "    if not (fail and fail in joined):\n"
        "        os.makedirs(os.path.dirname(out), exist_ok=True)\n"
        "        with open(out, 'w', encoding='utf-8') as handle:\n"
        "            handle.write('{}\\n')\n"
        "if '-m scripts.eval_harness.build_bakeoff_report' in joined:\n"
        "    raise SystemExit(0)\n"
        "if fail and fail in joined:\n"
        "    raise SystemExit(1)\n"
        "raise SystemExit(0)\n",
    )
    shell_path = tmp_path / "planned.sh"
    shell_path.write_text(emit_shell([_plan(tmp_path, "good"), _plan(tmp_path, "bad")], incumbent_runs={}), encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    if fail_token is not None:
        env["BAKEOFF_RUNNER_FAIL_TOKEN"] = fail_token
    proc = subprocess.run(
        ["bash", str(shell_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    calls = []
    if log_path.exists():
        calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return proc, calls


def test_emit_shell_exits_nonzero_when_one_of_two_fetch_legs_fails(tmp_path: Path) -> None:
    proc, _calls = _run_shell(tmp_path, fail_token="run-bakeoff-bad.json")
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, combined
    assert "candidate bad fetch FAILED" in combined


def test_emit_shell_exits_nonzero_when_score_gate_fails_after_fetch(tmp_path: Path) -> None:
    bad_run = str((tmp_path / "out" / "run-bakeoff-bad.json").resolve())
    proc, calls = _run_shell(tmp_path, fail_token=f"--run-record {bad_run}")
    combined = proc.stdout + proc.stderr
    score_calls = [call for call in calls if call[:3] == ["-m", "scripts.eval_harness.cli", "score"]]
    assert any(
        call[-6:] == [
            "--rubric-gate",
            "enforce",
            "--allow-refused",
            "detection",
            "--allow-refused",
            "identification",
        ]
        for call in score_calls
    ), score_calls
    assert proc.returncode != 0, combined
