# GUIDEV4-1 wave-3 review

Scope: review of the supplied non-test diff `6ae597c50..e0136803f` for l2b names and l2c review, excluding the l2d `GuidedSamplePhoto.tsx` fix wave, plus the current worktree. Compared with the proposed screens and the distilled heuristics canon. This checkout has no task history, so the supplied diff was used.

## Findings

- **RV-W3-01 — MEDIUM —** `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedDescriptionReview.tsx:543`. After a visitor uses an edited description, Keep remains enabled because it only checks whether the names were answered. Clicking it calls the keep action, which restores the pre-Use description and clears the application history, although the button says “Keep the current description” while the current description is now the one just applied. That silently replaces the visible text and removes the direct Undo path (INT-06, INT-09). **Suggested fix:** disable Keep while this photo's outcome is `APPLIED`; Undo can restore the prior text before the visitor chooses Keep.
- **RV-W3-02 — LOW —** `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedDescriptionReview.tsx:419`. If a visitor clears the editor and presses Use, the component sets `emptyError`; pressing Keep afterward succeeds but leaves the editor marked invalid with its “description cannot be empty” alert beside “You kept the current description.” The stale error is unrelated to the completed Keep action and can confuse readers and screen readers (A11Y-21). **Suggested fix:** clear `emptyError` in `handlePublicKeep` before announcing the Keep status.

## Verification

- The requested scoped test command could not run: no local Vitest binary is installed. `npx` stalled while resolving Vitest from the registry and was stopped; an offline retry failed with `ENOTCACHED` because there was no cached package response.
- Source files were not edited.
- Known hub wiring and legacy-DOM findings routed to l3/l4/l5 were excluded as instructed.
