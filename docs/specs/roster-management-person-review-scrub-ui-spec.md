# Roster Management Person Review and Scrub UI Specification

> **Metadata**
>
> - **Date**: 2026-05-05
> - **Author**: Codex
> - **Status**: Draft
> - **Related assessment**: [docs/assessments/current/recognition-roster-suggestion-workflow-assessment-2026-05-05.md](../assessments/current/recognition-roster-suggestion-workflow-assessment-2026-05-05.md)
> - **Related spec**: [docs/specs/recognition-roster-curation-loop-spec.md](recognition-roster-curation-loop-spec.md)
> - **Related ADR**: [docs/adrs/ADR-009-recognition-curation-refresh-and-person-review-projection.md](../adrs/ADR-009-recognition-curation-refresh-and-person-review-projection.md)
> - **Interaction reference**: pointer-driven face scrub preview with low-latency image switching; implement this behavior locally rather than depending on any external marketing-code path.

This spec proposes a more usable Roster Management page for `wp-admin/admin.php?page=alt-context-roster#/roster`. The page should open on people and review work, not raw clusters. User curation should auto-populate roster entries, and every person entry should provide a scrub interface for reviewing and selecting faces across images.

The current UI has the right ingredients but the wrong center of gravity. It shows an empty Entries tab after curation, while the Clusters tab shows duplicated person cards, raw cluster IDs, identity counts without the linked face context, circular thumbnails with poor aspect handling, and similarity values without enough explanation. The redesign makes the person projection the primary surface and turns clusters into supporting evidence.

**Literature anchors:** DDIA supports treating the person review surface as a derived read model with explicit source facts and freshness (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4727`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4733`). Refactoring UI supports person-first visual hierarchy and contextual score labels (`literature/extracted/refactoring/Refactoring-UI.txt:465`, `literature/extracted/refactoring/Refactoring-UI.txt:617`, `literature/extracted/refactoring/Refactoring-UI.txt:639`). Latency supplies the interaction target for scrub responsiveness and warns against hiding tail delays behind averages (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:592`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:798`). Apple's people-recognition and CurricularFace texts support surfacing singleton proposals, explicit user input, and hard examples as review work (`literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt:95`, `literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt:212`, `literature/extracted/recognition/apple/CurricularFace--Adaptive-Curriculum-Learning-Loss-for-Deep-Face-Recognition.txt:30`).

---

## Observed Current State

The in-app browser was inspected on 2026-05-05 at:

- `http://localhost:10010/wp-admin/admin.php?page=alt-context-roster#/roster`
- `http://localhost:10010/wp-admin/admin.php?page=alt-context-roster#/roster?tab=entries`
- `http://localhost:10010/wp-admin/admin.php?page=alt-context-roster#/roster?tab=clusters`

The current Entries tab renders `No people yet. Add one manually or assign a cluster.` even though the Clusters tab has curated Flaxen Yarrow clusters. The Clusters tab presents several raw cluster cards, including duplicate Flaxen Yarrow cards and unresolved singleton cards. This makes successful curation feel invisible.

Relevant implementation anchors:

- `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesTable.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterGrid.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterDrawerPanel.tsx`
- `apps/prototype-wp-alt-context/src/api/class-api.php::get_roster_entries`
- `apps/prototype-wp-alt-context/src/api/class-api.php::commit_roster_cluster`
- `packages/shared-contracts/schemas/roster-entry.schema.json`

---

## Product Goals

1. Make curation visible immediately.
2. Make the default Roster page person-centric.
3. Let an operator review all images and face instances for one person without bouncing between tabs.
4. Provide a fast scrub interface for comparing face instances and selecting representatives, rejects, split candidates, and hard examples.
5. Preserve the cluster evidence needed by curriculum review queues without making raw clusters the first mental model.
6. Reuse the interaction pattern of pointer-driven preview changes, low-latency frame switching, and compact metadata where it helps, but implement it within the roster UI's own accessible component model.

---

## Non-Goals

- Do not make the Roster page a marketing page.
- Do not introduce new similarity score semantics in this UI spec. RCL-009 owns enhanced score labels, thresholds, floors, and `recomputedAt`.
- Do not make WordPress depend on live backend availability to render existing roster entries.
- Do not replace ADR-009. This UI depends on ADR-009 for the authoritative projection decision.
- Do not implement broad `prototype-description-service` refactoring as part of this surface. Only use enabling refactors already allowed by E15-13.

---

## Proposed Information Architecture

The Roster page should have one primary layout instead of two competing tabs.

Refactoring UI's hierarchy guidance is the reason this spec changes the default center of gravity: the selected person, review state, representative/candidate faces, and primary decision should outrank raw cluster IDs and counts (`literature/extracted/refactoring/Refactoring-UI.txt:465`, `literature/extracted/refactoring/Refactoring-UI.txt:733`).

```text
Roster
  Review queue strip
    Needs names | Singleton proposals | Hard examples | Needs confirmation | All people

  People workspace
    Left: people list grouped by review state
    Center: selected person review surface with face scrubber
    Right: cluster/evidence drawer, only when useful
```

The current Entries and Clusters tabs can remain as deep links during migration, but the default route should become the person review workspace. A cluster-only grid can move behind a secondary "Cluster evidence" mode for debugging and batch review.

---

## Spec Items

### RSU-001: Auto-populate roster entries from every user curation

**Priority:** P0  
**Depends on:** ADR-009, RCL-004  
**Current problem:** The Entries tab can be empty after a cluster is assigned to a person.

Every successful cluster label, bind, merge confirmation, or person assignment should create or update a roster person projection. The UI should not require the operator to manually create a person after they have already curated a cluster.

DDIA's materialized-view guidance requires this projection to update when underlying curation facts change, because the person review surface is a read model over `wp_acx_persons`, clusters, identities, media, and refresh state (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4727`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4733`).

**Done when:**

- `commit_roster_cluster` updates the local person projection or triggers a durable projection refresh.
- `useRosterEntries()` returns a person entry immediately after a successful cluster assignment.
- A newly curated person appears in the default roster workspace without a full browser refresh.
- Empty state copy is only shown when there are no curated persons and no queued curation results.

### RSU-002: Replace the default cluster grid with a person review workspace

**Priority:** P0  
**Depends on:** RSU-001

The default Roster page should show people first. Each person row should include:

- Representative face thumbnail.
- Display name or unresolved label.
- Person UUID or stable short ID in secondary metadata.
- Counts for clusters, images, and face instances.
- Review state: clean, needs confirmation, singleton proposals, hard examples, merge review.
- Last curated time.
- Suggestion refresh status when present.

Clusters bound to the same `person_uuid` should collapse under the same person context. Duplicate Flaxen Yarrow cards should become one Flaxen Yarrow person row with multiple supporting clusters.

**Done when:**

- The default view is useful after the first curated cluster.
- Duplicate named clusters do not appear as separate primary identities.
- Operators can filter by review state without understanding cluster topology first.
- Raw cluster IDs remain discoverable in evidence details.

### RSU-003: Add a person face scrubber for review and selection

**Priority:** P0  
**Depends on:** RCL-004

The selected person review surface should include a scrub interface inspired by the marketing static face-pose viewer. The scrubber is not a decorative avatar. It is an operational review control for moving through face instances quickly.

Latency's human-perception threshold makes the preview swap feel "instant" only if common interactions respond inside roughly 100 ms, while its tail-latency guidance means tests should cover slow thumbnails and refresh updates without layout jumps (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:592`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:798`).

**Layout:**

- Large preview panel using the true face crop aspect ratio.
- Horizontal filmstrip of all face instances for the person.
- Scrub rail where pointer movement or keyboard navigation changes the preview.
- Metadata panel for the current face: media title, media ID, cluster ID, identity ID, score, curation state, and source job.
- Selection controls for representative face, accept, reject, split, merge target, and hard-example flag.

**Interaction:**

- Pointer drag across the filmstrip updates the preview with no layout shift.
- Arrow keys move one instance at a time.
- Shift plus arrow extends selection.
- Space toggles selected state.
- Enter opens the media detail or source image.
- The scrubber preserves scroll position and selected index when a background refresh completes.

**Done when:**

- Operators can review all instances of a person from one surface.
- Selecting a representative face does not require opening the cluster drawer.
- Face crops are shown with correct aspect ratio and stable dimensions.
- The UI can select one face, many faces, or all faces in a cluster for downstream actions.

### RSU-004: Keep clusters as evidence, not the primary identity model

**Priority:** P1  
**Depends on:** RCL-005

Cluster cards should support review work without owning the page. The cluster drawer should be person-aware:

- If `person_uuid` exists, show the linked person and offer "Open person review".
- If no `person_uuid` exists, show the cluster in unresolved review mode.
- If the cluster is a singleton proposal, show its suggested target person and similarity context.
- If the cluster was merged or superseded, show its current topology state instead of another primary identity card.

**Done when:**

- The operator can understand why a cluster appears.
- Cluster counts identify what they count: clusters, face identities, images, or face instances.
- The drawer links to the person review surface by `person_uuid`.
- Merged clusters do not look like unmerged duplicate identities.

### RSU-005: Add curriculum review queues above the people workspace

**Priority:** P1  
**Depends on:** RCL-008

The queue strip should surface the Apple curriculum review work in plain operator terms:

Apple's people-recognition paper describes clustering plus explicit user input as part of gallery formation, and CurricularFace motivates hard-example handling; the UI should therefore name those queues rather than bury them as generic cluster states (`literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt:95`, `literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt:216`, `literature/extracted/recognition/apple/CurricularFace--Adaptive-Curriculum-Learning-Loss-for-Deep-Face-Recognition.txt:89`).

- `Needs names`: curated or clustered faces without a person label.
- `Singleton proposals`: singletons suggested for an existing person.
- `Hard examples`: low-confidence or high-disagreement instances that need a human decision.
- `Needs confirmation`: clusters affected by merge or label changes that need another pass.
- `All people`: stable person roster.

Each queue item should open the same person review surface when a person exists, or unresolved cluster review mode when it does not.

**Done when:**

- The curriculum work is visible without visiting a debug page.
- Queues share one review surface instead of spawning unrelated workflows.
- Queue counts are derived from durable projection state, not transient client filtering alone.

### RSU-006: Show similarity values with local context first

**Priority:** P1  
**Depends on:** RCL-006 now, RCL-009 later

The UI should stop showing bare percentages as if they were self-explanatory. Until RCL-009 lands, use existing fields and conservative copy:

Refactoring UI's label/value guidance is the anchor for this requirement: score labels should clarify the value in the same unit of meaning instead of adding disconnected labels that flatten hierarchy (`literature/extracted/refactoring/Refactoring-UI.txt:617`, `literature/extracted/refactoring/Refactoring-UI.txt:639`).

- `Match evidence from current cluster response`
- `Compared with selected person`
- `Higher is closer within this batch`

After RCL-009 lands, the same UI slot should render:

- Source identity.
- Target person or target cluster.
- Score type.
- Threshold.
- Floor.
- Recomputed time.

**Done when:**

- Existing score fields are not overclaimed.
- Enhanced score details have a stable place in the design.
- Slice 4 cannot ship a score label that hides source, target, score type, threshold, floor, or recompute status once the backend contract exists.

### RSU-007: Make thumbnail policy face-first and aspect-correct

**Priority:** P1  
**Depends on:** none

Thumbnails should respect face crop aspect ratio and use consistent boxes. Circular thumbnails are acceptable only for chosen representative faces, not for evidence review where crop boundaries matter.

**Done when:**

- Evidence thumbnails use rectangular or square crops with `object-fit: contain` or crop-aware rendering.
- Representative thumbnails can use a softer presentation but keep the actual face legible.
- No thumbnail stretches faces.
- Layout dimensions remain stable while images load.

---

## Data Shape

The canonical wire contract is `RCL-004` in [docs/specs/recognition-roster-curation-loop-spec.md](recognition-roster-curation-loop-spec.md). The UI types below describe the expected rendering shape after consuming that projection and may add clearly-labeled UI-derived fields, but they do not replace the shared schema as the source of truth.

```ts
interface RosterPersonReview {
  id: number;
  person_uuid: string;
  name: string;
  tags: string[];
  representative_face: FaceInstance | null; // UI convenience view over RCL-004 representative evidence.
  review_state: "clean" | "needs_name" | "singleton_proposals" | "hard_examples" | "needs_confirmation";
  counts: {
    clusters: number;
    images: number;
    instances: number;
    pending_suggestions: number;
  };
  clusters: PersonClusterEvidence[];
  queue_memberships: string[];
  projection_status: "current" | "refreshing" | "stale" | "failed";
  suggestion_refresh_status?: SuggestionRefreshStatus;
  updated_at: string;
}

interface PersonClusterEvidence {
  cluster_id: string;
  label: string | null;
  topology_state: "active" | "merged" | "superseded" | "singleton";
  identity_count: number;
  instances: FaceInstance[];
}

interface FaceInstance {
  identity_id: string;
  media_id: number;
  media_title?: string;
  media_url?: string;
  thumb_url: string;
  bbox?: [number, number, number, number];
  cluster_id: string;
  similarity?: number | null;
  source_job_id?: string;
  curation_state: "accepted" | "rejected" | "pending" | "hard_example" | "split_candidate";
}
```

UI-derived fields such as `review_state` are presentation helpers layered on top of the RCL-004 projection. Shared fields including `queue_memberships`, `projection_status`, and refresh state must remain aligned with the RCL-004/shared-schema contract rather than diverging in a TypeScript-only definition.

---

## Route Proposal

```text
#/roster
#/roster?queue=singleton-proposals
#/roster?queue=hard-examples
#/roster?person={person_uuid}
#/roster?person={person_uuid}&face={identity_id}
#/roster?cluster={cluster_id}
```

The route should deep-link the selected person and selected face. Cluster links should resolve to the person workspace when possible. If the cluster is unassigned, the route opens unresolved cluster review mode.

---

## Migration Plan

1. Keep the current Entries and Clusters tabs as secondary routes.
2. Add the person review workspace through an alternate route and compatibility navigation, not a feature flag.
3. Teach `useRosterEntries()` to request the enriched projection when available.
4. Build the scrubber using current thumbnails first.
5. Add queue filters once RCL-008 projection data exists.
6. Retire the raw cluster grid as the default after the person workspace handles assigned and unresolved cases.

---

## Acceptance Checklist

- A curated Flaxen Yarrow cluster creates or updates one Flaxen Yarrow roster person.
- Duplicate Flaxen Yarrow clusters appear under one person review surface.
- The singleton `cluster-e22d355c86504443896d9bd73c54b80e` appears in the singleton proposals queue when suggested.
- The person review surface can scrub all Flaxen Yarrow face instances.
- Face selection supports representative, accept, reject, split, and hard-example decisions.
- The Entries empty state is not shown after successful user curation.
- Similarity copy explains what the current score can and cannot mean.
- Thumbnail aspect ratio is correct in cards, drawers, and the scrub preview.

---

## Planning Notes

This proposal is compatible with E15-13, but it is larger than a narrow fixture and projection repair. The minimum E15-13 UI work should cover auto-populated person entries, person-aware cluster grouping, and a basic scrub review surface if the projection data lands. A polished scrubber, selection batching, and final cluster-grid deprecation can be a follow-on slice if the implementation risk grows.

The marketing static scrubber is useful as an interaction reference, especially its pointer-driven nearest-frame lookup and low-latency image switching. The WordPress UI should not reuse that code directly without adapting it to accessibility, keyboard selection, persistent curation actions, and backend projection state.
