# E21-20 REV2 final-four verdict

Lane `e21-20-fix1`. One commit per finding. TEST-15: mutate the covered production line, confirm RED, restore, confirm GREEN.

## E21-20-REV2-03

- status: fixed
- files: `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/WorkbenchFindingsPanel.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx`
- commit: `fix(e21-20): move findings Retry controls out of live regions (E21-20-REV2-03)`
- TEST-15 mutation: moved the error-state Retry button back inside the `role=status` region.
- RED: `REV2-03: error Retry sits outside the live region...` failed at `within(region).queryByRole('button')` — found `<button>Retry</button>` inside status.
- GREEN: restore (button after the live region, `aria-describedby="acx-findings-panel-error"`). REV1-04 now also asserts no button/link inside any `role=status`.

## E21-20-REV2-05

- status: fixed
- files: `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/WorkbenchFindingsPanel.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx`
- commit: `fix(e21-20): announce findings Retry progress and restore focus (E21-20-REV2-05)`
- TEST-15 mutation: dropped the `retrying` / `retryFailed` live-region branches so the error copy stayed `Could not load recognition findings.`
- RED: `REV2-05: Retry announces in-progress then a distinct failure...` failed — `getByText('Retrying recognition findings…')` not found; live region still showed the original sentence (`isLoading` stayed false).
- GREEN: restore local retrying state (not RQ `isLoading`). Retry stays focused during the attempt; success moves focus to Review next or `#acx-workbench-findings-heading`.

## E21-20-REV2-07

- status: fixed
- files: `apps/prototype-wp-alt-context/js/components/ui/__tests__/avatar.test.tsx`
- commit: `fix(e21-20): assert Avatar swap-frame on component rerender (E21-20-REV2-07)`
- TEST-15 mutation: `avatar.tsx` stopped calling `resolveAvatarRenderState` and dropped the render-phase src reset (`const state = resolveAvatarState(src, loadStatus)`).
- RED: both new component tests failed — `data-avatar-state` stayed `real` / `error` after rerender to `status=hold`. The old REV1-05 helper-only tests stayed green.
- GREEN: restore helper + render-phase reset.

## E21-20-REV2-09

- status: fixed
- files: `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx`, `apps/prototype-wp-alt-context/js/admin/styles/components/_review-queue.scss`
- commit: `fix(e21-20): keep drain copy and add queue Resync for gated clusters (E21-20-REV2-09)`
- TEST-15 mutation: restored the old ternary that replaces drain with repair-only copy and no Resync.
- RED: `REV1-02` and `REV2-09` failed — `All caught up — no items need review` and `getByRole('button', { name: 'Resync' })` missing.
- GREEN: restore drain + repair + Resync (`data.refetchTopUnlabeled()`). Live drain announcements include both sentences.
