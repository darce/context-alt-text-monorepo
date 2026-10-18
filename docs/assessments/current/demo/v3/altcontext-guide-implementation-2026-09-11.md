# AltContext public guide: implementation brief

**Date:** 11 September 2026  
**Audience:** Junior implementation agent  
**Status:** Implementation instructions, not an applied patch  
**Target:** `https://demo.altcontext.com/guide/` — public guided prototype only  
**Baseline:** User-supplied `Pasted text(4).txt`, copied verbatim to `source-markup.txt`  
**Baseline SHA-256:** `c673f65e18682fc7d089073c3f9a4b30cc28522896dc50ab0cf632627567b374`

## Contents

1. Evidence and correction to the previous review
2. Scope and implementation order
3. Selector index
4. Exact copy and layout changes
5. Interaction and state contract
6. Acceptance tests
7. Validation evidence and delivery requirements
8. References and canon mapping

## 1. Evidence and correction to the previous review

The earlier review did **not** establish that it had the latest deployed markup. It used repository files whose structure differed from this supplied fragment. This brief supersedes its DOM-specific instructions and is based on the attached two-photo markup. A fresh web-reader request did not retrieve the live page, so this brief does not assert that the attachment is byte-identical to the deployment now serving every visitor.

The supplied fragment was parsed in Chromium and the companion JavaScript's **116 structural/cardinality assertions passed**. These include assertions that proposed new hooks are absent. This is selector validation on a static snapshot, not an executed test of the application's React handlers, computed layout, or network behavior.

### What the supplied markup actually establishes

| Observation | Consequence for this patch |
|---|---|
| H1 is `Review a recorded alt text example`. | Replace this title, not the title quoted from the older repository copy. |
| There are two source figures: `tribeca` and `coachella`. | Apply layout/copy changes to both, with separate editing and application state. Do not restore a single-photo implementation. |
| The top comparison is AltContext output versus AltText.ai output. | It is **not** a current-versus-proposed edit diff. Keep provider attribution. |
| The Tribeca figure has an extra direct `figcaption > span` containing its current alt text. Coachella does not. | Remove that one redundant span; preserve each editor's current text. |
| Face controls are already inside both source photo figures. | Do not move them into the intermediate names section. |
| `#guided-section-identity` has no children. Its parent names section retains instructions and a `Review the draft` button. | Remove this empty intermediate section and put its continuation action at the end of the existing photo/name section. |
| The named sidebar exists as `[data-testid="public-roster-explainer"]`. | Remove this exact public-only aside. |
| `#guided-section-apply` is a **div** inside `#guided-section-review`, holding two articles. | Do not treat it as the separate section from the earlier implementation. |
| Each article has a textarea, a second read-only copy under `Will be applied`, and its own Apply/Undo buttons. | Use one editable proposed text per photo, beside its existing preview image. |
| Top comparison provenance says 10 September; editor origins say 9 September. Tribeca's top AltContext text also differs from its editable draft. | Preserve these as separate records. Do not overwrite one with the other or silently unify their dates. |
| The captured stepper says step 3 of 4; `Review the draft` has no `disabled` attribute; both Apply buttons are disabled with preview-related messages. | These are observed states only. Initial readiness and event behavior still require source tracing and runtime tests. |

**Correction on order:** Keep **AltContext first, AltText.ai second** in the provider comparison. In the editing surface, show **Current alt text before Alt text to apply**. The two comparisons have different purposes. This ordering is a product-design decision, not a universal canon rule.

**Correction on generated content:** The supplied markup explicitly labels recorded AltContext outputs. It does not prove that those outputs were fabricated, nor does it independently verify the underlying runs. Preserve the actual recorded text. Never author replacement descriptions to make this patch look better.

The fragment contains four radio groups but a summary of two named people. It does not prove whether the two photos share two canonical inclusion decisions or have four independent decisions. Preserve the current application's decision scope after inspecting its state and handlers; do not infer it from the number of rendered controls.

## 2. Scope and implementation order

Implement a public workflow with two named stages:

**Choose names → Review and apply**

The photo comparison and face evidence stay in the first stage. The second contains both existing photo-specific editors. No new generation request, server roster change, WordPress media write, photo replacement, or backend schema change belongs in this patch.

Work in this order:

1. Locate the source that renders the supplied multi-image guide. Inspect repository instructions and the documentation contents/index before finding its current roadmap. Record the working commit and trace the public route, copy owner, choice predicate, and per-image draft/apply/undo state.
2. Add characterization tests for existing choice scope and image isolation. Establish where the current preview gate is implemented before changing it.
3. Apply the copy changes and remove the exact redundant public elements.
4. Rewire the existing continuation action directly to review. Update the public stepper to two stages.
5. Rebuild each review card around one textarea beside the image. Implement explicit Apply without a separate Preview action.
6. Run the tests in section 6, check responsive/keyboard behavior, and provide before/after evidence.

Use these strings to locate owners; source paths from the earlier answer are **search leads**, not proof of which file renders this version:

```sh
rg -n 'public-roster-explainer|guided-description-review-|guided-description-draft-|guided-section-identity|guided-section-apply' apps docs
rg -n 'Review a recorded alt text example|People recognised in this photo|Preview the change' apps docs
```

Follow the actual imports to the copy catalog. Do not edit generated copy files if their header identifies a source catalog. Do not patch a built/minified asset. Do not use `innerHTML`, `remove()`, or a MutationObserver to alter React-owned content after rendering. The selectors below identify targets for source edits and tests; they are not production mutation instructions.

Preserve the authenticated/admin guide's behavior when it shares components. A public-only change must not silently remove a preview contract still used by another route. Prefer a small explicit public presentation/state policy over a new generic wizard framework.

## 3. Selector index

All selectors below are valid for `querySelector`/`querySelectorAll`. Use the root actually included in the fragment. The earlier outer `#acx-public-guide` selector is not present in this attachment and is not a prerequisite.

```js
const root = document.querySelector(
  '[data-testid="guided-demo-root"][data-scope="public"]'
);
if (!root) throw new Error('Public guide root not found; verify the mounted build.');

function one(selector) {
  const matches = root.querySelectorAll(selector);
  if (matches.length !== 1) {
    throw new Error(`${selector}: expected 1 match, found ${matches.length}`);
  }
  return matches[0];
}
```

### Existing selectors: verified against the attachment

Counts are for the supplied state, relative to `root`.

| Target | JavaScript selector string | Count |
|---|---|---:|
| H1 | `#acx-guided-entrance-title` | 1 |
| Intro | `.acx-guided-entrance__intro` | 1 |
| Scope disclosure | `[data-testid="guided-scope"]` | 1 |
| Start button | `.acx-guided-entrance__actions > button` | 1 |
| Stepper buttons | `[data-testid="guided-demo-stepper"] ol > li > button` | 4 |
| Stepper status | `.acx-guided-guide__bar > div > strong` | 1 |
| First-stage heading | `#acx-guided-page-title` | 1 |
| Source photo list | `.acx-guided-page__media-list` | 1 |
| Redundant Tribeca current text | `[data-testid="guided-photo-tribeca"] > figcaption > span` | 1 |
| Same location in Coachella | `[data-testid="guided-photo-coachella"] > figcaption > span` | 0 |
| Public roster aside | `aside[data-testid="public-roster-explainer"]` | 1 |
| Existing context continuation | `#guided-section-understand > .acx-guided-page__scenario > button` | 1 |
| Empty intermediate names step | `#guided-section-face` | 1 |
| Empty cards container | `#guided-section-identity` | 1 |
| Children of empty cards container | `#guided-section-identity > *` | 0 |
| Old draft continuation | `#guided-section-face > button` | 1 |
| Detached review explanation | `.acx-guided-page__workspace > p.acx-guided-review__explanation` | 1 |
| Choice summary | `[data-testid="guided-choice-summary"]` | 1 |
| Page live status | `[data-testid="guided-page-feedback-status"]` | 1 |
| Review section | `#guided-section-review` | 1 |
| Review heading | `#acx-guided-review-title` | 1 |
| Review-card container (div) | `#guided-section-apply` | 1 |
| Review articles | `#guided-section-apply > article[data-image-key]` | 2 |
| Name-choice fieldsets | `fieldset.acx-guided-face__choice` | 4 |
| Name-choice radio inputs | `fieldset.acx-guided-face__choice input[type="radio"]` | 8 |

Use image keys rather than `article:nth-child(1)` or a long DOM ancestry chain:

```js
const imageKeys = ['tribeca', 'coachella'];

for (const key of imageKeys) {
  const photo = one(`[data-testid="guided-photo-${key}"]`);
  const editor = one(`[data-testid="guided-description-review-${key}"]`);
  const textarea = one(`#guided-description-draft-${key}`);
  const current = one(`[data-testid="guided-description-review-${key}"] [data-applied-text]`);
  const image = one(`[data-testid="demo-applied-image-${key}"]`);
  const apply = one(`[data-testid="demo-apply-${key}"]`);
  const undo = one(`[data-testid="demo-undo-${key}"]`);
  // Read-only inspection. Application updates belong in the React state/actions.
  console.log(key, textarea.value, current.textContent, image.alt, apply.disabled, undo.disabled);
}
```

Each of those per-image selectors matches one element. For provider comparison and face headings:

```js
const acxHeading = (key) => `#guided-caption-${key}-altcontext`;
const otherHeading = (key) => `#guided-caption-${key}-alttextai`;
const facesHeading = (key) => `#guided-faces-${key}-title`;
const comparison = (key) =>
  `[data-testid="guided-photo-${key}"] .acx-guided-page__caption-compare`;
const acxBlock = (key) =>
  `[data-testid="guided-photo-${key}"] section[aria-labelledby="guided-caption-${key}-altcontext"]`;
const otherBlock = (key) =>
  `[data-testid="guided-photo-${key}"] section[aria-labelledby="guided-caption-${key}-alttextai"]`;
```

The existing duplicated proposed-text paragraph can be located during the migration with:

```js
const oldDuplicate = (key) =>
  `[data-testid="guided-apply-${key}"] .acx-guided-review__preview-grid > div:nth-child(2) > p`;
```

This is a snapshot-specific locator, not a new durable selector. Remove that paragraph from the component; retain the textarea and its stable ID.

Several existing `data-testid` values, including `face-matches-justin-trudeau` and `face-matches-katy-perry`, repeat once per source photo. Scope them to `[data-testid="guided-photo-${key}"]`; do not use an unscoped `querySelector` and silently operate only on the first photo.

### Proposed hooks: add these in source

These hooks are **not** claimed to exist in the supplied markup.

| New hook | Required target |
|---|---|
| `data-testid="guided-eyebrow"` | Small `Guided prototype` label above H1 |
| `data-testid="guided-review-draft"` | Reused context continuation button, now `Review drafts` |
| `data-testid="guided-choices-help"` | Help immediately beside that button |
| `data-testid="guided-editor-layout-${key}"` | Image-and-editor grid in each article |
| `data-testid="guided-editor-column-${key}"` | Text and actions column |
| `data-testid="guided-current-alt-${key}"` | Current-alt heading and existing read-only text |
| `data-testid="guided-draft-field-${key}"` | Label and sole textarea |
| `data-testid="guided-keep-current-${key}"` | Existing Keep action moved to the final action group |
| `data-testid="guided-image-status-${key}"` | Persistent, initially empty per-image status region |

The companion `altcontext-guide-selectors-2026-09-11.js` contains the complete existing/new map and count assertions.

## 4. Exact copy and layout changes

### A. Entrance and stage names

| Existing target | Replacement |
|---|---|
| New eyebrow above H1 | `Guided prototype` |
| `#acx-guided-entrance-title` | `Bring names into alt text` |
| `.acx-guided-entrance__intro` | `Compare descriptions of two photos, choose which names to include, then edit and apply each draft.` |
| `[data-testid="guided-scope"]` | `Recorded example. Changes stay in this tab; WordPress and the server roster are unchanged.` |
| Start button | `Choose names` |
| `#acx-guided-page-title` | `Choose names` |
| `#acx-guided-review-title` | `Review and apply` |
| Public step 1 | `Choose names` → controls `guided-section-understand` |
| Public step 2 | `Review and apply` → controls `guided-section-review` |

Derive `Step 1 of 2: Choose names` and `Step 2 of 2: Review and apply` from the public step definitions. Update visible status and announcements together. There must not be a hidden four-step requirement underneath the new two-step navigation.

Keep Home, Case study, and Reset. Do not add a sign-in, access request, or new modal before the guide.

### B. Provider comparison and duplicated baseline

For both image keys, change the comparison headings to:

- AltContext heading: **`AltContext — with people roster`**
- AltText.ai heading: **`AltText.ai — no names or keywords`**

Keep the existing order: AltContext first in DOM and visual order. Use comparable typography; do not describe either result as the objectively correct answer. Preserve the actual output paragraphs, provider links, credits, and captured/generated dates.

Remove only the direct current-alt span in the Tribeca `figcaption`. Coachella already has no corresponding span. The actual current text remains in each review card, available at the moment of applying a replacement.

Use the existing `.acx-guided-page__provenance-footer` for these compact distinctions:

> Two recorded examples, not a benchmark. AltText.ai was run without names or keywords.
>
> These comparisons include both roster names. Your choices affect only the editable drafts.
>
> Face matches recorded 10 September 2026; recognition is not running here.

Keep the per-result dates/attribution next to their result. Render dates from the actual records when available. Do not change a 9 September record to 10 September merely to match the top comparison. The current phrase “one recorded sample” should not describe a two-photo comparison.

Do **not** label the competitor paragraph “Current alt text” or “Before.” Its wording is different from the current demo alt text in this attachment. Do **not** update the static provider comparison as the user types into an editor.

### C. Machine attribution and face evidence

Replace both `#guided-faces-${key}-title` strings with:

> Names suggested by AltContext

Keep `Saved suggestion: {name}` in the four existing face cards; it accurately distinguishes a saved suggestion from a fresh run. Keep the include/omit radio labels. Omission is an editorial decision, not proof that the suggested identity is false.

Retain the reference-photo disclosures, enlarge comparison controls, and coverage statements. In particular, preserve the distinction between all three references shown for one roster entry and three of five shown for the other.

Do not alter matching thresholds, scores, face bounding boxes, or source image metadata. Preserve the Coachella weak-match warning, including its non-colour indication. A threshold or a displayed 100% cluster-anchor score is not a verified-identity claim. This patch must not add probability-of-correctness language that the source data does not establish.

### D. Remove the aside and empty intermediate step

Remove `aside[data-testid="public-roster-explainer"]` from the public component tree. Do not hide it with CSS while leaving it in the reading order.

Remove `#guided-section-face` and its empty `#guided-section-identity` child from the **public** rendering. The actual face cards remain under the two source figures. Move the meaningful continuation behavior to the button already at the end of `#guided-section-understand > .acx-guided-page__scenario`.

Change that button from `Review name suggestions` to **`Review drafts`**, add the proposed `guided-review-draft` test hook, and have it go directly to `#guided-section-review`.

Add nearby help with the proposed `guided-choices-help` hook. When incomplete:

> Choose an option for each name to continue. Either name can be left out.

Use face-specific wording instead if source tracing establishes that the current guide has independent per-photo decisions. Preserve the current domain semantics; do not claim a global choice affects both drafts unless the handlers actually do that. Once ready, remove the blocking message or replace it with a short accurate selection summary. Keep the button in the same location and do not auto-navigate on a radio change.

Remove the one detached direct-child review-explanation paragraph: the per-image origin statements already identify recorded drafts. Do not remove elements through a broad `.acx-guided-review__explanation` deletion that could catch unrelated content on another route.

### E. One editor beside each photo

Retain the two articles, their `data-image-key`, headings, and IDs. Retain `#guided-section-apply` as the review-card container; it is no longer a separate public navigation stage.

Each article should contain this order:

```text
Photo-specific heading
  Image-and-editor grid
    Existing demo preview figure
    Editor column
      Recorded-origin statement
      Current alt text — existing read-only value
      Alt text to apply — sole labeled textarea
      Applies only to this demo image.
      Apply to demo | Keep current alt text | Undo application
      Local validation reason, when applicable
      Local application status
```

Use the new hooks in section 3. Keep `data-testid="guided-apply-${key}"` on the final actions/status wrapper, and keep the existing `demo-apply-${key}` and `demo-undo-${key}` buttons. Move the Keep action there and add its proposed hook.

Change the textarea label to **`Alt text to apply`** and preserve its existing `id="guided-description-draft-${key}"` and corresponding `htmlFor`. Remove the read-only `Will be applied` paragraph and its obsolete heading. Remove `Preview the change` and the old draft-actions wrapper; do not leave another copy of Keep behind.

Keep the textarea populated from its actual recorded draft state. Keep current text from its actual applied state. Do not use the top marketing comparison as either value.

**Layout:** Use one column at narrow widths and two columns when there is enough room for a useful photo and text field. Image first, editor second in DOM; use the same order when stacked. A 64rem breakpoint is a starting implementation choice, not a canon requirement. Reuse the project's grid/gap tokens and scope styling to the public guide. Preserve both the landscape and portrait images without cropping. Use existing image dimensions/aspect metadata to reserve space. Do not copy serialized inline textarea heights (317px/288px) into styles; preserve or repair its auto-size behavior after reflow.

The reference photo and field must be visible together at normal desktop size without scrolling between different sections. On mobile, keep them in the same card; do not force two cramped columns or add a sticky image that obscures the keyboard/field.

## 5. Interaction and state contract

### Canonical choices, not a DOM count

Trace the predicate currently used by the enabled `Review the draft` button and reuse that domain predicate at the new location. Do not derive application readiness by counting `input:checked`, reading `.acx-guided-face__decision` strings, or observing CSS.

The target is to continue immediately after the existing meaningful name choices are complete, including either or both omissions. Where the current domain stores two shared person choices, choosing each person once must be enough; the four rendered fieldsets must not create four mandatory decisions. Both rendered copies must remain synchronized. Where source tracing instead establishes per-photo choices, preserve that scope and test it explicitly; do not silently turn a weak observation's inclusion into a cross-photo approval.

Report which model the source actually implements. The HTML's omitted `checked` attributes do not establish that no choice was made in the original browser: serialized attributes alone are not the runtime form-state contract.

### Explicit inline Apply

Keep one authoritative editable draft per image and a separate applied-alt value. Use the existing state/reducer where possible. The Apply handler must receive the latest visible field value and validate against the latest relevant choice/context state in one action.

A public inline Apply is allowed when the relevant choices are complete, the corresponding recorded draft is available/current, the visible value is non-empty under the existing validation policy, no replacement/conflict is pending, and the value differs from that image's applied value. It does **not** require an extra Preview click or a `previewedVersion` flag solely used for the removed public screen.

Do not implement this by permanently setting `previewedVersion = draftVersion`, simulating clicks on a hidden Preview button, or making Apply always enabled. Update the real guard and transition for the public path. Preserve any distinct admin-route preview contract.

On Apply, validate with `text.trim()` as appropriate but store the actual visible string unchanged; do not silently trim/normalize a different value into the demo. If normalization is required by the existing domain, first display its actual result and make that contract explicit. A final keystroke followed immediately by Apply must be included—no blur/debounce dependency and no stale closure over an older draft.

Applying Tribeca must not write Coachella state, and vice versa. Update only the corresponding `[data-applied-text]` and `demo-applied-image-${key}` alt attribute. Show **`Applied to this demo image.`** in that image's status region. No WordPress or roster mutation is authorized by this action.

### Preview and undo semantics

The textarea itself is the visible proposed result before Apply. The existing demo image's `alt` attribute continues to represent the **applied** value until the explicit action occurs. Do not make typing silently update the applied image or its read-only current text.

After Apply, the field equals the applied text, so another identical Apply is unavailable. Undo restores the previous applied alt for that image and displays **`Previous alt text restored.`** Keep the current editable draft available so the user does not lose work. Preserve existing deeper history when available; do not collapse a supported undo stack to one irreversible reset.

`Keep current alt text` leaves that photo's applied value unchanged. Do not wipe the other photo, reset choices, or discard a manual edit without preserving it or asking before replacement.

Use per-image error messages. A blank field can use **`Enter alt text before applying.`** An unchanged value can use **`This demo image already uses this text.`** Do not retain “Preview it again before applying” after removing Preview.

### Changing names after editing

Use existing recorded variants for the actual choice combination. Preserve provenance, including the original output text and subsequent manual-edit distinction. If an automatic variant replacement would overwrite a manual edit, use the existing guarded replacement/history mechanism for **all affected images**. A trivial change before any manual edit should not require a redundant names-review screen.

Never synthesize a missing variant by stripping names from another output, inserting names into the competitor result, or composing a new caption in UI code. Show **`No recorded draft is available for these choices.`**, preserve existing work, allow a return to choices/Keep current, and disable Apply for that unavailable candidate. Missing data for one image must not destroy the other image's usable draft.

### Focus, status, and navigation

Selecting a radio changes a value and readiness, not location or focus. Clicking `Review drafts` selects public stage 2 and focuses the review heading or the existing focusable section. Start selects stage 1 and focuses its section. Each stepper button controls an existing target; exactly one has `aria-current="step"`.

Keep the public page's status region for concise navigation/readiness feedback. Add the proposed persistent per-image `role="status"` regions for Apply/Undo feedback. Avoid duplicate announcements from local and global regions, and do not announce the entire draft on each keystroke. Keep validation linked with `aria-describedby` only to IDs that are rendered.

Keyboard users must be able to choose, inspect reference photos, continue, edit, apply, and undo. Preserve visible focus and dialog focus restoration. Do not claim that this implementation brief or a structural audit establishes full accessibility conformance.

## 6. Acceptance tests

Write these against the current components/reducer and existing test runner. Use the stable root and photo-specific selectors above; do not introduce a new test framework for this patch.

| ID | Test and required result |
|---|---|
| AC-01 | Public title/intro match section 4. There is one `Guided prototype` eyebrow and two public stepper entries with valid targets. No public status says “of 4.” |
| AC-02 | Both top comparisons remain present and AltContext-first. All four provider output paragraphs and their attribution/date records are unchanged by the copy/layout patch. |
| AC-03 | The Tribeca direct `figcaption > span` is gone. Each review article still has its own single current-alt text. Competitor text is never relabeled or assigned as current text. |
| AC-04 | Public roster aside and empty names step are absent. Both photo-local face panels, all eight radio inputs, the four reference disclosures, and weak-match warning remain. |
| AC-05 | From a fresh/reset application state, the continuation cannot advance before required choices. Complete the existing two-person choice set where shared. It immediately enables; there is no second names-review action. No auto-scroll/focus jump occurs on the last radio choice. |
| AC-06 | Include/include, include/omit, omit/include, and omit/omit all satisfy the existing two-choice gate. Test mirrored controls when shared; test the existing per-photo model instead if source tracing establishes that contract. Missing recorded variants are handled explicitly, not fabricated. |
| AC-07 | Exactly one textarea per image. Each is associated with `Alt text to apply`; no second read-only proposed paragraph or `Preview the change` button remains. |
| AC-08 | Type a distinctive test edit and immediately click that image's Apply without first blurring the field. The applied text and image alt equal the latest complete field value. No Preview step is required. |
| AC-09 | Apply/Undo Tribeca while Coachella has an unapplied edit. Coachella's draft, applied alt, and history remain unchanged. Repeat in reverse. |
| AC-10 | After Apply, repeat-Apply is unavailable for the identical value. Undo restores the previous applied alt only for that image and keeps editable work available. |
| AC-11 | Blank text, no-change, unavailable variant, pending replacement, and stale choice-context states retain the existing safety checks and accurate inline reasons. No obsolete preview error survives. |
| AC-12 | Change a name after manually editing a draft. Cancelling replacement preserves choices/work according to the existing guard; accepting preserves displaced edits in the existing history mechanism and loads only authentic corresponding variants. Test every affected image. |
| AC-13 | Changing names, applying, or undoing does not rewrite the static top provider comparison or its 10 September provenance. The separate 9 September editor provenance is not silently replaced. |
| AC-14 | Walk the flow by keyboard. Inspect a reference, close its enlarged view, continue, edit, apply, undo, reset. Focus and announcements stay attached to the intended controls/photo. All `aria-controls`, label references, and rendered descriptions resolve. |
| AC-15 | At representative desktop width, image and editable field are adjacent; at 390px and a narrow reflow width, they stack without horizontal overflow or image distortion. Check both aspect ratios and textarea resizing. |
| AC-16 | Inspect network calls while exercising recorded name/Apply/Undo actions: no new recognition/generation job, roster mutation, or WordPress media write is introduced. Page assets/normal reads are not mistaken for writes. |
| AC-17 | Reset restores the initial public choices, drafts, per-image applied alt, and existing local-history policy. No stale field value reappears from an old ref after reset. |
| AC-18 | Shared/admin route regression tests still pass. Removing a public section must not remove an admin-only feature or silently weaken its commit guard. |

HTML serialization alone cannot execute AC-05 through AC-18. Do not mark these passed merely because a static selector report is green.

## 7. Validation evidence and delivery requirements

Included files:

- `source-markup.txt`: exact supplied markup, saved as text rather than an executable page.
- `altcontext-guide-selectors-2026-09-11.js`: read-only selector map and structural assertions.
- `selector-validation.json`: Chromium baseline result with 116/116 passing count assertions and extracted observed values.

Run the companion JavaScript in a browser containing the relevant build, then:

```js
// Before editing: confirms this version's structure, not its behavior.
const before = ACXGuideHandoff.assertStructure('before');
console.table(before.checks);

// After implementing: validates the proposed structural contract.
const after = ACXGuideHandoff.assertStructure('after');
console.table(after.checks);
```

For this handoff the `before` audit was executed against a detached parsed copy of the uploaded fragment in Chromium, with external requests blocked. `node --check` passed for the JavaScript file. As a negative control, the `after` contract correctly failed against the unchanged snapshot. **No post-refactor application test has been run and no production changes have been made.**

Before handing the implementation back, provide the working commit, actual changed files, the resolved choice model, executed test commands/results, and screenshots of both photo editors at desktop/mobile widths. Include any remaining failures explicitly. A screenshot cannot replace the exact-value Apply and cross-image isolation tests.

## 8. References and canon mapping

### Primary implementation evidence

The baseline is the attached `Pasted text(4).txt`, reproduced without edits in [source-markup.txt](source-markup.txt). Exact selectors identify each finding. The reviewed fragment has no stylesheet or handler implementation; its labels are evidence of what the interface says, not independent evidence of generation provenance or runtime behavior.

### Canon

The following are references for the decisions, not claims that every rule's trigger is violated by this snapshot:

| Rule | Application in this brief |
|---|---|
| [GTM-07](https://github.com/darce/heuristics-canon/blob/main/lexicons/business-marketing.md#gtm-07) | A title that makes the names-in-alt-text benefit understandable without explanation. |
| [GTM-08](https://github.com/darce/heuristics-canon/blob/main/lexicons/business-marketing.md#gtm-08) | Lead the public example with the distinguishing capability, without claiming a benchmark win. |
| [NAV-13](https://github.com/darce/heuristics-canon/blob/main/lexicons/interaction-ux.md#nav-13) | Use alt text consistently for the editable field; distinguish providers and applied versus proposed values. |
| [NAV-09](https://github.com/darce/heuristics-canon/blob/main/lexicons/interaction-ux.md#nav-09) | Keep the public step map consistent with the two actual stages. |
| [FORM-09](https://github.com/darce/heuristics-canon/blob/main/lexicons/interaction-ux.md#form-09) | Enable continuation responsively from real prerequisites, not a redundant confirmation. |
| [INT-05](https://github.com/darce/heuristics-canon/blob/main/lexicons/interaction-ux.md#int-05), [INT-06](https://github.com/darce/heuristics-canon/blob/main/lexicons/interaction-ux.md#int-06) | Prominent, accurately scoped per-image Apply action near its field. |
| [INT-07](https://github.com/darce/heuristics-canon/blob/main/lexicons/interaction-ux.md#int-07) | Show the proposed result before commitment; this need not be a separate Preview button/screen. |
| [INT-09](https://github.com/darce/heuristics-canon/blob/main/lexicons/interaction-ux.md#int-09), [INT-11](https://github.com/darce/heuristics-canon/blob/main/lexicons/interaction-ux.md#int-11) | Preserve undo and useful edits rather than resetting the whole task. |
| [HAI-01](https://github.com/darce/heuristics-canon/blob/main/lexicons/interaction-ux.md#hai-01), [HAI-08](https://github.com/darce/heuristics-canon/blob/main/lexicons/interaction-ux.md#hai-08) | Keep machine attribution, inspectable references, and the weak-match cue where decisions happen. |
| [HAI-05](https://github.com/darce/heuristics-canon/blob/main/lexicons/interaction-ux.md#hai-05), [HAI-12](https://github.com/darce/heuristics-canon/blob/main/lexicons/interaction-ux.md#hai-12) | Disclose recorded output, keep it editable, and do not invent live behavior. |
| [HAI-15](https://github.com/darce/heuristics-canon/blob/main/lexicons/interaction-ux.md#hai-15) | Do not call choosing a displayed machine suggestion independent identity verification. This patch is editorial inclusion, not a blinded verification protocol. |

Canon sections were consulted in the preceding review and the relevant interaction/marketing sections were re-read for this handoff. Returned blob identifiers: `interaction-ux.md` — `180740093900725559b00833adc1a1e1a95547af`; `business-marketing.md` — `c0b770492cfd4625f9d7bf2259550ef746c66944`. These are file blob IDs, not deployment commit IDs.

**Judgment calls:** The exact headline, keeping AltContext first in the provider comparison, using two public stages, and the responsive breakpoint are recommendations for this page. Canon does not prescribe them literally. No conversion or usability improvement has been measured yet.

### Uploaded roadmap check

The available uploaded roadmap, `roadmap-v3.hybrid.md`, was checked through its heading outline and glossary, then its consent and alt-text generation sections. It supports identity-aware alt text, editor review/approval, and explicit initiation of remote operations. It does not require this public prototype to have four steps or a separate Preview button. This patch preserves those relevant boundaries and does not change production roster authority or backend architecture.

That roadmap's Appendix A contains a 30 October 2025 timestamp, and the document does not describe this September 2026 public markup. Its being available is not proof that it is the repository's latest roadmap. During source preflight, inspect the current repository documentation index and any applicable public-guide plan; record conflicts rather than importing old architectural assumptions into this UI patch. The requested attached markup remains the baseline for the selector changes here.
