# GUIDEDGPU-1 / guidedgpu-1-rev-s1a — adversarial review, slice S1

You are an adversarial reviewer. Refute this slice. Do not admire it. When you are
uncertain whether something is a defect, record it: a false positive costs a paragraph,
a missed defect ships to a public demo.

**Read-only.** Do not edit any file. Do not commit. Do not run the test suite (it is slow
and already green). `git diff`, `git log`, `grep`, and reading files are all fine.

## The diff under review

Branch `feature/guidedgpu-1`, tip `6638d51324d5b1aa6049bb5428f55a020dbae23b`.
Slice S1 is commit `2c98fe7f31415246ce3d1151c24b8c8349501863` and its three predecessors:

```
git diff main...2c98fe7f3
```

In scope, nothing else:

- `apps/prototype-wp-alt-context/js/admin/guidedPrototype/liveDescription.ts` + test
- `apps/prototype-wp-alt-context/js/admin/guidedPrototype/useGuidedLiveDescription.ts` + test
- `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedLiveDescriptionPanel.tsx` + test
- `apps/prototype-wp-alt-context/js/admin/api/config.ts` + `js/admin/api/__tests__/guidedLiveMediaId.test.ts`
- `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedDescriptionReview.tsx`, `GuidedPrototypePage.tsx`
- `apps/prototype-wp-alt-context/js/admin/styles/components/_guided-prototype.scss`
- `apps/prototype-wp-alt-context/src/admin/class-admin.php` + `tests/Unit/AdminTest.php`

## What it is supposed to do

The guided prototype is a teaching screen. It gains an optional "See it run live" panel:
the learner presses **Describe it live**, the panel submits a describe run for one
configured attachment, polls queued -> warming (GPU cold start) -> describing ->
ready/degraded, and shows the resulting sentence BESIDE the saved draft. It must never
overwrite the draft and never change what Apply would write.

## Prior art — chase this first

The codemap says these already exist in this repo. The highest-value question is whether
this slice reinvented any of them.

- `js/public/demo-describe.js` — already has `pollRun` (lines 214-258) and a
  `PublicDemoGpuState` type. A public demo that already polls a describe run through GPU
  states.
- `js/admin/hooks/useJobStateMachine.ts` and its `Effects` / `Mutations` /
  `DerivedState` siblings — the admin polling machine.
- `js/admin/pages/workbench/gpuStatePresentation.ts` — `gpuStateNotice` (111-128) and
  `degradedNotice` (54-58). Existing user-facing copy for GPU and degraded states.
- `js/admin/utils/retryPolicy.ts`, `js/admin/utils/recognitionCooldown.ts` — existing
  backoff and cooldown policy.

Read the relevant parts. If the new code duplicates polling, backoff, GPU-state
vocabulary, or degraded-state copy that one of those already owns, that is a finding.
Name the module that should have been reused and say what will drift when one is changed
and the other is not.

## Lenses, in priority order

1. **Duplication of existing owned behaviour** (above).
2. **The additive promise.** The panel claims a live run "never changes the draft above,
   and it never changes what Apply would write." Try to break that from the code. Any
   state, race, re-render, shared store, cancel or timeout path where a live result could
   reach the draft, the Apply payload, or the lesson progress.
3. **Bounded-ness.** There is a wait ceiling (`GUIDED_LIVE_WAIT_CEILING_SECONDS`) and a
   poll loop. Can it leak a timer, poll after unmount, poll forever, double-submit on a
   fast double click, or keep polling after cancel? Does cancel actually cancel
   server-side, and what happens when the cancel request itself fails?
4. **Trust boundary.** `guided_live_media_id` arrives via `wp_localize_script`, which
   stringifies numbers. Check the PHP side in `class-admin.php` and the JS normalization
   in `config.ts`. Is it validated at the boundary or trusted? Does a missing or garbage
   value degrade only this capability, or take the whole admin config load down?
5. **Accessibility.** Status must pair colour with a second channel (a glyph), and the
   live region must announce phase changes without being noisy. Check `role="status"` and
   `aria-live`, the disabled-button explanation, and the SCSS: design tokens `--acx-*`
   only. Raw hex, px literals for radius or shadow, or numeric font-weights violate repo
   rule sr-004.
6. **Honest failure copy.** Timed-out, cancelled, unavailable and empty-description states
   must each say plainly that nothing was applied. Find any state whose copy overstates
   what happened.
7. **Tests that do not test.** Any test that would still pass if the behaviour it names
   were deleted or inverted. Check the fake-timer tests especially: do they actually
   advance into the state they claim to assert?

## Recording findings

Write every finding under `task_ref='GUIDEDGPU-1-REV-r09076638-S1-A'`. That scratch ref is
yours alone and is currently empty. Do not write under any other task_ref, and in
particular never under `GUIDEDGPU-1` itself.

Use the handoff Python API from the package root:

```python
from workbay_handoff_mcp import RuntimeConfig, configure_runtime, review_findings
```

with `review_findings(review={"operation": "batch_record", "session":
"codex-review-r09076638-S1-A", "task_ref": "GUIDEDGPU-1-REV-r09076638-S1-A", "findings":
[...], "actor": {"branch": "feature/guidedgpu-1", "commit_sha":
"6638d51324d5b1aa6049bb5428f55a020dbae23b"}})` — one atomic batch when you have three or
more. Finding ids `GUIDEDGPU-1-REV-r09076638-S1-A-01`, `-02`, and so on. Each needs
`finding_id`, `severity` (high|medium|low), `file_path` (repo-relative), `description`,
and `details` with `line_start`, `line_end`, `fix`.

A description must name the concrete failure: the input or sequence, and the wrong
result. "Consider extracting this" is not a finding. "A second click before the first
submit resolves starts two runs, because `canRequest` derives from `state.status` which is
still IDLE until the promise settles; the second run poll then overwrites the first run
text" is a finding.

`ruff`/`eslint`/`prettier` style noise is at most `low` and must be prefixed
`lint(<tool>):`.

Finish by reporting the count, the ids and severities, and the single most serious thing
you found.
