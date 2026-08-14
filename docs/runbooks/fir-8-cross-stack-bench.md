# FIR-8 cross-stack bench — operator runbook

## Live E2E is BLOCKED

**Live run path is BLOCKED until FIR23-STACK delivers `acx-dev-fir`.**

The `acx-dev-fir` stack does not exist in this environment. Only the mocked/unit path is verified and mergeable. A live head-to-head is an **operator gate**, not a CI result. Do not treat a green unit suite as a live pass.

Framing: *Live E2E blocked; unit/mocked path still merges; live run is operator gate.*

FIR23-STACK is **BLOCKING** for live runs (unit tests unblocked).

---

## 1. Purpose + license posture

Score InsightFace (dev stack, 512-D buffalo_l) vs the FIR candidate (`acx-dev-fir`, 128-D face_pipeline / SFace) on the **same corpus** by driving both stacks over public APIs and scoring public exports with FIR-5 face metrics.

**License (mandatory):**

- The insightface / buffalo_l stack is **INTERNAL BENCH ONLY** (NC weights).
- Never user-facing. Never commercial product ingress. Never a customer-tenant key on that stack.
- Outputs must **never** become training data.
- Every `run.json`, export JSON, `score/frames.json`, and HTML report stamps `license_banner` with that sense.

---

## 2. Prerequisites

| Need | Status |
| --- | --- |
| FIR23-STACK `acx-dev-fir` up next to the existing insightface dev stack | **BLOCKED** — stack not delivered |
| Dev stack (`acx-dev-insightface`) healthy at `https://dev.api.altcontext.com` | operator |
| `ACX_BENCH_DEV_API_KEY` / `ACX_BENCH_DEV_TENANT_ID` | scratch/bench tenant only |
| `ACX_BENCH_FIR_API_KEY` / `ACX_BENCH_FIR_TENANT_ID` | scratch/bench tenant only |
| Golden-schema v2 manifest + `--images-dir` corpus root | operator / VLM-6; not vendored here |
| Package root | `apps/prototype-description-service` on `PYTHONPATH` (run all commands from that directory) |

Unit/mocked verification (does **not** require live stacks):

```bash
# from apps/prototype-description-service
uv run --extra dev pytest scripts/bench/tests/ -q
uv run --extra dev pytest scene/tests/test_eval_harness_face_metrics.py
```

---

## 3. Preflight

Working directory: `apps/prototype-description-service`.

```bash
uv run python -m scripts.bench.cross_stack_bench preflight --config stack-pair.yaml
```

Optional: write per-leg `preflight.json` under a run-dir:

```bash
uv run python -m scripts.bench.cross_stack_bench preflight --config stack-pair.yaml --out ../../benchmarks/results/crossbench-<stamp>/
```

Fails closed on auth (`preflight_auth_failed`), missing routes (`preflight_endpoint_missing`), profile/dim drift (`profile_or_dim_drift`), or unattested `opencv_major` (`opencv_major_unattested`). No partial `preflight.json` on those failures.

**Live preflight against `acx-dev-fir` is blocked** until FIR23-STACK stands that stack up.

---

## 4. Run

Working directory: `apps/prototype-description-service`. `--out` resolves to the repository-level `benchmarks/results/` tree.

```bash
uv run python -m scripts.bench.cross_stack_bench run --config stack-pair.yaml --manifest <manifest.json> --images-dir <corpus-root> --out ../../benchmarks/results/crossbench-<stamp>/
```

Flow: ingest → analyze → cluster → export persist. Resume is append-only via `legs/<stack_id>/items.jsonl`.

**Do not run this against live endpoints until `acx-dev-fir` exists.** A mocked/unit path is the only verified path in this task.

---

## 5. Status

Working directory: `apps/prototype-description-service`. Reads the run-dir only; **no network**.

```bash
uv run python -m scripts.bench.cross_stack_bench status --run-dir ../../benchmarks/results/crossbench-<stamp>/
```

---

## 6. Score

Working directory: `apps/prototype-description-service`. Offline; **no credentials / no network**. Fails if either leg's cluster phase is missing or non-success. Writes `score/accepted_set.json`, `score/attrition.json`, `score/frames.json`, `score/report.html`.

```bash
uv run python -m scripts.bench.cross_stack_bench score --run-dir ../../benchmarks/results/crossbench-<stamp>/
```

---

## 7. Teardown

**Only** FIR23-STACK's documented stack-scoped DB reset for `acx-dev-fir` (and optional dev bench-tenant cleanup).

Placeholder until that command is stable:

> See FIR23-STACK runbook §reset

Do **not** invent `DROP DATABASE` one-liners here.

---

## 8. Failure routing

| Symptom | Owner |
| --- | --- |
| Stack down, wrong dim in compose, missing ingress, reset path broken | **FIR23-STACK** |
| CLI logic, scoring, accepted-set / bootstrap / tiers | **FIR-8** |
| Need embedding-export / landmark diagnostic for purity sweeps | optional upstream task (not FIR-8) |

---

## 9. Verification checklist

- [ ] Unit/mocked suite green (`scripts/bench/tests/` and `scene/tests/test_eval_harness_face_metrics.py`)
- [ ] **Live path still blocked** — do not tick this as a live pass
- [ ] When FIR23-STACK delivers `acx-dev-fir`: both preflights green
- [ ] Report path exists under `benchmarks/results/crossbench-<stamp>/score/`
- [ ] Both sampling frames (`frame_e2e`, `frame_fir5_native`) and both label maps present
- [ ] `license_notice` / `license_banner` present; insightface not referenced as a product path
- [ ] Stacks reset via FIR23-STACK §reset only

---

## Residual risks

| Residual | Note |
| --- | --- |
| **`opencv_major` is operator-attested, not service-reported** | A wrong attestation produces a confident-looking but false provenance stamp. Required field; `opencv_major_source: operator_attested`. **Upstream ask (not FIR-8):** add `opencv_version` to `/health/detailed` `model_cache` so preflight can set `opencv_major_source: service_reported` and fail closed on disagreement. Until that field lands, OpenCV major drift between legs is undetectable. |
| Live E2E blocked on FIR23-STACK | Unit/mocked path still merges; live run is operator gate |
| No public embeddings | Clustering purity sweeps are out of scope |

---

## CLI `--help` (rg-006)

Commands above match:

```text
usage: scripts.bench.cross_stack_bench [-h] {preflight,run,status,score} ...
    preflight           Fail-closed health/profile/dim check
    run                 ingest → analyze → cluster → export both legs
    status              read run-dir only; no network
    score               offline score on run-dir (no credentials)
```

All invocations are from `apps/prototype-description-service`.
