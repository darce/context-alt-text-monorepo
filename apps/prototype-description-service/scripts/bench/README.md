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

`score` is offline (no credentials / no network).

## Tests

```bash
uv run --extra dev pytest scripts/bench/tests/ -q
uv run --extra dev pytest scene/tests/test_eval_harness_face_metrics.py
```
