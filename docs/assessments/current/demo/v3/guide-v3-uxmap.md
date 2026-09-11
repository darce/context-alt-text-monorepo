# GUIDEV3-1 UX map: two-stage public guide

Scope: `scope="public"` rendering only. Admin route unchanged.
Canon source: `~/Development/heuristics-canon-research` (lexicons + reasoning cards).

## Screen 1 — Stage 1: Choose names (`#guided-section-understand`)

```text
┌───────────────────────────────────────────────────────────────────────────┐
│ [Home]                                          [Case study]   [Reset]    │
├───────────────────────────────────────────────────────────────────────────┤
│  Guided prototype                              <- guided-eyebrow          │
│  Who's in the photo belongs in the alt text.   <- #acx-guided-entrance-.. │
│  Compare descriptions of two photos, choose which names to include,       │
│  then edit and apply each draft.                                          │
│  Recorded example. Changes stay in this tab; WordPress and the server     │
│  roster are unchanged.                         <- [data-testid=guided-scope]│
│                                      [ Choose names ]                     │
├───────────────────────────────────────────────────────────────────────────┤
│  ┌ nav [data-testid=guided-demo-stepper] ────────────────────────────────┐ │
│  │ (1) Choose names  ● aria-current=step   (2) Review and apply          │ │
│  │      aria-controls=guided-section-understand  ..=guided-section-review│ │
│  │ Step 1 of 2: Choose names                                             │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
├───────────────────────────────────────────────────────────────────────────┤
│  # Choose names                                <- #acx-guided-page-title  │
│                                                                           │
│  ┌ figure data-image-key=tribeca ──────────────────────────────────────┐  │
│  │  [ landscape photo ]        (figcaption: NO duplicate current-alt)   │  │
│  │  AltContext — with people roster                                     │  │
│  │    "<recorded output paragraph, unedited>"   credit · 9 Sep 2026     │  │
│  │  AltText.ai — no names or keywords                                   │  │
│  │    "<recorded output paragraph, unedited>"   link  · 10 Sep 2026     │  │
│  │  ── Names suggested by AltContext ──  <- #guided-faces-tribeca-title │  │
│  │   ┌ face card L ─────────────┐  ┌ face card R ─────────────┐         │  │
│  │   │ [crop] Saved suggestion: │  │ [crop] Saved suggestion: │         │  │
│  │   │        Katy Perry        │  │        Justin Trudeau    │         │  │
│  │   │ ( ) Include  ( ) Omit    │  │ ( ) Include  ( ) Omit    │         │  │
│  │   │ > References (3 of 3)    │  │ > References (3 of 5)    │         │  │
│  │   └──────────────────────────┘  └──────────────────────────┘         │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  ┌ figure data-image-key=coachella ────────────────────────────────────┐  │
│  │  [ portrait photo ]                                                  │  │
│  │  AltContext — with people roster     /  AltText.ai — no names ...    │  │
│  │  ── Names suggested by AltContext ──                                 │  │
│  │   [ mirrored face cards — SAME two canonical decisions ]             │  │
│  │   ⚠ weak match (icon + text, not colour alone)                       │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  .acx-guided-page__provenance-footer                                      │
│    Two recorded examples, not a benchmark. AltText.ai was run without     │
│    names or keywords.                                                     │
│    These comparisons include both roster names. Your choices affect only  │
│    the editable drafts.                                                   │
│    Face matches recorded 10 September 2026; recognition is not running    │
│    here.                                                                  │
│                                                                           │
│  [ Review drafts ]   Choose an option for each name to continue.          │
│   ^ guided-review-draft   Either name can be left out.                    │
│     disabled until          ^ guided-choices-help                         │
│     namesDecided(state)                                                   │
└───────────────────────────────────────────────────────────────────────────┘

REMOVED from public: aside[data-testid=public-roster-explainer]
REMOVED from public: #guided-section-face and its empty #guided-section-identity
HOISTED out of GuidedFacesPanel: the pendingChoiceChange replacement Dialog
```

## Screen 2 — Stage 2: Review and apply (`#guided-section-review`)

Desktop, >= 64rem. Two columns. Image first in DOM and when stacked.

```text
┌───────────────────────────────────────────────────────────────────────────┐
│  stepper: (1) Choose names   (2) Review and apply ● aria-current=step     │
│           Step 2 of 2: Review and apply                                   │
├───────────────────────────────────────────────────────────────────────────┤
│  # Review and apply                            <- #acx-guided-review-title│
│                                                                           │
│ ┌ article data-image-key=tribeca ─────────────────────────────────────┐   │
│ │  ## <photo-specific heading>                                        │   │
│ │ ┌ guided-editor-layout-tribeca (grid) ────────────────────────────┐ │   │
│ │ │ ┌ demo preview figure ────┐ ┌ guided-editor-column-tribeca ───┐ │ │   │
│ │ │ │                         │ │ Recorded altcontext.com draft   │ │ │   │
│ │ │ │  [ demo-applied-image-  │ │ from 9 September 2026 ...       │ │ │   │
│ │ │ │    tribeca ]            │ │                                 │ │ │   │
│ │ │ │  alt = APPLIED value    │ │ Current alt text                │ │ │   │
│ │ │ │  aspect reserved from   │ │ ┌ read-only [data-applied-text]┐│ │ │   │
│ │ │ │  existing dimensions    │ │ │ "<current applied alt>"      ││ │ │   │
│ │ │ │  no crop                │ │ └──────────────────────────────┘│ │ │   │
│ │ │ │                         │ │   ^ guided-current-alt-tribeca  │ │ │   │
│ │ │ │                         │ │                                 │ │ │   │
│ │ │ │                         │ │ Alt text to apply               │ │ │   │
│ │ │ │                         │ │ ┌ textarea ────────────────────┐│ │ │   │
│ │ │ │                         │ │ │ id=guided-description-draft- ││ │ │   │
│ │ │ │                         │ │ │    tribeca   (auto-size)     ││ │ │   │
│ │ │ │                         │ │ │ SOLE editable field          ││ │ │   │
│ │ │ │                         │ │ └──────────────────────────────┘│ │ │   │
│ │ │ │                         │ │   ^ guided-draft-field-tribeca  │ │ │   │
│ │ │ │                         │ │ Applies only to this demo image.│ │ │   │
│ │ │ └─────────────────────────┘ └─────────────────────────────────┘ │ │   │
│ │ └─────────────────────────────────────────────────────────────────┘ │   │
│ │ ┌ [data-testid=guided-apply-tribeca] ─────────────────────────────┐ │   │
│ │ │ [ Apply to demo ]  [ Keep current alt text ]  [ Undo application ]│ │  │
│ │ │   demo-apply-tribeca  guided-keep-current-   demo-undo-tribeca  │ │   │
│ │ │                        tribeca                                   │ │   │
│ │ │ <validation reason, only when applicable, aria-describedby>      │ │   │
│ │ │ ┌ role=status guided-image-status-tribeca (persistent, empty) ─┐ │ │   │
│ │ │ └──────────────────────────────────────────────────────────────┘ │ │  │
│ │ └─────────────────────────────────────────────────────────────────┘ │   │
│ └─────────────────────────────────────────────────────────────────────┘   │
│                                                                           │
│ ┌ article data-image-key=coachella ───────────────────────────────────┐   │
│ │  [ identical structure, portrait image, independent draft + status ] │   │
│ └─────────────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────────────┘

REMOVED: "Will be applied" read-only paragraph + its heading
REMOVED: "Preview the change" button + old draft-actions wrapper
REMOVED: the one detached .acx-guided-review__explanation direct child
RETAINED: #guided-section-apply as review-card container, no longer a nav stage
```

## Screen 3 — Narrow (390px), stacked

```text
┌───────────────────────────┐
│ stepper (1)(2)            │
│ Step 2 of 2: Review and   │
│ apply                     │
├───────────────────────────┤
│ ## <photo heading>        │
│ ┌ image (first, no crop) ┐│
│ │                        ││
│ └────────────────────────┘│
│ Recorded draft origin ... │
│ Current alt text          │
│ ┌ read-only ─────────────┐│
│ └────────────────────────┘│
│ Alt text to apply         │
│ ┌ textarea (auto-size) ──┐│
│ └────────────────────────┘│
│ Applies only to this      │
│ demo image.               │
│ [ Apply to demo ]         │
│ [ Keep current alt text ] │
│ [ Undo application ]      │
│ role=status (empty)       │
└───────────────────────────┘
No horizontal overflow. Same card. No sticky image over the keyboard.
```

## Interaction state matrix (per image key, independent)

```text
 names undecided          -> Review drafts DISABLED; guided-choices-help shows
                             "Choose an option for each name to continue..."
 names decided            -> help replaced by a short accurate selection summary
 draft READY, text empty  -> Apply DISABLED; "Enter alt text before applying."
 text == applied value    -> Apply DISABLED; "This demo image already uses this text."
 no recorded variant      -> Apply DISABLED; "No recorded draft is available for
                             these choices."  existing work preserved; Keep offered
 valid + changed          -> Apply ENABLED (no previewedVersion requirement)
 after Apply              -> image alt + [data-applied-text] update for THIS key only
                             status: "Applied to this demo image."
                             field == applied text, so Apply becomes unavailable
 after Undo               -> previous applied alt restored for THIS key only
                             status: "Previous alt text restored."
                             editable draft preserved
 replacement pending      -> Apply DISABLED; hoisted guarded-replacement Dialog open
```

## Canon validation

| Rule | Verdict | Where it lands |
|---|---|---|
| NAV-09 progress indicator on linear flows | satisfied | Two named stages, current + remaining, `Step N of 2` derived from the public step list, each button `aria-controls` a rendered target, exactly one `aria-current="step"`. |
| NAV-13 controlled vocabulary before label freeze | satisfied | One say-list: `Alt text to apply`, `Current alt text`, `Apply to demo`, `Keep current alt text`, `Undo application`, `AltContext — with people roster`, `AltText.ai — no names or keywords`. No accidental synonyms for draft/current/applied. |
| FORM-09 responsive enabling | satisfied | `Review drafts` gated on `namesDecided`; per-image Apply gated on the domain predicate, never on `input:checked` counting. |
| INT-05 prominent Done | satisfied, and this is the load-bearing gain | `Apply to demo` moves to the end of the editor column, immediately after the last control, as one unmistakable verb-labelled button. Previously the commit was separated from the field by a Preview step. |
| INT-06 smart action labels | satisfied | Labels name object and operation; disabled with no valid target. |
| INT-07 preview before commit | **adjudicated, not violated** | INT-07 conditions on high cost or unpredictability. Here the textarea *is* the outcome sample on the same surface, the action is demo-local, and Undo restores the prior value. The separate Preview screen sampled an outcome the user was already looking at. Removing it is ceremony reduction, not commit-without-sample. Recorded because it is the one place the redesign reads as moving against a canon row. |
| INT-09 reversible command stack | at risk, guarded | Undo must restore the previous applied alt and must not collapse an existing deeper stack to one reset. Called out as a non-goal in the v3-review and v3-state lane briefs. |
| INT-11 refine over restart | satisfied | Missing-variant and replacement paths preserve existing work; recovery never wipes the good prefix. |
| HAI-01 evidence before label | satisfied | Face cards keep reference-photo disclosures and coverage statements (3 of 3 vs 3 of 5) in one action. |
| HAI-05 imperceptible AI is not ethical | satisfied | `Names suggested by AltContext`, provenance footer, recorded-origin statement per draft, explicit "recognition is not running here". |
| HAI-08 uncertainty at decision granularity | satisfied | Weak-match warning stays on the card where the include/omit decision is made, with a non-colour indication. |
| HAI-12 output is a proposal | satisfied, and strengthened | The sole textarea is editable and its value is what Apply commits. The static provider comparison never becomes the field value and does not update as the user types. |
| HAI-15 commit before reveal | **scoped out, deliberately** | HAI-15 governs a human placed in the loop to catch model error. This guide's user is an editor deciding name inclusion, not a verifier adjudicating identity. Suppressing the suggestion before the choice would remove the very artefact under review. Noted so the omission is a decision, not an oversight. |
| GTM-07 title = emotional first line | satisfied by the operator override | `Who's in the photo belongs in the alt text.` is one basic feeling, repeatable after one exposure. The brief's `Bring names into alt text` was a feature description. |
| CARD-18 attribute claims to their bearer | satisfied | `Names suggested by AltContext` and `Saved suggestion: {name}` attribute to the source, never asserting identity as fact about the depicted person. |
| CARD-15 reversible commitments | satisfied | Undo plus Keep current keep the cheap reversible path open at every commit point. |
| CARD-30 signal density, not length | satisfied | Provenance footer compresses to three lines; the removed aside and the removed duplicate baseline were length without signal. |
| sr-004 design tokens | enforced as a v3-styles non-goal | Grid, gap, radius, colour must come from `--acx-*`; the serialized 317px/288px textarea heights must not be copied into styles. |
| rg-003 primary controls reachable from zero state | satisfied | `Review drafts` is rendered from the zero state, disabled with a stated reason, not hidden. |
| rg-004 controlled dialogs wire onOpenChange | must survive the hoist | The replacement Dialog moves out of `GuidedFacesPanel`; its `onOpenChange` -> `onCancelReplacement` wiring is a v3-sections acceptance condition. |
