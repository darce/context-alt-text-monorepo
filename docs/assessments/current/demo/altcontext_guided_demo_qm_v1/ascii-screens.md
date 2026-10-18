# AltContext guided demo — target screens (ASCII)

Source: `implementation-brief.json` (`target_information_architecture`, `state_machine`,
`target_test_hooks`, `findings`) + `copy.en.json` (verbatim strings). Route:
`/wp-admin/admin.php?page=alt-context-dashboard#/guided-prototype`. Copy strings below are
quoted verbatim from `copy.en.json`; `{placeholder}` fields are shown rendered with example
values in brackets. Boxes are ~78 cols. Canon rule ids are cited as they appear in
`heuristics-canon-research/lexicons/{interaction-ux,accessibility}.md` (`INT-*`, `FORM-*`,
`HAI-*`, `A11Y-*`) — the scheme has no `F06`/`F12`/`T21` ids; nearest actual rules are used
and noted where a request mapped to one of those.

---

## S0 — Compact entry

```text
+------------------------------------------------------------------------------+
| AltContext guided demo                                          [page.eyebrow]|
| Review an AI-assisted alt text draft                             [page.title] |
|                                                                                |
| You are editing a photo in a festival gallery. Review two saved name          |
| suggestions, edit the alt text, then apply it to a demo copy. You can leave   |
| either person unnamed.                                            [page.intro]|
|                                                                                |
| This walkthrough uses recorded face suggestions and sample drafts. Your       |
| choices change only the demo copy in this tab and reset when you reload.      |
|                                                                     [page.scope]|
| An optional live test at the end runs separately on the server.              |
|                                                                [page.live_scope]|
|                                                                                |
|            +--------------------------------+                                |
|            |     Start the walkthrough       |  <- primary, only CTA        |
|            +--------------------------------+          [page.start]         |
|                                                                                |
|            Read the AltContext case study                    [page.case_study]|
|            (secondary, text link, exits demo)                                |
+------------------------------------------------------------------------------+
```

Notes: one dominant CTA (`page.start`); `page.live_scope` sits directly under
`page.scope` as a secondary sentence, not a second CTA (INT-05 prominent-Done,
INT-03 button grouping by scope). `page.case_study` is a link, not a button —
visually subordinate so it does not compete (INT-01 affordance match).

---

## S1 — Step 1: context (`guided-section-understand`)

```text
+------------------------------------------------------------------------------+
| Demo steps                                                        [guide.label]|
| Step 1 of 4: Understand the page          [Show all steps]  [guide.current/.show]|
+------------------------------------------------------------------------------+
| Understand the page                                          [step.context]  |
| This photo appears in a festival gallery. Review the existing alt text       |
| alongside the photo and its page context.                    [context.intro]|
|                                                                                |
| +----------------------+   Example page                 [context.page_label]|
| | [photo: two people   |   Current alt text in the demo copy:                |
| |  at a festival]      |   "Two people at a film festival."                  |
| +----------------------+                        [context.current_label]     |
|                                                                                |
| Names can be useful in this gallery when the editor has enough evidence to   |
| include them. Leaving someone unnamed is also a valid choice. [context.purpose]|
|                                                                                |
| > Saved example and image credits                     [provenance.disclosure]|
|   (closed <details>; contains provenance.recorded when open)                 |
|                                                                                |
|                                    +---------------------------+             |
|                                    |  Review name suggestions   |  <- primary|
|                                    +---------------------------+ [context.next]|
+------------------------------------------------------------------------------+
```

Guard: `context.next` (→ `continue_to_names`) is always enabled per
`transitions.start_or_select_step` ("Always allowed for inspection").

---

## S2 — Step 2: names, both undecided (`guided-section-identity`)

```text
+------------------------------------------------------------------------------+
| Step 2 of 4: Choose which names to use                        [guide.current]|
+------------------------------------------------------------------------------+
| Choose which names to use                                       [step.names] |
| For each face, compare the saved suggestion with the reference photos.       |
| Choose whether to include that name in the sample draft.        [names.intro]|
| This is an assisted review of saved suggestions, not an independent          |
| identity check.                                                [names.assisted]|
|                                                                                |
| +---------------------------------+  +---------------------------------+     |
| | [crop: left face]                |  | [crop: right face]               |    |
| | Saved suggestion: Jordan Lee     |  | Saved suggestion: Rowan Ames      |    |
| |                    [names.suggestion]|                  [names.suggestion]|
| | > Compare the left face and      |  | > Compare the right face and      |   |
| |   reference photos               |  |   reference photos                |   |
| |          [names.evidence_open]   |  |           [names.evidence_open]   |   |
| |                                   |  |                                    |  |
| | fieldset legend: "Name choice     | fieldset legend: "Name choice        |  |
| |  for the left face"               |  for the right face"       [names.legend]|
| | ( ) Use Jordan Lee    [names.include]| ( ) Use Rowan Ames    [names.include]|
| | ( ) Leave this person unnamed        | ( ) Leave this person unnamed        |
| |               [names.omit] -- no preselection --      [names.omit]        |
| |                                   |  |                                    |  |
| | Choose an option for this face.  |  | Choose an option for this face.   |   |
| |                    [names.pending]|  |                    [names.pending]|   |
| | test id: name-choice-left        |  | test id: name-choice-right        |   |
| +---------------------------------+  +---------------------------------+     |
|                                                                                |
| Choose an option for both faces. Leaving a person unnamed counts as a        |
| choice.                                                    [names.next_blocked]|
|                                    +---------------------------+ (disabled)  |
|                                    |   Review the draft         |            |
|                                    +---------------------------+ [names.next]|
+------------------------------------------------------------------------------+
```

Both radio groups are native `<fieldset>`/`<input type=radio>` (FORM-06 native
controls, A11Y-12 native-first) with no checked default (state contract:
`choices.initial = {left: undecided, right: undecided}`). `names.next` is
disabled and paired with `names.next_blocked` reason text — never colour-only
(A11Y-06) — until `namesDecided` is true.

---

## S2b — Step 2, left=include / right=omit

```text
+------------------------------------------------------------------------------+
| +---------------------------------+  +---------------------------------+     |
| | (o) Use Jordan Lee               |  | ( ) Use Rowan Ames                |    |
| | ( ) Leave this person unnamed    |  | (o) Leave this person unnamed     |    |
| |                                   |  |                                    |  |
| | The sample draft will use Jordan |  | The sample draft will describe    |   |
| | Lee.                [names.included]| this person without a name.       |   |
| |                                   |  |              [names.omitted]      |   |
| | Saved photos of Jordan Lee: 4 of 4|  |                                    |  |
| | reference photos are shown.       |  |                                    |  |
| |          [names.coverage_all]    |  |                                    |  |
| +---------------------------------+  +---------------------------------+     |
|                                                                                |
|                                    +---------------------------+  <- primary |
|                                    |   Review the draft         |  (enabled) |
|                                    +---------------------------+ [names.next]|
+------------------------------------------------------------------------------+
```

Right-face coverage variant (partial reference set):
`names.coverage_partial` → "3 of 5 reference photos are included in this demo."
Both `names.included`/`names.omitted` sentences are live status text next to
the fieldset, not colour alone (A11Y-06); focus remains on the radio just
activated — no forced focus jump (A11Y-11 keyboard walk / focus order).

---

## S3 — Step 3: draft (`guided-section-review`)

```text
+------------------------------------------------------------------------------+
| Step 3 of 4: Edit the alt text                                 [guide.current]|
+------------------------------------------------------------------------------+
| Edit the alt text                                                [step.draft]|
| Check the wording against the photo and the page context. Edit anything     |
| you would not publish.                                          [draft.intro]|
|                                                                                |
| Sample draft from the recorded example.               [draft.origin_saved]  |
| (or, once edited: "Your edit, based on the recorded example."                |
|                                             [draft.origin_edited])           |
|                                                                                |
| Alt text draft                                                  [draft.label]|
| +----------------------------------------------------------------------+    |
| | Jordan Lee and an unnamed guest pose together at the festival red    |    |
| | carpet.                                                    [textarea]|    |
| +----------------------------------------------------------------------+    |
| Edits stay in this tab. Nothing is applied until you choose Apply to         |
| demo copy.                                                     [draft.effect]|
|                                                                                |
|            +---------------------------+   Keep current alt text            |
|            |   Preview the change       |   (secondary, text/outline)       |
|            +---------------------------+          [draft.keep]              |
|              [draft.next] <- primary                                        |
|                                                                                |
| > Draft history (closed; only rendered when revisions exist)  [draft.history]|
|   Earlier edits are kept in this tab until you reset or reload.              |
|                                                        [draft.history_note]  |
+------------------------------------------------------------------------------+
```

`draft.next` ("Preview the change") is the one primary action (INT-05);
`draft.keep` is a same-scope secondary, clustered but visually subordinate
(INT-03). Empty-textarea guard: `draft.empty_error` ("Enter alt text before
reviewing the change.") appears inline at the field, not a toast (FORM-05,
A11Y-17).

---

## S3b — Step 3: pending choice-change confirmation

Triggered when `choose_name_option` fires while `draftOrigin == visitor_edit`
(state machine `pendingChoiceChange`). Modal/dialog over the draft step.

```text
+------------------------------------------------------------------------------+
|  Change the name choice?                                  [names.change_title]|
|                                                                                |
|  This loads the sample draft for your new choices. Your current edit will    |
|  remain in Draft history. The demo image will not change until you apply     |
|  again.                                                    [names.change_body]|
|                                                                                |
|                      +----------------------------+   +----------------+     |
|                      | Change choice and load draft|   |  Keep editing  |     |
|                      +----------------------------+   +----------------+     |
|                        [names.change_confirm]           [names.change_cancel]|
+------------------------------------------------------------------------------+
```

On confirm: `names.change_status` ("Name choice changed. Review the updated
draft before applying it.") is announced via a status live region back on the
draft step (A11Y-21). On cancel: focus returns to the radio the visitor just
activated (`cancel_choice_replacement` → "return focus to the originating
control") — explicit focus-restoration requirement, closest actual rule to a
"focus management after choice" check is A11Y-11 (focus order/visible) plus
A11Y-13 (focus not obscured by the dialog it just closed).

---

## S4 — Step 4: apply (`guided-section-apply`), outcome = applied

```text
+------------------------------------------------------------------------------+
| Step 4 of 4: Apply and undo                                    [guide.current]|
+------------------------------------------------------------------------------+
| Apply and undo                                                   [step.apply]|
| Compare the current alt text with your draft. Applying changes only the      |
| demo image below.                                                [apply.intro]|
|                                                                                |
| Current alt text                    | Will be applied                        |
|            [apply.before]           |              [apply.after]             |
| "Two people at a film festival."    | "Jordan Lee and an unnamed guest pose |
|                                      |  together at the festival red carpet."|
|                                                                                |
| Demo image preview                                       [apply.preview_title]|
| +----------------------------------------------------------------------+    |
| |  [distinct demo image — test id: demo-applied-image]                 |    |
| |  alt = appliedAltText (post-apply)                                    |    |
| +----------------------------------------------------------------------+    |
|                                                                                |
|   +-------------------------+     +---------------------------+            |
|   |  Apply to demo copy      |     |  Undo last application     |          |
|   +-------------------------+     +---------------------------+            |
|     [apply.submit] test id:         [apply.undo] test id: demo-undo        |
|     demo-apply (primary)            (secondary, enabled: canUndo)          |
|                                                                                |
| Your demo copy is updated                              [outcome.applied]    |
| (outcome container — test id: demo-outcome; status announced via live region)|
| Applied to the demo copy in this tab. WordPress media has not been updated.  |
|                                                              [apply.success] |
+------------------------------------------------------------------------------+
| > Design notes   (optional, closed)                            [notes.title]|
| > Optional: test live description generation (closed)          [live.title] |
+------------------------------------------------------------------------------+
```

`apply.submit` is enabled only when `canApply`; `apply.undo` only when
`canUndo`. Live-generation disclosure (`live.title`) is placed after the
outcome, subordinate chrome — it "never competes with Apply"
(`primary_action_policy`).

---

## S4b — Step 4: outcome = kept

```text
+------------------------------------------------------------------------------+
| The demo copy is unchanged                                  [outcome.kept]  |
| You kept the current alt text. You can return to the draft or inspect the   |
| design notes below.                                       [outcome.kept_body]|
|                                    +---------------------------+            |
|                                    |   Return to the draft      |            |
|                                    +---------------------------+ [outcome.return]|
+------------------------------------------------------------------------------+
```

Replaces the before/after comparison block in S4; `apply.submit`/`apply.undo`
are not shown (nothing to apply/undo yet — guard `canApply` requires a
previewed draft that differs from `appliedAltText`; `keep_current_alt_text` is
"Always allowed, including a blocked/missing sample").

---

## S5 — Optional live test disclosure

### Closed

```text
+------------------------------------------------------------------------------+
| > Optional: test live description generation                   [live.title] |
+------------------------------------------------------------------------------+
```

### Open — unavailable (contract not verified)

```text
+------------------------------------------------------------------------------+
| v Optional: test live description generation                                |
| Generate a separate description of this photo on the server. It will not    |
| replace your draft or change the demo copy.                     [live.intro]|
| The server uses its own saved people. Your name choices in the walkthrough  |
| do not change this live test.                                   [live.names]|
| Live generation is unavailable in this build. The recorded walkthrough      |
| still works.                                         [live.request_unverified]|
| (Generate a separate live description button: absent/disabled — canStartLive|
|  requires liveContractVerified)                                              |
+------------------------------------------------------------------------------+
```

### Open — pending

```text
+------------------------------------------------------------------------------+
| This sends a live description request for the example photo to the          |
| configured AltContext service. See Request details before starting.         |
|                                                  [live.request_confirmed]    |
| > Request details                                                [live.details]|
| Waiting for the live description. Your demo copy is unchanged. [live.pending]|
|                          +---------------------+                            |
|                          |   Stop waiting        |         [live.stop_waiting]|
|                          +---------------------+                            |
+------------------------------------------------------------------------------+
```

### Open — failed / timed out (shared shape, one of two strings)

```text
+------------------------------------------------------------------------------+
| failed: The live description could not be completed. Your demo copy is      |
|         unchanged.                                          [live.failed]   |
| timed out: The wait limit was reached. The server job may still be running. |
|            Your demo copy is unchanged.                  [live.timed_out]   |
|                          +---------------------------+                      |
|                          |  Try live generation again  |    [live.retry]    |
|                          +---------------------------+                      |
+------------------------------------------------------------------------------+
```

Live output, when present, renders in a dedicated read-only region:
`live.output_label` ("Live server result (read-only)") — kept visually and
structurally separate from `draft.label` so the two never merge into one
announced region (state guard: `live_response` "Never copy into the demo
candidate automatically"). Test ids: `guided-live`, `guided-live-status`
(preserved existing).

---

## S6 — Reset dialog

```text
+------------------------------------------------------------------------------+
|  Reset this demo?                                              [reset.title]|
|                                                                                |
|  This clears name choices, drafts and local history, and restores the       |
|  original demo alt text.                                        [reset.body]|
|                                                                                |
|  A live server job may continue after this reset.   [reset.active_live_note]|
|  (shown only when liveStatus == pending at the time Reset is opened)         |
|                                                                                |
|                      +-----------------+       +-----------------+           |
|                      |  Reset demo      |       |  Keep my work    |         |
|                      +-----------------+       +-----------------+           |
|                        [reset.confirm]           [reset.cancel]              |
+------------------------------------------------------------------------------+
```

On confirm: `reset.status` ("Demo reset. WordPress media was not changed.")
announced via status live region; focus returns to `page.start` /
`page.reset` trigger. `reset.active_live_note` is the only variant row —
present iff a live request is in flight, per `confirm_reset` forbidding a
claim that "remote work was stopped merely because local state reset."

---

## S7 — Narrow width (≤360px), step 2 reflow, with wp-admin toolbar

```text
+--------------------------------+
|[WP] alt-context-dashboard    ▾ |  <- WordPress admin toolbar row (fixed)
+--------------------------------+
| Step 2 of 4: Choose which      |
| names to use     [Show steps]  |
+--------------------------------+
| Choose which names to use      |
| For each face, compare the     |
| saved suggestion with the      |
| reference photos. Choose       |
| whether to include that name   |
| in the sample draft.           |
+--------------------------------+
| [crop: left face]              |
| Saved suggestion: Jordan Lee   |
| > Compare the left face and    |
|   reference photos             |
|                                 |
| Name choice for the left face  |
| ( ) Use Jordan Lee             |
| ( ) Leave this person unnamed  |
| Choose an option for this      |
| face.                          |
+--------------------------------+
| [crop: right face]             |
| (mirrors left face block:      |
|  suggestion, evidence link,    |
|  fieldset, pending sentence)   |
+--------------------------------+
| Choose an option for both      |
| faces. Leaving a person        |
| unnamed counts as a choice.    |
|                                 |
|   +-------------------------+  |
|   | Review the draft (dis.) |  |
|   +-------------------------+  |
+--------------------------------+
```

Face articles stack single-column (no 2-D scroll at 320–360px width, A11Y-08
reflow/resize); the admin toolbar row is fixed chrome at the top and must not
obscure the currently focused radio when it scrolls into view (A11Y-13 focus
not obscured). No horizontal truncation of `names.legend`/`names.pending`
text — wraps instead.

---

## Guard annotations

| Button / control | Copy key | Derived guard | Enabled when |
| --- | --- | --- | --- |
| Review the draft (S2) | `names.next` | `namesDecided` | both `choices.left` and `choices.right` != `undecided` |
| Preview the change (S3) | `draft.next` | `canPreview` | `namesDecided` AND `draftStatus==ready` AND `draftText` non-empty (trimmed) |
| Keep current alt text (S3) | `draft.keep` | none (always allowed) | always, "including a blocked/missing sample" |
| Apply to demo copy (S4) | `apply.submit` | `canApply` | `canPreview` AND `previewedVersion==draftVersion` AND `draftText != appliedAltText` AND `pendingChoiceChange==null` |
| Undo last application (S4) | `apply.undo` | `canUndo` | `applicationUndoStack.length > 0` |
| Generate a separate live description (S5) | `live.submit` | `canStartLive` | `liveContractVerified` AND `liveStatus != pending` |
| Restore earlier draft (draft history) | `draft.restore_revision` | `canRestoreRevision` | `revision.choices == choices`; else copy-only recovery per `draft.restore_guard` |
| Change choice and load draft (S3b) | `names.change_confirm` | `pendingChoiceChange != null` | dialog is open (guard is presence-based, not derived-boolean) |

---

## Canon review checklist

| # | Screen | Rule | What to check | Pass/fail criterion |
| --- | --- | --- | --- | --- |
| 1 | S2 | INT-05 (Prominent Done) | Exactly one unmistakable final action after the two fieldsets | Fails if `names.next` shares visual weight with any radio or the disclosure link |
| 2 | S2 | FORM-09 (Responsive enabling) | `names.next` state before both choices are made | Fails if the button is clickable (not just visually muted) while `namesDecided` is false |
| 3 | S2/S2b | A11Y-06 (Second channel always, 1.4.1) | Status of each face's choice (`names.pending`/`included`/`omitted`) | Fails if state is conveyed by radio fill colour alone with no adjoining text |
| 4 | S2, S2b | A11Y-12 (Native first) | Radio fieldsets are native `<fieldset>`/`<legend>`/`<input type=radio>` | Fails if built from styled `<div>`s with ARIA roles bolted on |
| 5 | S3b | A11Y-11 (Keyboard walk) / focus order | Focus destination on dialog open and on `Keep editing` | Fails if focus is not moved into the dialog on open, or not returned to the originating radio on cancel |
| 6 | S3b | A11Y-13 (Focus not obscured) | Dialog does not hide the focused control it just replaced | Fails if the confirm/cancel buttons render under the sticky guide bar at any breakpoint |
| 7 | S3 | INT-03 (Button group by scope) | `draft.next` (primary) vs `draft.keep` (secondary) | Fails if both are styled as equal-weight primary buttons |
| 8 | S3 | FORM-05 / A11Y-17 (Inline actionable errors) | Empty-textarea submit attempt | Fails if `draft.empty_error` appears in a toast/modal instead of inline at the textarea |
| 9 | S4 | INT-07 (Preview before commit) | Before/after comparison renders before `apply.submit` is enabled | Fails if Apply is reachable without the current `apply.before`/`apply.after` pair on screen |
| 10 | S4 | INT-09 (Reversible command stack) | `apply.undo` after one apply | Fails if Undo is absent, or restores something other than the immediately preceding `appliedAltText` |
| 11 | S4 | A11Y-21 (Announce status, 4.1.3) | `outcome.applied`/`apply.success` on apply; `apply.undone` on undo | Fails if the outcome text updates in the DOM with no `role="status"`/live region so AT users get no announcement |
| 12 | S4 | live-region duplication (nearest: A11Y-21) | `demo-outcome` region vs any toast/snackbar echoing the same success text | Fails if two live regions both announce `apply.success`, producing duplicate AT output |
| 13 | S5 | HAI-05 (Imperceptible AI is not ethical) / disclosure pattern | Live-test section stays a closed `<details>` until opened | Fails if live generation can start without the visitor first expanding the disclosure |
| 14 | S5 | INT-08 (Wait state and cancel) | `live.pending` state | Fails if there is no `live.stop_waiting` control while `liveStatus==pending` |
| 15 | S5 vs S3/S4 | HAI-12 (Output is a proposal) | `live.output_label` region vs `draft.label` | Fails if live output and the editable draft share one visual/DOM container, implying live output edits the draft |
| 16 | S6 | INT-06 (Smart action labels) | `reset.confirm` vs `reset.cancel` labels | Fails if either button reads as a generic "OK"/"Cancel" instead of naming the action ("Reset demo" / "Keep my work") |
| 17 | S6 | A11Y-24 (Every state accessible) | `reset.active_live_note` variant | Fails if the live-job caveat is only ever tested in the no-live-job dialog state |
| 18 | S7 | A11Y-08 (Reflow and resize, 1.4.4/1.4.10) | 320–360px width, 200% zoom | Fails on any 2-D scroll or clipped `names.legend`/`names.pending` text |
| 19 | S7 | A11Y-13 (Focus not obscured) | wp-admin toolbar row over a focused radio | Fails if the fixed toolbar covers the focused control when the fieldset scrolls under it |
| 20 | S0 | INT-12 (First success before extract) | Path from `page.start` to a completed step-1 read | Fails if any account/profile/setup gate sits between `page.start` and `context.intro` |

---

## Open questions for the reflow lane

- At 320px, do the two face articles in S2/S7 stack with `names.evidence_open` disclosures closed by default, or does the reflow spec require both open (taller scroll, less discovery friction)?
- Where does the sticky/fixed `guide.current` step-indicator row dock relative to the wp-admin admin-bar at ≤360px — same fixed layer, or does it scroll away to avoid double-fixed-header stacking (interacts with A11Y-13, check 19)?
- Does `apply.preview_title` (S4 image preview) get a max-height crop or full reflow to full-bleed width under 360px, and does that change the demo image's effective tap target relative to `apply.submit`/`apply.undo` (A11Y-14, 24×24px floor)?
- In S3b (choice-change confirm), does the dialog reflow as a full-screen sheet under 360px, or stay a centered modal — affects where "return focus to the originating control" lands relative to viewport scroll position?
- Does the `draft.history` disclosure (S3) get its own reflow treatment, or is it hidden entirely below a breakpoint (task brief doesn't specify a narrow-width drop policy for optional content)?
- For S5's four open states (unavailable/pending/failed/timed_out), is there a narrow-width layout difference beyond the shared `live.title` disclosure width, or does the reflow lane treat them as width-invariant?
- Does `names.coverage_partial`'s reference-photo strip (evidence disclosure) reflow to a horizontal scroller or a wrapped grid under 360px, and which one keeps single-pointer/keyboard parity (A11Y-15)?
- Is there a target breakpoint between 360px and desktop (e.g. tablet) that changes the two-column S4 before/after comparison to stacked, or does it stay two-column down to 360px per this doc's S7 scope (S7 only specifies S2)?
