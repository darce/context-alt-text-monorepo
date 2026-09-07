# Guided live description — server-negotiated deadline (GUIDEDFIX-2)

Scope: what the operator sees once the panel stops guessing a local ceiling and
adopts `deadline_seconds` disclosed by the scene service at accept time.

Wire fact: `POST /scene/describe/run` returns `deadline_seconds` (float, may be
null). It is the server's GENERATION budget for the accepted run
(`ACX_DESCRIPTION_TIMEOUT_SECONDS`, default 180) and it explicitly EXCLUDES GPU
warm-up. A scale-to-zero pod pays `ACX_GPU_WARMUP_TIMEOUT_SECONDS` (default 510)
before generation starts, so the panel adds that leg back itself whenever
`gpu_state` is not `ready`:

```
deadlineMs = min(
  localCeilingMs,
  (deadline_seconds + (gpu_state === 'ready' ? 0 : 510)) * 1000 + slack
)
```

This is the same total the WordPress proxy already discloses —
`src/api/class-public-demo-describe-controller.php::public_deadline_seconds()`
returns `$warmup + $inference` — so the client's cold ceiling is 510 + 180 =
690 s (11:30), not 510 s. Null, or anything outside a plausible band
(under 30 s, or longer than the local ceiling), keeps the local ceiling.

The disclosed budget is kept verbatim in reducer state, not folded into the
deadline. When a poll reveals the GPU is colder than the submit assumed, the
deadline is re-derived from the same disclosure against the wider ceiling and
the larger of the two wins. The re-derivation is idempotent, so it needs no
one-shot latch — and a latch is precisely what made a legitimate extension
unreachable for the rest of the run.

### Screen status

| Screen | State |
| --- | --- |
| S1 idle | implemented |
| S2 budget disclosed | implemented |
| S3 no budget disclosed | implemented |
| S4 deadline reached | implemented |
| S5 replayed submit | forward-looking — see below |
| S6 idempotency key rejected | forward-looking — see below |

## S1 — idle, before submit

```
+--------------------------------------------------------------+
| Live description                                     [ idle ] |
+--------------------------------------------------------------+
| Image: kitchen-window-2048.jpg                                |
| Context: "kitchen, morning light"                             |
|                                                               |
|                       [ Describe image ]                      |
+--------------------------------------------------------------+
```

No budget is shown before submit: the panel does not know the server's budget
until the run is accepted. Inventing one here is the bug this change removes.

## S2 — accepted, budget disclosed

```
+--------------------------------------------------------------+
| Live description                                  [ running ] |
+--------------------------------------------------------------+
| Run 8f2c-41ab accepted.                                       |
| [############--------------------]  0:38 / 3:00               |
| Server budget 3:00 - polling every 2s                         |
|                                                               |
|                          [ Cancel ]                           |
+--------------------------------------------------------------+
```

The "3:00" is the server's number, not ours. Progress bar fills against it.

## S3 — accepted, server disclosed no budget

```
+--------------------------------------------------------------+
| Live description                                  [ running ] |
+--------------------------------------------------------------+
| Run 8f2c-41ab accepted.                                       |
| [####----------------------------]  0:38 elapsed              |
| No server budget disclosed - local ceiling 11:30               |
|                                                               |
|                          [ Cancel ]                           |
+--------------------------------------------------------------+
```

Degraded, and says so. Elapsed replaces a ratio because the denominator is a
guess; showing a fake denominator would misstate certainty.

## S4 — deadline reached

```
+--------------------------------------------------------------+
| Live description                                 [ timed out ]|
+--------------------------------------------------------------+
| ! The server's 3:00 budget for run 8f2c-41ab elapsed.         |
|   The run may still finish; this panel stopped waiting.       |
|                                                               |
|              [ Keep waiting ]     [ Start over ]              |
+--------------------------------------------------------------+
```

Timeout names whose budget elapsed and does not claim the run failed. "Keep
waiting" resumes polling the SAME run under a fresh local window (one generation
budget, 3:00) — no second submit, no second burst, nothing cancelled. "Start
over" is the existing submit control, relabelled in this state; it discards the
old run and starts a new one.

Both ways out are named in the status sentence as well as on the buttons, so the
`role="status" aria-live="polite"` region announces the recovery rather than only
rendering it. The status keeps its icon + colour pairing; colour is never the
only channel.

## S5 — replayed submit (idempotency key hit) — FORWARD-LOOKING

```
+--------------------------------------------------------------+
| Live description                                  [ running ] |
+--------------------------------------------------------------+
| Reattached to run 8f2c-41ab (already in flight).              |
| [##################--------------]  1:52 / 3:00               |
+--------------------------------------------------------------+
```

A double submit returns 202 with the same run id. The panel reattaches instead
of starting a second generation. The countdown continues against the original
budget, so a replay never resets the clock.

**Not implemented in GUIDEDFIX-2.** The guided live run sends no
`idempotency_key` (`guidedLiveRequestPayload` carries `media_ids` and nothing
else), so no submit can be deduplicated and this screen is unreachable by
construction. It is specified here for the slice that adds idempotency-key
submission to the guided live run; until then the reattach path does not exist
and must not be described in the panel.

## S6 — idempotency key rejected — FORWARD-LOOKING

```
+--------------------------------------------------------------+
| Live description                                     [ error ]|
+--------------------------------------------------------------+
| ! This submit could not be de-duplicated (invalid key).       |
|   Nothing was generated and nothing was charged.              |
|                                                               |
|                       [ Try again ]                           |
+--------------------------------------------------------------+
```

WordPress returns 400 `invalid_idempotency_key` before touching the backend. The
copy states the safe fact: no run started.

**Not implemented in GUIDEDFIX-2**, and blocked on the same missing piece as S5:
the guided panel sends no key, so it can never receive this rejection. Landing
S6 without S5 would mean writing copy for an error the screen cannot produce.
Both belong to the slice that adds idempotency-key submission; a submit failure
today lands in the generic "The live run could not finish. Nothing was applied."
state instead.

## State transitions

Implemented today (`guidedLiveReducer`):

```
idle --submit--> queued/warming/describing --deadline--> timed_out
  |                        |                                 |
  |                        +--terminal payload--> ready/degraded/unavailable
  |                        |                                 |
  |                        +--stop--> cancelled              |
  |                                                          |
  +<---------------- start over (new run) -------------------+
                                                             |
       keep waiting (same run, fresh window) ----------------+
```

Forward-looking, once a key is sent:

```
  +--400 invalid key--> error --try again--> idle
```

## Accessibility notes

- Status is text plus icon, never colour alone.
- The countdown is an `aria-live="polite"` region updated at most once per
  second so a screen reader is not flooded by the 2s poll.
- "timed out" is announced once, not on every tick.
