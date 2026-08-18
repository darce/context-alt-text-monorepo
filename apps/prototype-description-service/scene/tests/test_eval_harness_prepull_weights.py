"""VLM-6 S2: weight pre-pull planner (no network, no real huggingface-cli)."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.eval_harness.bakeoff_candidates import (
    BakeoffCandidateRegistry,
    BakeoffTier,
    CandidateEntry,
    CandidateRole,
    ServingRecipe,
    ServingStack,
    load_bakeoff_candidates,
)
from scripts.eval_harness.bakeoff_runner import (
    SKIP_REASON_NOT_COMPETING,
    SKIP_REASON_STACK,
    SkipNotesInconsistentError,
    UnknownCandidateError,
    build_plans,
)
from scripts.eval_harness.prepull_weights import (
    DOWNLOAD_TIMEOUT_S,
    PRESENT_SIZE_RATIO,
    DiskBudgetError,
    DownloadStatus,
    SkipReason,
    already_present,
    check_disk_budget,
    list_skips,
    main,
    plan_downloads,
    run_downloads,
)

_SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_MODELS_DIR = "/opt/models"
_PLAN_KW = {
    "endpoint": "http://localhost:8000",
    "manifest": "scripts/eval_harness/corpus646-interleave-manifest-20260716.json",
    "out_dir": "out",
    "models_dir": _MODELS_DIR,
}


def _recipe(**overrides: Any) -> ServingRecipe:
    payload: dict[str, Any] = {
        "stack": ServingStack.LLAMA_CPP,
        "ctx_size": 8192,
        "image_max_tokens": 1536,
        "parallel": 1,
        "extra_flags": ["--flash-attn", "--no-mmap"],
        "gguf": "model.gguf",
        "mmproj": "mmproj.gguf",
    }
    payload.update(overrides)
    return ServingRecipe.model_validate(payload)


def _entry(entry_id: str, **overrides: Any) -> CandidateEntry:
    payload: dict[str, Any] = {
        "id": entry_id,
        "role": CandidateRole.CANDIDATE,
        "competing": True,
        "model_id": f"Model-{entry_id}",
        "repo": f"org/{entry_id}",
        "revision": _SHA,
        "quant": "Q4_K_M",
        "artifact": "model.gguf",
        "artifact_gb": 6.0,
        "license": "Apache-2.0",
        "prompt_template": "v3",
        "tiers": [BakeoffTier.GPU_ASYNC],
        "recipe": _recipe(),
        "reasoning_tuned": False,
    }
    payload.update(overrides)
    return CandidateEntry.model_validate(payload)


def _registry(entries: list[CandidateEntry], *, usable_vram_budget_gb: int = 20) -> BakeoffCandidateRegistry:
    return BakeoffCandidateRegistry.model_validate(
        {
            "schema": "acx-bakeoff-candidates/v1",
            "task_ref": "VLM-6",
            "hardware_target": {
                "shape": "VM.GPU.A10.1",
                "vram_gb": 24,
                "usable_vram_budget_gb": usable_vram_budget_gb,
            },
            "sealed": {
                "candidates": 13,
                "incumbent_anchors": 2,
                "generation_pairs": [{"ids": ["alpha", "bravo"], "quant": "Q4_K_M"}],
            },
            "entries": entries,
        }
    )


def _sample_registry() -> BakeoffCandidateRegistry:
    return _registry(
        [
            _entry("alpha"),
            _entry("bravo", reasoning_tuned=True),
            _entry("phi-ref", competing=False, notes="measured, not competing"),
            _entry(
                "florence-anchor",
                role=CandidateRole.INCUMBENT,
                competing=False,
            ),
            _entry("charlie"),
            _entry(
                "qwen-anchor",
                role=CandidateRole.INCUMBENT,
                competing=False,
            ),
        ]
    )


def _mutate_entry(
    registry: BakeoffCandidateRegistry,
    entry_id: str,
    **updates: Any,
) -> BakeoffCandidateRegistry:
    entries = [
        entry.model_copy(update=updates, deep=True) if entry.id == entry_id else entry for entry in registry.entries
    ]
    return registry.model_copy(update={"entries": entries})


def _plenty(_path: str) -> SimpleNamespace:
    return SimpleNamespace(total=10**15, used=0, free=10**15)


def _write_job_files(job: Any, *, size_bytes: int | None = None) -> None:
    dest = Path(job.local_dir)
    dest.mkdir(parents=True, exist_ok=True)
    expecteds = getattr(job, "file_expected_gb", None)
    for idx, name in enumerate(job.files):
        path = dest / name
        if size_bytes is not None:
            nbytes = size_bytes
        elif expecteds:
            expected = expecteds[idx] if idx < len(expecteds) else None
            nbytes = 1 if expected is None else max(1, int(PRESENT_SIZE_RATIO * float(expected) * 1e9))
        else:
            nbytes = 1
        with path.open("wb") as handle:
            handle.truncate(nbytes)


def test_plan_argv_shape_and_order_match_build_plans() -> None:
    registry = _sample_registry()
    plans = build_plans(registry, **_PLAN_KW)
    jobs = plan_downloads(registry, models_dir=_MODELS_DIR)
    assert [job.candidate_id for job in jobs] == [plan.candidate_id for plan in plans]
    assert [job.candidate_id for job in jobs] == ["alpha", "bravo", "charlie"]
    for job, plan in zip(jobs, plans, strict=True):
        assert job.repo == plan.repo
        assert job.revision == plan.revision
        assert job.size_gb == plan.total_gb
        assert job.local_dir == f"{_MODELS_DIR}/{plan.candidate_id}"
        gguf = plan.serve_argv[plan.serve_argv.index("--model") + 1].rsplit("/", 1)[-1]
        mmproj = plan.serve_argv[plan.serve_argv.index("--mmproj") + 1].rsplit("/", 1)[-1]
        assert job.files == (gguf, mmproj)
        assert job.argv == (
            "huggingface-cli",
            "download",
            plan.repo,
            "--revision",
            plan.revision,
            "--include",
            gguf,
            "--include",
            mmproj,
            "--local-dir",
            job.local_dir,
        )


def test_only_unknown_id_raises_same_class_as_runner() -> None:
    registry = _sample_registry()
    with pytest.raises(UnknownCandidateError, match="no-such-model"):
        build_plans(registry, **_PLAN_KW, only=["alpha", "no-such-model"])
    with pytest.raises(UnknownCandidateError, match="no-such-model"):
        plan_downloads(registry, models_dir=_MODELS_DIR, only=["alpha", "no-such-model"])


def test_cli_only_unknown_id_exits_3(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--only", "definitely-missing"]) == 3
    err = capsys.readouterr().err
    assert "definitely-missing" in err


def test_disk_budget_fail_names_required_and_free(tmp_path) -> None:
    jobs = plan_downloads(_registry([_entry("alpha")]), models_dir=str(tmp_path))
    needed = jobs[0].size_gb + 5.0
    free_gb = 1.5

    def tight(_path: str) -> SimpleNamespace:
        return SimpleNamespace(total=10 * 1024**3, used=0, free=int(free_gb * 1024**3))

    with pytest.raises(DiskBudgetError) as exc_info:
        check_disk_budget(jobs, str(tmp_path), margin_gb=5.0, disk_usage=tight)
    message = str(exc_info.value)
    assert "required_gb" in message
    assert "free_gb" in message
    assert f"{needed}" in message or f"{needed:.1f}" in message
    assert "1.5" in message
    assert exc_info.value.required_gb == pytest.approx(needed)
    assert exc_info.value.free_gb == pytest.approx(free_gb)


def test_already_present_skips_and_is_excluded_from_budget(tmp_path) -> None:
    models_dir = tmp_path / "models"
    jobs = plan_downloads(_sample_registry(), models_dir=str(models_dir))
    present, missing = jobs[0], jobs[1]
    _write_job_files(present)
    empty = models_dir / missing.candidate_id
    empty.mkdir(parents=True)
    (empty / missing.files[0]).write_bytes(b"")
    assert already_present(present) is True
    assert already_present(missing) is False

    def plenty_local(_path: str) -> SimpleNamespace:
        return SimpleNamespace(total=100 * 1024**3, used=0, free=80 * 1024**3)

    budget = check_disk_budget(jobs, str(models_dir), margin_gb=5.0, disk_usage=plenty_local)
    expected = sum(job.size_gb for job in jobs if job is not present) + 5.0
    assert budget.required_gb == pytest.approx(expected)
    assert budget.ok is True


def test_dry_run_spawns_nothing() -> None:
    jobs = plan_downloads(_sample_registry(), models_dir=_MODELS_DIR)
    calls: list[Any] = []

    def spy(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((_args, _kwargs))
        return subprocess.CompletedProcess(args=["huggingface-cli"], returncode=0)

    results = run_downloads(jobs, execute=False, runner=spy)
    assert calls == []
    assert [result.status for result in results] == [
        DownloadStatus.PLANNED,
        DownloadStatus.PLANNED,
        DownloadStatus.PLANNED,
    ]
    assert all(result.returncode is None for result in results)


def test_execute_exit_0_without_file_is_failed(tmp_path) -> None:
    jobs = plan_downloads(_registry([_entry("alpha")]), models_dir=str(tmp_path))
    logs: list[str] = []

    def runner(argv: Any, **_kwargs: Any) -> subprocess.CompletedProcess[Any]:
        return subprocess.CompletedProcess(args=argv, returncode=0)

    results = run_downloads(jobs, execute=True, runner=runner, log=logs.append)
    assert results[0].status is DownloadStatus.FAILED
    assert results[0].returncode == 0
    assert any("downloaded but expected file missing:" in line for line in logs)
    assert any("model.gguf" in line for line in logs)


def test_execute_runner_that_writes_files_is_downloaded(tmp_path) -> None:
    jobs = plan_downloads(_registry([_entry("alpha")]), models_dir=str(tmp_path))

    def runner(argv: Any, **_kwargs: Any) -> subprocess.CompletedProcess[Any]:
        _write_job_files(jobs[0])
        return subprocess.CompletedProcess(args=argv, returncode=0)

    results = run_downloads(jobs, execute=True, runner=runner)
    assert results[0].status is DownloadStatus.DOWNLOADED
    assert results[0].returncode == 0
    assert already_present(jobs[0]) is True


def test_one_failing_job_does_not_stop_the_next(tmp_path) -> None:
    jobs = plan_downloads(
        _registry([_entry("alpha"), _entry("bravo")]),
        models_dir=str(tmp_path),
    )
    seen: list[str] = []

    def runner(argv: Any, **_kwargs: Any) -> subprocess.CompletedProcess[Any]:
        seen.append(str(argv[2]))
        if "alpha" in str(argv):
            return subprocess.CompletedProcess(args=argv, returncode=1)
        _write_job_files(jobs[1])
        return subprocess.CompletedProcess(args=argv, returncode=0)

    results = run_downloads(jobs, execute=True, runner=runner)
    assert [result.candidate_id for result in results] == ["alpha", "bravo"]
    assert results[0].status is DownloadStatus.FAILED
    assert results[0].returncode == 1
    assert results[1].status is DownloadStatus.DOWNLOADED
    assert seen == ["org/alpha", "org/bravo"]


def test_json_output_round_trips(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "scripts.eval_harness.prepull_weights.load_bakeoff_candidates",
        _sample_registry,
    )
    monkeypatch.setattr(
        "scripts.eval_harness.prepull_weights.shutil.disk_usage",
        _plenty,
    )
    assert main(["--json", "--models-dir", str(tmp_path)]) == 0
    raw = capsys.readouterr().out
    payload = json.loads(raw)
    assert json.loads(json.dumps(payload)) == payload
    assert [row["candidate_id"] for row in payload["jobs"]] == ["alpha", "bravo", "charlie"]
    assert payload["budget"]["ok"] is True
    assert "required_gb" in payload["budget"]
    assert "free_gb" in payload["budget"]
    skip_ids = {row["candidate_id"] for row in payload["skips"]}
    assert skip_ids == {"phi-ref", "florence-anchor", "qwen-anchor"}
    for row in payload["skips"]:
        assert row["reason"] == SKIP_REASON_NOT_COMPETING
    first = payload["jobs"][0]
    assert first["argv"][0] == "huggingface-cli"
    assert first["files"] == ["model.gguf", "mmproj.gguf"]


def test_skips_name_stack_and_not_competing() -> None:
    vllm = _recipe(stack=ServingStack.VLLM, gguf=None, mmproj=None, extra_flags=[])
    registry = _registry(
        [
            _entry("ok"),
            _entry("ref", competing=False),
            _entry("vllm-one", recipe=vllm),
        ]
    )
    jobs = plan_downloads(registry, models_dir=_MODELS_DIR)
    assert [job.candidate_id for job in jobs] == ["ok"]
    skips = list_skips(registry, jobs)
    reasons = dict(skips)
    assert reasons["ref"] == SKIP_REASON_NOT_COMPETING
    assert reasons["vllm-one"] == SKIP_REASON_STACK
    assert "ok" not in reasons


def test_dry_run_already_present_is_skipped_present(tmp_path) -> None:
    jobs = plan_downloads(_registry([_entry("alpha")]), models_dir=str(tmp_path))
    _write_job_files(jobs[0])
    results = run_downloads(jobs, execute=False, runner=lambda *_a, **_k: None)
    assert results[0].status is DownloadStatus.SKIPPED_PRESENT


def test_cli_dry_run_prints_plan_and_skip(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "scripts.eval_harness.prepull_weights.load_bakeoff_candidates",
        _sample_registry,
    )
    monkeypatch.setattr(
        "scripts.eval_harness.prepull_weights.shutil.disk_usage",
        _plenty,
    )
    assert main(["--models-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "PLAN alpha org/alpha@" in out
    assert "PLAN bravo " in out
    assert "PLAN charlie " in out
    assert f"SKIP phi-ref: {SKIP_REASON_NOT_COMPETING}" in out
    assert "BUDGET " in out
    assert "required_gb=" in out
    assert "free_gb=" in out


_COMPETING_LLAMA_CPP_EXCLUDED_BY_ONLY = (
    "gemma-4-12b",
    "kimi-vl-a3b",
    "minicpm-v-46",
    "qwen36-27b",
    "qwen38-27b",
)


def test_only_union_covers_every_row_and_names_excluded_llama_cpp() -> None:
    registry = _registry(
        [
            _entry("keep"),
            _entry("drop-a"),
            _entry("drop-b"),
            _entry("ref", competing=False),
            _entry(
                "vllm-one",
                recipe=_recipe(stack=ServingStack.VLLM, gguf=None, mmproj=None, extra_flags=[]),
            ),
        ]
    )
    only = ["keep"]
    jobs = plan_downloads(registry, models_dir=_MODELS_DIR, only=only)
    skips = list_skips(registry, jobs, only=only)
    job_ids = {job.candidate_id for job in jobs}
    skip_ids = {candidate_id for candidate_id, _reason in skips}
    assert job_ids | skip_ids == {entry.id for entry in registry.entries}
    assert job_ids.isdisjoint(skip_ids)
    reasons = dict(skips)
    assert reasons["drop-a"] == SkipReason.EXCLUDED_BY_ONLY
    assert reasons["drop-b"] == SkipReason.EXCLUDED_BY_ONLY
    assert reasons["ref"] == SKIP_REASON_NOT_COMPETING
    assert reasons["vllm-one"] == SKIP_REASON_STACK


def test_only_real_roster_names_five_competing_gguf_skips() -> None:
    registry = load_bakeoff_candidates()
    only = ["minicpm-v-45"]
    jobs = plan_downloads(registry, models_dir=_MODELS_DIR, only=only)
    skips = list_skips(registry, jobs, only=only)
    job_ids = {job.candidate_id for job in jobs}
    skip_ids = {candidate_id for candidate_id, _reason in skips}
    sealed_ids = {entry.id for entry in registry.entries}
    assert job_ids | skip_ids == sealed_ids
    assert job_ids == {"minicpm-v-45"}
    reasons = dict(skips)
    for candidate_id in _COMPETING_LLAMA_CPP_EXCLUDED_BY_ONLY:
        assert reasons[candidate_id] == SkipReason.EXCLUDED_BY_ONLY


def test_list_skips_without_only_reraises_inconsistent_competing_row() -> None:
    registry = _registry([_entry("keep"), _entry("drop-a")])
    jobs = plan_downloads(registry, models_dir=_MODELS_DIR, only=["keep"])
    with pytest.raises(SkipNotesInconsistentError):
        list_skips(registry, jobs)


def test_cli_margin_gb_negative_exits_2() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--margin-gb", "-1"])
    assert exc_info.value.code == 2


def test_cli_margin_gb_nan_exits_2() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--margin-gb", "nan"])
    assert exc_info.value.code == 2


def test_cli_margin_gb_inf_exits_2() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--margin-gb", "inf"])
    assert exc_info.value.code == 2


def test_check_disk_budget_rejects_negative_margin(tmp_path) -> None:
    jobs = plan_downloads(_registry([_entry("alpha")]), models_dir=str(tmp_path))
    with pytest.raises(ValueError, match="margin"):
        check_disk_budget(jobs, str(tmp_path), margin_gb=-1000, disk_usage=_plenty)


def test_check_disk_budget_rejects_nonfinite_margin(tmp_path) -> None:
    jobs = plan_downloads(_registry([_entry("alpha")]), models_dir=str(tmp_path))
    with pytest.raises(ValueError, match="margin"):
        check_disk_budget(jobs, str(tmp_path), margin_gb=float("nan"), disk_usage=_plenty)
    with pytest.raises(ValueError, match="margin"):
        check_disk_budget(jobs, str(tmp_path), margin_gb=math.inf, disk_usage=_plenty)


def test_one_byte_files_are_not_present_and_runner_is_called(tmp_path) -> None:
    jobs = plan_downloads(_registry([_entry("alpha")]), models_dir=str(tmp_path))
    _write_job_files(jobs[0], size_bytes=1)
    assert already_present(jobs[0]) is False
    calls: list[Any] = []

    def runner(argv: Any, **_kwargs: Any) -> subprocess.CompletedProcess[Any]:
        calls.append(argv)
        _write_job_files(jobs[0])
        return subprocess.CompletedProcess(args=argv, returncode=0)

    results = run_downloads(jobs, execute=True, runner=runner)
    assert calls, "truncated 1-byte artifacts must not skip the runner"
    assert results[0].status is DownloadStatus.DOWNLOADED


def test_file_at_threshold_is_skipped_present(tmp_path) -> None:
    jobs = plan_downloads(_registry([_entry("alpha", artifact_gb=0.00001)]), models_dir=str(tmp_path))
    _write_job_files(jobs[0])
    assert already_present(jobs[0]) is True
    results = run_downloads(
        jobs,
        execute=True,
        runner=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("runner must not run")),
    )
    assert results[0].status is DownloadStatus.SKIPPED_PRESENT


def test_missing_registry_size_requires_nonzero_and_notes_unverified(tmp_path) -> None:
    jobs = plan_downloads(
        _registry([_entry("alpha", artifact_gb=0.00001)]),
        models_dir=str(tmp_path),
    )
    assert jobs[0].file_expected_gb[1] is None
    dest = Path(jobs[0].local_dir)
    dest.mkdir(parents=True)
    gguf, mmproj = jobs[0].files
    threshold = max(1, int(PRESENT_SIZE_RATIO * 0.00001 * 1e9))
    with (dest / gguf).open("wb") as handle:
        handle.truncate(threshold)
    (dest / mmproj).write_bytes(b"")
    assert already_present(jobs[0]) is False
    (dest / mmproj).write_bytes(b"x")
    notes: list[str] = []
    assert already_present(jobs[0], notes=notes) is True
    assert any("unverified" in note.lower() for note in notes)
    results = run_downloads(jobs, execute=False, runner=lambda *_a, **_k: None)
    assert results[0].status is DownloadStatus.SKIPPED_PRESENT
    assert results[0].note is not None
    assert "unverified" in results[0].note.lower()


def test_timeout_expired_is_failed_and_runner_gets_timeout(tmp_path) -> None:
    jobs = plan_downloads(_registry([_entry("alpha")]), models_dir=str(tmp_path))
    seen: dict[str, Any] = {}

    def runner(*_args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(cmd="huggingface-cli", timeout=kwargs.get("timeout", 0))

    results = run_downloads(jobs, execute=True, runner=runner)
    assert seen.get("timeout") == DOWNLOAD_TIMEOUT_S
    assert DOWNLOAD_TIMEOUT_S == 3600
    assert results[0].status is DownloadStatus.FAILED
    assert results[0].returncode is None
