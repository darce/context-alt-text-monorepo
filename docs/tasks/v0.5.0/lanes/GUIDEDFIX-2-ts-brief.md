# GUIDEDFIX-2 lane `guidedfix-2-ts`: honour the server-disclosed deadline in the guided live panel

Branch `feature/guidedfix-2-ts` @ `ed48d331ffff19af12739ea4e76b93df23c2a089`.
Findings id range if you must record a blocker: `GUIDEDFIX-2-TS-01` .. `GUIDEDFIX-2-TS-09`. Do not reuse other ids.
Owned paths: `apps/prototype-wp-alt-context/js/admin/guidedPrototype/**` only. Do not touch `src/**`, the description
service, `hooks/useDescribeRunProgress.ts`, or `utils/http.ts`.

## The defect (coordinator-verified against the tree)

`useGuidedLiveDescription.ts:50` — `GUIDED_LIVE_WARM_CEILING_SECONDS = 180`.
`liveDescription.ts:65` — `GUIDED_LIVE_WAIT_CEILING_SECONDS = 510`.
`useGuidedLiveDescription.ts:121` picks one of them from the GPU state and that becomes `state.deadlineMs`.

Both numbers are guesses. The server's real bound is `DescriptionSettings.generation_timeout_seconds` (default 180, env
`ACX_DESCRIPTION_TIMEOUT_SECONDS`) and the client never sees it. If an operator sets it to 60 the learner watches a
"warming" panel for 120 s after the run already died; if they set it to 400 the warm client gives up 220 s early on a run
that would have finished. Canon: [RES-02] the party that enforces a bound must disclose it and the waiter must use it
(Release It! ch-5); [PERF-09] a client cannot beat a budget it cannot see; CARD-09 feedback-bounded-waiting — the wait
must be bounded by feedback from the thing being waited on, not by a constant.

## Wire contract (pinned by the coordinator — do not rename)

The submit 202 and every status poll now carry `deadline_seconds: number | null` on the describe-run payload (sibling
lanes are adding it server-side and passing it through WP). Treat `null`/absent as "server did not disclose" and fall
back to today's local ceiling — the client must keep working against an old backend.

## Required semantics

1. On the submit response, when `deadline_seconds` is a finite positive number:
   `deadlineMs = min(localCeilingMs, deadline_seconds * 1000 + GUIDED_LIVE_DEADLINE_SLACK_MS)`.
   Slack is a small named constant (suggest 15 000 ms) covering poll cadence + transport — the client should time out
   *just after* the server, never before it, and never wildly after it. Do not let the server value *extend* the wait
   beyond the local ceiling: the local ceiling is the learner-patience bound and still wins upward.
2. The cold-start case: when `gpu` is not `ready`, the local wait ceiling includes warm-up time the server's generation
   budget does not. Keep the existing warm/cold selection for `localCeilingMs`; then apply the min(). Decide and encode
   the invariant for cold + disclosed-60s (does warm-up time get added to the disclosed budget, or not?) and write the
   reducer test that names it.
3. A status poll that carries a *different* `deadline_seconds` than the submit did is a server bug; do not chase it.
   Take the value once, at submit accept, and ignore it on polls. Add the reducer test.
4. Put the arithmetic in a pure exported function in `liveDescription.ts` (e.g. `resolveGuidedLiveDeadlineMs`) and test
   it as a table; the reducer calls it. No new state fields beyond what is needed to carry the resolved deadline.
5. Validate the boundary value explicitly (`typeof === 'number' && Number.isFinite && > 0`), not with an assertion helper
   — this is API data (sr-005).
6. Type the field on whatever payload type the guided client reads. If that type lives outside your owned paths, extend
   it via a local intersection type in `liveDescription.ts` rather than editing the shared file; note it in the report so
   the coordinator can hoist it.

## Test obligations (acceptance bar — failing-first, [TEST-06]/[TEST-15])

In `liveDescription.test.ts`:
- `resolveGuidedLiveDeadlineMs` table: disclosed 60/warm → 75 000; disclosed 400/warm → 180 000 (local wins upward);
  disclosed 60/cold → whatever invariant you chose in (2), named in the test title; `null` → local ceiling;
  `NaN`/negative/`Infinity` → local ceiling.
- reducer: submit-accept with `deadline_seconds: 60` sets `state.deadlineMs` to 75 000; a later poll with
  `deadline_seconds: 900` leaves it at 75 000.

In `useGuidedLiveDescription.test.tsx`:
- the existing timeout assertions at ~lines 220-258 and 332-346 keep passing with a fake client that omits
  `deadline_seconds`
- a new case: fake client returns `deadline_seconds: 30` on submit with gpu ready; advancing fake timers 46 s reaches
  `TIMED_OUT`; advancing only 40 s does not.

Mutation check you must run before committing: change the `min` to `max` in the resolver → the "local wins upward" row
must go red. State that you ran it.

Never weaken or delete a test. `npx tsc --noEmit -p apps/prototype-wp-alt-context` must be clean.

## Commit

One commit, subject `guidedfix-2(ts): honour the server-disclosed deadline in the guided live panel`. No attribution
trailers. Lane test command: `npx vitest run apps/prototype-wp-alt-context/js/admin/guidedPrototype`. Report the pass
count.
