# ADR-019: Person-anchored curation — names, stale references, roster, findings

- **Status:** Accepted 2026-10-18 (recorded operator acceptance of the independently reviewed contract; implementation, producer-verification and real-database gates remain open — see Status)
- **Date:** 2026-10-16
- **Context task:** CURUX-1
- **Amends:** [ADR-003](ADR-003-wordpress-local-authority-and-durable-outbox-replay.md) rules 7 and 8 (stale references only); [WBTRUST-3](../tasks/v0.5.0/WBTRUST-3-naming-ux-and-persistence-task-plan.md) Slice S2 row content; [WBTRUST-2](../tasks/v0.5.0/WBTRUST-2-cluster-curation-surface-task-plan.md) contextual commits, ordinary K>0 producer-readiness hold (rule 6) and the explicit stale-rebind context in rule 2e.
- **Extends:** [ADR-009](ADR-009-recognition-curation-refresh-and-person-review-projection.md) rule 1 (WordPress owns the person binding).
- **Coordinates with:** ADR-018 post-curation identity weaving (Proposed, branch `feature/idweave-1`).
- **Screens and map deltas:** [CURUX-1 screens](../assessments/current/curux-1-identity-curation-screens-2026-10-16.md) (S-A..S-F).
- **Heuristics (canon v0.26.2):** AGT-13, COG-02, HAI-11, EMB-06, CAL-02, CAL-10, HAI-15, HAI-16, HAI-17, NAV-02, FORM-09, FORM-11, INT-08, A11Y-21, DOM-03, DOM-06, DATA-14, RES-19, HAI-02, HAI-06, INT-07, INT-10, INT-13, INT-20, NAV-35, NAV-19, NAV-20, NAV-26, NAV-05, PERC-10, INT-01, INT-06, INT-27, A11Y-04, A11Y-14, RLSE-04, GRPH-01, GRPH-14, GRPH-32, GRPH-39, NAV-13, WRIT-02, WRIT-27.

## Status

Accepted. Operator acceptance was recorded on 2026-10-18 at 00:32:16 (handoff decision 18002, commit `eb06587939b441f91b50c83f82bbca926000ab84`, branch `feature/curux-1`). The operator was asked to accept the concrete reviewed contract. They replied "begin implementation asap, stop nitpicking over planning documents". That reply is recorded as explicit authorization to proceed with the reviewed contract, with no further planning-review loop.

- **Accepted text.** The fourth corrective author revision, exact ADR blob `4e8c768e9bb88826c838f26a10fc1659cbf296ae`, together with the reviewed companion blobs: [CURUX-1 screens](../assessments/current/curux-1-identity-curation-screens-2026-10-16.md) `3aa17ccdc8f46fb6b2c7d9516cd81f3c27e7bf5b`, [WBTRUST-2](../tasks/v0.5.0/WBTRUST-2-cluster-curation-surface-task-plan.md) `71594b52002480c34f013858601cc8aa8c735c01` and [WBTRUST-3](../tasks/v0.5.0/WBTRUST-3-naming-ux-and-persistence-task-plan.md) `31fe8e4b6f4fdcece78c9bfbc05d483c4276ca1a`. That revision addresses CURUX1-ADR3-01: ordinary K>0 exclusions stay in an explained hold pending WBTRUST-2's owned, independently verified valid atomic exclusion producer. It preserves the third revision's eight independently closed residual contracts.
- **Review basis.** Independent A2 review 1512 (source `eb065879`, tree `5bcaed11`; decision 17999) passed those exact blobs, verified all eight previous planning closures and left zero open planning findings.
- **Scope of this status edit.** Only acceptance and status prose changed: this header, this section, and the amendment labels and status paragraph after Decision rule 8. Normative rules, the source-bounded inventory, rationale, guardrails and references are unchanged from the accepted blob.
- **What acceptance covers.** The decision, its rules, and the ADR-003, WBTRUST-2 and WBTRUST-3 amendments below are the recorded planning authority. Implementation lanes may consume them without another planning or approval round. AGT-13 ("No silent ADR override") still applies to any later change of these choices.
- **What acceptance does not cover.** These remain separate implementation gates, not planning debates:
  - Every field, producer, command and result marked *proposed* below stays unimplemented until it is built and independently verified at its real seams. This includes `face_evidence_v1` and the namespace/lifecycle authority, the curation-intent journal and receipts, `review_source_ref`, the correspondence result and the ordinary K>0 exclusion producer. Until then, consumers abstain exactly as rules 2c–2e and 6 state, and automatic correspondence stays unavailable.
  - The required atomic producer, result and consumer tests, identity counterexamples and test matrix (Guardrails) must pass before implementation acceptance.
  - Schema-bearing slices also need real PostgreSQL migration, RLS and trigger qualification, plus independent review, before they land.
  - Step 0 (rule 8) still precedes the first slice.
- **No implementation proof.** This ADR records no implementation, readiness, live-database or served-build evidence.

The historical source review and earlier corrected portions remain in force.

## Date

2026-10-16

## Context

On 2026-10-16 the operator reported six broken surfaces on demo.altcontext.com:

- **(a) Name combobox** (`acx-identity-cluster__label-input`). It stays disabled at "Loading people…", then offers "Person 1".."Person 5". Only curated, human-named people should appear, ordered by how closely they match the face being named.
- **(b) Conflicts.** Four `cluster_not_found` rows appear: Keanu Reeves, Emma Watson, Sophia Loren, Werner Herzog. Each reads "compound topology conflict … Phase 4 … keep-local only" and "No resolution actions are available".
- **(c) Roster.**
  - Row 4 of the People table is empty.
  - People cannot be named from this page.
  - The avatar is too small.
  - Clicking does nothing.
  - The operator proposes that clicking a person lists the images that contain them.
- **(d)** The `acx-roster__review-cta` section ("Open Review Queue") duplicates other entries.
- **(e)** The `acx-findings-panel__actions` buttons are inert.
- **(f)** `#acx-workbench-queue-heading` offers no visible path to curate face groups or name people.

Prior art comes from `find_related_prior_work` (handoff ids). Each item was re-checked against this tree:

- **(a)**
  - UXW2-5 (9291, 9397): one row per person, highest similarity wins. Present.
  - GTMSMOKE-1 (18601): the closest-people read gated the whole form. Absent at this tree; other reads still gate it.
  - UXW2-3 (9333): roster-loading duplicate race.
  - E21-15 (7930, 8391, 8396): machine labels were shown as people. BR-17 filters the cluster leg only. The reserved-label gates reject `cluster-*` shapes only, so `Person N` passes. Regressed.
  - IDREBIND-1 (16118, 16115): self-suggestion. Open.
- **(b)**
  - DEMOLIVE-4 (6351): reset loses outbox rows.
  - TRIAGE0918-M-08 (15196): entity-gone orphan discard.
  - IDREBIND-1 (13534): 43 conflicts dismissed by hand.
  - REL0024-M-07 (15174): deferred.
  - UXP-4 (4551): vocabulary single source of truth.
  - DEMO-UX-1 (10107).
  - E15-37: offline-curation sovereignty.
- **(c)**
  - E21-15 (7864): the thumbnail size path. Not applied to the roster directory.
  - WBUX-5 (6569): face crop.
  - MAINT-ROSTER-UX-ASSESS (11143): name click opens the workspace; the 32 px dense-row trade-off.
  - DEMO-UX-1 (10030).
- **(d)**
  - IDREBIND-1 W3-03 (16117): circular review path.
  - DUXW2-VOCAB.
- **(e)**
  - E15-23 (131, 137): "Review next" only scrolls. Long known.
  - E21-20 (8847): dead REPAIR branch. Already removed; the Resync control is live.
  - MAINT-demow3 C-12.
- **(f)**
  - E21-18 (8624): dangling heading. Fixed by L3R-08.
  - UXW2-4 R4-03: `z-review-name` deleted.
  - WBTRUST-2: "no path to accept, curate, or manage".

### Constraints from prior review

- **WBTRUST plans.** The v0.5.0 plans (base 372a6413) already own parts of this:
  - WBTRUST-3: one option per person; advisory suggestions.
  - WBTRUST-2: one curation panel; S5 retires `ClusterReviewPanel`.
  - WBTRUST-1: queue-card trust; Yes/No under HAI-15.
  - WBTRUST-4: request budgets.
  - WBTRUST-5: control placement, rg-003.

  Preserve their existing corrections. This proposal adds the fourth WBTRUST-2 recovery context, holds ordinary K>0 on its separate owned producer prerequisite, and amends WBTRUST-3 option/provenance and binding semantics explicitly below.
- **ADR-018 (Proposed).**
  - Names are never generation inputs.
  - Every naming-relevant curation event (bind, unbind, label, merge, split, member move) triggers a derived re-weave.
- **Greenfield.**
  - No data migrations.
  - A destructive demo reset requires separate authorization; this document revision authorizes no reset. Legacy names/person UUIDs are preserved by the proposed recovery contract.
- **The served build is unknown.**
  - The only fingerprint is `ACX_VERSION` 0.0.38 (`alt-context.php:7`, `class-admin.php:277-292`), and there is no commit marker.
  - The original inventory was read at d25922fa; this corrective revision is source-bound to commit `2b9d4a0ed3146095b956f7946673fee00ce548b5`, tree `94f760713f266845f4d2b40cc8c22d41907324c8`. Current-state claims are source reads, not observed browser outcomes. Proposed contracts and required future tests are labelled below.

## Current State Inventory

**(a) Naming**

- *Input gating*
  - The input is disabled whenever `isLoading` is true (`NameFaceControl.tsx:268-269`). "Loading people…" is the status text (`:355-357`).
  - `isLoading` ORs four reads (`useClusterSuggestionsLoader.ts:328-335`): the identity-batch read, label matches, at-rest labels and the roster list.
  - The closest-people read waits for the identity batch (`:266-285`).
  - The identity-batch read sets a 2 s abort signal where `AbortSignal.timeout` exists (`identityQueriesApi.ts:105-108`, `requestTimeout.ts:1-7`). The loader passes no `timeoutMs` to its other reads, which fall back to `DEFAULT_FETCH_TIMEOUT_MS = 300_000` (`http.ts:46, 232`).
- *Option sources*
  - `buildNamingOptions.ts:194-209` adds every roster entry with a non-empty name and checks nothing about provenance.
  - Only the cluster leg is filtered (`:228-231`). It uses `isHumanLabeledTarget`, which rejects `cluster-*` and hex shapes only (`suggestionProjection.ts:34-35, 99-105`), so "Person 3" passes.
  - `is_auto_label` exists on the identity types (`utils.ts:155-162`), but naming ignores it.
  - The local-projection cluster leg requires only a non-empty label (`class-clusters-read-repository.php:85-90`).
  - No person-level provenance field exists (`roster-entry.ts:40-52`).
- *Ranking*
  - Python ranks labelled clusters, not people (`roster_candidates.py:139-151, 226-251`).
  - Candidates are selected by `user_confirmed ∧ label ∧ ¬cluster-*` (`cluster_repository.py:550-566`).
  - PHP asks for a top-50 window, collapses it to one row per person, and slices to 5 (`class-suggestions-controller.php:412-440, 488-563`).
  - The service also sets `user_confirmed` on split output (`split/executor.py:58-71, 237-242`).
  - The WordPress snapshot mirrors that flag as `curation_state='confirmed'` (`clusters_snapshot.py:199, 219-229`).
  - WordPress UI label writes mark the label confirmed (`interface-clusters-repository.php:103-105`); backend-applied labels do not (`class-conflict-resolution-service.php:675`).
- *Self-suggestion.* Only the probe group is excluded (`roster_candidates.py:201-202`, `buildNamingOptions.ts:217-219`). The person already bound to it is not.
- *"Person N".* Written by the production auto-labeler: `allocate_person_label` (`auto_labeler.py:15-52`) and `assignment_writer.py:771-791` set `cluster.label`. Auto-labelling is on by default with prefix `Person` (`settings/clustering.py:198-214`). The snapshot label backfill binds a person from any label that is not `cluster-*`, so `Person N` binds (`class-cluster-snapshot-merger.php:210-266`). The person resolver can reuse an unlinked same-name person (`class-person-resolution-service.php:173-176`). A test fixture also produces it (`test_api_suggestions.py:1014`).

**(b) `cluster_not_found`**

- *Service side*
  - The service returns the conflict when an outbox operation targets a group it no longer has (`curation_sync_service.py:125-134`).
  - Results are replayed by `(tenant, idempotency_key)` before any lookup (`:110-112`; `identity.py:321`).
  - The persisted curation replay record has no request fingerprint (`identity.py::CurationReplayRecord:290-321`; `curation_sync_service.py::_load_replay_result:244-268`). The HTTP route already fingerprints each full operation for usage admission, rejects differing same-key operations within a batch, and holds reservations around application (`curation_router.py::sync_curation_operation:88-137`). These are separate layers; preserve the route's tenant context, reservations and ticket commits (`:163-164`).
- *Group UUID removal and membership changes*
  - Operator merge moves source members into a surviving target. With a valid `moved_by_merge_id` and session, it records `source_cluster_id`, `survivor_cluster_id` and `moved_identity_ids` (`cluster_merge.py::merge_cluster:381-481`); source deletion follows recomputation, or deferred cleanup (`:495-502,555-569`; `curation_job.py::run_curation_job:273-288`). Recovery merge also creates this lineage (`clustering/recovery_merge.py::_new_receipt:464-485`).
  - Discovery singleton merge moves members and deletes the source without creating a merge receipt in that path (`clustering/discovery_pipeline.py::_run_singleton_hac_refinement_body:778-796`).
  - Soft disposal sets `disposed_at`; it does not delete group or face UUIDs (`retention_policy_service.py::apply_disposal_after_ack:129-136`). Snapshot export excludes disposed groups (`cluster_repository.py::get_snapshot:1658-1662`), while curation lookup does not filter disposal (`curation_sync_service.py::_load_cluster:380-385`). Snapshot absence therefore does not itself prove deletion or `cluster_not_found`.
  - Purge deletes scoped group and face rows (`purge_service.py::_delete_dependency_rows:282-291`, `_cluster_delete_predicate:460-465`, `_identity_delete_predicate:467-472`).
  - Split retains the original UUID and moves other partitions to new groups (`split/executor.py::split_cluster:288-348`). The retained partition starts as the largest; when a normalized anchor and a valid label owner exist, the owner partition is placed first even if smaller (`:189-198,229-260`). Label ownership prefers the anchor, then representative, then centroid similarity, with a largest-partition fallback (`split/anchor.py::determine_label_owner:61-118`). Without the anchor override, label ownership and original-UUID retention can differ; neither is person-identity proof.
  - Split emits `original_cluster_id`, `new_cluster_ids` and `moved_counts` (`split/executor.py::_emit_split_events:114-140`). The topology-command route additionally persists `member_delta.source_cluster_id`, `remaining_identity_ids`, `created_clusters[].{cluster_id,identity_ids}` and `result_snapshot_version` (`clusters_topology.py::split_topology_command:499-536`). WordPress stores the dispatch result before reconciling it and checks member-set completeness (`class-split-topology-command-drain.php::process_pending_split_command:266-278`, `has_complete_member_delta:687-736`). The older split endpoint returns new IDs/counts or an async job, not that complete delta (`clusters_topology.py::split_cluster:380-447`).
- *Snapshot contents*
  - Cluster snapshots carry neither `roster_id` nor a general successor map, but do include `undoable_merge_receipt_id` (`responses.py::ClusterSnapshotClusterResponse:670-691`; `clusters_snapshot.py::_build_cluster_responses:216-230`). That receipt handle is not the full lineage payload. Snapshot omissions do not imply that service replay or topology commands lack binding or correspondence inputs.
  - Its members carry `identity_uuid`, `cluster_uuid`, `attachment_id` and `bbox` (`responses.py:643-656`).
- *WordPress recording*
  - WordPress records the 409 as an outbox `CONFLICT` plus a conflict row in one transaction (`class-outbox-dispatcher.php:273-274`; `class-outbox-drain.php:564-570, 665`).
- *Snapshot merge*
  - It keeps curated groups that are absent from the snapshot untouched, with no successor mapping (`class-cluster-snapshot-merger.php:96, 379-392, 422`).
  - It deletes uncurated absent groups and their `cluster_not_found` rows (`:491`).
  - The general snapshot member merger stores `identity_uuid`, `attachment_id` and `bbox_json`; conflicting curated membership is recorded and preserved (`class-identity-member-snapshot-merger.php::merge_snapshot_for_tenant:108-153`). This path has no rule-2 anchor resolver. Separately, the split-command drain already consumes the command's identity-level member delta; that existing correspondence must be preserved, not described as absent.
- *Copy*
  - `getUnsupportedExplanation` first returns no explanation when `allowed_resolutions` includes `accepted` or `accept_backend`. Otherwise it chooses person-side versus compound-topology copy by `entity_type`, not by conflict code (`conflictInboxUtils.ts::getUnsupportedExplanation:71-87`). Thus the compound copy is a guarded fallback, not copy for every cluster row.
  - An empty `allowed_resolutions` (`class-conflict-controller.php:400-444`) renders "No resolution actions are available" (`ConflictDetailPanel.tsx:79, 130, 149`).
- *Keep local loops*
  - Keep local requeues the same outbox row with a current base and reset retry metadata (`class-conflict-resolution-service.php::resolve:220-225` → `class-outbox-maintenance-service.php::re_enqueue_with_current_base:1918-1935`).
  - For `cluster_person_bound`, it resolves the current same-tenant canonical `person_name`, refuses a missing/blank/foreign-tenant person, and rotates `idempotency_key` when the name or base version changes (`:1936-1966`, `canonical_person_name:1993-2009`). Payload metadata is reset too; key and payload are not universally unchanged.
  - An unchanged key with a cached `cluster_not_found` returns that result before lookup (`curation_sync_service.py::_apply:108-133`). A fresh key bypasses that cache, but still returns a new `cluster_not_found` if the addressed group is absent. Key rotation does not choose a successor.
  - A repeated conflict can reopen the existing row through `ON DUPLICATE KEY UPDATE` (`class-conflict-repository.php::record_conflict:132-146`). These source paths describe a possible loop; no runtime loop was reproduced here.
- *Orphan discard* applies only to `FAILED` rows (`class-outbox-maintenance-service.php:1087-1103, 1565-1579`), never to `CONFLICT` rows.

**(c) Roster**

- *Row opening*
  - A row opens only when it has a person UUID (`RosterEntriesTable.tsx:159`); otherwise it renders a static span (`:304-308`).
  - The projection emits `''` for a missing UUID (`class-roster-entry-projection-repository.php:92-96`).
- *Avatar*
  - `DIRECTORY_THUMB_SIZE = 32` (`RosterEntriesTable.tsx:31`).
  - The avatar has no handler of its own (`:96-106`); it sits inside the name button (`:294-303`).
  - Edit and Delete are icon-only with a title only (`:338-345, 351-359`).
- *Workspace gate.* The workspace renders only for a `current` projection (`RosterPage.tsx:60-65`). Otherwise a gate notice replaces it (`:81-108`).
- *Photos*
  - Photos already ship, 50 per page (`PersonWorkspacePanel.tsx:49, 843-868`).
  - Captions read "Media %d" (`:817-823`).
  - Besides the lightbox (`:257-261`), each photo has a "Use as cover" button (`:825-834`).
  - `mediaEditUrl` exists (`adminUrls.ts:20-24`) but is unused here.
  - The header shows debug metadata (`:566-586`).

**(d) Review CTA**

- The CTA lives at `RosterPage.tsx:210-238`.
- It repeats the hero subtitle (`:195-199`) and the admin menu entry "Review Queue" (`class-menu.php:18`).

**(e) Findings**

- The actions live at `WorkbenchFindingsPanel.tsx:525-549`.
- "Review next" (`:369-378`) and "View all findings" both call `onTargetFindings`.
- `onTargetFindings` scrolls to an anchor inside the queue section and focuses the current card (`ScanTabContent.tsx:172-184`; `ReviewQueue.tsx:665-711`).
- The hints promise "Name the largest unlabeled group" (`:71-83`), but no branch opens a panel.

**(f) Queue**

- A naming path exists but is hidden:
  - "Open labeling form" appears only when a card has no suggested label (`TopClusterCard.tsx:205-215`).
  - `PersonCommitControl` appears only on name, cluster and assignment rows (`ReviewQueue.tsx:2173-2192`; `personCommitVisibility.ts:26-29`).
- "Review" opens `ClusterReviewPanel`, which has no name control (`ClusterReviewPanel.tsx:122-130, 169-170`).
- The heading region does not dangle (`ScanTabContent.tsx:233-238`).

### Downstream surfaces that must migrate together

- **UX maps:** `roster-people`, `workbench-2pane`, `workbench-operator-loop`. The screens doc lists the deltas. Each task's slice 1 applies them, then runs `make lint-ux-maps`.
- **Proposed WordPress schema:** provenance, anchors and one curation-intent journal with draft/command/delivery records (rules 1 and 2). Exact storage/transport schemas are future work under the greenfield policy; these names do not describe current wire fields.
- **Generated `RosterEntry` type:** gains `name_source`.
- **Conflict vocabulary:** the UXP-4 single source of truth. `stale_reference` copy is keyed by code.
- **Plans:** WBTRUST-3 S2 text (rule 1d) and WBTRUST-2 S5 card label (rule 6).

## Decision

### Chosen design rules

1. **Naming options are human-named people, ranked by face similarity.** This rule amends WBTRUST-3 S2.
   - **a. Grain.** One option per person (an `acx_persons` row). Sources:
     - persons with `name_source = human`;
     - human-written group labels (`label_source = human`) that match no person by WBTRUST-3's name key. These render as explicit creation/review evidence; selecting and saving requires a new operator command with current source consent and does not resurrect a same-name unlinked binding. Distinct same-name people remain distinct UUID options.

     A machine-written label is never an option, whatever its shape.
   - **b. Provenance.** `acx_persons.name_source` and the projected group's `label_source` take values from a backed enum (`human`, `machine`).
     - An authenticated operator name write records `human`. Import, replay and derived label updates preserve that recorded origin; they do not promote a label to `human`. Missing or unverified origin is ineligible, not an implicit enum default.
     - `name_source` and `label_source` are proposed provenance fields, not fields exported by the current snapshot. WordPress owns human-name provenance; the service owns machine-label provenance. Imported copies point to their originating write. A label echoed by replay is not a new human decision.
     - Retire snapshot name-based person creation and binding, including `backfill_persons_for_human_labels` calling `resolve_for_automatic_bind`. Even a proven human label or exact same name cannot select a person, activate an anchor, clear an unlink suppression or bind a group. Preserve the label and its origin as evidence. Only an explicit operator command or the guarded rule 2d continuation of current WordPress binding intent may change the binding. Legacy labels without binding proof remain unlinked and available for explicit review; names and person rows are not deleted.
     - Every person-name write path, including roster create and rename and `handlePersonSelect`/`applyPersonLabel`, goes through one shared reserved-label gate (FORM-11). Each path has a gate today, but the predicate rejects `cluster-*` shapes only. The shared gate must also reject auto-label shapes. This closes the E21-15 bypasses.
   - **c. Ranking.**
     - Similarity is pairwise probe–gallery similarity at person grain (EMB-06).
     - The Python candidate set is the groups bound to a WordPress person (`roster_id` set by `cluster_person_bound`), grouped by `roster_id` and scored by maximum similarity. `user_confirmed` no longer selects candidates.
     - PHP maps `roster_id` to `acx_persons` and drops any person that fails 1a.
     - A person below `suggestion_floor` is not ranked (CAL-02).
   - **d. Display.**
     - At most 5 ranked rows, then the A–Z remainder filtered by the typed text.
     - The ranked block does not re-sort while the list is open (NAV-02).
     - Each ranked row shows up to 3 proved current faces closest to the probe group and the confirmed face count under 2b–2c/2e (HAI-17). Unverified associations show Faces need review; neither avatars nor counts imply proof from a bare anchor.
     - No score or band word appears beside a name.
     - The person already bound to the probe group is not offered (IDREBIND-1).
   - **e. Loading.**
     - The input is enabled from first render, and `isInputDisabled` keeps only `disabled` and save-pending.
     - Pending reads drive a polite status line, "Finding closest people…" (INT-08, A11Y-21).
     - "Add as a new person" stays disabled until the roster list loads successfully, and the status line gives the reason (FORM-09; UXW2-3 race).
     - The optional reads start in parallel, each with an explicit WBTRUST-4 budget rather than the 300 s default.
     - A failed closest-people read or timeout shows "Closest people unavailable" with Retry. The A–Z list still shows.
     - A failed roster read shows "Couldn't load people" with Retry, and Retry refetches the roster list. Typing a name always works (CAL-02, HAI-11).
   - **f. Empty roster.** "No named people yet — type a name" (RLSE-04).

2. **A missing or changed face group is a stale reference, re-linked by face identity, not a curation conflict.** This rule amends ADR-003 rules 7 and 8; the amendment text follows the rules.
   - **a. Classification.** These cases are classified as `stale_reference`, separate from `version_conflict` (a true concurrent edit):
     - a service `cluster_not_found`;
     - a snapshot that drops a person-bound group;
     - a snapshot or merge that adds or removes members of a person-bound group, including the retained original of a split and a merge into a bound survivor;
     - changed, missing or namespace-incompatible face evidence under 2c, even when the group UUID, member UUIDs, attachment IDs and boxes are unchanged. A failed or incomplete evidence read is unknown, not proof that the faces disappeared.

     Each is still stored as a record, so rule 7 holds.
   - **b. Anchors.**
     - Face membership has two local writers: snapshot import and operator curation. The resolver retains the incoming snapshot member set separately from the protected curation overlay. The overlay cannot prove where the service currently placed a face.
     - In the same transaction as a bind or any member-changing curation write, retain the before/after evidence `(person_uuid, identity_uuid, attachment_id, bbox, from_cluster_uuid, snapshot_version)` and the responsible intent. Snapshot replacement preserves the previous evidence before changing or removing it. Capture is not permission to activate new matches.
     - **Proposed WordPress authority:** one curation-intent journal owns `binding_intent_id` (non-reused UUID), `binding_intent_revision` (monotonic), `auto_rebind_suppressed` and each anchor's `authority_state` (`active` or `historical`). These are proposed storage fields, not current APIs. All binding/member writers, including snapshot reconciliation, use this journal's transaction and concurrency fence; no other component independently activates claims.
     - Active evidence is a current claim authorized by an explicit operator bind or reviewed membership choice. Automatic matching additionally requires current unsuppressed intent and `correspondence_status = exact` under 2c. Use only that result vocabulary throughout this contract. Historical evidence supports audit, separately labelled historical previews and attachment lookup; it cannot authorize matching. Neither state alone certifies today's face pixels.
     - A person's confirmed current faces, avatars, counts and photos require a valid current binding, an active claim, and either proved unchanged source correspondence under 2c or a fresh reviewed source selection under 2e. Suppression may coexist with unrelated still-valid bindings. Unverified current associations show "Faces need review" separately from historical evidence; no unverified live crop is rendered as a confirmed face.
     - Exclude or reassign retires the affected source person's claim to historical. A move into a person-bound group activates a destination claim only when that operator command explicitly confirms that person membership; otherwise it remains review evidence. Source and destination claim changes are atomic. For the correspondence established by rule 2c, at most one person's active claim is allowed; a competing claim blocks automation rather than picking by name or UUID alone.
     - Unlink and Keep name, unlinked retire claims for the removed association and set `auto_rebind_suppressed` for that person. Undo of a re-link also sets it. Existing unrelated valid bindings remain intact. Import, re-scan, rename, reload, option toggles and retry cannot clear suppression. Only a new explicit Bind/Re-apply intent can clear it at its successful guarded final commit, and only the faces explicitly reviewed in that command become active; draft saves, exclusions and failed commits do not clear it. Previously retired claims stay historical.
     - A machine membership change preserves the last authorized claims for reconciliation; it cannot expand them to new faces. An absent or stale old group is a retained reference, not a current face list. Every bind and membership writer captures evidence; activation still requires the authority and source predicates above.
     - New anchors store proposed `face_evidence_v1` when available. Legacy names/person UUIDs and historical associations remain intact, but absent proof stays absent: hashing today's attachment cannot certify the source shown during an earlier naming decision. No snapshot label, protected overlay or later proof producer bootstraps historical anchors into active matching authority. Fresh review creates new intent for the exact current source shown, without certifying the old observation. A group without eligible proved anchors is never pure.
   - **c. Successor resolution** proves an unchanged source observation, never embedding similarity.
     - **Current fields are insufficient.** Scan reconciliation can retain `identity_uuid` while rewriting detection data. Snapshot members carry attachment, box, dimensions and thumbnail data, but no immutable media revision. `image_phash` is a mutable perceptual hash in the service, not an exported immutable source proof. Equal UUID, attachment and box therefore do not authorize automatic re-link.
     - **Proposed evidence contract, not current API fields.** The description-service recognition evidence registry is the sole proposed authority for `face_evidence_v1`: `{identity_namespace_id, observation_id, source_sha256, raster_sha256, decode_recipe_id, raster_width, raster_height, region}`. Detection adapters must measure the exact fetched byte buffer and decoded full-image raster used for that detection, not refetch a URL for hashing. `source_sha256` hashes those bytes. `raster_sha256` hashes a versioned serialization of dimensions, channel layout, dtype and row-major pixels; `decode_recipe_id` pins decoding and orientation. `region` is a positive, in-bounds, half-open integer `(x,y,width,height)` in that raster. These are proposed fields even where a similar diagnostic digest exists today (GRPH-14 — Record provenance as a walkable lineage graph; canon v0.26.2, `lexicons/graph-theory.md#grph-14`).
     - **Producer invariant.** The proposed registry immutably binds `(tenant_id, identity_namespace_id, observation_id)` to `attachment_id` and the complete source/raster/region evidence. Scan persistence records that binding; snapshot member production exports it; WordPress stores the received proof with the anchor. Retain immutable input/raster evidence or digest-verified references for previews. Named face rendering must use those verified pixels; an unverified live attachment crop cannot replace them. A claim about current attachment contents additionally requires validation that its current source revision matches the proof; otherwise retain only historical evidence and request review, including when replacement happened without a new scan. An observation is never retargeted to changed evidence, even when the mutable identity row is recycled. Reuse on an unchanged re-scan requires exact evidence equality and one unique observation in both directions; duplicate detections or multiple possible correspondences abstain. Two faces in one attachment need separate observations and regions. A changed box is review-only even on unchanged media.
     - **Exact predicate.** A current face matches one eligible WordPress anchor only when tenant, namespace, observation, attachment and every evidence component are equal and validated, and the incoming-face-to-anchor mapping is one-to-one and both proofs remain lifecycle-eligible. Missing fields, conflicting proofs, duplicated observations or competing person claims cannot satisfy it. A URL, crop, representative, timestamp, UUID, perceptual hash or export stamp cannot substitute for proof. This establishes the same previously reviewed source region, not a model claim about who appears in it.
     - **Proposed namespace and lifecycle rule.** The same service evidence authority owns tenant-scoped `identity_namespace_id`, proposed on full/delta export envelopes, and the retirement state of observations. Reset, restore, clone and tenant-wide purge make all earlier proofs automatically ineligible; selective purge permanently retires its affected observations. They cannot regain eligibility by restoring UUIDs, pixels or a serialized namespace token. Before exporting eligible evidence after such an operation, issue a fresh namespace and require fresh explicit review for old associations. The producer/storage procedure must independently attest this discontinuity and retirement rule; if restoration can roll that attestation back or its validity is unknown, automation stays unavailable for the affected scope. A bounded ineligibility/review barrier satisfies this requirement; this ADR does not require a global external registry. Export restamping, rename, ordinary re-clustering, process restart and presentation URL changes do not rotate identity. `snapshot_generation_id` is an export/disposal-ack stamp, and `snapshot_version` is a version; neither proves a lifecycle boundary. A WordPress projection rebuild cannot recreate lost anchor proof or clear negative intent. The curation journal is durable authority outside disposable projection rows; if a WordPress restore/reset cannot establish current journal/suppression ancestry, mark affected associations ineligible and require new explicit review rather than restoring automatic authority from an old backup.
     - **Proposed consumer result.** The WordPress correspondence resolver returns `correspondence_status` (`exact`, `no_match`, `changed_source`, `namespace_mismatch`, `ambiguous`, `insufficient_evidence`, `unavailable`) and `matched_faces` pairing incoming face IDs with anchor/proof references, bound to the imported `snapshot_version` and namespace. These result fields and values are proposed. Only `exact` may feed automatic 2d; `no_match` requires a complete successful membership/proof read in its declared scope. Missing exports, disposal filtering or a failed page do not establish deletion or zero matches. All other results retain the name and go to review. Validation occurs during export/import and uses local projected evidence for the UI; admin rendering does not add a live backend dependency (ADR-003 rule 1).
     - Until the proposed producer/export/storage contract is implemented and independently verified, automatic correspondence is unavailable, including equal-UUID matches and the default-on setting. Attachment plus bbox IoU ≥ 0.7 is only a candidate-generation proposal, not a verified threshold or an automatic identity test. Missing historical proof stays missing after the producer becomes available. Review must show current faces and require fresh explicit selection bound to the exact source shown. If trustworthy visual context cannot be loaded or that source cannot be pinned to the resulting intent, retain the draft and offer Retry or "Keep name, unlinked". Manual review consumes this result without upgrading it: fresh source consent under 2e and guarded commit under 2d are separate from automatic correspondence.
   - **d. Automatic re-link applies only to a pure successor.**
     - *Pure* means:
       - there is exactly one non-empty successor group, evaluated from complete incoming membership and the 2c evidence result;
       - a moved-to group is unbound and has no human label; a retained original may retain only this person's existing binding and incident-owned human label, with their revisions checked;
       - every incoming face maps one-to-one to an eligible active anchor of this person with `correspondence_status = exact` under 2c;
       - no incoming face has another person's active claim, binding or unresolved competing human label;
       - current binding intent is unsuppressed, and all affected-input guards below pass. Multiple successors always require review.
     - **Proposed guarded rebind command.** Automatic resolution and explicit Re-apply share one WordPress command; the normal bind command's merge-on-bind does not run. A manual successor set remains separate groups. A retained source UUID is an in-place case, not a second clear/bind target; eligibility still requires the proposed rule 2c/2d predicate or explicit reviewed source/membership under 2e.
     - Under the same curation-intent journal, the proposed `rebind_receipt` has an immutable command/preimage/plan and append-only delivery results. It records `command_id`, caller `request_id`, `binding_intent_id`/`binding_intent_revision`, before/after bindings and anchor states, frozen input/proof references, affected-row guards, ordered outbox step keys and delivery outcomes. All these receipt fields are proposed. Duplicate submission of the same request with the same inputs returns that receipt; changed inputs are rejected. Repeated automatic evaluation of the same intent and frozen successor set reuses its receipt.
     - Compute against a frozen, complete incoming membership view. Before committing, lock affected people in stable order, then affected groups and the intent/anchor/member state; snapshot and member writers participate in the same fence. Re-read and compare the person's tenant, UUID, `local_revision` and current name; binding-intent id/revision/suppression; the source and every successor's current binding, label/provenance, `local_revision` and `snapshot_version`; affected members' `projection_version`, full membership sets, active claims and proof inputs; and the resolution record and predecessor outbox states. Freeze and compare the incoming membership independently of the protected overlay. A newly competing binding or member, absent input, changed version or newer operator choice rejects the whole command and refreshes review. Checking only the old group's `local_revision` is insufficient.
     - `snapshot_version` and optional `snapshot_generation_id` are current envelope fields, not a durable reset epoch or correspondence proof. A proposed frozen-input receipt/digest must bind their values, completeness, exact incoming members and accepted correspondence proof. A partial import cannot establish absence or purity. The identity-evidence contract must provide testable replay-time guards for these same inputs; until supported, automatic commit abstains. No consumer treats the proposed receipt as currently exported data.
     - On successful validation, one local transaction retires only the covered old associations, writes the intended successor bindings and active claims, increments affected local and journal revisions, stores the receipt/audit and undo preimage, inserts immutable outbox steps, and closes the stale record as `auto_resolved` (automatic path) or an explicit reviewed outcome (manual path). Preserve other groups and the person's name/provenance. A failed write, enqueue, audit or commit rolls back every local part. No service request is made inside this transaction.
     - Outbox steps use current `cluster_person_unbound` and `cluster_person_bound` operations with their existing payloads (`cluster_uuid`, and for bind `person_uuid`/`person_name`), plus explicitly proposed receipt/guard metadata. Retire a source that still exists remotely before binding successors; a source independently proved deleted (for example by a settled `cluster_not_found` receipt) needs no request to a vanished UUID. Snapshot absence alone cannot establish that proof; disposal-filtered/unknown source state pauses delivery for review. For an in-place group, emit only the necessary guarded transition. Read the canonical name under the person lock. Each step keeps `expected_base_version` and `local_revision` and gets a distinct key derived from tenant, intent, command, step and operation identity; never the former person/source/successor/snapshot-only key.
     - Replace blanket supersession with a compare-and-set transition of explicitly listed older outbox rows owned by this receipt. Only a never-dispatched `pending` row with no claim or prior delivery uncertainty may become the proposed terminal `superseded` state, atomically with the binding/enqueue/record change. A proposed durable per-step `send_started` marker is owned by the WordPress outbox: the worker sets it before network I/O using the current claim token and state; a reclaimed old claim cannot set it or send. Cancellation compares that marker and claim fence under the same lock. Zero attempts alone is not proof of non-delivery. A concurrent claim aborts that cancellation. Acknowledged, in-flight, previously attempted or unrelated/newer rows are not cancelled; preserve their receipts and settle their effect with their original immutable key before ordered dependent delivery. A stale completion may finish its own outbox row but cannot restore an obsolete binding or close a newer review record.
     - The operator sees "Re-linked "{name}" to N faces after re-analysis · Undo" (INT-10).
     - **Proposed delivery contract.** The local receipt and service delivery are separate durable states. Per affected person/group, an outbox step is claimable only after its effect predecessors are acknowledged or proved not applied. On first application, each service step must atomically validate the captured current binding, membership/correspondence and relevant backend-version guards and store its replay result with the mutation; missing guards or drift produces review, not an automatic rebase. Exact immutable retries return that step's stored outcome without reapplying it or treating its ACK as a newer intent's result. Current `apply_batch` and its label-to-bind continuation are not a general inverse/multi-group transaction. Preserve the narrow existing continuation and all expected-base checks. Independent groups without shared effects need no delivery edge.
     - **Version materialization (proposed journal/outbox extension).** The atomic local enqueue stores an immutable effect plan and preallocated step key. For a root step, capture its known backend base; for a dependent step, proposed `base_version_ref` names the specific predecessor receipt/result whose version it must consume. After all predecessors settle, a fenced preparation transaction validates the planned after-membership/binding/proof guards and seals the complete outbound payload with that proven `expected_base_version`. Persist the sealed fingerprint before `send_started` and any network I/O. This is one-time materialization of an unsent plan, not rebase of an attempted request; missing/conflicting predecessor results hold delivery for review. Once sealed, its key, base, name and payload never change. A changed command needs a fresh step/key, preserving current maintenance fresh-key behavior. Current outbox schemas do not yet supply this dependency/preparation contract.
     - If transport fails or an ACK is lost, retain the local binding and receipt as delivery-pending and retry the exact immutable step/key. Settle that step before sending a dependent inverse or redo. A conflict or permanent failure stops dependent steps; retain acknowledged steps and remaining work durably and expose Retry/Review after reload. Do not roll back authoritative local intent merely because the service is unavailable, report full delivery after partial success, or overwrite later operator work during recovery. Before dispatching a not-yet-sent step, revalidate its current intent and guards; an obsolete intent follows cancellation/ordered compensation, not blind delivery.
     - **Undo is a new inverse intent.** Under the same locks, compare the receipt's after-state with the current person revision, intent, bindings, anchors, member sets and relevant snapshot/proof versions. If newer rename, bind, unlink, reassign, exclusion, merge or relevant membership work intervened, refuse the stale Undo without overwriting it; retain a review path. Otherwise one local transaction restores the receipt's prior associations and record state, restores only still-valid active claims, increments revisions, sets `auto_rebind_suppressed`, consumes the Undo once, and writes its audit and ordered inverse plan. A missing/changed old group remains a stale reference with no current faces, never a resurrected group or an automatic proof.
     - Cancel original steps only where never-dispatched cancellation is proved. Derive inverse effects from each group's receipt before/after map: unbind a delivered new association only if that group was previously unbound; retain an in-place binding that already belonged to this person, without an unbind/rebind round trip. Restore a delivered source-unbind or incident-owned label change only if its preimage still exists and passes current guards. Prior individual exclusions remain saved; Undo of the final map does not reverse them. Use each predecessor's proven resulting backend version for its inverse, retaining normal CAS rejection on intervening changes. A possibly delivered predecessor is settled with its original key first. Undo is locally saved while an inverse is pending; service failure keeps an actionable inverse receipt. It does not silently become a completed remote undo.
     - The same pure snapshot cannot auto-bind again after Undo or Keep name, unlinked: suppression survives imports, retries and reload. **Redo requires a new explicit Bind/Re-apply intent**, freshly validates the selected faces, and obtains new intent/command identities and new outbox keys after the inverse is settled. Retrying that redo reuses its own key. An old bind ACK can acknowledge only its old step, never this redo; name equality and an identical snapshot do not collapse the two intents.
     - Rename remains a separate ordered `cluster_label_updated` event for every then-bound group, using the current WordPress name. A rename before rebind commit invalidates the captured person revision; a rename after commit sees the locally bound successors and follows their bind effects. A new Bind/Re-apply after unlink likewise follows all unsettled predecessor effects. No queued retry rewrites an already transmitted name/payload under its original key, and no old bind, inverse or maintenance retry may supersede a newer operator intent.
     - Proposed option `acx_auto_relink_names` (default on) expresses preference only; it never overrides missing producer proof, suppression or a failed guard. Off routes every case to Needs attention. Manual Re-apply always requires the explicit fourth context and reviewed-source guards (INT-20).
     - This is INT-13's one safe choice: it asserts nothing the operator had not already seen under this person.
   - **e. Every other case goes to Needs attention** (`workbench-conflicts`). Each item states the cause in plain words and shows the successor faces as evidence:
     - *Several successor groups, every face an anchor:* `act-rebind-person-faces` opens the fourth WBTRUST-2 context with a preview of the complete intended group set. A surviving original is included explicitly when it retains reviewed faces; successors are not merged together.
     - *Extra, geometric-only or unproved faces:* `act-review-rebind-faces` opens that same context. Missing historic proof, changed source, namespace mismatch and ambiguity never offer identity-based Re-apply or "Found" claims. Review every kept face and choose individual exclusions; no preview bypasses them or the final checks.
     - **Fresh reviewed source (proposed local producer).** WordPress captures `review_source_ref` for the exact current attachment revision/bytes, decoded pixels and region actually displayed, binds it to the selected incoming member/group and the acknowledged draft, and retains a digest-verified preview. This is a proposed local review record, not a current snapshot field or historical proof. Immediately before each mutation the command revalidates that current source, member mapping and versions still equal what was shown. Changed/unpinnable source, unavailable preview or incomplete membership retains the name/draft with Retry. A successful fresh selection authorizes only those displayed faces under a NEW explicit intent, even if historical `correspondence_status` remains `insufficient_evidence`. Manual review need not wait for the automatic proof producer, but its own source/command producer must be verified; no missing guard is waived.
     - *Another person's binding, human label or anchors:* no whole-group Re-apply. Review may propose exclusions, but another person's binding or unresolved competing evidence cannot be overwritten. Keep the name unlinked or resolve that separate conflict, then refresh and review the intended map again.
     - **Fourth-context contract:** the proposed WordPress recovery journal, version inputs, retained-original/multiple-successor commit map, ordered exclusions, atomic final rebind and interruption/reload behavior are specified in the WBTRUST-2 amendment. That contract applies to both manual actions above, including K=0. Ordinary named-group review stays close-only. Until its local command and exclusion-capable panel exist, show the unmet prerequisite, retain the recovery record and offer Keep name, unlinked; never fall back to the static grid.
     - *Verified no match:* `act-rescan-person-photos` (recognition discovery on historically anchored attachments, not identity proof) and `act-keep-person-unlinked`. Unknown/incomplete/unavailable reads retain review and Retry rather than asserting the faces disappeared.

     "Keep name, unlinked" uses the same guarded WordPress transaction: remove only the reviewed associations, retire their anchors to historical, set the person's automatic-rebind suppression, increment intent/revisions, write the ordered unbind/cancellation receipt and audit, and close the record as `resolved_unlinked`. This negative-intent branch validates the existing local person, chosen association set, current intent/revisions and effect predecessors; it does not require positive correspondence or a current preview to stop claiming those associations. Missing face proof must not trap an otherwise valid Unlink command. Missing local person/association authority still holds with Retry. Preserve the person UUID, name, origin and historical evidence. Show "no faces" if no other valid binding remains. Historical anchors never participate in automatic matching. Snapshot backfill, re-scan and replay cannot undo this choice; re-linking requires a new explicit Bind/Re-apply intent. If service delivery remains pending or fails, keep its status and recovery actionable without reopening automation (RLSE-04).
   - **f. Dead ends removed.**
     - A stale-reference resolution never retargets an original row/key. Settling possibly delivered predecessors still retries their original immutable keys under 2d; fresh resolution effects have new keys.
     - `determine_allowed_resolutions` returns the 2e actions for `stale_reference`.
     - Copy is keyed by conflict code, not `entity_type`.
     - The payload sits behind a closed "Technical details" disclosure (WRIT-02, WRIT-27, NAV-13).
     - Existing `cluster_not_found` rows go through the same resolver on their next read. No migration is needed.
   - **g. Service changes.**
     - **Replay integrity (proposed addition).** Store a fingerprint of the full immutable operation (including name, base version, intent/command/step and identity guards) with its replay result. This proposed persistent check is additional to current HTTP usage admission. Same-key changed identity or guard inputs must be rejected, never answered by a cached bind ACK. Each retry keeps the complete original payload and key. Preserve the existing authenticated tenant context, full-request usage fingerprint, duplicate-key mismatch rejection, reservation lifetime, ticket commits, expected-base checks, claim fencing and replay-result retention; the added identity guard does not narrow or replace them. A rebase or changed canonical name requires a separately validated fresh event/key, retaining the current maintenance path's fresh-key protection. The existing batch-local `curation_intent_id` is not a durable binding-intent ledger, Undo token or cross-batch ordering proof.
     - **Split.** It stops setting `user_confirmed` on labels it generates.
     - **Recovery ownership.** WordPress validates and commits changed person bindings under rule 2, then replays that intent through the outbox. The service applies WordPress-authorized binding operations; independent service identity inference is excluded. Choosing WordPress for topology recovery is this ADR's binding extension, not a ban on deterministic service projection imposed by ADR-009's label rule (alternative 3).
     - **Delivery.** Schedule eligible steps on the next drain under 2d ordering/guards; offline/conflicted steps remain pending and visible. Ranking can refresh after acknowledgement; enqueue alone promises neither synchronization nor immediate ranked eligibility (HAI-02).
   - **h. ADR-018.** A re-link and its Undo are naming-relevant curation events, so each triggers the ADR-018 derived re-weave.

3. **Every roster row is an openable person, and the photo list is that person's destination.**
   - **a. No empty UUIDs.** The projection writer never emits an empty `person_uuid`. CURUX-4 slice 1 fixes the writer and pins it with a test; such a row is never rendered inert.
   - **b. Unnamed people.** An unnamed person shows:
     - "Unnamed person";
     - their counts ("no faces" when zero);
     - a visible "Name this person" (`act-name-unnamed-person`) using the rule 1 control.
     - A machine-named person (`name_source = machine`) shows the same way, without its machine name.
     - Naming a zero-face person updates that person by UUID. It never runs the group create-or-bind path. If the name matches another person, the row offers "Merge into…" and creates no second person.
   - **c. Avatar.**
     - It is its own button, accessible name "Open {name}".
     - It uses the 72 px face crop from the E21-15 size path.
     - Avatar, name and photo count all open the same workspace (INT-01, A11Y-04).
   - **d. Row tools.**
     - Rename, Merge into… and Delete sit in one "More actions for {name}" menu (INT-27, A11Y-04).
     - The workspace header shows a visible Rename.
   - **e. Projection not current.** The workspace opens read-only with a status line; it is no longer replaced by a gate notice. Edits are disabled and the reason is shown.
   - **f. Photos with {name}** (`z-person-photos`). The shipped section keeps 50 per page and shows the person's faces (rule 2b). It gains:
     - the face box;
     - the attachment title instead of "Media %d";
     - View (`act-open-photo-lightbox`);
     - Edit media (`act-open-media-item` via `mediaEditUrl`).
     - Use as cover, as shipped.
   - **g. Header.**
     - 120 px crop, counts, and provenance in words ("named by you").
     - Debug metadata moves behind a disclosure.

4. **One unscoped review entry per roster page.**
   - Remove `z-review-cta`.
   - A header button "Review Queue (N)" (`act-goto-workbench`) sits beside Add person. Its label matches the admin menu entry and the current link text (NAV-26).
   - The hero subtitle stays as plain text (PERC-10, NAV-05).
   - The person-scoped queue buttons in the workspace stay; they serve a different job.

5. **Findings buttons act on their own loaded targets** (`z-findings`). One row per kind shows its measured scope, state and action. Counts and the global `nextAction` never supply another row's target.
   - **Selection authority.** Reuse `useSuggestionReviewQueries` and `buildReviewQueue`; select the first eligible item of each kind from the ordered, unfiltered `queue`, after existing projection/tombstone/evidence gates. Assignment, merge and name counts currently describe loaded items; top-unlabeled has a server total and truncation/repair envelope. Label those scopes honestly. A count can remain positive without an actionable loaded item.
   - **Actual targets** (current shapes from `reviewQueueDriver.ts::ReviewQueueItem`):
     - `name`: its own `suggestionId` and `clusterId`; `cluster`: its own `clusterId`. "Name next face group" opens the shared panel in label mode for that exact locally available group, with focus in the name field. NAME and CLUSTER remain separate kinds even when their copy matches.
     - `assignment`: its own `suggestionId` and nullable `clusterId`. With a resolved group, "Review next suggestion" opens the ordinary pending-suggestion panel context for that exact suggestion. With `clusterId = null`, do not invent a group: "Review suggestion in queue" selects its exact assignment card; its existing non-panel actions keep their own guards. If that card cannot be resolved, offer Retry for the assignment source and explain that its target is unavailable.
     - `merge`: its own `suggestionId`, resolved against `mergeSuggestions.id`. "Review next suggestion" selects and focuses that exact merge card; its existing Accept/Reject path remains the commit authority. No cluster id or curation-panel context is fabricated.
     - Stale references: a successfully loaded local recovery summary opens Needs attention at the selected open record; "Review N names" is shown only for a known count of distinct affected people. That summary/selection is a proposed CURUX-3 local projection, not an existing `nextAction` kind or queue field.
     - Repair: `repairPending`, `zeroEvidenceClusterCount` and `topUnlabeledTruncated` retain their current meanings. "Resync" refetches `topUnlabeledQuery`; it does not claim to start a repair job. Show checking, still pending, failed or successfully refreshed from the returned envelope; never invent a repair count or use REPAIR as a queue kind.
   - **Exact queue navigation is proposed consumer behavior.** Capture the row item's kind and stable id, re-resolve it on activation, then reveal it through the existing kind/band/index state owner. If current filters hide it, announce the change and set kind to that item's kind where supported (otherwise all), band to all. MERGE must use band=all because strong/weaker exclude merges. Find the item's index in the resulting filtered queue; render it before focusing it. Preserve bulk selections and held mutations; if existing pending-work guards prevent navigation, retain the requested target with an explained hold or let the operator defer. Do not commit anything or focus the previous card merely because filters changed. No current `focusCurrentCard()` API is claimed to select an id.
   - **Changed or disappearing targets.** Recheck the exact selected item and panel group before opening. A missing suggestion/group shows "This review target is no longer available" with Retry and Back; keep focus on the row/status. A verified local merge-survivor mapping may be offered after revalidation and announcement, without carrying stale suggestion consent onto the survivor. Null targets, timeout and 5xx are unknown/error, not proof of retirement or emptiness. Preserve an open draft and require refreshed review before mutation; never silently substitute the queue head.
   - **Availability per row.** Pending: "Checking...". Failed: name the failed source and Retry it. Unavailable: state the local projection/configuration reason and offer its existing recovery/settings action. A positive count with no loaded target remains a visible "No actionable item loaded" row with Retry/Resync as appropriate. A known successful zero may hide that kind. Loaded usable rows remain available while an unrelated source fails. Preserve locally available read/navigation while the backend is offline; writes retain their actual roster, projection, evidence and pending-work prerequisites.
   - **Empty is a successful result.** "Nothing needs review" requires successful, available reads for all included queue/recovery sources, known zero work and no repair/truncation gap. `queueSettled` includes failures/disabled reads and is insufficient. If available producers attest only page emptiness, use No review items loaded with its scope and Retry rather than a backlog-wide all-clear. A first-time successful empty result retains the existing Run a scan entry; failed or unknown sources never become zero. Status/failure changes are announced, Retry restores focus, and disabled actions give a reason. This applies RLSE-04 — Undesigned state is a bug (canon v0.26.2, `lexicons/engineering.md#rlse-04`; source `SOURCES.md#src-bootstrap`) and CARD-03 — Designed unknown (supplied CARD-03 text).
   - **Removed:** "View all findings", which duplicates the queue directly below. Extend the existing UX-map zones/actions and mirror JSON/rendered Markdown for these interactions before implementation acceptance.

6. **The queue reaches naming in one step.**
   - WBTRUST-2 S5 is the vehicle: one panel with two entries, and the heading id kept.
   - Cards for unnamed groups label their button "Name these faces", which opens label mode.
   - Named-suggestion cards keep Yes/No (WBTRUST-1).
   - The panel's name field is the rule 1 control.
   - **Ordinary exclusions have their own readiness prerequisite.** The current `removeClusterMember` sends a null target (`clusterApiMembers.ts:64-73`; `clusterApiMutations.ts:42-62`); WordPress rejects it with `missing_target_cluster_id`/400 before proxy/local mutation (`class-cluster-membership-service.php::reassign_cluster_identity:74-79`). This is the source-backed K=1 counterexample CURUX1-ADR3-01, not an executed endpoint defect. Follow [WBTRUST-2's ordinary K>0 contract](../tasks/v0.5.0/WBTRUST-2-cluster-curation-surface-task-plan.md#ordinary-k0-owned-producer-readiness-and-explained-hold): WBTRUST-2 owns the valid atomic exclusion producer and its independent verification at the actual frontend/WordPress membership/curation/outbox seams. Until ready, retain selected exclusions and name text with an explained hold; no request, label/confirm/final action or successful close may bypass them. Read/review navigation stays usable; Back/discard follows draft confirmation semantics. No fake Retry for an absent producer. Pending/unknown/partial exclusions retain work and block the final action. K=0 keeps the exact three mappings and their existing naming/confirmation gates: pending suggestion confirm, unnamed valid-name commit, named/no-suggestion zero-write close. K=0-only plus hold may be delivered under normal gates; K>0 cannot be marked complete. This prerequisite is separate from the fourth-context recovery journal and adds no dependency on all of CURUX-3. FORM-11 (Microinteractions, ch. 3), RLSE-04, designed-unknown and evidence-before-commitment apply.

7. **One vocabulary.**
   - **Visible copy** uses person, face, face group and Needs attention. It never uses cluster, identity, topology, phase, payload or compound, and it comes from one source (UXP-4; NAV-13, WRIT-02, WRIT-27).
   - **In code** (DOM-03):
     - "person" means an `acx_persons` row;
     - the service's roster-candidate grain is "bound group keyed by `roster_id`", and the API names it that way.

8. **Step 0: record the served build and demo data before any slice.** This matches WBTRUST-2's existing binding. Record:
   - `ACX_VERSION` and the bundle name from the enqueued script URL;
   - a build marker: a commit SHA as a data attribute on the admin root, since none exists;
   - the writer and provenance of "Person 1".."Person 5";
   - the row-4 record (person UUID, name, group count);
   - the roster `projection_status`;
   - for the four stale references, record UUID survival separately from immutable source proof, namespace compatibility and anchor eligibility under 2b–2c. UUID survival alone cannot establish correspondence; served reset/restore behavior remains an observation to obtain, not a source-read result.

**ADR-003 amendment (rule 7, appended; accepted with this ADR).** "A stale reference is an outbox operation or projected binding that targets a face group the backend no longer has, or whose membership/source correspondence changed or became unverified under a person binding. It is recorded as `stale_reference` and surfaced in Needs attention unless the rule 8 exception applies."

**ADR-003 amendment (rule 8, appended; accepted with this ADR).** "Exception: a stale reference may continue an existing WordPress binding intent automatically only when the successor is pure under ADR-019 rule 2d, correspondence is verified under rule 2c, intent is active and unsuppressed, and all person/group/membership/snapshot guards pass at commit. Historical anchors and human labels alone confer no matching authority. Resolution is audited, visible, undoable and switchable; Undo and intentional unlink persist suppression until new explicit binding intent. The local mutation, intent/anchor transition and durable outbox plan commit atomically. Service application remains version-checked, idempotent derived alignment, not a second person authority."

This written amendment and the binding-consumer contract were accepted with this ADR on 2026-10-18 (see Status). The rule 7 and 8 text has not yet been appended to the ADR-003 document itself; that is a documentation follow-up, not another approval gate. Acceptance does not make any proposed field, producer or command current. Consumers that depend on them keep the abstentions and holds stated in rules 2c–2e and 6 until those producers are implemented and independently verified. No plan or consumer silently substitutes choices beyond this accepted text for ADR-003/009 (AGT-13).

### Target outcome

- **S-A** `workbench-2pane/workbench-control/z-name-curate` (`max_candidates: 5`):
  - typing works at once;
  - only human-named people appear: up to 5 ranked rows with reference faces, then A–Z.
- **S-B** `workbench-conflicts` (retitled "Needs attention"):
  - a re-analysis with complete same-namespace proof and a pure successor may re-link behind a status line with Undo; a reset, restore or missing proof preserves names and routes to review under 2c;
  - every other case gets evidence and an action (`act-rebind-person-faces`, `act-review-rebind-faces`, `act-keep-person-unlinked`, `act-rescan-person-photos`).
- **S-C** `roster-shell/z-entries`:
  - no inert row;
  - the 72 px avatar, the name and the count each open the person;
  - `z-review-cta` is gone.
- **S-D** `roster-person-workspace/z-person-photos`: photos show face boxes, with View and Edit media (`exit-media-item`, `flow-person-to-photos`).
- **S-E** `workbench-control/z-findings`: every button opens what it names.
- **S-F** `workbench-review-panel` ("Name these faces", `z-review-name`, `act-save-review-name`): naming is one step from the queue.

## Why This Decision

### Curated-only is a provenance fact, not a label shape

- "Person 3" passes every shape filter in the tree.
- `user_confirmed` is set by service paths the operator never touched.
- The only durable signal is who wrote the name, so the writer records it once, at write time.

### HAI-15 and HAI-16 do not fire here

- **HAI-15** triggers on a face-pair review that shows a model same/different label before the reviewer's own judgment.
  - Free naming is not a pair review.
  - Successor matching requires proved unchanged source observations under rule 2c, not a similarity verdict or a bare face-record UUID.
  - The "Is this X?" card stays with WBTRUST-1.
  - Dropping band words (rule 1d) follows HAI-15's intent but is not required by it.
- **HAI-16** triggers on a forced-choice pick with no cap.
  - The picker is not forced: typing a new name and leaving the face unnamed both remain available.
  - The cap of 5 is a design choice, well under the row's 100-item risk line.

### Face identity, not similarity, moves a human name

- Moving a name by embedding proximity would be the model naming people.
- Exact correspondence requires the immutable source-observation evidence and namespace contract in rule 2c. Equality of `identity_uuid`, attachment and box is insufficient. Geometry may propose faces for fresh human review; neither geometry nor embedding similarity transfers a name automatically.

### Amend ADR-003 instead of routing everything to the inbox

- Automatic carry-forward is limited to proved unchanged source observations in the same namespace. Reset, restore and missing proof require review even when every UUID survives; the person and name remain available.
- The pure-successor exception overwrites nothing curated.
- It keeps rule 8's intent: no silent overwrite, operator control through Undo and the setting, and an audit row.

### The photo proposal is right, and it mostly exists

- Canon v0.26.2 supports the proposal:
  - NAV-19: keep the photos next to the person.
  - NAV-20: the Media Library has no person attribute path.
  - NAV-35: `person_uuid` → face members → `attachment_id` is the unique link.
- The section already ships (50 per page). The defect is reachability: the UUID, the projection gate and the avatar target.
- No canon row sets a face-thumbnail size. The current 32 px already clears A11Y-14 (24 px). The 72 px choice rests on E21-15's prior decision and the operator report.

## Alternatives Considered

### 1. Filter machine labels by pattern (`^Person \d+$`)

Rejected. BR-17 already showed that shape filters leak, and machine labels can take any shape. Provenance does not leak.

### 2. Keep WBTRUST-3 S2 as written ("face count or band words")

Rejected. A band word beside a name is a model verdict shown before the operator compares faces. Reference faces are better evidence (HAI-17).

### 3. Deterministic service projection of WordPress intent across merge and split

A derived service projection is compatible with one WordPress curation authority. It is distinct from independently inferring identity from labels, embeddings or the split label-owner heuristic. Snapshot omissions alone reject neither the inputs nor the alternative.

- **Existing inputs.** `CurationSyncService._apply` reads and writes `roster_id` from `cluster_person_bound` / `cluster_person_unbound`; the bind name comes from `person_name` (`curation_sync_service.py:135-203,441-469`). Operator/recovery merge receipts contain `source_cluster_id`, `survivor_cluster_id` and `moved_identity_ids`. The split topology command persists source, remaining-member and created-group partitions through `member_delta`, with `result_snapshot_version`, already consumed by WordPress (inventory b). These are useful correspondence inputs; do not duplicate them.
- **Limits.** A merge receipt stores `source_label`, not the authoritative person intent or its revision (`identity.py::ClusterMergeReceipt:386-409`). Receipt sequence numbers order merges per survivor, not all person edits. Split partitions identify moved rows, but its label-owner choice can use centroid similarity; that does not authorize extending a human name. Discovery deletion, soft disposal and purge have different lineage/lifecycle paths. None of these receipts establishes unchanged media evidence: scan reconciliation can reuse UUIDs by box overlap and rewrite detection data (`scan/service.py::_persist_identities_unlocked:736-795`). Snapshot member fields contain no immutable media revision (`responses.py::ClusterSnapshotMemberResponse:643-656`). Complete identity correspondence remains a required predicate, not an assumption supplied by a receipt.
- **Ordering and offline authority.** The service sees replayed intent; WordPress can have a newer offline unlink, exclusion or rename. Cached replay is per key, and the `curation_intent_id` / `local_revision` continuation proof is limited to a label-then-bind chain within one `apply_batch` (`curation_sync_service.py:92-112,394-432`). It is not a persistent ordering proof for all person/topology changes. Preserve canonical-name refresh and changed-bind key rotation, route admission guards, and existing tenant/LIFO/expiry/member/source-occupancy checks on merge revert (`cluster_merge.py::_revert_merge_impl:714-777`). None is evidence of a reproduced runtime defect.

**Decision.** Keep recovery validation and local binding commits in WordPress under rule 2, where current operator intent and the offline rendering authority reside; use existing service receipts/deltas as evidence and replay authorized changes. This is a locality and contract-completeness choice, not an inherent dual-writer objection or a prohibition inferred from ADR-009 rule 1. WordPress still requires the separately reviewed correspondence and commit predicates; locating the resolver there does not prove them.

**Condition for reconsideration (proposed contract, not current wire fields).** A service projection proposal must supply WordPress-authorized person intent with an ordering/version proof, complete tenant-scoped before/after membership correspondence including retained originals, verified media correspondence, and the consumed receipt/snapshot versions. WordPress remains the sole authority for person intent. Postconditions: replay or late lineage cannot restore an intentionally removed binding; no mixed or unknown face acquires the name; duplicate delivery has no additional effect. Missing, stale, loading, failed or offline evidence retains the local name and routes to review; it is not proof of zero successors. Any changed consumer choice needs a written ADR amendment before landing (AGT-13 — No silent ADR override; canon v0.26.2, `lexicons/engineering.md#agt-13`, Software Architecture: The Hard Parts, ch. 1).

### 4. Pick the successor by embedding similarity to the old group

Rejected. A model judgment would attach a human name without review. Only the proved unchanged source-observation correspondence in rule 2c may feed automatic re-link; a face-record UUID alone is not exact evidence.

### 5. Discard `cluster_not_found` as entity-gone (the TRIAGE0918-M-08 path)

Rejected. It silently drops a human name from the faces.

### 6. Send every stale reference to the inbox

Not required for proved pure successors under rule 2c–2d. It is the mandatory fallback for reset, restore, missing proof or ambiguous correspondence, and remains available for every case through the setting-off mode (INT-20). A preserved human name is preferable to an unproved transfer.

### 7. A separate photos page per person

Rejected. Photos already live in the workspace, and a second surface would split the destination (NAV-19).

## Consequences

### Positive

- Names survive a re-analysis with proved unchanged source observations (rule 2c). Every other case retains the person and name and offers fresh review or "Keep name, unlinked"; missing proof never authorizes direct identity-based Re-apply.
- The picker shows people, not machine artifacts.
- Every roster row and findings button leads somewhere.

### Negative

- **Bootstrap and reset.** Legacy records may have no proof of the source the operator named. Keep the existing person UUID/name and historical association, mark "Faces need review", and withhold unverified current faces/counts from that person's confirmed view until fresh selection. Do not reconstruct historic proof from today's attachment or require a new person row. A separately authorized destructive demo rebuild is an operational action, not evidence that recovery preserves names; this proposal authorizes no reset or re-naming exercise.
- **Background mutation.** Automatic re-link is a background mutation. It needs status, Undo, a setting and an audit trail.
- **Service work.** Person-grain ranking changes the service's candidate query and the PHP mapper.

### Guardrails for the follow-on implementation task

- **Enums (sr-007).** New status values are backed enums: `stale_reference`, `auto_resolved`, `resolved_unlinked`, `superseded`, `name_source`, `label_source`; proposed correspondence and recovery values are defined once in 2c and WBTRUST-2 respectively.
- **Identity evidence gate.** Automatic resolution is unavailable until the proposed 2c producer, snapshot schema, importer, lifecycle barrier and anchor storage preserve the complete proof. No fallback uses equal UUID/attachment/bbox, `image_phash`, URLs, `snapshot_generation_id` or `snapshot_version` as source identity. A test must show that changed source with identical IDs/box abstains; the unchanged-source control must qualify only with valid proof and eligible current intent.
- **Frozen decision inputs.** Resolve against one frozen incoming member set, its namespace/proofs, and the corresponding WordPress anchor/intent view, separately from preserved local membership. A changed input invalidates that decision; the mutation owner must revalidate or recompute before applying it. This is a predicate requirement, not a choice of locks, transactions or replay keys (GRPH-39 — Parallelise only against a frozen topology; canon v0.26.2, `lexicons/graph-theory.md#grph-39`).
- **Identity counterexamples required before implementation acceptance (not executed by this ADR):** replaced attachment pixels at the same bbox/UUID → no automatic transfer; replacement without a new scan → no named unverified live crop; byte-identical source/raster/region with valid same-namespace observation → eligible under 2d; purge then recreate → new observation, review; export-only restamp → unchanged correspondence; reset/restore/clone or recycled namespace token → review; two faces in one media item → distinct one-to-one observations, no cross-assignment; changed crop/thumbnail/representative URL only → no identity change when backed by the same verified source; missing legacy proof or unavailable/incomplete input → unknown, name retained; complete proved zero-match → no faces, name retained. Restoring equal serialized namespace IDs cannot restore eligibility; an unverified lifecycle attestation keeps automation unavailable.
- **Required test matrix:**
  1. a reset with four named people;
  2. one person split across two groups;
  3. two people merged into one group;
  4. all faces gone;
  5. the same operation replayed twice;
  6. a rename while the re-link is pending;
  7. an unnamed person with zero faces;
  8. an empty roster.
- **No invented values (rg-015).** PHP never invents similarity for A–Z rows.
- **No unexplained disabled controls.** Hold reasons use `aria-disabled` plus text (rg-003).
- **Map deltas** land in slice 1 of each task and pass `make lint-ux-maps`.

### Follow-on tasks

| Task | Scope | Depends on |
|---|---|---|
| WBTRUST-3 amendment | S2 row content per rule 1d; S2/S3 consume 1a–1c and 1e | CURUX-2 for 1a–1c |
| WBTRUST-2 amendment | S5 card label and ordinary exclusion readiness/hold (rule 6); fourth stale-rebind context and commit/failure contract (rule 2e) | Ordinary contexts retain WBTRUST-3's settled naming control and the WBTRUST-1 shared-file exclusion. Ordinary K>0 additionally consumes WBTRUST-2's owned, independently verified valid exclusion producer; K=0-only/hold delivery does not. Only the fourth-context renderer consumes the proposed CURUX-3 recovery journal and command receipts; it does not wait for the whole CURUX-3 surface. |
| CURUX-2 | Provenance columns and gate (1a, 1b); person-grain ranking (1c); service split flag (2g) | Step 0 |
| CURUX-3 | Stale-reference core: anchors, resolver, guarded local command/journal, replay and copy; then Needs attention/review entry (rule 2) | Step 0. Core produces the proposed recovery record, validated group map and command receipts without a panel dependency. Exposing `act-review-rebind-faces` consumes WBTRUST-2 S5's fourth-context renderer and exclusion support; no static-grid fallback. |
| CURUX-4 | Roster and workspace (rules 3, 4) | Step 0; CURUX-2 (rule 1 control and provenance); WBTRUST-3 control (rule 1e) |
| CURUX-5 | Findings target selection, exact navigation and availability (rule 5) | Existing queue items and source query states feed queue actions. Panel actions consume WBTRUST-2 S5's resolved ordinary contexts. Only the stale-reference row consumes CURUX-3's proposed local recovery summary/record selection; absent that producer, show its designed unavailable state. Other rows remain independently implementable. |

Step 0 (rule 8) runs once as the first slice of whichever task starts first, and its result is recorded under CURUX-1.

**Dependency inputs (proposed implementation decomposition).** Edges below name actual consumed outputs, not proposal authors or prose order (GRPH-32). Each node also consumes Step 0's served-build/projection/evidence inventory. The table is acyclic (GRPH-01); ordinary work need not wait for missing automatic-evidence readiness.

| Producer node | Consumer node | Named input or ordering constraint |
|---|---|---|
| WBTRUST-4 | WBTRUST-3-control | `runAfterCooldown` invalidation/budget primitive |
| CURUX-2 | WBTRUST-3-options | human provenance and UUID-grain candidate projection (rules 1a–1c) |
| WBTRUST-3-control | WBTRUST-3-options | settled naming-control behavior and roster guards |
| WBTRUST-3-options | WBTRUST-2-ordinary | amended naming control/options; existing contextual commits |
| WBTRUST-2-exclusion-producer | WBTRUST-2-ordinary-K-positive | independently verified valid atomic exclusion capability, guarded inputs/results and replay/failure semantics; K=0 and explained hold do not consume it |
| WBTRUST-2-ordinary | WBTRUST-2-ordinary-K-positive | selected identities and resolved ordinary entry context from the shared panel |
| CURUX-3-core | WBTRUST-2-recovery | recovery record, acknowledged draft, `review_source_ref`, guarded exclusion/rebind commands and receipts |
| WBTRUST-2-ordinary | WBTRUST-2-recovery | shared selectable panel component and resolved ordinary contexts |
| WBTRUST-2-recovery | CURUX-3-entry | explicit record-based recovery renderer/resume action |
| CURUX-3-core | CURUX-3-entry | local recovery summary and selected open record |
| CURUX-2 | CURUX-4 | human provenance and person options |
| WBTRUST-3-options | CURUX-4 | UUID rename/create control and roster guard |
| WBTRUST-2-ordinary | CURUX-5-panel | resolved ordinary panel entry for the row's exact target |
| CURUX-3-core | CURUX-5-stale | local summary/count scope and open recovery record |

CURUX-3-core may implement manual source/intent/receipt producers without the automatic `face_evidence_v1` producer; its automatic branch remains ineligible until 2c is independently verified. The ordinary K-positive branch is part of WBTRUST-2, distinct from its K=0/hold panel and from CURUX-3-core: it consumes the ordinary panel's selection/resolved context as well as the producer capability. CURUX-5 queue navigation consumes existing `ReviewQueueItem` and per-source query states directly. There is no edge from CURUX-3-entry/panel back to core. WBTRUST-1 versus WBTRUST-2 writes to `ReviewQueue.tsx`, provenance versus recovery writes to `class-cluster-snapshot-merger.php`, and ordinary/recovery writes to shared membership/curation/outbox seams are resource exclusions to serialize at integration, not data dependencies. WBTRUST-3 retains its WBTRUST-4 prerequisite throughout.


## Open Questions

1. **Proposed reset/restore contract is fixed by rule 2c; implementation readiness is unproved.** Current new identities default to `uuid4`, purge can delete them, and `snapshot_generation_id` is minted per stamped export. Step 0 records deployed behavior and whether the proposed evidence/namespace authority exists. Until it is verified, reset/restore matches abstain; no outcome is inferred from UUID survival or an export stamp.
2. **Does the member merger rewrite `cluster_uuid` for members of a preserved curated group?** Source says curated rows keep their `cluster_uuid` (`class-identity-member-snapshot-merger.php:146`), while uncurated rows move. CURUX-3 slice 1 confirms where in the merge the anchors are written.
3. **Which build is served, and is the GTMSMOKE-1 fix in it?**
4. **What writes "Person 1".."Person 5"?** Answered in the inventory (rule 1b): the production auto-labeler. Step 0 confirms which demo rows it wrote.
5. **What data is behind row 4?**
6. **Attachment-scoped discovery.** `class-analysis-jobs-controller.php:124-141` already accepts `media_ids`. Step 0 verifies the served route and its guards; reuse that seam rather than adding a duplicate endpoint. Discovery never certifies prior correspondence.

## References

- [ADR-003](ADR-003-wordpress-local-authority-and-durable-outbox-replay.md), [ADR-009](ADR-009-recognition-curation-refresh-and-person-review-projection.md), ADR-018 (`feature/idweave-1`)
- [WBTRUST-1](../tasks/v0.5.0/WBTRUST-1-review-queue-trust-task-plan.md), [WBTRUST-2](../tasks/v0.5.0/WBTRUST-2-cluster-curation-surface-task-plan.md), [WBTRUST-3](../tasks/v0.5.0/WBTRUST-3-naming-ux-and-persistence-task-plan.md), [WBTRUST-4](../tasks/v0.5.0/WBTRUST-4-request-budget-task-plan.md), [WBTRUST-5](../tasks/v0.5.0/WBTRUST-5-control-placement-task-plan.md)
- [CURUX-1 screens and map deltas](../assessments/current/curux-1-identity-curation-screens-2026-10-16.md)
- [Roster/workbench identity UX assessment](../assessments/current/roster-workbench-identity-ux-assessment-20260913.md)
- Canon v0.26.2 rows (`lexicons/`):
  - `interaction-ux.md`: `#cog-02`, `#form-09`, `#form-11`, `#hai-02`, `#hai-06`, `#hai-11`, `#hai-15`, `#hai-16`, `#hai-17`, `#int-01`, `#int-06`, `#int-07`, `#int-08`, `#int-10`, `#int-13`, `#int-20`, `#int-27`, `#nav-02`, `#nav-05`, `#nav-13`, `#nav-19`, `#nav-20`, `#nav-26`, `#nav-35`, `#perc-10`
  - `engineering.md`: `#agt-13`, `#data-14`, `#dom-03`, `#dom-06`, `#res-19`, `#rlse-04`
  - `ml-systems.md`: `#cal-02`, `#cal-10`, `#emb-06`
  - `graph-theory.md`: `#grph-01` (Model the work as a DAG, then topological-sort), `#grph-32` (An edge exists only where data moves), `#grph-14` (Record provenance as a walkable lineage graph; Building Knowledge Graphs, ch. 8 + Mental Models, ch. 8), `#grph-39` (Parallelise only against a frozen topology; STORM / Co-STORM knowledge curation system)
  - `accessibility.md`: `#a11y-04`, `#a11y-14`, `#a11y-21`
  - `writing.md`: `#writ-02`, `#writ-27`
