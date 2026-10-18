# Workbench UX-Map Evaluation — review queue, curation, controls (2026-10-15)

> **Metadata**
>
> - **Date**: 2026-10-15
> - **Author**: Claude (Sonnet 5.5)
> - **Scope**: `/wp-admin/admin.php?page=alt-context-dashboard#/workbench` (Scan tab, Review Suggestions, cluster panels, media library pane), plus `post.php?post=107&action=edit`
> - **Canon**: Heuristics canon v0.26.2 (pinned copy). Lenses requested: Tufte corpus (VIZ), microinteractions + aesthetics (INT/PERC), grid layout (LAY), interactivity lexicons (INT/NAV/HAI).
> - **Umbrella**: [workbench-curation-trust-scope.md](../../scopes/workbench-curation-trust-scope.md)
> - **Status**: Draft for implementation planning

## Method and limits

Input: the operator's DOM snippets and console log (R1–R14 in the scope), `docs/ux-maps/workbench-review-queue.md` and `workbench-2pane.uxmap.json` as the intended behavior, and the component code named per row.
**Not done:** no live browser session. No Chrome automation tier was available to the planner and the computer-use browser tier is read-only, so spacing, contrast, focus order and animation were not measured on screen. Every "Verify in browser" below is an acceptance step in the owning plan. Severity: **S1** blocks the operator's job or states something false; **S2** degrades it; **S3** polish.

## Findings

### A. Interactivity and trust (INT / NAV / HAI)

| # | Finding | Evidence | Canon | Sev | Task |
| --- | --- | --- | --- | --- | --- |
| A1 | A match percent renders with a missing reference image. | R1; `SuggestionCards.tsx` `matchPercent` unconditional; avatar `data-avatar-state="data-missing"` | HAI-01 evidence before label; HAI-08 uncertainty at decision granularity (a bare percentage is the failure trigger); CAL-02 unknown is a valid result; CAL-11 quality gate | S1 | WBTRUST-1 |
| A2 | Approve is disabled behind a toggle whose content cannot satisfy it (only face 1 has an image). | R2; `storedFaceReviewGate.ts`, "Image unavailable" text for faces 2..N | HAI-17 every reference the store holds (present them); FORM-09 responsive enabling; HAI-21 identity evidence in one action | S1 | WBTRUST-1 |
| A3 | A 34 % candidate is on the default list. | R3; suggestions created down to effective floor 0.30; queue only flags below `LOW_CONFIDENCE_THRESHOLD` 0.6 | CAL-02; HAI-08; PERC-07 do not habituate alarms (a caution flag on routine cards stops being read) | S2 | WBTRUST-1 |
| A4 | Cluster panel is inspect-only: one × per face, a confirm dialog per removal, no name, no accept. | R4; `ClusterReviewPanel.tsx`; map text "remove an incorrect face with confirmation, and return" | HAI-13 user is the last error detector (they need a way to finish); NAV-07 escape hatch; INT-13 run the likely path with recovery; INT-04 item tools reach every input | S1 | WBTRUST-2 |
| A5 | Name picker exposes "Group"/"Person" for the same name. | R9; `NameFaceControl.tsx` `sourceBadgeLabel` | PERC-10 least useful feedback; INT-22 explain the result (say what will happen, not which table it came from) | S2 | WBTRUST-3 |
| A6 | Suggestion-load failure reads as a fault and sits beside the primary field. | R9; `NameFaceControl.tsx` `suggestionsError` | FORM-05 inline actionable errors; PERC-07; RES-06 queue-and-retry, answer fast | S2 | WBTRUST-3 / 4 |
| A7 | Save success depends on a refetch that 429s. | R10, R14; `useClusterMutations.ts` `invalidateQueries()` | INT-10 status–predict–stop; INT-22; RES-13 | S1 | WBTRUST-3 |
| A8 | Frequent command (Describe) shares a row with configuration prose; GPU wording appears in four places. | R6; `BulkDescribeCta`, `BulkDescribeProgress`, `ActivityStatusStrip`, `GpuTierStatus` | INT-13; NAV-06 frequency elevates chrome; INT-23 limit and mark modes; COG-07 just-in-time help | S2 | WBTRUST-5 |
| A9 | "Details" opens a region mounted after the layout, with a second trigger beside it. | R12; `ActivityStatusStrip.tsx`, `AdvancedDrawer.tsx`, `WorkbenchPage.tsx` | NAV-19 keep related work adjacent; PERC-01 proximity binds meaning; NAV-38 co-locate task steps | S2 | WBTRUST-5 |
| A10 | Pagination only below a long table. | R8; `MediaSelection.tsx` footer | NAV-21 bound lists for return trips (paging, footer access) | S2 | WBTRUST-5 |
| A11 | Seeded fixture captions carry "Drafted by AI". | R13; `seeded_adapter.py` `_FIXTURE_POOL`; `QueueDraftCell.tsx` | HAI-05 imperceptible AI is not ethical; PROV-01 every output walks back to its evidence; ATTRIB-02 captions explain or falsify identity; EVAL-16 upstream failure counts against the end-to-end metric | S1 | WBTRUST-7 |
| A12 | A missed face is silent. | R11 | CAL-02; CAL-10 inconclusive is a valid human output; EVAL-19 | S2 | WBTRUST-8 |

### B. Tufte lens (VIZ)

| # | Finding | Evidence | Canon | Sev | Task |
| --- | --- | --- | --- | --- | --- |
| B1 | The card repeats one quantity in three places: "100 % match", "(10 faces)", "9 more faces not shown", "Stored face N of M". | R2, R3 | VIZ-33 remove optional scalar repetition; VIZ-27 remove content-empty decoration | S3 | WBTRUST-1 |
| B2 | The evidence (candidate vs stored faces) is not shown as one comparison; the reference is one thumbnail plus text. | R2, R3 | VIZ-23 show the evidence path; VIZ-15 coordinate multiple views; VIZ-16 compact the visual query | S1 | WBTRUST-1 |
| B3 | The 47-face grid has no per-point names; a face cannot be traced to its photo without opening it. | R4 | VIZ-25 restore required point names (filename/date on focus/hover, not always-on) | S3 | WBTRUST-2 |
| B4 | Selecting faces to exclude does not update any summary view (count, accept label). | R4 | VIZ-15 coordinate multiple views | S2 | WBTRUST-2 |
| B5 | Overlay chip is centred on the bbox: the annotation occludes the data. | R7; `FaceOverlayLayer.tsx` `controlStyle` | VIZ-12 layered transparency discipline; PERC-01 | S1 | WBTRUST-6 |
| B6 | Flags and disclosure prose compete with the faces for attention on the card and in the footer. | R3, R6 | VIZ-27; VIZ-17 focus plus context | S3 | WBTRUST-1 / 5 |

### C. Microinteractions and feedback (INT / PERC)

| # | Finding | Canon | Sev | Task |
| --- | --- | --- | --- | --- |
| C1 | Trigger → rules → feedback for "Yes": disabled with a hint under the button, not at the point of gaze; the toggle that unlocks it sits below. | PERC-05 fovea-first feedback; PERC-10; INT-22 | S2 | WBTRUST-1 |
| C2 | Save has no immediate confirmation independent of the refetch. | INT-10; A11Y-21 announce status | S1 | WBTRUST-3 |
| C3 | Per-card errors during a rate-limit window instead of one wait state with a countdown. | INT-08 wait state and cancel; PERC-07 | S2 | WBTRUST-4 |
| C4 | Removal confirm dialog per face makes a 47-face clean-up 47 interruptions; the safe alternative (reversible exclude) does not exist. | INT-13; NAV-07 | S1 | WBTRUST-2 |
| C5 | Overlay chip hit area for small faces must stay ≥ 24 × 24 CSS px when the label moves out. | A11Y-14 target size | S2 | WBTRUST-6 |
| C6 | Focus management on "Details" depends on a distant panel; Esc returns focus to the drawer's own trigger, not the strip's button. | A11Y-13 focus not obscured; INT-28 | S2 | WBTRUST-5 |

### D. Grid and aesthetics (LAY)

| # | Finding | Canon | Sev | Task |
| --- | --- | --- | --- | --- |
| D1 | Card layout mixes the evidence region, score, flags and actions with no shared grid: the stored-face strip, the candidate and the action row do not align to one content-and-frame grid. | LAY-24 content-and-frame grid; LAY-21 layout–content boundary | S3 | WBTRUST-1 |
| D2 | Footer row hosts pagination, a button and two prose paragraphs with no group-level layout property (to confirm in browser how the paragraphs flow beside the button). | LAY-22 group-level layout property; LAY-24 | S3 | WBTRUST-5 |
| D3 | New styles must use `--acx-*` tokens and pair colour with an icon (sr-004). | UI-01 predefined scales only; UI-08 elevation system | — | all |

D2/D1 are reading from code and class names; confirm in browser before designing pixel values.

## Heuristic coverage not yet findable

No `GpuTierStatus` mount was found; if it is dead, A8 loses one surface (delete rather than restyle). The NAME review kind keeps its blind-judgment protocol (reveal-after-record) — WBTRUST-1 must not touch it; only the ASSIGN "Is this X?" card changes.

## Map maintenance

Source of truth for the 2-pane workbench is `apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.uxmap.json` (zones `z-lib-actions`, `z-lib-table`, `z-lib-inline-edit`; open question on bulk-describe cost preview) with the derived `workbench-2pane.md`; `workbench-identity-chips`, `workbench-operator-loop`, `gpu-operator-control` and `describe-gpu-tier` maps sit beside it. The hand-written `docs/ux-maps/workbench-review-queue.md` records the queue and cluster-panel jobs. Each implementing plan edits the JSON first, regenerates or hand-mirrors the `.md` (the renderer has a known version gap: never `json.dump`; an extra H2 breaks parity), and runs `make lint-ux-maps` (at this commit `render_ux_maps.py --check` alone prints "all UX-map artifacts are current (11 checked)"; the unicode-width and unit-test legs of the target were not run). Operator vocabulary is group / person / face; the banned-vocabulary sweep rejects cluster / identities / embeddings in map text.
