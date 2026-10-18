# Task Plan — WBTRUST-3

> **Date:** 2026-10-15
> **Author:** claude (Sonnet 5.5)
> **Owning Epic:** none yet — umbrella scope [workbench-curation-trust-scope.md](../../scopes/workbench-curation-trust-scope.md)
> **Task ID:** WBTRUST-3
> **Target Branch:** feature/wbtrust-3
> **Base SHA:** 372a6413a7ae0eb71baa3566716546684bac5a58
> **Revision:** 1
> **Review Coverage Target:** frontend + PHP label service read; PHP edits only if S1, run on a build that already contains the rename-durability fix, still proves a server-side persistence defect
> **Depends on:** WBTRUST-4 merged (shared invalidation primitive; rate-limit-clean repro)
> **Executor:** `claude-remote` `claude-haiku-5-5`, effort `xhigh` for implementation and grunt work (operator order 2026-10-15). Brief each slice separately (1–3 files), inline the slice text plus codemap snippets; if the write-enabled remote Claude harness is denied or unavailable, record a blocker and ask the operator — no silent fallback to another model.
> **Prior art:** [scope](../../scopes/workbench-curation-trust-scope.md) (R9, R10, root causes 6–7), [UX-map evaluation](../../assessments/current/workbench-curation-trust-uxmap-evaluation-2026-10-15.md) (A5, A6, A7, C2), [GPUFLOW-3 plan](GPUFLOW-3-demo-triage-identity-gpu-lifecycle-and-unified-queue-task-plan.md) (cluster→person bind, I1), [workbench-identity-chips map](../../../apps/prototype-wp-alt-context/docs/ux-maps/workbench-identity-chips.md); semantic prior art: IDREBIND-1-W3-01 (`invalidateLabelSurfaces`), UXW2-3-R1-02 (roster gate on commit), GTMSMOKE-1 decision 16666 (rename durable-enqueue audit; `person_updated` ACK is a no-op), `PersonRenameReplayTest.php`, [roster-person-binding scope](../../scopes/roster-person-binding-scope.md), contract `docs/workbay/contracts/curation-sync-api.md`, E21-20 (name-suggestion query not refetched by retry handlers)
> **Carried findings (by ID only):** none recorded yet; query `review_findings(list, task_ref="WBTRUST-3")`

## WBTRUST-3. Naming — one option per person, non-blocking suggestions, saves that stick

Frontend paths are relative to `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/` unless stated.

## Objective

The name picker lists each person once, a failed suggestion load never competes with the primary field, and a saved name is visible immediately and persists to the media item.

## Problem Statement

Labelling `bea-burke_57b99d594f1b` (#106): the edit form shows "3 naming options" and "Could not load name suggestions." with Retry (Save name disabled). The list shows "Ellyn Heald" as a **Group** (60 % medium, with a reject ✕) and again as a **Person**, plus "Bea Burke" as a **Person** — "why group/person?". After assigning an identity: "it does not save to media item."

## Constraints

- Do not merge Person/Group on the server; the cluster→roster binding stays (scope Not-doing). The UI stops exposing the distinction.
- Preserve PR-16: a person hit renames, a group hit merges/accepts; collapsing the *row* must not collapse the *action*.
- Operator vocabulary: person, group, face. sr-004 tokens; status = colour + icon. sr-007 enums for source/phase values. sr-008 ≤ 8 params.
- Greenfield: schema changes (if S1 finds any) go directly in `001_identity_schema.py`.
- PHP tests via `composer test`; JS via `vitest run`; both on the remote VM lane.

## Workflow Principles

- RED persistence repro first (S1): do not "fix" a save path that is only losing a refetch.
- Show success from the mutation response; treat refetch as reconciliation (INT-10).

## Terminology

**Option** = one row in the name picker. **Survivor cluster** = the person's cluster that other groups merge into (`find_person_survivor_cluster_uuid`).

## Current State Analysis

(Symbols, not line numbers.)

- `NameFaceControl.tsx`: `sourceBadgeLabel(option)` returns "Person" (source person) or "Group" (source cluster) and feeds the option `aria-label`/`title` and a visible `acx-badge--source` span. `matchBandDisplay` prints band words (HAI-08). The text "Could not load name suggestions." renders from the `suggestionsError` prop with Retry.
- **Correction to the scope's root cause 6:** `buildNamingOptions.ts` already dedupes person-preferred, case-insensitively. The duplicate "Ellyn Heald" rows come from `selectClusterSuggestions` in `useClusterSuggestions.ts`: identity-projection rows (source `cluster`, group `NAMING_GROUP_SUGGESTED`, carrying `similarity`, `suggestion_id`, `suggestion_identity_id`) come first, then naming options; person rows always render ("persons never suppress a same-named cluster", FIX-5). Cluster-source rows are the merge/accept path; `resolveClusterMatchFromOptions` returns null for person hits so save renames instead of merging (PR-16). `mergeRosterCandidateOptions` merges roster-candidate options.
- PHP `src/api/services/class-cluster-person-bind-service.php` `bind_cluster_to_person` already merges into the person's survivor (`find_person_survivor_cluster_uuid`, `merge_into_person_survivor`, row lock `acx_bind_busy`), so collapsing to one row per name is semantically safe when a survivor exists.
- `class-cluster-label-service.php`: `update_cluster_label` has a proxy-to-service path and a local-projection path; `persist_local_person_for_label`, private `bind_persisted_person`. `class-media-identities-controller.php` reads the local projection once it has rows. Which path the fir site takes, and whether the media chip reads the updated label, is unverified.
- Save path: `utils/invalidateLabelSurfaces.ts` invalidates eight families per save; `useClusterMutations.ts` `invalidateQueries` wraps it — a 429 here is the leading "not saved" suspect.
- `useMediaIdentities.ts`: `refetchInterval` 3000 ms while `hasPendingClustering`, `retry` ≤ 2 with Retry-After, `staleTime` 15 s, a recovery latch. `useClusterRosterCandidates.ts`; `useClusterSuggestionsLoader.ts` single-id `identityBatch` query with `initialData` from the batch cache, `staleTime` = `IDENTITY_BATCH_STALE_MS`, `retry`, `isError`.
- Tests: `buildNamingOptions.test.ts`, `NameFaceControl*.test.tsx`, `useClusterLabelMutations.test.tsx`, `useClusterMutations*.test.tsx`; plugin PHP tests for the label service.
- Rename durability is already addressed on `main`. By contract the backend `person_updated`/`person_created` operations are no-op acknowledgements; a rename persists through the WP cluster-label enqueue (`Api::update_person()` → `enqueue_bound_cluster_label_updates`), proven by `tests/Unit/PersonRenameReplayTest.php` (rename durable enqueue, conflict replay freshness, causal batch with real CAS). The PHP served on :10028 predates that fix (scope Step 0), so the operator's "does not save to media item" may be the stale deployment.
- Already on `main` from the parallel FIR-UI track: `NameFaceControl` none-abstention, `useClusterRosterCandidates`, optional-read budgets in `useClusterSuggestions`/`useClusterSuggestionsLoader`, `useClusterMutations` failed-read budget, `PersonCommitControl` busy-candidate handling, `ClusterLabelingPanel` hanging-closest budget. Tests: `useClusterSuggestions.optionalReadBudget`, `.rosterRecovery`, `useClusterMutations.failedReadBudget`, `NameFaceControl.noneAbstention`, `ClusterLabelingPanel.hangingClosestBudget`. Read them before S3 and S4: a failure that no longer blocks the picker on `main` is not a defect to fix again.
- Roster may be empty while cluster labels exist (roster-person-binding scope), which is why both sources exist; S2 hides the distinction in the UI without removing either source.

## Target Outcome

- The picker shows "Ellyn Heald" once, with face count or band words (no "Group"/"Person").
- A suggestion-load failure is a quiet inline note with "Try again" below the field; typing a new name and Save name still work.
- Save shows a `role="status"` "Saved" within 1 s from the mutation response; after reload the media row chip carries the name.

## Context Loading

`NameFaceControl.tsx`, `buildNamingOptions.ts`, `useClusterSuggestions.ts`, `useClusterSuggestionsLoader.ts`, `useClusterMatchAction.ts`, `useClusterLabelMutations.ts`, `useClusterMutations.ts`, `utils/invalidateLabelSurfaces.ts`, `hooks/useMediaIdentities.ts`; PHP `class-cluster-label-service.php`, `class-cluster-person-bind-service.php`, `class-media-identities-controller.php`. Canon (v0.26.2): INT-10, INT-22, FORM-04, FORM-05, PERC-10, PERC-07, RES-06, RES-13, HAI-08, A11Y-21.

## Contract and Boundary Impact

- None expected. If S1 shows the local-projection path omits the media-row update, the fix is in `class-cluster-label-service.php` and pins a PHP test; contract docs change only if the response shape changes.
- **Open decision:** none for the operator; the collapsed row's action routing is settled in S2 from `useClusterMatchAction`.

## Proposed Solution

Collapse suggestion + roster rows into one option per canonical person keyed by lower-cased trimmed name, keeping the suggestion evidence (`similarity`, `suggestion_id`) on that single row. Make suggestion loading advisory. Write the saved label into the query cache from the mutation response and reconcile with a deferred, targeted invalidation.

## Files and Surfaces to Change

Owned paths:

- `NameFaceControl.tsx`, `buildNamingOptions.ts`, `useClusterSuggestions.ts`, `useClusterSuggestionsLoader.ts`, `useClusterMatchAction.ts`, `useClusterLabelMutations.ts`, `useClusterMutations.ts`, `useClusterSaveStatus.ts`
- `utils/invalidateLabelSurfaces.ts` (consumes the WBTRUST-4 primitive), `hooks/useMediaIdentities.ts` (cache write only)
- PHP (conditional): `apps/prototype-wp-alt-context/src/api/services/class-cluster-label-service.php`, `class-media-identities-controller.php`, tests under `apps/prototype-wp-alt-context/tests/`
- Tests: `buildNamingOptions.test.ts`, `NameFaceControl*.test.tsx`, `useClusterLabelMutations.test.tsx`, `useClusterMutations*.test.tsx`, new `namePicker.collapse.test.tsx`
- Docs: `workbench-identity-chips` map text if the chip copy changes; hand-mirror JSON/`.md`; `make lint-ux-maps`

## Verification Strategy

- Unit: option collapse (same name via suggestion and person ⇒ one row, evidence kept, action routing unchanged); error-state rendering (field usable, Save enabled); save success writes cache before any refetch resolves.
- Persistence: RED test first (S1) reproduces "assign then reopen ⇒ name missing" with the refetch forced to 429.
- PHP: label-service test for both paths (proxy, local projection) asserting the media row reads back the label.
- Browser (fir tenant): label #106, reload, chip shows the name; picker lists each person once.
- `npm run typecheck`, `npm run lint`, `vitest run`, `composer test` on the VM.

## Slice Delivery

### Slice S1: persistence-repro

Find out whether "not saved" is a server defect or a lost refetch.
Closes: R10 (diagnosis). Canon: INT-10, EVAL-16.
Design decision (binding): first record the served build and whether it contains `enqueue_bound_cluster_label_updates` (scope Step 0); if not, request an operator redeploy and reproduce only after it. Adopt `PersonRenameReplayTest.php` as the existing server-side proof instead of writing a duplicate. Then reproduce on the fir tenant with the network panel open: record which `class-cluster-label-service.php` path ran, the PATCH/POST response, and the next `media-identities` read. RED tests: (a) JS — mutation succeeds, all refetches 429 ⇒ UI still shows "Saved" and the label; (b) PHP — only for a path `PersonRenameReplayTest.php` does not already cover: both label paths ⇒ media-identities returns the label.
Acceptance: decision names the path and the defect (stale deployment / server / client-refetch / combination); RED tests fail on the base SHA for that reason.

### Slice S2: one-option-per-person

Remove the Group/Person leak.
Closes: R9. Canon: PERC-10, INT-22, HAI-08.
Design decision (binding): `selectClusterSuggestions` merges projection rows into the matching person/roster option (same lower-cased trimmed name) so one row carries `similarity`, `suggestion_id`, `suggestion_identity_id`; `sourceBadgeLabel` and the `acx-badge--source` span are removed; the row shows the face count or band words. Action routing is unchanged: a row with a suggestion evidence id still routes to the merge/accept path, a bare person row to rename (PR-16). Internal `person:`/`cluster:` value namespacing stays. The reject ✕ stays on the evidence-bearing row.
Acceptance: fixture "Ellyn Heald (group, 60 %) + Ellyn Heald (person) + Bea Burke (person)" ⇒ two rows; both save paths exercised; `aria-label` has no "Group"/"Person" word.

### Slice S3: non-blocking-suggestions

A failed advisory call stays advisory.
Closes: R9. Canon: FORM-05, PERC-07, RES-06, A11Y-21.
Design decision (binding): start by reading the landed optional-read budget tests; implement only what they do not cover. Confirm the Retry handler refetches the name-suggestion query itself (prior finding E21-20 said it did not). `suggestionsError` renders an inline note below the field ("Suggestions are busy — you can still type a name. Try again") with rate-limit-aware copy when the WBTRUST-4 cooldown is open; Save name stays enabled; no `role="alert"` for rate-limit (a polite `role="status"`); retry reuses the loader's `retry`.
Acceptance: error fixture leaves the field and Save usable; cooldown fixture shows the busy copy and no alert role.

### Slice S4: read-your-writes

Make the save visible without a refetch.
Closes: R10. Canon: INT-10, INT-22, RES-13, A11Y-21.
Design decision (binding): on mutation success `setQueryData` updates `media.identities()` entries and the cluster label caches from the response; a `role="status"` "Saved" appears within 1 s and clears after 4 s; the existing `invalidateLabelSurfaces` helper (IDREBIND-1-W3-01; extend it, never add a second one) then reconciles through `runAfterCooldown`, narrowed to the families the save actually changed (WBTRUST-4 S4 primitive). If S1 found a server defect, fix it in the PHP service with its RED test first.
Acceptance: S1 RED tests green; request count for one save ≤ 1 write + ≤ 3 reads in 5 s.

### Slice S5: maps-and-browser-check

Document and verify.
Closes: R9, R10. Canon: INT-28, LAY-24.
Design decision (binding): update the identity-chips map for the new option and "Saved" copy (operator vocabulary only), hand-mirror the `.md`, run `make lint-ux-maps`; browser walk: label #106, reload, chip persists.
Acceptance: map lint green; walk recorded in the decision; slice-complete decision per template.
