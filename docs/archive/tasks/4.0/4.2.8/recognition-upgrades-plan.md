# Recognition Upgrades Plan (4.2.8)

Date: 2025-12-17  
Scope: prototype description service + WP plugin integration

## Executive Summary

We need to support large scan batches (e.g., 3500 images) without request timeouts, improve assignment safety by replacing global “system maturity” heuristics with per-candidate evidence, and preserve transitivity across chunk boundaries, runs, and user-labeled clusters. We should also evaluate whether a two-pass clustering strategy (greedy + HAC) similar to Apple Photos improves recall/transitivity without harming precision.

This document breaks the work into four parallel workstreams with concrete milestones, interfaces, and acceptance criteria:

1. **Per-candidate maturity & adaptive thresholds** (rep count/diversity/label state + identity quality; remove global label-count heuristics)
2. **Async queueing** for scan/analyze (and optionally clustering) to eliminate 60s timeouts and handle 3500+ workloads
3. **Transitivity preservation** within a batch, across chunks, and across completed batches anchored by user-labeled clusters
4. **HAC investigation** (Apple paper) as an optional second-pass cluster growth/merge stage

---

## Current State (Key Constraints)

### Scan/analyze is synchronous from the backend’s perspective

- `POST /recognition/analyze` awaits the full scan pipeline (`ScanService.analyze_media`) before returning a job response.
  - Backend: `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py`
  - Scan pipeline: `apps/prototype-description-service/recognition/application/scan/service.py`

### WordPress proxy has a hard 60s upstream timeout

- WP proxy uses `wp_remote_request(..., timeout=60)` for POST/PUT/PATCH.
  - `apps/prototype-wp-alt-context/src/api/class-recognition-proxy-controller.php`
  - `apps/prototype-wp-alt-context/src/api/class-recognition-controller.php`

### Chunking currently exists, but transitivity can still be lost

- WP admin currently chunks scans (300 IDs per request) and then triggers clustering after all scan jobs complete:
  - `apps/prototype-wp-alt-context/js/admin/api/recognition/scanApi.ts`
  - `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx`
- Backend clustering (`cluster_unclustered_identities`) runs `GraphDiscovery` per chunk of identities, which prevents graph-connected components spanning across chunks.
  - `apps/prototype-description-service/recognition/application/orchestration/incremental_clustering.py`

### Adaptive threshold logic is “global-per-tenant”

- Confidence gating uses a threshold derived from the tenant’s labeled cluster count.
  - `apps/prototype-description-service/recognition/application/assignment/checks/confidence.py`
- Training-stage endpoint is derived from labeled cluster count and presents “maturity” as a global state.
  - `apps/prototype-description-service/recognition/interface_adapters/http/routers/training.py`

---

## Workstream 1 — Per-Candidate Maturity & Adaptive Thresholds

### Problem

Global “maturity” (e.g., labeled cluster count) can relax thresholds even when the target cluster is new/unlabeled/low-representative, which increases the chance of “snowballing” errors. The decision should be based on _evidence for this candidate → this cluster_, plus the _trustworthiness of the target cluster_, plus the _quality of the identity_.

### Goal

Replace global label-count heuristics with a per-candidate “trust + quality” model:

- **Target cluster trust**: rep count, rep diversity, label state (user confirmed), and rep quality
- **Candidate identity quality**: detector confidence, pose/blur/occlusion proxies, embedding norm stability

### Proposed Model (High-Level)

#### A) Target Cluster Trust (per candidate)

Inputs (already available or trivially derivable):

- `rep_count` for cluster (already used by `MaturityCheck`)
- `representative_diversity` / `diversity_score` (exists on `IdentityClusterRepresentative`)
- `label_state`
  - “trusted” if user-confirmed or has a non-auto label
  - “untrusted” if auto/unlabeled
- representative quality (`quality_score`) and/or centroid stability (member_count)

Outputs:

- `cluster_trust_level ∈ {untrusted, developing, trusted}`
- or a scalar `cluster_trust_score ∈ [0,1]`

#### B) Candidate Identity Quality (per identity)

Inputs:

- detection `confidence` and bbox/pose fields on `MediaIdentity` rows
- (optional) derived “quality score” normalized to [0,1]

Output:

- `identity_quality_score ∈ [0,1]`

#### C) Threshold Selection (per candidate)

Instead of “global labeled cluster count → threshold”, compute:

- `effective_threshold = base_threshold + trust_adjustment(cluster_trust_level, identity_quality_score)`
- Keep the existing special-case: **anchor-linked transitivity** can still reduce the threshold, but only when the _target cluster is trusted_.

### Implementation Plan

1. **Define cluster label state consistently**

   - Create one canonical function for “is user-labeled/trusted” (used by training-stage, gate checks, UI).
   - Update any ad-hoc label checks (e.g., `label.startswith("cluster-")`) to use this shared logic.

2. **Add (or reuse) cluster-level signals**

   - Ensure representative selection populates `quality_score` and `diversity_score` consistently.
   - Add repository methods:
     - `get_representative_stats(cluster_id)` → `{count, min_quality, diversity_summary}`
     - `is_user_labeled(cluster_id)` or return label-state with cluster model.

3. **Replace global labeled-count adaptive threshold**

   - Modify `ConfidenceCheck` to remove `count_labeled()` dependency and instead use per-candidate cluster/identity signals.
   - Keep “suggest vs reject” behavior explicit:
     - Untrusted clusters: stricter threshold; prefer _reject or new cluster_ over suggesting to unlabeled targets.
     - Trusted clusters: allow suggestions at lower thresholds (human review has value).

4. **Turn on per-cluster maturity guard (safely)**

   - Consider enabling `min_representatives_for_maturity` and tuning it by label-state:
     - Trusted/labeled clusters can bypass this guard (already supported).
     - Unlabeled clusters must meet rep-count floor to accept candidates.

5. **Rework `GET /recognition/training-stage`**
   Options:
   - Deprecate the endpoint (if it encodes misleading global maturity), or
   - Replace with something non-misleading:
     - “trusted cluster coverage” (how many labeled/trusted clusters exist)
     - “representative health” distribution
     - “recent acceptance rate” metrics

### Acceptance Criteria

- A tenant with many labeled clusters does **not** automatically become permissive for assignments into new/unlabeled clusters.
- New/unlabeled clusters require stronger evidence (rep count/diversity + candidate similarity) before accepting new members.
- Regression tests cover:
  - Mature tenant + brand-new cluster → still strict
  - Anchor-linked to trusted cluster → can be permissive without sacrificing precision

---

## Workstream 2 — Async Queueing (Handle 3500+ Scans Reliably)

### Problem

Large batches are heavy (download images, detect faces, embed, DB writes). Any synchronous HTTP path is fragile because:

- WP proxy timeout (60s)
- reverse proxies (nginx, ALB) often have request/idle timeouts
- synchronous CPU/GPU work blocks web workers

### Goal

Make `/recognition/analyze` “enqueue + return job id” within ~1s, and process scan work asynchronously with progress reporting.

### Architecture Options (Recommended → Optional)

#### Recommended: Postgres-backed queue + dedicated worker

No new infrastructure required; durable and restart-safe.

Schema:

- `identity_scan_jobs` already exists for job status
- Add `identity_scan_job_items` (or similar):
  - `job_id`, `tenant_id`, `media_id`, `media_url`, `status`, `attempts`, `last_error`, timestamps

Worker:

- A new process (or a `uvicorn` “worker mode” entrypoint) that loops:
  - `SELECT ... FOR UPDATE SKIP LOCKED` next pending items
  - run detection + embedding + persist results
  - update per-item and per-job progress

API:

- `POST /recognition/analyze`:
  - creates job + job_items
  - returns `{job_id, status=pending, progress.total=N}`
- `GET /recognition/jobs/{job_id}`:
  - reads `identity_scan_jobs` and returns progress, error info
- (optional) `POST /recognition/jobs/{job_id}/cancel`

### WordPress / Frontend Considerations

Even if “3500 at once” is allowed, request bodies can hit:

- PHP `post_max_size`, `max_input_vars`
- proxy request size limits

We can support 3500:

- **Accept 3500 in one request**, but require backend to respond quickly and store job_items (queue) server-side.

### Acceptance Criteria

- A 3500-image scan request returns a job id quickly and does not rely on long-lived HTTP connections.
- Worker can resume after restart without corrupting jobs.
- Progress is observable and usable in WP UI (batch progress bars do not yet exist).

---

## Workstream 3 — Preserve Transitivity Across Chunks and Across Batches

### Problem

Transitivity is the product’s core. Current failure modes:

- **Across chunks (same batch/run):** graph clustering is performed per chunk; components cannot span chunks.
- **Across batches (different runs):** even if anchors exist, splitting graph runs can prevent bridge formation unless we reintroduce context.

### Goal

Guarantee that “bridge identities” can connect identities:

- within the same scan batch (even if processed in chunks),
- across runs (new batch can connect to identities discovered earlier),
- and strongly to user-labeled clusters (stable anchors).

### Proposed Approach (Phased)

#### Phase 3A: Run-level anchor accumulation (quick win)

Within `cluster_unclustered_identities`:

- Maintain a mutable `run_anchor_embeddings` map that persists across chunk iterations.
- When identities are accepted into clusters in earlier chunks, add their embeddings as temporary anchors for later chunks.
  - This preserves within-run transitivity without requiring a single huge graph pass.

#### Phase 3B: One graph pass over “all remaining” (transitivity-first)

Restructure clustering to:

1. chunked rep/centroid matching (cheap) → accept obvious assignments
2. accumulate the unresolved identities across all chunks
3. run `GraphDiscovery` once on the union of unresolved identities + anchors

This matches the intuition: graph is where transitivity is “made”, so it must see all nodes that might be connected.

#### Phase 3C: Cross-run transitivity via stable anchors + periodic re-cluster

To preserve transitivity across completed runs:

- Always inject anchors from **trusted clusters** (user-labeled + high-quality reps).
- Maintain a rolling window of “unclustered/unresolved identities” and re-run the graph stage periodically (or on-demand) with anchors.

Implementation ideas:

- Add a “needs_recluster” flag for unclustered identities.
- When a cluster becomes user-labeled, enqueue a “recluster unresolved identities” job to pull in historical identities that now have a trusted anchor.

### Acceptance Criteria

- Splitting a scan batch into N scan jobs does not reduce final clustering recall/connectedness when clustering is run after all embeddings are present.
- Within a single clustering run, identities that bridge between chunk A and chunk B can still connect (measurable via reduced “singleton new clusters” and increased anchor-linked assignments).
- When a user labels a cluster, subsequent runs can “pull in” matching historical identities without requiring manual merges.

---

## Workstream 4 — Evaluate HAC (Apple Photos) as a Second-Pass Growth/Merge Stage

### Reference

Apple describes a two-pass approach:

- first pass greedy clustering
- second pass hierarchical agglomerative clustering (HAC) using a median-linkage strategy with sampling for scalability

Source excerpt:
`docs/literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt`

### Hypothesis

HAC as a second pass can increase recall and improve transitivity across “boundaries” (our equivalent: chunks/runs/moments) while controlling false merges via robust linkage (median) and conservative thresholds.

### Investigation Plan

1. **Define the unit of clustering for HAC**
   Options:

   - identity-level HAC (expensive for large N)
   - cluster-level HAC using representatives/centroids (more scalable)

2. **Implement a prototype HAC pass**

   - Input: current clusters + representatives (and optionally unresolved identities)
   - Linkage: median distance between cluster members (approximate via sampling when large)
   - Output: merge proposals with confidence metrics

3. **Integrate safely**

   - Never auto-merge two trusted/user-labeled clusters without high confidence + constraints.
   - Prefer “suggest merge” workflows for ambiguous merges.

4. **Benchmark on internal datasets**
   - Metrics:
     - cluster purity / false merge rate
     - recall / fragmentation (singleton rate)
     - transitivity score: fraction of known same-person identities connected via any chain
     - runtime/memory scaling with N=3500, N=10k

### Decision Gate

Adopt HAC if it measurably improves transitivity/recall with acceptable precision and operational cost, otherwise keep current graph approach and focus on run-level/global graph restructuring.

---

## Milestones & Sequencing

### Milestone 0 — Instrumentation (prerequisite)

- Add per-run metrics/events for:
  - anchor-linked assignment rate
  - cross-chunk linkage success rate
  - singleton creation rate
  - suggestion/accept/reject rates by target label-state

### Milestone 1 — Async scan queue MVP

- Postgres queue table + worker
- `/recognition/analyze` returns quickly with job id
- WP UI continues polling existing job status endpoint(s)

### Milestone 2 — Transitivity within-run

- Run-level anchor accumulation OR single graph pass over “all remaining”

### Milestone 3 — Per-candidate maturity + threshold refactor

- Replace global labeled-count adaptive threshold
- Enable/tune per-cluster maturity safeguards
- Update training-stage endpoint or deprecate it

### Milestone 4 — HAC prototype + evaluation

- Implement behind a flag
- Benchmark + decide

---

## Open Questions

1. Should WP continue chunking scan requests for request-size safety, even if backend is async?
2. What should be the canonical definition of “trusted cluster” (user-labeled only, or also high-rep-count unlabeled)?
3. Do we want a “recluster after labeling” job to pull historical unclustered identities into newly-labeled clusters?
4. For HAC: do we cluster identities, clusters, or both (two-level HAC)?
