# Task Plan — GPUFLOW-3

> **Date:** 2026-09-18
> **Author:** claude (orchestrator)
> **Owning Epic:** E23 — [gpu-operator-control-and-named-captions-epic.md](../../epics/v0.5.0/gpu-operator-control-and-named-captions-epic.md) (Short ID GPUOPS)
> **Task ID:** GPUFLOW-3
> **Target Branch:** `feature/gpuflow-3`
> **Base SHA:** `213fad181474e5739a3b4859536f28792638cdeb`
> **Revision:** 1
> **Review Coverage Target:** one luna MAX review per slice group (8), one local harmonizing review before `main`
> **Prior art:** GPUFLOW-2 (describe durability, roster identity, cluster recovery), GPCOMP-1 (`docs/assessments/` Google Photos comparison, section 3 roster gaps), FIR report `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html`, heuristics canon lexicons (interaction-ux, engineering, graph-theory, ml-systems, security, accessibility)
> **Carried findings (by ID only; bodies live in the handoff DB):** task refs `MAINT-RELEASE-0024-20260918` (REL0024 series) and `MAINT-demo-identity-gpu-triage-20260918` (TRIAGE0918 series). Query: `review_findings(review={"operation":"list","status":"open","task_ref":"<ref>"})`.

## GPUFLOW-3. Demo Triage: Identity Integrity, GPU Run Lifecycle and the Unified Review Queue

## Objective

Close every defect the 0.0.24 demo triage confirmed, and ship the three operator-requested surface changes, in one parallel wave: (1) one person renders as one card backed by one service cluster; (2) a GPU warm-up never ends a run silently and every status surface tells the truth; (3) confirmed names reach the alt text on the GPU tier; (4) description drafts are reviewed inside the review queue, with one status authority instead of two disconnected indicators; (5) the roster gains the person-page features the Google Photos comparison ranks highest.

## Problem Statement

The 2026-09-18 triage of demo.altcontext.com (plugin 0.0.24) found that the reported symptoms share a small number of causes.

- **Duplicate identity cards / "2 face groups".** Binding a second cluster to an existing person replays a label copy instead of merging clusters, so the service keeps N clusters per person and the SPA renders the topology. Snapshot ingest never tombstones rows the service dropped, so stale members survive. The per-image card prefers the cluster representative over the face in the image.
- **GPU "never online".** A warm-up timeout fails the whole run with zero items and no reason. The lifecycle writer never publishes `starting`, and `gpu-state.json` flaps on a single failed probe. The SPA stall banner fires at 30 s during a 2–6 minute warm-up; single-image Suggest gives up at 120 s; an expired run context is purged without a terminal check.
- **"Backend unavailable" / Retry does nothing.** Retention and GPU control drop the typed proxy reason, so the panels cannot say which service, why, or whether Retry did anything.
- **Stale failed attempts.** Failed rows in the pending-changes timeline have no reason or action; entity-gone failures never age out.
- **Names not woven into the description.** The GPU (Qwen) tier emits no phrase boxes, so the grammar-aware realizer is unreachable; a cached draft is returned without re-running the name merge; every skip reason collapses into one status.
- **Two disconnected status indicators; drafts on a separate page.** The Control pane progress bar and the Library footer GPU chip poll independently and can disagree; description runs are reviewed on a page detached from the queue they came from.

## Constraints

- Greenfield: no migrations, no shims. Plugin boundary: only this monorepo.
- Lanes own 1–5 files including tests. A lane that needs another path reports a typed blocker.
- Remote sandboxes are history-stripped and have no network, `node_modules` or `vendor`; briefs inline everything needed and stay under the 27,000-character transport budget.
- A wrong name in alt text is worse than no name (FIR; ATTRIB-02, CAL-02). No similarity-driven merge anywhere in this wave: merges run only through the verified, receipted merge path on operator evidence (GRPH-18).
- Builds and description-service tests run on the OCI VM. Deploy is operator-owned.

## Workflow Principles

- One spec (`.task-state/gpuflow3_spec.py`) generates the lane manifest, the tables below and the dispatch queue.
- Contracts that two lanes share are frozen in this plan so producer and consumer run in parallel.
- Canon rules are cited by ID here; the rule text is inlined into each lane brief from the lexicon row.

## Terminology

- **Survivor cluster:** the service cluster a person keeps after a merge.
- **Activity status:** the single composed state of scan, describe run and GPU phase.
- **Slice group:** one of I, G, S, O, N, E, R, U; the unit of remote review.

## Current State Analysis

Verified on `213fad181` with the codemap index and direct reads; evidence for each carried defect is in the finding body. `ClusterMergeService::merge_cluster` and the service-side `cluster_merge.py` already exist and are receipted and revertible, so identity integrity is a routing fix, not new machinery. `usePinRepresentative`, the merge-suggestion accept/reject routes, the person media endpoint and `AdvancedDrawer` already exist, so the roster and status work composes existing parts.

## Target Outcome

- Binding a cluster to an existing person leaves exactly one service cluster for that person; the snapshot removes what the service removed; one card per person, with the face from this image.
- A warm-up timeout either continues on the CPU tier or ends with `gpu_warmup_timeout`, retryable. `gpu-state.json` shows `starting` and does not flap. No stall banner during warm-up.
- Retention and GPU control name the service, the reason, the fix and the last-checked time.
- Failed timeline rows carry a reason and Retry/Discard; orphans and exhausted rows age out.
- One confirmed face and one generic person phrase yields a woven name on any tier; grounding on the GPU tier sits behind a flag gated by the position-accuracy evaluation.
- One activity-status strip in the Control pane; drafts inline in the queue with a filter; the history route redirects into the queue.
- Person page: cover pick, photo grid, "Also with…" filter, and a same-or-different prompt.

## Context Loading

Each lane brief carries, in this order: ownership, job, verification, turn protocol, the lane's table row, sandbox facts, the binding design decision, the canon rule text for the lane's cited IDs, the slice section, then (trimmed to the transport budget) a codemap packet (symbols in owned and context files, graph search hits, snippets), upstream artifacts, read-only context files, a semantic prior-work packet (`semantic_reinjection_packet` plus `find_related_prior_work`, lexical fallback when the embedding volume is unmounted), and the current owned files. Identity lanes also carry the FIR distillation.

## Contract and Boundary Impact

Frozen for this wave. Producers and consumers implement against this text, not against each other's branches.

**C1. Typed unavailable reason (S1 producer, S2 consumer).** Retention status and GPU control responses add:

```json
{"unavailable": {"reason": "circuit_open", "service": "recognition", "http_status": null, "retry_after_seconds": 30, "checked_at": "2026-09-18T14:03:22Z"}}
```

`reason` is a closed set: `not_configured`, `api_key_missing`, `circuit_open`, `upstream_5xx`, `upstream_4xx`, `timeout`, `contract_mismatch`. `service` is `recognition` or `scene`. Every field comes from the proxy error (rg-015); absent values are `null`. Existing fields and status codes are unchanged. Consumers treat an unknown `reason` as generic copy plus the code.

**C2. Warm-up terminal (G1).** Run terminal detail: `{"code": "gpu_warmup_timeout", "retryable": true, "startup_budget_seconds": <int>}`. CPU continuation keeps items on the existing `tier: "provisional_cpu"` (the tier enum stays `provisional_cpu | final_gpu`; no `cpu_fallback` member) and stamps the run with an optional `fallback_reason: "gpu_warmup_timeout"` plus `provenance.fallback_reason` on each item. Amended 2026-09-19 (canon API-09, REF-29, DOM-03, PROV-01): deployed consumers hold a closed tier set, so the cause travels as an additive optional field.

**C3. GPU state (G2).** `starting` is published with `since` on START actuation or a RUNNING lease. Leaving `ready` requires a named number of consecutive probe failures (default 2). No state outside the existing contract enum.

**C4. Naming status wire values (N1 producer, E2 consumer).** `no_faces`, `no_confirmed_identities`, `no_eligible_identities`, `ambiguous_grounding`, plus the existing success values. Consumers map unknown values to neutral copy.

**C5. Run item thumbnails (E1 producer, E2 consumer).** Each describe-run item adds `thumbnail_url: string|null` and `thumbnail_srcset: string|null`, enriched in the PHP passthrough only.

**C6. Person media intersection (R4a producer, R4b consumer).** `with_person_ids[]`: up to 5 positive integers; invalid input is a 400. Result is media where the path person and all listed people appear. Pagination metadata comes from the real query.

**C7. SPA internal seams.** `describeOperationStore` exports `pendingTerminalRuns()` and `settleRun(id, outcome)`; `jobMachine` exports `stallThresholdMs(phase, startupBudgetSeconds)`; `useGpuStateToasts` reads `useActivityStatus()` and never derives GPU state itself; `setDescribeProgressMounted` tracks whether the strip is on screen; `useActivityStatus()` returns a discriminated union `{kind: idle|scanning|warming|describing|done|failed, progress, etaSeconds, reason, canCancel}` and owns the only GPU status poll.

### Open decisions

- **Modal or drawer for run details.** Resolved from the canon: non-modal drawer. A warm-up lasts minutes and the operator keeps working, so a blocking modal violates PERC-07, INT-08 and NAV-07. A confirm dialog is used only for Cancel run (INT-10).
- **Toast for GPU or activity status.** Resolved from the canon: a toast is never the status surface, and is kept as the edge channel. A warm-up lasts minutes; a message that vanishes carries no progress, ETA or Cancel (INT-08, INT-10) and makes the operator remember it (FORM-05), and a status toast on every poll habituates (PERC-07). The persistent strip stays the one surface. Transition toasts (GPU ready, run finished, run failed) fire once per run per edge, from the same `useActivityStatus` value, only while the strip is off screen (PERC-05, A11Y-21); toasts with an action or a failure persist until dismissed (A11Y-16) and never take focus (A11Y-13). The SPA already has this shape in `useGpuStateToasts`; lane `spa-activity-toasts` rewires it to the one authority and adds the finished and failed edges.
- **n ≥ 2 naming rule.** Not in this wave. Gated on the N4 evaluation verdict (CAL-02).
- **Removing the Description History menu slug.** Deferred; the slug lands on the filtered queue.
- **Storing `http_status` on outbox rows.** Out of scope; O2 classifies from persisted codes and reports the residual.

## Proposed Solution

Eight slice groups, 33 lanes, each lane 1–5 files. Shared files are serialized by dependency edges; everything else is independent. New UI capability is built in new files first (U1a, U2a, R3) and mounted by a separate lane, so the wide level-0 frontier never contends for `MediaSelection.tsx` or `PersonWorkspacePanel.tsx`.

## Files and Surfaces to Change

See the Lanes table. Surfaces: WordPress plugin PHP (`src/api`, `src/sovereign`, `src/settings`, `src/cli`), SPA (`js/admin/hooks`, `js/admin/pages`), description service (`scene`, `recognition`), GPU lifecycle (`infra/oci/gpu_lifecycle`), demo bootstrap, docs (`docs/assessments`, `docs/ux-maps`).

## Verification Strategy

- **Lane:** the lane's `test_cmd` through the orchestrator's self-verify in the provisioned VM environment. `self_verify` not run or failed for environmental reasons is resolved in the lane's VM sandbox over ssh, never by re-dispatching.
- **Integration:** after each merge into `feature/gpuflow-3`, run only the touched tests (`vitest run --changed`, `phpunit --filter` on touched classes, the lane's pytest files).
- **Slice review:** one luna MAX review per slice group on the concatenated lane deltas, inlined in the brief.
- **Release:** local harmonizing review (cross-slice contracts C1–C7, conflicts, missed interactions), fresh `test_result` on the final HEAD, `handoff_close_check(enforce=True)`.
- **Operator acceptance after deploy:** media 103, 104, 109, 115, 116 show one card per person and woven names; a cold GPU start shows `starting` and no stall banner.

## Slice Delivery

### Slice group I: Identity integrity (one person, one card, one service cluster)

### Slice I1: php-bind-merge

Binding a cluster to an existing person merges it into that person's survivor cluster instead of replaying a label copy.

Closes REL0024-H-06 (bodies in the handoff DB). Canon: GRPH-18, RES-13.

Design decision (binding): bind_cluster_to_person: when the person already owns a survivor cluster on the service, call ClusterMergeService::merge_cluster(loser=this cluster, survivor=person's cluster) (the verified merge path, receipted and revertible); label replay (cluster_person_bound/cluster_label_updated) only for the FIRST cluster of a person. Never merge by similarity here; the operator's bind is the evidence. A failed merge surfaces a typed error, never a silent unlabelled cluster. Inject the merge service through the constructor; test first-bind (label) and second-bind (merge) paths plus merge failure.

Acceptance: `vendor/bin/phpunit --filter "ClusterPersonBindService"` passes; changed paths stay inside the lane's owned list.

### Slice I2: php-snapshot-tombstone

Snapshot ingest tombstones local members/clusters the service no longer has and drops cluster_not_found conflicts.

Closes REL0024-M-07 (bodies in the handoff DB). Canon: GRPH-29, RES-07.

Design decision (binding): A FULL snapshot is authoritative for its tenant: rows in wp_acx_identity_members / wp_acx_clusters whose cluster id is absent from the snapshot are deleted inside the same run_transactional unit (sr-009) and counted in the merge result (tombstoned_clusters, tombstoned_members). A partial/paged snapshot must NOT tombstone (guard on the snapshot completeness flag already carried by the payload; if none exists, tombstone only when the payload declares itself complete and say so in the report). Never touch person rows or operator labels. Test: 3 local clusters vs 1 in snapshot => 1 remains; partial snapshot => nothing deleted.

Acceptance: `vendor/bin/phpunit --filter "ClusterSnapshotMerger"` passes; changed paths stay inside the lane's owned list.

### Slice I3: spa-cluster-crop

Per-image identity cards crop the face from this image; the cluster representative is secondary evidence only.

Closes TRIAGE0918-M-04 (bodies in the handoff DB). Canon: HAI-01, HAI-17.

Design decision (binding): ClusterPreview.tsx:28 currently prefers representativeFace when a referenceUrl exists. In a per-media context (the row has its own bbox + the media url) render the row's own crop; fall back to the representative only when the row has no bbox. Keep the prop surface backward compatible for roster callers.

Acceptance: `npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/ClusterPreview.test.tsx` passes; changed paths stay inside the lane's owned list.

### Slice I4: svc-scan-lock

Identity persistence is serialized per (tenant, media) so one physical face never becomes two rows.

Closes TRIAGE0918-M-03 (bodies in the handoff DB). Canon: RES-13, CAL-02.

Design decision (binding): _persist_identities (service.py ~409-550): take a per-(tenant_id, media_id) lock around read-reconcile-write (pg advisory xact lock on Postgres; an in-process asyncio lock keyed the same way otherwise; no new dependency). Regression test: two passes over the same media with bbox jittered by <= 2 px keep the row count stable. The defect is PLAUSIBLE/unreproduced: do not change IOU thresholds or clustering.

Acceptance: `python3 -m pytest apps/prototype-description-service/recognition/tests/unit/test_scan_service_reconcile_lock.py apps/prototype-description-service/recognition/tests/unit/test_scan_service_observability.py -q -p no:cacheprovider` passes; changed paths stay inside the lane's owned list.

### Slice group G: GPU run lifecycle (warm-up never fails silently; state is truthful)

### Slice G1: svc-warmup-terminal

A GPU warm-up timeout degrades per item to the CPU adapter when one is configured, else ends the run with a typed retryable reason.

Closes TRIAGE0918-H-01 (bodies in the handoff DB). Canon: RES-13, INT-10, OBS-08.

Design decision (binding): _wait_for_gpu_ready TimeoutError must never mark the whole run FAILED with zero items and no reason. Order: (1) if a non-Unavailable CPU description adapter is resolvable, continue the run on it and stamp each item + the run with tier=cpu_fallback, reason=gpu_warmup_timeout; (2) otherwise finish the run FAILED with a typed terminal detail {code: gpu_warmup_timeout, retryable: true, startup_budget_seconds}. Status/reason values come from the existing StrEnum surfaces (sr-007); add members there if they live in this file, else report a typed blocker naming the enum file. Scene DB fixtures may hang in-turn: prove collection with --co -q.

Acceptance: `python3 -m pytest apps/prototype-description-service/scene/tests/test_describe_run_worker_gpu_warmstart.py apps/prototype-description-service/scene/tests/test_describe_run_worker_phases.py -q -p no:cacheprovider` passes; changed paths stay inside the lane's owned list.

### Slice G2: infra-gpu-state-starting

gpu-state.json publishes starting/warming from START actuation and stops flapping to non-ready while the model server is healthy.

Closes REL0024-M-04, REL0024-M-02 (bodies in the handoff DB). Canon: OBS-08, RES-14.

Design decision (binding): reaper.py is >3000 lines: grep -n first, read ranges only. (a) When START is actuated or a RUNNING lease is recorded, write state=starting with since= so /scene/gpu/status renders the starting headline. (b) A single failed probe while the previous state was ready must not publish non-ready: require N consecutive failures (named constant, default 2) before leaving ready; `since` only resets on a real transition. Keep the snapshot contract test green; no new states outside the contract enum.

Acceptance: `python3 -m pytest infra/oci/gpu_lifecycle/tests/test_state_snapshot.py infra/oci/gpu_lifecycle/tests/test_start_actuator.py infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py -q -p no:cacheprovider` passes; changed paths stay inside the lane's owned list.

### Slice G3: spa-stall-phase

The 30 s stall banner is suppressed while the run is warming; the threshold follows the server startup budget.

Closes REL0024-M-05 (bodies in the handoff DB). Canon: PERC-03, INT-08.

Design decision (binding): JOB_MACHINE_STALL_THRESHOLD_MS=30000 stays for the processing phase. While phase is warming / gpu state is not ready the threshold is startup_budget_seconds (from the run payload; fallback 510) * 1000. Export a pure `stallThresholdMs(phase, startupBudgetSeconds)` helper so spa-activity-status can reuse it.

Acceptance: `npx vitest run js/admin/hooks/__tests__/jobMachine.test.ts` passes; changed paths stay inside the lane's owned list.

### Slice G4: spa-suggest-ceiling

Single-image Suggest waits for the server's startup budget instead of a fixed 120 s.

Closes TRIAGE0918-M-10 (bodies in the handoff DB). Canon: RES-02, INT-08.

Design decision (binding): Replace the 120 s ceiling (useDescribeMedia.ts:27-35) with startup_budget_seconds from the typed starting envelope plus one retry gap; keep a hard upper bound constant (900 s) so a bad payload cannot wait forever (RES-02 every wait has a timeout). Storage spies: spy Storage.prototype, never sessionStorage directly (jsdom).

Acceptance: `npx vitest run js/admin/hooks/__tests__/useDescribeMedia.test.tsx` passes; changed paths stay inside the lane's owned list.

### Slice G5: spa-run-resume

A persisted describe run is re-polled to a terminal phase on remount before it is purged, and its outcome is reported on the queue.

Closes TRIAGE0918-M-09 (bodies in the handoff DB). Canon: GRPH-29, OBS-08, INT-10.

Design decision (binding): purgeInvalid must not delete an expired run context outright: mark it `needs_terminal_check` and expose `pendingTerminalRuns()`; the consumer polls GET describe/run/{id} once and then calls `settleRun(id, outcome)` which purges. progressMounted moves into the persisted record. Typed status enum (sr-007). Spy Storage.prototype in tests.

Acceptance: `npx vitest run js/admin/hooks/__tests__/describeOperationStore.test.ts` passes; changed paths stay inside the lane's owned list.

### Slice group S: Service-status honesty (typed unavailable reason end to end)

### Slice S1: php-unavailable-reason

Retention status and GPU control return the typed unavailable reason, service name and checked_at instead of a bare available:false / generic 502.

Closes TRIAGE0918-M-05, TRIAGE0918-M-06 (bodies in the handoff DB). Canon: FORM-05, RES-13, SECD-12.

Design decision (binding): Wire shape is frozen in the plan (Contract section): `unavailable: {reason, service, http_status|null, retry_after_seconds|null, checked_at}` with reason in the closed set not_configured | api_key_missing | circuit_open | upstream_5xx | upstream_4xx | timeout | contract_mismatch. Source every field from the proxy error (rg-015: never invent); map the existing recognition_not_configured / recognition_api_key_missing / recognition_circuit_open codes; never leak the raw upstream message or key material. Retention keeps HTTP 200 + available:false but adds `unavailable`; GPU control keeps its status code and adds the same object.

Acceptance: `vendor/bin/phpunit --filter "RetentionController|GpuControlController"` passes; changed paths stay inside the lane's owned list.

### Slice S2: spa-unavailable-reason

Retention and GPU control panels name the service, the reason, the fix and a last-checked time that visibly changes on Retry.

Closes TRIAGE0918-M-05, TRIAGE0918-M-06 (bodies in the handoff DB). Canon: FORM-05, PERC-05, INT-08.

Design decision (binding): Consume the frozen `unavailable` object (plan Contract section); payloads without it fall back to today's copy. Copy = which service + why + how to fix, from a closed reason->copy map (unknown reason => generic copy + the code). Show `Last checked HH:MM:SS` from checked_at and a pending state during refetch so Retry is never inert; countdown only when retry_after_seconds exists. Status pairs icon with colour; --acx-* tokens only (sr-004).

Acceptance: `npx vitest run js/admin/pages/__tests__/RetentionPage.test.tsx js/admin/pages/settings/__tests__/GpuControlCard.test.tsx` passes; changed paths stay inside the lane's owned list.

### Slice group O: Outbox hygiene (failed sync rows have a reason, an action and an age-out)

### Slice O1: spa-timeline-actions

Failed rows in the pending-changes timeline show code, attempts and Retry/Discard like the Failed changes list.

Closes TRIAGE0918-M-07 (bodies in the handoff DB). Canon: FORM-05, INT-06.

Design decision (binding): Reuse formatErrorSummary + useRetryOperation/useDiscardOperation already used by the Failed changes list in this file (timeline ~927-984). One row component for both lists; no duplicated action wiring.

Acceptance: `npx vitest run js/admin/pages/workbench/__tests__/DeadLetterPanel.test.tsx` passes; changed paths stay inside the lane's owned list.

### Slice O2: php-outbox-hygiene

Entity-gone failures are auto-discarded as orphans with an audit row, exhausted rows age out, and purge has an Action Scheduler fallback.

Closes TRIAGE0918-M-08 (bodies in the handoff DB). Canon: RES-07, RES-06.

Design decision (binding): Classify from PERSISTED fields only (terminal reason / error code already stored on the row; cluster_not_found or 404-class codes => orphaned). auto_retry_exhausted rows older than a named retention constant are purged with an audit count. Purge schedules through Action Scheduler when available, WP-Cron otherwise (same pattern as drain). Bounded batches (rg-007), run_transactional (sr-009). Storing a new http_status column is OUT of scope for this lane: report it as residual if the persisted code is insufficient.

Acceptance: `vendor/bin/phpunit --filter "OutboxMaintenanceService"` passes; changed paths stay inside the lane's owned list.

### Slice group N: Names in descriptions (re-realize on relabel; woven names on the GPU tier)

### Slice N0: svc-rerealize-names

A cache hit re-runs the name merge against current confirmed faces, so naming a face after the draft was cached reaches the alt text.

Closes TRIAGE0918-M-02 (bodies in the handoff DB). Canon: HAI-02, ATTRIB-02.

Design decision (binding): visual_facts_service.py ~412-459: on (image_hash, context_hash) hit, re-run merge_identities over the cached base caption with the CURRENT confirmed faces (no VLM call) and return the re-realized draft + recomputed provenance. The cached row keeps the un-named base caption as the merge input; if only the named draft was stored, re-realize from the stored base field when present and otherwise return the cached draft with naming_status unchanged (say which in the report). A wrong name is worse than no name: never add a name the merge policy rejects.

Acceptance: `python3 -m pytest apps/prototype-description-service/scene/tests/test_visual_facts_service.py -q -p no:cacheprovider` passes; changed paths stay inside the lane's owned list.

### Slice N1: svc-naming-status

Naming skip reasons stop collapsing into NO_FACES; each reason is reported as itself.

Closes REL0024-M-08 (bodies in the handoff DB). Canon: CAL-02, OBS-08.

Design decision (binding): merge.py ~200: NamingStatus gains/uses NO_CONFIRMED_IDENTITIES, NO_ELIGIBLE_IDENTITIES, AMBIGUOUS_GROUNDING distinctly from NO_FACES (StrEnum, sr-007). If the enum lives outside merge.py and lacks members, report the file as a typed blocker rather than editing it. Wire values are the lowercase enum values; spa-apply-view-evidence maps them to copy.

Acceptance: `python3 -m pytest apps/prototype-description-service/scene/tests/test_identity_merge_merge.py apps/prototype-description-service/scene/tests/test_identity_merge_policy.py -q -p no:cacheprovider` passes; changed paths stay inside the lane's owned list.

### Slice N2: svc-n1-substitution

With exactly one confirmed face and one leading generic person phrase, the name is woven into the sentence without phrase boxes.

Closes REL0024-M-09 (bodies in the handoff DB). Canon: ATTRIB-02, CAL-02, HAI-04.

Design decision (binding): n == 1 ONLY: exactly one confirmed face in the image AND exactly one generic person noun phrase in the caption (closed list: a man, a woman, a person, a young man, ...) => deterministic NP substitution ('Keanu Reeves stands ...'). Any other count keeps PositionalFallbackRealizer. No n >= 2 rule in this wave (gated on svc-position-eval). Abstain when the NP count is ambiguous (CAL-02: unknown is a valid result).

Acceptance: `python3 -m pytest apps/prototype-description-service/scene/tests/test_identity_merge_realizer.py apps/prototype-description-service/scene/tests/test_identity_merge_merge.py -q -p no:cacheprovider` passes; changed paths stay inside the lane's owned list.

### Slice N3: svc-qwen-grounding

The GPU adapter asks Qwen3-VL for grounded person spans and maps them to phrase_boxes so the grammar-aware realizer is reachable.

Closes REL0024-M-09 (bodies in the handoff DB). Canon: EMB-02, RES-13.

Design decision (binding): Mirror the phrase_boxes shape emitted by florence_local_adapter._parse_phrase_grounding (inlined below). Grounding is requested in the same call or one bounded follow-up call with its own timeout; malformed / out-of-image / missing boxes => phrase_boxes=[] (fail closed to the positional realizer), never a fabricated box. Behind a settings flag defaulting OFF until svc-position-eval accepts it.

Acceptance: `python3 -m pytest apps/prototype-description-service/scene/tests/test_gpu_remote_adapter.py -q -p no:cacheprovider` passes; changed paths stay inside the lane's owned list.

### Slice N4: svc-position-eval

Evaluation protocol and acceptance gate for position accuracy before any n>=2 naming rule or the grounding flag is enabled.

Closes REL0024-M-09 (bodies in the handoff DB). Canon: CAL-02, EMB-02.

Design decision (binding): Analysis lane. Define position_accuracy (name attached to the right person), the labelled sample needed, per-stratum intervals (group size, occlusion), the abstain rule, and the pass bar for enabling the grounding flag and any n>=2 rule. End with `Verdict: accepted|needs_operator`. No production edits.

Acceptance: `python3 -m pytest scripts/tests/test_composer_lock_tracked.py -q -p no:cacheprovider` passes; changed paths stay inside the lane's owned list.

### Slice group E: Evidence and defaults (draft beside image, CLI detail, recognition opt-in)

### Slice E1: php-run-item-thumb

Describe-run items carry thumbnail_url/srcset from WordPress so a draft can sit beside its image.

Closes REL0024-L-10 (bodies in the handoff DB). Canon: PERC-01, HAI-01.

Design decision (binding): get_describe_run_items (~513-575) enriches each item with thumbnail_url + thumbnail_srcset from wp_get_attachment_image_src/srcset in the PHP passthrough only; missing attachment => nulls (never a fabricated URL, rg-015). No service change. class-describe-controller.php is large: grep -n, ranged reads.

Acceptance: `vendor/bin/phpunit --filter "DescribeRunItemsThumbnail"` passes; changed paths stay inside the lane's owned list.

### Slice E2: spa-apply-view-evidence

Ready-to-apply rows show the image beside the draft and reason-specific naming copy.

Closes REL0024-L-10, REL0024-M-08 (bodies in the handoff DB). Canon: PERC-01, COG-02, HAI-01.

Design decision (binding): Reuse the acx-media-selection__thumb pattern (MediaSelectionTableBody.tsx ~250). Naming badge copy from a closed map over the naming status wire values (no_faces, no_confirmed_identities => 'Faces found, none confirmed', no_eligible_identities, ambiguous_grounding => 'Grounding ambiguous'); unknown value => neutral copy. Export the row as a reusable component for spa-queue-drafts-mount.

Acceptance: `npx vitest run js/admin/pages/__tests__/DescribeRunApplyView.test.tsx` passes; changed paths stay inside the lane's owned list.

### Slice E3: php-cli-detail

wp describe prints the typed error code/message instead of 'Array' and honours retry_after for a starting GPU.

Closes REL0024-M-01 (bodies in the handoff DB). Canon: OBS-08, RES-02.

Design decision (binding): class-description-command.php:299: when detail is an array read detail.code/detail.message. For code description_service_starting retry after retry_after seconds, bounded (max 3 attempts, total wait capped by startup_budget_seconds).

Acceptance: `vendor/bin/phpunit --filter "DescriptionCommandGenerate"` passes; changed paths stay inside the lane's owned list.

### Slice E4: php-recognition-default-off

Face recognition defaults to off with explicit opt-in; the demo bootstrap opts in explicitly and its guide-rule assert stops flaking.

Closes TRIAGE0918-M-13, REL0024-L-03 (bodies in the handoff DB). Canon: SECD-12.

Design decision (binding): RecognitionPolicy::DEFAULT=false. bootstrap-wp.sh sets the recognition option on explicitly for the demo tenant (idempotent) and the post-flush ^guide assert reads the rewrite_rules option directly with one retry (bootstrap-wp.sh:290). Greenfield: no migration of existing installs.

Acceptance: `vendor/bin/phpunit --filter "RecognitionPolicy"` passes; changed paths stay inside the lane's owned list.

### Slice group R: Roster features from the Google Photos comparison (GPCOMP-1 section 3)

### Slice R1: spa-person-card

One card per person: face-group topology leaves the daily view and moves under a 'Not the same person?' split affordance.

Closes REL0024-M-11 (bodies in the handoff DB). Canon: NAV-14, GRPH-18, COG-02.

Design decision (binding): Remove the 'N face groups' badge and '+N' count from the card (IdentityClusterItem.tsx ~397, representativeVocabulary.ts:48-49). groupIdentitiesByClusters (utils.ts:82-163) additionally dedups rows that are the same face in the same media (same media id + bbox IOU > 0.5) so one face renders once. Split stays reachable via a secondary 'Not the same person?' disclosure. No client-side merging by similarity (GRPH-18).

Acceptance: `npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterItem.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.test.ts js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterList.test.tsx` passes; changed paths stay inside the lane's owned list.

### Slice R2: spa-person-page

Person page: pick the cover face and see the person's full photo grid (GPCOMP-1 section 3).

New capability (GPCOMP-1 section 3 / operator request); no carried finding. Canon: NAV-05, HAI-01, INT-06.

Design decision (binding): Extend PersonWorkspacePanel: 'Use as cover' on any face via the existing usePinRepresentative mutation (optimistic, undoable toast), and a paged photo grid from the existing person media endpoint. No new routes.

Acceptance: `npx vitest run js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx js/admin/pages/roster/__tests__/PersonWorkspacePanel.scrubber.test.tsx` passes; changed paths stay inside the lane's owned list.

### Slice R3: spa-same-person-prompt

'Same or different person?' yes/no prompt built from pending merge suggestions; Yes merges through the verified path, at most one prompt per session.

New capability (GPCOMP-1 section 3 / operator request); no carried finding. Canon: HAI-04, GRPH-18, INT-07, COG-02.

Design decision (binding): Source: GET suggestions/merge (pending). Yes => existing accept route (verified, receipted merge) ; No => reject route (becomes a cannot-link); Skip => nothing. Two face crops side by side, names if any, no similarity percentages as the primary signal. Max one prompt per session (sessionStorage flag; spy Storage.prototype in tests). Non-modal card at the top of the roster; never auto-merge.

Acceptance: `npx vitest run js/admin/pages/roster/__tests__/SamePersonPrompt.test.tsx js/admin/pages/__tests__/RosterPage.test.tsx` passes; changed paths stay inside the lane's owned list.

### Slice R4a: php-person-media-with

Person media endpoint accepts with_person_ids[] and returns only media where all named people appear.

New capability (GPCOMP-1 section 3 / operator request); no carried finding. Canon: NAV-06.

Design decision (binding): Optional with_person_ids[] (ints, max 5, validated at the boundary; invalid => 400). Intersection computed in SQL over the existing projected rows; pagination metadata from the real query (rg-015); column names validated against the real schema (rg-005).

Acceptance: `vendor/bin/phpunit --filter "PersonMediaController"` passes; changed paths stay inside the lane's owned list.

### Slice R4b: spa-person-also-with

'Also with...' people filter on the person page ('A and B' search).

New capability (GPCOMP-1 section 3 / operator request); no carried finding. Canon: NAV-06, FORM-08.

Design decision (binding): Multi-select of named people feeding with_person_ids[] on the photo grid query; empty result state names the people searched; removable chips.

Acceptance: `npx vitest run js/admin/pages/roster/__tests__/PersonWorkspacePanel.alsoWith.test.tsx js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx` passes; changed paths stay inside the lane's owned list.

### Slice group U: Unified review queue (one status authority, drafts inline, UX maps)

### Slice U1a: spa-activity-status

One activity-status authority hook (scan + describe + GPU phase, ETA, cancel) and a status strip with a non-modal details drawer.

Closes TRIAGE0918-M-11 (bodies in the handoff DB). Canon: PERC-01, PERC-05, INT-03, INT-10, PERC-07.

Design decision (binding): NEW files only. useActivityStatus composes the scan job pipeline state, useDescribeRunProgress and ONE gpu/status poll (no second poller) into a discriminated union {kind: idle|scanning|warming|describing|done|failed, progress, etaSeconds, reason, canCancel}. ActivityStatusStrip renders it (role=status, polite) with a 'Details' button opening AdvancedDrawer (non-modal: a warm-up is 2-6 minutes, the user keeps working; PERC-07/INT-08/NAV-07 rule out a blocking modal). ConfirmDialog only for Cancel run. Parameters grouped into typed objects (sr-008). The strip is the persistent surface (INT-08/INT-10: progress, ETA and Cancel stay visible for the whole wait); toasts are a secondary edge channel owned by lane spa-activity-toasts, so export a stable `ActivityStatus` type and keep every action a toast could carry (Review drafts, Retry, Back to run) available in the strip or drawer.

Acceptance: `npx vitest run js/admin/hooks/__tests__/useActivityStatus.test.ts js/admin/pages/workbench/__tests__/ActivityStatusStrip.test.tsx` passes; changed paths stay inside the lane's owned list.

### Slice U1b: spa-status-mount

The strip mounts in the Control pane; the Library footer keeps only the Describe CTA.

Closes TRIAGE0918-M-11 (bodies in the handoff DB). Canon: PERC-01, INT-03.

Design decision (binding): Panels.tsx ScanActionPanel replaces its bare <progress> with ActivityStatusStrip. MediaSelection.tsx: remove GpuTierStatus + BulkDescribeProgress from the footer (BulkDescribeCta keeps the button and hands run start to the shared hook); exactly one live region announces status. Keep the setDescribeProgressMounted(true/false) effect, now tied to the strip being mounted: it is the signal that suppresses transition toasts while the strip is on screen. MediaSelection.tsx is >1000 lines: grep -n, ranged reads, minimal diff.

Acceptance: `npx vitest run js/admin/pages/workbench/__tests__/Panels.test.tsx js/admin/pages/workbench/__tests__/MediaSelection.gpuStatus.test.tsx js/admin/pages/workbench/__tests__/MediaSelection.statusAnnouncement.test.tsx` passes; changed paths stay inside the lane's owned list.

### Slice U1c: spa-activity-toasts

Transition toasts (GPU ready, run finished, run failed) driven by the one activity-status authority, shown only when the strip is off screen.

Closes TRIAGE0918-M-11 (bodies in the handoff DB). Canon: PERC-05, PERC-07, A11Y-21, A11Y-13, A11Y-16, FORM-05.

Design decision (binding): A toast is never the status surface: a warm-up lasts minutes and a vanishing message carries no progress, ETA or Cancel (INT-08/INT-10/FORM-05). It is the edge channel for an operator who has navigated away from the strip (PERC-05). Rewire the existing useGpuStateToasts (keep the export name, App.tsx is not owned) to read useActivityStatus instead of deriving GPU state itself, so strip and toast can never disagree. Emit on kind-change edges only, once per run per edge, never on a poll tick and never on the first observation (PERC-07): warming (info, auto-dismiss), ready (persistent, 'Back to run'), done (success, persistent, 'Review N drafts' -> review queue), failed (error, persistent, reason-specific copy; 'Retry' only when the reason is retryable per C2). Keep the existing degraded edge as is. All other edges are suppressed while progressMounted is true so exactly one region announces (A11Y-21). Persistent = durationMs null, user-dismissed (A11Y-16); ToastContext is read-only context and already never moves focus (A11Y-13). Copy lives in GPU_STATE_VOCABULARY (sr-007), no inline strings.

Acceptance: `npx vitest run js/admin/hooks/__tests__/useGpuStateToasts.test.tsx` passes; changed paths stay inside the lane's owned list.

### Slice U2a: spa-queue-drafts

Queue-side draft data hook and an inline draft cell (accept, edit, apply) for review-queue rows.

Closes TRIAGE0918-M-12 (bodies in the handoff DB). Canon: NAV-05, NAV-06, INT-07, HAI-04.

Design decision (binding): NEW files only. useQueueDrafts(mediaIds, runId?) reads drafts through the existing describe-run items / description-history API functions (no new routes) keyed by media id. QueueDraftCell shows the draft beside the row with Accept / Edit / Dismiss; apply stays explicit through the existing apply mutation (never auto-apply, HAI-04); one atomic backend call per apply (rg-002).

Acceptance: `npx vitest run js/admin/hooks/__tests__/useQueueDrafts.test.tsx js/admin/pages/workbench/__tests__/QueueDraftCell.test.tsx` passes; changed paths stay inside the lane's owned list.

### Slice U2b: spa-queue-drafts-mount

Drafts render inline in the review queue with a 'Has draft' / per-run filter; the history route redirects into the filtered queue.

Closes TRIAGE0918-M-12 (bodies in the handoff DB). Canon: NAV-05, NAV-06, NAV-07.

Design decision (binding): Mount QueueDraftCell in MediaSelectionTableBody; add 'Has draft' and `?run=` filters to the queue (URL-addressable, NAV-07). App.tsx: /description-history and ?run= redirect to the queue with the matching filter; the 'Review drafts' link targets the queue filter. The PHP menu slug stays this wave (audit entry point) and lands on the same filtered queue.

Acceptance: `npx vitest run js/admin/pages/workbench/__tests__/MediaSelection.filters.test.tsx js/admin/pages/workbench/__tests__/MediaSelectionTableBody.commitExclusivity.test.tsx` passes; changed paths stay inside the lane's owned list.

### Slice U3: ux-maps

UX maps for the review queue and the roster/person screens as built by this wave.

New capability (GPCOMP-1 section 3 / operator request); no carried finding. Canon: NAV-05, INT-10.

Design decision (binding): Docs lane. Mirror the structure of the inlined existing map; no extra H2 under `## Screens`; states and actions only as implemented at the base commit (cite file:line).

Acceptance: `python3 -m pytest scripts/tests/test_composer_lock_tracked.py -q -p no:cacheprovider` passes; changed paths stay inside the lane's owned list.

## Lane Decomposition

### Lanes

`W` = `apps/prototype-wp-alt-context`, `S` = `apps/prototype-description-service`. Implement lanes run grok-remote grok-4.6 HIGH; `svc-position-eval` and `ux-maps` run codex-remote gpt-5.6-luna MAX.

| Lane ID | Slice | Owned Paths | Upstream Dependencies (artifact transferred) | Required Tests |
| --- | --- | --- | --- | --- |
| `spa-run-resume` | G5 | `W/js/admin/hooks/describeOperationStore.ts`<br>`W/js/admin/hooks/activeDescribeRun.ts`<br>`W/js/admin/hooks/__tests__/describeOperationStore.test.ts` | none | `npx vitest run js/admin/hooks/__tests__/describeOperationStore.test.ts` |
| `spa-cluster-crop` | I3 | `W/js/admin/pages/workbench/identity-clusters/ClusterPreview.tsx`<br>`W/js/admin/pages/workbench/identity-clusters/__tests__/ClusterPreview.test.tsx` | none | `npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/ClusterPreview.test.tsx` |
| `spa-stall-phase` | G3 | `W/js/admin/hooks/jobMachine.ts`<br>`W/js/admin/hooks/__tests__/jobMachine.test.ts` | none | `npx vitest run js/admin/hooks/__tests__/jobMachine.test.ts` |
| `php-cli-detail` | E3 | `W/src/cli/class-description-command.php`<br>`W/tests/Unit/DescriptionCommandGenerateTest.php` | none | `vendor/bin/phpunit --filter "DescriptionCommandGenerate"` |
| `spa-suggest-ceiling` | G4 | `W/js/admin/hooks/useDescribeMedia.ts`<br>`W/js/admin/hooks/__tests__/useDescribeMedia.test.tsx` | none | `npx vitest run js/admin/hooks/__tests__/useDescribeMedia.test.tsx` |
| `spa-timeline-actions` | O1 | `W/js/admin/pages/workbench/DeadLetterPanel.tsx`<br>`W/js/admin/pages/workbench/__tests__/DeadLetterPanel.test.tsx` | none | `npx vitest run js/admin/pages/workbench/__tests__/DeadLetterPanel.test.tsx` |
| `php-run-item-thumb` | E1 | `W/src/api/class-describe-controller.php`<br>`W/tests/Unit/DescribeRunItemsThumbnailTest.php` | none | `vendor/bin/phpunit --filter "DescribeRunItemsThumbnail"` |
| `php-recognition-default-off` | E4 | `W/src/settings/class-recognition-policy.php`<br>`W/tests/Unit/Settings/RecognitionPolicyTest.php`<br>`infra/oci/demo/bootstrap-wp.sh` | none | `vendor/bin/phpunit --filter "RecognitionPolicy"` |
| `spa-unavailable-reason` | S2 | `W/js/admin/pages/RetentionPage.tsx`<br>`W/js/admin/pages/settings/GpuControlCard.tsx`<br>`W/js/admin/pages/__tests__/RetentionPage.test.tsx`<br>`W/js/admin/pages/settings/__tests__/GpuControlCard.test.tsx` | none | `npx vitest run js/admin/pages/__tests__/RetentionPage.test.tsx js/admin/pages/settings/__tests__/GpuControlCard.test.tsx` |
| `svc-naming-status` | N1 | `S/scene/application/identity_merge/merge.py`<br>`S/scene/tests/test_identity_merge_merge.py` | none | `python3 -m pytest apps/prototype-description-service/scene/tests/test_identity_merge_merge.py apps/prototype-description-service/scene/tests/test_identity_merge_policy.py -q -p no:cacheprovider` |
| `php-person-media-with` | R4a | `W/src/api/class-person-media-controller.php`<br>`W/tests/Unit/PersonMediaControllerTest.php` | none | `vendor/bin/phpunit --filter "PersonMediaController"` |
| `php-unavailable-reason` | S1 | `W/src/api/class-retention-controller.php`<br>`W/src/api/class-gpu-control-controller.php`<br>`W/tests/Unit/RetentionControllerTest.php`<br>`W/tests/Unit/GpuControlControllerTest.php` | none | `vendor/bin/phpunit --filter "RetentionController|GpuControlController"` |
| `php-bind-merge` | I1 | `W/src/api/services/class-cluster-person-bind-service.php`<br>`W/tests/Unit/ClusterPersonBindServiceTest.php` | none | `vendor/bin/phpunit --filter "ClusterPersonBindService"` |
| `php-snapshot-tombstone` | I2 | `W/src/sovereign/repositories/class-cluster-snapshot-merger.php`<br>`W/tests/Unit/ClusterSnapshotMergerTest.php` | none | `vendor/bin/phpunit --filter "ClusterSnapshotMerger"` |
| `svc-scan-lock` | I4 | `S/recognition/application/scan/service.py`<br>`S/recognition/tests/unit/test_scan_service_reconcile_lock.py` | none | `python3 -m pytest apps/prototype-description-service/recognition/tests/unit/test_scan_service_reconcile_lock.py apps/prototype-description-service/recognition/tests/unit/test_scan_service_observability.py -q -p no:cacheprovider` |
| `svc-rerealize-names` | N0 | `S/scene/application/visual_facts_service.py`<br>`S/scene/tests/test_visual_facts_service.py` | none | `python3 -m pytest apps/prototype-description-service/scene/tests/test_visual_facts_service.py -q -p no:cacheprovider` |
| `svc-warmup-terminal` | G1 | `S/scene/application/describe_run_worker.py`<br>`S/scene/tests/test_describe_run_worker_gpu_warmstart.py` | none | `python3 -m pytest apps/prototype-description-service/scene/tests/test_describe_run_worker_gpu_warmstart.py apps/prototype-description-service/scene/tests/test_describe_run_worker_phases.py -q -p no:cacheprovider` |
| `php-outbox-hygiene` | O2 | `W/src/sovereign/sync/class-outbox-maintenance-service.php`<br>`W/tests/Unit/OutboxMaintenanceServiceTest.php`<br>`W/tests/Unit/OutboxMaintenanceServicePurgeTest.php` | none | `vendor/bin/phpunit --filter "OutboxMaintenanceService"` |
| `spa-person-page` | R2 | `W/js/admin/pages/roster/PersonWorkspacePanel.tsx`<br>`W/js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx` | none | `npx vitest run js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx js/admin/pages/roster/__tests__/PersonWorkspacePanel.scrubber.test.tsx` |
| `spa-same-person-prompt` | R3 | `W/js/admin/pages/roster/SamePersonPrompt.tsx`<br>`W/js/admin/pages/roster/__tests__/SamePersonPrompt.test.tsx`<br>`W/js/admin/pages/RosterPage.tsx` | none | `npx vitest run js/admin/pages/roster/__tests__/SamePersonPrompt.test.tsx js/admin/pages/__tests__/RosterPage.test.tsx` |
| `infra-gpu-state-starting` | G2 | `infra/oci/gpu_lifecycle/reaper.py`<br>`infra/oci/gpu_lifecycle/state_snapshot.py`<br>`infra/oci/gpu_lifecycle/tests/test_state_snapshot.py`<br>`infra/oci/gpu_lifecycle/tests/test_start_actuator.py` | none | `python3 -m pytest infra/oci/gpu_lifecycle/tests/test_state_snapshot.py infra/oci/gpu_lifecycle/tests/test_start_actuator.py infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py -q -p no:cacheprovider` |
| `svc-qwen-grounding` | N3 | `S/scene/infrastructure/vlm/gpu_remote_adapter.py`<br>`S/scene/tests/test_gpu_remote_adapter.py` | none | `python3 -m pytest apps/prototype-description-service/scene/tests/test_gpu_remote_adapter.py -q -p no:cacheprovider` |
| `spa-queue-drafts` | U2a | `W/js/admin/hooks/useQueueDrafts.ts`<br>`W/js/admin/pages/workbench/QueueDraftCell.tsx`<br>`W/js/admin/hooks/__tests__/useQueueDrafts.test.tsx`<br>`W/js/admin/pages/workbench/__tests__/QueueDraftCell.test.tsx` | none | `npx vitest run js/admin/hooks/__tests__/useQueueDrafts.test.tsx js/admin/pages/workbench/__tests__/QueueDraftCell.test.tsx` |
| `spa-activity-status` | U1a | `W/js/admin/hooks/useActivityStatus.ts`<br>`W/js/admin/pages/workbench/ActivityStatusStrip.tsx`<br>`W/js/admin/hooks/__tests__/useActivityStatus.test.ts`<br>`W/js/admin/pages/workbench/__tests__/ActivityStatusStrip.test.tsx` | `spa-run-resume` (W/js/admin/hooks/describeOperationStore.ts, W/js/admin/hooks/activeDescribeRun.ts); `spa-stall-phase` (W/js/admin/hooks/jobMachine.ts) | `npx vitest run js/admin/hooks/__tests__/useActivityStatus.test.ts js/admin/pages/workbench/__tests__/ActivityStatusStrip.test.tsx` |
| `spa-apply-view-evidence` | E2 | `W/js/admin/pages/DescribeRunApplyView.tsx`<br>`W/js/admin/pages/__tests__/DescribeRunApplyView.test.tsx` | `php-run-item-thumb` (W/src/api/class-describe-controller.php); `svc-naming-status` (S/scene/application/identity_merge/merge.py) | `npx vitest run js/admin/pages/__tests__/DescribeRunApplyView.test.tsx` |
| `spa-person-also-with` | R4b | `W/js/admin/pages/roster/PersonWorkspacePanel.tsx`<br>`W/js/admin/pages/roster/__tests__/PersonWorkspacePanel.alsoWith.test.tsx` | `spa-person-page` (W/js/admin/pages/roster/PersonWorkspacePanel.tsx); `php-person-media-with` (W/src/api/class-person-media-controller.php) | `npx vitest run js/admin/pages/roster/__tests__/PersonWorkspacePanel.alsoWith.test.tsx js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx` |
| `svc-n1-substitution` | N2 | `S/scene/application/identity_merge/realizer.py`<br>`S/scene/application/identity_merge/merge.py`<br>`S/scene/tests/test_identity_merge_realizer.py` | `svc-naming-status` (S/scene/application/identity_merge/merge.py) | `python3 -m pytest apps/prototype-description-service/scene/tests/test_identity_merge_realizer.py apps/prototype-description-service/scene/tests/test_identity_merge_merge.py -q -p no:cacheprovider` |
| `spa-person-card` | R1 | `W/js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx`<br>`W/js/admin/pages/workbench/identity-clusters/representativeVocabulary.ts`<br>`W/js/admin/pages/workbench/identity-clusters/utils.ts`<br>`W/js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterItem.test.tsx`<br>`W/js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.test.ts` | `spa-cluster-crop` (W/js/admin/pages/workbench/identity-clusters/ClusterPreview.tsx) | `npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterItem.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.test.ts js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterList.test.tsx` |
| `spa-status-mount` | U1b | `W/js/admin/pages/workbench/Panels.tsx`<br>`W/js/admin/pages/workbench/MediaSelection.tsx`<br>`W/js/admin/pages/workbench/__tests__/Panels.test.tsx`<br>`W/js/admin/pages/workbench/__tests__/MediaSelection.gpuStatus.test.tsx` | `spa-activity-status` (W/js/admin/hooks/useActivityStatus.ts, W/js/admin/pages/workbench/ActivityStatusStrip.tsx) | `npx vitest run js/admin/pages/workbench/__tests__/Panels.test.tsx js/admin/pages/workbench/__tests__/MediaSelection.gpuStatus.test.tsx js/admin/pages/workbench/__tests__/MediaSelection.statusAnnouncement.test.tsx` |
| `spa-activity-toasts` | U1c | `W/js/admin/hooks/useGpuStateToasts.ts`<br>`W/js/admin/hooks/__tests__/useGpuStateToasts.test.tsx`<br>`W/js/admin/pages/workbench/gpuStatePresentation.ts` | `spa-activity-status` (W/js/admin/hooks/useActivityStatus.ts, W/js/admin/pages/workbench/ActivityStatusStrip.tsx) | `npx vitest run js/admin/hooks/__tests__/useGpuStateToasts.test.tsx` |
| `svc-position-eval` | N4 | `docs/assessments/GPUFLOW-3-position-accuracy-eval-20260918.md` | `svc-n1-substitution` (S/scene/application/identity_merge/realizer.py, S/scene/application/identity_merge/merge.py); `svc-qwen-grounding` (S/scene/infrastructure/vlm/gpu_remote_adapter.py) | `python3 -m pytest scripts/tests/test_composer_lock_tracked.py -q -p no:cacheprovider` |
| `spa-queue-drafts-mount` | U2b | `W/js/admin/pages/workbench/MediaSelectionTableBody.tsx`<br>`W/js/admin/pages/workbench/MediaSelection.tsx`<br>`W/js/admin/App.tsx`<br>`W/js/admin/pages/workbench/__tests__/MediaSelection.filters.test.tsx` | `spa-queue-drafts` (W/js/admin/hooks/useQueueDrafts.ts, W/js/admin/pages/workbench/QueueDraftCell.tsx); `spa-status-mount` (W/js/admin/pages/workbench/Panels.tsx, W/js/admin/pages/workbench/MediaSelection.tsx); `spa-apply-view-evidence` (W/js/admin/pages/DescribeRunApplyView.tsx) | `npx vitest run js/admin/pages/workbench/__tests__/MediaSelection.filters.test.tsx js/admin/pages/workbench/__tests__/MediaSelectionTableBody.commitExclusivity.test.tsx` |
| `ux-maps` | U3 | `docs/ux-maps/workbench-review-queue.md`<br>`docs/ux-maps/roster-people.md` | `spa-status-mount` (W/js/admin/pages/workbench/Panels.tsx, W/js/admin/pages/workbench/MediaSelection.tsx); `spa-activity-toasts` (W/js/admin/hooks/useGpuStateToasts.ts, W/js/admin/pages/workbench/gpuStatePresentation.ts); `spa-queue-drafts-mount` (W/js/admin/pages/workbench/MediaSelectionTableBody.tsx, W/js/admin/pages/workbench/MediaSelection.tsx, W/js/admin/App.tsx); `spa-person-card` (W/js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx, W/js/admin/pages/workbench/identity-clusters/representativeVocabulary.ts, W/js/admin/pages/workbench/identity-clusters/utils.ts); `spa-same-person-prompt` (W/js/admin/pages/roster/SamePersonPrompt.tsx, W/js/admin/pages/RosterPage.tsx); `spa-person-also-with` (W/js/admin/pages/roster/PersonWorkspacePanel.tsx) | `python3 -m pytest scripts/tests/test_composer_lock_tracked.py -q -p no:cacheprovider` |

### Lane summaries

| Lane | Est. min | Canon | Summary |
| --- | --- | --- | --- |
| `spa-run-resume` | 35 | GRPH-29 OBS-08 INT-10 | A persisted describe run is re-polled to a terminal phase on remount before it is purged, and its outcome is reported on the queue. |
| `spa-cluster-crop` | 20 | HAI-01 HAI-17 | Per-image identity cards crop the face from this image; the cluster representative is secondary evidence only. |
| `spa-stall-phase` | 20 | PERC-03 INT-08 | The 30 s stall banner is suppressed while the run is warming; the threshold follows the server startup budget. |
| `php-cli-detail` | 20 | OBS-08 RES-02 | wp describe prints the typed error code/message instead of 'Array' and honours retry_after for a starting GPU. |
| `spa-suggest-ceiling` | 25 | RES-02 INT-08 | Single-image Suggest waits for the server's startup budget instead of a fixed 120 s. |
| `spa-timeline-actions` | 25 | FORM-05 INT-06 | Failed rows in the pending-changes timeline show code, attempts and Retry/Discard like the Failed changes list. |
| `php-run-item-thumb` | 25 | PERC-01 HAI-01 | Describe-run items carry thumbnail_url/srcset from WordPress so a draft can sit beside its image. |
| `php-recognition-default-off` | 25 | SECD-12 | Face recognition defaults to off with explicit opt-in; the demo bootstrap opts in explicitly and its guide-rule assert stops flaking. |
| `spa-unavailable-reason` | 30 | FORM-05 PERC-05 INT-08 | Retention and GPU control panels name the service, the reason, the fix and a last-checked time that visibly changes on Retry. |
| `svc-naming-status` | 30 | CAL-02 OBS-08 | Naming skip reasons stop collapsing into NO_FACES; each reason is reported as itself. |
| `php-person-media-with` | 30 | NAV-06 | Person media endpoint accepts with_person_ids[] and returns only media where all named people appear. |
| `php-unavailable-reason` | 35 | FORM-05 RES-13 SECD-12 | Retention status and GPU control return the typed unavailable reason, service name and checked_at instead of a bare available:false / generic 502. |
| `php-bind-merge` | 40 | GRPH-18 RES-13 | Binding a cluster to an existing person merges it into that person's survivor cluster instead of replaying a label copy. |
| `php-snapshot-tombstone` | 40 | GRPH-29 RES-07 | Snapshot ingest tombstones local members/clusters the service no longer has and drops cluster_not_found conflicts. |
| `svc-scan-lock` | 40 | RES-13 CAL-02 | Identity persistence is serialized per (tenant, media) so one physical face never becomes two rows. |
| `svc-rerealize-names` | 40 | HAI-02 ATTRIB-02 | A cache hit re-runs the name merge against current confirmed faces, so naming a face after the draft was cached reaches the alt text. |
| `svc-warmup-terminal` | 45 | RES-13 INT-10 OBS-08 | A GPU warm-up timeout degrades per item to the CPU adapter when one is configured, else ends the run with a typed retryable reason. |
| `php-outbox-hygiene` | 45 | RES-07 RES-06 | Entity-gone failures are auto-discarded as orphans with an audit row, exhausted rows age out, and purge has an Action Scheduler fallback. |
| `spa-person-page` | 45 | NAV-05 HAI-01 INT-06 | Person page: pick the cover face and see the person's full photo grid (GPCOMP-1 section 3). |
| `spa-same-person-prompt` | 45 | HAI-04 GRPH-18 INT-07 COG-02 | 'Same or different person?' yes/no prompt built from pending merge suggestions; Yes merges through the verified path, at most one prompt per session. |
| `infra-gpu-state-starting` | 50 | OBS-08 RES-14 | gpu-state.json publishes starting/warming from START actuation and stops flapping to non-ready while the model server is healthy. |
| `svc-qwen-grounding` | 50 | EMB-02 RES-13 | The GPU adapter asks Qwen3-VL for grounded person spans and maps them to phrase_boxes so the grammar-aware realizer is reachable. |
| `spa-queue-drafts` | 50 | NAV-05 NAV-06 INT-07 HAI-04 | Queue-side draft data hook and an inline draft cell (accept, edit, apply) for review-queue rows. |
| `spa-activity-status` | 50 | PERC-01 PERC-05 INT-03 INT-10 PERC-07 | One activity-status authority hook (scan + describe + GPU phase, ETA, cancel) and a status strip with a non-modal details drawer. |
| `spa-apply-view-evidence` | 30 | PERC-01 COG-02 HAI-01 | Ready-to-apply rows show the image beside the draft and reason-specific naming copy. |
| `spa-person-also-with` | 30 | NAV-06 FORM-08 | 'Also with...' people filter on the person page ('A and B' search). |
| `svc-n1-substitution` | 45 | ATTRIB-02 CAL-02 HAI-04 | With exactly one confirmed face and one leading generic person phrase, the name is woven into the sentence without phrase boxes. |
| `spa-person-card` | 45 | NAV-14 GRPH-18 COG-02 | One card per person: face-group topology leaves the daily view and moves under a 'Not the same person?' split affordance. |
| `spa-status-mount` | 40 | PERC-01 INT-03 | The strip mounts in the Control pane; the Library footer keeps only the Describe CTA. |
| `spa-activity-toasts` | 35 | PERC-05 PERC-07 A11Y-21 A11Y-13 A11Y-16 FORM-05 | Transition toasts (GPU ready, run finished, run failed) driven by the one activity-status authority, shown only when the strip is off screen. |
| `svc-position-eval` | 40 | CAL-02 EMB-02 | Evaluation protocol and acceptance gate for position accuracy before any n>=2 naming rule or the grounding flag is enabled. |
| `spa-queue-drafts-mount` | 45 | NAV-05 NAV-06 NAV-07 | Drafts render inline in the review queue with a 'Has draft' / per-run filter; the history route redirects into the filtered queue. |
| `ux-maps` | 40 | NAV-05 INT-10 | UX maps for the review queue and the roster/person screens as built by this wave. |

### DAG levels (longest-path depth)

| Level | Width | Lanes (critical path first, then shortest first) |
| --- | --- | --- |
| 0 | 23 | `spa-run-resume`, `spa-cluster-crop`, `spa-stall-phase`, `php-cli-detail`, `spa-suggest-ceiling`, `spa-timeline-actions`, `php-run-item-thumb`, `php-recognition-default-off`, `spa-unavailable-reason`, `svc-naming-status`, `php-person-media-with`, `php-unavailable-reason`, `php-bind-merge`, `php-snapshot-tombstone`, `svc-scan-lock`, `svc-rerealize-names`, `svc-warmup-terminal`, `php-outbox-hygiene`, `spa-person-page`, `spa-same-person-prompt`, `infra-gpu-state-starting`, `svc-qwen-grounding`, `spa-queue-drafts` |
| 1 | 5 | `spa-activity-status`, `spa-apply-view-evidence`, `spa-person-also-with`, `svc-n1-substitution`, `spa-person-card` |
| 2 | 3 | `spa-status-mount`, `spa-activity-toasts`, `svc-position-eval` |
| 3 | 1 | `spa-queue-drafts-mount` |
| 4 | 1 | `ux-maps` |

Critical path: `spa-run-resume` → `spa-activity-status` → `spa-status-mount` → `spa-queue-drafts-mount` → `ux-maps` = 210 min of estimated lane time. Serial total 1210 min; ideal speed-up 5.8x, bounded in practice by the admission cap below.

Owned-path conflicts between unordered lanes: 0. Every shared file is covered by a dependency edge (`PersonWorkspacePanel.tsx`: `spa-person-page` → `spa-person-also-with`; `MediaSelection.tsx`: `spa-status-mount` → `spa-queue-drafts-mount`; `merge.py`: `svc-naming-status` → `svc-n1-substitution`).

### Collision map

| File | Lanes | Order |
| --- | --- | --- |
| `W/js/admin/pages/roster/PersonWorkspacePanel.tsx` | `spa-person-page`, `spa-person-also-with` | edge |
| `W/js/admin/pages/workbench/MediaSelection.tsx` | `spa-status-mount`, `spa-queue-drafts-mount` | edge |
| `S/scene/application/identity_merge/merge.py` | `svc-naming-status`, `svc-n1-substitution` | edge |

### Merge Order

Topological order of the Lanes table. A lane integrates as soon as it is green and its upstream lanes are integrated; order inside a level is completion order.

### Manifest

`config/lane-orchestration/GPUFLOW-3.json` (gitignored, root checkout only), generated by `.task-state/gpuflow3_gen.py manifest` and validated with `load_manifest`. It holds the 33 lanes plus eight `slice-<group>-review` twins pinned to codex-remote gpt-5.6-luna max.

### Orchestration Mode

Remote lanes on the OCI VM. Implementation: grok-remote, grok-4.6, HIGH. Analysis, docs and review: codex-remote, gpt-5.6-luna, MAX. Local claude integrates, triages and runs the harmonizing review. Dispatch is one lane per detached process from the root checkout, launched serially with a spawn gate because the dispatch breaker admits one trial at a time.

### Landing Protocol

1. **Land on green.** A lane integrates into `feature/gpuflow-3` when its touched tests are green. Review never gates integration.
2. **Retire at once.** After integration: `merge-base --is-ancestor` check, thin bundle to `.task-state/branch-archive`, `git worktree remove`, branch delete. A dirty worktree is triaged file by file first (rg-017). `status=active` in the lane row is not a reason to keep a worktree.
3. **Admission cap.** At most 6 lanes open (dispatched and not yet integrated). Finished lanes land before any new lane is admitted. The cap is raised from the earlier guidance of 4 because the operator asked for maximum parallelism; the serial breaker already limits launch rate.
4. **Admission order.** Critical-path lanes first, then shortest first among the rest (PERF-11). A lane is admissible when its upstream lanes are integrated.
5. **One review per slice group.** Started when the group's last lane integrates. At most 10 findings, fenced ids `GPUFLOW-3-<GROUP>-R-NN`. One fix wave; no re-review of fix deltas.
6. **Only highs block.** Lint findings are recorded low with a `lint(<tool>):` prefix and deferred once. Mediums are listed once for operator triage; the operator picks which get fixed.
7. **One harmonizing review, then the gate.** Local claude, narrow scope (contracts, conflicts, interactions). Then the close check and the merge to `main`. The feature worktree retires after the merge and release checks.

Tracked while the wave runs: oldest unintegrated lane, review waiting time, completed-but-unretired worktrees.

## Highest-Leverage Next Items

1. `spa-run-resume` and `spa-stall-phase` (head of the critical path).
2. `php-bind-merge` and `php-snapshot-tombstone` (the blocking high and its cleanup path).
3. `svc-warmup-terminal` (the other high).

## Operator Steps (not executed by lanes)

- **D0, live path diagnosis:** on the demo host, confirm the WP recognition URL and key, circuit state, `gpu-state.json` content and the `acx-gpu-start` journal. This decides whether "GPU never online" on the live demo is configuration or code.
- **Deploy:** `package-plugin.sh` then `PLUGIN_ZIP=… make deploy-demo` over Tailscale; backend images via the VM build.
- **Data repair after deploy:** recover-orphans, then re-bind the duplicate clusters so the new bind path merges them.

## Consolidated Checklist

- [ ] Manifest generated and validated
- [ ] Level-0 lanes dispatched, integrated and retired
- [ ] Levels 1–4 dispatched as upstream lanes integrate
- [ ] Eight slice-group reviews run; highs fixed; mediums listed for triage
- [ ] Harmonizing review, fresh test evidence, close check, merge to `main`
- [ ] Operator steps handed over

## Review Readiness

Contracts C1–C7 are frozen. The owned-path conflict check reports zero unordered collisions. Every lane has an allow-listed test command.

## Stretch Goals

- n ≥ 2 naming rule, if the N4 verdict is `accepted`.
- Remove the Description History menu slug.

## Success Criteria

- No open high on GPUFLOW-3, REL0024 or TRIAGE0918 findings addressed by this wave.
- One card per person on the five acceptance media; woven name where exactly one confirmed face exists.
- Cold start shows `starting`, no stall banner, and either completes or ends with a typed retryable reason.
- One status strip; drafts reviewed inside the queue.
- No lane worktree left after its integration.
