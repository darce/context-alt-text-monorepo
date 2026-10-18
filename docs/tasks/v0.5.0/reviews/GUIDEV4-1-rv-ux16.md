# GUIDEV4-1 UX-16 review

Scope: review of the supplied non-test UX-16 diff for the public review layout, caption comparison, and photo-match lightbox, plus the current worktree. Compared with the shared contract and proposed screens. This checkout has no task history, so the supplied diff was used.

## Findings

- **RV-UX16-01 — HIGH —** `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedSamplePhoto.tsx:53`. On the admin `/guided-prototype` page, focusing a face overlay now shows `89.4% match` instead of the previous admin diagnostic text `89.4%`; a cluster anchor also receives the public “No score” wording. This changes the admin overlay branch and leaks public copy into the admin scope. **Suggested fix:** restore the pre-UX-16 admin overlay text path in this file, keeping the new percentage copy in the public branch only.
- **RV-UX16-02 — MEDIUM —** `apps/prototype-wp-alt-context/js/admin/styles/components/_guided-prototype.scss:455`. The shared lightbox gallery now sizes its images with `--acx-guide-lightbox-tile-size`, but that variable is declared only in the public guide stylesheet. In the admin guide, opening Compare photos leaves the variable unset, so the width and height declarations are invalid and reference photos can render at their intrinsic size and overflow the dialog. **Suggested fix:** provide the tile-size value on the shared lightbox selector in this stylesheet so the admin dialog retains a bounded tile size.

## Verification

- Attempted the requested scoped command: `cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/guided/__tests__/GuidedFaceMatchCard.test.tsx js/admin/pages/guided/__tests__/GuidedSamplePhoto.test.tsx`. There is no local `node_modules`; `npx` produced no output while resolving Vitest and was stopped. The host should run these tests.
- No source files were edited.
