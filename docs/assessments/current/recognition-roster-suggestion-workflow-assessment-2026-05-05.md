# Recognition Roster Suggestion Workflow Assessment

> **Metadata**
>
> - **Date**: 2026-05-05
> - **Author**: Codex
> - **Scope**: Recognition clustering, roster curation, suggestion surfacing, and `apps/prototype-description-service` robustness
> - **Status**: Draft
> This assessment traces why curated face clusters are not becoming obvious roster review surfaces, why singleton and merge suggestions can disappear after curation, and why the cluster UI is exposing backend topology instead of person-centric state. The strongest current signal is that local WordPress roster curation, backend curation replay, and suggestion refresh are implemented as separate workflows with different data contracts. A user can label or bind a cluster locally, but the backend path that normally surfaces suggestions is not necessarily invoked, and the roster entry read model cannot yet show the images and instances the user expects to review.

**Related docs:**

- `docs/agentic/templates/ASSESSMENT.template.md`
- `docs/adrs/ADR-002-person-as-first-class-local-entity.md`
- `docs/adrs/ADR-003-wordpress-local-authority-and-durable-outbox-replay.md`
- `docs/assessments/clustering-pipeline-postgres-refactor-literature-2026-04-26.md`
- `docs/scopes/pds-pipeline-stability-26.md`
- `literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt`
- `literature/extracted/recognition/apple/CurricularFace--Adaptive-Curriculum-Learning-Loss-for-Deep-Face-Recognition.txt`
- `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt`
- `literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt`
- `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt`
- `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt`
- `literature/extracted/refactoring/modern-software-engineering.txt`
- `literature/extracted/refactoring/Refactoring-UI.txt`

## Executive Summary

The current product expectation is person-centric: once a user curates an entity cluster, the system should treat that curation as training signal, surface nearby candidate clusters or singleton faces, adjust similarity context after curation, and create a roster entry where all images and face instances for that person can be reviewed. The codebase currently implements pieces of that model, but the pieces are not composed into one reliable workflow.

The most likely explanation for the reported batch job behavior, including singleton `cluster-e22d355c86504443896d9bd73c54b80e` being left behind instead of being suggested into the Flaxen Yarrow cluster, is that suggestion surfacing is only triggered on selected backend paths. A backend `PATCH /clusters/{id}` label update can schedule `surface_for_newly_labeled_cluster`, but the WordPress local roster commit path writes a local person binding and emits `cluster_person_bound`; backend curation sync applies `roster_id` without deriving the person label or invoking the same suggestion refresh path. Merge follow-up is also narrow: the curation job calls `refresh_for_cluster`, which updates existing pending suggestions for a target cluster but does not create missing suggestions when none exist.

The roster and cluster UI confusion follows from the same split. The cluster tab lists raw cluster rows, not a person-consolidated read model, so multiple clusters can remain visible for the same identity after workbench merges. The roster entries contract returns only person metadata and `cluster_count`, so entries can appear empty or non-reviewable even after curation. Thumbnail and similarity UI add friction because face crops are forced into square/circular thumbnails and similarity values are not explained as face-to-representative, face-to-centroid, threshold, floor, or post-curation deltas.

The refactoring literature and existing service refactor work point toward the same direction: keep adapter timeouts, circuit breakers, and pool isolation, but move suggestion refresh and projection updates into durable, bounded workflows with explicit contracts and observable state. The next step should be a spec that unifies curation, roster entries, and suggestion surfacing before implementation slices begin.

For planning, the most relevant refactoring frame is source-of-truth plus derived-data clarity. `Designing Data-Intensive Applications` distinguishes systems of record from derived data, and notes that explicit inputs/outputs clarify otherwise confusing architecture (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15680`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15700`). The next spec should treat WordPress roster curation as authoritative local input, backend suggestion queues as derived/projection work, and roster review tables as materialized read models that can be rebuilt or refreshed.

## Issue Coverage Outline

This outline is intended as the cross-reference checklist for follow-on artifacts.

| User issue | Assessment findings | Recommended direction |
| ---------- | ------------------- | --------------------- |
| Batch job `4f7236f5-55ed-4b55-8eae-51e5b7d256f4` left `cluster-e22d355c86504443896d9bd73c54b80e` as a singleton | F2, F3, F4, F9 | Reproduce the job against DB/API state, then define a durable post-curation suggestion refresh contract |
| Singleton should be suggested into Flaxen Yarrow cluster after initial curation | F1, F2, F3 | Make local roster binding and backend curation replay invoke the same newly-labeled-cluster suggestion workflow |
| Similarity percentage should adjust after user curation | F2, F3, F8 | Recompute and expose suggestion similarity context after curation, not only on initial clustering |
| Suggestion workflow no longer surfaces in UI | F1, F2, F3, F4, F8 | Connect curation sync, suggestion refresh, and UI suggestion surfaces with durable status |
| Apple recognition literature is present but not obvious to user | F9 | Surface curriculum/singleton/proposal state as user-facing review queues, not generic cluster copy |
| `prototype-description-service` is brittle and complex | F10 | Continue the refactor around durable orchestration, explicit contracts, bounded background work, and smaller use cases |
| Cluster page shows multiple clusters for one identity after merge | F5 | Make the cluster list person-aware and topology-aware |
| Cluster identity counts do not identify which face is linked | F7, F8 | Show representative face, candidate face, score context, and member/instance provenance |
| Similarity values lack context | F8 | Label score type, threshold, floor, and before/after curation meaning |
| Thumbnail aspect ratio is incorrect | F7 | Use inspectable face crops and media aspect policy instead of forced circular square thumbnails |
| Roster entries remain empty after curation | F1, F6 | Expand roster entries from person counts to reviewable person clusters, identities, images, and instances |

## Findings

### F1. Local roster commits do not carry a complete backend curation signal

The WordPress local roster commit path creates or binds a local person and marks the cluster user-confirmed, but the outbox payload only sends the cluster UUID and person UUID. Backend curation sync applies the `roster_id` but does not derive the person label for `cluster_person_bound`, and the sync endpoint does not invoke suggestion surfacing.

Current examples:

- `apps/prototype-wp-alt-context/src/api/class-api.php:363` - `commit_roster_cluster` creates or resolves a local roster person and updates the local cluster.
- `apps/prototype-wp-alt-context/src/api/class-api.php:492` - the outbox payload for `cluster_person_bound` includes `cluster_uuid` and `person_uuid`, but not the person label/name.
- `apps/prototype-description-service/roster/application/curation_sync_service.py:113` - curation sync applies `cluster.roster_id`, `cluster.label`, and dismissed state directly.
- `apps/prototype-description-service/roster/application/curation_sync_service.py:239` - `_resolve_desired_label` changes the label for `cluster_label_updated`, but leaves `cluster_person_bound` at the current label.
- `apps/prototype-description-service/roster/interface_adapters/http/curation_router.py:48` - `/curation/sync` applies curation operations and returns results without handing off to suggestion refresh.

**Impact:** A user can successfully curate a cluster in WordPress while the backend never sees the equivalent of a newly labeled cluster. That breaks the expectation that curation trains the suggestion workflow.

**Planning literature:** DDIA's system-of-record/derived-data distinction is directly applicable here: curation facts should be represented once in the authoritative record, while suggestion state and roster review projections should declare what they derive from (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15682`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15688`). Fowler's Divergent Change guidance more directly supports the cross-path sync concern: if a change requires scattered updates across unrelated contexts, those contexts need clearer module boundaries (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:2060`). Fowler's mutable-data guidance remains relevant only for the narrower query/mutation separation point (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:2053`).

### F2. Suggestion surfacing is coupled to backend label updates, not all curation paths

The backend cluster label route schedules `surface_for_newly_labeled_cluster` only when a cluster is labeled through that route. Local WordPress roster commits and backend curation sync do not share that same trigger.

Current examples:

- `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py:904` - `PATCH /clusters/{cluster_id}` is the backend label update route.
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py:928` - the route calls `cluster_service.update_cluster(... surface_suggestions=False)`.
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py:959` - when a label is submitted and the cluster was not already user-confirmed, the route schedules `run_background_surface_suggestions`.
- `apps/prototype-description-service/recognition/application/orchestration/cluster_service.py:290` - `update_cluster` can surface suggestions directly only when called with `surface_suggestions=True`.
- `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py:456` - `surface_for_newly_labeled_cluster` is the main workflow that scans unlabeled clusters against a newly labeled cluster.

**Impact:** Suggestion surfacing depends on which API path performed the curation. The same user intent can produce different system behavior.

**Spec decision point:** The current backend route does not re-surface suggestions when an already user-confirmed cluster is re-labeled or corrected. The spec must decide whether that is intentional protection against noisy refreshes or a gap to close with explicit "label correction" refresh semantics.

**Planning literature:** Fowler's "Split Phase" guidance is a useful planning lens: the spec should separate curation command capture from suggestion computation through a clear intermediate event/result structure (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:1648`). That also aligns with DDIA's stream-processing model for lower-delay event-derived outputs after user input (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15759`).

### F3. Post-merge curation refresh updates existing suggestions but does not create missing ones

Merge follow-up refreshes the target cluster through `refresh_for_cluster`, but that method is explicitly scoped to existing pending suggestions for the cluster. If the Tory singleton never had a pending suggestion, this follow-up path will not create one.

Current examples:

- `apps/prototype-description-service/recognition/application/orchestration/curation_job.py:97` - merge cleanup calls `suggestion_refresh.refresh_for_cluster(target_cluster_id)`.
- `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py:377` - `refresh_for_cluster` reloads similarity for pending suggestions targeting a cluster.
- `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py:399` - if there are no pending suggestions, `refresh_for_cluster` returns without scanning for new candidate clusters.
- `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py:527` - the broader newly-labeled-cluster path loads unlabeled clusters for candidate discovery, but this is not the path used by merge cleanup.

**Impact:** User curation can improve the target cluster while still leaving nearby singletons invisible. Similarity percentages also cannot be adjusted for suggestions that were never created.

**Planning literature:** `Release It!` argues for queue-and-retry over immediate retry when remote or slow work cannot complete inside the user path (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4409`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4453`). The spec should therefore distinguish "refresh existing suggestions" from "discover missing candidates" and make both durable follow-up work rather than hidden request-time side effects.

### F4. Async clustering skips some suggestion generation paths

The worker invokes clustering with `commit=False`. Inside `ClusterService.cluster_unclustered_identities`, merge suggestion generation only runs under `commit=True`. The orchestrator can also perform singleton HAC refinement after initial cluster creation, but those refinement-created or refinement-merged clusters are not clearly returned as `created_cluster_ids` for later backfill.

Current examples:

- `apps/prototype-description-service/recognition/worker/handlers/clustering.py:138` - the worker calls `cluster_unclustered_identities(... commit=False)`.
- `apps/prototype-description-service/recognition/application/orchestration/cluster_service.py:205` - merge suggestion generation is guarded by `if commit and tenant_id`.
- `apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py:629` - singleton HAC refinement can run after fallback singleton creation.
- `apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py:680` - the job payload stores `created_cluster_ids` from the earlier create list, not from all later topology changes.
- `apps/prototype-description-service/recognition/application/orchestration/cluster_service.py:188` - backfill after clustering depends on `result.created_cluster_ids`.

**Impact:** A batch job can finish with topology changes but without the suggestion backfill inputs needed to surface candidates created or affected by the run.

**Planning literature:** DDIA separates batch jobs, stream processing, and online request/response systems (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15741`). The planning implication is that a batch clustering job should emit a complete durable result/event set for near-real-time suggestion processing instead of relying on a `commit` flag or request-path cleanup.

### F5. The cluster tab exposes raw cluster rows instead of a person-consolidated view

The local cluster repository lists clusters by tenant and returns each cluster row with optional person label data. It does not collapse by `person_id`, hide merged/deleted sources, or present a person-centric topology after workbench merges.

Current examples:

- `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php:198` - `list_for_tenant` selects raw clusters for a tenant.
- `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php:211` - the query joins person names but still returns cluster rows.
- `apps/prototype-wp-alt-context/src/sovereign/mappers/class-cluster-response-mapper.php:116` - `map_cluster_summary` returns one summary per cluster.
- `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:39` - the clusters tab queries recognition clusters directly with a fixed limit.

**Impact:** After merges or local person binding, the UI can still show multiple cards for the same person, which makes it look as if curation did not work.

**Planning literature:** DDIA's materialized-view framing fits this UI problem: the cluster tab is a derived read model and needs an explicit update/rebuild contract when underlying curation facts change (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4727`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4733`). The spec should name the person-aware cluster list as a projection, not a direct dump of cluster rows.

### F6. Roster entries are not a reviewable person-instance read model

The roster entry endpoint and shared contract expose person metadata and a `cluster_count`, but not the person clusters, identities, images, media IDs, bounding boxes, or instance thumbnails required for review.

Current examples:

- `apps/prototype-wp-alt-context/src/api/class-api.php:329` - `get_roster_entries` returns local persons with `cluster_count`.
- `packages/shared-contracts/schemas/roster-entry.schema.json:7` - the roster entry schema includes only `id`, `name`, `tags`, `cluster_count`, and `updated_at`.
- `apps/prototype-wp-alt-context/js/admin/api/generated/roster-entry.ts:3` - the generated frontend type mirrors the minimal schema.
- `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesTable.tsx:151` - the table renders identity, tags, cluster count, and actions, with no image or instance review surface.

**Impact:** Even when local curation creates a roster person, the entries tab cannot satisfy the expectation that all images and face instances of that person are reviewable there.

**Planning literature:** DDIA notes that derived datasets can provide multiple points of view over the same source data (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15696`). The roster entry should be planned as such a derived person-review projection, with rebuild semantics and freshness/status expectations.

### F7. Cluster cards do not identify the linked face and force inspectable imagery into square thumbnails

Cluster cards show a label and identity count, then render sample face thumbnails. The representative identity mapper omits useful identity and score context, and the thumbnail component/CSS force square/circular presentation that can distort media inspection.

Current examples:

- `apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterGrid.tsx:211` - cluster card header shows label and identity count.
- `apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterGrid.tsx:224` - sample faces render without representative/candidate explanation.
- `apps/prototype-wp-alt-context/src/sovereign/mappers/class-cluster-response-mapper.php:197` - representative identity mapping includes media and bbox fields but not a clear linked identity label or similarity context.
- `apps/prototype-wp-alt-context/js/admin/pages/roster/IdentityThumbnail.tsx:24` - if `thumb_url` exists, the component returns an image directly instead of applying bbox crop logic.
- `apps/prototype-wp-alt-context/js/admin/styles/components/_cluster-grid.scss:87` - cluster face thumbnails use `aspect-ratio: 1 / 1`, `object-fit: cover`, and circular styling.

**Impact:** Users see a count and face samples, but not which face anchors the person identity or why a candidate belongs. Cropped square thumbnails can hide the visual evidence needed to trust clustering.

**Planning literature:** `Refactoring UI` warns that naive label/value display gives all data equal emphasis and weakens hierarchy (`literature/extracted/refactoring/Refactoring-UI.txt:592`), while also emphasizing clear visual hierarchy for what matters most (`literature/extracted/refactoring/Refactoring-UI.txt:465`). The spec should define which visual evidence is primary: representative face, candidate face, linked person, similarity evidence, and review action.

### F8. Similarity values are available but not explained as decision context

The backend suggestion APIs return similarity and identity counts, but the UI surfaces do not consistently explain what the similarity is comparing, which threshold/floor applies, or whether a value was recomputed after user curation.

Current examples:

- `apps/prototype-description-service/recognition/interface_adapters/http/routers/suggestions.py:125` - identity suggestion responses include cluster label, similarity, and identity count.
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/suggestions.py:168` - accepting a suggestion assigns the outlier and resolves alternatives, but the API does not expose a before/after curation score story.
- `apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterGrid.tsx:224` - cluster cards render sample faces without similarity annotations.
- `apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterDrawerPanel.tsx` should be reviewed in the spec phase for exact similarity rendering and copy; the current cluster summary contract does not provide enough score semantics to make the UI self-explanatory.

**Impact:** Similarity percentages can look arbitrary or stale. This is especially confusing when the user expects curation to change the percentage.

**Planning literature:** `Refactoring UI` recommends combining labels and values when that improves clarity (`literature/extracted/refactoring/Refactoring-UI.txt:617`) and treating labels as supporting content where scanability matters (`literature/extracted/refactoring/Refactoring-UI.txt:635`). Similarity should therefore be planned as evidence text, not a naked number.

### F9. Curriculum clustering insight exists in code and literature, but the user sees a generic cluster queue

The Apple recognition literature emphasizes periodic clustering, explicit user input, canonical representatives, incremental curriculum, and hard-example handling. The code has related concepts such as singleton HAC and representative/centroid recomputation, but the local UI does not turn them into clear user-facing queues such as "new singleton proposals", "hard examples", or "needs confirmation after merge".

Current examples:

- `literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt:95` - the paper describes unsupervised face clusters and efficient incremental updates.
- `literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt:212` - periodic clustering plus explicit user input determines the people gallery.
- `literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt:311` - incremental curriculum is described as part of recognition improvement.
- `literature/extracted/recognition/apple/CurricularFace--Adaptive-Curriculum-Learning-Loss-for-Deep-Face-Recognition.txt:136` - adaptive curriculum learning and hard samples are central to the approach.
- `apps/prototype-description-service/recognition/application/orchestration/discovery_pipeline.py:236` - singleton HAC only operates when enough singleton candidates exist.
- `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php:358` - local top-unlabeled selection excludes clusters with fewer than two identities, while singleton counts are tracked separately.
- `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:239` - the clusters tab has generic help copy rather than surfacing clustering curriculum state.

**Impact:** The system may be doing curriculum-like clustering work, but the user cannot see what needs review, what was learned from curation, or why a singleton remains separate.

**Planning literature:** Modern Software Engineering frames complex-system work as iterative, feedback-driven, and empirical (`literature/extracted/refactoring/modern-software-engineering.txt:800`, `literature/extracted/refactoring/modern-software-engineering.txt:809`). The curriculum UI should make the feedback loop visible: user curation, resulting candidates, hard examples, and remaining singleton work.

### F10. Service robustness work exists, but orchestration remains brittle and hard to observe

Recent refactor work added adapter timeouts, circuit breakers, session timeouts, and pool isolation. The remaining brittleness is concentrated in workflow orchestration: background suggestion surfacing has a hard timeout and no durable retry/status, curation replay and projection are separate, and suggestion responsibilities are spread across routers, cluster service, curation jobs, and refresh services.

Current examples:

- `apps/prototype-description-service/recognition/application/integrations/timeouts.py:20` - adapter calls can be wrapped with `asyncio.wait_for`.
- `apps/prototype-description-service/recognition/application/integrations/circuit_breaker.py:54` - circuit breaker config provides bounded failure handling for adapters.
- `apps/prototype-description-service/db/session.py:31` - separate async engines/pools exist, including clustering isolation.
- `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py:46` - sessions set PostgreSQL statement and idle-in-transaction timeouts.
- `apps/prototype-description-service/recognition/application/tasks/clustering.py:73` - suggestion surfacing is bounded by a 30 second timeout and semaphore.
- `apps/prototype-description-service/recognition/application/tasks/clustering.py:186` - timeout/failure is logged, but there is no durable retry or user-visible status.
- `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-drain.php:112` - outbox drain batches and dispatches operations, but does not trigger a durable local suggestion/projection follow-up after acknowledgement.
- `docs/assessments/clustering-pipeline-postgres-refactor-literature-2026-04-26.md:38` - prior refactor assessment already identified timeout, transaction, and circuit-breaker concerns.

**Impact:** Remote VM thrash and unreliable projection are not only adapter problems. They are also orchestration problems: expensive or important follow-ups run as transient background work, and the user cannot tell whether a curation-driven refresh is pending, failed, or complete.

**Planning literature:** `Release It!` supports the existing timeout/circuit-breaker direction and strengthens the next planning requirement: timeout state, circuit-breaker state, and delayed retry status must be observable (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4433`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4560`). `Latency` adds that concurrency, throughput, and latency must be modeled together, and that queues grow without bounds when arrival rate exceeds processing capacity (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:699`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:728`). The spec should therefore include queue depth, tail latency, timeout, retry, and refresh-status metrics, not just "make it async."

## Recommendations

### 1. Define one post-curation suggestion refresh contract

**Traces:** F1, F2, F3, F4, F8  
**Priority:** P0  
**ADR gate:** Yes. This direction may change the `cluster_person_bound` event shape and replay semantics governed by ADR-003.

All curation paths should converge on one durable post-curation workflow. Backend direct label updates, WordPress `cluster_person_bound`, merge cleanup, and batch clustering completion should produce the same domain event shape: person/cluster identity, authoritative label, curation revision, affected clusters, and expected suggestion refresh scope. The workflow should create missing suggestions as well as refresh existing ones.

Planning references: model the event as the boundary between record and projection (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15700`), and use Fowler's parameter-object/record guidance to prevent the event contract from becoming another long argument list (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:2084`).

### 2. Expand roster entries into a person review model

**Traces:** F1, F6, F7  
**Priority:** P0  
**ADR gate:** Yes. This direction may expand the person-as-first-class local entity model governed by ADR-002.

Roster entries should represent the reviewable person surface, not just a row in `wp_acx_persons`. The contract should expose a person's clusters, identities, media, bounding boxes, thumbnails, curation state, and review actions so that each cluster labeling creates an entry where all images and face instances can be inspected.

Planning references: treat this as a materialized read model over authoritative curation and recognition facts (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4727`), and keep query/read concerns separate from mutation actions so the review surface is easy to reason about (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:2053`).

### 3. Make the cluster tab person-aware and topology-aware

**Traces:** F5, F7, F8  
**Priority:** P1

The cluster list should not expose raw backend cluster topology as the primary mental model after curation. It should collapse or group by `person_id`/`roster_id`, clearly identify merged or superseded clusters, and distinguish unresolved clusters from clusters already bound to a roster person.

Planning references: use DDIA's derived-data framing to define cluster cards as a projection with a freshness rule (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15688`), and use `Refactoring UI` hierarchy guidance so person identity and review state outrank backend topology details (`literature/extracted/refactoring/Refactoring-UI.txt:465`).

### 4. Replace transient suggestion background work with durable orchestration

**Traces:** F2, F3, F4, F10  
**Priority:** P1

Suggestion refresh should be a durable job or outbox-linked follow-up with retries, scoped progress, failure status, and observable results. A 30 second in-process background task is acceptable as an optimization, but not as the only path for post-curation suggestion surfacing.

Planning references: `Release It!` recommends delayed queue-and-retry for slow or failed work rather than immediate repeated waiting in the user path (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4415`), while `Latency` requires sizing queue/concurrency/throughput together instead of adding unbounded workers (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:719`).

### 5. Surface similarity as explainable evidence

**Traces:** F3, F7, F8, F9  
**Priority:** P1

Similarity UI should explain the comparison target and source, such as candidate face to representative face, candidate cluster centroid to person centroid, or singleton to confirmed cluster. It should also expose the applied floor/threshold and whether the score was recomputed after user curation.

Planning references: use `Refactoring UI`'s data presentation guidance to combine value and context where possible (`literature/extracted/refactoring/Refactoring-UI.txt:617`) and to de-emphasize supporting labels without losing scanability (`literature/extracted/refactoring/Refactoring-UI.txt:639`).

### 6. Adopt an inspectable face thumbnail policy

**Traces:** F7  
**Priority:** P2

Face thumbnails should preserve useful evidence. The UI should apply bbox-aware crops consistently, avoid arbitrary circular square distortion for review contexts, and reserve decorative thumbnails for places where inspection is not required.

Planning references: `Refactoring UI`'s visual hierarchy guidance should drive the thumbnail rules: the review evidence should be visually primary, while decorative framing should not compete with or obscure it (`literature/extracted/refactoring/Refactoring-UI.txt:465`).

### 7. Continue the description-service refactor around smaller use cases

**Traces:** F10  
**Priority:** P2

The current circuit breaker, timeout, pool, and three-phase scan work should be kept. The next refactor target should be orchestration boundaries: separate curation replay, suggestion refresh, clustering topology mutation, and projection into explicit use cases with smaller inputs/outputs and durable observability.

Planning references: Fowler supports preparatory and comprehension refactoring before feature work where structure makes the change hard (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:1751`, `literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:1761`), but also emphasizes small behavior-preserving steps and self-checking tests (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:518`, `literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:1660`). Modern Software Engineering adds the planning guardrail: optimize for learning, feedback, modularity, cohesion, separation of concerns, abstraction, and loose coupling (`literature/extracted/refactoring/modern-software-engineering.txt:809`, `literature/extracted/refactoring/modern-software-engineering.txt:834`).

## Code-Verified Critique

### What the assessment gets right

The strongest findings are F1 through F6. The code clearly shows that WordPress roster commits and backend curation replay do not share the same suggestion-surfacing trigger used by backend cluster label updates. The roster entry schema is also plainly too small to support review of all images and instances.

### Where the assessment overstates the problem

The assessment should not claim that suggestion surfacing is completely absent. Backend direct cluster label updates can schedule `surface_for_newly_labeled_cluster`, and the suggestion refresh service can create or update suggestions in that path. The narrower and code-supported claim is that surfacing is path-dependent and incomplete for local roster commit, merge cleanup, and some async clustering outcomes.

The assessment also should not claim that the description service lacks refactoring work. Adapter timeouts, circuit breakers, database session timeouts, and pool isolation are present. The remaining concern is orchestration reliability and complexity rather than a total absence of resilience controls.

### Recommendations the assessment is missing

R-MISS-1: The spec should include a concrete reproduction harness for job `4f7236f5-55ed-4b55-8eae-51e5b7d256f4` and singleton `cluster-e22d355c86504443896d9bd73c54b80e`. The repo contains older Flaxen Yarrow references, but this exact job evidence was not available through file search alone; verification likely requires DB/API inspection.

R-MISS-2: The spec should define metrics and status surfaces for curation-driven suggestion refresh: queued, running, completed, no candidates, candidates created, candidates refreshed, timed out, and failed.

R-MISS-3: The spec should decide whether the authoritative person label for backend curation replay comes from the WordPress outbox payload, backend roster lookup, or a shared person snapshot contract. The current `cluster_person_bound` payload is not sufficient by itself.

R-MISS-4: The spec should define explicit stability and throughput measures for the refactor slices. Modern Software Engineering points to stability and throughput as useful delivery-performance measures (`literature/extracted/refactoring/modern-software-engineering.txt:1938`) and names change failure rate, recovery time, lead time, and deployment frequency as the relevant dimensions (`literature/extracted/refactoring/modern-software-engineering.txt:1953`). For this codebase, planning equivalents should include curation refresh failure rate, time to recover a failed refresh, lead time from label to visible suggestion, and projection freshness.

R-MISS-5: The spec should model latency as a distribution rather than a single timeout. `Latency` notes that averages hide variability and tail latency is what users often feel (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:796`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:798`). Acceptance criteria should include p95/p99 refresh latency or explicit async-status behavior for long-running work.

## Priority Ordering

| Priority | Change | Impact | Effort | Trace |
| -------- | ------ | ------ | ------ | ----- |
| **P0** | Post-curation suggestion refresh contract | Restores curation-driven suggestions and similarity refresh | Medium | F1, F2, F3, F4 |
| **P0** | Reviewable roster entry read model | Makes entries tab useful after every cluster labeling | Medium-large | F6 |
| **P1** | Person-aware cluster tab | Reduces duplicate identity confusion after merges | Medium | F5 |
| **P1** | Durable suggestion refresh orchestration | Prevents silent loss from timeout/background-task failures | Medium | F10 |
| **P1** | Explainable similarity UI | Makes candidate suggestions auditable by users | Small-medium | F8 |
| **P2** | Inspectable thumbnail policy | Improves trust in face review evidence | Small | F7 |
| **P2** | Description-service use-case refactor | Reduces complexity and remote VM pressure over time | Large | F10 |

## Deferred or Rejected Directions

- Do not make the first implementation pass a broad rewrite of `apps/prototype-description-service`. The code already has resilience improvements; the urgent failures are workflow contract gaps.
- Do not solve duplicate cluster display only with frontend filtering. The UI needs help, but hiding raw rows without a person/topology contract risks masking backend state bugs.
- Do not treat singleton HAC as a replacement for user-visible suggestion review. The reported expectation is that the suggestion workflow surfaces candidates after curation, not that the backend silently merges every singleton.
- Do not expand roster entries only with more counts. The missing capability is instance review, including images, face crops, clusters, and provenance.
- Do not plan resilience as "increase timeouts" or "add more workers." `Release It!` and `Latency` both point toward bounded waiting, delayed retry, queue/concurrency sizing, and observable state rather than unbounded concurrency (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4453`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:728`).

## Suggested Spec Direction

Write one spec for the recognition roster curation loop at `docs/specs/recognition-roster-curation-loop-spec.md`.

**Epic affiliation:** Primary affiliation is E15 Phase 6, "Local Sync Correctness and Audit Closure", because the defects block the sovereign local-read/curation loop and public demo trust. E14 does not own this work directly; E14 remaining deliverables are folded into E15. If owner review declares the broader description-service refactor outside E15 MVP, split that portion into the v0.4.1 follow-on epic rather than creating a new epic.

The spec should cover:

1. Curation event contract for backend direct edits, WordPress local commits, outbox replay, merge cleanup, and batch job completion. ADR-gate candidate: event shape and replay semantics.
2. Durable suggestion refresh lifecycle and status. ADR-gate candidate: durable queue contract if this changes ADR-003 replay boundaries.
3. Roster entry read model for person, clusters, identities, media, bboxes, thumbnails, and actions.
4. Person-aware cluster tab behavior after merges and bindings.
5. Similarity evidence model and UI terminology, including whether label corrections re-surface suggestions for already user-confirmed clusters.
6. Exact reproduction/acceptance case for job `4f7236f5-55ed-4b55-8eae-51e5b7d256f4` and singleton `cluster-e22d355c86504443896d9bd73c54b80e`.
7. Bounded refactor plan for `apps/prototype-description-service` orchestration, with adapter resilience work treated as existing baseline.
8. Refactoring guardrails from the extracted literature:
   - ADR-gate candidate: record vs derived data boundary when it changes authority or replay contracts.
   - ADR-gate candidate: durable queue contract when it changes outbox/replay semantics.
   - Informational: bounded latency/concurrency and queue sizing for implementation acceptance criteria.
   - Informational: observable circuit/timeouts for operational metrics.
   - Informational: small refactor slices with self-checking tests.
   - Informational: UI hierarchy for review evidence.

## Next Step

- [x] Draft assessment artifact at `docs/assessments/current/recognition-roster-suggestion-workflow-assessment-2026-05-05.md`
- [x] Draft spec for the recognition roster curation loop under E15 Phase 6 at `docs/specs/recognition-roster-curation-loop-spec.md`
- [ ] Author or amend ADR coverage before implementation for ADR-003 event/replay changes and ADR-002 person/roster-entry model changes
- [ ] Split implementation into artifacts/slices after spec review: backend curation event contract, durable suggestion refresh, roster entry read model, cluster UI, thumbnail/similarity UI, and description-service orchestration refactor

## References

- `apps/prototype-description-service/recognition/application/orchestration/cluster_service.py`
- `apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py`
- `apps/prototype-description-service/recognition/application/orchestration/curation_job.py`
- `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py`
- `apps/prototype-description-service/recognition/application/tasks/clustering.py`
- `apps/prototype-description-service/roster/application/curation_sync_service.py`
- `apps/prototype-description-service/roster/interface_adapters/http/curation_router.py`
- `apps/prototype-wp-alt-context/src/api/class-api.php`
- `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php`
- `apps/prototype-wp-alt-context/src/sovereign/mappers/class-cluster-response-mapper.php`
- `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterGrid.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/roster/IdentityThumbnail.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesTable.tsx`
- `packages/shared-contracts/schemas/roster-entry.schema.json`
- `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt`
- `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt`
- `literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt`
- `literature/extracted/refactoring/Refactoring-UI.txt`
- `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt`
- `literature/extracted/refactoring/modern-software-engineering.txt`
