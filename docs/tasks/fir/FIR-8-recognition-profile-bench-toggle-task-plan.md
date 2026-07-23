# FIR-8. Cross-stack face-pipeline bench orchestration

> **Metadata**
>
> - **Date**: 2026-07-23
> - **Author**: Grok (docs-only plan authoring)
> - **Plan version**: v6 — supersedes in-service bench supervisor (v5); re-scopes to cross-stack orchestration aligned with FIR23-STACK + QA v2
> - **Projects**: `scripts/bench/` (primary, new); consumes `apps/prototype-description-service/scripts/eval_harness/` (FIR-5, merged); **no** recognition-service code changes
> - **Task ID**: `FIR-8`
> - **Target Branch**: `feature/fir-8`
> - **Epic**: [E22 Commercial Face Identity Replacement](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Depends on (BLOCKING)**: **FIR23-STACK** delivers the running `acx-dev-fir` stack (compose project, network, DB `alt_context_dev_fir` @ `PGVECTOR_DIM=128`, ingress `fir.api.altcontext.com`) standing next to the existing dev stack (512-D insightface). FIR-4 (runtime factory + profile seam, merged). FIR-5 harness (bake-off scoring / score-face surfaces, merged to main @`07f9a5d1`).
> - **House style note**: Structure follows the TASK_PLAN template (objective → constraints → slices with named files/functions + proof). Junior-executable contracts; no finding lists; no status trailers.
> - **Review Coverage Target**: 2
> - **Isolation track (LOCKED)**: **per-model isolated stacks** (FIR23-STACK) — not a runtime profile toggle, not an in-service supervisor
> - **Execution mode (LOCKED)**: **operator CLI** drives both stacks over public APIs; wall-clock + queued-age budgets enforced by the CLI (not a service supervisor)

## Objective

Score **InsightFace** (dev stack, 512-D buffalo_l) vs **FIR candidate** (`acx-dev-fir` stack, 128-D face_pipeline / SFace) head-to-head on the **same corpus** by driving **both** stacks over their public APIs and scoring exports with the merged FIR-5 harness.

Deliverable: a **bench-orchestration CLI** + **scoring path** + **operator runbook**. **No recognition-service code changes.** Stack deploy/compose/Caddy/systemd ownership stays with FIR23-STACK.

## Intake

- **Operator ask**: measure the quality gap between buffalo_l (internal-bench only) and the commercial candidate face_pipeline on a fixed corpus, with honest cascade denominators and per-run provenance — without mixing embedding spaces in one DB.
- **Ground truth (operator-accepted)**:
  1. **One vector space per (modality, model)** — canon EMB-01 / IDX-02 + QA doc digest (`benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` §per-modality tables): buffalo_l=512-D and SFace=128-D **cannot share a DB**; each DB is dimension-pinned by `PGVECTOR_DIM` (three-way guard in `face_pipeline_adapter.py`); clusters are model-specific materialized outputs. Cross-model reads = mixed-space garbage.
  2. **FIR23-STACK already owns the deployment answer**: profile-pinned isolated stacks side-by-side, **not** a per-request profile header or in-process dual-dim toggle.
  3. Therefore v5's in-service async bench supervisor is the **wrong layer** — it duplicates exclusivity/teardown that stack isolation already provides and collides with FIR23-STACK ownership. Supersession: [Superseded: v5 in-service vehicle](#superseded-v5-in-service-vehicle).
- **Key Q&A decisions**: decision **#2951** (supersede in-service supervisor; re-scope to cross-stack orchestration). Isolation mode locked by FIR23-STACK deployment design, not re-litigated here.
- **Not-Doing**: [Non-goals](#non-goals).

## Problem Statement

Operators need a head-to-head score of insightface (512-D) vs face_pipeline (128-D) on one corpus. Same-process dual-profile and same-DB dual-dim are structurally impossible ([EMB-01], [IDX-02]). Isolated stacks (FIR23-STACK) solve space separation. What remains is **orchestration**: enroll + scan the same media on both endpoints, export clusters/assignments, score with FIR-5, emit a tier-labeled report — without inventing a parallel scorer or mutating recognition service code.

## Constraints

- **No recognition-service code changes** in this task. No new `/admin/bench/*` routes, no `recognition_bench_runs` table, no scan_worker supervisor tick, no boot-coupled bench license gate inside the worker/API process.
- **FIR23-STACK owns deploy surfaces.** Compose projects, networks, DB names, Caddy/ingress, systemd units, and stack-scoped DB reset paths are FIR23-STACK. If a stack gap blocks a bench run, **route to FIR23-STACK** — do not expand this plan into infra ownership.
- **One vector space per stack** ([EMB-01], [IDX-02]). CLI preflight **fails closed** when either stack drifts from its pinned `(profile, dim)` pair.
- **Reuse FIR-5 scoring** (merged @`07f9a5d1`). Map exports into existing `score-face` / bakeoff report surfaces under `scripts/eval_harness/`. Do not invent a parallel scorer.
- **License**: insightface / buffalo_l stack is **INTERNAL BENCH ONLY** (NC weights). Outputs never become training data; never user-facing/commercial ([RLSE-05], QA digests §buffalo-as-judge).
- **Boundary honesty** ([rg-015]): when normalizing the two stacks' API payloads, every envelope field (`limit`, `offset`, `total`, status/projection metadata) comes from the request, the upstream payload, or a **named** documented constant — never `count(payload)` invention.
- **Cascade honesty** ([EVAL-16]): a face a stack's detector missed counts as an identification error end-to-end in the head-to-head report.
- **Fixed denominators** ([EVAL-19]): both legs share the same accepted media set / labeled face denominators; do not shrink denominators per leg after partial detection failure.
- **Per-run provenance** ([PROV-01]): every report stamps stack identity (base URL / compose project name), model ids, `PGVECTOR_DIM`, corpus hash, CLI + harness code SHAs.
- **Canon**: heuristics v0.12.3; distilled refs `~/Development/heuristics-canon-research/distilled/ml-systems/janus-benchmark-c.md` (pooling-unit / cascade eval), `handbook-face-recognition.md`.

## Workflow Principles

- **Drive stacks as black boxes** via public HTTP APIs already used by `scripts/eval_harness/remote_client.py` (`analyze`, `wait_job`, `media_identities`, `clusters`, `cluster_members`). Prefer extending that client or a thin wrapper in `scripts/bench/` over ad-hoc curl.
- **CLI is the supervisor.** Wall-clock budget + per-item / queued-age timeouts live in the CLI process. No service-side single-live-run index.
- **Idempotent resume.** Per-item ingest/scan outcomes persist under the run directory so a crashed run continues without double-billing work that already succeeded.
- **Fail closed on preflight drift.** Dimension or profile mismatch on either stack aborts before any media write.
- **Stack gaps escalate out.** Missing ingress, wrong dim in compose, broken reset path → FIR23-STACK ticket / decision, not a FIR-8 code fork into deploy YAML.

## Terminology

| Term | Meaning in this plan |
| --- | --- |
| **Dev stack** | Existing recognition deployment: `RECOGNITION_FACE_PIPELINE_PROFILE=insightface`, `PGVECTOR_DIM=512`, public API base (operator-configured; typically the standard dev ingress). **Internal bench only** for commercial product posture. |
| **`acx-dev-fir` stack** | FIR23-STACK profile-pinned isolated stack: compose project + network + DB `alt_context_dev_fir` @ `PGVECTOR_DIM=128`, profile `face_pipeline`, ingress `fir.api.altcontext.com`. FIR candidate leg. |
| **Stack pair** | Named config binding both base URLs, API keys / tenant ids, expected `(profile, dim)` pairs, and optional LAN override flag for private media hosts. |
| **Corpus** | Fixed media set for a run (paths or resolvable HTTPS URLs). Accepted set = media that pass CLI validation before enroll. |
| **Leg** | Full enroll→scan→export path against **one** stack. A head-to-head run has two legs: `insightface@512` and `face_pipeline@128`. |
| **Superset baseline / accepted set** | Any uploaded or declared baseline / label artifact's `media_id` (or sha256) set **must be a SUPERSET** of the run's accepted set. Partial intersection = **blocker** (do not silently score a subset). |
| **Crossbench report** | Tier-labeled head-to-head artifact under `benchmarks/results/crossbench-<stamp>/` using FIR-5 tier vocabulary (`CONFIRMATORY` / `DIRECTIONAL` / `DIAGNOSTIC`). |
| **Named bench stacks** | Exactly the two stack identities listed in the stack-pair config (dev + `acx-dev-fir`). Production-shaped-data guard allows nonzero identity tables **only** on these two named stacks. |

## Current State Analysis

- **FIR23-STACK (parallel session, `feature/fir23-stack`)** owns isolated stack deploy: per-model stacks, not runtime toggles. That design **supersedes** per-request profile headers and the v5 in-service bench vehicle.
- **FIR-5 harness is on main** (`07f9a5d1`): face metrics, bake-off / score-face report surfaces, remote client, cluster export helpers under `apps/prototype-description-service/scripts/eval_harness/`. Reuse; do not fork.
- **Health / ready endpoints** already expose profile-aware readiness, active `embedding_model`, and pgvector dimension checks (`api/main.py` `register_health_probes`, `recognition/application/health.py` — `check_active_embedding_model`, typmod probe). CLI preflight consumes these; it does not re-implement probes inside the service.
- **Three-way dim guard** lives in `face_pipeline_adapter.py` / factory construction — each stack is already fail-closed on dim/profile mismatch **internally**. Cross-stack orchestration still needs an **external** preflight that both stacks match the **expected pair** for this bench (dev=512/insightface, fir=128/face_pipeline).
- **No `scripts/bench/` package yet.** This task creates it.
- **v5 plan** (recoverable at git `bc97ff4b`) specified an in-service async supervisor, `uq_bench_single_live`, purge-before-terminal, marker rail, boot-coupled license gate, tick contract. **Superseded** — see below. Do not re-implement.

## Target Outcome

1. Operator configures a stack-pair file pointing at dev + `acx-dev-fir` endpoints.
2. CLI preflight proves both stacks are healthy and match pinned `(profile, dim)`; fails closed on drift.
3. CLI enrolls + scans the same corpus on both stacks; persists per-item outcomes; resumes safely.
4. CLI exports clusters/assignments from both stacks, maps into FIR-5 scoring legs, emits a tier-labeled head-to-head report under `benchmarks/results/crossbench-*/` with provenance + cascade-honest denominators.
5. Runbook documents license posture, preflight, run, score, and **stack-scoped teardown** via FIR23-STACK's documented reset path (not a new FIR-8 reset invention).
6. Zero recognition-service source edits land in this task's commits.

## Context Loading (read before implementation)

| Order | Path | Why |
| --- | --- | --- |
| 1 | This plan (v6) end-to-end | Locked scope, dependency boundary, carried invariants, slices |
| 2 | `apps/prototype-description-service/scripts/eval_harness/remote_client.py` | Existing HTTP client (`analyze`, `wait_job`, `media_identities`, `clusters`, …) |
| 3 | `apps/prototype-description-service/scripts/eval_harness/face_metrics.py` + `cli.py` + bakeoff / score-face report surfaces (FIR-5 on main) | Scoring legs — map exports here |
| 4 | `apps/prototype-description-service/api/main.py` `register_health_probes` + `recognition/application/health.py` | Preflight fields from `/ready` and `/health/detailed` |
| 5 | `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` | Production-shaped-data table set (`tenants`, `media_identities`, `identity_clusters`, `identity_members`) |
| 6 | FIR23-STACK runbook / compose docs (when present on that branch) | Stack endpoints, reset path, network names — **consume, do not fork** |
| 7 | QA digest (authoritative for this lane): one space per (modality, model); buffalo = internal judge only; EVAL-16 / EVAL-19 / PROV-01 discipline | Ground truth that forced v6 re-scope |
| 8 | Distilled canon: `janus-benchmark-c.md`, `handbook-face-recognition.md` | Cascade / pooling-unit eval discipline |

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Recognition public API | description-service | existing analyze / clusters / media / health routes | **none** (read + existing write paths only) | n/a — consumer only | CLI integration uses recorded fixtures / mocks |
| FIR-5 eval harness | `scripts/eval_harness/` | score / bakeoff / face_metrics surfaces | **thin adapter** in `scripts/bench/` mapping stack exports → harness input shapes; no harness fork unless a documented gap is fixed upstream with rationale | yes — adapter must not invent envelope fields ([rg-015]) | unit tests + one mocked E2E |
| Stack deploy / reset | **FIR23-STACK** | isolated compose + DB + ingress | **none in FIR-8** | n/a | runbook cites FIR23-STACK commands only |
| WP plugin | WP | n/a | **none** | n/a | grep-clean of plugin paths in this task |

## Proposed Solution

A new package under **`scripts/bench/`** (repo root or description-service scripts tree — pin: **`scripts/bench/cross_stack_bench.py`** at the monorepo path used by other operator scripts; import FIR-5 via the description-service package path already used by eval harness).

```text
scripts/bench/
  cross_stack_bench.py          # CLI entry (argparse subcommands)
  stack_pair.py                 # load + validate stack-pair config
  preflight.py                  # health + dim + profile checks (fail-closed)
  corpus.py                     # accept set, media source pin, per-item outcomes
  driver.py                     # enroll + scan both stacks; resume
  export_map.py                 # pull clusters/assignments; map to FIR-5 shapes
  score_report.py               # invoke FIR-5 legs; write crossbench report dir
  production_shaped_guard.py    # refuse non-named stacks with nonzero core tables
  tests/                        # unit + one mocked E2E
docs/runbooks/
  fir-8-cross-stack-bench.md    # operator runbook (S3)
benchmarks/results/crossbench-*/  # gitignored run outputs
```

**Operator flow**

1. Confirm FIR23-STACK has `acx-dev-fir` healthy next to dev.
2. `cross_stack_bench preflight --config stack-pair.yaml` → both sides green or abort.
3. `cross_stack_bench run --config … --corpus … --out benchmarks/results/crossbench-<stamp>/` → enroll+scan both legs with resume file.
4. `cross_stack_bench score --run-dir …` → FIR-5 legs + head-to-head HTML/JSON.
5. Teardown: FIR23-STACK stack-scoped DB reset for the FIR stack (and optional dev-bench tenant wipe per runbook) — **not** a new recognition purge phase.

---

## Superseded: v5 in-service vehicle

v5 specified an **in-service** async single-live-run bench supervisor inside the recognition worker: state machine over `recognition_bench_runs`, `uq_bench_single_live`, purge-before-terminal, deployment marker rail, boot-coupled license gate, non-blocking tick contract, and `/admin` bench routes. That vehicle is **superseded** by **per-model isolated stacks** (FIR23-STACK): exclusivity, no mixed-space reads, and teardown via stack-scoped DB reset are structural properties of the deploy topology, not application supervisor features. Re-implementing them inside the worker would duplicate FIR23-STACK ownership and re-open dual-space foot-guns. **Do not delete git history** — v5 plan text is recoverable at commit **`bc97ff4b`**. Decision **#2951** records the supersession. The rest of this document is the v6 scope only.

---

## Carried-forward invariants (orchestration layer)

Adapt v5 review-hardened invariants; **do not re-litigate**. Enforcement lives in the **CLI**, not the recognition service.

### CF-1. Baseline / corpus ingest contract

- Uploaded or declared baseline / label artifact `media_id` (or content-sha) set **must be a SUPERSET** of the run's accepted set. **Partial intersection = blocker** (exit non-zero; do not score a silent subset).
- **Per-item ingest outcomes** persist under the run directory (`items.jsonl` or equivalent): `media_id`, outcome (`ok`/`failed`), optional `error_code`, `content_sha256` when ok — so resume never loses hard-fail tallies.
- **Pinned resolved-address SET** for each media source host: at enroll, resolve full address set and persist; at fetch, connect only to pinned addresses (anti DNS-rebinding).
- **Public-unicast enforcement**: reject link-local, RFC1918, loopback unless explicit **`allow_private_source: true`** LAN override in stack-pair config (operator-acked residual).

### CF-2. Production-shaped-data guard

Refuse to run against a stack whose core identity-adjacent tables are **nonzero** unless the stack is one of the **two named bench stacks** in the stack-pair config.

Enumerate from `001_identity_schema.py` (same set as v5):

| Table | Role |
| --- | --- |
| `tenants` | tenant root |
| `media_identities` | embedding/identity media rows |
| `identity_clusters` | cluster/person-like entities |
| `identity_members` | cluster membership edges |

Implementation note: the CLI does **not** open a raw production DB URL for arbitrary hosts. Prefer an **operator-exported** table-count snapshot endpoint **only if already present**; otherwise the runbook requires FIR23-STACK / operator attestation that the target is a named bench stack, and the CLI checks a **stack identity allowlist** (compose project name / configured `stack_id`) before any write. If a future stack admin diagnostic exposes counts, consume it without inventing envelope fields ([rg-015]). **Do not** query `handoff.db` or invent SQL against unknown DSNs.

### CF-3. License posture

- Insightface / buffalo_l leg: **INTERNAL BENCH ONLY** (NC weights; QA §buffalo-as-judge — judge / acceptance-bar use only).
- Outputs **never** become training data.
- Runbook **forbids** exposing the insightface stack to any commercial or user-facing path (no public product ingress, no customer tenant keys on that stack for product traffic).
- Reports always carry `license_notice` with that sense.

### CF-4. Bounded runs

- Wall-clock budget per bench run (config: `wall_clock_timeout_sec`, default **3600**).
- Queued-age / per-job poll budget (config: `job_poll_timeout_sec`, default **600**; align with `RemoteSceneClient` poll bounds).
- Enforced by the **CLI** (cancel outstanding polls, write partial outcomes, exit non-zero) — **not** a service supervisor.

### CF-5. Scoring discipline (QA + canon)

- [EVAL-16] cascade honesty in the head-to-head report.
- [EVAL-19] fixed denominators across stacks.
- [PROV-01] per-run provenance: stack identity, model ids, corpus hash, code SHAs.
- Tier labels from FIR-5: `CONFIRMATORY` / `DIRECTIONAL` / `DIAGNOSTIC` — do not invent new tier names.

---

## Non-goals

- **No recognition-service code changes** (API, worker, schema, admin console).
- **No compose / Caddy / systemd / ingress ownership** — FIR23-STACK.
- **No in-service bench supervisor**, `recognition_bench_runs`, marker rail, or purge-before-terminal phases.
- **No same-process dual-profile toggle**; no Option B wipe/flip.
- **No parallel scorer** replacing FIR-5.
- **No WP control surface**.
- **No commercial / user-facing exposure** of the insightface stack.
- **No training-data export** from bench outputs.
- **No escalation-ladder implementation** (scope/epic contingent ladder remains a separate task id if still reserved — out of this plan's code path).

---

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| tooling (new) | `scripts/bench/cross_stack_bench.py` | CLI entry: `preflight`, `run`, `score`, `status` subcommands |
| tooling (new) | `scripts/bench/stack_pair.py` | Load/validate YAML/JSON stack-pair config |
| tooling (new) | `scripts/bench/preflight.py` | Dual-stack health + dim + profile assertions |
| tooling (new) | `scripts/bench/corpus.py` | Accept set, pin sets, superset check, per-item outcomes |
| tooling (new) | `scripts/bench/driver.py` | Enroll + scan driver with resume |
| tooling (new) | `scripts/bench/export_map.py` | Export clusters/assignments; map to FIR-5 shapes ([rg-015]) |
| tooling (new) | `scripts/bench/score_report.py` | Invoke FIR-5 legs; write `benchmarks/results/crossbench-*/` |
| tooling (new) | `scripts/bench/production_shaped_guard.py` | Named-stack allowlist + optional count attestation |
| tests (new) | `scripts/bench/tests/test_preflight.py` | Fail-closed dim/profile drift |
| tests (new) | `scripts/bench/tests/test_corpus_superset.py` | Superset / partial-intersection blocker |
| tests (new) | `scripts/bench/tests/test_resume.py` | Resume idempotency |
| tests (new) | `scripts/bench/tests/test_e2e_mocked.py` | One mocked end-to-end (both legs → report dir) |
| docs (new) | `docs/runbooks/fir-8-cross-stack-bench.md` | Operator runbook + teardown + license |
| docs (edit) | this plan | v6 re-scope (this commit) |

**Explicitly untouched:** `apps/prototype-description-service/recognition/**`, `db/migrations/**`, WP plugin, FIR23-STACK compose/deploy files.

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/scripts/eval_harness/remote_client.py` | Prefer reuse / thin wrap for HTTP |
| `apps/prototype-description-service/scripts/eval_harness/face_metrics.py` | Face P/R pure functions |
| `apps/prototype-description-service/scripts/eval_harness/cli.py` | Existing fetch/score patterns |
| `apps/prototype-description-service/recognition/application/health.py` | Preflight field sources |
| `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` | Core identity-adjacent table list |
| git `bc97ff4b` | Recoverable v5 plan text (superseded) |

## Verification Strategy

### Deterministic tests (required)

```bash
# from repo root / description-service as appropriate for package layout chosen in S1
python -m pytest scripts/bench/tests/ -q
```

Must cover:

1. **Preflight fail-closed** — mock `/ready` (or client) so dev reports dim≠512 or profile≠insightface → exit/exception with stable code `profile_or_dim_drift`; same for fir leg (expect 128 / face_pipeline).
2. **Superset blocker** — accepted `{1,2,3}`, baseline `{1,2}` → blocker; accepted `{1,2}`, baseline `{1,2,3}` → pass.
3. **Resume idempotency** — after partial `items.jsonl`, re-run does not re-POST successful media; failed items retry once within budget.
4. **One mocked E2E** — fake dual clients return fixed cluster payloads → report dir contains provenance + both legs + tier label; no network.

### Runtime-parity / operator checks (S3 runbook)

- Live preflight against real dev + `acx-dev-fir` when stacks are up (operator session; not CI-blocking if stacks absent).
- Stack-scoped reset via **FIR23-STACK documented command** after a run (cite exact command from that plan/runbook when available; placeholder section until FIR23-STACK docs land — **do not invent** reset SQL).

### Contract / fixture

- Export mapper unit test: fixture payloads with pagination fields only from upstream; assert adapter does not set `total=len(data)` unless upstream provided `total` ([rg-015]).

### Manual

- Operator opens head-to-head report; confirms `license_notice` present; confirms insightface stack not referenced as product path.

---

## Slice Delivery

### Slice 1: Bench CLI skeleton — config, preflight, corpus driver

**Goal**: Runnable CLI that validates a stack pair, fails closed on dim/profile drift, and drives corpus enroll+scan on both stacks with durable per-item outcomes and resume.

**Files / functions (normative names)**

| Module | Symbols | Responsibility |
| --- | --- | --- |
| `scripts/bench/stack_pair.py` | `load_stack_pair(path) -> StackPairConfig`, `StackEndpoint` dataclass | Parse config; require keys: `stack_id`, `base_url`, `api_key` env ref, `tenant_id`, `expected_profile`, `expected_pgvector_dim`; reject unknown keys (fail-closed) |
| `scripts/bench/preflight.py` | `preflight_stack(client, endpoint) -> PreflightResult`, `preflight_pair(pair) -> None` | GET `/ready` + `/health/detailed` (or minimal fields the client already exposes); assert `expected_profile` + `expected_pgvector_dim`; raise `PreflightError` with stable codes |
| `scripts/bench/corpus.py` | `build_accepted_set(...)`, `assert_baseline_superset(accepted, baseline)`, `pin_media_hosts(...)`, `ItemOutcomeStore` | Superset blocker; public-unicast pin; JSONL outcome store |
| `scripts/bench/driver.py` | `run_leg(endpoint, items, outcome_store, *, budgets)`, `run_pair(...)` | For each stack: upload/analyze media via `RemoteSceneClient.analyze` + `wait_job`; respect wall-clock + poll budgets; write outcomes |
| `scripts/bench/production_shaped_guard.py` | `assert_named_bench_stack(endpoint, allowlist)` | Allow only configured stack_ids before writes |
| `scripts/bench/cross_stack_bench.py` | `main()`, subcommands `preflight` / `run` / `status` | argparse CLI |
| `scripts/bench/tests/test_preflight.py` | dim/profile drift cases | red first |
| `scripts/bench/tests/test_corpus_superset.py` | partial intersection | red first |
| `scripts/bench/tests/test_resume.py` | partial JSONL resume | red first |

**Stack-pair config shape (normative)**

```yaml
# example only — not a committed secret file
wall_clock_timeout_sec: 3600
job_poll_timeout_sec: 600
allow_private_source: false
stacks:
  - stack_id: acx-dev-insightface
    role: insightface_judge
    base_url: https://api.altcontext.com   # operator-local value
    expected_profile: insightface
    expected_pgvector_dim: 512
    api_key_env: ACX_BENCH_DEV_API_KEY
    tenant_id_env: ACX_BENCH_DEV_TENANT_ID
  - stack_id: acx-dev-fir
    role: face_pipeline_candidate
    base_url: https://fir.api.altcontext.com
    expected_profile: face_pipeline
    expected_pgvector_dim: 128
    api_key_env: ACX_BENCH_FIR_API_KEY
    tenant_id_env: ACX_BENCH_FIR_TENANT_ID
```

**Proof**

- `pytest scripts/bench/tests/test_preflight.py scripts/bench/tests/test_corpus_superset.py scripts/bench/tests/test_resume.py -q` green.
- Red-proofs: (1) force mock ready payload `pgvector_dimension=128` on insightface endpoint → preflight test fails if assertion removed; (2) baseline partial set → test fails if superset check deleted; (3) resume re-POSTs completed ids if outcome store ignored.

**Dependencies**: FIR23-STACK not required for unit tests (mocked). Live `run` requires both stacks up.

---

### Slice 2: Export + score via FIR-5

**Goal**: Pull clusters/assignments from both stacks, map into FIR-5 scoring legs, emit tier-labeled head-to-head report under `benchmarks/results/crossbench-*/`.

**Files / functions**

| Module | Symbols | Responsibility |
| --- | --- | --- |
| `scripts/bench/export_map.py` | `export_leg(client) -> LegExport`, `to_face_score_input(export, corpus) -> …` | Use `clusters` / `cluster_members` / `media_identities`; preserve upstream pagination fields; no invented `total` |
| `scripts/bench/score_report.py` | `score_head_to_head(run_dir) -> Path`, `write_provenance(...)` | Call FIR-5 `face_metrics` / score-face / bakeoff report builders already on main; write JSON + HTML under `benchmarks/results/crossbench-<stamp>/` |
| `scripts/bench/cross_stack_bench.py` | subcommand `score` | Wire score path |
| `scripts/bench/tests/test_export_map_rg015.py` | fixture without `total` must not gain fabricated total | [rg-015] |
| `scripts/bench/tests/test_e2e_mocked.py` | dual fake clients → report artifacts | one mocked E2E |

**Report must include**

- Both legs' detection / identification frames (null where labels absent — honest nulls, not `0.0` purity invention).
- Cascade-honest treatment ([EVAL-16]): detector miss → identification miss on that face.
- Shared denominators ([EVAL-19]).
- Provenance block ([PROV-01]): `stack_id`, `base_url`, `expected_profile`, `expected_pgvector_dim`, resolved `embedding_model` if exposed, corpus sha256, CLI git SHA, harness identity.
- `license_notice` for the insightface leg.
- Tier label from FIR-5 vocabulary.

**Proof**

- Mocked E2E green; export mapper rg-015 test green.
- Red-proof: strip provenance writer → test asserting provenance keys fails; set `total=len(rows)` in mapper → rg-015 test fails.

**Dependencies**: S1 complete. FIR-5 on main (already).

---

### Slice 3: Runbook + teardown

**Goal**: Operator-facing runbook covering license, preflight, run, score, and stack-scoped teardown via FIR23-STACK; verification commands copy-pasteable ([rg-006]).

**Files**

| File | Change |
| --- | --- |
| `docs/runbooks/fir-8-cross-stack-bench.md` | Full operator path (below) |
| `scripts/bench/README.md` | One-page pointer to runbook + CLI help |

**Runbook sections (normative outline)**

1. **Purpose + license posture** — insightface stack INTERNAL BENCH ONLY; never commercial/user-facing; outputs not for training.
2. **Prerequisites** — FIR23-STACK `acx-dev-fir` up; dev stack up; API keys for both scratch/bench tenants; corpus path.
3. **Preflight** — exact `python -m scripts.bench.cross_stack_bench preflight --config …` (adjust module path to S1 layout).
4. **Run** — `… run --config … --corpus … --out …`
5. **Score** — `… score --run-dir …`
6. **Teardown** — **only** FIR23-STACK's documented stack-scoped DB reset for `acx-dev-fir` (and optional dev bench-tenant cleanup). Placeholder: `See FIR23-STACK runbook §reset` until that doc's command is stable — **do not invent** `DROP DATABASE` one-liners here that disagree with FIR23-STACK.
7. **Failure routing** — stack health / dim wrong in compose → FIR23-STACK; CLI logic / scoring → FIR-8.
8. **Verification checklist** — both preflights green; report path exists; license_notice present; stacks reset.

**Proof**

- Runbook paths resolve (`test` or `make` doc link check if repo has one; else manual path exists check in S3).
- Commands match CLI `--help` (no broken copy-paste — [rg-006]).

**Dependencies**: S1–S2 CLI surface stable; FIR23-STACK reset command available or explicitly stubbed with "blocked on FIR23-STACK" note.

---

## Lane Decomposition

Single-lane work. No multi-agent lane split required.

---

## Consolidated Checklist

> Checklist describes **work**, not finding status. Query open findings via handoff DB.

### Context and Ownership

- [ ] Loaded this plan, eval_harness remote client, health probes, 001 schema table list, FIR23-STACK endpoint/reset docs.
- [ ] Confirmed no recognition-service files in the intended diff.
- [ ] FIR23-STACK dependency recorded as BLOCKING for live runs (unit tests unblocked).

### Checklist for Slice 1: Bench CLI skeleton

- [ ] `scripts/bench/` package + `cross_stack_bench.py` subcommands `preflight` / `run` / `status`
- [ ] `StackPairConfig` validates expected profile/dim pairs (dev: insightface/512; fir: face_pipeline/128)
- [ ] Preflight fail-closed on drift (stable error codes)
- [ ] Corpus accept set + baseline superset blocker + host pin set + public-unicast default
- [ ] Per-item outcome store + resume
- [ ] Wall-clock + job-poll budgets enforced in CLI
- [ ] Named-stack allowlist guard before writes
- [ ] Unit tests: preflight, superset, resume — each observed red first
- [ ] Handoff decision for S1 with verification commands

### Checklist for Slice 2: Export + score

- [ ] Export both legs via existing cluster/media APIs
- [ ] Mapper preserves upstream envelope fields ([rg-015])
- [ ] FIR-5 scoring legs invoked (no parallel scorer)
- [ ] Report under `benchmarks/results/crossbench-*/` with provenance, cascade honesty, fixed denominators, license_notice, tier label
- [ ] Mocked E2E + rg-015 unit test green
- [ ] Handoff decision for S2

### Checklist for Slice 3: Runbook + teardown

- [ ] `docs/runbooks/fir-8-cross-stack-bench.md` complete per outline
- [ ] License posture explicit; insightface non-exposure rule explicit
- [ ] Teardown cites FIR23-STACK reset only
- [ ] Failure routing table (stack gap → FIR23-STACK; CLI → FIR-8)
- [ ] Commands match CLI help ([rg-006])
- [ ] Handoff decision for S3 / task close path prepared

## Review Readiness

- [ ] No recognition-service or deploy-YAML changes slipped into the branch.
- [ ] Boundary adapters do not invent pagination/provenance metadata ([rg-015]).
- [ ] Live run path blocked in docs until FIR23-STACK delivers `acx-dev-fir` (not silently mocked as success).
- [ ] Handoff decisions record verification + dependency status.
- [ ] Review findings recorded in MCP only (never pasted into this plan).

## Stretch Goals

- [ ] Optional HTML index linking multiple historical crossbench runs.
- [ ] Prometheus/log-free local progress TUI — only if it does not expand scope past one slice.

## Success Criteria

- [ ] Operator can preflight + run + score a corpus against **both** stacks with **zero** recognition-service code changes in the FIR-8 diff.
- [ ] Preflight fails closed on dimension or profile drift for either stack.
- [ ] Superset / partial-intersection blocker enforced.
- [ ] Resume does not reprocess successful items.
- [ ] Head-to-head report exists under `benchmarks/results/crossbench-*/` with EVAL-16 / EVAL-19 / PROV-01 discipline and insightface license notice.
- [ ] Runbook forbids commercial exposure of the insightface stack and points teardown at FIR23-STACK.
- [ ] v5 in-service vehicle explicitly superseded (decision #2951; history at `bc97ff4b`).

## Residual risks (pinned)

| Risk | Residual | Mitigation |
| --- | --- | --- |
| FIR23-STACK delayed | Live E2E blocked | Unit/mocked path still merges; live run is operator gate |
| Health payload shape differs across deploys | Preflight false fail/pass | Pin field names to `/ready` + `/health/detailed` contract; fail closed on missing fields |
| Public-unicast pin vs LAN media store | Operator needs private fetch | Explicit `allow_private_source` only; documented residual |
| Production-shaped guard without DB counts API | Weaker than v5 marker rail | Named stack allowlist + operator attestation; escalate if FIR23-STACK adds a count diagnostic |
| Insightface NC misuse | License | Runbook + report `license_notice`; stack must not sit on product ingress |

---

## Canon citations (index)

| ID | Use in this task |
| --- | --- |
| EMB-01 / IDX-02 | One vector space per (modality, model); isolated stacks |
| EVAL-16 | Cascade honesty in head-to-head |
| EVAL-19 | Fixed denominators across legs |
| PROV-01 | Per-run provenance block |
| RLSE-05 / SERVE-03 | Insightface internal-bench only |
| rg-015 | No invented envelope metadata |
| rg-006 | Documented commands run as written |
| DIAG-08 | Live/strategy bench ≠ Golden-150 substitute (corpus still explicit; do not re-host Golden as only path) |
| Heuristics canon v0.12.3 | Governing revision |
| Distilled: `janus-benchmark-c.md`, `handbook-face-recognition.md` | Cascade / face-eval discipline |
