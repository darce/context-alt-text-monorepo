# Task Plan — ORCH-LAUNCH-01 Production VLM & Launch Sequencing

> **Metadata**
>
> - **Date**: 2026-08-11
> - **Author**: Claude Opus 5
> - **Project**: apps/prototype-description-service · infra/oci · docs/gtm
> - **Task ID**: `ORCH-LAUNCH-01`
> - **Target Branch**: `feature/orch-launch-01`
> - **Review Coverage Target**: 2 (adversarial `/review-parallel`, one remote reviewer)
> - **Canon**: `~/Development/heuristics-canon-research` @ agent-index schema `heuristics-canon/agent-index@2` (1185 rules / 75 families / 36 routes)

---

## ORCH-LAUNCH-01. Ship a real description model, then ask for money

## Objective

Move production from the model-free `seeded` description adapter to a measured CPU-tier VLM behind a
shadow→canary rollout with a `seeded` fallback; instrument accept/edit on the output; retire the launch-blocking
worktree debt; and only then run the first paid-conversion motion. Explicitly defer the A10 GPU bake-off.

## Intake — the measurement that reorders the roadmap

Collected 2026-08-11 against live production, not inferred from the repo:

```
api.altcontext.com/health   200 (0.95s)
demo.altcontext.com/        200 (1.50s)
altcontext.com/             200 (0.74s)

acx-prod-api-1  $ env | grep ACX_DESCRIPTION   ->  (no output)
acx-prod-api-1  $ torch: False   transformers: False
host                                            23 GB total / 15 GB available / 7 GB used
containers: acx-{prod,staging,dev}-{api,worker,postgres} + caddy + acx-demo-{wordpress,mariadb}
```

`ACX_DESCRIPTION_ADAPTER` unset resolves to `seeded`, documented at
`apps/prototype-description-service/.env.prod.example:176` as "deterministic, instant, model-free (DEFAULT;
recognition image)". The prod image is torch-free, so the env var cannot simply be flipped — the `[vlm]` extra
runtime image does not exist for production.

**The entire public surface is live and serving placeholder alt text.** Every GTM slice — concierge
provisioning (AP-7/DS-3), target lists (LS-1), funnel telemetry (OB-1..3) — routes prospects into a demo that
does not perform the product's one job.

## Problem Statement

The launch plan is sequenced as if the product works. It does not yet. `seeded` was the correct first ship — the
deterministic baseline before ML, per AIPX-01 — and that step is complete. What is overdue is the step after it.
A public demo that silently returns placeholder output is the failure mode RLSE-05 names as the worst kind: not a
crash, which is honest, but a trust violation that looks like success. No amount of conversion instrumentation
raises the conversion rate of a bare product that does not deliver its value (GTM-13, PROD-01).

The limiting link is description quality in production (STRAT-22). Every other candidate next-action — GPU
quality headroom, recognition accuracy, funnel analytics, cost governance — improves a non-bottleneck link.

## Canon Grounding

Routes consulted via `tools/canon.py select --route <r>`: `strategy_or_product_bet`,
`model_weights_or_training_change`, `release_or_deploy_change`, `image_description_or_alt_text_change`,
`agent_loop_change`, `pricing_positioning_or_launch`.

The ordering rests on STRAT-22 (weakest-link first: sequence improvement at the limiting link, do not stretch a
non-bottleneck), PROD-01 (outcome over output), PROD-11 (second-step test), GTM-13 (bare-product test) and
RLSE-05 (silent failure is the worst failure). The rollout shape rests on AIPX-06 (shadow then canary), AIPX-05
(heuristic fallback required), RLSE-07 (phased rollout is instrumentation), RLSE-08 (rollback written before
ship) and RLSE-10 (the model is a separately revertible artifact). The measurement contract rests on EVAL-01
(require offline baselines), EVAL-04 (slice-based gate), PERF-01 (percentiles, not averages), PERF-03
(coordinated omission), PERF-06 (measure, don't guess) and PERF-13 (leave headroom against the queue).

The GPU deferral rests on GTM-02 (micro-test the offer before building capability), OPS-02 (sit on your hands —
swing only at fat pitches) and PROD-05 (Truth Curve: investment proportional to market evidence).

Tension held open, not resolved by fiat: OPS-14 (commercial-first gate — buy before greenfield) argues for a
hosted VLM provider. That was already dispositioned `reject` under E20-11 and is not re-litigated here; per
AGT-13 the ADR is not silently overridden, and re-opening it is an explicit out-of-scope decision.

## Constraints

- **No GPU spend.** `acx-gpu-burst` stays STOPPED for the duration of this task. Any slice that would provision
  the A10 is out of scope and must be recorded as such rather than skipped silently (AGT-06).
- **Prod host is shared.** The A1 now co-hosts three environment stacks plus the WordPress demo. The E19-1
  memory envelope (~18 GB free) no longer holds; headroom is a fresh measurement, not an assumption (PERF-06).
- **Descriptions run on the remote OCI CPU.** The 8 GB M1 laptop is orchestration-only; no inference is
  benchmarked or served locally.
- **Eval isolation.** Eval runs use the dedicated eval tenant, never the demo or prod tenants.
- **Determinism.** Greedy decode, pinned model revision, pinned prompts; the offline re-score path stays
  bit-identical (TEST-08).
- **Branch isolation + pre-merge gate.** Every slice merges only through `handoff_close_check(enforce=True)`.

## Disconfirmers (STRAT-02 — what would kill this plan)

- The CPU tier's p95 latency at realistic WordPress batch sizes exceeds what the queue can absorb, and no
  amount of concurrency tuning closes it. Then the GPU deferral is wrong and VLM-6 S3 becomes P0.
- Qwen3-VL-4B Q4 fails the golden-corpus regression gate against the Florence-2 incumbent on hallucination.
  Then the adoption candidate changes, not the sequencing.
- Prod memory headroom cannot fit the model alongside the existing stacks without evicting the demo WordPress
  container. Then the host topology, not the model, is the blocking decision.
- A warm prospect converts on the `seeded` demo. Then description quality is not the limiting link and STRAT-22
  points somewhere else.

## Not-Doing

- The A10 burst window (VLM-6 slices 3, 5, 6). Deferred until a disconfirmer above fires.
- Hosted VLM providers (E20-11 disposition `reject` stands).
- FIR recognition-quality work. It gates neither production descriptions nor first revenue.
- The depiction colour thread (trigger-gated on FM-04 by its own recorded decision).
- Full funnel analytics beyond the accept/edit signal.
- Fine-tuning, multi-GPU serving, WordPress plugin redesign.

## Slice Delivery

### Slice 1: Production VLM runtime image

Build and publish the `[vlm]`-extra runtime image for the prod tag. Verify torch + transformers import inside
the container and that the recognition path is unregressed. Measure resident memory of the loaded model against
live host headroom before any traffic is routed (PERF-06, PERF-13). Exit: image published, boot smoke green,
measured RSS and free-memory delta recorded as a `test_result`.

### Slice 2A: A gate that can fail (prerequisite — added 2026-08-11)

**Why this slice exists.** Slice 2 as originally written assumed `feature/vlm-6` supplied a working offline
regression gate. The adversarial review of that branch (round `r0811e7f1`, 5 reviewers, 40 findings, verdict
**fail**) established empirically that it does not: `score` exits 0 for a model that puts a wrong human name on
100% of images, and `--check-determinism` passed all four deliberate corruptions (every caption corrupted, wrong
names injected, corpus truncated 37→5, `must_right` emptied) because it re-scores the same inputs twice in one
process. A green exit from that harness is a false green by construction. Under TEST-15 a gate that cannot go
red certifies nothing, so a gate must exist before there is anything to gate.

**Scope is the catastrophic case only, not all 40 findings.** Moving from `seeded` placeholder text to any real
VLM does not need a meets-or-beats quality gate — that comparison is close to trivial and PROD-05 forbids
building eval apparatus ahead of market evidence. What it does need is a floor on the one failure that is
*worse* than placeholder text: attaching a wrong or hallucinated human name to a photograph. That is the only
threshold that must be able to fail before cutover.

Four items, in dependency order:

1. Fix the emitter, not the validator (sr-001): `fusion_runner` emits bare-string identity rows against a
   schema that now requires dicts. This is `VLM6-GATE-01`, and it is the same break that already made the
   frozen determinism anchor un-rescorable at HEAD — it landed after the freeze and passed the gate meant to
   catch it.
2. Give `score` a verdict. A `verdict` field in the report JSON and a non-zero exit when the wrong-name rate
   exceeds its floor. Today the only exit condition is items that could not be *scored*, never items that
   scored badly.
3. Make the determinism check cross-process: re-score from the persisted anchor artifact in a subprocess
   rather than calling `build_reports` twice with identical arguments in one.
4. Ship the four corruptions as permanent discrimination guards (TEST-15, second clause). Each mutation that
   currently passes becomes a committed test asserting the specific red it should produce.

Exit: each of the four corruptions fails the gate with its predicted message, and the suite proves it.

### Slice 2: `cpu_qwen4b` profile, scored against the Slice 2A gate

Add the Qwen3-VL-4B Q4 profile to `scene/config/profiles.py` with pinned revision and decode params. Score it
against the golden corpus and the recorded 646-image CPU baseline, hallucination-first, reporting per-stratum
scores rather than a single aggregate (EVAL-04). Report readiness as the weakest category, not an average or a
total (EVAL-23). Delete or hard-gate the `gpu_phi4` and `florence_large` enum values, which today are selectable
into a guaranteed 503 (AGT-10). Exit: the wrong-name floor holds, with the per-stratum table recorded.

**Corpus caveat carried forward.** All 37 golden entries have empty `difficulty`, `domain`, `tags`,
`reference_facts`, `spatial_facts` and `face_boxes`. Per-stratum reporting (EVAL-04) is therefore uncomputable
today, and positional-identity scoring silently excludes 37/37 images while reporting `degraded_images: 0`.
Populating `face_boxes` is in scope for this slice because the wrong-name floor depends on it; the remaining
stratification metadata (MLDATA-01) is explicitly deferred with the rest of the VLM-6 finding set.

### Slice 3: Async description path + fallback

Wire the description request through the worker with an explicit timeout, bounded pending work and a readiness
signal (RES-14, RES-02). On timeout or model error, degrade to `seeded` loudly — recorded, never silent
(AIPX-05, AGT-10). Report p50/p95/p99 from open-loop per-image timing, never a mean, never closed-loop
(PERF-01, PERF-03). Exit: measured p95 at a realistic WordPress batch size, with the queue-depth gate stated.

### Slice 4: Shadow → canary → prod

Run the new adapter in shadow against live traffic, compare against `seeded`, then canary a bounded slice
before full cutover (AIPX-06, RLSE-07). Write the rollback before shipping and pin the previous-good artifact
(RLSE-08, RLSE-10). Exit: prod serving real descriptions, rollback rehearsed, not just documented.

### Slice 5: Accept/edit instrumentation

Instrument accept, edit and reject on every generated description (AIPX-03). This is simultaneously the model
quality signal and the only funnel telemetry worth building before conversion works (GTM-05). No confidence
badge (AIPX-10). Exit: events flowing with tenant correlation.

### Slice 6: Worktree debt triage

~~Land vlm-6 slices 0–2 (determinism anchor, golden-100, harness) — they are the regression gate Slice 2 depends
on~~ — **superseded 2026-08-11.** The review verdict on `feature/vlm-6` @`e7f1d164` is **fail**; slices 0–2 do
not constitute a working gate, so landing them as-is would land the false green. The branch's genuinely sound
parts (the FL30A identity/position binding fix, merge integrity, cloud-init safety) carry forward into Slice 2A,
which is where the gate actually gets built. Park 3–6 as before. Batch-disposition the branch's 40 findings in
one pass against the Slice 2A scope: `fixed` for the four items 2A takes on, explicit `deferred` with rationale
for the rest — including the PUBLIC-report leak set (`R3-01/02/03`), which is real but only reachable if
bake-off reports are actually published, and which no launch slice publishes.

Land or delete cmap-1. Batch-disposition the ~300 open FIR-wave findings in one pass rather
than per-branch; 158 open on a single task is a stalled review process, not review debt (AGT-06, AGT-08).
Triage fir-8's dirty file before any teardown (rg-017). Decide land-or-re-derive on depiction-eval and fir-7,
which at 165 ahead are forks rather than branches. Exit: worktree count reduced, every remaining one with a
written reason.

### Slice 7: Ask for money

Only after Slice 4 is live. Concierge-provision a demo for a warm contact and ask them to buy (GTM-01, GTM-02).
Exit: an explicit yes or no from a real prospect, recorded either way.

## Verification Checklist

- [ ] Live-production adapter state re-measured at the end of the task, not assumed from config.
- [ ] Every latency figure is a percentile from open-loop timing.
- [ ] Every quality figure is per-stratum, not a single aggregate; readiness is the weakest category (EVAL-23).
- [ ] The regression gate has been observed going red on a deliberate corruption, in CI, not by hand (TEST-15).
- [ ] Rollback executed once in staging before prod cutover.
- [ ] Every deferred item has a written reason; nothing is silently skipped.
- [ ] Each slice merged only through a passing `handoff_close_check(enforce=True)`.

## Open Threads

- E15's recorded constraint "Recognition-only: InsightFace CPU inference. No VLM/Phi-3.5 for this milestone" now
  blocks the product. It must be amended explicitly rather than routed around (AGT-13).
- OCIGOV-1's cost-governance work deprioritizes with the GPU deferral, but the guard that would have caught a
  burst host billing unnoticed is worth keeping cheap.
