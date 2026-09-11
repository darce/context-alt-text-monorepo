LANE v3-review — one editor beside each photo, inline Apply, no Preview gate.

OWNED FILE (edit only this one):
  apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedDescriptionReview.tsx

Zero edits outside this file. Do not touch RecordedWalkthrough.tsx, state.ts, publicGuideCopy.ts, GuidedSamplePhoto.tsx, or any SCSS. If another file must change, stop and report it as a handoff note.

CONTEXT
This file holds two renderers. `GuidedImageReviewCard` renders one `<article data-testid="guided-description-review-${key}" data-image-key={key}>` per photo; `GuidedDescriptionReview` renders the per-image list inside `<section id="guided-section-review" data-testid="guided-candidate">` with `<div id="guided-section-apply" className="acx-guided-review__image-cards">` as the card container, and separately keeps a legacy single-draft path plus a legacy `#guided-section-apply` section for the older flow.

Inside the READY branch of `GuidedImageReviewCard` today:
  .acx-guided-review__comparison
    .acx-guided-review__origin                 recorded-origin statement
    <label htmlFor={editorId}> draft.label     + <textarea id="guided-description-draft-${key}">
    field error (role="alert")
    <p>{guidedCopy('draft.effect')}</p>
    .acx-guided-review__actions                [ draft.next = "Preview the change" ] [ draft.keep ]
    preview-blocked reason
  .acx-guided-review__apply  data-testid="guided-apply-${key}"
    .acx-guided-review__preview-grid           <h4>apply.before</h4><p data-applied-text> AND <h4>apply.after</h4><p> "will be applied"
    figure.acx-guided-review__demo-preview     <img data-testid="demo-applied-image-${key}">
    .acx-guided-review__actions                [ demo-apply-${key} ] [ demo-undo-${key} ]
    apply reason / undo reason paragraphs

Lane v3-state has landed `canApplyImageDraftPublic(state, draft)` in state.ts. Lane v3-copy has landed these keys in publicGuideCopy.ts:
  'draft.field_label.public'       -> 'Alt text to apply'
  'draft.current_alt_label.public' -> 'Current alt text'
  'draft.apply_scope.public'       -> 'Applies only to this demo image.'
  'outcome.applied_image.public'   -> 'Applied to this demo image.'
  'outcome.undone_image.public'    -> 'Previous alt text restored.'
  'error.empty_draft.public'       -> 'Enter alt text before applying.'
  'error.unchanged_draft.public'   -> 'This demo image already uses this text.'
  'error.no_recorded_draft.public' -> 'No recorded draft is available for these choices.'

TASK

1. Add an explicit `scope?: 'public' | 'admin'` prop to `GuidedDescriptionReviewProps`, defaulting to 'admin', and thread it into `GuidedImageReviewCard`. Do NOT infer public scope from the presence of `recordedOriginLabel`. Every change below applies only when scope === 'public'; the admin rendering, including its Preview button and its preview gate, must be byte-for-byte behaviourally unchanged.

2. Public card structure. Inside the READY branch, render exactly this order:

   <h3 id={`${editorId}-title`}>{photo.event}</h3>
   <div data-testid={`guided-editor-layout-${key}`}>          image-and-editor grid
     <figure className="acx-guided-review__demo-preview">      MOVED here from the apply block, unchanged markup
       <img data-testid={`demo-applied-image-${key}`} alt={draft.appliedAltText} />
     </figure>
     <div data-testid={`guided-editor-column-${key}`}>
       <p className="acx-guided-review__origin">              recorded-origin statement, unchanged
       <div data-testid={`guided-current-alt-${key}`}>        heading from 'draft.current_alt_label.public'
         <p data-applied-text>{draft.appliedAltText}</p>      KEEP the data-applied-text attribute
       </div>
       <div data-testid={`guided-draft-field-${key}`}>
         <label htmlFor={editorId}>                           'draft.field_label.public'
         <textarea id={editorId} ... />                       the SOLE textarea in this card
       </div>
       <p>{guidedCopy('draft.apply_scope.public')}</p>        'Applies only to this demo image.'
       <div data-testid={`guided-apply-${key}`}>
         actions: [demo-apply-${key}] [guided-keep-current-${key}] [demo-undo-${key}]
         validation reason paragraph, when applicable
         <p role="status" data-testid={`guided-image-status-${key}`}>  persistent, initially empty
       </div>
     </div>
   </div>

   Image first, editor second in DOM, and the same order when stacked. Keep `data-testid="guided-apply-${key}"` on the final actions-and-status wrapper. Keep `demo-apply-${key}` and `demo-undo-${key}` on their existing buttons. Add `data-testid="guided-keep-current-${key}"` to the moved Keep button.

3. Public removals. Remove the Preview button (`draft.next`) and the old `.acx-guided-review__actions` wrapper that held it. Remove the `.acx-guided-review__preview-grid` block entirely, including the `apply.after` heading and its "will be applied" paragraph. Remove the `draft.effect` paragraph. Remove the preview-blocked reason paragraph and its `aria-describedby` wiring. There must be exactly one Keep button and exactly one textarea per card afterwards. Do not leave a second copy of Keep behind.

4. Public apply gate. Use `canApplyImageDraftPublic(state, draft)` instead of the preview-gated predicate. The Apply button must be enabled when the choices are complete, the recorded draft is available and current, the visible value is non-empty, no replacement is pending, and the value differs from that image's applied value. It must NOT require a Preview click or a `previewedVersion` flag.

   FORBIDDEN implementations: setting `previewedVersion = draftVersion` anywhere; programmatically clicking a hidden Preview button; making Apply always enabled; calling the preview action inside the apply handler.

5. Latest-keystroke correctness. The Apply handler must receive the latest visible field value and validate it in one action. The existing `callTextImageAction(actions.onApplyForImage, ..., editValue, true)` already passes `editValue`; keep that shape. A final keystroke immediately followed by Apply must be included, with no blur or debounce dependency and no stale closure over an older draft. Do not introduce a `useEffect` that syncs `editValue` on a delay.

6. Validation and storage. Validate with `editValue.trim()` but pass the visible string unchanged to the action. Blank field renders `guidedCopy('error.empty_draft.public')`. A value equal to the applied text renders `guidedCopy('error.unchanged_draft.public')`. A missing recorded variant renders `guidedCopy('error.no_recorded_draft.public')`, preserves existing work, keeps Keep-current reachable, and disables Apply for that image only. Delete any residual "Preview it again before applying" wording from the public path.

7. Per-image status region. `guided-image-status-${key}` is a persistent `role="status"` element that exists from first render and starts empty. After a successful Apply it announces `guidedCopy('outcome.applied_image.public')`. After Undo it announces `guidedCopy('outcome.undone_image.public')`. Do not create or destroy the node on state change, do not announce the draft text on every keystroke, and do not duplicate what the page-level status region already announces. Wire `aria-describedby` only to IDs that are actually rendered.

8. Isolation. Applying one image key must not alter the other image's applied text, draft, status region, or `demo-applied-image-${otherKey}` alt attribute. Undo restores the previous applied alt for that image and leaves the editable draft in place so the user does not lose work. Preserve any deeper undo history the reducer already supports; do not collapse it to a single irreversible reset. Keep current alt text leaves that photo's applied value unchanged and must not reset choices or wipe the other photo.

9. Textarea sizing. Keep the existing auto-size and manual-resize machinery working after the reflow into the new grid. Do not hardcode a pixel height. Do not copy any serialized inline height into the component.

10. Leave the legacy single-draft path and the legacy `#guided-section-apply` section alone except where the per-image public rendering strictly requires it. Keep `id="guided-section-review"` and `id="guided-section-apply"` present as the card container; `#guided-section-apply` is no longer a public navigation stage but it is still the container element.

HOW TO VERIFY
Run: npx vitest run apps/prototype-wp-alt-context/js
Admin tests must stay green. Public tests asserting the Preview button or the before/after grid WILL fail; that is expected. Do not weaken or delete a test. Report each failing test by exact name and file; the tests lane owns the rewrite.

CONSTRAINTS
- Preserve atomic write paths; do not split one apply into several sequential mutations. [rg-002]
- Primary controls reachable from zero state. [rg-003]
- Role semantics must match behaviour. [rg-004]
- `as const` status objects, no scattered magic strings. [sr-007]
- Design tokens only for any inline style. [sr-004]
- Commit only the one owned file.
- NON-GOALS: Co-Authored-By or AI attribution trailers; any edit outside the owned file; new dependencies; a new test framework.

COMMIT MESSAGE
guide v3: one editor beside each photo with inline apply

ADDITIONAL REQUIREMENT — finding GUIDEV3-1-STATE-BR-02 (medium, must be closed by this lane)
The reducer already exports `canApplyImageDraftPublic`, but the preview-free policy is currently unreachable from the UI. `applyGuidedDraftForImage(state, imageKey, visibleText)` only selects the public predicate when the third argument `visibleText` is supplied; called with two arguments it falls back to the admin predicate and still demands `previewedVersion === draftVersion`.

Therefore, in public scope:
- The apply handler this lane wires MUST pass the visible textarea string as the third argument to `applyGuidedDraftForImage`. Two-argument calls are forbidden on the public path.
- The Apply control's enabled state MUST be derived from `canApplyImageDraftPublic(state, draft)`, never from `canApply(state)` and never from the admin per-image predicate.
- Validate with `trim()` but pass and store the visible string unchanged.
- Admin scope keeps calling the two-argument form so its preview gate is untouched.
A public Apply that cannot enable once its stated precondition is met violates FORM-09 responsive enabling. Report `ALREADY-FIXED:` if you find this already wired.
