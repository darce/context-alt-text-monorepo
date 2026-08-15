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
