"""VLM-6 S2a-2: registry-driven bake-off planner (plan-only)."""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

import pytest

from scripts.eval_harness import bakeoff, build_bakeoff_report
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
    READY_ATTEMPTS,
    READY_SLEEP_S,
    SKIP_REASON_NOT_COMPETING,
    SKIP_REASON_STACK,
    SKIP_REASON_VRAM,
    WARMUP_REQUESTS,
    NotCompetingError,
    SkipNotesInconsistentError,
    UnknownCandidateError,
    UnsupportedStackError,
    VramBudgetError,
    _emit_skip_notes,
    _report_argv,
    _skip_reason,
    build_plans,
    emit_shell,
    main,
)

_SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_PLAN_KW = {
    "endpoint": "http://localhost:8000",
    "manifest": "scripts/eval_harness/corpus646-interleave-manifest-20260716.json",
    "out_dir": "out",
    "models_dir": "/opt/models",
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
            _entry(
                "phi-ref",
                competing=False,
                notes="measured, not competing",
            ),
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


def test_plan_count_and_order_are_competing_registry_order() -> None:
    registry = _sample_registry()
    plans = build_plans(registry, **_PLAN_KW)
    assert [plan.candidate_id for plan in plans] == ["alpha", "bravo", "charlie"]
    assert "phi-ref" not in [plan.candidate_id for plan in plans]
    assert "florence-anchor" not in [plan.candidate_id for plan in plans]
    assert "qwen-anchor" not in [plan.candidate_id for plan in plans]


def test_llama_cpp_serve_argv_contains_artifacts_ctx_and_extra_flags() -> None:
    extra = ["--flash-attn", "--no-mmap"]
    registry = _registry([_entry("minicpm-v-45", recipe=_recipe(extra_flags=extra, ctx_size=4096))])
    plan = build_plans(registry, **_PLAN_KW)[0]
    argv = plan.serve_argv
    assert argv[0] == "llama-server"
    model_path = argv[argv.index("--model") + 1]
    mmproj_path = argv[argv.index("--mmproj") + 1]
    assert model_path == "/opt/models/minicpm-v-45/model.gguf"
    assert mmproj_path == "/opt/models/minicpm-v-45/mmproj.gguf"
    assert argv[argv.index("-c") + 1] == "4096"
    assert argv[-len(extra) :] == tuple(extra)
    assert argv.index("--model") < argv.index("--mmproj") < argv.index("-c")
    assert argv.index("-c") < argv.index("--image-max-tokens") < argv.index("-np")
    assert argv.index("-np") < len(argv) - len(extra)
    assert argv[argv.index("--host") + 1] == "localhost"
    assert argv[argv.index("--port") + 1] == "8000"
    assert argv.index("--host") < argv.index("--port") < argv.index("--model")


def test_reasoning_tuned_controls_no_think_on_run_argv() -> None:
    registry = _registry(
        [
            _entry("thinky", reasoning_tuned=True),
            _entry("plain", reasoning_tuned=False),
        ]
    )
    plans = {plan.candidate_id: plan for plan in build_plans(registry, **_PLAN_KW)}
    assert "--no-think" in plans["thinky"].run_argv
    assert plans["thinky"].run_argv[-1] == "--no-think"
    assert "--no-think" not in plans["plain"].run_argv
    for plan in plans.values():
        assert plan.run_argv[:3] == ("python3", "-m", "scripts.eval_harness.bakeoff")
        assert "--two-pass" in plan.run_argv
        assert "--limit" not in plan.run_argv
        assert plan.out_path == f"out/run-bakeoff-{plan.candidate_id}.json"
        assert plan.run_argv[plan.run_argv.index("--out") + 1] == plan.out_path


def test_vllm_stack_skipped_unless_explicitly_requested() -> None:
    registry = _mutate_entry(
        _sample_registry(),
        "bravo",
        recipe=_recipe(stack=ServingStack.VLLM, gguf=None, mmproj=None, extra_flags=[]),
    )
    plans = build_plans(registry, **_PLAN_KW)
    assert [plan.candidate_id for plan in plans] == ["alpha", "charlie"]
    with pytest.raises(UnsupportedStackError, match="bravo") as exc_info:
        build_plans(registry, **_PLAN_KW, only=["bravo"])
    assert "vllm" in str(exc_info.value)


def test_artifact_over_budget_raises_vram_error() -> None:
    registry = _mutate_entry(_sample_registry(), "charlie", artifact_gb=25.0)
    with pytest.raises(VramBudgetError, match="charlie") as exc_info:
        build_plans(registry, **_PLAN_KW)
    message = str(exc_info.value)
    assert "26.0" in message
    assert "20" in message


def test_only_filters_named_ids_and_rejects_unknown() -> None:
    registry = _sample_registry()
    plans = build_plans(registry, **_PLAN_KW, only=["charlie", "alpha"])
    assert [plan.candidate_id for plan in plans] == ["alpha", "charlie"]
    with pytest.raises(UnknownCandidateError, match="no-such-model"):
        build_plans(registry, **_PLAN_KW, only=["alpha", "no-such-model"])


def test_emit_shell_is_bash_n_clean_and_mentions_incumbents(tmp_path) -> None:
    registry = _sample_registry()
    plans = build_plans(registry, **_PLAN_KW)
    incumbent_runs = {
        "florence-anchor": "/records/florence-anchor.json",
        "qwen-anchor": "/records/qwen-anchor.json",
    }
    script = emit_shell(plans, incumbent_runs=incumbent_runs)
    path = tmp_path / "bake.sh"
    path.write_text(script, encoding="utf-8")
    completed = subprocess.run(["bash", "-n", str(path)], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert script.splitlines()[1] == "set -euo pipefail"
    assert "/v1/models" in script
    assert "scripts.eval_harness.build_bakeoff_report" in script
    for plan in plans:
        assert plan.candidate_id in script
        assert plan.out_path in script
    assert "/records/florence-anchor.json" in script
    assert "/records/qwen-anchor.json" in script
    assert f"seq 1 {READY_ATTEMPTS}" in script
    assert READY_ATTEMPTS == 600
    assert READY_SLEEP_S == 1
    assert f"sleep {READY_SLEEP_S}" in script
    assert "--max-time" in script
    assert "trap" in script
    assert 'kill "${_serve_pid}" 2>/dev/null || true' in script
    assert "[ -f /records/florence-anchor.json ]" in script
    assert "[ -f /records/qwen-anchor.json ]" in script


def test_build_plans_is_deterministic() -> None:
    registry = _sample_registry()
    first = build_plans(registry, **_PLAN_KW)
    second = build_plans(registry, **_PLAN_KW)
    assert first == second
    assert [plan.serve_argv for plan in first] == [plan.serve_argv for plan in second]
    assert [plan.run_argv for plan in first] == [plan.run_argv for plan in second]


def test_cli_only_unknown_id_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--only", "definitely-missing"]) == 2
    err = capsys.readouterr().err
    assert "definitely-missing" in err


def test_run_argv_pins_warmup_on_every_plan() -> None:
    # VLM-6 S2 residual / PERF-03: --warmup must be explicit, not implicit default.
    plans = build_plans(_sample_registry(), **_PLAN_KW)
    assert plans
    for plan in plans:
        argv = list(plan.run_argv)
        assert "--warmup" in argv, plan.run_argv
        assert argv[argv.index("--warmup") + 1] == str(WARMUP_REQUESTS)


def test_run_argv_omits_limit_zero() -> None:
    plan = build_plans(_registry([_entry("alpha")]), **_PLAN_KW)[0]
    assert "--limit" not in plan.run_argv


def test_only_non_competing_id_raises() -> None:
    registry = _sample_registry()
    with pytest.raises(NotCompetingError, match="florence-anchor"):
        build_plans(registry, **_PLAN_KW, only=["florence-anchor"])
    with pytest.raises(NotCompetingError, match="phi-ref"):
        build_plans(registry, **_PLAN_KW, only=["phi-ref"])


def test_no_think_extra_flag_stays_off_serve_argv() -> None:
    registry = _registry(
        [
            _entry(
                "thinky",
                reasoning_tuned=True,
                recipe=_recipe(extra_flags=["--flash-attn", "--no-think", "--no-mmap"]),
            )
        ]
    )
    plan = build_plans(registry, **_PLAN_KW)[0]
    assert "--no-think" not in plan.serve_argv
    assert plan.serve_argv[-2:] == ("--flash-attn", "--no-mmap")
    assert plan.run_argv.count("--no-think") == 1


def test_serve_argv_binds_host_port_from_endpoint() -> None:
    kw = {**_PLAN_KW, "endpoint": "http://127.0.0.1:9001"}
    plan = build_plans(_registry([_entry("alpha")]), **kw)[0]
    assert plan.serve_argv[plan.serve_argv.index("--host") + 1] == "127.0.0.1"
    assert plan.serve_argv[plan.serve_argv.index("--port") + 1] == "9001"
    assert plan.run_argv[plan.run_argv.index("--endpoint") + 1] == "http://127.0.0.1:9001"


def test_cli_default_on_sealed_registry_plans_llama_cpp_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    ids = [row["candidate_id"] for row in payload]
    assert ids == [
        "minicpm-v-45",
        "qwen38-27b",
        "qwen36-27b",
        "kimi-vl-a3b",
        "gemma-4-12b",
        "minicpm-v-46",
    ]
    for row in payload:
        assert "--limit" not in row["run_argv"]
        assert "--host" in row["serve_argv"]
        assert "--port" in row["serve_argv"]
        assert "--no-think" not in row["serve_argv"]


def test_run_argv_round_trips_through_bakeoff_parser() -> None:
    registry = load_bakeoff_candidates()
    plans = build_plans(registry, **_PLAN_KW)
    parser = bakeoff.build_parser()
    for plan in plans:
        assert plan.run_argv[:3] == ("python3", "-m", "scripts.eval_harness.bakeoff")
        parsed = parser.parse_args(list(plan.run_argv[3:]))
        assert parsed.endpoint == _PLAN_KW["endpoint"]
        assert parsed.model_id == plan.model_id
        assert parsed.out == plan.out_path


def test_report_argv_round_trips_through_report_parser() -> None:
    plans = build_plans(_sample_registry(), **_PLAN_KW)
    incumbents = {
        "florence-anchor": "/records/florence-anchor.json",
        "qwen-anchor": "/records/qwen-anchor.json",
    }
    argv = _report_argv(plans, incumbents)
    assert argv[:3] == ["python3", "-m", "scripts.eval_harness.build_bakeoff_report"]
    parsed = build_bakeoff_report.build_parser().parse_args(argv[3:])
    assert parsed.manifest == _PLAN_KW["manifest"]
    assert parsed.limit == 646
    assert parsed.run == [f"{plan.candidate_id}={plan.out_path}" for plan in plans] + [
        "florence-anchor=/records/florence-anchor.json",
        "qwen-anchor=/records/qwen-anchor.json",
    ]


def test_report_run_paths_are_plan_outs_or_supplied_incumbents() -> None:
    plans = build_plans(_sample_registry(), **_PLAN_KW)
    incumbents = {"florence-anchor": "/records/florence-anchor.json"}
    argv = _report_argv(plans, incumbents)
    allowed = {plan.out_path for plan in plans} | set(incumbents.values())
    for plan in plans:
        assert plan.out_path == plan.run_argv[plan.run_argv.index("--out") + 1]
    parsed = build_bakeoff_report.build_parser().parse_args(argv[3:])
    for spec in parsed.run:
        path = spec.split("=", 1)[1]
        assert path in allowed


def test_run_argv_round_trip_rejects_limit_zero() -> None:
    plan = build_plans(_registry([_entry("alpha")]), **_PLAN_KW)[0]
    mutated = list(plan.run_argv[3:]) + ["--limit", "0"]
    with pytest.raises(SystemExit):
        bakeoff.build_parser().parse_args(mutated)


def test_cli_emits_skip_notes_for_unsupported_stacks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--json"]) == 0
    err = capsys.readouterr().err
    registry = load_bakeoff_candidates()
    planned = {plan.candidate_id for plan in build_plans(registry, **_PLAN_KW)}
    expected = [entry for entry in registry.entries if entry.id not in planned]
    skip_lines = [line for line in err.splitlines() if line.startswith("skip ")]
    summary = next(line for line in err.splitlines() if line.startswith("skipped "))
    parsed = re.fullmatch(r"skipped (\d+) of (\d+) registry entries", summary)
    assert parsed is not None
    assert int(parsed.group(1)) == len(skip_lines) == len(expected)
    assert int(parsed.group(2)) == len(registry.entries)
    for entry in expected:
        if not entry.competing:
            assert f"skip {entry.id} ({SKIP_REASON_NOT_COMPETING})" in err
        elif entry.recipe.stack is not ServingStack.LLAMA_CPP:
            assert f"skip {entry.id} ({SKIP_REASON_STACK})" in err
        else:
            assert f"skip {entry.id} ({SKIP_REASON_VRAM})" in err


def test_skip_notes_name_vram_and_not_competing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    vllm = _recipe(stack=ServingStack.VLLM, gguf=None, mmproj=None, extra_flags=[])
    registry = _registry(
        [
            _entry("ok"),
            _entry("huge", artifact_gb=25.0),
            _entry("ref", competing=False),
            _entry("vllm-one", recipe=vllm),
        ]
    )
    plans = build_plans(_registry([_entry("ok")]), **_PLAN_KW)
    _emit_skip_notes(registry, plans)
    err = capsys.readouterr().err
    skip_lines = [line for line in err.splitlines() if line.startswith("skip ")]
    summary = next(line for line in err.splitlines() if line.startswith("skipped "))
    parsed = re.fullmatch(r"skipped (\d+) of (\d+) registry entries", summary)
    assert parsed is not None
    assert int(parsed.group(1)) == len(skip_lines) == 3
    assert int(parsed.group(2)) == 4
    assert f"skip huge ({SKIP_REASON_VRAM})" in err
    assert f"skip ref ({SKIP_REASON_NOT_COMPETING})" in err
    assert f"skip vllm-one ({SKIP_REASON_STACK})" in err
    assert "skip ok " not in err


def test_skip_reason_raises_when_planner_and_notes_disagree() -> None:
    entry = _entry("ghost")
    with pytest.raises(SkipNotesInconsistentError, match="ghost"):
        _skip_reason(entry, planned=set(), budget_gb=20.0)


def test_cli_does_not_invent_incumbent_paths(tmp_path) -> None:
    script_path = tmp_path / "plan.sh"
    assert main(["--emit-shell", str(script_path)]) == 0
    text = script_path.read_text(encoding="utf-8")
    assert "run-bakeoff-florence-2-base-ft.json" not in text
    assert "run-bakeoff-qwen3-vl-30b-a3b.json" not in text
    assert "florence-2-base-ft=" not in text
    assert "qwen3-vl-30b-a3b=" not in text


def test_cli_incumbent_run_uses_supplied_path_only(tmp_path) -> None:
    script_path = tmp_path / "plan.sh"
    assert (
        main(
            [
                "--emit-shell",
                str(script_path),
                "--incumbent-run",
                "florence-2-base-ft=/records/florence.json",
            ]
        )
        == 0
    )
    text = script_path.read_text(encoding="utf-8")
    assert "/records/florence.json" in text
    assert "[ -f /records/florence.json ]" in text
    assert "run-bakeoff-qwen3-vl-30b-a3b.json" not in text
    assert "qwen3-vl-30b-a3b=" not in text


def test_cli_incumbent_run_rejects_non_incumbent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--incumbent-run", "minicpm-v-45=out/x.json"]) == 2
    err = capsys.readouterr().err
    assert "minicpm-v-45" in err
    assert "incumbent" in err


def test_emit_shell_tracks_failures_and_probes_liveness() -> None:
    plans = build_plans(_sample_registry(), **_PLAN_KW)
    script = emit_shell(plans, incumbent_runs={})
    assert "_fail=0" in script
    assert "_total=$((_total + 1))" in script
    assert 'kill -0 "$_serve_pid" 2>/dev/null || break' in script
    assert 'if [ "${_total}" -gt 0 ] && [ "${_fail}" -eq "${_total}" ]; then' in script
    assert "exit 1" in script


def test_emit_shell_download_hint_includes_artifacts() -> None:
    plans = build_plans(_registry([_entry("alpha")]), **_PLAN_KW)
    script = emit_shell(plans, incumbent_runs={})
    assert "--include model.gguf" in script
    assert "--include mmproj.gguf" in script
    assert "--limit 646" in script


def test_mmproj_gb_from_recipe_not_placeholder() -> None:
    registry = _registry([_entry("gemma-like", artifact_gb=7.2, recipe=_recipe(mmproj_gb=0.18))])
    plan = build_plans(registry, **_PLAN_KW)[0]
    assert plan.total_gb == pytest.approx(7.38)


def test_mmproj_gb_falls_back_to_estimate() -> None:
    plan = build_plans(_registry([_entry("alpha", artifact_gb=6.0)]), **_PLAN_KW)[0]
    assert plan.total_gb == pytest.approx(7.0)


def test_sealed_llama_cpp_mmproj_gb_from_notes() -> None:
    registry = load_bakeoff_candidates()
    plans = {plan.candidate_id: plan for plan in build_plans(registry, **_PLAN_KW)}
    assert plans["kimi-vl-a3b"].total_gb == pytest.approx(11.5 + 0.91)
    assert plans["gemma-4-12b"].total_gb == pytest.approx(7.2 + 0.18)
    assert plans["minicpm-v-45"].total_gb == pytest.approx(7.0)


_PREFLIGHT_CAPTURE = "_build=$(llama-server --version 2>&1 | grep -oE 'b[0-9]+' | head -1)"


def _assert_runtime_build_preflight(
    script: str,
    *,
    floored_ids: list[str],
    lower_bound_ids: list[str],
) -> None:
    assert _PREFLIGHT_CAPTURE in script
    for cid in floored_ids:
        assert f"candidate {cid}" in script
        assert "required " in script
        block_at = script.find(f"# preflight: {cid} requires llama.cpp")
        assert block_at != -1, cid
        next_serve = script.find("llama-server --host", block_at)
        assert next_serve != -1, cid
        assert block_at < next_serve
        assert "exit 1" in script[block_at:next_serve]
        assert "cannot parse llama-server runtime build" in script[block_at:next_serve]
        assert '"${_obs}" -lt "${_req}"' in script[block_at:next_serve]
    for cid in lower_bound_ids:
        block_at = script.find(f"# preflight: {cid} requires llama.cpp")
        next_serve = script.find("llama-server --host", block_at)
        block = script[block_at:next_serve]
        assert '"${_obs}" -gt "${_req}"' in block
        assert "strictly greater" in block


def test_emit_shell_runtime_build_preflight_refuses_under_versioned_host() -> None:
    registry = _registry(
        [
            _entry("exact-floor", recipe=_recipe(min_runtime_build="b6887")),
            _entry(
                "lower-bound",
                recipe=_recipe(
                    min_runtime_build="b6887",
                    min_runtime_build_is_lower_bound=True,
                ),
            ),
            _entry("no-floor"),
        ]
    )
    plans = build_plans(registry, **_PLAN_KW)
    assert {plan.candidate_id for plan in plans} == {"exact-floor", "lower-bound", "no-floor"}
    for plan in plans:
        if plan.candidate_id == "no-floor":
            assert plan.min_runtime_build is None
        else:
            assert plan.min_runtime_build == "b6887"
    script = emit_shell(plans, incumbent_runs={})
    _assert_runtime_build_preflight(
        script,
        floored_ids=["exact-floor", "lower-bound"],
        lower_bound_ids=["lower-bound"],
    )
    no_floor_at = script.find("# candidate: no-floor")
    no_floor_serve = script.find("llama-server --host", no_floor_at)
    assert "llama-server --version" not in script[no_floor_at:no_floor_serve]

    stripped = "\n".join(
        line
        for line in script.splitlines()
        if "llama-server --version" not in line
        and "_obs=" not in line
        and "_req=" not in line
        and "strictly greater" not in line
        and "# preflight:" not in line
        and "cannot parse llama-server runtime build" not in line
    )
    with pytest.raises(AssertionError):
        _assert_runtime_build_preflight(
            stripped,
            floored_ids=["exact-floor", "lower-bound"],
            lower_bound_ids=["lower-bound"],
        )


def test_sealed_qwen_pair_emit_shell_has_lower_bound_preflight() -> None:
    registry = load_bakeoff_candidates()
    plans = build_plans(registry, **_PLAN_KW)
    floored = [plan for plan in plans if plan.min_runtime_build]
    assert [plan.candidate_id for plan in floored] == ["qwen38-27b", "qwen36-27b"]
    for plan in floored:
        assert plan.min_runtime_build == "b6887"
        assert plan.min_runtime_build_is_lower_bound is True
    script = emit_shell(plans, incumbent_runs={})
    _assert_runtime_build_preflight(
        script,
        floored_ids=["qwen38-27b", "qwen36-27b"],
        lower_bound_ids=["qwen38-27b", "qwen36-27b"],
    )


def test_emit_shell_stamps_cold_load_and_leaves_warmup_to_bakeoff() -> None:
    script = emit_shell(build_plans(_sample_registry(), **_PLAN_KW), incumbent_runs={})
    assert "_t0=$(date +%s.%N)" in script
    assert '_cold=$(python3 -c "import time;print(round(time.time()-$_t0,1))")' in script
    assert '--cold-load-s "${_cold}"' in script
    assert "# warm-up:" in script
    assert "bakeoff --warmup" in script
    assert "this shell does not send extra requests" in script
    assert "_t0=$(date +%s.%N)" in script.split("llama-server --host")[0] or script.index(
        "_t0=$(date +%s.%N)"
    ) < script.index("llama-server --host")


def test_emit_shell_echoes_nvidia_smi_sanity_after_run() -> None:
    script = emit_shell(build_plans(_registry([_entry("alpha")]), **_PLAN_KW), incumbent_runs={})
    assert "command -v nvidia-smi" in script
    assert "nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits" in script
    run_at = script.find('--cold-load-s "${_cold}"')
    smi_at = script.find("nvidia-smi --query-gpu=memory.used")
    kill_at = script.find('kill "${_serve_pid}"', smi_at)
    assert run_at != -1 and smi_at != -1 and kill_at != -1
    assert smi_at < kill_at


def test_emit_shell_polls_every_second_and_stamps_cold_inside_ready_branch() -> None:
    # VLM6-RV3-Q2-02: first /v1/models success stamps _cold before break, 0.1s resolution.
    script = emit_shell(build_plans(_registry([_entry("alpha")]), **_PLAN_KW), incumbent_runs={})
    assert f"sleep {READY_SLEEP_S}" in script
    assert READY_SLEEP_S == 1
    assert f"seq 1 {READY_ATTEMPTS}" in script
    assert READY_ATTEMPTS == 600
    ready_at = script.find("_ready=1")
    cold_at = script.find("_cold=$(python3 -c")
    break_at = script.find("break", ready_at)
    assert ready_at != -1 and cold_at != -1 and break_at != -1
    assert ready_at < cold_at < break_at
    assert "round(time.time()-$_t0,1)" in script
    assert "round(time.time()-$_t0,3)" not in script
    assert "cold-load resolution" in script
    assert 'if [ -n "${_cold}" ]' in script
    assert '|| _cold=""' in script


def test_emit_shell_cold_stamp_uses_python3_and_survives_without_python(tmp_path) -> None:
    # VLM6-RV3-Q4-02: no bare `python -c`; missing measurement is empty, never a crash.
    plans = build_plans(_registry([_entry("alpha")]), **_PLAN_KW)
    script = emit_shell(plans, incumbent_runs={})
    assert "python -c" not in script
    assert "python3 -c" in script
    path = tmp_path / "plan.sh"
    path.write_text(script, encoding="utf-8")
    syntax = subprocess.run(["bash", "-n", str(path)], check=False, capture_output=True, text=True)
    assert syntax.returncode == 0, syntax.stderr

    lines = script.splitlines()
    start = next(idx for idx, line in enumerate(lines) if line.startswith("for _i in"))
    end = next(idx for idx, line in enumerate(lines) if idx > start and line == "done")
    poll = "\n".join(lines[start : end + 1])
    snippet = "\n".join(
        [
            "set -euo pipefail",
            "_t0=$(date +%s.%N)",
            "_serve_pid=$$",
            '_cold=""',
            poll,
            'if [ -n "${_cold}" ]; then echo "COLD=${_cold}"; else echo COLD_EMPTY; fi',
        ]
    )
    stub_bin = tmp_path / "stub"
    stub_bin.mkdir()
    curl = stub_bin / "curl"
    curl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    curl.chmod(0o755)
    ran = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", snippet],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": f"{stub_bin}:/usr/bin:/bin"},
    )
    assert ran.returncode == 0, ran.stderr + ran.stdout
    assert ran.stdout.startswith("COLD=")
    stamped = ran.stdout.strip().removeprefix("COLD=")
    assert re.fullmatch(r"\d+\.\d", stamped), stamped


_BARE_PYTHON_M = re.compile(r"(^|[^0-9a-z_])python -m")


def test_plan_and_report_argv_use_python3_not_bare_python() -> None:
    # VLM6-RV3-Q4-02 residual: GPU host PATH has python3, not bare python.
    plans = build_plans(_registry([_entry("alpha")]), **_PLAN_KW)
    assert plans
    for plan in plans:
        assert plan.run_argv[0] == "python3"
        assert plan.run_argv[:3] == ("python3", "-m", "scripts.eval_harness.bakeoff")
    report_argv = _report_argv(plans, {})
    assert report_argv[0] == "python3"
    assert report_argv[:3] == ["python3", "-m", "scripts.eval_harness.build_bakeoff_report"]
    script = emit_shell(plans, incumbent_runs={})
    assert _BARE_PYTHON_M.search(script) is None, script
    assert "python3 -m scripts.eval_harness.bakeoff" in script
    assert "python3 -m scripts.eval_harness.build_bakeoff_report" in script
