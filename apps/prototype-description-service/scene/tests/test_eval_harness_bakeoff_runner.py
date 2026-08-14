"""VLM-6 S2a-2: registry-driven bake-off planner (plan-only)."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from scripts.eval_harness import bakeoff
from scripts.eval_harness import build_bakeoff_report
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
    NotCompetingError,
    UnknownCandidateError,
    UnsupportedStackError,
    VramBudgetError,
    _report_argv,
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
            "sealed": {"candidates": 13, "incumbent_anchors": 2},
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
        entry.model_copy(update=updates, deep=True) if entry.id == entry_id else entry
        for entry in registry.entries
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
        assert plan.run_argv[:3] == ("python", "-m", "scripts.eval_harness.bakeoff")
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
    assert "seq 1 40" in script
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
        assert plan.run_argv[:3] == ("python", "-m", "scripts.eval_harness.bakeoff")
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
    assert argv[:3] == ["python", "-m", "scripts.eval_harness.build_bakeoff_report"]
    parsed = build_bakeoff_report.build_parser().parse_args(argv[3:])
    assert parsed.manifest == _PLAN_KW["manifest"]
    assert parsed.limit == 646
    assert parsed.run == [
        f"{plan.candidate_id}={plan.out_path}" for plan in plans
    ] + [
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
    non_llama = [
        entry
        for entry in registry.entries
        if entry.recipe.stack is not ServingStack.LLAMA_CPP
    ]
    assert non_llama
    for entry in non_llama:
        assert entry.id in err
        assert f"skip {entry.id} ({entry.recipe.stack.value})" in err
    assert "skipped 8 of 13 candidates (stack not supported by this planner)" in err


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
    registry = _registry(
        [_entry("gemma-like", artifact_gb=7.2, recipe=_recipe(mmproj_gb=0.18))]
    )
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
