# E21-15 MERGE-01 red-check
## One unavailable-image literal
- Mutation applied: `imageUnavailable: REPRESENTATIVE_IMAGE_UNAVAILABLE` (imported from faceThumbDisplay) -> `imageUnavailable: __('Representative image unavailable', 'alt-context')` with the import removed
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.source.test.tsx`
- Verdict: FAILED
- Failing assertion: `expect(matches).toHaveLength(1);`
- After restore: PASSED

## hideMissingLabel parity
- Mutation applied: `const hideMissingClass = hideMissingLabel ? \`${baseClass}--hide-missing-label\` : ''; const classes = [baseClass, stateClass, errorClass, hideMissingClass, className, callerUncropped].filter(Boolean).join(' ');` -> `const classes = [baseClass, stateClass, errorClass, className, callerUncropped].filter(Boolean).join(' ');` (prop left declared)
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/components/ui/__tests__/DurableFaceThumb.test.tsx`
- Verdict: FAILED
- Failing assertion: `expect(container.querySelector('.acx-durable-face-thumb--hide-missing-label')).toBeInTheDocument();`
- After restore: PASSED

## REV1-15 mutation 1
- Mutation applied: `identity_attachment_url: suggestion.identity_attachment_url ?? null,` -> deleted
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/api/recognition/__tests__ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.test.ts`
- Verdict: FAILED
- Failing assertion: `expect(suggestion).toHaveProperty('identity_attachment_url', IDENTITY_ATTACHMENT_URL);`
- After restore: PASSED

## REV1-15 mutation 2
- Mutation applied: `attachment_url: normalizeOptionalUrl(representative.attachment_url ?? null),` -> `attachment_url: null,`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/api/recognition/__tests__ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.test.ts`
- Verdict: FAILED
- Failing assertion: `expect(mapped).toHaveProperty('attachment_url', ATTACHMENT_URL);`
- After restore: PASSED

## REV1-15 mutation 3
- Mutation applied: ENRICHMENT_SOURCE_FIELDS dropped `['identityAttachmentUrl', 'identity_attachment_url']` and `['representativeAttachmentUrl', 'representative_attachment_url']`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/api/recognition/__tests__ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.test.ts`
- Verdict: FAILED
- Failing assertion: `expect(projected.enrichment).toEqual({ identityAttachmentUrl: ATTACHMENT_ONLY_URL });`
- After restore: PASSED

## REV1-15 mutation 4 — attachment-only preview survives the filter
- Mutation applied: `(preview) => preview.thumbUrl !== null || preview.mediaUrl !== null || preview.attachmentUrl != null` -> `(preview) => preview.thumbUrl !== null || preview.mediaUrl !== null`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/useWorkbenchFindings.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.test.ts`
- Verdict: FAILED
- Failing assertion: `expect(assignmentModel.previews.map((preview) => preview.key)).toEqual(['assignment-attach-only']);`
- After restore: PASSED
