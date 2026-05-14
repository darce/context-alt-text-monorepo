# E15-22. Workbench Avatar and Progress Readiness (MVP-critical demo gate)

> **Task Short ID**: E15-22
> **Status**: in_progress -- backend avatar surfaces, cluster-members envelope, frontend thumbnail/progress regressions, proof-bundle doc hooks, and the operator capture checklist shipped on `feature/e15-22`; remaining work is the seeded-media/LocalWP proof capture itself for the manual gate
> **Target Branch**: feature/e15-22
> **Epic**: [E15. Public Demo Launch Readiness](../../epics/v0.4.0/public-demo-launch-readiness-epic.md) Phase 4 (pre-demo workbench gate)
> **Predecessors**: E15-1 (security baseline) merged; E15-2 (observability baseline) merged. [E15-11](./E15-11-image-upload-transport-task-plan.md) hosted multipart proof is only a predecessor for the demo-proof-bundle slice and the private-media LocalWP gate, not for the backend or frontend Workbench slices.
> **Blocks**: [E15-3](./E15-3-wordpress-demo-provisioning-task-plan.md) completion and [E15-5](./E15-5-manual-remote-e2e-task-plan.md) live-demo sign-off.
> **Source intake**: MCP decision `copilot_scope_workbench_avatar_progress_intake` under `MAINT-workbench-avatar-progress-20260511`
> **Plan-analyze revision (2026-05-12)**: decision `plan_analyze_e15_avatar_gate_20260512_revise_first` reopened `E15-PA-AVATAR-GATE-20260512-01` and added backend prerequisite slices (Slices 1 and 2 below) to address findings `E15-AVATAR-PA-20260512-01` (cluster-members envelope mismatch) and `E15-AVATAR-PA-20260512-02` (missing backend face-thumbnail surface). Concrete browser HTML showed an 8-face cluster rendering placeholder thumbs, identity preview rendering `acx-face-thumbnail--error`, and Review Cluster drawer rendering "No members found." even after the frontend-only changes landed.

---

## Objective

Make the Workbench demo path visually and semantically trustworthy before the public demo is treated as launch-ready. When this task is complete, representative face avatars render from detected crop data when available, missing images surface an explicit error/fallback state, and scan/clustering progress no longer reports `Scan complete` or a decreasing processed count before the UI is actually ready.

## Problem Statement

The current Workbench can show blank cluster/entity avatars and misleading progress during real scans. The reported failure mode is specific and user-visible: top-cluster and identity previews may fall back to empty placeholders instead of representative face crops, `Scan complete` can appear while clustering is still in progress, and the processed counter can jump backward or reset during the same run. That is unacceptable on a public demo, even if the backend recognition request technically succeeds.

## Constraints

- Scope is limited to the Workbench avatar/progress surface needed for the public demo path. The broader 100-item scan-pipeline trust work in [scan-pipeline-trust-and-data-plane-canonicalization.md](../tech-debt/scan-pipeline-trust-and-data-plane-canonicalization.md) remains a v0.4.1 follow-on unless a discovered defect is unavoidable for the demo path.
- Do not redesign the Workbench layout. Fix correctness, fallback semantics, and proof.
- Hosted/private-media scan proof remains owned by [E15-11](./E15-11-image-upload-transport-task-plan.md); this task consumes that evidence in Slice 3 rather than blocking Slices 1 and 2 implementation on transport proof.
- The post-demo automated regression path remains owned by [E15-6](./E15-6-e2e-smoke-gate-automation-stub.md); this task must leave a proof bundle that E15-6 can later automate.

## Workflow Principles

- Visible demo state must match backend truth. `Scan complete` is a semantic contract, not a spinner label.
- Prefer representative face crops (`media_url + bbox`) when available; fallback/avatar states must be explicit rather than silently blank.
- Ship proof with behavior. Each slice must add focused tests or a named run-log artifact in the same slice.

## Terminology

- **Representative crop**: a face preview rendered from `media_url + bbox` rather than a generic thumbnail URL.
- **Explicit fallback/error state**: a named unavailable-image variant that is visibly rendered in the card/preview, exposes accessible text or an aria-label explaining that no representative image is available, and does not silently collapse to an empty box.
- **UI-ready completion**: the point where scan ingestion and clustering/projection work have produced the data the Workbench needs to render cluster suggestions truthfully.

## Current State Analysis

- `TopClusterCard.tsx` and `ClusterPreview.tsx` support representative crop rendering, but the public-demo plans do not currently require evidence that this data path is populated and visible.
- `ClusterPreview.tsx` on `feature/e15-22` already renders an explicit unavailable-image variant when representative crop data is missing; the remaining task is to prove that branch behavior on the real naming-queue surfaces and keep it from regressing.
- `JobTimeline.tsx` on `feature/e15-22` already keeps the scan milestone active until `scanProgress.phase` reaches `complete` or `awaiting_projection`; the remaining task is to preserve that truthfulness with direct regression coverage plus seeded-media proof.
- Processed-count aggregation in this branch flows through `useJobStateMachine.ts`, which calls `buildScanProgress()` in `jobStateMachineUtils.ts`; remaining work should target those live seams rather than the stale `jobStateMachineProgress.ts` anchor.
- The broader scan-pipeline trust debt doc records larger batch-run/data-plane problems; this task needs only the pre-demo subset required to avoid a misleading Workbench during the MVP demo path.

## Target Outcome

The demo Workbench shows representative faces when the backend returns crop data, degrades explicitly when images are unavailable, and reports progress in a way that a human operator can trust. A small seeded-media demo run must show increasing processed counts, no false green `Scan complete` state before clustering/projection is ready, and at least one screenshot/transcript proving the rendered avatar and progress surfaces.

## Context Loading

- Rules: `docs/agentic/rules/frontend-guidelines.md`, `docs/agentic/rules/testing-typescript.md`, `docs/agentic/rules/development-workflow.md`
- Contracts: `packages/shared-contracts/schemas/recognition-cluster-top-unlabeled-response.schema.json`, `docs/agentic/contracts/cluster-snapshot-api.md`, `docs/agentic/contracts/recognition-clustering.md`
- Handoff/MCP state: task ref `E15-22`; intake findings `MAINT-WB-PROGRESS-PLAN-01..05`; planning-review findings `E15-22-PLAN-01..07`
- Tech-debt inputs: `docs/tasks/tech-debt/scan-pipeline-trust-and-data-plane-canonicalization.md`, `docs/tasks/tech-debt/e2e-smoke-automation-path.md`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Workbench top-cluster payload | plugin/shared contracts | top-unlabeled response includes `thumb_url`, `media_url`, `bbox` | tighten demo proof so representative crop/fallback semantics are evidenced | Yes -- existing payload shape stays compatible | Vitest + run-log screenshot |
| Workbench job-status semantics | plugin frontend | progress UI reads per-job scan/clustering state | preserve truthful scan/projection semantics and close the remaining monotonic-progress proof gap | Yes -- no backend contract widening unless unavoidable | Vitest + LocalWP/manual proof |
| Demo gate evidence | E15 planning docs | run logs prove request success only | add explicit avatar/progress proof bundle | N/A -- planning-only boundary | E15-3a / E15-3 run-log checklist |

## Proposed Solution

Land a focused Workbench-correctness slice before public demo sign-off. The remaining work is to finish the backend prerequisites (`/clusters/{cluster_id}/members` envelope and backend-served face thumbnails), pin the already-landed avatar/progress frontend behavior with branch-local regression coverage, and capture the proof bundle that E15-3a and E15-3 require before E15-5 executes against the live demo. Broader batch-run canonicalization, stale-cluster reconciliation, and smoke automation remain follow-ons outside this task unless they are required to make the 5-10 image demo path trustworthy.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/TopClusterCard.tsx` | Touch only if regression-proof work exposes a mismatch in representative selection or explicit fallback semantics |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterPreview.tsx` | Touch only if regression-proof work exposes a mismatch in the shipped unavailable-image variant |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/JobTimeline.tsx` | Touch only if progress-proof coverage exposes a remaining mismatch in the scan-complete predicate |
| frontend | `apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachine.ts` | Keep the displayed scan progress sourced from the live aggregation seam when clustering/projecting begins |
| frontend | `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineUtils.ts` | Keep `buildScanProgress()` and phase derivation aligned with the timeline predicate |
| tests | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/TopClustersSection.test.tsx` | Extend top-cluster coverage for representative/thumb precedence and explicit unavailable-image fallback on the real rendered section |
| tests | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/SuggestionReviewPanel.test.tsx` | Extend integrated naming-queue coverage for pinned representative selection and avatar fallback on the real feature branch surface |
| tests | `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/JobTimeline.test.tsx` | Add `Scan complete` phase-predicate regressions for `clustering`, `projecting`, and projection-ready completion |
| tests | `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useJobStateMachine.test.ts` | Add monotonic processed-count coverage at the live aggregation seam used by the Workbench UI |
| tests | `apps/prototype-wp-alt-context/js/admin/api/__tests__/recognitionApi.test.ts` | Keep the cluster-members envelope contract pinned from the WP client side |
| tests | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/ClusterReviewPanel.test.tsx` | Verify the review drawer consumes the canonical members envelope without falling back to `No members found.` |
| planning/docs | `docs/tasks/15.0/E15-3a-localwp-oci-roundtrip-task-plan.md`, `docs/tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md`, `docs/tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md` | Consume the proof bundle and regression guard outputs; `E15-5` consumes the artifact at execution time but is not a required doc-edit surface in this branch |

## Related Files

| File | Note |
| --- | --- |
| `docs/tasks/tech-debt/scan-pipeline-trust-and-data-plane-canonicalization.md` | Broader post-MVP scan trust work; this task takes only the public-demo subset |
| `docs/tasks/tech-debt/e2e-smoke-automation-path.md` | Post-demo automation target E15-6 should absorb |
| `docs/tasks/15.0/E15-11-image-upload-transport-task-plan.md` | Hosted/private-media transport proof remains prerequisite evidence |
| `docs/tasks/15.0/E15-5-manual-remote-e2e-task-plan.md` | Live-demo execution consumes the proof bundle, but this task does not require a parallel E15-5 planning-doc edit to start Slices 1 and 2 |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/api/test_api_clusters.py -q`
  - `cd apps/prototype-wp-alt-context && npx vitest run js/admin/api/__tests__/recognitionApi.test.ts js/admin/pages/workbench/identity-clusters/__tests__/ClusterReviewPanel.test.tsx`
  - `cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/TopClustersSection.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/SuggestionReviewPanel.test.tsx`
  - `cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/workbench/__tests__/JobTimeline.test.tsx`
  - `cd apps/prototype-wp-alt-context && npx vitest run js/admin/hooks/__tests__/useJobStateMachine.test.ts`
- Runtime-parity / environment checks:
  - LocalWP seeded-media scan against hosted API after E15-11 proof is green for the Slice 3 demo-gate handoff
- Manual verification:
  - Capture a Workbench screenshot/transcript showing rendered representative avatars, processed count progression, and the point at which `Scan complete` appears

## Slice Delivery

### Slice 1: Cluster-Members Contract Envelope (backend prerequisite)

**Goal**: `GET /clusters/{cluster_id}/members` returns the envelope `{members, limit, total, truncated}` the WP client already requires, so the Review Cluster drawer can populate instead of falling back to "No members found." (finding `E15-AVATAR-PA-20260512-01`).

Changes:

- Update `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` so the `/clusters/{cluster_id}/members` route returns a Pydantic envelope model with `members: list[ClusterMemberResponse]`, `limit: int`, `total: int`, `truncated: bool` instead of the current `response_model=list[ClusterMemberResponse]`.
- Keep the members query bounded at the documented page limit and compute `total` separately, so the envelope does not preserve the old all-members fetch cost for large clusters.
- Mirror the envelope model in `recognition/interface_adapters/http/schemas/responses.py` so OpenAPI and the generated client agree.
- Update or add deterministic tests for the route to assert the envelope shape and the truncation flag at the documented page limit.
- Verify the WP client `apps/prototype-wp-alt-context/js/admin/api/recognition/clusterApiMembers.ts` no longer throws on a real backend response (its requires already match the new shape; the test is that no extra client edit is needed).

Proof:

- Pytest coverage proving the envelope shape and `truncated=true` boundary, plus a Vitest run against a recorded backend fixture that walks through `clusterApiMembers.ts` without throwing.

### Slice 2: Backend Face-Thumbnail Surface (backend prerequisite)

**Goal**: The Workbench can render representative faces from a backend-served, admin-reachable thumbnail surface instead of relying on WP attachment URLs that error inside the admin context (finding `E15-AVATAR-PA-20260512-02`).

Changes:

- Add a `thumb_url: BlobUrl | None` field to both `RepresentativeResponse` and `ClusterMemberResponse` in `recognition/interface_adapters/http/schemas/responses.py`.
- Populate `thumb_url` from the existing tenant-scoped image store via either (a) a new `/faces/{identity_id}/thumb` route that streams a cropped JPEG/PNG, or (b) a signed-URL helper that issues short-lived URLs against the existing media-blob path. Pick whichever path the backend already supports; do not invent a new storage tier.
- Update `apps/prototype-wp-alt-context/js/components/ui/FaceThumbnail.tsx` and the Workbench member/representative renderers (`TopClusterCard.tsx`, `ClusterReviewPanel.tsx`, `ClusterLabelingPanel.tsx`, and `ClusterPreview.tsx` where applicable) to prefer `thumb_url` over `media_url + bbox`.
- Add a pytest covering the new response field and route/signed-URL path, plus a Vitest case proving `FaceThumbnail` prefers `thumb_url` when both are present and only falls back to `media_url + bbox` when `thumb_url` is null.

Proof:

- Pytest + Vitest coverage for the new field + preference order, plus a LocalWP transcript showing an authenticated admin session loading thumbs without `acx-face-thumbnail--error` against seeded media.

### Slice 3: Representative Avatar Regression Proof (frontend proof)

**Goal**: Lock in the representative-avatar behavior that already shipped on `feature/e15-22` with regression coverage on the real naming-queue surfaces.

Changes:

- Add focused regression coverage in `TopClustersSection.test.tsx` and/or `SuggestionReviewPanel.test.tsx` proving the shipped top-cluster card path prefers the best representative (`thumb_url` first when present, otherwise representative crop data) on the surfaces that actually render in this branch.
- Add explicit unavailable-image assertions on the same rendered surfaces so the shipped `No image` variant and `Representative image unavailable` accessible label cannot regress back to a silent placeholder.
- Only touch `TopClusterCard.tsx` or `ClusterPreview.tsx` if the proof work exposes a real mismatch between the branch implementation and the documented demo contract.

Proof:

- Vitest coverage in the existing Workbench rendering suites (`TopClustersSection.test.tsx`, `SuggestionReviewPanel.test.tsx`, or another existing branch-local surface) for representative selection and explicit unavailable-image fallback.

### Slice 4: Honest Progress Regression Proof

**Goal**: Lock in the scan/projection truthfulness already tightened on `feature/e15-22` and close the remaining proof gap around monotonic displayed progress.

Changes:

- Extend `JobTimeline.test.tsx` so the shipped predicate remains pinned: `clustering` and `projecting` keep the scan milestone active until `scanProgress.phase` reaches `complete` or `awaiting_projection`, and projection-ready review remains separate from the raw pipeline phase.
- Extend `useJobStateMachine.test.ts` around the live `useJobStateMachine.ts` / `buildScanProgress()` seam so the displayed processed count stays monotonic when batch runs hand off from scanning to backend-driven clustering/projecting.
- Only change `useJobStateMachine.ts`, `jobStateMachineUtils.ts`, or `JobTimeline.tsx` if those new tests expose a real regression or an uncovered monotonicity bug.

Proof:

- Vitest coverage proving the no-early-`Scan complete` rule in `JobTimeline.test.tsx`, plus monotonic processed-count coverage in `useJobStateMachine.test.ts` at the live aggregation seam.

### Slice 5: Demo Proof Bundle + Regression Handoff (was Slice 3)

**Goal**: E15-3a and E15-3 require explicit proof before sign-off, and E15-6 has a clear regression target after MVP.

Changes:

- Add run-log requirements for avatar/progress screenshots or annotated transcripts to E15-3a.
- Add an operator-ready checklist in E15-3a so the seeded-media proof packet can be executed in capture order without reinterpreting the run log.
- Add explicit dependency notes in E15-3 so public-demo provisioning does not claim readiness before the proof bundle exists; E15-5 consumes that artifact at execution time without requiring a separate planning-doc edit in this branch.
- Carry the proof bundle into E15-6 as the first post-demo regression-automation target.

Proof:

- E15-3a run-log section names the avatar/progress evidence, the operator checklist points back to the same packet, and the seeded-media demo transcript remains the reusable artifact.

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Do not add rows like `(BR-04 closed)` or "resolve handoff issue X"; finding status lives in MCP / `DASHBOARD.txt`.

## Context and Ownership

- [ ] Loaded the Workbench code anchors, planning findings, and demo-gate docs before implementation.
- [ ] Confirmed the hosted/private-media proof surface from E15-11 is available before treating the LocalWP demo gate as green.
- [ ] Kept the broader scan-pipeline trust/canonicalization work scoped to v0.4.1 unless a defect is proven demo-blocking.

### Checklist for Slice 1: Cluster-Members Contract Envelope

- [x] `/clusters/{cluster_id}/members` returns the `{members, limit, total, truncated}` envelope through a Pydantic model shared by route and OpenAPI.
- [x] Pytest coverage proves the envelope shape and the `truncated=true` boundary at the documented page limit.
- [x] WP client `clusterApiMembers.ts` is exercised against a recorded backend fixture without throwing, and no extra client edit is required.

### Checklist for Slice 2: Backend Face-Thumbnail Surface

- [x] `RepresentativeResponse` and `ClusterMemberResponse` carry an admin-reachable `thumb_url` (route or signed URL), populated from the existing tenant-scoped image store.
- [x] `FaceThumbnail` and the top-cluster/cluster-preview resolvers prefer `thumb_url`, falling back to `media_url + bbox` only when `thumb_url` is null.
- [x] Pytest + Vitest coverage proves the field shape and preference order.
- [ ] A LocalWP transcript shows seeded-media thumbs loading without `acx-face-thumbnail--error` and records the reusable proof-bundle artifact for downstream demo gates.

### Checklist for Slice 3: Representative Avatar Truthfulness (frontend)

- [x] Existing Workbench rendering suites prove the shipped top-cluster representative-selection path on the actual naming-queue surfaces.
- [x] Explicit unavailable-image variants remain visible and accessible when images are unavailable.
- [x] Focused avatar regression coverage lands in existing branch-local suites such as `TopClustersSection.test.tsx` and/or `SuggestionReviewPanel.test.tsx`.

### Checklist for Slice 4: Honest Scan/Clustering Progress

- [x] `Scan complete` no longer appears in `clustering` or `projecting` unless the pinned completion predicate is satisfied.
- [x] Processed count is monotonic for the seeded-media demo path at the live `useJobStateMachine.ts` / `buildScanProgress()` seam that owns the displayed total.
- [x] Focused progress/timeline tests land in `JobTimeline.test.tsx` and `useJobStateMachine.test.ts`.

### Checklist for Slice 5: Demo Proof Bundle + Regression Handoff

- [x] E15-3a run-log requirements include avatar/progress screenshots or transcript evidence.
- [x] E15-3a operator checklist sequences the seeded-media proof packet without becoming a second evidence ledger.
- [x] E15-3 planning surface consumes the proof bundle before demo sign-off, and E15-5 execution reuses that artifact instead of redefining it.
- [x] E15-6 names this proof bundle as the first post-demo regression target.
- [x] E15-3a, E15-3, and E15-5 run-log templates carry a shared artifact-bundle ID and source scan identifier so one seeded-media proof packet can flow forward unchanged.

## Review Readiness

- [x] No Workbench-correctness change lands without matching proof in tests or the seeded-media run log.
- [x] Demo sign-off docs do not treat request success alone as sufficient once avatar/progress proof is required.
- [x] Slice 4 includes an explicit `JobTimeline.test.tsx` case proving `clustering` and `projecting` do not imply `Scan complete`.
- [x] Handoff records the avatar/progress contract implications for the public demo path.

## Stretch Goals

- [ ] Pull the broader batch-run aggregate state work from `scan-pipeline-trust-and-data-plane-canonicalization.md` only if the demo path still lies after the focused fixes above.

## Success Criteria

- [ ] The seeded-media Workbench demo shows representative avatars from crop data when available, with explicit unavailable-image states otherwise.
- [ ] The processed counter does not decrease during the demo run, and `Scan complete` appears only after clustering/projection is UI-ready.
- [ ] E15-3a and E15-3 require one named run-log proof bundle from the seeded-media LocalWP run that captures the avatar/progress behavior the public demo will rely on, and E15-5 reuses that same artifact during live-demo execution.
