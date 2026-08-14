# `scripts.bench` — FIR-8 cross-stack bench

Operator CLI that drives two named stacks (insightface@512 vs face_pipeline@128) over public APIs, persists exports, and scores offline with FIR-5 face metrics.

**Live E2E is BLOCKED** until FIR23-STACK delivers `acx-dev-fir`. Only the mocked/unit path is verified. See the runbook: [`docs/runbooks/fir-8-cross-stack-bench.md`](../../../../docs/runbooks/fir-8-cross-stack-bench.md).

## License

InsightFace / buffalo_l is **INTERNAL BENCH ONLY**. Never user-facing. Never training data.

## Commands

From `apps/prototype-description-service`:

```bash
uv run python -m scripts.bench.cross_stack_bench --help
uv run python -m scripts.bench.cross_stack_bench preflight --config stack-pair.yaml
uv run python -m scripts.bench.cross_stack_bench run --config stack-pair.yaml --manifest <manifest.json> --images-dir <corpus-root> --out ../../benchmarks/results/crossbench-<stamp>/
uv run python -m scripts.bench.cross_stack_bench status --run-dir ../../benchmarks/results/crossbench-<stamp>/
uv run python -m scripts.bench.cross_stack_bench score --run-dir ../../benchmarks/results/crossbench-<stamp>/
```

`score` is offline (no credentials / no network). It refuses a run-dir whose legs lack `preflight.json`.

`run` must be invoked from a **git checkout** of the monorepo (`init_run_dir` fails closed with `provenance_sha_unavailable` otherwise).

### Fail-closed codes operators hit on the live path

| Code | When |
| --- | --- |
| `stack_media_id_missing` | analyze payload has no integer `media_id` / `stack_media_id` |
| `provenance_sha_unavailable` | git SHA for the bench/harness tree is unavailable (no checkout) |
| `join_row_missing` | score join hole (path or media_id has no metric row) |
| `bootstrap_series_mismatch` | named cell's paired bootstrap series missing or length-mismatched |
| `bootstrap_status` | cell stamp / demotion reason; `!= ok` on the primary or a Holm secondary demotes CONFIRMATORY |
| `bootstrap_status_missing` | `assign_tier` raises if a confirmatory-eligible ctx omits the stamp (not a demotion) |
| `export_envelope_invalid` | export is not a bare JSON array (object envelopes are rejected) |
| `preflight_missing` | score-time: a leg has no `preflight.json`; recover with `preflight --config <stack-pair.yaml> --out <run-dir>` |
| `preflight_invalid` | score-time: `preflight.json` is unreadable (incl. non-UTF-8), not an object, or missing PROV-01 keys (key-presence only). `frames.json` `preflight_present` means present-and-structurally-valid. |
| `leg_outcome_unreadable` | `leg_outcome.json` exists but is torn / not JSON |

See the plan's [stable error codes table](../../../../docs/tasks/fir/FIR-8-recognition-profile-bench-toggle-task-plan.md#stable-error-codes-normative) and the runbook §4 failure modes.

## Tests

```bash
uv run --extra dev pytest scripts/bench/tests/ -q
uv run --extra dev pytest scene/tests/test_eval_harness_face_metrics.py
```
