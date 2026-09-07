# UX Map — guided-prototype

**Product:** `AltContext — authenticated guided prototype`

## Goals

- Implementation inventory and correction target for feature/guided-prototype-1; one in-memory example inside authenticated WordPress admin, not the public homepage.
- Show visual draft + confirmed identity + page context → named description; editing/rejection never applies automatically.
- Only the saved candidate can be applied; pending text is labelled and must be saved or discarded before Apply.
- Guide navigation reaches its named region; reset dialog preserves edits on cancel; all disappearing actions restore focus.
- Clear illustrative provenance, bundled sample with text fallback, no live inference dependency.
- State variants share one route; refresh resets memory, and the UI explains this.

## Jobs

- `review` — Review identity-informed description and apply to practice copy
- `recover` — Undo or reset practice without hidden losses

## Screens

| id | kind | route | title |
| --- | --- | --- | --- |
| `intro` | screen | `#/guided-prototype` | AltContext guided demo |
| `guide` | screen | `#/guided-prototype` | Step by step |
| `evidence` | screen | `#/guided-prototype` | Photo and page |
| `face` | screen | `#/guided-prototype` | Faces found in the photo |
| `draft` | screen | `#/guided-prototype` | Check the description before anything changes |
| `live` | screen | `#/guided-prototype` | See it run live |
| `apply` | screen | `#/guided-prototype` | Apply it yourself |
| `result` | screen | `#/guided-prototype` | Applied result and history |
| `reset` | overlay | `#/guided-prototype` | Reset practice confirmation |
| `image-fallback` | screen | `#/guided-prototype` | Image unavailable, text evidence remains |
| `case-study` | exit | `https://darce.xyz/projects/altcontext/` | Authoritative case study |

## Code references

- `screen:intro` — `apps/prototype-wp-alt-context/js/admin/pages/GuidedPrototypeEntrance.tsx`
- `screen:guide` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedPrototypeGuide.tsx`
- `screen:evidence` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedPrototypePage.tsx`
- `screen:face` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedFaceMatchCard.tsx`
- `screen:draft` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedDescriptionReview.tsx`
- `screen:live` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedLiveDescriptionPanel.tsx`
- `screen:apply` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedDescriptionReview.tsx`
- `screen:result` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedPrototypePage.tsx`
- `screen:reset` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedResetDialog.tsx`
- `screen:image-fallback` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedSamplePhoto.tsx`
- `screen:case-study` — `apps/prototype-wp-alt-context/js/admin/pages/GuidedPrototypeEntrance.tsx`

## Screens (ASCII)

```text
+------------------------------------------------------------------------------+
| Saved run                                                    [Reset practice]|
| How two faces become two names in the description                            |
| Photo [done] > 2 faces found [done] > Matched to Justin Trudeau and          |
| Katy Perry [done] > You confirm each match [now] > Names in the description  |
| [waiting]                                                                    |
+------------------------------------------------------------------------------+
| [press photo: two people, red carpet]   | Where this example comes from      |
| The photo                               | Example  Saved from a real run ...  |
| Alt text on the page right now: Two ... | Page     Tribeca Festival 2026 ...  |
| Photo credit: Colleen Sturtevant, ...   | People   Katy Perry (5) · Justin (2)|
| AltContext found two faces in this ...  | Also     A Coachella press photo ...|
+------------------------------------------------------------------------------+
| Faces found in the photo                                                     |
| AltContext found 2 faces. Each one matched a person you named before.        |
| +-----------------------------+  +-----------------------------+             |
| | [crop]  Face on the left    |  | [crop]  Face on the right   |             |
| | It matches ... Justin       |  | It matches ... Katy Perry   |             |
| | ✓ Match strength: strong... |  | ✓ Match strength: strong... |             |
| |                             |  | Her face is turned a little |             |
| | [saved photo] Saved photo   |  | [saved photo] Saved photo   |             |
| | You have not decided yet.   |  | You have not decided yet.   |             |
| +-----------------------------+  +-----------------------------+             |
| Confirm each match                                                           |
|  Justin Trudeau, face on the left   [Yes, this is Justin Trudeau] [Keep ...] |
|  Katy Perry, face on the right      [Yes, this is Katy Perry]     [Keep ...] |
+------------------------------------------------------------------------------+
| Check the description before anything changes           [Ready for you ...]  |
| Without the names          | Draft for you to check                          |
| A man in a black tuxedo... | [textarea: Justin Trudeau and Katy Perry ...]   |
|                            | [Save my edit] [Reject this draft]              |
| Apply it yourself  The practice copy says "Two people at a film festival."   |
| [Apply to practice copy] [Undo]                                              |
+------------------------------------------------------------------------------+
| See it run live                                        [Describe it live]   |
| A live run never changes the draft above, and it never changes what Apply   |
| would write. Names come from your roster on the server, not this page.      |
| Confirmed here: Justin Trudeau, Katy Perry.                                 |
| ... Starting the GPU. A cold start can take several minutes.                |
| 1:05 of up to 8:30                                       [Stop waiting]     |
| > Katy Perry waves from the red carpet.                                     |
| (v) Done. The GPU wrote this.   The draft above did not change.             |
+------------------------------------------------------------------------------+
```

## Screen inventories

### AltContext guided demo (`intro`)

Purpose: Follow one photo from start to finish. AltContext finds two faces, matches each one to a person you already named, and puts their names in the image description. You choose what gets saved.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `intro-0` | Guided demo, scope, and current build status: This demo uses one saved face-match run. Descriptions can run live on the real GPU. | content | default |
| `intro-1` | Start the demo and read the AltContext case study | nav | default |

Actions: `open` Start the demo → `guide`; `case` Read the AltContext case study → `case-study`.

### Step by step (`guide`)

Purpose: Five steps show the path from the photo to the description: Look at the photo, Find the faces, Confirm each match, Check the description, and Apply it yourself.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `guide-0` | Current step, Skip to this step, and Show steps / Hide steps | nav | default |
| `guide-1` | Five steps: Look at the photo — See the photo and the page it sits on.; Find the faces — AltContext found two faces and matched each one to a person you named before.; Confirm each match — Say yes to each match, or keep that person unnamed.; Check the description — Read the draft. Edit it or reject it.; Apply it yourself — Nothing changes until you press Apply.; Close the steps | nav | default |

Actions: `toggle-guide` Show steps / Hide steps → `guide`; `skip-guide` Skip to this step → `evidence`; `guide-step` Choose a step → `draft`; `end-guide` Close the steps → `evidence`.

### Photo and page (`evidence`)

Purpose: See the photo and the page it sits on. AltContext found two faces and the next step shows the matches.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `evidence-0` | The photo; Alt text on the page right now: Two people at a film festival.; Photo credit: Colleen Sturtevant, CC BY-SA 4.0.; AltContext found two faces in this photo. The next step shows the matches. | ai_review | default |
| `evidence-1` | Saved run — How two faces become two names in the description. AltContext looks at the photo, finds each face, and checks it against people you already named. If you confirm a match, that name goes into the description. You always have the last word. Where this example comes from: Example — Saved from a real run, not a live run; Page — Tribeca Festival 2026: red carpet photos; People on file — Katy Perry (5 saved photos) · Justin Trudeau (2 saved photos); Photo credit — Colleen Sturtevant, CC BY-SA 4.0.; Also checked — A Coachella press photo of the same two people matched both, even with a hand over her mouth. It is not bundled because of licensing.; Flow strip (How the faces reach the description) — Photo · 2 faces found · Matched to Justin Trudeau and Katy Perry · You confirm each match · Names in the description. | content | default |

### Faces found in the photo (`face`)

Purpose: AltContext found 2 faces. Each one matched a person you named before.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `face-0` | Face crops and matches: Face on the left — It matches a person you named before: Justin Trudeau. ✓ Match strength: strong. This face is close to the 2 saved photos of Justin Trudeau.; Face on the right — It matches a person you named before: Katy Perry. ✓ Match strength: strong. This face is close to the 5 saved photos of Katy Perry.; Her face is turned a little to the side.; Saved photos of Justin Trudeau: 2 of 2 shown.; Saved photos of Katy Perry: 3 of 5 shown. | ai_review | first_time, default |
| `face-1` | How this works: 1. AltContext finds every face in the photo. 2. It compares each face to the people you already named. 3. It asks you to confirm each match. Nothing is named without your OK. These matches were saved from a real run. The demo does not run recognition live. | content | first_time, default |
| `face-2` | Decision status: You have not decided yet. / You confirmed: Justin Trudeau. / You confirmed: Katy Perry. / You kept this person unnamed. Decisions block: Confirm each match. Justin Trudeau, face on the left — Yes, this is Justin Trudeau / Keep this person unnamed. Katy Perry, face on the right — Yes, this is Katy Perry / Keep this person unnamed. Changing an answer swaps in a different saved draft. Save or discard your edit first. Buttons are disabled and described by this note while an edit is unsaved; confirm is disabled when already confirmed; unnamed is disabled when already unidentified. Feedback: Match confirmed. {name} is in the draft. Nothing is applied yet. The person on the {position} stays unnamed. You can still check the description. | form | first_time, default |

Actions: `confirm-katy-perry` Yes, this is Katy Perry → `draft`; `unnamed-katy-perry` Keep this person unnamed → `draft`; `confirm-justin-trudeau` Yes, this is Justin Trudeau → `draft`; `unnamed-justin-trudeau` Keep this person unnamed → `draft`. While an edit is unsaved, all decision buttons are disabled and described by the change note; the confirm button is disabled when already confirmed and the unnamed button is disabled when already unidentified.

### Check the description before anything changes (`draft`)

Purpose: Read the draft. Edit it or reject it. Nothing changes until you press Apply.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `draft-0` | Ready for you to check, Edited by you, or Rejected. The saved text did not change. Both confirmed: You confirmed both matches, so both names are in the draft. The visual details and page context stay the same. One confirmed: You confirmed one match, so one name is in the draft. The other person is described, not named. None confirmed, all decided: You kept both people unnamed, so the draft only says what is visible. Otherwise: Confirm or skip each face match first. Until then the draft only says what is visible. | form | default |
| `draft-1` | Draft without names: A man in a black tuxedo and a woman in a white draped gown pose side by side at the Tribeca Festival. Her hand rests on his chest. Without the names. This draft comes from a saved run, not a live one. | ai_review | default |
| `draft-2` | Description draft with Save my edit, Discard my edit, and Reject this draft. Rejected notice: You rejected this draft, so Apply is off. Edit and save the text, or change an answer about a face, to get a new draft. | form | default, error |

Actions: `save` Save my edit → `apply`; `discard` Discard my edit → `draft`; `reject` Reject this draft → `draft`.

### See it run live (`live`)

Purpose: Optional. Send the same photo to the real service and watch it work. The result sits beside the saved draft; it never replaces it, and it never changes what Apply would write.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `live-0` | See it run live: A live run never changes the draft above, and it never changes what Apply would write. | content | default |
| `live-1` | Names come from your roster on the server, not from this page. Confirmed here: {names}. Otherwise: You have not confirmed anyone here yet. | content | default |
| `live-2` | Live run status, colour always paired with a glyph (• waiting, … working, ✓ done, ! degraded or timed out, × stopped): Ready when you are. / Queued. Waiting for the service to pick it up. / Starting the GPU. A cold start can take several minutes. / Describing the photo now. / Done. The GPU wrote this. / Done, but the GPU was not available, so the CPU wrote this. It is rougher than a GPU description. / Stopped waiting. The run may still finish on its own; nothing was applied here. / You stopped the wait. Nothing was applied. / The live run could not finish. Nothing was applied. Elapsed while waiting: 1:05 of up to 8:30. | status | default, loading, degraded, error |
| `live-3` | Describe it live and Stop waiting. Describe it live is off until every face match is decided: Decide each face match first, then you can describe this photo live. That is the lesson's order, not something the run needs. It is off entirely when the demo has no live photo: No live photo is configured for this demo, so the live run is off. | form | default, loading |
| `live-4` | The live sentence, quoted beside the saved draft and never written into it. | ai_review | default, degraded |

Actions: `describe-live` Describe it live → `live`; `stop-live` Stop waiting → `live`. Describe it live is a costly action: it can wake a stopped GPU, so the wait is shown honestly in minutes rather than behind a spinner, and it is disabled until every face match is decided. Every terminal state — done, degraded to CPU, timed out, cancelled, failed — says what happened and that nothing was applied; none of them touch the draft above or what Apply would write.

### Apply it yourself (`apply`)

Purpose: Nothing changes until you press Apply. Pressing Apply writes the saved draft to this practice copy only.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `apply-0` | The practice copy says {appliedText}; pressing Apply writes the saved draft to this practice copy only | ai_review | default, error |
| `apply-1` | Apply to practice copy and Undo; Apply is off while your edit is unsaved | form | default, error |

Actions: `apply-now` Apply to practice copy → `result`; `undo` Undo → `apply`.

### Applied result and history (`result`)

Purpose: Applied value is separate from draft; history preserves original revisions and shows an empty state before any decisions are recorded; the Reset practice trigger lives in the workspace header.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `result-0` | Applied description and unchanged original media scope | content | default |
| `result-1` | Chronological decision history; empty state before any decisions. History labels: You confirmed the face match: {name}. You kept the person on the {position} unnamed. | status | default, empty |
| `result-2` | Reset practice trigger in the workspace header | nav | default |

Action: `reset-open` Reset practice → `reset`.

### Reset practice confirmation (`reset`)

Purpose: Radix dialog overlay; safe default Cancel preserves unsaved and saved edits; danger-styled Reset practice confirm clears session state and pending buffer then focuses the scenario.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `reset-0` | Explicit effects: remove practice changes, preserve original WordPress attachment | content | default |
| `reset-1` | Cancel / Reset practice; Escape cancels | form | default |

Actions: `keep` Cancel → `draft`; `reset-confirm` Reset practice → `evidence`.

### Image unavailable, text evidence remains (`image-fallback`)

Purpose: Image load failure does not invent a rendered photograph or prevent practice decisions.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `image-fallback-0` | Visible image unavailable explanation: Sample photo unavailable. A man in a black tuxedo and a woman in a white draped gown pose side by side at the Tribeca Festival. Her hand rests on his chest.; independent visual facts remain available | status | default |
| `image-fallback-1` | Sample record and text-based review remain available | ai_review | default |

### Authoritative case study (`case-study`)

Purpose: External destination in a new tab; browser owns network failure; closing it returns to the practice tab.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `case-study-0` | Case study content | content | default |

## Actions

| id | screen | verb | target | hierarchy |
| --- | --- | --- | --- | --- |
| `open` | `intro` | Start the demo | `guide` | primary |
| `toggle-guide` | `guide` | Show steps / Hide steps | `guide` | secondary |
| `skip-guide` | `guide` | Skip to this step | `evidence` | tertiary |
| `guide-step` | `guide` | Choose a step | `draft` | secondary |
| `end-guide` | `guide` | Close the steps | `evidence` | tertiary |
| `confirm-katy-perry` | `face` | Yes, this is Katy Perry | `draft` | secondary |
| `unnamed-katy-perry` | `face` | Keep this person unnamed | `draft` | tertiary |
| `confirm-justin-trudeau` | `face` | Yes, this is Justin Trudeau | `draft` | secondary |
| `unnamed-justin-trudeau` | `face` | Keep this person unnamed | `draft` | tertiary |
| `save` | `draft` | Save my edit | `apply` | primary |
| `discard` | `draft` | Discard my edit | `draft` | tertiary |
| `reject` | `draft` | Reject this draft | `draft` | secondary |
| `describe-live` | `live` | Describe it live | `live` | primary |
| `stop-live` | `live` | Stop waiting | `live` | secondary |
| `apply-now` | `apply` | Apply to practice copy | `result` | primary |
| `undo` | `apply` | Undo | `apply` | tertiary |
| `reset-open` | `result` | Reset practice | `reset` | tertiary |
| `keep` | `reset` | Cancel | `draft` | primary |
| `case` | `intro` | Read the AltContext case study | `case-study` | secondary |
| `reset-confirm` | `reset` | Reset practice | `evidence` | destructive |

## Flows

| id | job | label |
| --- | --- | --- |
| `both-named` | `review` | Confirm both matches → both names in the draft → apply → undo |
| `one-named` | `review` | Confirm one match, keep the other unnamed → one name in the draft, other person described |
| `nobody-named` | `review` | Keep both people unnamed → visual-only draft |
| `live-run` | `review` | Run the same photo live → the live sentence sits beside the saved draft |
| `pending` | `review` | Save or discard your edit before Apply |
| `undo-flow` | `recover` | Apply two edits and undo in order |
| `reset-flow` | `recover` | Cancel or confirm reset safely |
| `image-error` | `review` | The photo is unavailable, but text lets you keep practising |

### Confirm both matches → both names in the draft → apply → undo (`both-named`)

| screen | action / expected copy |
| --- | --- |
| `intro` | Start the demo |
| `guide` | Find the faces → Confirm each match |
| `evidence` | Photo → 2 faces found |
| `face` | confirm-justin-trudeau: Yes, this is Justin Trudeau; confirm-katy-perry: Yes, this is Katy Perry |
| `draft` | Expected: You confirmed both matches, so both names are in the draft. The visual details and page context stay the same. |
| `apply` | apply-now: Apply to practice copy |
| `result` | Both names are in the applied draft. |
| `apply` | undo: Undo |

### Confirm one match, keep the other unnamed → one name in the draft, other person described (`one-named`)

| screen | action / expected copy |
| --- | --- |
| `intro` | Start the demo |
| `guide` | Find the faces → Confirm each match |
| `evidence` | Photo → 2 faces found |
| `face` | confirm-katy-perry: Yes, this is Katy Perry + unnamed-justin-trudeau: Keep this person unnamed (or confirm-justin-trudeau + unnamed-katy-perry) |
| `draft` | Expected: You confirmed one match, so one name is in the draft. The other person is described, not named. |
| `apply` | apply-now: Apply to practice copy |
| `result` | One name is in the applied draft; the other person is described, not named. |

### Keep both people unnamed → visual-only draft (`nobody-named`)

| screen | action / expected copy |
| --- | --- |
| `intro` | Start the demo |
| `guide` | Find the faces → Confirm each match |
| `evidence` | Photo → 2 faces found |
| `face` | unnamed-justin-trudeau: Keep this person unnamed + unnamed-katy-perry: Keep this person unnamed |
| `draft` | Expected: You kept both people unnamed, so the draft only says what is visible. |
| `apply` | apply-now: Apply to practice copy |
| `result` | Visual-only draft applied. |

### Run the same photo live → the live sentence sits beside the saved draft (`live-run`)

| screen | action / expected copy |
| --- | --- |
| `face` | Decide each face match first |
| `live` | describe-live: Describe it live |
| `live` | Starting the GPU. A cold start can take several minutes. |
| `live` | Done. The GPU wrote this. Or: stop-live: Stop waiting |
| `draft` | The saved draft is unchanged; Apply still writes the saved draft |

### Save or discard your edit before Apply (`pending`)

| screen | action / expected copy |
| --- | --- |
| `draft` | save: Save my edit or discard: Discard my edit |
| `apply` | Apply is off while your edit is unsaved |
| `result` | Saved draft is ready for Apply |

### Apply two edits and undo in order (`undo-flow`)

| screen | action / expected copy |
| --- | --- |
| `draft` | Save the first edit |
| `apply` | apply-now: Apply to practice copy |
| `result` | Applied value is separate from draft |
| `draft` | Save the second edit |
| `apply` | apply-now: Apply to practice copy |
| `result` | Chronological decision history |
| `apply` | undo: Undo |

### Cancel or confirm reset safely (`reset-flow`)

| screen | action / expected copy |
| --- | --- |
| `draft` | reset-open: Reset practice |
| `reset` | keep: Cancel or reset-confirm: Reset practice |
| `evidence` | Cancel preserves edits; Reset practice clears session state |

### The photo is unavailable, but text lets you keep practising (`image-error`)

| screen | action / expected copy |
| --- | --- |
| `image-fallback` | Sample photo unavailable; text evidence remains |
| `draft` | Check the description |
| `apply` | Apply it yourself |

## Open questions

- Saved-run provenance note: recognition engine InsightFace buffalo_l on the AltContext recognition service (dev build); saved run 2026-09-06; Saved from a real run on 2026-09-06, not a live run; threshold 0.6; Tribeca press photo similarities: Justin Trudeau on the left 0.686 and Katy Perry on the right 0.742.
- Cluster ids from the dev tenant: Katy Perry 68adc97c-f81f-42c3-9e5c-061f16770361 (11 photos; 5 saved photos shown in the bundled gallery) and Justin Trudeau fd0d2b5d-108a-42b7-af25-f028e40d5778 (8 photos; 2 saved photos shown).
- Also checked for provenance: a Coachella press photo of the same two people matched both, even with a hand over her mouth. It is not bundled because of licensing.
- Live recognition versus live description: the demo now describes the photo live on demand, but the face matches and the names still come from the saved run and the server-side roster. If live recognition also ships, show a fresh timestamp and drop the saved-run disclosure; keep the engine name out of screen copy.

## Parity index

Machine-checked by `js/admin/__tests__/uxmap-parity.test.ts` and
`js/admin/__tests__/uxmap-render-parity.test.ts`: every id, state, and verbatim label
below must exist in the sibling `.uxmap.json`, and no `z-*`/`act-*` id may appear here
that the JSON does not define. Regenerate with `docs/ux-maps/render_ux_maps.py` when the
renderer dependency is available.

Zone ids: intro-0 intro-1 guide-0 guide-1 evidence-0 evidence-1 face-0 face-1 face-2 draft-0 draft-1 draft-2 live-0 live-1 live-2 live-3 live-4 apply-0 apply-1 result-0 result-1 result-2 reset-0 reset-1 image-fallback-0 image-fallback-1 case-study-0

Action ids: open toggle-guide skip-guide guide-step end-guide confirm-katy-perry unnamed-katy-perry confirm-justin-trudeau unnamed-justin-trudeau save discard reject describe-live stop-live apply-now undo reset-open keep case reset-confirm

Zone labels (verbatim; the tables above escape `|` for markdown, this list does not):

- Guided demo, scope, and current build status: This demo uses one saved face-match run. Descriptions can run live on the real GPU.
- Start the demo and read the AltContext case study
- Current step, Skip to this step, and Show steps / Hide steps
- Five steps: Look at the photo — See the photo and the page it sits on.; Find the faces — AltContext found two faces and matched each one to a person you named before.; Confirm each match — Say yes to each match, or keep that person unnamed.; Check the description — Read the draft. Edit it or reject it.; Apply it yourself — Nothing changes until you press Apply.; Close the steps
- The photo; Alt text on the page right now: Two people at a film festival.; Photo credit: Colleen Sturtevant, CC BY-SA 4.0.; AltContext found two faces in this photo. The next step shows the matches.
- Saved run — How two faces become two names in the description. AltContext looks at the photo, finds each face, and checks it against people you already named. If you confirm a match, that name goes into the description. You always have the last word. Where this example comes from: Example — Saved from a real run, not a live run; Page — Tribeca Festival 2026: red carpet photos; People on file — Katy Perry (5 saved photos) · Justin Trudeau (2 saved photos); Photo credit — Colleen Sturtevant, CC BY-SA 4.0.; Also checked — A Coachella press photo of the same two people matched both, even with a hand over her mouth. It is not bundled because of licensing.; Flow strip (How the faces reach the description) — Photo · 2 faces found · Matched to Justin Trudeau and Katy Perry · You confirm each match · Names in the description.
- Face crops and matches: Face on the left — It matches a person you named before: Justin Trudeau. ✓ Match strength: strong. This face is close to the 2 saved photos of Justin Trudeau.; Face on the right — It matches a person you named before: Katy Perry. ✓ Match strength: strong. This face is close to the 5 saved photos of Katy Perry.; Her face is turned a little to the side.; Saved photos of Justin Trudeau: 2 of 2 shown.; Saved photos of Katy Perry: 3 of 5 shown.
- How this works: 1. AltContext finds every face in the photo. 2. It compares each face to the people you already named. 3. It asks you to confirm each match. Nothing is named without your OK. These matches were saved from a real run. The demo does not run recognition live.
- Decision status: You have not decided yet. / You confirmed: Justin Trudeau. / You confirmed: Katy Perry. / You kept this person unnamed. Decisions block: Confirm each match. Justin Trudeau, face on the left — Yes, this is Justin Trudeau / Keep this person unnamed. Katy Perry, face on the right — Yes, this is Katy Perry / Keep this person unnamed. Changing an answer swaps in a different saved draft. Save or discard your edit first. Buttons are disabled and described by this note while an edit is unsaved; confirm is disabled when already confirmed; unnamed is disabled when already unidentified. Feedback: Match confirmed. {name} is in the draft. Nothing is applied yet. The person on the {position} stays unnamed. You can still check the description.
- Ready for you to check, Edited by you, or Rejected. The saved text did not change. Both confirmed: You confirmed both matches, so both names are in the draft. The visual details and page context stay the same. One confirmed: You confirmed one match, so one name is in the draft. The other person is described, not named. None confirmed, all decided: You kept both people unnamed, so the draft only says what is visible. Otherwise: Confirm or skip each face match first. Until then the draft only says what is visible.
- Draft without names: A man in a black tuxedo and a woman in a white draped gown pose side by side at the Tribeca Festival. Her hand rests on his chest. Without the names. This draft comes from a saved run, not a live one.
- Description draft with Save my edit, Discard my edit, and Reject this draft. Rejected notice: You rejected this draft, so Apply is off. Edit and save the text, or change an answer about a face, to get a new draft.
- See it run live: A live run never changes the draft above, and it never changes what Apply would write.
- Names come from your roster on the server, not from this page. Confirmed here: {names}. Otherwise: You have not confirmed anyone here yet.
- Live run status, colour always paired with a glyph (• waiting, … working, ✓ done, ! degraded or timed out, × stopped): Ready when you are. / Queued. Waiting for the service to pick it up. / Starting the GPU. A cold start can take several minutes. / Describing the photo now. / Done. The GPU wrote this. / Done, but the GPU was not available, so the CPU wrote this. It is rougher than a GPU description. / Stopped waiting. The run may still finish on its own; nothing was applied here. / You stopped the wait. Nothing was applied. / The live run could not finish. Nothing was applied. Elapsed while waiting: 1:05 of up to 8:30.
- Describe it live and Stop waiting. Describe it live is off until every face match is decided: Decide each face match first, then you can describe this photo live. That is the lesson's order, not something the run needs. It is off entirely when the demo has no live photo: No live photo is configured for this demo, so the live run is off.
- The live sentence, quoted beside the saved draft and never written into it.
- The practice copy says {appliedText}; pressing Apply writes the saved draft to this practice copy only
- Apply to practice copy and Undo; Apply is off while your edit is unsaved
- Applied description and unchanged original media scope
- Chronological decision history; empty state before any decisions. History labels: You confirmed the face match: {name}. You kept the person on the {position} unnamed.
- Reset practice trigger in the workspace header
- Explicit effects: remove practice changes, preserve original WordPress attachment
- Cancel / Reset practice; Escape cancels
- Visible image unavailable explanation: Sample photo unavailable. A man in a black tuxedo and a woman in a white draped gown pose side by side at the Tribeca Festival. Her hand rests on his chest.; independent visual facts remain available
- Sample record and text-based review remain available
- Case study content

States (all zones and screens): default first_time error empty loading degraded

## Not doing

- Public homepage or marketing deployment
- Guest-session authentication or credentials settings
- Applying a live result automatically, or letting a live run rewrite the saved draft
- Multi-scenario library and production privacy settings
- Full WordPress or screen-reader conformance claim from component-only browser tests
