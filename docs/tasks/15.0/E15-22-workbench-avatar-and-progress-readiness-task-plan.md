# E15-22. Workbench Avatar and Progress Readiness (MVP-critical demo gate)

> **Task Short ID**: E15-22
> **Status**: scoped -- not started
> **Epic**: [E15. Public Demo Launch Readiness](../../epics/v0.4.0/public-demo-launch-readiness-epic.md) Phase 4 (pre-demo workbench gate)
> **Predecessors**: E15-1 (security baseline) merged; E15-2 (observability baseline) merged. [E15-11](./E15-11-image-upload-transport-task-plan.md) hosted multipart proof is only a predecessor for Slice 3 demo-proof handoff and the private-media LocalWP gate, not for Slices 1 and 2 Workbench implementation.
> **Blocks**: [E15-3](./E15-3-wordpress-demo-provisioning-task-plan.md) completion and [E15-5](./E15-5-manual-remote-e2e-task-plan.md) live-demo sign-off.
> **Source intake**: MCP decision `copilot_scope_workbench_avatar_progress_intake` under `MAINT-workbench-avatar-progress-20260511`

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
- `ClusterPreview.tsx` currently falls back to a silent placeholder `<span>` when `representative.media_url` or `representative.bbox` is missing, so the plan must define an explicit unavailable-image variant instead of leaving the blank-box behavior implicit.
- `JobTimeline.tsx` derives `Scan complete` from pipeline phase in a way that can mark the scan complete when the phase reaches `clustering` or `projecting`, before clustering/projection is actually UI-ready.
- Processed-count aggregation currently flows through `jobStateMachineProgress.ts`; the plan should treat that helper as the primary monotonicity enforcement layer, with `jobStateMachineUtils.ts` limited to phase derivation unless the implementation proves otherwise.
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
| Workbench job-status semantics | plugin frontend | progress UI reads per-job scan/clustering state | refine phase/completion semantics for demo truthfulness | Yes -- no backend contract widening unless unavoidable | Vitest + LocalWP/manual proof |
| Demo gate evidence | E15 planning docs | run logs prove request success only | add explicit avatar/progress proof bundle | N/A -- planning-only boundary | E15-3a / E15-3 run-log checklist |

## Proposed Solution

Land a focused Workbench-correctness slice before public demo sign-off. The implementation should verify representative crop rendering for top clusters and cluster previews, replace silent placeholders with an explicit unavailable-image variant, fix progress/completion semantics so `Scan complete` is no longer derived from `phase === 'clustering' || phase === 'projecting'`, and capture a proof bundle that E15-3a and E15-3 require before E15-5 executes against the live demo. Broader batch-run canonicalization, stale-cluster reconciliation, and smoke automation remain follow-ons outside this task unless they are required to make the 5-10 image demo path trustworthy.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/TopClusterCard.tsx` | Ensure representative crop/fallback path matches demo contract |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterPreview.tsx` | Replace the current silent placeholder fallback with the named unavailable-image variant used by the demo contract |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/JobTimeline.tsx` | Align `Scan complete` with UI-ready completion |
| frontend | `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineProgress.ts` | Make processed count semantics monotonic for the demo path; only touch `jobStateMachineUtils.ts` if phase derivation must change alongside the timeline predicate |
| tests | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/TopClusterCard.test.tsx` | Add representative-crop vs unavailable-image assertions for top-cluster cards |
| tests | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/ClusterPreview.test.tsx` | Add representative-crop vs unavailable-image assertions for cluster previews |
| tests | `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/JobTimeline.test.tsx` | Add `Scan complete` phase-predicate regressions for `clustering`, `projecting`, and projection-ready completion |
| tests | `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/jobStateMachineProgress.test.ts` | Add monotonic processed-count coverage if Slice 2 changes land in the progress aggregation helper |
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
  - `cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/TopClusterCard.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/ClusterPreview.test.tsx`
  - `cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/workbench/__tests__/JobTimeline.test.tsx`
  - `cd apps/prototype-wp-alt-context && npx vitest run js/admin/hooks/__tests__/jobStateMachineProgress.test.ts`
- Runtime-parity / environment checks:
  - LocalWP seeded-media scan against hosted API after E15-11 proof is green for the Slice 3 demo-gate handoff
- Manual verification:
  - Capture a Workbench screenshot/transcript showing rendered representative avatars, processed count progression, and the point at which `Scan complete` appears

## Slice Delivery

### Slice 1: Representative Avatar Truthfulness

**Goal**: The Workbench renders representative crops when the data exists and shows an explicit fallback/error state when it does not.

Changes:

- Verify top-cluster cards and cluster previews prefer `media_url + bbox` representative crops.
- Replace the current silent `ClusterPreview.tsx` placeholder span with an explicit unavailable-image variant that exposes visible placeholder text or icon treatment plus an accessible label explaining that no representative image is available.
- Keep thumbnail fallback/error states explicit; do not silently render blank placeholders when valid crop data is unavailable.
- Add focused tests in `TopClusterCard.test.tsx` and `ClusterPreview.test.tsx` for representative crop vs unavailable-image fallback behavior.

Proof:

- Vitest coverage in `TopClusterCard.test.tsx` and `ClusterPreview.test.tsx` for representative-crop rendering and the explicit unavailable-image variant.

### Slice 2: Honest Scan/Clustering Progress

**Goal**: The Workbench processed counter and `Scan complete` label are trustworthy during the demo path.

Changes:

- Redefine the scan-complete predicate so the scan milestone is complete only when `scanProgress.phase` is `complete` or `awaiting_projection`; entering `clustering` or `projecting` must no longer mark the scan milestone complete by phase alone.
- Treat UI-ready completion as projection-ready review data, not merely the start of `projecting`; if the implementation needs a second completion gate, pin it to the projection-sync state rather than the pipeline phase name.
- Make the processed indicator monotonic for the seeded-media demo run in `jobStateMachineProgress.ts` unless the implementation proves a different aggregation seam is required.
- Add focused tests in `JobTimeline.test.tsx` and `jobStateMachineProgress.test.ts` around phase transitions, processed-count behavior, and the no-early-`Scan complete` rule.

Proof:

- Vitest coverage proving `clustering` and `projecting` no longer render `Scan complete` by default, plus monotonic processed-count coverage at the aggregation layer.

### Slice 3: Demo Proof Bundle + Regression Handoff

**Goal**: E15-3a and E15-3 require explicit proof before sign-off, and E15-6 has a clear regression target after MVP.

Changes:

- Add run-log requirements for avatar/progress screenshots or annotated transcripts to E15-3a.
- Add explicit dependency notes in E15-3 so public-demo provisioning does not claim readiness before the proof bundle exists; E15-5 consumes that artifact at execution time without requiring a separate planning-doc edit in this branch.
- Carry the proof bundle into E15-6 as the first post-demo regression-automation target.

Proof:

- E15-3a run-log section names the avatar/progress evidence and links the seeded-media demo transcript.

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Do not add rows like `(BR-04 closed)` or "resolve handoff issue X"; finding status lives in MCP / `DASHBOARD.txt`.

## Context and Ownership

- [ ] Loaded the Workbench code anchors, planning findings, and demo-gate docs before implementation.
- [ ] Confirmed the hosted/private-media proof surface from E15-11 is available before treating the LocalWP demo gate as green.
- [ ] Kept the broader scan-pipeline trust/canonicalization work scoped to v0.4.1 unless a defect is proven demo-blocking.

### Checklist for Slice 1: Representative Avatar Truthfulness

- [ ] Representative crop rendering is proven for top clusters and cluster previews.
- [ ] Explicit unavailable-image variants remain visible and accessible when images are unavailable.
- [ ] Focused avatar rendering tests land in `TopClusterCard.test.tsx` and `ClusterPreview.test.tsx`.

### Checklist for Slice 2: Honest Scan/Clustering Progress

- [ ] `Scan complete` no longer appears in `clustering` or `projecting` unless the pinned completion predicate is satisfied.
- [ ] Processed count is monotonic for the seeded-media demo path at the aggregation seam that owns the displayed total.
- [ ] Focused progress/timeline tests land in `JobTimeline.test.tsx` and, when needed, `jobStateMachineProgress.test.ts`.

### Checklist for Slice 3: Demo Proof Bundle + Regression Handoff

- [ ] E15-3a run-log requirements include avatar/progress screenshots or transcript evidence.
- [ ] E15-3 planning surface consumes the proof bundle before demo sign-off, and E15-5 execution reuses that artifact instead of redefining it.
- [ ] E15-6 names this proof bundle as the first post-demo regression target.

## Review Readiness

- [ ] No Workbench-correctness change lands without matching proof in tests or the seeded-media run log.
- [ ] Demo sign-off docs do not treat request success alone as sufficient once avatar/progress proof is required.
- [ ] Slice 2 includes an explicit `JobTimeline.test.tsx` case proving `clustering` and `projecting` do not imply `Scan complete`.
- [ ] Handoff records the avatar/progress contract implications for the public demo path.

## Stretch Goals

- [ ] Pull the broader batch-run aggregate state work from `scan-pipeline-trust-and-data-plane-canonicalization.md` only if the demo path still lies after the focused fixes above.

## Success Criteria

- [ ] The seeded-media Workbench demo shows representative avatars from crop data when available, with explicit unavailable-image states otherwise.
- [ ] The processed counter does not decrease during the demo run, and `Scan complete` appears only after clustering/projection is UI-ready.
- [ ] E15-3a and E15-3 require a run-log proof bundle that captures the avatar/progress behavior the public demo will rely on, and E15-5 reuses that artifact during live-demo execution.
