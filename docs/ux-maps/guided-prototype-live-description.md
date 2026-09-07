# Guided prototype, live description

The guided prototype teaches one loop: see the evidence, decide each face, check the description, apply it yourself. Until now every word of that description was canned, and the screen said so. This map covers the change that lets the same loop end in a real description produced by the bursty GPU backend, without giving up the determinism the teaching flow depends on.

## The rule that shapes the whole screen

The saved draft is never removed. A live run is an addition on top of a screen that is already complete and already correct. That is the queue-and-retry-with-a-fast-answer form of **CARD-09** / **RES-06**: the learner is never blocked on a cold GPU, because the answer they need is already on screen before they ask for a better one.

The live run is offered only after every face has been decided. That is **HAI-15** commit-before-reveal: the model's live sentence must not arrive while a face match is still unanswered, because a displayed model verdict pulls the human decision toward it. The button is present but disabled, and it names the reason.

## Screen and state map

### Draft step, decisions complete, no live run yet

```text
+-- Draft for you to check ------------------------------------------------+
| This draft comes from a saved run.                                        |
| +----------------------------------------------------------------------+ |
| | Katy Perry and Justin Trudeau stand at a podium, ...                 | |
| +----------------------------------------------------------------------+ |
|                                                                           |
|  [ Save my edit ]  [ Reject this draft ]                                  |
|                                                                           |
|  --- Try it live ------------------------------------------------------   |
|  ● Ready. The saved draft stays here either way.              IDLE        |
|    A live run sends this photo and the names you confirmed to the         |
|    description service. First run of the day can take several minutes.    |
|  [ Describe this photo live ]                                             |
+---------------------------------------------------------------------------+
```

### Bounded wait, GPU cold

```text
|  --- Try it live ------------------------------------------------------   |
|  ◌ Starting the GPU. This is the slow part.                   WARMING     |
|    [############--------------------]  1:12 elapsed / 8:30 limit          |
|    Next: describing the photo. The saved draft above is untouched.        |
|  [ Stop waiting ]                                                         |
```

### Bounded wait, GPU warm

```text
|  ◌ Describing the photo.                                     DESCRIBING   |
|    [########################------]  0:09 elapsed / 3:00 limit            |
|  [ Stop waiting ]                                                         |
```

### Live draft arrived

```text
|  ✓ Live description ready. Compare it with the saved draft.   READY       |
|  +---------------------------------------------------------------------+  |
|  | Katy Perry and Justin Trudeau shake hands in front of a blue ...    |  |
|  +---------------------------------------------------------------------+  |
|    Written just now by the description service, using the names you       |
|    confirmed. Check it before you use it: it can be wrong.                |
|  [ Use this instead ]  [ Keep the saved draft ]                           |
```

### Degraded, the description came from CPU

```text
|  ! Ready, but the GPU was unavailable, so this ran on CPU.   DEGRADED     |
|    A CPU run sees the same photo but is slower and usually less           |
|    detailed. Judge the text, not the machine.                             |
|  [ Use this instead ]  [ Keep the saved draft ]  [ Try again ]            |
```

### The wait hit its limit

```text
|  ! Still not finished after 8:30, so the wait stopped.       TIMED OUT    |
|    Nothing was lost. The saved draft above is unchanged and Apply         |
|    still works. The run may finish on the server without you.             |
|  [ Try again ]                                                            |
```

### The service could not be reached

```text
|  × The description service did not answer.                  UNAVAILABLE   |
|    Nothing was sent to the page. The saved draft is unchanged.            |
|    If this keeps happening, check Settings, then the backend URL.         |
|  [ Try again ]                                                            |
```

### Stopped by the learner

```text
|  ● You stopped waiting. Nothing changed.                     CANCELLED    |
|  [ Describe this photo live ]                                             |
```

### The button before the faces are decided

```text
|  ● Decide each face first, then a live run can use the names.  BLOCKED    |
|  [ Describe this photo live ]  (disabled)                                 |
```

## State machine

```text
                       +-----------+
        blocked  <---- |   idle    | ----> queued ----> warming ----> describing
                       +-----------+          |            |              |
                             ^                v            v              v
                             |            unavailable   timed_out       ready
                             |                |            |            |   \
                             +--- try again --+------------+            |    +-> degraded
                             |                                          |
                             +----------------- cancelled <-------------+
```

Terminal states are `ready`, `degraded`, `timed_out`, `unavailable`, `cancelled`. Every one of them leaves the saved draft and the Apply button exactly as they were. `ready` and `degraded` are the only states that offer to replace the draft, and replacement is an explicit press, never automatic, which is **INT-10** status-predict-stop and **HAI-12** output is a proposal.

## Bounds

Every wait is bounded twice, in the browser and at the server, and the browser limit is the one the learner is shown. The elapsed and limit numbers are both visible from the first second, so the learner can decide to stop instead of guessing (**INT-08**: progress over one second, a side-effect-free cancel over two). Stopping abandons the browser's wait only. The screen says so rather than claiming the server was cancelled, because a false claim of cancellation is worse than an honest one about scope.

| Bound | Value |
|---|---|
| Submit request timeout | 30 s |
| Poll interval | 500 ms, doubling to a 5 s ceiling |
| Client wait ceiling, cold | the server deadline, capped at 510 s |
| Client wait ceiling, warm | the server deadline, capped at 180 s |
| Retries after a terminal failure | operator-pressed only, never automatic |

There is no automatic retry. A GPU burst costs money, and an automatic retry on a timeout is the classic way to pay for the same work twice while the first run is still going.

## Accessibility

The live panel is one `role="status"` live region, so a screen reader hears each transition the sighted learner sees (**A11Y-21**). Every state pairs its icon with its text, and no state is carried by color alone (**A11Y-06**, repo rule sr-004). Focus moves to the live result only when the result arrives, never during the wait, because moving focus mid-wait would interrupt a learner reading the saved draft (**A11Y-20**). Loading, degraded, timed-out, unavailable and cancelled each get their own focus and announcement treatment: an accessible happy path with an inaccessible error state fails as a whole (**A11Y-24**, **RLSE-04**).

The progress meter is `role="progressbar"` with `aria-valuemin`, `aria-valuemax` and `aria-valuenow` in seconds, and a text equivalent next to it. Where the remaining time is genuinely unknown the meter becomes indeterminate rather than inventing a percentage.

## What a live run sends, and what it cannot send

A live run sends one thing: the sample photo's attachment id, on the admin bulk describe run route. It cannot send the names the learner confirmed on this screen, because no describe request accepts caller-supplied person names. Naming happens on the server, from the roster projection, gated by the person-naming policy option.

That is not a limitation to hide behind vague wording. The screen says it:

```text
|  --- Try it live ------------------------------------------------------   |
|  ● The live service describes what it can see in the photo.    IDLE       |
|    Names come from your roster, not from the practice answers above.      |
|    If this photo's people are not confirmed in your roster, the live      |
|    description will describe them without naming them.                    |
|  [ Describe this photo live ]                                             |
```

The face decisions above therefore gate the live run for a different reason than supplying names: they keep the model's sentence from arriving while a human judgment is still open. The gate is about order, not about payload.

A live run never writes alt text. It produces a draft on a run the learner can read and discard. Applying anything to the practice copy stays a separate, explicit press, exactly as it is today.

## Request and poll shape

| Step | Call | Reads |
|---|---|---|
| Submit | `POST acx/v1/recognition/describe/runs` with one media id | `run_id`, `status`, `phase`, `gpu_state`, `eta_seconds` |
| Poll | `GET acx/v1/recognition/describe/runs/{run_id}` | `phase`, `gpu_state`, `eta_seconds` |
| Result | `GET acx/v1/recognition/describe/runs/{run_id}/items` | `alt_text_draft`, `tier`, `provenance` |
| Stop | `POST acx/v1/recognition/describe/runs/{run_id}/cancel` | `cancel_requested` |

`tier` is the degraded signal that matters: `final_gpu` is a warm result, `provisional_cpu` is the CPU fallback the DEGRADED screen names. `gpu_state` is advisory and explicitly untrusted by the existing admin client, so the screen treats it as a label for the wait, never as proof about the result.

Unlike the public demo, this route has a real cancel. Pressing Stop sends the cancel and then stops polling, so the screen can honestly say the run was asked to stop rather than only that the browser looked away.
