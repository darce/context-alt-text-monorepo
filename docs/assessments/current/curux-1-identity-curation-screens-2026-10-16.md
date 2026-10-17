# CURUX-1 — current vs target screens (ux-map iterations 1–2)

Map SSOT: `apps/prototype-wp-alt-context/docs/ux-maps/{roster-people,workbench-2pane,workbench-operator-loop}.uxmap.json`.
Vocabulary (map + UXP-4): person, face, face group. Never cluster, identity, topology, phase, payload in copy.
Iteration rule: each target names the map screen/zone/action it adds or changes; critique runs on the target deltas.
Decision record: [ADR-019](../../adrs/ADR-019-person-anchored-curation-surfaces.md). The maps stay at shipped state; slice 1 of each follow-on plan applies its deltas below to the real map and re-runs `make lint-ux-maps`.

---

## S-A. Name a face — `workbench-2pane/workbench-control/z-name-curate` (NameFaceControl)

CURRENT (operator report)
```
┌ Name this person ───────────────────────────────┐
│ [ Loading people…                         ▾ ]   │  disabled for seconds
│ (Save name)  disabled                           │
└─────────────────────────────────────────────────┘
        … later …
┌ Name this person ───────────────────────────────┐
│ [                                         ▾ ]   │
│  ┌──────────────────────────────┐               │
│  │ Person 1                     │  machine      │
│  │ Person 2                     │  auto-labels  │
│  │ Person 3   …   Person 5      │  shown as     │
│  └──────────────────────────────┘  people       │
└─────────────────────────────────────────────────┘
```

TARGET
```
┌ Name this person ─────────────────────────────────────┐
│ [ Type a name…                               ▾ ]      │  enabled at once
│  ┌ Closest named people ──────────────────────────┐   │
│  │ [◯◯◯] Keanu Reeves     12 faces                │   │  human-named people only
│  │ [◯◯◯] Werner Herzog     3 faces                │   │  ranked by similarity, ≤5
│  │ ── Other people (A–Z) ──────────────────────── │   │  rest of roster, typed filter
│  │     Emma Watson · Sophia Loren …               │   │
│  │  +  Add "Keanu R" as a new person              │   │
│  └────────────────────────────────────────────────┘   │
│ ⓘ Finding closest people…   (polite status, no lock)  │  loading = status line only
│ [Save name]                                           │
└───────────────────────────────────────────────────────┘
```
Deltas
- z-name-curate states: `loading` = suggestions pending (input stays enabled; create-new disabled until the roster list settles, UXW2-3 race); new state `empty` = "No named people yet — type a name".
- Option source: human-named people only (roster persons and human-confirmed labels); machine auto-labels and reserved labels never become options.
- Order: similarity rank (people-grain, max over that person's faces, UXW2-5), at most 5, then the alphabetical remainder; no re-sort of the ranked block while open (NAV-02). Below the suggestion floor a person is not ranked (CAL-02).
- Each ranked option shows up to 3 of that person's faces closest to this group, plus the face count (HAI-17: several references, not one); A–Z rows show the name and count only. No match score or band word beside a name (iteration 2: a verdict word beside a name is a model same-label shown before the operator compares faces; HAI-15 spirit).
- Owner: WBTRUST-3 (S2/S3) absorbs this; ADR-019 adds the curated-only and ranking rules.

---

## S-B. Conflict detail — `workbench-2pane/workbench-conflicts/{z-conflict-list,z-conflict-detail,z-conflict-actions}`

CURRENT
```
┌ Conflicts (4) ─────────┬ Conflict Detail ─────────────────────────────┐
│ ▸ Keanu Reeves         │ compound topology conflict … Phase 4         │
│   cluster_not_found    │ keep-local only                              │
│ ▸ Emma Watson          │ Machine payload                              │
│ ▸ Sophia Loren         │ { cluster_uuid: b274…, reason:               │
│ ▸ Werner Herzog        │   cluster_not_found }                        │
│                        │ Local payload { cluster_uuid, label:         │
│                        │   "Keanu Reeves", acx_auto_attempts: 1 }     │
│                        │ No resolution actions are available.         │
└────────────────────────┴──────────────────────────────────────────────┘
```

TARGET (the single-pure-successor case never reaches the inbox: it re-links with a status line and Undo)
```
┌ Needs attention (1) ───┬ Keanu Reeves ─────────────────────────────────┐
│ ▸ Keanu Reeves         │ The face analysis was rebuilt, so the faces   │
│   name not re-applied  │ you named "Keanu Reeves" moved to new face    │
│                        │ groups. Your name is kept.                    │
│                        │                                               │
│                        │ Found 11 of 12 named faces in 2 new groups:   │
│                        │ [face][face][face][face] +7      (evidence)   │
│                        │                                               │
│                        │ [Re-apply "Keanu Reeves" to these 11 faces]   │
│                        │ [Review faces first]  [Keep name, unlinked]   │
│                        │ ▸ Technical details (operation id, codes)     │
└────────────────────────┴───────────────────────────────────────────────┘
```
Zero-successor case: "None of the faces you named are in the current analysis. Your name is kept in People." Actions: [Find faces again] (re-run recognition for the named photos) · [Keep name, unlinked]. Deleting the person stays in People.
Deltas
- New state on z-conflict-detail: `stale_reference` (service no longer has the face group) — distinct from a true concurrent edit (`version_conflict`).
- New actions: `act-rebind-person-faces` (primary), `act-review-rebind-faces`, `act-keep-person-unlinked`, `act-rescan-person-photos`. Payload JSON moves behind a closed disclosure.
- Auto path (ADR-019 rule 2d): exactly one successor face group, unbound and unnamed, holding only faces that were shown under this person → re-link with a status line and Undo. Two or more groups, extra unreviewed faces, another person's faces, or zero faces → this inbox screen.

---

## S-C. Roster people table — `roster-people/roster-shell/z-entries`

CURRENT
```
People
┌──────┬──────────────────────┬───────────────┬────────────┐
│ ◯32px│ Keanu Reeves      ✎  │ 2 face groups │ Merge into…│
│ ◯32px│ Emma Watson       ✎  │ 1 face group  │ Merge into…│
│ ◯32px│ Sophia Loren      ✎  │ 1 face group  │ Merge into…│
│      │                      │               │            │ ← row 4: empty
│ ◯32px│ Werner Herzog     ✎  │ 1 face group  │ Merge into…│
└──────┴──────────────────────┴───────────────┴────────────┘
avatar: button only when a person id exists; otherwise static
┌ section.acx-roster__review-cta ──────────────────────────┐
│ Unnamed faces are waiting. [Open Review Queue]           │ ← duplicate entry
└──────────────────────────────────────────────────────────┘
```

TARGET
```
People (5)                    [Review Queue (23)]   [+ Add person]
┌────────┬──────────────────────────────┬──────────────┬─────────┐
│ ┌────┐ │ Keanu Reeves                 │ 134 photos   │ ⋯       │
│ │ 72 │ │                              │ 2 face groups│         │
│ └────┘ │                              │              │         │
│ ┌────┐ │ Unnamed person               │ 6 photos     │ ⋯       │
│ │ 72 │ │ [Name this person]           │ 1 face group │         │
│ └────┘ │                              │              │         │
└────────┴──────────────────────────────┴──────────────┴─────────┘
row click target = avatar · name · photo count → person workspace (one destination)
⋯ = "More actions for {name}": Rename · Merge into… · Delete (INT-27)
```
Deltas
- Every rendered row is a person with a UUID. A row without a UUID is a projection defect, fixed at the projection writer and pinned by a test; it is never rendered as an inert row. An unnamed person (with or without faces) shows "Unnamed person", its face/photo count ("no faces" when zero) and a visible [Name this person]; Delete stays in the row menu. No dead end.
- Avatar: face crop at the existing 72 px size path (E21-15), always a button to the workspace, accessible name "Open {name}".
- Rename / Merge into… / Delete: one per-row menu named "More actions for {name}" (INT-27, A11Y-04), not icon-only buttons; the person workspace header carries a visible [Rename].
- `z-review-cta` removed; its entry moves to a header button "Review Queue (N)" beside Add person (one unscoped review entry per page; the label matches the admin menu entry "Review Queue" and the current link text, NAV-26).

---

## S-D. Person workspace — `roster-people/roster-person-workspace` (+ new zone `z-person-photos`)

CURRENT
```
┌ Person ─────────────────────────────────────────────────────┐
│ Keanu Reeves   Data status · Last refreshed · Record version│
│ Linked faces  [◯][◯][◯]                                     │
│ Photos  [Media 41] [Media 42] [Media 57]  → lightbox only    │
│ (Save person changes)                                       │
└─────────────────────────────────────────────────────────────┘
```

TARGET
```
┌ Keanu Reeves ──────────────────────── [Rename] [Merge into…] ┐
│ ┌──────┐  134 photos · 2 face groups · named by you          │
│ │ 120  │  [Review 3 suggested faces]                         │
│ └──────┘                                                     │
│ Photos with Keanu Reeves (134)                               │
│ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                          │
│ │ img ▣│ │ img ▣│ │ img  │ │ img  │   ▣ = face box on photo  │
│ └──────┘ └──────┘ └──────┘ └──────┘                          │
│ sunset.jpg   gala.jpg    set-04.jpg  premiere.jpg  (titles)  │
│ each tile: [View] (lightbox, face highlighted)               │
│            [Edit media ↗] (WordPress attachment edit)        │
│ « Previous photos · 1–50 of 134 photos · Next photos »       │
│ Face groups  [group A · 30 faces] [group B · 4 faces]        │
└──────────────────────────────────────────────────────────────┘
```
Deltas
- Zone `z-person-photos`: the Photos section already ships (pages of 50, `PersonWorkspacePanel.tsx:817-868`, lightbox only) but is missing from the map; iteration 2 records it and adds the face box, `act-open-media-item` (exit to WordPress media edit) and keeps `act-page-person-photos`.
- The reported "click does nothing": the open path needs a person UUID and a `current` projection (`RosterEntriesTable.tsx:150`, `RosterPage.tsx:60-65`); otherwise a gate notice replaces the workspace. Target: every rendered row has a UUID; a non-current projection opens the workspace read-only with a status line, not a replaced panel.
- Header carries the larger face crop, counts and provenance in words; debug meta removed from the header (kept behind a details disclosure only if needed for support).
- The operator's proposal (click → images containing the person) is adopted as this zone, reached by the avatar/name/photo-count click; not a separate surface.

---

## S-E. Findings panel — `workbench-2pane/workbench-control` (new zone `z-findings`)

CURRENT
```
┌ Findings ───────────────────────────────────────────┐
│ 23 faces need a name · 4 conflicts · 2 need repair  │
│ [Review next]  [View all findings]   ← both only     │
│                                        scroll/focus  │
│                                        a target that │
│                                        is not on     │
│                                        screen: inert │
└─────────────────────────────────────────────────────┘
```

TARGET
```
┌ Findings ────────────────────────────────────────────────┐
│ ● 23 faces need a name        [Name next face group]     │ → opens curation panel
│ ▲ 1 name could not be re-applied   [Open]                │ → conflict detail (S-B)
│ ■ 2 face groups need a resync  [Resync now]              │ → runs repair, status line
└──────────────────────────────────────────────────────────┘
```
Deltas
- New zone `z-findings` with one row per finding kind; each button names its effect and routes by `nextAction.kind` (review → curation panel for the target group; conflict → conflict detail; repair → resync job with status).
- A row with nothing to act on is not rendered (no disabled buttons without a reason); "View all findings" is removed.

---

## S-F. Review queue → name a person — `workbench-operator-loop/workbench-scan/z-review-queue` + `workbench-review-panel`

CURRENT
```
┌ Review queue (#acx-workbench-queue-heading) ────────────┐
│ [face] Is this Keanu Reeves?  [Yes] [No]                │
│ [face] 12 unnamed faces       [Review these faces]      │ → panel: faces + × only
│                                                         │   no name field
└─────────────────────────────────────────────────────────┘
```

TARGET (WBTRUST-2 S5 one-panel-two-entries + WBTRUST-3 control)
```
┌ Review queue ───────────────────────────────────────────┐
│ [face] Is this Keanu Reeves?  [Yes] [No]                │
│ [face] 12 unnamed faces       [Name these faces]        │
└─────────────────────────────────────────────────────────┘
          ↓ opens (heading id kept)
┌ Name these faces — 12 faces · 1 excluded ───────────────┐
│ [face][face][▒▒][face] …       click = exclude / undo   │
│ Name  [ Type a name…                        ▾ ] (S-A)    │
│                        [Save name for 11 faces]         │
│ ← Back to review queue                                  │
└─────────────────────────────────────────────────────────┘
```
Deltas
- Owned by WBTRUST-2 S5 (one panel, two entries; heading id preserved) with the S-A control from WBTRUST-3. ADR-019 only fixes the label rule ("Name these faces" for unnamed groups) and the sequencing.

---

## Map deltas (target vs baseline at d25922fa)

`roster-people`
- Screens added: `exit-media-item` (zone `z-media-edit`).
- Zones added: `roster-person-workspace/z-person-photos` (records the shipped Photos section). Removed: `roster-shell/z-review-cta`. Changed: `roster-shell/z-entries`, `roster-person-workspace/z-person-header`.
- Actions added: `act-name-unnamed-person`, `act-open-photo-lightbox`, `act-open-media-item`, `act-page-person-photos`. Changed: `act-goto-workbench`, `act-rename-person-pencil`.
- Flow added: `flow-person-to-photos`.

`workbench-2pane`
- Zones added: `workbench-control/z-findings`. Changed: `workbench-control/z-name-curate` (states + `max_candidates: 5`), `workbench-conflicts/z-conflict-detail` (`stale_reference` state), `workbench-conflicts/z-conflict-actions`; overlay `workbench-conflicts` retitled "Needs attention".
- Actions added: `act-rebind-person-faces` (primary), `act-review-rebind-faces`, `act-keep-person-unlinked`, `act-rescan-person-photos`, `act-finding-name-next`, `act-finding-open-rebind`, `act-finding-resync`.

`workbench-operator-loop`
- Screen `workbench-review-panel` retitled "Name these faces"; zone added `z-review-name`; action added `act-save-review-name` (WBTRUST-2 S5 panel).

Critique (`ux-map critique`, target maps): no finding on any added or changed id. Four baseline findings remain, all outside this scope: `act-undo-person-merge` preview (INT-07), `z-person-merge-preview` max_candidates (HAI-16), `workbench-2pane-shell` primary action (INT-05), `z-review-suggestions-group-card` evidence link (HAI-01; WBTRUST-1 owns it).
