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
| explanation unconfirmed | Decide each face match first: confirm it, or keep the person unnamed. Until then the draft only says what is visible. |
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

---

## 7. Wave 2 — two people, one press photo (`guided-people-v3`)

### 7.1 Why

Wave 1 kept the single Keanu Reeves example. The operator's scenario is: two people are named from their own
photos (Katy Perry, Justin Trudeau); a press photo shows both; both faces cluster to their labelled identities;
one coherent caption names both and keeps the visual details. Recognition ran for real on the AltContext dev
recognition service (InsightFace `buffalo_l`, commit `f66c5335`, similarity threshold 0.6) on 2026-09-06. The
demo ships the saved result; it never runs recognition live.

### 7.2 Recognition evidence (saved run, dev service, 2026-09-06)

| Photo | Person | Similarity | Box on bundled file | Note |
| --- | --- | --- | --- | --- |
| Tribeca red carpet, bundled `guided-press-tribeca-2026.jpg` (1400×933) | Justin Trudeau | 0.686 | `{x:514,y:77,width:132,height:189}` | face on the left |
| same | Katy Perry | 0.742 | `{x:707,y:140,width:121,height:181}` | face on the right, turned a little to the side |
| Coachella, The Guardian (evidence only, not bundled) | Katy Perry | 0.965 | — | hand over her mouth (occlusion) |
| same | Justin Trudeau | 0.972 | — | backwards cap |
| Coachella, noodles (evidence only) | Katy / Justin | 0.662 / 0.692 | — | small faces |
| Tribeca foreheads touching (evidence only) | Katy / Justin | none / 0.554 | — | both in profile, eyes closed |
| Representatives vs the press faces (local one-off, same buffalo_l, bundled sizes) | Katy Perry 2026 / 2019 / 2016 | 0.783 / 0.612 / 0.527 | each a single clear face, det ≥ 0.81 | `guided-katy-perry-{2026,2019,2016}.jpg` |
| same | Justin Trudeau 2025 crop / 2025 | 0.694 / 0.686 | single clear face, det ≥ 0.88 | `guided-justin-trudeau-2025{,-b}.jpg` |

Clusters on the dev tenant: Katy Perry `68adc97c-f81f-42c3-9e5c-061f16770361` (11 photos), Justin Trudeau
`fd0d2b5d-108a-42b7-af25-f028e40d5778` (8 photos). Saved gallery before the press photo: Katy Perry 5 photos
(Hotel Cafe 2026 ×3, Glenn Francis 2019, DNC 2016), Justin Trudeau 2 photos (European Commission 2025 ×2). The
entity representatives are built from clear, mostly frontal photos; the bundled gallery shows three of Katy Perry's
and both of Justin Trudeau's. Image licences: `apps/prototype-wp-alt-context/js/admin/assets/guided/CREDITS.md`.

### 7.3 State contract (lane `gpface-1-w2-l1-state` owns `state.ts`; `state.test.ts` is frozen)

```ts
export type GuidedCandidateStatus = 'ready' | 'edited' | 'rejected';
export type GuidedIdentityStatus = 'unconfirmed' | 'confirmed' | 'unidentified';
export type GuidedMatchStrength = 'strong' | 'weak';
export type GuidedPersonKey = 'katy-perry' | 'justin-trudeau';
export const GUIDED_PERSON_KEYS: readonly GuidedPersonKey[] = ['katy-perry', 'justin-trudeau'];
export type GuidedFacePosition = 'left' | 'right';
export type GuidedDraftKey = 'none' | 'katy-perry' | 'justin-trudeau' | 'both';
export interface GuidedFaceBox { x: number; y: number; width: number; height: number }
export interface GuidedGalleryPhoto { src: string; altText: string; credit: string }
export interface GuidedLabeledPerson {
  key: GuidedPersonKey; name: string; clusterId: string;
  savedPhotoCount: number;             // photos in the saved run
  galleryPhotos: GuidedGalleryPhoto[];  // clear representative photos from that run, newest first (bundled)
}
export interface GuidedFace {
  id: GuidedPersonKey;            // one face per person in this example: face id === matched person key
  position: GuidedFacePosition;   // plain-language handle: "the face on the left"
  box: GuidedFaceBox;             // on pressPhoto at bundled size (1400×933)
  matchedPersonKey: GuidedPersonKey;
  similarity: number;             // 0..1 from the saved run; never shown as a percentage
  strength: GuidedMatchStrength;  // 'strong' when similarity >= 0.6 (service threshold)
  note?: string;                  // e.g. 'Her face is turned a little to the side.'
  source: 'saved-run';
}
export interface GuidedIdentity { faceId: GuidedPersonKey; status: GuidedIdentityStatus; name?: string; source: 'face-match' | 'none' }
export interface GuidedHistoryEvent {
  kind: 'identity-confirmed' | 'identity-unidentified' | 'edit-saved' | 'rejected' | 'applied' | 'application-undone';
  faceId?: GuidedPersonKey; text?: string; previousAppliedText?: string;
}
export interface GuidedProvenance { service: string; model: string; runDate: string; threshold: number; note: string; alsoChecked: string }
export type GuidedScenarioOrigin = 'illustrative' | 'saved-build';   // GUIDED_SCENARIO_ORIGIN_LABELS unchanged
export interface GuidedScenario {
  origin: GuidedScenarioOrigin; scenarioVersion: string;
  pressPhoto: { src: string; altText: string; credit: string; event: string };
  pageContext: { title: string; summary: string };
  people: GuidedLabeledPerson[];      // order: katy-perry, justin-trudeau
  faces: GuidedFace[];                // order left→right: justin-trudeau, katy-perry
  identities: GuidedIdentity[];       // same order as faces; all start { status: 'unconfirmed', source: 'none' }
  visualFacts: string[];
  drafts: Record<GuidedDraftKey, string>;
  provenance: GuidedProvenance;
  candidate: { text: string; status: GuidedCandidateStatus };
  appliedText: string;
  history: GuidedHistoryEvent[];
}
```

Exports (all pure, all return a new scenario; never mutate): `createGuidedScenario()`, `resetGuidedScenario()`,
`getGuidedPerson(scenario, key)`, `getGuidedFace(scenario, faceId)`, `getGuidedIdentity(scenario, faceId)`,
`confirmedPersonKeys(scenario)`, `draftKeyFor(scenario)`, `draftFor(scenario)`,
`confirmGuidedIdentity(scenario, faceId)`, `leaveGuidedIdentityUnidentified(scenario, faceId)`,
`saveGuidedEdit(scenario, text)`, `rejectGuidedCandidate(scenario)`, `applyGuidedCandidate(scenario)`,
`undoGuidedApplication(scenario)`, `getLastGuidedApplication(history)`, `nameGuardError(name)`.
Lookups use an `asserts` helper for the impossible-miss case (sr-005), never `!`.

Rules:

- Draft key: confirmed set = identities with `status === 'confirmed' && source === 'face-match'`. Both → `both`;
  only Katy → `katy-perry`; only Justin → `justin-trudeau`; otherwise `none`. `candidate` is recomputed to
  `{ text: draftFor(next), status: 'ready' }` on every identity change, dropping any edit.
- `confirmGuidedIdentity(s, faceId)`: identity becomes `{ faceId, status: 'confirmed', name: person.name, source: 'face-match' }`,
  history gets `{ kind: 'identity-confirmed', faceId }`.
- `leaveGuidedIdentityUnidentified(s, faceId)`: identity becomes `{ faceId, status: 'unidentified', source: 'none' }` (no name),
  history gets `{ kind: 'identity-unidentified', faceId }`.
- Name guard: `nameGuardError(name) === \`You can only use the name ${name} after you confirm that face match.\``.
  `saveGuidedEdit` and `applyGuidedCandidate` throw it for the first person (people order) whose name appears in the
  text (case-insensitive, trimmed) while that person's identity is not confirmed via face-match.
- `saveGuidedEdit`: empty/whitespace → `'A description cannot be empty.'`; else `candidate = { text, status: 'edited' }`,
  history `{ kind: 'edit-saved', text }`.
- `rejectGuidedCandidate`: status `rejected`, history `{ kind: 'rejected' }`.
- `applyGuidedCandidate`: rejected → throw `'Cannot apply a rejected description.'`; same text as `appliedText` →
  return the scenario unchanged (no history); else `appliedText = candidate.text`, history
  `{ kind: 'applied', text, previousAppliedText }`.
- `undoGuidedApplication`: LIFO over applications not yet undone; restores `previousAppliedText`, history
  `{ kind: 'application-undone', text: restored }`; nothing to undo → unchanged.
- `scenarioVersion = 'guided-people-v3'`, `origin = 'saved-build'`.

Seed (verbatim):

| Field | Value |
| --- | --- |
| pressPhoto.src | import of `../assets/guided/guided-press-tribeca-2026.jpg` |
| pressPhoto.altText / appliedText | `Two people at a film festival.` |
| pressPhoto.credit | `Colleen Sturtevant, CC BY-SA 4.0` |
| pressPhoto.event | `Tribeca Festival, New York, June 2026` |
| pageContext.title | `Tribeca Festival 2026: red carpet photos` |
| pageContext.summary | `A photo gallery from the opening nights of the Tribeca Festival in New York, June 2026.` |
| people[0] | key `katy-perry`, name `Katy Perry`, clusterId `68adc97c-f81f-42c3-9e5c-061f16770361`, savedPhotoCount 5, galleryPhotos [ { src import `../assets/guided/guided-katy-perry-2026.jpg`, altText `Katy Perry at a microphone, reading from a note, in front of a red curtain.`, credit `Justin Higuchi, CC BY 4.0` }, { src import `../assets/guided/guided-katy-perry-2019.jpg`, altText `Katy Perry smiling at the camera, blonde hair with a headband, red lips, checked shirt.`, credit `Glenn Francis, CC BY-SA 4.0` }, { src import `../assets/guided/guided-katy-perry-2016.jpg`, altText `Katy Perry singing into a microphone, long dark hair, silver striped dress, blue and red lights behind her.`, credit `Voice of America, public domain` } ] |
| people[1] | key `justin-trudeau`, name `Justin Trudeau`, clusterId `fd0d2b5d-108a-42b7-af25-f028e40d5778`, savedPhotoCount 2, galleryPhotos [ { src import `../assets/guided/guided-justin-trudeau-2025.jpg`, altText `Justin Trudeau, close up, in a grey suit and green tie, with flags behind him.`, credit `European Union, 2025` }, { src import `../assets/guided/guided-justin-trudeau-2025-b.jpg`, altText `Justin Trudeau speaking, grey suit, white shirt and green patterned tie, flags behind him.`, credit `European Union, 2025` } ] |
| faces[0] | id `justin-trudeau`, position `left`, box `{x:514,y:77,width:132,height:189}`, matchedPersonKey `justin-trudeau`, similarity 0.686, strength `strong`, source `saved-run` |
| faces[1] | id `katy-perry`, position `right`, box `{x:707,y:140,width:121,height:181}`, matchedPersonKey `katy-perry`, similarity 0.742, strength `strong`, note `Her face is turned a little to the side.`, source `saved-run` |
| visualFacts | `Two people stand side by side in front of a white wall of Tribeca Festival logos.` · `The man on the left wears a black tuxedo with a white shirt.` · `The woman on the right wears a white draped gown with her dark hair pinned up.` · `Her hand rests on his chest.` |
| drafts.none | `A man in a black tuxedo and a woman in a white draped gown pose side by side at the Tribeca Festival. Her hand rests on his chest.` |
| drafts['katy-perry'] | `Katy Perry, in a white draped gown with her dark hair pinned up, poses with a man in a black tuxedo at the Tribeca Festival. Her hand rests on his chest.` |
| drafts['justin-trudeau'] | `Justin Trudeau, in a black tuxedo and white shirt, poses with a woman in a white draped gown at the Tribeca Festival. Her hand rests on his chest.` |
| drafts.both | `Justin Trudeau and Katy Perry pose side by side at the Tribeca Festival. He wears a black tuxedo with a white shirt; she wears a white draped gown with her dark hair pinned up and rests a hand on his chest.` |
| provenance | service `AltContext recognition service (dev build)`, model `InsightFace buffalo_l`, runDate `2026-09-06`, threshold 0.6, note `Saved from a real run. The demo does not run recognition live.`, alsoChecked `A Coachella press photo of the same two people matched both, even with a hand over her mouth. It is not bundled because of licensing.` |

### 7.4 Copy deck v3 (delta over section 4; any string not listed here stays as in section 4)

#### Entrance (lane W2-L3)

intro: `Follow one photo from start to finish. AltContext finds two faces, matches each one to a person you already named, and puts their names in the image description. You choose what gets saved.`
status text: `This demo uses one saved run. It does not run recognition live.`

#### Guide (lane W2-L3)

| id | label | description |
| --- | --- | --- |
| understand | Look at the photo | See the photo and the page it sits on. |
| face | Find the faces | AltContext found two faces and matched each one to a person you named before. |
| identity | Confirm each match | Say yes to each match, or keep that person unnamed. |
| review | Check the description | Read the draft. Edit it or reject it. |
| apply | Apply it yourself | Nothing changes until you press Apply. |

#### Page shell (lane W2-L3)

hero eyebrow `Saved run` · hero h2 `How two faces become two names in the description` · hero p
`AltContext looks at the photo, finds each face, and checks it against people you already named. If you confirm a match, that name goes into the description. You always have the last word.`

Flow strip `<ol aria-label="How the faces reach the description">`: `Photo` · `2 faces found` · `Matched to Justin Trudeau and Katy Perry` · `You confirm each match` · `Names in the description`. Stages 1–3 always `done`; stage 4 `now` until every identity is decided, then `done`; stage 5 `waiting` until every identity is decided, then `done` if at least one is confirmed, else `skipped`.

Provenance `<dl>` (h3 `Where this example comes from`): `Example` / `Saved from a real run on 2026-09-06, not a live run` · `Page` / {pageContext.title} · `People on file` / `Katy Perry (5 saved photos) · Justin Trudeau (2 saved photos)` · `Photo credit` / {pressPhoto.credit} · `Also checked` / {provenance.alsoChecked}.

History labels: identity-confirmed `You confirmed the face match: {name}.` · identity-unidentified `You kept the person on the {position} unnamed.` (others unchanged).
Feedback: confirm `Match confirmed. {name} is in the draft. Nothing is applied yet.` · unidentified `The person on the {position} stays unnamed. You can still check the description.` (others unchanged).

#### Sample photo (lane W2-L3)

`<img>` shows `pressPhoto.src`, alt = `drafts.none`. figcaption: `The photo` (strong) · `Alt text on the page right now: {pressPhoto.altText}` · `Photo credit: {pressPhoto.credit}.` · `AltContext found two faces in this photo. The next step shows the matches.`
Fallback label: `Sample photo unavailable. {drafts.none}`.

#### Faces panel (new `GuidedFacesPanel.tsx`, mounts one `GuidedFaceMatchCard` per face, lane W2-L2)

Root `<section id="guided-section-face" tabIndex={-1} aria-labelledby="guided-faces-title">`.
h3 `Faces found in the photo` · found line `AltContext found 2 faces. Each one matched a person you named before.` · how-it-works `<ol>`: `1. AltContext finds every face in the photo.` `2. It compares each face to the people you already named.` `3. It asks you to confirm each match. Nothing is named without your OK.` · disclosure `These matches were saved from a real run. The demo does not run recognition live.`

Per card (`GuidedFaceMatchCard`, props `{ face, person, identity }`), root `<article aria-labelledby="guided-face-{face.id}-title">`:

| Slot | Text |
| --- | --- |
| crop | `FaceThumbnail` size `lg` shape `square`, `mediaUrl` = pressPhoto.src, `bbox` = face.box, alt `Face on the {position}` |
| h4 (id `guided-face-{face.id}-title`) | Face on the {position} |
| match line | It matches a person you named before: **{person.name}**. |
| strength line | ✓ Match strength: {strength}. This face is close to the {savedPhotoCount} saved photos of {person.name}. |
| note line (only when face.note) | {face.note} |
| saved photos | strip: one `<img>` per `person.galleryPhotos` (alt = photo.altText, `loading="lazy"`), each followed by a visually hidden `{photo.credit}`; caption `Saved photos of {person.name}: {galleryPhotos.length} of {savedPhotoCount} shown.` |
| decision status | unconfirmed `You have not decided yet.` · confirmed `You confirmed: {person.name}.` · unidentified `You kept this person unnamed.` |

Decisions block (inside the panel, after the cards): `<div id="guided-section-identity" tabIndex={-1} aria-label="Confirm each match">`, one row per face in face order: `<p>{person.name}, face on the {position}</p>` + buttons `Yes, this is {person.name}` / `Keep this person unnamed`; change note (id `guided-identity-change-reason`): `Changing an answer swaps in a different saved draft. Save or discard your edit first.` Buttons disabled and described by the note while an edit is unsaved; confirm disabled when already confirmed; unnamed disabled when already unidentified.

#### Description review (lane W2-L2)

Explanation: both confirmed `You confirmed both matches, so both names are in the draft. The visual details and page context stay the same.` · one confirmed `You confirmed one match, so one name is in the draft. The other person is described, not named.` · none confirmed, all decided `You kept both people unnamed, so the draft only says what is visible.` · otherwise `Decide each face match first: confirm it, or keep the person unnamed. Until then the draft only says what is visible.`
visual card draft line `Draft without names: {drafts.none}` · before h3 `Without the names` · origin line `This draft comes from a saved run, not a live one.` · rejected notice `You rejected this draft, so Apply is off. Edit and save the text, or change an answer about a face, to get a new draft.` (others unchanged).

### 7.5 ASCII screens (wave 2)

```
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

### 7.6 Wave 2 DAG

```
N0' contract (this section + frozen state.test.ts + uxmap contract test + bundled assets)  [coordinator, done]
 |-- types+copy --> W2-L1 state      state.ts                                             [codex-remote]
 |-- types+copy --> W2-L2 faces      GuidedFacesPanel.tsx (new), GuidedFaceMatchCard.tsx,
 |                                   GuidedDescriptionReview.tsx, __tests__/GuidedFaceMatchCard.test.tsx,
 |                                   _guided-prototype.scss                               [codex-remote]
 |-- copy+ids  --> W2-L3 shell       Page/Guide/Entrance/SamplePhoto, __tests__/GuidedPrototypePage.test.tsx,
 |                                   _guided-flow-strip.scss                              [codex-remote]
 '-- screens   --> W2-L4 ux-map      docs/ux-maps/guided-prototype.uxmap.json + .md        [codex-remote]
W2-L1..L4 --branches--> N5' integrate (tsc, vitest, lint non-blocking) --> N6' adversarial review --> N7' fix --> N8' close
```

Width 4, `depends_on = []` everywhere, file ownership disjoint. Lanes code against 7.3 and 7.4 only; the
coordinator resolves type drift at N5'.
