# Plan: CPU-first tiered serving with automatic fallback (2026-07-16)

> Answers "can the whole scene-description pipeline run on CPU, kicking in automatically when
> GPUs are unavailable?" and defines the measurement cells that make the answer evidence-based.
> Companions: [`gpu-procurement-reachability-decomposition-2026-07-16.md`](gpu-procurement-reachability-decomposition-2026-07-16.md) ·
> [`gpu-availability-async-pool-adversarial-review-2026-07-16.md`](gpu-availability-async-pool-adversarial-review-2026-07-16.md) ·
> [`../../runbooks/oci-vlm-batch-compute-learnings.md`](../../runbooks/oci-vlm-batch-compute-learnings.md).
> Measurement rides **VLM-6** (`docs/tasks/vlm/VLM-6-gpu-vlm-bakeoff-task-plan.md`, S4/S5).

## 1. CPU metrics that already exist (and the gap)

| Model (profile) | Hardware | Latency/img | RSS / cold | Quality signal | Source |
| --- | --- | --- | --- | --- | --- |
| Florence-2-base-ft (`florence_small`) | OCI A1 CPU | ~14 s | — | inline incumbent, ≤20 s bar | E19-1 decision memo |
| Florence-2-large-ft (`florence_large`) | OCI A1 CPU | ~39 s | — | quality ceiling; async-only, stub today | E19-1 decision memo |
| **Qwen3-VL-4B-Instruct Q4_K_M** | OCI A1 CPU | **206 s mean** | 7.0 GB / 27 s | gated 0.90, insertion 1.0, 0 Must-Right fails, no fabricated specifics (Golden-10) | VLM-2B decision memo |
| CapRL-Qwen3VL-4B Q4_K_M | OCI A1 CPU | 208 s | 6.9 GB / 37 s | 0.90 but 3 fabricated specifics → runner-up | VLM-2B decision memo |
| Phi-4-multimodal | OCI A1 CPU | ~900 s | — | GPU-only, disqualified for CPU | E19-1 |
| **Qwen3-VL-30B-A3B Q4_K_M** | — | **no CPU measurement exists** | — | GPU-only scope so far (VLM-6 S3, A10-blocked) | — |

**Gap**: no 30B-vs-4B CPU comparison has ever run. The 30B is a **MoE with ~3B active params**
(`Qwen3-VL-30B-A3B`), so CPU inference is plausibly closer to the 4B's 206 s than dense-30B
intuition suggests — but its ~18 GB Q4 weights exceed the S4 12 GB RSS abort and need a
dedicated ≥32 GB box. Unmeasured ⇒ it gets a bounded feasibility cell, not an assumption
[AGT-03, DIAG-03].

## 2. Stage inventory — two of three stages are already CPU-native

| Stage | Runtime today | CPU status |
| --- | --- | --- |
| Facial recognition | InsightFace / ONNX Runtime (`recognition/infrastructure/embeddings/__init__.py`) — **being replaced for the commercial product** (E22 / FIR-2/FIR-3 commercial face-pipeline plan; remote OCI pipeline is canonical, local FR retired) | **Already CPU today** — provider chain ends in `CPUExecutionProvider`; detector wrapped in a circuit breaker (`recognition/application/embedding/detector.py`). The CPU-parity requirement transfers to the **replacement**: its detector/embedder legs must ship a measured CPU execution path as an acceptance criterion, or the face leg reintroduces the GPU lottery. |
| Caption synthesis (scene description) | Deterministic fusion (`scene/application/fusion/reconcile.py`) **today**; ALTQ-1 Slice 2 replaces this with a **model-based two-pass describe-then-ground weave** (pass-1 structured objective JSON, pass-2 reasoning-model interleave of captions with face identities; scoring stays deterministic, generation does not) | Deterministic path is CPU-trivial. The **two-pass weave is a new model inference per image** and needs its own tier cells: pass-2 is text-only (no vision), so a small CPU text model is the T1d candidate — **unmeasured** on both axes (latency, weave quality). See §4. |
| Image description | Profile registry (`scene/config/profiles.py`), static `ACX_DESCRIPTION_ADAPTER` knob | **The only GPU-dependent stage today.** CPU profiles exist (`florence_small` live; `florence_large` fail-closed stub pending the async describe worker). |

So "everything on CPU" reduces to: ship the async describe worker, then make the description
tier degrade automatically. Constraint carried forward: the FIR/E22 commercial face-pipeline
replacement must keep `CPUExecutionProvider` parity as an acceptance criterion, or it
reintroduces the GPU lottery through the face leg.

## 3. Tier ladder and automatic kick-in

| Tier | Profile | Placement | Budget (p95) | Role |
| --- | --- | --- | --- | --- |
| T2 quality | `gpu_qwen30b(_ensemble)` | GPU endpoint (reservation-backed if adopted) | ≤170 s (S5 gate) | optional, health-gated |
| T1d detailed | winner of S4/S5: Qwen3-VL-4B **or** `florence_large` (or 30B-A3B-CPU if the spike surprises) | dedicated CPU, async worker | set in S5 memo — explicit, falsifiable [DIAG-03] | **automatic fallback target** |
| T1f fast | `florence_small` | CPU, inline | ≤20 s (existing bar) | inline path |
| T0 | `seeded` | — | — | dev/test only; **never in the auto-chain** — degrading a real job to stub captions fabricates provenance [rg-015] |

Design requirements for the auto-fallback resolver (each falsifiable at review):

1. Fallback chain is **declared config validated at load** [rg-008], resolved in one place —
   no scattered profile string-compares [sr-007].
2. GPU tier is guarded by a **readiness probe + circuit breaker**; a tripped breaker routes new
   jobs to T1d immediately instead of queue-stalling behind a dead endpoint [RES-15, RES-03].
3. Every remote describe call carries a **bounded timeout** (the 170 s chain) [RES-02].
4. The job queue is **bounded with a full-queue policy**; the WP plugin sees job status
   (queued/tier/degraded), not silence [RES-14, API-07].
5. Launch/describe retries have **backoff + jitter + ceiling**; "no GPU capacity" is a routine
   routing outcome, not a retryable error loop [RES-06, API-08].
6. Jobs carry an **end-to-end request ID** so a tier-switch retry cannot double-caption
   [DATA-13, RES-01].
7. Response provenance records the **tier/model that actually served** (`adapter_kind`,
   `model_id`, `model_version` from the registry) — degradation is loud, logged, and queryable
   [AGT-10, OBS-01, rg-015].
8. Exported metrics: per-tier serve counts, fallback rate, breaker state, queue depth,
   per-stage p50/p95 [OBS-05, PERF-01].

## 4. Measurement plan — new cells inside the current VLM-6 bake-off

Harness stays the S2-frozen runner (`scripts/eval_harness/cli.py` fetch → `report.build_reports`
score); compute follows the runbook's dedicated-VM public-subnet on-box pattern (never the
laptop, never `acx-backend`).

**S4 (CPU tier run) additions** — anchor-first order preserved:

- `florence_small` anchor, then MiniCPM-V 4.6 (already planned).
- **Qwen3-VL-4B-Instruct Q4_K_M on Golden-100**: extend the VLM-2B Golden-10 protocol unchanged
  (llama.cpp ≥ b9893, `--image-max-tokens 1536`, greedy, 900 s ceiling) so 4B gets the same
  corpus as every S3 GPU candidate — today's 206 s number is Golden-10-only.
- **Qwen3-VL-30B-A3B Q4_K_M CPU feasibility spike (timeboxed)**: 10-image probe on a dedicated
  ≥32 GB CPU box (E4.Flex 16 OCPU/32 GB or A1 16/64; the 12 GB RSS abort is per-S4-prod-shape and
  is explicitly raised for this dedicated cell). Abort criteria: mean >600 s/img on the probe or
  RSS beyond the box ⇒ record `infeasible-cpu` with evidence and stop [AGT-12, AGT-04]. Only a
  passing probe earns a Golden-100 run.
- **Per-stage timing cells**: face pass wall-time per image (`face_pass.py`; curation-tenant
  JSONL already exists in `bakeoff-results/`), fusion runner wall-time (in-harness, cheap) — so
  the tiered plan has p50/p95 for *all three stages*, not just description [PERF-01].
- **Two-pass weave (ALTQ-1) tier cells**: ALTQ-1 Slice 3 measures the describe-then-ground
  configs on the A10 (GPU). Add the **CPU counterpart**: pass-2 weave is text-only, so bench it
  standalone on the dedicated CPU box (candidate: a small instruct text model via llama.cpp;
  the 4B running text-only is the zero-new-weights option) against the same 37-image A/B
  manifest — latency + the ALTQ-1 expanded rubric (name P/R, hallucinated-name rate). Without
  this cell the tiered plan's T1d has no synthesis stage number once the deterministic fusion
  path is superseded [AGT-03, DIAG-03]. Face-pipeline replacement (E22/FIR) inherits the same
  obligation: detector/embedder CPU cells measured before adoption.

**S5 (decision memo) additions**:

- Pick the T1d model (hallucination-first ranking unchanged) and **state the T1d p95 budget**
  as a falsifiable gate next to the existing GPU ≤170 s / CPU-inline ≤20 s gates [DIAG-03].
- Per-tier **cost/1k images** column (CPU box $/hr ÷ throughput vs GPU reservation amortization)
  [PERF-07, ARCH-06].

## 5. Adoption path (post-bake-off, separate slices)

1. **Async describe worker** (unblocks the `florence_large` stub and any >20 s CPU model) —
   prerequisite for T1d; design notes already exist (E19-1 impl notes).
2. **Fallback-chain resolver** + breaker + provenance + metrics (§3).
3. **FIR/E22 acceptance criterion**: commercial face pipeline keeps `CPUExecutionProvider`
   parity.
4. GPU tier remains optional and reservation-backed only if S5 shows a material quality gap —
   per the adversarial-review verdict, production must never be hostage to the A10 lottery.

## Success criteria

- Every stage (face, describe, fuse) has measured CPU p50/p95 on the same Golden-100 strata.
- Tier gates hold: inline ≤20 s p95, T1d ≤ its S5-declared budget, GPU ≤170 s p95.
- With the GPU endpoint absent for 24 h, zero jobs stuck pending: fallback rate 100 %, queue
  drains at CPU throughput, every response's provenance names the CPU tier that served it.
