# CURUX-1 — current vs target screens (ux-map iterations 1–2)

Map SSOT: `apps/prototype-wp-alt-context/docs/ux-maps/{roster-people,workbench-2pane,workbench-operator-loop}.uxmap.json`.
Vocabulary (map + UXP-4): person, face, face group. Never cluster, identity, topology, phase, payload in copy.
Iteration rule: each target names the map screen/zone/action it adds or changes; critique runs on the target deltas.
All TARGET screens below are proposed, not implemented or accepted.
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
- z-name-curate states: `loading` = suggestions pending (input stays enabled; create-new disabled until the roster list loads successfully, UXW2-3 race); new states `error-roster` ("Couldn't load people", Retry refetches the roster, create-new disabled) and `error-closest` ("Closest people unavailable", Retry, A–Z still shown); new state `empty` = "No named people yet — type a name".
- Option source: human-named people only (roster persons and human-confirmed labels); machine auto-labels and reserved labels never become options.
- Order: similarity rank (people-grain, max over that person's faces, UXW2-5), at most 5, then the alphabetical remainder; no re-sort of the ranked block while open (NAV-02). Below the suggestion floor a person is not ranked (CAL-02).
- Each ranked option shows up to 3 of that person's faces closest to this group, plus the face count (HAI-17: several references, not one); A–Z rows show the name and count only. Only proved current reference faces/counts appear; unverified associations show Faces need review. No match score or band word beside a name (iteration 2: a verdict word beside a name is a model same-label shown before the operator compares faces; HAI-15 spirit).
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

TARGET (illustrative verified topology change: counts below require proved correspondence under ADR-019 2c. A single pure successor bypasses the inbox only with complete same-namespace proof and eligible anchors; missing proof, reset and restore stay in Needs attention.)
```
┌ Needs attention (1) ───┬ Keanu Reeves ─────────────────────────────────┐
│ ▸ Keanu Reeves         │ The current analysis places verified faces  │
│   name not re-applied  │ in separate groups.                           │
│                        │ Your name is kept.                            │
│                        │                                               │
│                        │ Found 11 of 12 named faces in 2 new groups:   │
│                        │ [face][face][face][face] +7      (evidence)   │
│                        │                                               │
│                        │ [Re-apply "Keanu Reeves" to these 11 faces]   │
│                        │ [Review faces first]  [Keep name, unlinked]   │
│                        │ ▸ Technical details (operation id, codes)     │
└────────────────────────┴───────────────────────────────────────────────┘
```
Verified zero-match case, only after a complete successful read: "None of the faces you named are in the current analysis. Your name is kept in People." Actions: [Find faces again] (recognition is discovery, not identity proof) · [Keep name, unlinked].
Insufficient proof, changed source or reset/restore: "We cannot verify that these are the faces you named. Your name is kept in People." Show current candidates as unverified, never as "Found"; offer [Review faces first] and [Keep name, unlinked]. No identity-based Re-apply before fresh review. If current evidence is unavailable, keep the draft and offer Retry; do not turn a failed read into "none". Legacy records keep the existing person UUID/name and show "Faces need review" until fresh selection. Deleting the person stays in People.
Deltas
- New state on z-conflict-detail: `stale_reference` (missing group, changed membership or unverified source correspondence) — distinct from a true concurrent edit (`version_conflict`).
- New actions: `act-rebind-person-faces` (primary), `act-review-rebind-faces`, `act-keep-person-unlinked`, `act-rescan-person-photos`. Payload JSON moves behind a closed disclosure.
- Auto path (ADR-019 rules 2b–2d): exactly one nonempty successor, every incoming face proved one-to-one against this person's eligible active anchors, complete immutable source/raster/region evidence and eligible namespace, no competing binding/human label/active claim, current unsuppressed intent, and all person/group/member/proof guards. A moved-to group must be unbound and human-unnamed; a retained original may keep only this person's checked binding/incident label. Equal UUID/attachment/bbox is insufficient. Automatic re-link stays unavailable until the producer/export/storage/lifecycle contract is independently verified; a default-on preference cannot waive this. Multiple groups require review.
- Keep name, unlinked preserves the person UUID/name/origin and historical evidence, retires only reviewed active associations and suppresses automation. Unrelated valid bindings remain visible. Import, human-label backfill, rename, re-scan, toggles and reload cannot clear suppression; only a NEW explicit reviewed Bind/Re-apply intent can.
- Undo applies the guarded inverse, preserves a stale old reference as historical, and sets suppression. Distinguish locally saved, delivery pending, partially delivered, synced and needs review. Stale Undo cannot overwrite newer work. Redo needs new intent/command/step keys after the inverse settles; a cached original ACK never acknowledges redo.

- Both manual Re-apply and Review faces first use the proposed fourth WBTRUST-2 `StaleRebind` context. Fresh source consent is distinct from historical correspondence and cannot certify legacy observations. A preview never bypasses exclusions. Preserve ordinary named-group close-only outside that explicit recovery record.

Proposed interaction, reusing `workbench-review-panel` and the existing conflict-detail return path:
```text
Review faces for Keanu Reeves                 [Back to Needs attention]
Original group O (still present)   Keep group: [yes]  [face Keep] [face Exclude → destination]
Successor S1                      Keep group: [yes]  [face Keep] [face Keep]
Successor S2                      Keep group: [yes]  [face Keep] [face Exclude → destination]
N reviewed faces / K required exclusions       [Re-apply name to N faces]
  -> Excluding 1 of K... -> all local exclusions saved -> guarded rebind
  -> failure: Excluded M of K; name not re-applied       [Retry remaining]
  -> final failure: Exclusions saved; name not re-applied [Retry rebind]
  -> unknown outcome: Checking saved result...           [Check again]
  -> local success: Name saved locally / Sync pending    [Back]
Reload -> open this recovery record -> restored choices + step results [Resume review]
```

- Exclusion requires a reviewed real nonempty destination under the proposed adapter. No eligible destination: retain choices, explain the hold, and offer Retry/Keep name, unlinked. The current null-target removal helper is not this contract.
- All identifiers O/S1/S2 are illustrative, not API fields. The proposed journal belongs to the WordPress recovery command. Required local versions, complete incoming memberships independently of protected overlays, current intent and the exact `review_source_ref` displayed must validate; missing inputs show a reason and Retry while retaining work. No group collapse or merge-on-bind occurs. A competing binding stays protected. T empty offers Keep name, unlinked.
- Retrying reconciles unknown receipts first and skips successful exclusions. A changed person/group/evidence pauses for refreshed review and retains valid choices. Back stops new steps; reload restores acknowledged drafts and results without auto-committing. Ordinary name text is not replaced by the recovery target picker. See the WBTRUST-2 amendment for exact binding/outbox/partial-failure postconditions.
- Proposed map actions `act-resume-rebind` and `act-retry-rebind-remaining` cover resume/retry; final-rebind retry is the same recovery action with no remaining exclusions. Mirror phases, controls, focus and announcements into JSON and rendered Markdown; this ASCII proposal is not renderer-parity evidence.

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
- Naming a zero-face row updates that existing person UUID; it never creates/binds a group. A duplicate-name outcome offers Merge into… without a second person.
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
│            [Edit media ↗] [Use as cover]                     │
│ « Previous photos · 1–50 of 134 photos · Next photos »       │
│ Face groups  [group 1 · 30 faces] [group 2 · 4 faces]        │
└──────────────────────────────────────────────────────────────┘
```
Deltas
- Zone `z-person-photos`: the Photos section already ships (pages of 50, `PersonWorkspacePanel.tsx:817-868`, lightbox and Use as cover) but is missing from the map; iteration 2 records it and adds the face box, `act-open-media-item` (exit to WordPress media edit) and keeps `act-page-person-photos`.
- The reported "click does nothing": the open path needs a person UUID and a `current` projection (`RosterEntriesTable.tsx:150`, `RosterPage.tsx:60-65`); otherwise a gate notice replaces the workspace. Target: every rendered row has a UUID; a non-current projection opens the workspace read-only with a status line, not a replaced panel.
- Header/avatars/counts/photos use only confirmed current evidence under ADR-019 2b/2c/2e. Historical evidence and unverified current associations show separately as Faces need review, with Review faces / Keep name, unlinked. No live mutable crop may masquerade as historical proof. The header carries the larger face crop, counts and provenance in words; debug meta removed from the header (kept behind a details disclosure only if needed for support).
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

TARGET (illustrative counts; actions resolve their own loaded kind/id)
```text
Findings
Name suggestions: 2 loaded       [Name next face group] -> exact NAME group
Unnamed groups: 23 reported      [Name next face group] -> exact loaded CLUSTER
Close matches: 3 loaded          [Review next suggestion] -> exact assignment
Possible duplicates: 1 loaded    [Review next suggestion] -> exact merge card
Names needing attention: 1       [Review names] -> local recovery record
Face evidence needs refresh      [Resync] -> refetch, then show returned state
```

Deltas
- `z-findings` selects each row's first eligible item of that kind from `buildReviewQueue`'s ordered unfiltered queue, after existing tombstone/evidence gates. Never route every row by the global `nextAction`, and never treat a count as a loaded target. Loaded suggestion counts and the top-unlabeled server envelope retain their different scopes.
- NAME carries its own suggestion/group ids; CLUSTER carries its own group id. Open label mode for that exact available group. Assignment carries its own suggestion id and nullable group id: with a group, open its ordinary pending-suggestion panel; without one, label the action Review suggestion in queue and select its exact card, or show target unavailable with Retry. Do not guess a group id.
- MERGE is selected by its own `suggestionId` against `mergeSuggestions.id`. The proposed navigation consumer revalidates it, changes hidden-item kind/band filters through their existing owner (merge/all), locates its new filtered index, mounts the exact card and then focuses it. Preserve selection and pending-work safeguards; no automatic Accept/Reject. The current focus-current-card method does not select this id. If the requested card disappears, announce Target no longer available and offer Retry/Back; never focus a different card as success.
- Stale-reference summary/record selection is a proposed CURUX-3 local producer. Missing summary means Names unavailable, not zero. Repair retains the current top-unlabeled refetch action; copy must not promise a repair job or a fabricated count.
```text
Per row:
pending                  Checking...                     (no target claim)
failed                   Could not load this kind        [Retry]
unavailable              Explain local/config reason     [Retry / settings]
count > 0, no target      No actionable item loaded       [Retry / Resync]
target removed           Target no longer available      [Retry] [Back]
successful known zero    hide row
all included sources successfully zero, no repair gap    Nothing needs review
```
- `queueSettled` includes failed/disabled reads and cannot prove the final empty state. Healthy rows remain available while another source is pending or failed. Offline backend status does not erase locally available reads; mutation guards remain. Announce status changes, return focus after retry, and retain open drafts on unknown/5xx. Keep the successful first-time Run a scan entry. Remove View all findings; show disabled reasons. Apply RLSE-04 — Undesigned state is a bug (canon v0.26.2, `lexicons/engineering.md#rlse-04`, bootstrap) and CARD-03 — Designed unknown (supplied CARD-03 text).
- These interactions amend the existing workbench maps; JSON and rendered Markdown must agree on targets, filter changes, holds, availability, return focus and recovery. If producers attest only page emptiness, show No review items loaded rather than a backlog-wide all-clear. No map lint, browser or renderer verification is claimed here.

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
- Owned by WBTRUST-2 S5 (ordinary label/review entries; heading id preserved) with the S-A control from WBTRUST-3. Ordinary named-group entry without a pending suggestion stays close-only, including reload. The explicit recovery-record entry selects the fourth `StaleRebind` context shown in S-B; no bare named-group URL does so. ADR-019 proposes that context, its source/intent guards and the Name these faces label for unnamed groups.

---

## Map deltas (proposed target vs shipped maps at frozen source 2b9d4a0e)

`roster-people`
- Screens added: `exit-media-item` (zone `z-media-edit`).
- Zones added: `roster-person-workspace/z-person-photos` (records the shipped Photos section). Removed: `roster-shell/z-review-cta`. Changed: `roster-shell/z-entries`, `roster-person-workspace/z-person-header`.
- Actions added: `act-name-unnamed-person`, `act-open-photo-lightbox`, `act-open-media-item`, `act-page-person-photos`. Changed: `act-goto-workbench`, `act-rename-person-pencil`.
- Flow added: `flow-person-to-photos`.

`workbench-2pane`
- Zones added: `workbench-control/z-findings`. Changed: `workbench-control/z-name-curate` (states + `max_candidates: 5`), `workbench-conflicts/z-conflict-detail` (`stale_reference` state), `workbench-conflicts/z-conflict-actions`; overlay `workbench-conflicts` retitled "Needs attention".
- Actions proposed: `act-rebind-person-faces`, `act-review-rebind-faces`, `act-keep-person-unlinked`, `act-rescan-person-photos`, `act-resume-rebind`, `act-retry-rebind-remaining`, `act-finding-name-next`, `act-finding-open-rebind`, `act-finding-resync`. The fourth context and per-kind findings navigation add pending/unavailable/error/target-removed/partial-progress/resume branches to the existing zones; preserve JSON/rendered Markdown parity for all branches before acceptance.

`workbench-operator-loop`
- Screen `workbench-review-panel` retitled "Name these faces"; zone added `z-review-name`; action added `act-save-review-name` (WBTRUST-2 S5 panel).

Historical iteration 1–2 critique (`ux-map critique`, earlier target maps) reported no finding on added/changed ids. It predates this corrective revision and does not validate these new interactions. Four baseline findings remain, all outside this scope: `act-undo-person-merge` preview (INT-07), `z-person-merge-preview` max_candidates (HAI-16), `workbench-2pane-shell` primary action (INT-05), `z-review-suggestions-group-card` evidence link (HAI-01; WBTRUST-1 owns it).

The three UX-map JSON files and their rendered Markdown are outside this revision's four-file ownership. They are unchanged. Follow-on owners must mirror the S-B recovery source/destination choices, receipt/status/resume/Undo states and S-E per-kind targets/filter holds/availability into those existing map IDs, then run renderer parity and `make lint-ux-maps`. This revision verifies Markdown/link/contract consistency only; it claims no map-lint, renderer or browser result.
