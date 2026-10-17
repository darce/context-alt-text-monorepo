# ADR-019: Person-anchored curation — names, stale references, roster, findings

- **Status:** Proposed (needs operator acceptance before CURUX-2..5 slices and the WBTRUST-3 S2 amendment)
- **Date:** 2026-10-16
- **Context task:** CURUX-1
- **Amends:** [ADR-003](ADR-003-wordpress-local-authority-and-durable-outbox-replay.md) rules 7 and 8 (stale references only); [WBTRUST-3](../tasks/v0.5.0/WBTRUST-3-naming-ux-and-persistence-task-plan.md) Slice S2 row content.
- **Extends:** [ADR-009](ADR-009-recognition-curation-refresh-and-person-review-projection.md) rule 1 (WordPress owns the person binding).
- **Coordinates with:** ADR-018 post-curation identity weaving (Proposed, branch `feature/idweave-1`).
- **Screens and map deltas:** [CURUX-1 screens](../assessments/current/curux-1-identity-curation-screens-2026-10-16.md) (S-A..S-F).
- **Heuristics (canon v0.26.2):** AGT-13, COG-02, HAI-11, EMB-06, CAL-02, CAL-10, HAI-15, HAI-16, HAI-17, NAV-02, FORM-09, FORM-11, INT-08, A11Y-21, DOM-03, DOM-06, DATA-14, RES-19, HAI-02, HAI-06, INT-07, INT-10, INT-13, INT-20, NAV-35, NAV-19, NAV-20, NAV-26, NAV-05, PERC-10, INT-01, INT-06, INT-27, A11Y-04, A11Y-14, RLSE-04, NAV-13, WRIT-02, WRIT-27.

## Status

Proposed. AGT-13 ("No silent ADR override") applies. Rule 2 changes how ADR-003 rules 7 and 8 treat one class of record, and rule 1 replaces a binding design decision in WBTRUST-3 S2. This ADR amends both before any code lands.

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
  - E21-15 (7930, 8391, 8396): machine labels were shown as people. BR-17 filters the cluster leg only, and BR-49 gate bypasses remain. Regressed.
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
  - E21-20 (8847): dead REPAIR branch.
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

  This ADR does not re-decide them. It adds the rules they lack and amends one WBTRUST-3 binding.
- **ADR-018 (Proposed).**
  - Names are never generation inputs.
  - Every naming-relevant curation event (bind, unbind, label, merge, split, member move) triggers a derived re-weave.
- **Greenfield.**
  - No data migrations.
  - Demo data follows the clean-slate procedure.
- **The served build is unknown.**
  - The only fingerprint is `ACX_VERSION` 0.0.38 (`alt-context.php:7`, `class-admin.php:277-292`), and there is no commit marker.
  - Every claim below comes from source at d25922fa (SOURCE-READ by five remote grunt lanes). None was reproduced in a browser.

## Current State Inventory

**(a) Naming**

- *Input gating*
  - The input is disabled whenever `isLoading` is true (`NameFaceControl.tsx:268-269`). "Loading people…" is the status text (`:355-357`).
  - `isLoading` ORs four reads (`useClusterSuggestionsLoader.ts:328-335`): the identity-batch read, label matches, at-rest labels and the roster list.
  - The closest-people read waits for the identity batch (`:266-285`).
  - None of these reads passes `timeoutMs`, so each falls back to `DEFAULT_FETCH_TIMEOUT_MS = 300_000` (`http.ts:45-46, 230-234`).
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
- *"Person N".* No production writer was found. Only a test fixture produces it (`test_api_suggestions.py:1014`).

**(b) `cluster_not_found`**

- *Service side*
  - The service returns the conflict when an outbox operation targets a group it no longer has (`curation_sync_service.py:125-134`).
  - Results are replayed by `(tenant, idempotency_key)` before any lookup (`:110-112`; `identity.py:321`).
  - The payload is not fingerprinted.
- *Paths that remove a group UUID*
  - User merge and recovery merge: with a receipt.
  - Discovery merge: no receipt; the source label is dropped (`discovery_pipeline.py:783-792`).
  - Curation-job cleanup: `curation_job.py:286-288`.
  - Soft-dispose and purge.
  - Split mints new groups with no link from old to new.
- *Snapshot contents*
  - It carries no `roster_id` (`responses.py:670-691`).
  - Its members carry `identity_uuid`, `cluster_uuid`, `attachment_id` and `bbox` (`responses.py:643-656`).
- *WordPress recording*
  - WordPress records the 409 as an outbox `CONFLICT` plus a conflict row in one transaction (`class-outbox-dispatcher.php:273-274`; `class-outbox-drain.php:564-570, 665`).
- *Snapshot merge*
  - It keeps curated groups that are absent from the snapshot untouched, with no successor mapping (`class-cluster-snapshot-merger.php:96, 379-392, 422`).
  - It deletes uncurated absent groups and their `cluster_not_found` rows (`:491`).
  - Members keep `identity_uuid`, `attachment_id` and `bbox_json` (`class-identity-member-snapshot-merger.php:122-136`), but no code uses them to find a successor.
- *Copy*
  - Copy is chosen by `entity_type`, not by code. Every cluster row gets "This compound topology conflict only supports keeping the local version in Phase 4" (`conflictInboxUtils.ts:71-87`).
  - An empty `allowed_resolutions` (`class-conflict-controller.php:400-444`) renders "No resolution actions are available" (`ConflictDetailPanel.tsx:79, 130, 149`).
- *Keep local loops*
  - Keep local re-enqueues the same outbox row, key and payload (`class-conflict-resolution-service.php:221` → `class-outbox-maintenance-service.php:1918-1932`).
  - The service returns its stored `cluster_not_found`.
  - `ON DUPLICATE KEY UPDATE` then reopens the same conflict row (`class-conflict-repository.php:135-147`).
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
  - The only action is the lightbox (`:257-261`).
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
  - `PersonCommitControl` appears only on name and assignment rows (`ReviewQueue.tsx:2173-2192`).
- "Review" opens `ClusterReviewPanel`, which has no name control (`ClusterReviewPanel.tsx:122-130, 169-170`).
- The heading region does not dangle (`ScanTabContent.tsx:233-238`).

### Downstream surfaces that must migrate together

- **UX maps:** `roster-people`, `workbench-2pane`, `workbench-operator-loop`. The screens doc lists the deltas. Each task's slice 1 applies them, then runs `make lint-ux-maps`.
- **WordPress schema:** two provenance columns and one anchor table (rules 1 and 2). These land in the plugin schema under the greenfield policy.
- **Generated `RosterEntry` type:** gains `name_source`.
- **Conflict vocabulary:** the UXP-4 single source of truth. `stale_reference` copy is keyed by code.
- **Plans:** WBTRUST-3 S2 text (rule 1d) and WBTRUST-2 S5 card label (rule 6).

## Decision

### Chosen design rules

1. **Naming options are human-named people, ranked by face similarity.** This rule amends WBTRUST-3 S2.
   - **a. Grain.** One option per person (an `acx_persons` row). Sources:
     - persons with `name_source = human`;
     - human-written group labels (`label_source = human`) that match no person by WBTRUST-3's name key. These render as the same kind of row, and saving one creates or binds that person.

     A machine-written label is never an option, whatever its shape.
   - **b. Provenance.** `acx_persons.name_source` and the projected group's `label_source` take values from a backed enum (`human`, `machine`).
     - Only the admin-UI write paths write `human`.
     - The snapshot merger and backend-applied labels write `machine`.
     - Every person-name write path, including roster create and rename and `handlePersonSelect`/`applyPersonLabel`, goes through one shared reserved-label gate (FORM-11). This closes the E21-15 BR-49 bypasses.
   - **c. Ranking.**
     - Similarity is pairwise probe–gallery similarity at person grain (EMB-06).
     - The Python candidate set is the groups bound to a WordPress person (`roster_id` set by `cluster_person_bound`), grouped by `roster_id` and scored by maximum similarity. `user_confirmed` no longer selects candidates.
     - PHP maps `roster_id` to `acx_persons` and drops any person that fails 1a.
     - A person below `suggestion_floor` is not ranked (CAL-02).
   - **d. Display.**
     - At most 5 ranked rows, then the A–Z remainder filtered by the typed text.
     - The ranked block does not re-sort while the list is open (NAV-02).
     - Each ranked row shows up to 3 of that person's faces closest to the probe group, plus the face count (HAI-17).
     - No score or band word appears beside a name.
     - The person already bound to the probe group is not offered (IDREBIND-1).
   - **e. Loading.**
     - The input is enabled from first render, and `isInputDisabled` keeps only `disabled` and save-pending.
     - Pending reads drive a polite status line, "Finding closest people…" (INT-08, A11Y-21).
     - "Add as a new person" stays disabled until the roster list settles, and the status line gives the reason (FORM-09; UXW2-3 race).
     - The optional reads start in parallel, each with an explicit WBTRUST-4 budget rather than the 300 s default.
     - A failure or timeout shows "Showing people A–Z" with Retry. Typing a name always works (CAL-02, HAI-11).
   - **f. Empty roster.** "No named people yet — type a name" (RLSE-04).

2. **A missing face group is a stale reference, re-linked by face identity, not a curation conflict.** This rule amends ADR-003 rules 7 and 8; the amendment text follows the rules.
   - **a. Classification.** These two cases are classified as `stale_reference`, separate from `version_conflict` (a true concurrent edit):
     - a service `cluster_not_found`;
     - a snapshot that drops a person-bound group.

     Each is still stored as a record, so rule 7 holds.
   - **b. Anchors.**
     - The snapshot merge is the only local writer of face membership.
     - In the same transaction, before it moves or removes members of a person-bound group, it writes one anchor per face shown under that person: `(person_uuid, identity_uuid, attachment_id, bbox, from_cluster_uuid, snapshot_version)`.
   - **c. Successor resolution** uses face-record identity only (NAV-35), never embedding similarity:
     - first, `identity_uuid`;
     - if that is absent (re-detection after a reset or purge), `attachment_id` plus a bbox IoU ≥ 0.7 with a unique 1:1 match. CURUX-3 slice 1 validates the threshold on demo data.
   - **d. Automatic re-link applies only to a pure successor.**
     - *Pure* means:
       - there is exactly one successor group;
       - it has no person binding and no human label;
       - every face in it is an anchor of this person.
     - In one transaction:
       - enqueue a new `cluster_person_bound` outbox operation (DOM-06, DATA-14), taking the name from local state (ADR-009 rule 1);
       - key it by `hash(person_uuid, from_cluster_uuid, successor_cluster_uuid, snapshot_version)` (RES-19);
       - mark any pending operation against the old group `superseded` (never re-sent);
       - close the record as `auto_resolved` with an audit row (HAI-06).
     - The operator sees "Re-linked "{name}" to N faces after re-analysis · Undo" (INT-10).
     - Undo enqueues `cluster_person_unbound` and reopens the record.
     - Option `acx_auto_relink_names` (default on) switches this off. When it is off, every case goes to Needs attention, where re-apply is the manual equivalent (INT-20).
     - This is INT-13's one safe choice: it asserts nothing the operator had not already seen under this person.
   - **e. Every other case goes to Needs attention** (`workbench-conflicts`). Each item states the cause in plain words and shows the successor faces as evidence:
     - *Several successor groups, every face an anchor:* `act-rebind-person-faces`, with a preview of groups and faces (INT-07).
     - *A successor with extra faces never shown under this person:* the default is `act-review-rebind-faces`, which opens the WBTRUST-2 panel to exclude faces. Re-apply stays available, and its preview marks the extra faces.
     - *A successor bound to another person, or holding another person's anchors:* no Re-apply. Only `act-review-rebind-faces` and `act-keep-person-unlinked` are offered (CAL-10).
     - *No successor:* `act-rescan-person-photos` (re-run recognition on the anchored attachments) and `act-keep-person-unlinked`.

     "Keep name, unlinked" keeps the person in People with "no faces", keeps the anchors, and closes the record as `resolved_unlinked`. Every state has an action (RLSE-04).
   - **f. Dead ends removed.**
     - A stale reference never re-enqueues its original outbox row or key.
     - `determine_allowed_resolutions` returns the 2e actions for `stale_reference`.
     - Copy is keyed by conflict code, not `entity_type`.
     - The payload sits behind a closed "Technical details" disclosure (WRIT-02, WRIT-27, NAV-13).
     - Existing `cluster_not_found` rows go through the same resolver on their next read. No migration is needed.
   - **g. Service changes.**
     - **Payload fingerprint.** The replay row stores a fingerprint of `operation_type`, `cluster_uuid` and `person_uuid` (not `person_name`). The same key with different identity fields gets an explicit 409 `idempotency_payload_mismatch`. Replay results stay stored, so ADR-003 rule 5 is unchanged.
     - **Split.** It stops setting `user_confirmed` on labels it generates.
     - **No carry-forward.** The service does not carry bindings across merge, split or discovery merge. WordPress re-binds, so there is a single writer (ADR-009 rule 1, DATA-14).
     - **Delivery.** The re-link must reach the service in the next drain, so that rule 1c ranks the person again (HAI-02).
   - **h. ADR-018.** A re-link and its Undo are naming-relevant curation events, so each triggers the ADR-018 derived re-weave.

3. **Every roster row is an openable person, and the photo list is that person's destination.**
   - **a. No empty UUIDs.** The projection writer never emits an empty `person_uuid`. CURUX-4 slice 1 fixes the writer and pins it with a test; such a row is never rendered inert.
   - **b. Unnamed people.** An unnamed person shows:
     - "Unnamed person";
     - their counts ("no faces" when zero);
     - a visible "Name this person" (`act-name-unnamed-person`) using the rule 1 control.
   - **c. Avatar.**
     - It is its own button, accessible name "Open {name}".
     - It uses the 72 px face crop from the E21-15 size path.
     - Avatar, name and photo count all open the same workspace (INT-01, A11Y-04).
   - **d. Row tools.**
     - Rename, Merge into… and Delete sit in one "More actions for {name}" menu (INT-27, A11Y-04).
     - The workspace header shows a visible Rename.
   - **e. Projection not current.** The workspace opens read-only with a status line; it is no longer replaced by a gate notice. Edits are disabled and the reason is shown.
   - **f. Photos with {name}** (`z-person-photos`). The shipped section keeps 50 per page and gains:
     - the face box;
     - the attachment title instead of "Media %d";
     - View (`act-open-photo-lightbox`);
     - Edit media (`act-open-media-item` via `mediaEditUrl`).
   - **g. Header.**
     - 120 px crop, counts, and provenance in words ("named by you").
     - Debug metadata moves behind a disclosure.

4. **One unscoped review entry per roster page.**
   - Remove `z-review-cta`.
   - A header button "Review Queue (N)" (`act-goto-workbench`) sits beside Add person. Its label matches the admin menu entry and the current link text (NAV-26).
   - The hero subtitle stays as plain text (PERC-10, NAV-05).
   - The person-scoped queue buttons in the workspace stay; they serve a different job.

5. **Findings buttons do what they say** (`z-findings`). There is one row per kind: a count, plus a button that names its effect (INT-06, A11Y-04, NAV-26).
   - **Rows**
     - `name` / `cluster`: "Name next face group" (`act-finding-name-next`) opens the curation panel in label mode for the target, with focus in the name field.
     - `merge` / `assignment`: "Review next suggestion" opens the panel in review mode with the `suggestionId`.
     - Stale references: "Review N names" (`act-finding-open-rebind`) opens Needs attention.
     - Repair (E21-20): "Resync now" (`act-finding-resync`) ships only if CURUX-5 slice 1 confirms an existing resync job route. Otherwise the dead REPAIR branch is deleted.
   - **Removed:** "View all findings", which duplicates the queue directly below (PERC-10).
   - **Empty states**
     - A kind with a zero count is not rendered.
     - When every kind is zero, the panel shows "Nothing needs review".
     - No button is disabled without a reason.

6. **The queue reaches naming in one step.**
   - WBTRUST-2 S5 is the vehicle: one panel with two entries, and the heading id kept.
   - Cards for unnamed groups label their button "Name these faces", which opens label mode.
   - Named-suggestion cards keep Yes/No (WBTRUST-1).
   - The panel's name field is the rule 1 control.

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
   - for the four stale references, whether their `identity_uuid`s survive.

**ADR-003 amendment (rule 7, appended).** "A stale reference is an outbox operation or projected binding that targets a face group the backend no longer has. It is recorded as `stale_reference` and surfaced in Needs attention unless the rule 8 exception applies."

**ADR-003 amendment (rule 8, appended).** "Exception: a stale reference whose successor is pure under ADR-019 rule 2d may be resolved automatically in favour of local curation. The human binding moves to faces it already covered. Nothing curated is overwritten. The resolution is audited, visible, undoable, and can be switched off."

### Target outcome

- **S-A** `workbench-2pane/workbench-control/z-name-curate` (`max_candidates: 5`):
  - typing works at once;
  - only human-named people appear: up to 5 ranked rows with reference faces, then A–Z.
- **S-B** `workbench-conflicts` (retitled "Needs attention"):
  - a reset with pure successors re-links names behind one status line with Undo;
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
  - Successor matching uses face-record identity, not a similarity verdict.
  - The "Is this X?" card stays with WBTRUST-1.
  - Dropping band words (rule 1d) follows HAI-15's intent but is not required by it.
- **HAI-16** triggers on a forced-choice pick with no cap.
  - The picker is not forced: typing a new name and leaving the face unnamed both remain available.
  - The cap of 5 is a design choice, well under the row's 100-item risk line.

### Face identity, not similarity, moves a human name

- Moving a name by embedding proximity would be the model naming people.
- `identity_uuid` is the face record itself. The attachment-plus-box fallback specifies the unique identifier that NAV-35 asks for, and it is validated on demo content before use.

### Amend ADR-003 instead of routing everything to the inbox

- After a reset, every named person would otherwise need a manual click (INT-13).
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

### 3. The service carries `roster_id` and labels across merge and split

Rejected. It would make the service a second writer of the binding (DATA-14, ADR-009 rule 1). WordPress re-links through the outbox instead.

### 4. Pick the successor by embedding similarity to the old group

Rejected. A model judgment would attach a human name without review. Face-record identity is exact.

### 5. Discard `cluster_not_found` as entity-gone (the TRIAGE0918-M-08 path)

Rejected. It silently drops a human name from the faces.

### 6. Send every stale reference to the inbox

Rejected as the default, because after a reset every named person would land in the inbox (INT-13). It remains available as the setting-off mode (INT-20).

### 7. A separate photos page per person

Rejected. Photos already live in the workspace, and a second surface would split the destination (NAV-19).

## Consequences

### Positive

- Names survive a re-analysis, and the four reported records resolve.
- The picker shows people, not machine artifacts.
- Every roster row and findings button leads somewhere.

### Negative

- **Data reset.** New WordPress columns and an anchor table mean a clean-slate reset of demo data. The four people must be re-named once.
- **Background mutation.** Automatic re-link is a background mutation. It needs status, Undo, a setting and an audit trail.
- **Service work.** Person-grain ranking changes the service's candidate query and the PHP mapper.

### Guardrails for the follow-on implementation task

- **Enums (sr-007).** New status values are backed enums: `stale_reference`, `auto_resolved`, `resolved_unlinked`, `superseded`, `name_source`, `label_source`.
- **No embedding similarity in successor code.** A test pins the resolver's inputs.
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
| WBTRUST-2 note | S5 card label "Name these faces" (rule 6) | — |
| CURUX-2 | Provenance columns and gate (1a, 1b); person-grain ranking (1c); service split flag (2g) | Step 0 |
| CURUX-3 | Stale references: anchors, resolver, re-link, Needs attention, copy, setting, fingerprint (rule 2) | Step 0; `act-review-rebind-faces` uses WBTRUST-2 S5, or the current labeling panel until S5 lands |
| CURUX-4 | Roster and workspace (rules 3, 4) | Step 0 |
| CURUX-5 | Findings rows (rule 5) | WBTRUST-2 S5, CURUX-3 |

Step 0 (rule 8) runs once as the first slice of whichever task starts first, and its result is recorded under CURUX-1.

## Open Questions

1. **Does a reset or purge re-mint `identity_uuid`?** This decides whether the 2c IoU fallback is the common path. Answered by Step 0.
2. **Does the member merger rewrite `cluster_uuid` for members of a preserved curated group?** This decides where in the merge the anchors are written. Answered in CURUX-3 slice 1.
3. **Which build is served, and is the GTMSMOKE-1 fix in it?**
4. **What writes "Person 1".."Person 5"?**
5. **What data is behind row 4?**
6. **Does an attachment-scoped recognition re-run exist for "Find faces again"?** If not, CURUX-3 adds one.

## References

- [ADR-003](ADR-003-wordpress-local-authority-and-durable-outbox-replay.md), [ADR-009](ADR-009-recognition-curation-refresh-and-person-review-projection.md), ADR-018 (`feature/idweave-1`)
- [WBTRUST-1](../tasks/v0.5.0/WBTRUST-1-review-queue-trust-task-plan.md), [WBTRUST-2](../tasks/v0.5.0/WBTRUST-2-cluster-curation-surface-task-plan.md), [WBTRUST-3](../tasks/v0.5.0/WBTRUST-3-naming-ux-and-persistence-task-plan.md), [WBTRUST-4](../tasks/v0.5.0/WBTRUST-4-request-budget-task-plan.md), [WBTRUST-5](../tasks/v0.5.0/WBTRUST-5-control-placement-task-plan.md)
- [CURUX-1 screens and map deltas](../assessments/current/curux-1-identity-curation-screens-2026-10-16.md)
- [Roster/workbench identity UX assessment](../assessments/current/roster-workbench-identity-ux-assessment-20260913.md)
- Canon v0.26.2 rows (`lexicons/`):
  - `interaction-ux.md`: `#cog-02`, `#form-09`, `#form-11`, `#hai-02`, `#hai-06`, `#hai-11`, `#hai-15`, `#hai-16`, `#hai-17`, `#int-01`, `#int-06`, `#int-07`, `#int-08`, `#int-10`, `#int-13`, `#int-20`, `#int-27`, `#nav-02`, `#nav-05`, `#nav-13`, `#nav-19`, `#nav-20`, `#nav-26`, `#nav-35`, `#perc-10`
  - `engineering.md`: `#agt-13`, `#data-14`, `#dom-03`, `#dom-06`, `#res-19`, `#rlse-04`
  - `ml-systems.md`: `#cal-02`, `#cal-10`, `#emb-06`
  - `accessibility.md`: `#a11y-04`, `#a11y-14`, `#a11y-21`
  - `writing.md`: `#writ-02`, `#writ-27`
