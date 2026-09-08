# GUIDEDGPU-1 fix lane: retire the bespoke guided poll loop

Branch `feature/guidedgpu-1` @ `6638d51324d5b1aa6049bb5428f55a020dbae23b`.
Findings id range: `GUIDEDGPU-1-FIX-01` .. `GUIDEDGPU-1-FIX-19`. Do not reuse other ids.

## The defect (verified by the coordinator, not a hypothesis)

`js/admin/guidedPrototype/useGuidedLiveDescription.ts` runs two effects against one clock:

- a 1000 ms `setInterval` dispatching `{kind:'tick'}` (`TICK_MS = 1000`, line 42)
- a `setTimeout` scheduled at `guidedLivePollDelayMs(attemptRef.current)` whose dependency
  array includes `state.elapsedMs`

Every tick mutates `state.elapsedMs`, so the poll effect tears down and re-arms once per
second. `guidedLivePollDelayMs` (liveDescription.ts:97-98) is `min(500 * 2**attempt, 5000)`.
Attempt 0 = 500 ms fires. Attempt 1 = 1000 ms races the teardown. Attempt 2 = 2000 ms can
never elapse inside a 1000 ms window. Polling dies ~1.5 s in; the panel sits on the warming
copy until the 510 s ceiling expires as `TIMED_OUT`. The vitest suite is green only because
every timer advance is wrapped in `act(async ...)`, which defers the re-render that would
trigger the teardown — the test harness hides the production behaviour.

## Required remedy: adopt the shared hook, do not patch the dependency array

Removing `state.elapsedMs` from the dep array makes the symptom go away and leaves the
duplication live. Do not do that.

`js/admin/hooks/useDescribeRunProgress.ts:107-252` already owns this exact poll, over the
exact same fetcher. The guided hook's `defaultClient.poll` **is** `fetchBulkDescribeRun`,
and its submit payload is `{media_ids:[mediaId]}` — the guided live run is a bulk describe
run of one item. The shared hook additionally has, and the guided copy lacks:

- `getDescribeRunRefetchInterval` (66-83): a pure, invertible poll predicate
- `gateRefetchInterval`: the shared recognition-cooldown gate
- `isDescribeRunTerminal`: the canonical terminal predicate
- frozen-poll streak accounting (abort/timeout keeps polling; hard error stops)
- `updateStallState` (214-224): the stall indicator
- `gpuState` carried on the same poll

Deliverable: `useGuidedLiveDescription` sources run status from `useDescribeRunProgress`
(or a thin shared extraction of it) and deletes its own `setTimeout` poll effect,
`guidedLivePollDelayMs`, `POLL_BASE_MS`, `POLL_CEILING_MS`, and `attemptRef`. The guided
reducer, phase ranking, naming disclosure, and wait ceilings stay — they are guided-specific
policy, not plumbing. Keep the `GuidedLiveDescriptionClient` seam if tests need it, but its
`poll` member must go away with the loop it fed.

If, and only if, a concrete blocker makes adoption impossible in this lane, stop and record
a finding stating the blocker with file:line evidence. Do not silently fall back to the dep-array patch.

## Also close in the same change

- The re-declared GPU-state / phase string unions in `liveDescription.ts:52-54` duplicate
  the canonical `GPU_STATE` / describe-run status enums. Import the canonical ones.
- The 1000 ms `setInterval` tick: the shared hook already ticks stall state once per second.
  Do not keep two independent 1 Hz clocks in one panel.
- Cancel must remain side-effect-free with respect to the saved draft, and must not orphan a
  paid GPU run: confirm cancel still calls `cancelBulkDescribeRun` and that a cancelled run
  cannot leave the backend burning burst time. Record a finding if it can.

## Test obligations (these are the acceptance bar)

1. **Prove the green can go red.** Add a regression test that fails on the current
   `6638d513` implementation and passes after the fix. It must exercise the poll across
   more than two attempts with real re-renders — not every advance wrapped in
   `act(async ...)`. If your new test also passes on the unfixed code, it is not testing
   the defect; iterate until it fails there. State in your summary the exact command and the
   observed failure output on the unfixed tree.
2. **No call-count-only assertions.** Assert observable panel state (rendered copy, testids,
   terminal status), not `expect(pollSpy).toHaveBeenCalledTimes(n)`.
3. Existing guided tests must stay green: `npx vitest run js/admin/guidedPrototype` from
   `apps/prototype-wp-alt-context`. Run `npx tsc --noEmit` too.

## Canon basis (cite in your commit body)

REF-26 (DRY is duplicated *intent*, not duplicated text), DBG-10 (symptom patches leave the
defect live; then sweep for sibling defects), DOM-01/DOM-02 (generic plumbing already solved
in this codebase), REF-19 (no information leakage), TEST-15 (count checks that never query
the real surface; prove the green can go red), TEST-06 (watch it fail once), DIAG-08
(QA harness is not production), REF-27 (do not program by coincidence), CON-22 (concurrent
correctness is not a test artifact), PRINCIPLES-11 / CARD-03 (progress bars lie),
CON-04 / RES-20 (orphaned paid work on cancel), INT-08 (cancel is side-effect-free).
REF-12/YAGNI was checked as the countervailing card and does not apply: its own
>=2-consumers exemption is already satisfied.

## Out of scope

Do not touch `js/public/demo-describe.js`, the PHP admin surface, the SCSS, or the ux-map
docs. Two review lanes are reading those at this same SHA.
