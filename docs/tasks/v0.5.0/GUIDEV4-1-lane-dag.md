# GUIDEV4-1 lane DAG: public guide copy, layout and trust fixes

Status: planning draft. Uncommitted and not approved. No lanes have been dispatched.
Blocked by B1 (model routing) and B2 (screens approval); see [Blockers](#blockers).

- Branch `feature/guidev4-1` at `684fb705b`, worktree `~/Development/context-alt-text-monorepo-guidev4-1`.
- App root: `apps/prototype-wp-alt-context`.
- Screens: [`GUIDEV4-1-proposed-screens.md`](./GUIDEV4-1-proposed-screens.md), in this folder and also uncommitted.
- Heuristics: <https://github.com/darce/heuristics-canon>. Cite rule IDs at use time and do not pin a version. Every lane brief carries this link, not pasted canon text.
- Handoff: task `GUIDEV4-1` in `context-alt-text-monorepo/.task-state/handoff.db`. Session `guidev4-1-assess-20260923` recorded decisions, blockers and findings UX-01 to UX-15.

## Import graph (codemap IMPORTS edges)

These edges set lane ownership. An edge exists only where data moves (GRPH-32).

```text
RecordedWalkthrough      ──► publicGuideCopy, state, Entrance, DescriptionReview, DesignNotes,
  (hub; the only cut        FaceMatchCard, FacesPanel, Outcome, PhotoFaces, PrototypeGuide,
   vertex, GRPH-05)         ResetDialog, SamplePhoto
GuidedPrototypeEntrance  ──► publicGuideCopy
GuidedDescriptionReview  ──► publicGuideCopy, reviewDrafts, state
GuidedFaceMatchCard      ──► publicGuideCopy, state            (renders the lightbox)
GuidedFacesPanel         ──► publicGuideCopy, state, GuidedPrototypeGuide
GuidedOutcome            ──► publicGuideCopy, state
GuidedSamplePhoto        ──► publicGuideCopy, state, GuidedFaceOverlay
GuidedResetDialog        ──► copy, state, GuidedPrototypeGuide
GuidedPrototypeGuide     ──► copy, publicGuideCopy, state
GuidedPhotoFaces, GuidedFaceOverlay ──► state
reviewDrafts ──► state ──► copy ◄── publicGuideCopy
js/guide/main.tsx        ──► RecordedWalkthrough, publicGuideCopy, publicGuideShell, index.css
GuidedPrototypePage      ──► RecordedWalkthrough, copy, GuidedLiveDescriptionPanel   (admin only)
```

No lane owns GuidedDesignNotes or GuidedLiveDescriptionPanel, and the public guide renders neither. DesignNotes appears only for `scope === 'admin'` (`RecordedWalkthrough.tsx:497-513`).

## Lane DAG

```text
W1  contracts: merge and freeze before W2 starts (GRPH-33, GRPH-39, CARD-01)
    [L1a copy]      [L1b state]      [L1c route/PHP]
        │   ╲          ╱   │                │
        ▼    ▼        ▼    ▼                │
W2  leaves: parallel, at most 3 lanes at once (GRPH-09)
    [L2a hero] [L2b names ★] [L2c review] [L2d photo] [L2e outcome+reset] [L2f style roots]
        │          │               │            │              │                 │
W3      │     [L3 guide wiring ★]  │            │              │                 │
        ▼          ▼               ▼            ▼              ▼                 ▼
W4  [L4 walkthrough hub ★]  serial; nothing else may touch the hub (GRPH-05)
        │
        ▼
W5  [L5 layout styles + uxmap + e2e 1440/390 + cleanup ★]  ◄── L1c
★ = critical path: L1a + L1b → L2b → L3 → L4 → L5 (GRPH-31)
```

Order of work with at most 3 lanes running (see [Monitoring](#monitoring)):

| Slot batch | Lanes | Why this order |
|---|---|---|
| 1 | L1a, L1b, L1c | The contracts go first. They have no shared files. |
| 2 | L2b ★, L2c, L2d | Start the critical-path leaf first, next to the two largest leaves. |
| 3 | L3 ★ (once L2b merges), L2a, L2e | L3 needs only L2b. |
| 4 | L2f | Style root causes. They do not depend on the new markup. |
| 5 | L4 ★ | Starts after every W2 lane and L3 have merged. |
| 6 | L5 ★ | Starts after L4 and L1c. |

## Lanes

All paths are relative to `apps/prototype-wp-alt-context`. A lane edits only the files it owns. Test commands run from the app root.

The worktree has no `node_modules` or `vendor/` yet. Install them on the host before verifying there, and expect the remote sandbox to lack them too (GUIDEV3-1 decision 10775).

| Lane | Owns | Does | Findings | Scoped test |
|---|---|---|---|---|
| L1a copy | `js/admin/guidedPrototype/copy.ts`, `publicGuideCopy.ts`, `publicGuideCopy.test.ts`, `copyCatalogParity.test.ts` | Plain-language copy at grade 7–8. Say "image description" (not "alt text"), explained once. No "draft", "roster", "prototype" or percentages. Buttons say what they do. Rewrite the unchanged-text error. Repurpose `entry.start.public` and add `nav.leave.public`. The H1 change waits on B2. | UX-09, UX-10 | `npx vitest run js/admin/guidedPrototype/publicGuideCopy.test.ts js/admin/guidedPrototype/copyCatalogParity.test.ts js/admin/__tests__/banned-vocabulary.test.tsx` |
| L1b state | `js/admin/guidedPrototype/state.ts`, `reviewDrafts.ts`, `state.test.ts` | One name answer per photo, including "Leave unnamed". Match strength in words; `formatGuidedSimilarity` stops being user-facing. Expose the anchor flag so the UI never calls a self-match "Strong". Show the outcome only when both photos are done. Record where the 0.6 threshold comes from. | UX-03, UX-04, UX-12, UX-13 | `npx vitest run js/admin/guidedPrototype/state.test.ts` |
| L1c route/PHP | `src/public/class-public-guide-route.php`, `src/public/templates/public-guide.php`, `tests/Unit/PublicGuideRouteTest.php` | Page `<title>` and meta description in the new wording. | P2 | `composer test -- --filter PublicGuideRouteTest` (the worktree has no `vendor/` yet) |
| L2a hero | `js/admin/pages/GuidedPrototypeEntrance.tsx`, `js/guide/__tests__/public-boundary.test.tsx` | Two-column hero from 60em up: heading column up to 38em, then "What you'll do" steps 1–3. Start moves focus to the first question. | UX-11 | `npx vitest run js/guide/__tests__/public-boundary.test.tsx` |
| L2b names ★ | `js/admin/pages/guided/GuidedFaceMatchCard.tsx`, `GuidedFacesPanel.tsx`, `GuidedFaceOverlay.tsx`, `GuidedPhotoFaces.tsx`, plus their four `__tests__` files | Name rows per photo, each at least 44px tall. The weak-match warning says what to do. The anchor face reads "started the saved group", not "Strong". Lightbox markup: the photo being checked comes first, reference photos 2-up at equal size, credits visible, a Close button at least 44px. Escape and focus return already work (lines 99–109 and 228–231); add tests so they stay that way. Move the pendingChoiceChange dialog out of GuidedFacesPanel (GUIDEV3 hazard). | UX-03, UX-08, UX-13, UX-14 | `npx vitest run js/admin/pages/guided/__tests__/GuidedFaceMatchCard.test.tsx js/admin/pages/guided/__tests__/GuidedFacesPanel.test.tsx js/admin/pages/guided/__tests__/GuidedFaceOverlay.test.tsx js/admin/pages/guided/__tests__/GuidedPhotoFaces.test.tsx` |
| L2c review | `js/admin/pages/guided/GuidedDescriptionReview.tsx`, `__tests__/GuidedDescriptionReview.test.tsx`, `__tests__/GuidedDescriptionReview.blastRadius.test.tsx` | Merge "Review and apply" into each photo card. Show the current and suggested descriptions side by side. Status, then Undo, with focus moved. Label AI text "Written by AI in advance". Show no buttons or errors until both people are answered. Drop the repeated small photo. | UX-02, UX-09 | `npx vitest run js/admin/pages/guided/__tests__/GuidedDescriptionReview.test.tsx js/admin/pages/guided/__tests__/GuidedDescriptionReview.blastRadius.test.tsx` |
| L2d photo | `js/admin/pages/guided/GuidedSamplePhoto.tsx`, `__tests__/GuidedSamplePhoto.test.tsx` | Remove the fixed caption shown before any decision. The photo's alt always equals the current description. The AltText.ai caption goes in a collapsed section marked "for comparison only". | UX-05 | `npx vitest run js/admin/pages/guided/__tests__/GuidedSamplePhoto.test.tsx` |
| L2e outcome+reset | `js/admin/pages/guided/GuidedOutcome.tsx`, `GuidedResetDialog.tsx`, `__tests__/GuidedOutcome.test.tsx` | Outcome: one line per photo plus the provenance line. Dialogs: "Keep my work"/"Start over" and "Keep my edits"/"Change the name", with focus on the safe button. | P1 | `npx vitest run js/admin/pages/guided/__tests__/GuidedOutcome.test.tsx` |
| L2f style roots | `js/guide/_theme-darce.scss`, `js/guide/_theme-darce-components.scss` | Remove the nested card borders at the source: the `// Cards` rule (lines 114–125), its `::after` (256–274) and the workspace layer. Stop the ≤768px override that shrinks `--acx-space-80` to 24px from shrinking the lightbox tiles. | UX-06, UX-07 | `npx vitest run js/guide/__tests__/publicCssBundle.test.ts` |
| L3 guide wiring ★ | `js/admin/pages/guided/GuidedPrototypeGuide.tsx` | Numbered headings inside each card replace the stepper strip. No auto-scroll. | UX-01 | `npx vitest run js/admin/pages/guided/__tests__/GuidedA11y.test.tsx` |
| L4 hub ★ | `js/admin/guidedPrototype/RecordedWalkthrough.tsx`, `RecordedWalkthrough.test.tsx`, `js/guide/__tests__/main.test.tsx` | Remove the stepper and "Hide steps". Mount the moved dialog. Wire per-photo state and outcome gating. Use `guideStepsForScope`, not the scope-blind `GUIDE_STEPS`. | UX-01, UX-02 | `npx vitest run js/admin/guidedPrototype/RecordedWalkthrough.test.tsx js/guide/__tests__/main.test.tsx` |
| L5 finish ★ | `js/admin/styles/components/_guided-prototype.scss`, `_guided-face-overlay.scss`, `js/guide/public-guide.scss`, `docs/ux-maps/public-guide.uxmap.json`, `js/admin/pages/guided/__tests__/GuidedUxMap.contract.test.ts`, `tests/e2e/evidence/public-guide.spec.ts` | Layout for the new markup: hero grid, side-by-side review, one 16px mobile gutter, lightbox tiles about 159px 2-up at 390px wide. Drop the `guided-candidate` uxmap reference. Playwright checks at 1440×900 and 390×844. Final `npm run check`. | UX-06, UX-07 | `npx vitest run js/admin/pages/guided/__tests__/GuidedUxMap.contract.test.ts` and `npm run e2e:public-guide` (on the host) |

## Monitoring

Remote lanes run on codex-remote with `gpt-6-luna`, effort `max`, `speed="fast"` (service tier `fast`). Do not swap in another model unless the user approves it (CARD-29, AGT-13).

1. **Preflight each lane:** `offload_preflight(agent="codex-remote", model="gpt-6-luna", reasoning_effort="max", speed="fast", token_budget=…, worktree_path=<lane worktree>)`. A refusal stops that lane (P16, AGT-10).
   - Never set `WORKBAY_REMOTE_SANDBOX_PREFLIGHT_OK` or `WORKBAY_REMOTE_WRITABLE_ROOTS_PREFLIGHT_OK`. `.task-state/guidev3-pass.py` sets both and pins gpt-5.6-luna, so do not copy it as-is.
2. **Before every pass,** re-post the brief with `dispatch_lane_work(start_worker=False, include_context_packet=True, context_targets=<owned files>)` (GUIDEV3 decision 10775: a refused pass uses up the brief).
3. **One pass per lane:** `run_offload_pass(timeout_seconds=1800, max_review_cycles=1, pass_id=f"{dispatch_id}-p1")`. Avoid `dispatch_wave` with role=review, because the luna row only has the implement role. Save a continuation packet naming the pass_id and dispatch_id before any wait that could outlive the session (AGT-07, GRPH-29).
4. **Waiting:**
   - Use a bounded `await_offload_pass(es)` with one wait window per call. No poll loops and no background monitors (RES-02, FM-08).
   - A pass that stays silent past its window is a failure (OBS-08).
5. **Handling outcomes:** branch on the typed outcome together with `commit_landed` and `failed_stage` (AGT-21).
   - If `commit_landed` is true, send the commit to the gate. Do not re-dispatch.
   - If two `self_verify_failed` results come in a row on the same lane, stop that lane (RES-15, CARD-09). Re-run preflight and fix the environment before trying again.
   - If the remote sandbox has no `node_modules` (npm EAI_AGAIN), run the scoped test on the host.
6. **Frontier:**
   - At most 3 lanes at once, and 2 while a gate review is running (GUIDEV3 decisions 10774 and 10781).
   - `admission_deferred` can be retried after memory pressure drops. `admission_refused` means wait for the host to recover.
7. **Gate:**
   - Run `/wb-review-slice`, then `/wb-auto-fix`, for each lane (RLSE-02, CARD-04, P17).
   - Ask the user before any merge.
   - Close the lane after it merges. A retired lane that still owns its worktree path blocks new dispatches (GUIDEV3 decision 10781).

## Lessons from earlier work

- GUIDEV3-1 decision 10774: a layered DAG over a file-ownership conflict graph, with the frontier kept at 2 to leave room for review.
- GUIDEV3-1 decision 10775:
  - Re-post the brief before each pass.
  - The remote sandbox had no `node_modules`, so verify on the host.
  - Move the pendingChoiceChange dialog out of GuidedFacesPanel.
  - `GUIDE_STEPS` ignores scope; use `guideStepsForScope`.
- GUIDEV3-1 decision 10785: the `.review` capsule clashed on merge; it is now gitignored.
- GUIDE2IMG-1 decision 10718: a lane could not wire the reducer or RecordedWalkthrough from outside its own files. That is why L4 is its own serial lane.
- MAINT-LANDING-20260908 decision 10725: saved similarities are Tribeca JT 0.894 and KP 1.0, and Coachella JT 0.701 and KP 0.567 (weak).

## Supersessions (need the user's approval, AGT-13 and CARD-05)

- Removing the stepper reverses GUIDEV3-1's v3-stepper design (decisions 10774 and 10775).
- A new H1 reverses the operator override `entry.title.public = "Who's in the photo belongs in the alt text."`.

## Blockers

- **B1, model routing.** Installed `mcp-workbay-orchestrator` 0.3.9 has no `gpt-6-luna` row, and its CLI pin is 0.153.4. It does support `max` effort and the `fast` tier for other rows.
  - Upstream commit `4f3ba52e15` adds `gpt-6-luna` and pins codex CLI 0.155.1. It is on `origin/main` but in no release: the latest tag is v0.1.68 and the package version is still 0.3.9.
  - Option (a):
    1. Cut a release that includes it: dry run first, then `FLAGS=--execute` once the user agrees.
    2. Refresh the consumer `.venv` and the uv tools.
    3. Put codex CLI 0.155.1 on the gate VM.
    4. Confirm with `offload_preflight`.
  - Option (b): the user names another model.
- **B2, screens approval.** The main trade-off: one name answer per photo means 4 answers instead of 2. The two supersessions above also need a yes.

## Rollback (RLSE-08)

Each lane merges as its own commit on `feature/guidev4-1`, so any lane can be reverted with `git revert` on its own. Nothing reaches `main` or the demo host without the user's go-ahead.
