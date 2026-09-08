# GUIDEDQM-1 lane contract (frozen topology)

Source of truth for scope: `implementation-brief.json` in this directory (findings, copy catalog, acceptance tests T01–T26). This file freezes the *module boundaries* so lanes can run in parallel (GRPH-33, GRPH-39). Lanes edit only their owned paths. Nobody edits `copy.ts` by hand: run `python3 scripts/generate_guided_copy.py` after changing `copy.en.json` (only the reflow lane may change the catalog, and only to fix a verified placeholder mismatch).

## Lane DAG

```
N0 contract (this file, copy.ts, manifest)          [landed on feature/guidedqm-1]
 ├── N1 core   state.ts + state.test.ts               W01 (F02 F08 F10)      wave 1
 ├── N2 live   liveDescription.ts, useGuidedLiveDescription.ts,
 │             GuidedLiveDescriptionPanel.tsx + tests W03 (F01 F13)          wave 1
 N1 ──► N3 reflow  pages/guided/*.tsx (not the live panel), Entrance,
                   _guided-prototype.scss, page tests  W02+W05 (F03–F07 F09 F11 F14)  wave 2
 N3 ──► N4 uxmap   docs/ux-maps/guided-prototype.*, GuidedUxMap.contract.test.ts    wave 3
 N2,N3 ─► N5 verify GuidedA11y.test.tsx + verification-report.md  W04 (F06 F10 F12)  wave 3
 N4,N5 ─► N6 review gate (/wb-review-slice) then W06 evidence handoff
```
Critical path: N0→N1→N3→N5→N6. Cut vertices: N1, N3. N1 ∥ N2 share no data (live modules stop importing `./state`), so the edge between them is removed rather than serialised (GRPH-32).

## Contract A — core state module (`js/admin/guidedPrototype/state.ts`, owned by N1)

Split the current `GuidedScenario` into an immutable fixture and a mutable demo state:

- `GuidedScenario` (fixture): photo, page context (title, one-sentence context, `runDate`), `faces` (left/right crops), `persons` with reference images + credits, `samples: Record<GuidedDraftKey, string | null>` (`null` = fixture missing → `draftStatus = fixture_missing`), provenance. Keep existing exports `getGuidedPerson`, `getGuidedFace`, `GUIDED_PERSON_KEYS`, `GuidedPersonKey`, `GuidedFacePosition`, `GuidedDraftKey`, `GuidedFaceBox`, `GuidedGalleryPhoto`, `GuidedLabeledPerson`, `GuidedFace`, `GuidedProvenance`, `GuidedScenarioOrigin`, `GUIDED_SCENARIO_ORIGIN_LABELS`, `createGuidedScenario`.
- `GuidedDemoState` with exactly these fields (brief `state_machine.state_fields`, minus the four `live*` fields, which live in N2's hook and never enter this module):
- `activeStep`: enum initial `"context"` values ['context', 'names', 'draft', 'apply']
- `choices`: object initial `{"left": "undecided", "right": "undecided"}`
- `draftText`: string_or_null initial `null`
- `draftOrigin`: enum initial `"none"` values ['none', 'recorded_sample', 'visitor_edit']
- `draftStatus`: enum initial `"blocked"` values ['blocked', 'ready', 'fixture_missing']
- `draftVersion`: integer initial `0`
- `previewedVersion`: integer_or_null initial `null`
- `draftHistory`: array initial `[]` records ['revisionId', 'text', 'origin', 'choices', 'draftVersion']
- `pendingChoiceChange`: object_or_null initial `null`
- `appliedAltText`: string initial `"Two people at a film festival."`
- `applicationUndoStack`: array initial `[]` records ['previousAltText', 'appliedDraftVersion', 'sequence']
- `outcome`: enum initial `"not_finished"` values ['not_finished', 'applied', 'kept']
- `actionHistory`: array initial `[]` records ['event', 'sequence', 'scope', 'summary']
- `liveStatus`: enum initial `"unavailable"` values ['unavailable', 'idle', 'pending', 'succeeded', 'failed', 'timed_out', 'stopped']
- `liveRequestToken`: string_or_null initial `null`
- `liveText`: string_or_null initial `null`
- `liveContractVerified`: boolean initial `false`
- Enums as `as const` objects + union types (sr-007): `GUIDED_STEP`, `GUIDED_NAME_CHOICE`, `GUIDED_DRAFT_ORIGIN`, `GUIDED_DRAFT_STATUS`, `GUIDED_OUTCOME`.
- Pure transition functions, one per brief event, `(state, scenario?, ...args) => GuidedDemoState`, never mutating input:
  `createGuidedDemoState`, `selectGuidedStep`, `chooseGuidedName(state, scenario, position, choice)`, `confirmGuidedChoiceReplacement(state, scenario)`, `cancelGuidedChoiceReplacement`, `editGuidedDraft(state, text)`, `previewGuidedDraft`, `keepGuidedCurrentAltText`, `applyGuidedDraft`, `undoGuidedApplication`, `restoreGuidedRevision(state, revisionId, mode: 'full' | 'copy_only')`, `resetGuidedDemoState`, `retryGuidedFixture(state, scenario)`.
- Guard functions with these exact names and semantics:
- `namesDecided` := choices.left != undecided AND choices.right != undecided
- `canPreview` := namesDecided AND draftStatus == ready AND draftText != null AND trim(draftText).length > 0
- `canApply` := canPreview AND previewedVersion == draftVersion AND draftText != appliedAltText AND pendingChoiceChange == null
- `canUndo` := applicationUndoStack.length > 0
- `canStartLive` := liveContractVerified AND liveStatus != pending
- `canRestoreRevision` := revision.choices == choices; otherwise offer copy-only recovery with the stated warning
- Selectors: `guidedDraftKeyFor(choices)`, `guidedSampleFor(scenario, choices)`, `guidedNameCoverage(scenario)` (bundled reference counts, never invented), `guidedStepIndex(step)`.
- Transitions (verbatim from the brief; tests must cover every guard and every forbidden clause):
- **start_or_select_step** — guard: Always allowed for inspection
  - updates: Set activeStep to requested step; scroll/focus its heading without changing router hash
  - forbidden: Do not mutate choices, drafts, applied text, or live state; Do not mark unperformed decisions as complete
- **choose_name_option** — guard: Requested choice differs; pendingChoiceChange == null
  - updates: If draftOrigin == visitor_edit, store only the proposed choice in pendingChoiceChange and ask for confirmation; Otherwise set the choice; if namesDecided resolve the matching recorded sample, increment draftVersion and invalidate previewedVersion; When either choice is undecided, candidate remains blocked; Set outcome=not_finished; do not change appliedAltText
  - forbidden: Never overwrite an edited draft without confirmation; Never call a roster write or recognition endpoint
- **confirm_choice_replacement** — guard: pendingChoiceChange != null
  - updates: Append the current draft with its old choices to draftHistory before any replacement; Apply pending choice, clear pendingChoiceChange, resolve the matching recorded sample; Increment draftVersion; clear previewedVersion; set outcome=not_finished; Keep appliedAltText and applicationUndoStack unchanged
  - forbidden: Never relabel a human-written fallback as a recorded model run
- **cancel_choice_replacement** — guard: pendingChoiceChange != null
  - updates: Clear pendingChoiceChange, retain all existing choices and draft text, return focus to the originating control
  - forbidden: No draft version or applied text change
- **edit_draft** — guard: namesDecided AND draftStatus == ready
  - updates: Set draftText to the textarea value, draftOrigin=visitor_edit, increment draftVersion, clear previewedVersion; set outcome=not_finished
  - forbidden: No separate hidden savedDraft version; No word filtering, entity insertion, truncation or automatic save to WordPress
- **preview_draft** — guard: canPreview
  - updates: Set previewedVersion=draftVersion; set activeStep=apply; show exact candidate text beside appliedAltText
  - forbidden: No rewriting during preview
- **apply_draft** — guard: canApply, checked inside handler as well as in the UI
  - updates: Push previous appliedAltText to applicationUndoStack; Set appliedAltText=draftText verbatim; bind it to the demo-image alt; Set outcome=applied; add browser-local history event and one short status announcement
  - forbidden: No WordPress media, roster, settings or user-preference write; No network or live generation dependency
- **undo_application** — guard: canUndo
  - updates: Pop one application record; restore previousAltText; update demo-image alt; announce restoration; Keep draft/choices; log the undo; derive current completion display from the restored image
  - forbidden: Do not alter the evidence image alternative or a server record
- **keep_current_alt_text** — guard: Always allowed, including a blocked/missing sample
  - updates: Set outcome=kept; keep appliedAltText unchanged; preserve draft text; log a local event; show completion summary
  - forbidden: Do not label this as rejection training or send server feedback
- **restore_draft_revision** — guard: canRestoreRevision
  - updates: Archive the current manual draft if present; restore revision text as visitor_edit; increment draftVersion; clear previewedVersion; set outcome=not_finished
  - forbidden: Do not restore old choices silently; Do not apply the restored draft automatically
- **initialize_live_availability** — guard: The existing adapter contract has been checked, or its status is unknown
  - updates: Set liveContractVerified only from the verified integration configuration, not a visitor toggle; Use idle when verified and no request is pending; otherwise unavailable
  - forbidden: Do not probe with a billable request merely to render the panel; Do not infer capability from old planning documents or the presence of a button
- **open_live_panel** — guard: Always allowed
  - updates: Disclose independent live scope and availability
  - forbidden: Do not start requests or provision GPU work
- **start_live_test** — guard: canStartLive
  - updates: Assign a new request token; clear previous live text; set pending; call the verified existing description endpoint once
  - forbidden: No dependency on choices or completed steps; No mutation of draftText, appliedAltText, applicationUndoStack or server roster; No new endpoint or payload fields invented from this brief
- **live_response** — guard: Response token equals current token AND liveStatus == pending
  - updates: Set succeeded only for a nonempty valid result; otherwise failed; set liveText only in the read-only live panel
  - forbidden: Never copy into the demo candidate automatically; Ignore obsolete responses
- **stop_waiting_or_timeout** — guard: liveStatus == pending
  - updates: Stop local polling/request wait; invalidate the request token; use stopped or timed_out state and accurate copy
  - forbidden: Do not claim the server job was cancelled without an acknowledged server cancellation
- **confirm_reset** — guard: User confirms; no implicit reset on section navigation
  - updates: Restore core initial state and empty local histories; invalidate request token; stop local waiting; retain only verified live availability configuration
  - forbidden: Never change WordPress media; Do not claim remote work was stopped merely because local state reset
- **reload_page** — guard: Browser reload
  - updates: Core demo state returns to initial values; server data is not changed
  - forbidden: No localStorage/sessionStorage persistence that contradicts the promised reload reset
- Zero imports from `../api/*`, no `fetch`, no `window` access. `state.test.ts` proves it (T01, T18).

## Contract B — optional live module (owned by N2)

- `useGuidedLiveDescription({ mediaId, client? })` and `GuidedLiveDescriptionPanel` props `{ mediaId: number | null; client?: GuidedLiveDescriptionClient; onWaitingChange?: (waiting: boolean) => void }`. **No `scenario` prop, no import from `./state`.** Face choices are not a prerequisite (F01, W03); the panel discloses the separate server roster with `live.names`.
- Statuses map to brief `liveStatus` values: unavailable | idle | pending | succeeded | failed | timed_out | stopped. `unavailable` when `mediaId === null` or the endpoint contract is not verified (`live.request_unverified`). Keep the existing deadline math, run-generation fencing, stale-response protection, and server-acknowledged cancel semantics; render every string from `guidedCopy(...)`.
- Panel is closed by default inside a `<details>` whose summary is `live.title`; `data-testid="guided-live"` and `guided-live-status` preserved. Never calls `/apply`; never writes WordPress media; live text is read-only (`live.output_label`).
- Reset is driven by the parent bumping React `key`; the hook must cancel an owned in-flight run on unmount.

## Contract C — page composition (owned by N3, reflow)

- Order: compact_intro, guide, context, names, draft, apply, outcome, local_history, optional_design_notes, optional_live_test. Section ids preserved: guided-section-understand, guided-section-face, guided-section-identity, guided-section-review, guided-section-apply.
- Navigation buttons call `selectGuidedStep` and `focusGuidedSection`; they never change `location.hash` (route `#/guided-prototype` stays).
- Native `<fieldset><legend>` radio groups per face, no preselection, test ids `name-choice-left` / `name-choice-right`.
- Mount `<GuidedLiveDescriptionPanel key={resetVersion} mediaId={liveMediaId} onWaitingChange={setLiveWaiting} />` last; show `reset.active_live_note` in the reset dialog when `liveWaiting`.
- All visible strings from `guidedCopy(...)`; delete duplicated intros and the Coachella aside; keep case-study anchor and CREDITS.
- Test hooks:
- `guided-demo-root` — add_on_main
- `guided-demo-stepper` — add_on_numbered_guide
- `name-choice-left` — add_on_left_fieldset
- `name-choice-right` — add_on_right_fieldset
- `guided-candidate` — preserve_existing
- `guided-page-feedback` — preserve_existing
- `guided-live` — preserve_existing
- `guided-live-status` — preserve_existing
- `demo-applied-image` — new_distinct_preview_image
- `demo-apply` — add_to_local_apply_button
- `demo-undo` — add_to_undo_button
- `demo-outcome` — new_outcome_container

## Contract D — verification (owned by N5) and UX map (owned by N4)

- N5 adds `pages/guided/__tests__/GuidedA11y.test.tsx` (keyboard order, focus after choice/restore/dialog, single polite status per event, distinct evidence vs applied image) and writes `verification-report.md` here with run / not-run truthfully separated. N5 may not edit components; it records findings instead.
- N4 rewrites `apps/prototype-wp-alt-context/docs/ux-maps/guided-prototype.md` + `.uxmap.json` to the shipped topology and keeps `GuidedUxMap.contract.test.ts` green.

## Test commands (run on the remote VM; never on the host)

- N1: `cd apps/prototype-wp-alt-context && npx vitest run js/admin/guidedPrototype/state.test.ts js/admin/guidedPrototype/credits.contract.test.ts`
- N2: `cd apps/prototype-wp-alt-context && npx vitest run js/admin/guidedPrototype/liveDescription.test.ts js/admin/guidedPrototype/useGuidedLiveDescription.test.tsx js/admin/pages/guided/__tests__/GuidedLiveDescriptionPanel.test.tsx`
- N3/N5: `cd apps/prototype-wp-alt-context && npx vitest run js/admin/guidedPrototype js/admin/pages/guided && npx tsc --noEmit --project tsconfig.type-check.json`
- N4: `cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/guided/__tests__/GuidedUxMap.contract.test.ts`

## Non-goals for every lane

No backend changes, no `/practice` route, no new endpoints, no idempotency-key work (separate slice), no `sync-demo.sh`, no push/merge, no AI attribution trailers, no edits outside owned paths.
