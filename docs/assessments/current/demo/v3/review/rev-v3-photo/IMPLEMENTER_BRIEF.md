LANE v3-photo — provider comparison headings, face-evidence title, and the duplicated baseline span.

OWNED FILES (edit only these):
  apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedSamplePhoto.tsx
  apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedPhotoFaces.tsx

Zero edits outside these two files. Do not touch RecordedWalkthrough.tsx, publicGuideCopy.ts, state.ts, or any SCSS. If you believe another file must change, stop and report it as a handoff note instead of editing it.

CONTEXT
GuidedSamplePhoto renders one `<figure data-testid="guided-photo-${photo.key}">` per press photo for both the public guide and the admin route. Inside `<figcaption>` it renders an optional current-alt span (gated by the `showCurrentAltText` prop) followed by `.acx-guided-page__caption-compare`, which holds `<AltContextCaption>` then `<AltTextAiCaption>` in that DOM order.

The two caption sections take their headings from `guidedCopy('context.photo.altcontext_title')` and `guidedCopy('context.photo.alttextai_title')`.

The component's props type already declares `scope: GuidedSamplePhotoScope` ('public' | 'admin') but the function body does NOT destructure it. It is currently dead. This lane makes it live.

Lane v3-copy has already landed these keys in `publicGuideCopy.ts`; import `guidedCopy` from '../../guidedPrototype/publicGuideCopy' exactly as the file already does and use them:
  'comparison.altcontext.public'  -> 'AltContext — with people roster'
  'comparison.alttextai.public'   -> 'AltText.ai — no names or keywords'
  'faces.title.public'            -> 'Names suggested by AltContext'

TASK

1. Destructure `scope` in the `GuidedSamplePhoto` function signature and thread it into `AltContextCaption` and `AltTextAiCaption` as a prop.

2. In `AltContextCaption`, when scope === 'public', render the heading from `guidedCopy('comparison.altcontext.public')`. When scope === 'admin', keep `guidedCopy('context.photo.altcontext_title')` exactly as today.

3. In `AltTextAiCaption`, when scope === 'public', render the heading from `guidedCopy('comparison.alttextai.public')`. When scope === 'admin', keep `guidedCopy('context.photo.alttextai_title')`.

4. Keep AltContext first in DOM order and visual order. Do not reorder, do not restyle, do not add any "correct answer" or "better" framing to either provider. Preserve every provenance paragraph, provider link, credit, captured-on date, and generated-on date exactly as they are.

5. The duplicated baseline: when scope === 'public', do not render the `showCurrentAltText` span in `<figcaption>` at all. The real current alt text lives in the review card, which is where the user is about to replace it. In admin scope the span must still render exactly as today. Do not delete the `showCurrentAltText` prop or the `currentAltText` prop; both stay in the public signature and the admin path keeps using them.

6. GuidedPhotoFaces renders `<h4 id={`guided-faces-${photoKey}-title`}>{title}</h4>` from a `title` prop supplied by its parent. Do NOT hardcode copy in this component and do NOT change the id or the `data-testid="guided-faces-${photoKey}"` value. The only permitted change here is if the heading level or wrapper needs to stay consistent with the figure it now sits under; if nothing needs to change, change nothing and say so. The parent passing `faces.title.public` is another lane's job.

7. Do not alter matching thresholds, similarity scores, face bounding boxes, the GuidedFaceOverlay call, `overlayFacesForPhoto`, the weak-match strength computation, or any source image metadata. Do not add probability-of-correctness or verified-identity language.

8. Preserve `isUsableNaturalSize` space reservation, the `data-orientation` attribute, and the image-failure placeholder path untouched.

HOW TO VERIFY
Run: npx vitest run apps/prototype-wp-alt-context/js
Existing tests must stay green. Do not weaken or delete a test to make it pass. If an existing assertion encodes the old admin-only heading for the public scope, report it as a handoff note naming the exact test; the tests lane owns the update.

CONSTRAINTS
- Design tokens only in any style you touch (--acx-*). No hex literals, no raw px font sizes. [sr-004]
- Centralize status values as `as const` objects; no scattered magic strings. [sr-007]
- Commit only the two owned files.
- NON-GOALS: Co-Authored-By or AI attribution trailers in the commit message; any edit outside the owned files; new dependencies; a new test framework.

COMMIT MESSAGE
guide v3: public provider comparison headings and single baseline
