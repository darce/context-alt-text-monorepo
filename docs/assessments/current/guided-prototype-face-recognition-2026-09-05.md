# Guided prototype: face recognition stage and plain-language copy (GPFACE-1)

Date: 2026-09-05 · Task: `GPFACE-1` · Branch: `feature/gpface-1`
Decision: handoff decision 8617.

## 1. Defect

The deployed tour (`#/guided-prototype`) says the person's name comes from
"sample record metadata" and that this "is not facial identification by the
tour". The product's real path is: find a face, match it to a person the site
owner already named, ask the editor to confirm, then use the name in the
description (`scene/application/identity_merge/merge.py:merge_identities`,
naming-policy consent gate). The tour hides the feature it exists to show.
The copy also reads like an internal spec ("provenance", "candidate",
"scenarioVersion", "identity-informed").

## 2. Target behaviour

```
photo  ->  face found  ->  matched to a known person  ->  you confirm  ->  name enters the description
```

- Matching is shown as evidence before the label (HAI-01): the face crop, the
  person it matched, and how many saved photos it resembles (HAI-08, no bare
  percentage).
- Nothing is named until the editor says yes (HAI-04, SEC-05 analogue).
- The demo discloses that the match is stored from an earlier run, not live
  (HAI-05).
- Every status pairs an icon or word with colour (A11Y-06); every control has a
  visible name (A11Y-04); the face crop has alt text (A11Y-02).
- Copy target: short sentences, everyday words, one idea per sentence
  (WRIT-02, WRIT-06). No "provenance", "candidate", "scenario", "inference".

## 3. State contract (lane L1 owns `state.ts`; every lane codes against this)

```ts
export type GuidedIdentityStatus = 'unconfirmed' | 'confirmed' | 'unidentified';
export type GuidedMatchStrength = 'strong' | 'weak';

export interface GuidedFaceMatch {
  faceCount: number;                        // 1 for the sample photo
  box: { x: number; y: number; width: number; height: number }; // pixels in the 1388x1777 sample
  matchedPersonName: string;                // 'Keanu Reeves'
  similarPhotoCount: number;                // 3
  strength: GuidedMatchStrength;            // 'strong'
  source: 'saved-example';                  // stored earlier, not run live (HAI-05)
}

export interface GuidedIdentity {
  status: GuidedIdentityStatus;
  name?: string;
  source: 'face-match' | 'none';            // was 'sample-record' | 'none'
}

export interface GuidedScenario {
  // unchanged: origin, scenarioVersion, originalMedia, pageContext, visualFacts,
  // genericDraft, namedDraft, unnamedDraft, candidate, appliedText, history
  sourceRecord: { name: string; credit: string; note: string }; // note text changes, see copy deck
  faceMatch: GuidedFaceMatch;               // NEW
  identity: GuidedIdentity;
}
```

Seed values: `faceMatch = { faceCount: 1, box: { x: 370, y: 320, width: 660, height: 800 }, matchedPersonName: 'Keanu Reeves', similarPhotoCount: 3, strength: 'strong', source: 'saved-example' }`.
`scenarioVersion` becomes `'guided-portrait-v2'`.

Function contract (names unchanged): `confirmGuidedIdentity` sets
`identity = { status: 'confirmed', name: faceMatch.matchedPersonName, source: 'face-match' }`
and `candidate.text = namedDraft`. `leaveGuidedIdentityUnidentified` keeps
`source: 'none'` and `candidate.text = unnamedDraft`. The name guard
`assertCandidateIdentity` requires `source === 'face-match'` and throws
`'You can only use the name after you confirm the face match.'`
History event kinds are unchanged.

## 4. Copy deck (every visible string; lanes copy these verbatim)

### Entrance (`GuidedPrototypeEntrance.tsx`, lane L3)

| Slot | Text |
| --- | --- |
| eyebrow | Guided demo |
| h1 | AltContext guided demo |
| intro | Follow one photo from start to finish. AltContext finds a face, matches it to a person you already named, and puts that name in the image description. You choose what gets saved. |
| status label | Current build |
| status text | This demo uses one saved example. It does not run live recognition. |
| CTA button | Start the demo |
| boundary | This is a practice copy. Changes stay in this tab and reset when you reload the page. Live recognition and guest access are still in progress. |
| case-study link | Read the AltContext case study |

### Guide (`GuidedPrototypeGuide.tsx`, lane L3)

`GuidedGuideStep = 'understand' | 'face' | 'identity' | 'review' | 'apply'`.
`GUIDED_SECTION_IDS.face = 'guided-section-face'` (rendered by lane L2 inside the review block).

| id | label | description |
| --- | --- | --- |
| understand | Look at the photo | See the photo and the page it sits on. |
| face | Find the face | AltContext found a face and matched it to a person you named before. |
| identity | Confirm the match | Say yes to the match, or keep the person unnamed. |
| review | Check the description | Read the draft. Edit it or reject it. |
| apply | Apply it yourself | Nothing changes until you press Apply. |

Bar eyebrow: `Step by step`. Skip link: `Skip to this step`. Toggle: `Show steps` / `Hide steps`. End: `Close the steps`. Nav aria-label stays `Guided review steps`.

### Page shell (`GuidedPrototypePage.tsx`, lane L3)

| Slot | Text |
| --- | --- |
| hero eyebrow | Saved example |
| hero h2 | How a face becomes a name in the description |
| hero p | AltContext looks at the photo, finds a face, and checks it against people you already named. If you confirm the match, the name goes into the description. You always have the last word. |
| scenario section aria-label | Photo and page |
| provenance h3 | Where this example comes from |
| dt/dd 1 | Example / Saved example, not a live run |
| dt/dd 2 | Page / {pageContext.title} |
| dt/dd 3 | Person on file / {sourceRecord.name} · photo credit {sourceRecord.credit} |
| history eyebrow | What you did |
| history h2 | Your decisions |
| history empty | Nothing yet. Your next action will show up here. |

Flow strip (new, rendered by L3 directly under the hero, `<ol aria-label="How the face reaches the description">`), one item per stage with a state word in brackets: `Photo` · `Face found` · `Matched to Keanu Reeves` · `You confirm` · `Name in the description`. State words: `done`, `now`, `waiting`; stages 1 to 3 are always `done`, stage 4 is `now` until the identity decision, stage 5 is `done` only when `identity.status === 'confirmed'`, `skipped` when unidentified.

History labels: identity-confirmed `You confirmed the face match: {name}.` · identity-unidentified `You kept the person unnamed.` · edit-saved `You saved an edit.` · rejected `You rejected the draft. The saved text did not change.` · applied `You applied the draft to the practice copy.` · application-undone `You undid the apply.`

Feedback messages: begin `The steps are open. Start with the photo.` · select `Now on: {label}.` · end `Steps closed. You can keep practising.` · confirm `Match confirmed. The name is in the draft. Nothing is applied yet.` · unidentified `The person stays unnamed. You can still check the description.` · save `Your edit is saved and ready to check.` · reject `Draft rejected. The saved text did not change.` · apply `Applied to the practice copy.` · undo `Apply undone.` · reset `Practice reset. The original text is back.`

### Sample photo (`GuidedSamplePhoto.tsx`, lane L3)

figcaption: `The photo` (strong) · `Alt text on the page right now: {mediaAltText}` · `Photo credit: {credit}.` · `AltContext found one face in this photo. The next step shows the match.`

### Reset dialog (`GuidedResetDialog.tsx`, lane L3)

Trigger `Reset practice`. Title `Reset this practice?` Body `This removes your practice changes. The real WordPress image is not touched.` Buttons `Cancel` (default) / `Reset practice`.

### Face match card (new `GuidedFaceMatchCard.tsx`, mounted inside `GuidedDescriptionReview.tsx`, lane L2)

Replaces the old "Identity evidence" card. Root `<div id="guided-section-face" tabIndex={-1} aria-labelledby="guided-face-match-title">`.

| Slot | Text |
| --- | --- |
| h3 | Face found in the photo |
| face crop | `FaceThumbnail` (`components/ui/FaceThumbnail`) size `lg`, shape `square`, `mediaUrl` = sample photo, `bbox` = `faceMatch.box`, alt `Face found in the photo` |
| found line | AltContext found 1 face. |
| match line | It matches a person you named before: **Keanu Reeves**. |
| strength line | Match strength: strong. This face is close to 3 saved photos of Keanu Reeves. (icon ✓ + word, never colour alone) |
| how-it-works list (`<ol>`) | 1. AltContext finds faces in the photo. 2. It compares each face to people you already named. 3. It asks you to confirm. Nothing is named without your OK. |
| disclosure | This match was saved from an earlier run. The demo does not run recognition live. |
| decision status | unconfirmed `You have not decided yet.` · confirmed `You confirmed: Keanu Reeves.` · unidentified `You kept the person unnamed.` |
| change note (id `guided-identity-change-reason`) | Changing your answer swaps in a different saved draft. Save or discard your edit first. |
| actions wrapper | `<div id="guided-section-identity" tabIndex={-1} aria-label="Confirm the match">` |
| confirm button | Yes, this is Keanu Reeves |
| unnamed button | Keep the person unnamed |

### Description review (`GuidedDescriptionReview.tsx`, lane L2)

| Slot | Text |
| --- | --- |
| header eyebrow | The description |
| header h2 | Check the description before anything changes |
| status pill | ready `Ready for you to check` · edited `Edited by you` · rejected `Rejected. The saved text did not change` |
| visual card h3 | What the photo shows |
| visual card draft line | Draft without a name: {genericDraft} |
| visual card applied line | Alt text on the page right now: {appliedText} |
| page card h3 | The page |
| explanation confirmed | You confirmed the match, so the name is in the draft. The visual details and page context stay the same. |
| explanation unidentified | You kept the person unnamed, so the draft only says what is visible. |
| explanation unconfirmed | Confirm or skip the face match first. Until then the draft only says what is visible. |
| before h3 | Without the name |
| proposed h3 | Draft for you to check |
| origin line | This draft comes from a saved example, not a live run. |
| textarea label | Description draft |
| empty error | A description cannot be empty. |
| rejected notice | You rejected this draft, so Apply is off. Edit and save the text, or change your answer about the face, to get a new draft. |
| unsaved notice | Unsaved edit. Save it before you apply, or discard it to go back to the saved draft. |
| buttons | Save my edit · Discard my edit · Reject this draft |
| apply h3 | Apply it yourself |
| apply body | The practice copy says **{appliedText}**. Pressing Apply writes the saved draft to this practice copy only. |
| apply blocked | Apply is off while your edit is unsaved. Save or discard it first. |
| apply buttons | Apply to practice copy · Undo |

## 5. ASCII screens (iterated against the canon)

### S2 Face found (new)

```
+--------------------------------------------------------------+
| 2. Find the face                                             |
|                                                              |
|  +--------+   AltContext found 1 face.                       |
|  | [face] |   It matches a person you named before:          |
|  | crop   |   Keanu Reeves.                                  |
|  +--------+   (v) Match strength: strong. This face is close |
|               to 3 saved photos of Keanu Reeves.             |
|                                                              |
|  How this works                                              |
|  1. AltContext finds faces in the photo.                     |
|  2. It compares each face to people you already named.       |
|  3. It asks you to confirm. Nothing is named without your OK.|
|                                                              |
|  (i) This match was saved from an earlier run. The demo does |
|      not run recognition live.                               |
|                                                              |
|  You have not decided yet.                                   |
|  [ Yes, this is Keanu Reeves ]  [ Keep the person unnamed ]  |
+--------------------------------------------------------------+
```

Canon check: HAI-01 evidence (crop, count, similar photos) precedes the name;
HAI-08 uncertainty stated as "close to 3 saved photos", not a percentage;
HAI-05 disclosure present; A11Y-04 both buttons name the outcome; A11Y-06 the
strength line pairs icon + word; INT-* both choices reachable from zero state
(rg-003).

### S0 Flow strip (new, under the hero)

```
 Photo [done] -> Face found [done] -> Matched to Keanu Reeves [done]
   -> You confirm [now] -> Name in the description [waiting]
```

After "Keep the person unnamed": last stage reads `[skipped]`.
After "Yes, this is Keanu Reeves": `You confirm [done] -> Name in the description [done]`.

### S3 Check the description (revised copy)

```
+--------------------------------------------------------------+
| The description                       [Ready for you to check]|
| Check the description before anything changes                |
|                                                              |
| You confirmed the match, so the name is in the draft. The    |
| visual details and page context stay the same.               |
|                                                              |
|  Without the name          | Draft for you to check          |
|  Portrait of a person in a | This draft comes from a saved   |
|  grey jacket.              | example, not a live run.        |
|                            | [Description draft            ] |
|                            | [Keanu Reeves wears a grey    ] |
|                            | [jacket against a plain bg.   ] |
|                            | [Save my edit] [Reject this draft]|
+--------------------------------------------------------------+
```

## 6. Slice DAG (GRPH-01 toposort, GRPH-06 components, GRPH-32 edges only where data moves)

Nodes and the data each edge carries:

```
N0 contract (this doc: types + copy deck + section ids)          [coordinator, done]
 |-- types+copy --> N1 state        state.ts, state.test.ts                    [codex-remote]
 |-- types+copy --> N2 face card    GuidedFaceMatchCard.tsx, GuidedDescriptionReview.tsx,
 |                                  __tests__/GuidedFaceMatchCard.test.tsx, _guided-prototype.scss [codex-remote]
 |-- copy+ids  --> N3 shell         Guide/Entrance/SamplePhoto/Page/ResetDialog,
 |                                  __tests__/GuidedPrototypePage.test.tsx     [codex-remote]
 '-- screens   --> N4 ux-map        guided-prototype.uxmap.json + rendered .md [codex-remote]
N1,N2,N3,N4 --branches--> N5 integrate (merge lanes, tsc, vitest, lint, stylelint) [coordinator]
N5 --HEAD sha--> N6 review wave: R-local (1, claude) || R-a11y/HAI || R-writing || R-eng   [parallel]
N6 --findings--> N7 fix wave, one lane per connected component of findings (GRPH-06)     [parallel]
N7 --HEAD sha--> N8 close: handoff_close_check(enforce) -> merge main -> task-finish -> deploy
```

- Wave 1 width 4 (N1..N4). Critical path N0 -> N1 -> N5 -> N6 -> N7 -> N8 (GRPH-31).
- Cut vertices (GRPH-05): N0 and N5. Both are small coordinator steps; N0 is
  frozen before dispatch so lanes never read a moving contract (GRPH-39).
- No cycles (GRPH-02): N2 and N3 share section ids and strings through N0 only,
  never through each other. File ownership is disjoint, so merges are
  conflict-free by construction.
- Remote sandboxes have no `node_modules`; the coordinator runs tsc and vitest
  locally at N5 before recording green evidence.
