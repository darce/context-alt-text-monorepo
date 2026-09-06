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
| `understand` | screen | `#/guided-prototype` | Look at the photo |
| `face` | screen | `#/guided-prototype` | Find the faces |
| `identity` | screen | `#/guided-prototype` | Confirm each match |
| `review` | screen | `#/guided-prototype` | Check the description |
| `apply` | screen | `#/guided-prototype` | Apply it yourself |
| `result` | screen | `#/guided-prototype` | Applied result and history |
| `reset` | overlay | `#/guided-prototype` | Reset practice confirmation |
| `image-fallback` | screen | `#/guided-prototype` | Image unavailable, text evidence remains |
| `case-study` | exit | `https://darce.xyz/projects/altcontext/` | Authoritative case study |

## Code references

- `screen:intro` — `apps/prototype-wp-alt-context/js/admin/pages/GuidedPrototypeEntrance.tsx`
- `screen:guide` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedPrototypeGuide.tsx`
- `screen:understand` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedPrototypePage.tsx`
- `screen:face` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedFaceMatchCard.tsx`
- `screen:identity` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedFacesPanel.tsx`
- `screen:review` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedDescriptionReview.tsx`
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
```

## Screen inventories

### AltContext guided demo (`intro`)

Purpose: Follow one photo from start to finish. AltContext finds two faces, matches each one to a person you already named, and puts their names in the image description. You choose what gets saved.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `intro-0` | Guided demo, scope, and current build status: This demo uses one saved run. It does not run recognition live. | content | default |
| `intro-1` | Start the demo and read the AltContext case study | nav | default |

Actions: `open` Start the demo → `guide`; `case` Read the AltContext case study → `case-study`.

### Step by step (`guide`)

Purpose: Five steps show the path from the photo to the description: Look at the photo, Find the faces, Confirm each match, Check the description, and Apply it yourself.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `guide-0` | Current step, Skip to this step, and Show steps / Hide steps | nav | default |
| `guide-1` | Five steps: Look at the photo — See the photo and the page it sits on.; Find the faces — AltContext found two faces and matched each one to a person you named before.; Confirm each match — Say yes to each match, or keep that person unnamed.; Check the description — Read the draft. Edit it or reject it.; Apply it yourself — Nothing changes until you press Apply.; Close the steps | nav | default |

Actions: `toggle-guide` Show steps / Hide steps → `guide`; `skip-guide` Skip to this step → `understand`; `guide-step` Choose a step → `review`; `end-guide` Close the steps → `understand`.

### Look at the photo (`understand`)

Purpose: See the photo and the page it sits on.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `understand-0` | The photo; Alt text on the page right now: Two people at a film festival.; Photo credit: Colleen Sturtevant, CC BY-SA 4.0, resized for this demo.; AltContext found two faces in this photo. The next step shows the matches. | ai_review | default |
| `understand-1` | Saved run — How two faces become two names in the description. AltContext looks at the photo, finds each face, and checks it against people you already named. If you confirm a match, that name goes into the description. You always have the last word. Where this example comes from: Example — Saved from a real run, not a live run; Page — Tribeca Festival 2026: red carpet photos; People on file — Katy Perry (5 saved photos) · Justin Trudeau (2 saved photos); Photo credit — Colleen Sturtevant, CC BY-SA 4.0, resized for this demo.; Also checked — A Coachella press photo of the same two people matched both, even with a hand over her mouth. It is not bundled because of licensing.; Flow strip (How the faces reach the description) — Photo · 2 faces found · Matched to Justin Trudeau and Katy Perry · You confirm each match · Names in the description. | content | default |

### Find the faces (`face`)

Purpose: AltContext found 2 faces. Each one matched a person you named before.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `face-0` | Face crops and matches: Face on the left — It matches a person you named before: Justin Trudeau. ✓ Match strength: strong. This face is close to the 2 saved photos of Justin Trudeau.; Face on the right — It matches a person you named before: Katy Perry. ✓ Match strength: strong. This face is close to the 5 saved photos of Katy Perry.; Her face is turned a little to the side.; Saved photos of Justin Trudeau: 2 of 2 shown.; Saved photos of Katy Perry: 3 of 5 shown. | ai_review | first_time, default |
| `face-1` | How this works: 1. AltContext finds every face in the photo. 2. It compares each face to the people you already named. 3. It asks you to confirm each match. Nothing is named without your OK. These matches were saved from a real run. The demo does not run recognition live. | content | first_time, default |

### Confirm each match (`identity`)

Purpose: Say yes to each match, or keep that person unnamed.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `identity-0` | Decision status: You have not decided yet. / You confirmed: Justin Trudeau. / You confirmed: Katy Perry. / You kept this person unnamed. | status | first_time, default |
| `identity-1` | Confirm each match. Justin Trudeau, face on the left — Yes, this is Justin Trudeau / Keep this person unnamed. Katy Perry, face on the right — Yes, this is Katy Perry / Keep this person unnamed. Changing an answer swaps in a different saved draft. Save or discard your edit first. Feedback: Match confirmed. {name} is in the draft. Nothing is applied yet. The person on the {position} stays unnamed. You can still check the description. | form | first_time, default |

Actions: `confirm-katy-perry` Yes, this is Katy Perry → `review`; `unnamed-katy-perry` Keep this person unnamed → `review`; `confirm-justin-trudeau` Yes, this is Justin Trudeau → `review`; `unnamed-justin-trudeau` Keep this person unnamed → `review`. While an edit is unsaved, all decision buttons are disabled and described by the change note; the confirm button is disabled when already confirmed and the unnamed button is disabled when already unidentified.

### Check the description (`review`)

Purpose: Read the draft. Edit it or reject it. Nothing changes until you press Apply.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `review-0` | Ready for you to check, Edited by you, or Rejected. The saved text did not change. Both confirmed: You confirmed both matches, so both names are in the draft. The visual details and page context stay the same. One confirmed: You confirmed one match, so one name is in the draft. The other person is described, not named. None confirmed, all decided: You kept both people unnamed, so the draft only says what is visible. Otherwise: Confirm each face match or keep the person unnamed first. Until then the draft only says what is visible. | form | default |
| `review-1` | Draft without names: A man in a black tuxedo and a woman in a white draped gown pose side by side at the Tribeca Festival. Her hand rests on his chest. Without the names. This draft comes from a saved run, not a live one. | ai_review | default |
| `review-2` | Description draft with Save my edit, Discard my edit, and Reject this draft. Rejected notice: You rejected this draft, so Apply is off. Edit and save the text, or change an answer about a face, to get a new draft. | form | default, error |

Actions: `save` Save my edit → `apply`; `discard` Discard my edit → `review`; `reject` Reject this draft → `review`.

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

Actions: `keep` Cancel → `review`; `reset-confirm` Reset practice → `understand`.

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
| `skip-guide` | `guide` | Skip to this step | `understand` | tertiary |
| `guide-step` | `guide` | Choose a step | `review` | secondary |
| `end-guide` | `guide` | Close the steps | `understand` | tertiary |
| `confirm-katy-perry` | `identity` | Yes, this is Katy Perry | `review` | secondary |
| `unnamed-katy-perry` | `identity` | Keep this person unnamed | `review` | tertiary |
| `confirm-justin-trudeau` | `identity` | Yes, this is Justin Trudeau | `review` | secondary |
| `unnamed-justin-trudeau` | `identity` | Keep this person unnamed | `review` | tertiary |
| `save` | `review` | Save my edit | `apply` | primary |
| `discard` | `review` | Discard my edit | `review` | tertiary |
| `reject` | `review` | Reject this draft | `review` | secondary |
| `apply-now` | `apply` | Apply to practice copy | `result` | primary |
| `undo` | `apply` | Undo | `apply` | tertiary |
| `reset-open` | `result` | Reset practice | `reset` | tertiary |
| `keep` | `reset` | Cancel | `review` | primary |
| `case` | `intro` | Read the AltContext case study | `case-study` | secondary |
| `reset-confirm` | `reset` | Reset practice | `understand` | destructive |

## Flows

| id | job | label |
| --- | --- | --- |
| `both-named` | `review` | Confirm both matches → both names in the draft → apply → undo |
| `one-named` | `review` | Confirm one match, keep the other unnamed → one name in the draft, other person described |
| `nobody-named` | `review` | Keep both people unnamed → visual-only draft |
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
- Live recognition: the demo ships the saved result and does not run recognition live. If live recognition ships, show a fresh timestamp and drop the saved-run disclosure; keep the engine name out of screen copy.

## Parity index

Machine-checked by `js/admin/__tests__/uxmap-parity.test.ts` and
`js/admin/__tests__/uxmap-render-parity.test.ts`: every id, state, and verbatim label
below must exist in the sibling `.uxmap.json`, and no `z-*`/`act-*` id may appear here
that the JSON does not define. Regenerate with `docs/ux-maps/render_ux_maps.py` when the
renderer dependency is available.

Zone ids: intro-0 intro-1 guide-0 guide-1 understand-0 understand-1 face-0 face-1 identity-0 identity-1 review-0 review-1 review-2 apply-0 apply-1 result-0 result-1 result-2 reset-0 reset-1 image-fallback-0 image-fallback-1 case-study-0

Action ids: open toggle-guide skip-guide guide-step end-guide confirm-katy-perry unnamed-katy-perry confirm-justin-trudeau unnamed-justin-trudeau save discard reject apply-now undo reset-open keep case reset-confirm

Zone labels (verbatim; the tables above escape `|` for markdown, this list does not):

- Guided demo, scope, and current build status: This demo uses one saved run. It does not run recognition live.
- Start the demo and read the AltContext case study
- Current step, Skip to this step, and Show steps / Hide steps
- Five steps: Look at the photo — See the photo and the page it sits on.; Find the faces — AltContext found two faces and matched each one to a person you named before.; Confirm each match — Say yes to each match, or keep that person unnamed.; Check the description — Read the draft. Edit it or reject it.; Apply it yourself — Nothing changes until you press Apply.; Close the steps
- The photo; Alt text on the page right now: Two people at a film festival.; Photo credit: Colleen Sturtevant, CC BY-SA 4.0, resized for this demo.; AltContext found two faces in this photo. The next step shows the matches.
- Saved run — How two faces become two names in the description. AltContext looks at the photo, finds each face, and checks it against people you already named. If you confirm a match, that name goes into the description. You always have the last word. Where this example comes from: Example — Saved from a real run, not a live run; Page — Tribeca Festival 2026: red carpet photos; People on file — Katy Perry (5 saved photos) · Justin Trudeau (2 saved photos); Photo credit — Colleen Sturtevant, CC BY-SA 4.0, resized for this demo.; Also checked — A Coachella press photo of the same two people matched both, even with a hand over her mouth. It is not bundled because of licensing.; Flow strip (How the faces reach the description) — Photo · 2 faces found · Matched to Justin Trudeau and Katy Perry · You confirm each match · Names in the description.
- Face crops and matches: Face on the left — It matches a person you named before: Justin Trudeau. ✓ Match strength: strong. This face is close to the 2 saved photos of Justin Trudeau.; Face on the right — It matches a person you named before: Katy Perry. ✓ Match strength: strong. This face is close to the 5 saved photos of Katy Perry.; Her face is turned a little to the side.; Saved photos of Justin Trudeau: 2 of 2 shown.; Saved photos of Katy Perry: 3 of 5 shown.
- How this works: 1. AltContext finds every face in the photo. 2. It compares each face to the people you already named. 3. It asks you to confirm each match. Nothing is named without your OK. These matches were saved from a real run. The demo does not run recognition live.
- Decision status: You have not decided yet. / You confirmed: Justin Trudeau. / You confirmed: Katy Perry. / You kept this person unnamed.
- Confirm each match. Justin Trudeau, face on the left — Yes, this is Justin Trudeau / Keep this person unnamed. Katy Perry, face on the right — Yes, this is Katy Perry / Keep this person unnamed. Changing an answer swaps in a different saved draft. Save or discard your edit first. Feedback: Match confirmed. {name} is in the draft. Nothing is applied yet. The person on the {position} stays unnamed. You can still check the description.
- Ready for you to check, Edited by you, or Rejected. The saved text did not change. Both confirmed: You confirmed both matches, so both names are in the draft. The visual details and page context stay the same. One confirmed: You confirmed one match, so one name is in the draft. The other person is described, not named. None confirmed, all decided: You kept both people unnamed, so the draft only says what is visible. Otherwise: Confirm each face match or keep the person unnamed first. Until then the draft only says what is visible.
- Draft without names: A man in a black tuxedo and a woman in a white draped gown pose side by side at the Tribeca Festival. Her hand rests on his chest. Without the names. This draft comes from a saved run, not a live one.
- Description draft with Save my edit, Discard my edit, and Reject this draft. Rejected notice: You rejected this draft, so Apply is off. Edit and save the text, or change an answer about a face, to get a new draft.
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

States (all zones and screens): default first_time error empty

## Not doing

- Public homepage or marketing deployment
- Guest-session authentication or credentials settings
- Live generation
- Multi-scenario library and production privacy settings
- Full WordPress or screen-reader conformance claim from component-only browser tests
