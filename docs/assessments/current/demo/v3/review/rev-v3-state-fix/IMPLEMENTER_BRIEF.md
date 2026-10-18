LANE v3-state-fix — strengthen the admin preview-gate regression test

OWNED FILES (edit only this one)
- apps/prototype-wp-alt-context/js/admin/guidedPrototype/state.test.ts

CONTEXT
Finding GUIDEV3-1-STATE-BR-03, medium, from the Luna MAX review of the v3-state delta.

The test at state.test.ts:501, `canApplyImageDraftPublic does not require a preview while canApply keeps the admin gate`, proves the admin preview gate survives by asserting `expect(canApply(ready)).toBe(false)`. `canApply` is a whole-state rollup, and `canApplyImageDraft` is module-private so the test cannot name it directly. The rollup can keep returning false for a reason unrelated to the preview gate, so the per-image admin gate could be deleted from `state.ts` without this test failing. The assertion does not protect the invariant it claims to protect.

The reducer under test, `applyGuidedDraftForImage(state, imageKey, visibleText?)`, is exported and is the honest seam:
- called with two arguments it takes the admin path and requires `previewedVersion === draftVersion`
- called with three arguments it takes the public path via `canApplyImageDraftPublic`

TASK
1. In the existing test at line 501, keep the two `canApplyImageDraftPublic` and `canApply` assertions and ADD behavioural assertions through the exported reducer, using a state whose draft has NOT been previewed:
   - `applyGuidedDraftForImage(ready, TRIBECA)` with two arguments returns a state whose `drafts[TRIBECA].appliedAltText` is unchanged from `ready.drafts[TRIBECA].appliedAltText`, and whose `applicationHistory` length is unchanged. The admin gate refused.
   - `applyGuidedDraftForImage(ready, TRIBECA, '<some visitor text distinct from both the draft text and the applied text>')` returns a state whose `drafts[TRIBECA].appliedAltText` equals that exact visitor string. The public path applied.
   Assert on the returned values, not on identity of the state object.
2. Add a second assertion that the admin gate is genuinely a preview gate, not an accident: take the same `ready` state, run it through `previewGuidedDraft` so `previewedVersion === draftVersion`, then assert the two-argument `applyGuidedDraftForImage` now DOES apply. Without this, step 1 could pass because the state was unappliable for some other reason.
3. Give the test a name that states the invariant, for example `applyGuidedDraftForImage refuses an unpreviewed draft for admin and accepts the visible text for public`.

HOW TO VERIFY
- `cd apps/prototype-wp-alt-context && npx vitest run js/admin/guidedPrototype/state.test.ts`
- `cd apps/prototype-wp-alt-context && npx tsc --noEmit -p tsconfig.json`
Report the pass and fail counts you see. One pre-existing failure in this file is expected: a fixture-note assertion at roughly line 197 that no longer matches `state.ts`. Leave it alone; it belongs to a separate finding.

CONSTRAINTS
- Do NOT edit `state.ts`. Do not export `canApplyImageDraft` to make the test easier; the point is to assert behaviour through the public seam.
- Do NOT weaken, skip, or delete any existing assertion.
- Import only symbols that `state.ts` already exports.

NON-GOALS: Co-Authored-By or AI attribution trailers; any edit outside the owned file; changing production code; touching the pre-existing fixture-note failure.

COMMIT MESSAGE
test(guided): assert the admin preview gate through the exported apply reducer
