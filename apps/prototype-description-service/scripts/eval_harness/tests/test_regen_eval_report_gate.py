"""S2R4-03 — regen_eval_report.py must not greenwash CLI exits (TEST-15).

Drives the real repo-root script end to end. Refusal (3) and partial (1) are
distinct: different messages, different outcomes, and publishing a refused
report requires --allow-refused (default off). An unrecognized nonzero exit
is not swallowed.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[5]
_REGEN_SCRIPT = _REPO_ROOT / "scripts" / "regen_eval_report.py"

_LINEAGE = {
    "labeler_id": "test-labeler",
    "batch_id": "test-batch",
    "capture_session_id": "test-session",
    "pass_index": 0,
    "labeled_at": "2026-08-14T00:00:00Z",
    "tool_version": "test",
    "saw_machine_proposals": False,
    "label_source": "operator_blind",
    "decision": "named",
    "confidence": "high",
    "arbitration_of": None,
}


def _load_regen():
    spec = importlib.util.spec_from_file_location(
        "regen_eval_report_under_test", _REGEN_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _roster_only_manifest() -> dict:
    return {
        "manifest_version": 3,
        "annotation_mode": "roster_only",
        # 2nd roster member so easy_wrong can be non-empty — roster_only mode
        # requires must_right/easy_wrong to be roster subsets, and an empty
        # easy_wrong trips the branch-only empty-rubric gate
        # (SCORE_GATE_PREFIX_EMPTY_RUBRIC, cli.py). VLM6-DELTA-14.
        "roster": ["Alice Example", "Bob Distractor"],
        "entries": [
            {
                "path": "mock_images/alice.jpg",
                "sha256": "a" * 64,
                "media_id": 1,
                "face_count": 1,
                "present_identities": ["Alice Example"],
                "context_pack": {"title": "t"},
                "base_caption": "Alice Example.",
                "must_right": ["Alice Example"],
                "easy_wrong": ["Bob Distractor"],
                "policy": {"recognition_enabled": True},
                "provenance": {"source": "fixture", "license": "fixture"},
                "face_boxes": [
                    {
                        "x": 0.5,
                        "y": 0.4,
                        "w": 0.2,
                        "h": 0.3,
                        "name": "Alice Example",
                        "source": "operator",
                        "lineage": _LINEAGE,
                    }
                ],
            }
        ],
    }


def _overshoot_record() -> dict:
    return {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "base_url": "x",
            "head_sha": "0" * 40,
            "started_at": "t",
        },
        "items": [
            {
                "media_id": 1,
                "path": "mock_images/alice.jpg",
                "describe": {
                    "alt_text_draft": "Alice Example by the pool.",
                    "visual_facts": {"objects": []},
                },
                # Dict identity rows (greenfield rejects bare strings —
                # VLM6-PANEL6L-SR-01); shape mirrors fusion_runner.py::_identity_rows.
                "identities": [{"name": "Alice Example", "unpositioned": True}],
                "face_count": 3,
                "error": None,
            }
        ],
    }


def _failed_item_record() -> dict:
    return {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "0" * 64,
            "base_url": "x",
            "head_sha": "f" * 40,
            "started_at": "t",
        },
        "items": [
            {
                "media_id": 1,
                "path": "mock_images/alice.jpg",
                "describe": None,
                "identities": [],
                "face_count": 0,
                "error": "FileNotFoundError: missing",
                "latency_s": None,
            }
        ],
    }


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _real_manifest_sha(manifest_path: Path) -> str:
    """Real sha256 of a manifest already on disk (VLM6-DELTA-15).

    Placeholder provenance shas (``"m" * 64``) trip a branch-only
    manifest-drift gate (cli.py: "manifest_matches_fetch=false") ahead of the
    failed-items / refused-metrics gates these tests target. Mirrors the
    working pattern in test_manifest_invariants.py.
    """
    from scripts.eval_harness.cli import _manifest_sha as _cli_manifest_sha
    from scripts.eval_harness.manifest import load_manifest

    manifest = load_manifest(str(manifest_path), skip_hash_verification=True)
    return _cli_manifest_sha(manifest)


_REAL_CLI_ENV = {"ACX_EVAL_PYTHON": sys.executable}


def _run_regen(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.pop("ACX_EVAL_PYTHON", None)
    merged.pop("ACX_EVAL_SCORE_PYTHON", None)
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(_REGEN_SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=merged,
    )


def _real_inputs(tmp_path: Path, record: dict, *, manifest_doc: dict | None = None) -> tuple[Path, Path, Path, Path]:
    manifest = _write_json(
        tmp_path / "manifest.json",
        manifest_doc if manifest_doc is not None else _roster_only_manifest(),
    )
    # VLM6-DELTA-15: stamp the record's provenance with the manifest's real
    # sha256 before writing it — a stale placeholder trips the manifest-drift
    # gate ahead of whichever gate each test actually targets.
    record = dict(record)
    record["provenance"] = {
        **record["provenance"],
        "manifest_sha256": _real_manifest_sha(manifest),
    }
    run_record = _write_json(tmp_path / "run-record.json", record)
    out_json = tmp_path / "dest-report.json"
    out_md = tmp_path / "dest-report.md"
    return run_record, manifest, out_json, out_md


def _assert_not_published(out_json: Path, out_md: Path, sentinel: str | None) -> None:
    if sentinel is None:
        assert not out_json.is_file(), "refused/partial/unrecognized must not publish JSON"
        assert not out_md.is_file(), "refused/partial/unrecognized must not publish MD"
        return
    assert out_json.read_text(encoding="utf-8") == sentinel
    assert out_md.read_text(encoding="utf-8") == sentinel


# ---------------------------------------------------------------------------
# Real score CLI (exit 3 refused, exit 1 partial)
# ---------------------------------------------------------------------------


def test_real_cli_refused_does_not_publish_and_exits_3(tmp_path: Path) -> None:
    """VLM-2C class: full corpus, both metrics refused → exit 3, hold dest.

    The pre-fix script printed 'partial-corpus' and returned 0 after
    publishing. That swallow must stay red.

    VLM6-DELTA-15: "both metrics refused" requires the unboxed manifest —
    a boxed roster_only manifest leaves identification scored, so a
    single-image corpus trips category-vacuity (undersized sample, exit 1)
    ahead of raise_if_unconsented_refusals (exit 3). Unboxed makes
    identification refuse too (identification_refuses_unboxed_identity_claims),
    matching this test's own "both metrics refused" premise.

    VLM6-GATE-INT-01: the category-vacuity gate only suppresses reasons that
    restate a refused identification/detection now, so
    ``_unboxed_roster_only_manifest``/``_unboxed_overshoot_record`` also make
    sample_size/placement/fabricated_fact genuinely non-vacuous — exit 3 is
    reached on its own merits, not via a blanket per-refusal skip.
    """
    run_record, manifest, out_json, out_md = _real_inputs(
        tmp_path, _unboxed_overshoot_record(), manifest_doc=_unboxed_roster_only_manifest()
    )
    sentinel = '{"sentinel":"unpublished-refused"}'
    out_json.write_text(sentinel, encoding="utf-8")
    out_md.write_text(sentinel, encoding="utf-8")
    proc = _run_regen(
        [
            "--run-record",
            str(run_record),
            "--manifest",
            str(manifest),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        cwd=_REPO_ROOT,
        env=_REAL_CLI_ENV,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 3, combined
    assert "refused metrics" in combined
    assert "partial-corpus" not in combined
    _assert_not_published(out_json, out_md, sentinel)


def test_real_cli_refused_allow_refused_publishes_and_still_exits_3(
    tmp_path: Path,
) -> None:
    """Consent publishes the refused report but must not greenwash to exit 0.

    VLM6-DELTA-15: unboxed manifest — see the sibling exits-3 test's
    docstring for why "both metrics refused" needs the unboxed fixture.
    VLM6-GATE-INT-01: same non-vacuous 5-entry fixture as that sibling.
    """
    run_record, manifest, out_json, out_md = _real_inputs(
        tmp_path, _unboxed_overshoot_record(), manifest_doc=_unboxed_roster_only_manifest()
    )
    proc = _run_regen(
        [
            "--run-record",
            str(run_record),
            "--manifest",
            str(manifest),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--allow-refused",
        ],
        cwd=_REPO_ROOT,
        env=_REAL_CLI_ENV,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 3, combined
    assert "refused metrics" in combined
    assert "--allow-refused" in combined
    assert "partial-corpus" not in combined
    assert out_json.is_file()
    assert out_md.is_file()
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert report["faces"]["detection"]["refused"] is True
    assert "REFUSED (detection_refuses_roster_only)" in out_md.read_text(
        encoding="utf-8"
    )


def test_real_cli_partial_does_not_publish_and_exits_1(tmp_path: Path) -> None:
    """failed>0 is the partial-corpus gate; it is not a refused-metrics exit."""
    run_record, manifest, out_json, out_md = _real_inputs(
        tmp_path, _failed_item_record()
    )
    sentinel = '{"sentinel":"unpublished-partial"}'
    out_json.write_text(sentinel, encoding="utf-8")
    out_md.write_text(sentinel, encoding="utf-8")
    proc = _run_regen(
        [
            "--run-record",
            str(run_record),
            "--manifest",
            str(manifest),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        cwd=_REPO_ROOT,
        env=_REAL_CLI_ENV,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "partial-corpus" in combined
    assert "refused metrics" not in combined
    _assert_not_published(out_json, out_md, sentinel)


def test_real_cli_partial_not_overridden_by_allow_refused(tmp_path: Path) -> None:
    """--allow-refused is publisher consent for exit 3 only, not for exit 1."""
    run_record, manifest, out_json, out_md = _real_inputs(
        tmp_path, _failed_item_record()
    )
    proc = _run_regen(
        [
            "--run-record",
            str(run_record),
            "--manifest",
            str(manifest),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--allow-refused",
        ],
        cwd=_REPO_ROOT,
        env=_REAL_CLI_ENV,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "partial-corpus" in combined
    assert not out_json.is_file()
    assert not out_md.is_file()


# ---------------------------------------------------------------------------
# Interpreter override (FIR-12-BR-67)
# ---------------------------------------------------------------------------


def test_invalid_override_errors_and_does_not_fall_back(tmp_path: Path) -> None:
    """A set-but-unusable ACX_EVAL_PYTHON must not fall back to .venv."""
    repo = _scratch_repo(tmp_path)
    argv_log = _install_stub_python(repo)
    run_record, manifest, out_json, out_md = _stub_paths(repo)
    junk = tmp_path / "neutral-helper.bin"
    junk.write_text("not an interpreter\n", encoding="utf-8")
    proc = _run_regen(
        [
            "--run-record",
            str(run_record),
            "--manifest",
            str(manifest),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        cwd=repo,
        env={"ACX_EVAL_PYTHON": str(junk), "STUB_SCORE_EXIT": "0"},
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 2, combined
    assert "invalid ACX_EVAL_PYTHON" in combined
    assert "not an executable file" in combined
    assert str(junk) in combined
    assert "missing service venv python" not in combined
    assert not argv_log.is_file()


def test_unset_override_missing_venv_reports_missing_cli(tmp_path: Path) -> None:
    repo = _scratch_repo(tmp_path)
    (repo / "apps" / "prototype-description-service").mkdir(parents=True)
    run_record, manifest, out_json, out_md = _stub_paths(repo)
    proc = _run_regen(
        [
            "--run-record",
            str(run_record),
            "--manifest",
            str(manifest),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        cwd=repo,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 2, combined
    assert "CLI did not write expected reports" in combined
    assert "environment/startup failure, not a corpus outcome" in combined
    assert "invalid ACX_EVAL_PYTHON" not in combined


def test_resolve_eval_python_override_wins_without_venv(tmp_path: Path) -> None:
    regen = _load_regen()
    chosen = regen.resolve_eval_python(
        tmp_path, environ={"ACX_EVAL_PYTHON": sys.executable}
    )
    assert chosen == Path(sys.executable)


def test_resolve_eval_python_accepts_neutrally_named_executable(
    tmp_path: Path,
) -> None:
    regen = _load_regen()
    helper = tmp_path / "worker"
    helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    helper.chmod(helper.stat().st_mode | stat.S_IXUSR)
    chosen = regen.resolve_eval_python(
        tmp_path, environ={"ACX_EVAL_PYTHON": str(helper)}
    )
    assert chosen == helper


def test_resolve_eval_python_empty_override_is_invalid_not_missing(
    tmp_path: Path,
) -> None:
    regen = _load_regen()
    default = (
        tmp_path / "apps" / "prototype-description-service" / ".venv" / "bin" / "python"
    )
    default.parent.mkdir(parents=True, exist_ok=True)
    default.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    default.chmod(default.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(regen.EvalPythonError) as ei:
        regen.resolve_eval_python(tmp_path, environ={"ACX_EVAL_PYTHON": ""})
    message = str(ei.value)
    assert "invalid ACX_EVAL_PYTHON" in message
    assert "missing service venv python" not in message


# ---------------------------------------------------------------------------
# Scratch-repo stub CLI (unrecognized + clean + swallow walk-arounds)
# ---------------------------------------------------------------------------


def _scratch_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "scratch"
    repo.mkdir()
    subprocess.run(
        ["git", "init"], cwd=repo, check=True, capture_output=True, text=True
    )
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    return repo


def _install_stub_python(repo: Path) -> Path:
    python = repo / "apps" / "prototype-description-service" / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    argv_log = repo / "stub-argv.txt"
    python.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"Path({str(argv_log)!r}).write_text('\\n'.join(sys.argv), encoding='utf-8')\n"
        "args = sys.argv\n"
        "if '--run-record' in args:\n"
        "    record = Path(args[args.index('--run-record') + 1])\n"
        "    (record.parent / f'{record.stem}-report.json').write_text('{}\\n')\n"
        "    (record.parent / f'{record.stem}-report.md').write_text('# stub\\n')\n"
        "raise SystemExit(int(os.environ.get('STUB_SCORE_EXIT', '0')))\n",
        encoding="utf-8",
    )
    python.chmod(python.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return argv_log


def _install_env_override_stub(tmp_path: Path, *, exit_code: int) -> Path:
    """A resolvable ``ACX_EVAL_PYTHON`` override that never writes a report.

    FIR-12-BR-70: `resolve_eval_python` only checks that the override is an
    executable file — it cannot see whether the inner CLI subprocess will
    actually produce a report. This stub is deterministic stand-in for a
    real-but-broken interpreter (e.g. a system python lacking the eval
    package's third-party deps: verified repro is
    ``ACX_EVAL_PYTHON=/usr/bin/python3`` -> inner ``ModuleNotFoundError`` ->
    inner exit 1, no report written) without depending on any particular
    system python's installed package set.
    """
    stub = tmp_path / f"override-python-exit{exit_code}"
    stub.write_text(
        f"#!/usr/bin/env python3\nraise SystemExit({exit_code})\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub


_STUB_PUBLISHED_JSON = "{}\n"
_STUB_PUBLISHED_MD = "# stub\n"


def _assert_stub_published(out_json: Path, out_md: Path) -> None:
    """S2R5-15: a publish is the destination bytes, not dest.is_file()."""
    assert out_json.read_text(encoding="utf-8") == _STUB_PUBLISHED_JSON
    assert out_md.read_text(encoding="utf-8") == _STUB_PUBLISHED_MD


def _stub_paths(repo: Path) -> tuple[Path, Path, Path, Path]:
    run_record = _write_json(repo / "in" / "run.json", {"kind": "stub"})
    manifest = _write_json(repo / "in" / "man.json", {"kind": "stub"})
    out_json = repo / "out" / "report.json"
    out_md = repo / "out" / "report.md"
    return run_record, manifest, out_json, out_md


def test_unrecognized_cli_exit_is_not_swallowed_or_published(tmp_path: Path) -> None:
    """Exit 99 is not partial, not refused, not exit 0, and must not publish."""
    repo = _scratch_repo(tmp_path)
    argv_log = _install_stub_python(repo)
    run_record, manifest, out_json, out_md = _stub_paths(repo)
    sentinel = '{"sentinel":"hold-unrecognized"}'
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(sentinel, encoding="utf-8")
    out_md.write_text(sentinel, encoding="utf-8")
    proc = _run_regen(
        [
            "--run-record",
            str(run_record),
            "--manifest",
            str(manifest),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        cwd=repo,
        env={"STUB_SCORE_EXIT": "99"},
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 99, combined
    assert "unrecognized" in combined
    assert "partial-corpus" not in combined
    assert "refused metrics" not in combined
    _assert_not_published(out_json, out_md, sentinel)
    argv = argv_log.read_text(encoding="utf-8")
    assert "--allow-refused" not in argv


def test_stub_clean_score_publishes_and_exits_0(tmp_path: Path) -> None:
    repo = _scratch_repo(tmp_path)
    _install_stub_python(repo)
    run_record, manifest, out_json, out_md = _stub_paths(repo)
    proc = _run_regen(
        [
            "--run-record",
            str(run_record),
            "--manifest",
            str(manifest),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        cwd=repo,
        env={"STUB_SCORE_EXIT": "0"},
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    _assert_stub_published(out_json, out_md)


def test_allow_refused_is_not_forwarded_to_score_cli(tmp_path: Path) -> None:
    """Forwarding --allow-refused would make the CLI exit 0 and greenwash."""
    repo = _scratch_repo(tmp_path)
    argv_log = _install_stub_python(repo)
    run_record, manifest, out_json, out_md = _stub_paths(repo)
    proc = _run_regen(
        [
            "--run-record",
            str(run_record),
            "--manifest",
            str(manifest),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--allow-refused",
        ],
        cwd=repo,
        env={"STUB_SCORE_EXIT": "3"},
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 3, combined
    assert "refused metrics" in combined
    argv = argv_log.read_text(encoding="utf-8")
    assert "--allow-refused" not in argv
    _assert_stub_published(out_json, out_md)


# ---------------------------------------------------------------------------
# FIR-12-BR-70: env/startup failure must not alias the CLI's own
# publication-contract exit codes (broken interpreter vs. genuine partial
# corpus; silent no-op vs. genuine clean score)
# ---------------------------------------------------------------------------


def test_broken_real_interpreter_no_report_is_not_partial_corpus(
    tmp_path: Path,
) -> None:
    """A resolvable-but-broken ACX_EVAL_PYTHON must not exit 1.

    Exit 1 is this script's "partial corpus, never published" contract
    (module docstring). A broken real interpreter that crashes before
    writing anything is an environment failure, not a corpus-quality
    result, and must not collapse onto that code.
    """
    repo = _scratch_repo(tmp_path)
    (repo / "apps" / "prototype-description-service").mkdir(parents=True)
    run_record, manifest, out_json, out_md = _stub_paths(repo)
    broken = _install_env_override_stub(tmp_path, exit_code=1)
    proc = _run_regen(
        [
            "--run-record",
            str(run_record),
            "--manifest",
            str(manifest),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        cwd=repo,
        env={"ACX_EVAL_PYTHON": str(broken)},
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 2, combined
    assert "environment/startup failure" in combined
    assert not out_json.is_file()
    assert not out_md.is_file()


def test_interpreter_exits_0_without_report_is_not_clean_score(
    tmp_path: Path,
) -> None:
    """A silent no-op override (exit 0, no report) must not exit 0.

    Exit 0 is this script's "clean score, published" contract. An
    interpreter that exits 0 without writing anything is a broken
    environment, not a clean score, and there is nothing to publish.
    """
    repo = _scratch_repo(tmp_path)
    (repo / "apps" / "prototype-description-service").mkdir(parents=True)
    run_record, manifest, out_json, out_md = _stub_paths(repo)
    silent = _install_env_override_stub(tmp_path, exit_code=0)
    proc = _run_regen(
        [
            "--run-record",
            str(run_record),
            "--manifest",
            str(manifest),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        cwd=repo,
        env={"ACX_EVAL_PYTHON": str(silent)},
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 2, combined
    assert "environment/startup failure" in combined
    assert not out_json.is_file()
    assert not out_md.is_file()


def test_env_failures_are_distinguishable_from_genuine_partial_corpus(
    tmp_path: Path,
) -> None:
    """TEST-15 three-way pin: broken interpreter, silent no-op, and a real
    partial-corpus result from the real score CLI must not be confusable —
    the two env failures share exit 2 (neither is a corpus outcome) and
    both are distinct from the genuine partial-corpus exit 1.
    """
    repo = _scratch_repo(tmp_path)
    (repo / "apps" / "prototype-description-service").mkdir(parents=True)
    run_record, manifest, out_json, out_md = _stub_paths(repo)
    broken = _install_env_override_stub(tmp_path, exit_code=1)
    silent = _install_env_override_stub(tmp_path, exit_code=0)

    def _returncode(env: dict[str, str]) -> int:
        return _run_regen(
            [
                "--run-record",
                str(run_record),
                "--manifest",
                str(manifest),
                "--out-json",
                str(out_json),
                "--out-md",
                str(out_md),
            ],
            cwd=repo,
            env=env,
        ).returncode

    broken_code = _returncode({"ACX_EVAL_PYTHON": str(broken)})
    silent_code = _returncode({"ACX_EVAL_PYTHON": str(silent)})

    real_run_record, real_manifest, real_out_json, real_out_md = _real_inputs(
        tmp_path, _failed_item_record()
    )
    partial_code = _run_regen(
        [
            "--run-record",
            str(real_run_record),
            "--manifest",
            str(real_manifest),
            "--out-json",
            str(real_out_json),
            "--out-md",
            str(real_out_md),
        ],
        cwd=_REPO_ROOT,
        env=_REAL_CLI_ENV,
    ).returncode

    assert broken_code == 2
    assert silent_code == 2
    assert partial_code == 1
    assert partial_code not in (broken_code, silent_code)


# ---------------------------------------------------------------------------
# S2R5-11: identification withdrawal must appear in the publish audit trail
# ---------------------------------------------------------------------------


def test_identification_summary_sees_scored_to_refused_withdrawal(
    tmp_path: Path,
) -> None:
    """S2R5-11: detection_summary cannot see this transition; ident must."""
    regen = _load_regen()
    scored = tmp_path / "before.json"
    scored.write_text(
        json.dumps(
            {
                "faces": {
                    "detection": {"refused": True, "invariant": "detection_refuses_roster_only"},
                    "identification": {
                        "refused": False,
                        "precision": 0.5,
                        "recall": 0.0,
                        "per_identity": {"Ada": {"precision": None, "recall": 0.0}},
                    },
                },
                "provenance": {"score_manifest_sha256": "ab"},
            }
        ),
        encoding="utf-8",
    )
    before_det = regen.detection_summary(scored)
    before_ident = regen.identification_summary(scored)
    assert before_det["refused"] is True
    assert before_ident["refused"] is False
    assert before_ident["precision"] == 0.5
    assert before_ident["per_identity_rows"] == 1

    refused = tmp_path / "after.json"
    refused.write_text(
        json.dumps(
            {
                "faces": {
                    "detection": {"refused": True, "invariant": "detection_refuses_roster_only"},
                    "identification": {
                        "refused": True,
                        "invariant": "identification_refuses_unboxed_identity_claims",
                        "precision": None,
                        "recall": None,
                        "per_identity": {},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    after_ident = regen.identification_summary(refused)
    assert after_ident["refused"] is True
    assert after_ident["invariant"] == "identification_refuses_unboxed_identity_claims"
    assert after_ident["precision"] is None
    assert after_ident["per_identity_rows"] == 0
    # detection_summary of the after file is unchanged refused-detection —
    # it still cannot describe the identification withdrawal.
    after_det = regen.detection_summary(refused)
    assert after_det["refused"] is True
    assert after_det.get("precision") is None


def test_md_identification_line_reads_face_identification_section(
    tmp_path: Path,
) -> None:
    regen = _load_regen()
    md = tmp_path / "report.md"
    md.write_text(
        "## Face detection\n\n"
        "- REFUSED (detection_refuses_roster_only): lower bound\n\n"
        "## Face identification (named assertions)\n\n"
        "- micro precision: 0.500 recall: 0.000\n",
        encoding="utf-8",
    )
    assert regen.md_detection_line(md) == (
        "- REFUSED (detection_refuses_roster_only): lower bound"
    )
    assert regen.md_identification_line(md) == (
        "- micro precision: 0.500 recall: 0.000"
    )


def _unboxed_roster_only_manifest(n: int = 5) -> dict:
    """``n``-entry boxless corpus — identification (and roster_only detection)
    still refuse, but sample_size/placement/fabricated_fact are genuinely
    non-vacuous (VLM6-GATE-INT-01).

    The CLI's category-vacuity gate (cli.py) now suppresses only the reasons
    that are pure restatements of a refused identification/detection — every
    other category-vacuity reason still hard-fails. The old single-entry,
    no-facts fixture relied on the previous, over-broad gate
    (``not ident_block.get("refused")``) skipping the whole check whenever
    identification refused, which silently hid an undersized sample and
    vacuous placement/fabricated_fact axes. This fixture clears those for
    real: ``n=5`` entries clear ``SCORE_PASS_MIN_SCORED_IMAGES``; every entry
    carries a ``spatial_facts`` "foreground" fact whose phrase the paired
    ``_unboxed_overshoot_record`` caption states, giving
    ``placement.claims > 0``; every entry carries a ``reference_facts``
    FALSE-polarity trap the caption never states, giving ``fabricated_fact``
    a real (untripped) rate instead of ``None``. Only used by the
    "both metrics refused" tests below — the boxed ``_roster_only_manifest``
    stays a single entry for the tests that target the partial-corpus /
    failed-item paths instead.
    """
    import copy

    template = _roster_only_manifest()["entries"][0]
    entries = []
    for i in range(1, n + 1):
        entry = copy.deepcopy(template)
        entry["media_id"] = i
        entry["path"] = f"mock_images/alice{i}.jpg"
        entry["sha256"] = f"{i:064x}"
        entry["face_boxes"] = []
        entry["spatial_facts"] = [
            {
                "subject": "Alice Example",
                "relation": "foreground",
                "phrases": ["in the foreground"],
            }
        ]
        entry["reference_facts"] = [
            {
                "text": "wearing a red hat",
                "kind": "attribute",
                "polarity": "false",
                "phrases": ["red hat"],
            }
        ]
        entries.append(entry)
    payload = _roster_only_manifest()
    payload["entries"] = entries
    return payload


def _unboxed_overshoot_record(n: int = 5) -> dict:
    """``n``-item record pairing ``_unboxed_roster_only_manifest`` (VLM6-GATE-INT-01).

    Mirrors ``_overshoot_record`` per item but states "in the foreground" —
    the phrase every unboxed manifest entry's ``spatial_facts`` carries — so
    ``placement.claims > 0`` for real.
    """
    import copy

    template = _overshoot_record()["items"][0]
    items = []
    for i in range(1, n + 1):
        item = copy.deepcopy(template)
        item["media_id"] = i
        item["path"] = f"mock_images/alice{i}.jpg"
        item["describe"]["alt_text_draft"] = "Alice Example in the foreground by the pool."
        items.append(item)
    record = _overshoot_record()
    record["items"] = items
    return record


def test_real_cli_allow_refused_prints_identification_audit_trail(
    tmp_path: Path,
) -> None:
    """Publisher stdout must show the scored→refused identification change."""
    manifest = _write_json(tmp_path / "manifest.json", _unboxed_roster_only_manifest())
    # VLM6-DELTA-15: same manifest-drift stamping as _real_inputs — this test
    # builds its own record inline instead of going through that helper.
    # VLM6-GATE-INT-01: unboxed manifest is now 5 entries with real
    # spatial_facts/reference_facts (see _unboxed_roster_only_manifest), so
    # the paired record must be the matching multi-item one.
    record = _unboxed_overshoot_record()
    record["provenance"] = {
        **record["provenance"],
        "manifest_sha256": _real_manifest_sha(manifest),
    }
    run_record = _write_json(tmp_path / "run-record.json", record)
    out_json = tmp_path / "dest-report.json"
    out_md = tmp_path / "dest-report.md"
    leftover = {
        "faces": {
            "detection": {"refused": True, "invariant": "detection_refuses_roster_only"},
            "identification": {
                "refused": False,
                "precision": None,
                "recall": 0.0,
                "per_identity": {"Ada": {}},
            },
        }
    }
    out_json.write_text(json.dumps(leftover), encoding="utf-8")
    out_md.write_text(
        "## Face detection\n\n- REFUSED (detection_refuses_roster_only): x\n\n"
        "## Face identification (named assertions)\n\n"
        "- micro precision: null recall: 0.000\n",
        encoding="utf-8",
    )
    proc = _run_regen(
        [
            "--run-record",
            str(run_record),
            "--manifest",
            str(manifest),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--allow-refused",
        ],
        cwd=_REPO_ROOT,
        env=_REAL_CLI_ENV,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 3, combined
    assert "BEFORE_IDENT_JSON" in proc.stdout
    assert "AFTER_IDENT_JSON" in proc.stdout
    assert "BEFORE_IDENT_MD" in proc.stdout
    assert "AFTER_IDENT_MD" in proc.stdout
    before_line = next(
        line for line in proc.stdout.splitlines() if line.startswith("BEFORE_IDENT_JSON ")
    )
    after_line = next(
        line for line in proc.stdout.splitlines() if line.startswith("AFTER_IDENT_JSON ")
    )
    before = json.loads(before_line.split(" ", 1)[1])
    after = json.loads(after_line.split(" ", 1)[1])
    assert before["refused"] is False
    assert before["per_identity_rows"] == 1
    assert after["refused"] is True
    assert after["invariant"] == "identification_refuses_unboxed_identity_claims"
    assert "REFUSED" in proc.stdout.split("AFTER_IDENT_MD ", 1)[1].splitlines()[0]


# ---------------------------------------------------------------------------
# Classifier: reason string is selected by the numeric exit, not a guess
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "allow", "publish", "exit_code", "reason", "must_have", "must_not"),
    [
        (0, False, True, 0, "clean-score", "clean score", "partial-corpus"),
        (1, False, False, 1, "partial-corpus", "partial-corpus", "refused metrics"),
        (1, True, False, 1, "partial-corpus", "partial-corpus", "refused metrics"),
        (3, False, False, 3, "refused-metrics", "refused metrics", "partial-corpus"),
        (3, True, True, 3, "refused-metrics", "refused metrics", "partial-corpus"),
        (2, False, False, 2, "cli-usage", "usage/argparse", "partial-corpus"),
        (7, False, False, 7, "unrecognized-cli-exit", "unrecognized", "partial-corpus"),
        (7, True, False, 7, "unrecognized-cli-exit", "unrecognized", "partial-corpus"),
    ],
)
def test_classify_score_exit_reason_comes_from_code(
    code: int,
    allow: bool,
    publish: bool,
    exit_code: int,
    reason: str,
    must_have: str,
    must_not: str,
) -> None:
    regen = _load_regen()
    decision = regen.classify_score_exit(code, allow_refused=allow)
    assert decision.publish is publish
    assert decision.exit_code == exit_code
    assert decision.reason == reason
    assert must_have in decision.message
    assert must_not not in decision.message


# ---------------------------------------------------------------------------
# Interpreter resolution (lane-worktree hermeticity)
# ---------------------------------------------------------------------------


def test_score_interpreter_falls_back_to_the_running_interpreter(
    tmp_path: Path,
) -> None:
    """A linked worktree has no service-local .venv and must still score.

    The venv lives in the root worktree only, so hardcoding it made every
    real-CLI test in this module abort with exit 2 in any lane worktree —
    the gate stopped testing the publication contract and started testing
    whether the checkout happened to be the one that ran `uv sync`.
    """
    mod = _load_regen()
    repo = tmp_path / "no-venv"
    (repo / "apps" / "prototype-description-service").mkdir(parents=True)

    resolved = mod.score_interpreter(repo)

    assert resolved == Path(sys.executable)


def test_score_interpreter_prefers_the_service_venv_over_the_caller(
    tmp_path: Path,
) -> None:
    """When the venv exists it stays authoritative — the stub tests rely on it."""
    mod = _load_regen()
    repo = _scratch_repo(tmp_path)
    _install_stub_python(repo)

    resolved = mod.score_interpreter(repo)

    assert resolved == repo / "apps" / "prototype-description-service" / ".venv" / "bin" / "python"


def test_score_interpreter_honours_an_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Operators pinning a specific interpreter must beat both discoveries."""
    mod = _load_regen()
    repo = _scratch_repo(tmp_path)
    _install_stub_python(repo)
    pinned = tmp_path / "pinned-python"
    pinned.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pinned.chmod(pinned.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("ACX_EVAL_SCORE_PYTHON", str(pinned))

    assert mod.score_interpreter(repo) == pinned


@pytest.mark.parametrize('value', ['', '/missing/score-python'])
def test_score_interpreter_rejects_invalid_score_override(tmp_path, monkeypatch, value):
    mod = _load_regen()
    monkeypatch.delenv('ACX_EVAL_PYTHON', raising=False)
    monkeypatch.setenv('ACX_EVAL_SCORE_PYTHON', value)
    with pytest.raises(mod.EvalPythonError, match='invalid ACX_EVAL_SCORE_PYTHON'):
        mod.score_interpreter(tmp_path)


def test_score_interpreter_legacy_override_has_explicit_precedence(tmp_path, monkeypatch):
    mod = _load_regen()
    monkeypatch.setenv('ACX_EVAL_PYTHON', sys.executable)
    monkeypatch.setenv('ACX_EVAL_SCORE_PYTHON', '/missing/score-python')
    assert mod.score_interpreter(tmp_path) == Path(sys.executable)
