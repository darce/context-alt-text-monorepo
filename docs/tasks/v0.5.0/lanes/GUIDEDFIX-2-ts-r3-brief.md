# GUIDEDFIX-2 · lane `guidedfix-2-ts` · round 3

One finding. Fix it, do not widen the lane.

## Finding GF2-R3-X01 (high)

`apps/prototype-wp-alt-context/js/admin/guidedPrototype/liveDescription.ts`

The trust floor's **upper** bound is the local ceiling, so the server's disclosed
budget can never exceed the guess it was meant to replace.

```ts
export const isGuidedLiveDeadlineDisclosed = (value: unknown, localCeilingMs: number): value is number =>
  typeof value === 'number' &&
  Number.isFinite(value) &&
  value >= GUIDED_LIVE_DEADLINE_FLOOR_SECONDS &&
  value * 1000 <= localCeilingMs;          // <-- the defect

export const resolveGuidedLiveDeadlineMs = (localCeilingMs, deadlineSeconds, gpu) => {
  if (!isGuidedLiveDeadlineDisclosed(deadlineSeconds, localCeilingMs)) return localCeilingMs;
  const totalSeconds = deadlineSeconds + guidedLiveWarmupLegSeconds(gpu);
  return Math.min(localCeilingMs, totalSeconds * 1000 + GUIDED_LIVE_DEADLINE_SLACK_MS);
  //     ^^^^^^^^^^^^^^^^^^^^^^^ the compounding half
};
```

Two things are wrong and they reinforce each other.

**1. The band is the wrong shape.** `deadline_seconds` is a GENERATION budget.
`localCeilingMs` is the WHOLE local wait (generation **plus** the warm-up leg,
or on a warm run generation alone). Comparing one against the other is a
category error. On a warm run `localCeilingMs` is exactly
`GUIDED_LIVE_WARM_CEILING_SECONDS * 1000` = 180 000, so any disclosed budget
above 180 is called implausible and discarded.

**2. The result is re-capped by the same ceiling.** Even a value that passes
the predicate is clamped by `Math.min(localCeilingMs, ...)`, so the server's
disclosure can never move the wait past the local guess. That defeats the whole
premise of the round-2 change: the server is the authority, the local ceiling is
only the fallback for when nothing was disclosed.

**Why this bites now.** The svc lane landed on this branch at `5e93b87c0`.
`packages/shared-contracts/schemas/scene-describe-run.schema.json` now defines
`deadline_seconds` as the run's end-to-end generation budget, *"derived at accept
from the per-item generation timeout the worker is handed (which depends on the
active adapter, not on `ACX_DESCRIPTION_TIMEOUT_SECONDS` alone) multiplied by the
run's unique item count"*. Read
`apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py`
around the `item_envelope_seconds(...)` derivation and the schema file before you
start — the contract text is the specification here, not this brief.

So an adapter whose per-item generation timeout is 240 s discloses `240` on a warm
guided run. The predicate rejects it, the client falls back to exactly 180 s, and
the panel declares `TIMED_OUT` at 3:00 on a run the server will still honour for
another minute. That is finding **GF2-R2-P01 reappearing through the guard added
for GF2-R2-P11**.

The guided path is single-item today (`guidedLiveRequestPayload` always sends
`[mediaId]`), so the unique-item multiplier does not bite yet. The
adapter-dependent per-item timeout does.

## Required fix

1. **Validate against a generation-shaped band, independent of GPU state.**
   Keep `GUIDED_LIVE_DEADLINE_FLOOR_SECONDS = 30` as the lower bound. Add a named
   exported upper bound — suggested name `GUIDED_LIVE_DEADLINE_CEILING_SECONDS` —
   that bounds a *believable generation budget*, not a local wait. Pick the number
   deliberately and justify it in the doc comment against the svc derivation
   (per-item timeout x unique item count, guided sends one item). Do not derive it
   from `GUIDED_LIVE_WARM_CEILING_SECONDS` or from anything GPU-state-dependent:
   that coupling is the defect.
   `isGuidedLiveDeadlineDisclosed` must stop taking `localCeilingMs` at all.

2. **Stop re-capping a disclosed budget.** When a budget IS disclosed,
   `resolveGuidedLiveDeadlineMs` returns
   `(deadlineSeconds + guidedLiveWarmupLegSeconds(gpu)) * 1000 + GUIDED_LIVE_DEADLINE_SLACK_MS`
   with no `Math.min(localCeilingMs, ...)`. `localCeilingMs` stays as the return
   value for the not-disclosed branch only.

3. **Preserve the two invariants the round-2 work established.** `deadline_raised`
   must stay monotonic upward (`Math.max(state.deadlineMs, raisedMs)`) and
   re-deriving from the same `state.disclosedDeadlineSeconds` against a wider
   ceiling must stay idempotent. Recheck both after the change — dropping the
   `min` alters what "idempotent" means here, so the existing comment at
   `case 'deadline_raised'` may now be stating something untrue. Fix the prose if
   so; a comment that describes the old algebra is worse than none.

4. Update the doc comments on `GUIDED_LIVE_DEADLINE_FLOOR_SECONDS`,
   `isGuidedLiveDeadlineDisclosed` and `resolveGuidedLiveDeadlineMs` so they state
   the new band and say plainly that the disclosed budget is not clamped. sr-005
   still applies: this is boundary data from an API and earns an explicit
   predicate, not an assertion helper.

## Tests (failing-first)

Add to `liveDescription.test.ts`, and extend `useGuidedLiveDescription.test.tsx`
where the wait length is observable:

- warm GPU (`ready`), disclosed `240` -> deadline is `240_000 + 15_000`, **not**
  `180_000`. This is the regression test for the finding; write it first and watch
  it fail.
- cold GPU (`unknown`), disclosed `240` -> `(240 + 510) * 1000 + 15_000`.
- disclosed `29` (under the floor) -> falls back to `localCeilingMs`.
- disclosed just above the new ceiling -> falls back to `localCeilingMs`.
- `null` / `undefined` / `NaN` / `Infinity` / `'240'` / `0` / negative -> fall back.
- `deadline_raised` after a warm-pinned accept that a later poll reveals as cold
  still widens the wait, and firing it twice yields the same deadline.

Do not weaken or delete an existing test. If a current test asserts the 180 s
clamp, it is asserting the bug — rewrite it to the new contract and say so in the
commit body.

## Boundaries

- Touch only `apps/prototype-wp-alt-context/js/admin/guidedPrototype/`.
- Do not touch `apps/prototype-description-service/**` — the svc side is landed
  and correct; the contract it publishes is what you conform to.
- Do not touch `apps/prototype-wp-alt-context/src/**`.
- Do not change the polling cadence or the retry policy.
- No AI attribution trailers in the commit message.

## Verify

```
node_modules/.bin/tsc --noEmit -p tsconfig.json
npx vitest run apps/prototype-wp-alt-context/js/admin/guidedPrototype
```

(from `apps/prototype-wp-alt-context` for the tsc line.)

## Done

`liveDescription.ts` validates the disclosed budget against a generation-shaped
band that does not mention GPU state, a disclosed budget larger than the local
guess actually lengthens the wait, and a warm 240 s run no longer times out at
3:00. Committed on `feature/guidedfix-2-ts`, lane test command green.
