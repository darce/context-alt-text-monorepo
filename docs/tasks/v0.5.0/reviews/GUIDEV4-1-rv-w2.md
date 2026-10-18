# GUIDEV4-1 wave-2 review

Scope: review of the supplied non-test diff `0e0e1e22b..6ae597c50` and the current worktree, against the proposed screens and the distilled heuristics canon. This checkout has no task history, so the supplied diff was used.

## Findings

- **RV-W2-01 — HIGH —** `apps/prototype-wp-alt-context/js/admin/guidedPrototype/RecordedWalkthrough.tsx:488-495`. The hub still passes only the aggregate `demo.outcome` to `GuidedOutcome`. The public component now requires per-photo summaries to establish `bothImagesFinished`; with the scalar input, `imageSummaries` is empty and it returns `null`, even after both photos are complete. The D1 result therefore never appears. **Suggested fix:** pass both `outcomeForPhoto` values and `outcomeReady(demo)` to `GuidedOutcome` from this call site.
- **RV-W2-02 — HIGH —** `apps/prototype-wp-alt-context/js/admin/guidedPrototype/RecordedWalkthrough.tsx:275`. The public entrance is mounted without `onFocusFirstNameQuestion`, so its new optional hook is undefined when Start is clicked. `handleBegin` focuses the context section, not the first name question, contrary to the B-screen Start behavior (A11Y-11). **Suggested fix:** pass a callback here that focuses the first photo's first name answer.
- **RV-W2-03 — HIGH —** `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedSamplePhoto.tsx:72-83`. The face overlay still receives `formatGuidedSimilarity` output as `similarityText`; the overlay displays that string both in its chip and accessible name. Hovering or focusing a face therefore exposes numeric match percentages, including the self-anchor score, despite the C1 requirement for strength in words and no percentages (HAI-08, AIPX-10). **Suggested fix:** supply word-only strength or no-score copy for public overlay faces instead of formatting the similarity value.
- **RV-W2-04 — MEDIUM —** `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedSamplePhoto.tsx:162-164`. The changed shared component renders only the collapsed AltText.ai caption for both scopes. Its existing admin caller still passes `showCurrentAltText` and `scope="admin"`, but those props no longer affect rendering; the admin photo loses its current-description and AltContext caption content even though the screen brief says the admin page does not change. **Suggested fix:** retain the previous admin caption branch and apply the reduced caption layout only to the public scope.

## Verification

- Ran the requested scoped command from `apps/prototype-wp-alt-context`: `npx vitest run js/admin/guidedPrototype/publicGuideCopy.test.ts js/admin/pages/guided/__tests__/GuidedSamplePhoto.test.tsx js/admin/pages/guided/__tests__/GuidedOutcome.test.tsx`. No local Vitest binary is installed, and `npx` produced no output while attempting to resolve it; the process was stopped after about 40 seconds. The host should run the scoped tests.
- Source files were not edited.
