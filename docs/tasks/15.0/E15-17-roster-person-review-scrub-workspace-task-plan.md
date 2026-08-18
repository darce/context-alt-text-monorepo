# E15-17. Roster Person Review Scrub Workspace

> **Metadata**
>
> - **Date**: 2026-05-05 21:15 EST
> - **Author**: GitHub Copilot
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-17
> - **Target Branch**: `feature/e15-17-roster-person-review-scrub-workspace`
> - **Review Coverage Target**: 2

---

## Objective

Build the person-first roster review workspace that sits on top of the ADR-009/E15-13 projection model. When this task is complete, the Roster page opens on people and review queues, one curated person owns all related face evidence, and operators can scrub, select, and act on face instances without using raw clusters as the primary identity model.

## Problem Statement

[docs/specs/roster-management-person-review-scrub-ui-spec.md](../../specs/roster-management-person-review-scrub-ui-spec.md) shows that the current Roster page has the ingredients for person review but the wrong center of gravity. E15-13 owns the curation loop, post-curation refresh, roster entry projection, and curriculum queue contracts. This task owns the larger UI follow-through once those projection contracts exist: the person workspace, scrub interface, route model, and cluster-as-evidence migration.

## Constraints

- Implementation depends on ADR-009 and E15-13 projection/queue contract work passing planning review and landing enough data. Slice 1 may render a baseline-only default workspace shell with today's `person_uuid`, `name`, `cluster_count`, `source_version`, `projection_status`, and `projection_refreshed_at` fields, but the richer queue strip / representative evidence / queue-membership shell stays blocked until E15-13 records the Slice 3 `close_slice` decision for the person-review projection landing and the regenerated `packages/shared-contracts/schemas/roster-entry.schema.json` plus generated types expose those upstream fields.
- Do not replace ADR-009 or change `wp_acx_persons` authority.
- Do not introduce new similarity score semantics beyond fields supplied by E15-13/RCL-009.
- Build the scrubber as a roster-local component under `apps/prototype-wp-alt-context/js/admin/pages/roster/`; do not import UI code from outside that path without explicit accessibility, keyboard, and curation-state adaptation review.

## Workflow Principles

- Person is the local source-of-truth entity; roster review data is a derived projection.
- Clusters are evidence and topology, not the primary operator identity model after curation.
- Face review should be fast, keyboard-accessible, aspect-correct, and stable under background refresh.

## Terminology

- **Person workspace**: The default Roster surface with queue strip, people list, selected person review, and optional evidence drawer.
- **Face scrubber**: A low-latency review control for moving through face instances and selecting representative, accepted, rejected, split, or hard-example states.
- **Cluster evidence mode**: A secondary route/drawer for raw cluster details, unresolved clusters, and topology evidence.

## Current State Analysis

- The current Entries tab can be empty after cluster curation because roster entries are count-only.
- The Clusters tab can show duplicate named cluster cards and unresolved singleton cards as separate primary identities.
- Cluster thumbnails and similarity copy do not provide enough person/face review context.
- E15-13 already plans the post-curation event, refresh status, person review projection, and curriculum queues that this UI needs.

## Target Outcome

The default Roster route shows a review queue strip and a person workspace. A curated Flaxen Yarrow cluster becomes one Flaxen Yarrow person row with supporting clusters and face instances. Operators can scrub all instances, choose representative faces, accept/reject/split/flag hard examples, and deep-link to a person, face, or unresolved cluster.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md`
- Rules: `docs/agentic/rules/frontend-guidelines.md`
- Rules: `docs/agentic/rules/testing-typescript.md`
- Spec: `docs/specs/roster-management-person-review-scrub-ui-spec.md`
- Spec: `docs/specs/recognition-roster-curation-loop-spec.md`
- ADR: `docs/adrs/ADR-009-recognition-curation-refresh-and-person-review-projection.md`
- Prerequisite task: `docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md`
- Handoff/MCP state: E15-13 decisions/findings, active task `E15-17`, open planning findings
- External docs via `ctx7` only if: React interaction/testing behavior blocks a concrete implementation decision.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Roster entry projection -> UI | plugin + shared contracts + frontend | E15-13 enriched `RosterPersonReview` projection | consume projection as default person workspace | Yes; E15-13 must land projection before full UI | shared contract checks + Vitest |
| Roster routes | frontend | Entries/Clusters tabs and cluster drawer deep links | person/queue/face/cluster deep links | Existing routes remain during migration | React route tests/manual browser |
| Curation actions | plugin REST + frontend | existing accept/bind/dismiss actions plus E15-13 review actions | scrubber controls call existing/new review actions | No fabricated actions; actions must map to API | Vitest + PHPUnit where API changes |

## Proposed Solution

Use E15-13 as the data-contract prerequisite, then build the person-first Roster workspace in four slices: route shell and queue strip, person list/detail projection rendering, face scrubber interactions, and cluster evidence migration. Keep raw Entries/Clusters routes as secondary compatibility paths until the workspace handles assigned and unresolved cases.

Implementation may begin route parsing earlier, and Slice 1 may replace the legacy default table with a baseline-only person workspace shell backed by the currently landed projection fields (`person_uuid`, `name`, `cluster_count`, `source_version`, `projection_status`, `projection_refreshed_at`). The richer queue strip and evidence-heavy shell remain gated on concrete upstream artifacts: E15-13 Slice 3 must record a slice-complete decision for the projection/navigation landing, `packages/shared-contracts/schemas/roster-entry.schema.json` must be regenerated with the representative evidence and queue-membership fields consumed here, and generated TypeScript types must refresh from that schema before those richer Slice 1 affordances enable.

## Dependency Gate

| Slice | Minimum upstream contract before work begins | Why |
| --- | --- | --- |
| Slice 1: Workspace Shell and Route Model | Queue/person/face/cluster routes parse immediately. A baseline-only default workspace shell may render with today's `person_uuid`, `name`, `cluster_count`, `source_version`, `projection_status`, and `projection_refreshed_at` fields, but queue strip / representative evidence / queue-membership rendering stays blocked until E15-13 Slice 3 records the projection/navigation `close_slice` decision and the regenerated `packages/shared-contracts/schemas/roster-entry.schema.json` plus generated TS types expose those richer fields | Prevent the legacy table from remaining the default surface while still blocking richer workspace affordances on the upstream projection artifacts |
| Slice 2: Person Projection Rendering | The Slice 1 gate is satisfied, and E15-13's RCL-005 person-aware cluster grouping / navigation contract is implemented in the roster payload and cluster drawer | Person rows and grouped evidence need the canonical projection and grouping contract |
| Slice 3: Face Scrubber and Selection Controls | RCL-002 per-event refresh status available if refresh badges are shown, and every enabled control has a real API/action row in the action matrix below; RCL-009 remains optional unless enhanced score evidence is rendered | Prevent scrubber controls from outrunning the underlying action/status contracts |
| Slice 4: Cluster Evidence Migration | RCL-005 topology state and RCL-008 queue membership labels implemented | Assigned, unresolved, merged, superseded, and curriculum-queue evidence all depend on those upstream fields |

## Action-to-API Matrix

| Scrubber control | Owning endpoint or contract | Availability |
| --- | --- | --- |
| Representative face | `PATCH /acx/v1/recognition/clusters/{cluster_id}/representatives/{representative_id}/pin` via `ClusterMutationsController` | Exists today |
| Accept suggestion | `POST /acx/v1/recognition/suggestions/{suggestion_id}/accept` plus merge/name variants in `SuggestionsController` | Exists today |
| Reject suggestion | `POST /acx/v1/recognition/suggestions/{suggestion_id}/reject` plus merge/name variants in `SuggestionsController` | Exists today |
| Split selected faces | `POST /acx/v1/recognition/clusters/{cluster_id}/split` via `ClusterMutationsController` | Exists today, but the scrubber can only call it after E15-13 defines the face-selection payload it should send |
| Merge target | `POST /acx/v1/recognition/clusters/{source_id}/merge` via `ClusterMutationsController` | Exists today, but the person-review UI depends on E15-13 for target-cluster selection context |
| Hard-example flag | E15-13 / RCL-008 review-action contract | Not available today; keep disabled or hidden until that contract lands |

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| roster page shell | `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx` | Make person workspace the default route when projection data exists |
| roster entries | `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx` | Migrate from table-only view to person list/workspace |
| person review UI | `apps/prototype-wp-alt-context/js/admin/pages/roster/` | Add person workspace, face scrubber, queue strip, evidence drawer integration |
| cluster drawer | `apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterDrawerPanel.tsx` | Link to person review by `person_uuid`; keep unresolved cluster mode |
| roster styles | `apps/prototype-wp-alt-context/js/admin/styles/components/_cluster-grid.scss` and adjacent roster styles | Aspect-correct, stable review layout with existing tokens |
| tests | `apps/prototype-wp-alt-context/js/admin/pages/roster/**/__tests__` | Cover routes, queues, scrubber, and evidence modes |

## Related Files

| File | Note |
| --- | --- |
| `packages/shared-contracts/schemas/roster-entry.schema.json` | E15-13 projection contract consumed here |
| `apps/prototype-wp-alt-context/src/api/class-api.php` | Roster entry/API actions owner, primarily E15-13 |
| `docs/specs/recognition-roster-curation-loop-spec.md` | RCL-004, RCL-005, RCL-008, RCL-009 define data dependencies |
| `docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md` | Must provide projection, queues, and action contracts before full UI polish |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && npm test -- --run js/admin/pages/roster`
- Runtime-parity / environment checks:
  - Open `http://localhost:10010/wp-admin/admin.php?page=alt-context-roster#/roster` after seeded curation and verify person workspace defaults.
- Contract/fixture verification:
  - Shared roster-entry schema/codegen checks from E15-13 are green before consuming enriched projection fields.
- Manual verification:
  - Deep links for `#/roster?queue=singleton-proposals`, `#/roster?person={person_uuid}`, `#/roster?person={person_uuid}&face={identity_id}`, and `#/roster?cluster={cluster_id}` behave as specified.

## Slice Delivery

### Slice 1: Workspace Shell and Route Model

**Goal**: Introduce the person-first Roster route without removing existing tabs.

Changes:

- Add route parsing for queue, person, face, and cluster query params.
- Render the baseline default workspace shell with the currently landed projection fields as soon as the route model is in place; keep queue strip and richer evidence content behind the Slice 1 dependency gate until the upstream projection artifacts land.
- Keep current Entries/Clusters modes reachable as secondary paths during migration.
- Treat the first current projected person as a temporary Slice 1 default-selection fallback only; Slice 2 must replace it with a deterministic canonical rule.

Proof:

- Vitest covers default route, queue route, person route, face route, and unresolved cluster route.

### Slice 2: Person Projection Rendering

**Goal**: Render one person row/detail surface from the E15-13 projection.

Changes:

- Show representative face, counts, review state, queue memberships, projection status, and refresh status.
- Collapse clusters under person context instead of separate primary identity cards.
- Preserve raw cluster IDs in evidence details.
- Replace the temporary Slice 1 "first current projected person" fallback with a deterministic default-selection rule (queue head once queue data lands; until then, use a stable alphabetical-by-name fallback with person UUID / row ID tiebreakers) and cover it in Vitest.
- Before the person-aware cluster payload lands from RCL-005, Slice 2 may still enrich the workspace with person-summary evidence sourced only from `RosterEntry` fields (formatted projection freshness, tags, grouped cluster count summary), but must not invent person-linked cluster grouping from raw cluster labels alone.

Proof:

- Vitest proves duplicate Flaxen Yarrow clusters render as one person with multiple evidence clusters.

### Slice 3: Face Scrubber and Selection Controls

**Goal**: Let operators review and select face instances quickly and accessibly.

Changes:

- Add aspect-correct preview, filmstrip, scrub rail, metadata panel, and keyboard controls.
- Wire representative, accept, reject, split, merge target, and hard-example controls only when the matching action-matrix row is available; hidden or disabled controls stay documented as E15-13 dependencies.
- Keep the metadata panel on RSU-006 conservative copy until RCL-009 lands: name score context as current-cluster evidence compared with the selected person, forbid bare percentages that imply threshold/floor semantics, and only show enhanced score metadata after the upstream contract exists.
- Preserve selected face and scroll position across background refreshes.

Proof:

- Vitest covers pointer/keyboard navigation, selection, representative action, refresh stability, and no layout-shift regressions at the component level.

### Slice 4: Cluster Evidence Migration

**Goal**: Keep clusters useful as evidence while removing them as the default identity model.

Changes:

- Make cluster drawer person-aware with `Open person review` when `person_uuid` exists.
- Render unresolved clusters in review mode without inventing a person link.
- Show merged/superseded topology state instead of duplicate primary identities.

Proof:

- Vitest covers assigned, unresolved, and singleton proposal cluster drawer states. _Merged/superseded states deferred with the scope narrowing recorded in decision 4617._

## Consolidated Checklist

## Context and Ownership

- [x] Loaded ADR-009, E15-13, the roster scrub spec, and frontend/testing rules before editing.
- [x] Confirmed E15-13 projection fields and action contracts exist before consuming them.
- [x] Recorded any boundary ownership changes if the UI needs fields/actions beyond E15-13. _No new boundary fields needed; consumed existing RosterEntry shape._

### Checklist for Slice 1: Workspace Shell and Route Model

- [x] Person, queue, face, and cluster routes parse deterministically. _`parseRosterRoute` + URLSearchParams gating; tests in `rosterRoute.test.ts`._
- [x] Existing Entries/Clusters routes remain reachable during migration. _`?personFilter=...` and `?cluster=...` keep the prior surfaces; verified by `RosterPage.container.test.tsx [PAG-M3]` and `RosterPage.test.tsx`._
- [x] Route tests captured. _`apps/prototype-wp-alt-context/js/admin/pages/roster/__tests__/rosterRoute.test.ts`._
- [x] Slice 1 baseline default-shell fallback is explicitly temporary and documented. _Dependency-gate carve-out updated; rendering enrichment moved to Slice 2._

### Checklist for Slice 2: Person Projection Rendering

- [ ] Person rows render representative evidence, counts, review state, queue memberships, and projection status. _Partial: name, cluster_count, projection_status, projection_refreshed_at, source_version, and tags rendered; review-state and queue-membership rendering deferred until those projection fields land._
- [x] Bound clusters collapse under one person context. _`PersonWorkspacePanel` renders assigned cluster evidence grouped under the selected person from the RCL-004 `clusters[]` projection; review-state and queue-membership rendering remain tracked by the preceding unchecked row._
- [x] Duplicate person cluster fixture covered. _`rosterRoute.test.ts` covers duplicate-name UUID tiebreak and numeric-id tiebreak cases for `selectDeterministicDefaultWorkspaceEntry`._
- [x] Default workspace selection follows a documented deterministic rule rather than first projection-row order. _Sorted by lowercased name → person_uuid → numeric id with locale-stable `localeCompare('en', { sensitivity: 'base' })`._

### Checklist for Slice 3: Face Scrubber and Selection Controls

- [x] Scrubber supports pointer and keyboard navigation. _Rail-scoped activedescendant listbox in `PersonFaceFilmstrip.tsx` (Arrow/Home/End, single tab stop) plus pointer selection; covered by `__tests__/PersonWorkspacePanel.scrubber.test.tsx` and `hooks/__tests__/useRosterFaceCursor.test.tsx`._
- [x] Face crop dimensions are stable and aspect-correct. _`FaceThumbnail` reserves explicit 64px box across loading/loaded/error states; layout-shift assertions hardened per review Slice 3 findings._
- [x] Selection actions map only to real API actions and are tested. _Representative pin maps to the existing pin API via `hooks/usePinRepresentative.ts` (pending guard, cache invalidation, error surface); no fabricated accept/reject/split controls shipped — those stay documented E15-13 dependencies._
- [x] Metadata panel follows RSU-006 conservative labels until RCL-009 fields land and does not overclaim similarity semantics. _`similarityCopy.ts` renders banded labels ("strong/likely/possible/weak match") with current-cluster framing and no bare percentages; consumed by `PersonFaceMetadataPanel.tsx`._

### Checklist for Slice 4: Cluster Evidence Migration

- [x] Assigned cluster drawer links to person review by `person_uuid`. _`ClusterDrawerPanel.tsx` renders `Open person review` as a real `a[href]` to `#/roster?person=<uuid>` with modifier-aware SPA navigation; `person_uuid` flows from the `wp_acx_persons` LEFT JOIN in `class-clusters-read-repository.php` through `class-cluster-response-mapper.php`; covered by `ClusterDrawerPanel.personAware.test.tsx` and `RosterPage.container.test.tsx`._
- [x] Unresolved clusters stay in unresolved review mode. _`clusterDrawerState.ts` classifies null/empty/whitespace `person_uuid` as unresolved (0-identity stale projections included) with no invented person link; boundary fixtures in `ClusterDrawerPanel.personAware.test.tsx` and the invention-vector guard in `RosterPage.test.tsx`._
- [ ] Merged/superseded clusters explain topology state. _Deferred: `merge_cluster` deletes source rows (greenfield delete-over-flag), so merged/superseded topology cannot be rendered without fabricating contract metadata (rg-015); scope narrowed per handoff decision 4617 to a future persist-on-merge schema task._

## Review Readiness

- [x] No UI field or action is consumed before the owning projection/API contract exists. _Only consumed pre-existing `RosterEntry` schema fields._
- [ ] Runtime roster check proves a curated person opens in the person workspace. _Pending live-WordPress verification once Slice 3/4 ships._
- [x] Handoff decision records ADR-009/E15-13 dependency status and verification. _Recorded in slice_complete decisions for the four slices that landed on this branch._

## Stretch Goals

- [ ] Retire the old cluster grid as the default route once assigned and unresolved cases are covered.

## Success Criteria

- [x] The default Roster route is person-first after projection data exists. _`RosterPage.tsx` computes `defaultWorkspaceRoute` from projection entries; `RosterPage.workspace.test.tsx` covers workspace routing._
- [ ] A curated Flaxen Yarrow cluster appears as one person with all supporting face evidence.
- [ ] Operators can scrub, select, and act on face instances from one surface.
- [x] Raw cluster evidence remains available without being the primary identity model. _`PersonWorkspacePanel` keeps assigned-cluster evidence inside the person context while legacy cluster routes remain available during the migration._
