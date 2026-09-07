# Guided prototype, live description

The guided prototype teaches one loop: see the evidence, decide each face, check the description, apply it yourself. Until now every word of that description was canned, and the screen said so. This map covers the change that lets the same loop end in a real description produced by the bursty GPU backend, without giving up the determinism the teaching flow depends on.

## The rule that shapes the whole screen

The saved draft is never removed. A live run is an addition on top of a screen that is already complete and already correct. That is the queue-and-retry-with-a-fast-answer form of **CARD-09** / **RES-06**: the learner is never blocked on a cold GPU, because the answer they need is already on screen before they ask for a better one.

The live run unlocks only when every face match has been answered — confirmed or marked unidentified. That is **HAI-15** commit-before-reveal: the model's live sentence must not arrive while a face match is still unanswered, because a displayed model verdict pulls the human decision toward it. The button is present but disabled, and the status line next to it names the reason. Re-opening a face drops the panel back to blocked from any state, clears any sentence the last run produced, and — if a run is still in flight — cancels it on the server: the sentence it would return was written against an identity answer that no longer holds.

A second reason can block the panel: no live attachment is configured for the demo. Both reasons use the same disabled button and a status line that says which one applies.

## Screen and state map

The heading, the additive line and the naming line are rendered for the panel's whole life, in every state. The frames below show them once, then only the parts that change.

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
|  --- See it run live --------------------------------------------------   |
|  A live run never changes the draft above, and it never changes what      |
|  Apply would write.                                                       |
|  Names come from your roster on the server, not from this page.           |
|  Confirmed here: Katy Perry, Justin Trudeau.                              |
|  • Ready when you are.                                        IDLE        |
|  [ Describe it live ]                                                     |
+---------------------------------------------------------------------------+
```

### Submitted, not picked up yet

```text
|  … Queued. Waiting for the service to pick it up.             QUEUED      |
|    0:02 of up to 8:30                                                     |
|  [ Describe it live ] (disabled)  [ Stop waiting ]                        |
```

### Bounded wait, GPU cold

```text
|  … Starting the GPU. A cold start can take several minutes.   WARMING     |
|    1:12 of up to 8:30                                                     |
|  [ Describe it live ] (disabled)  [ Stop waiting ]                        |
```

### Bounded wait, GPU warm

```text
|  … Describing the photo now.                                 DESCRIBING   |
|    0:09 of up to 3:00                                                     |
|  [ Describe it live ] (disabled)  [ Stop waiting ]                        |
```

### Live draft arrived

```text
|  ✓ Done. The GPU wrote this.                                  READY       |
|  +---------------------------------------------------------------------+  |
|  | Katy Perry and Justin Trudeau shake hands in front of a blue ...    |  |
|  +---------------------------------------------------------------------+  |
|  [ Describe it live ]                                                     |
```

### Degraded, the description came from CPU

```text
|  ! Done, but the GPU was not available, so the CPU wrote      DEGRADED    |
|    this. It is rougher than a GPU description.                            |
|  +---------------------------------------------------------------------+  |
|  | Two people shake hands in front of a blue backdrop ...              |  |
|  +---------------------------------------------------------------------+  |
|  [ Describe it live ]                                                     |
```

A completed run that reports no tier at all lands on the same state with a
different sentence: `Done, but the run did not say whether the GPU wrote this.`
The item's tier is the only proof of what wrote the sentence, so an unreported
tier is shown as unattributed rather than claimed for the GPU (**HAI-12**: never
overstate the machine).

### The wait hit its limit

```text
|  ! Stopped waiting. The run may still finish on its own;      TIMED OUT   |
|    nothing was applied here.                                              |
|  [ Describe it live ]                                                     |
```

### The service could not be reached

```text
|  × The live run could not finish. Nothing was applied.       UNAVAILABLE  |
|  [ Describe it live ]                                                     |
```

A run that completes with no draft for this photo lands on the same state with its own sentence: `The run finished with nothing to show. Nothing was applied.` An empty box with no reason would read as a success.

### Stopped by the learner

```text
|  × You stopped the wait. Nothing was applied.                 CANCELLED   |
|  [ Describe it live ]                                                     |
```

### The button before the faces are decided

```text
|  • Decide each face match first. Then you can describe this    BLOCKED    |
|    photo live.                                                            |
|  [ Describe it live ] (disabled)                                          |
```

### The button with no live photo configured

```text
|  • No live photo is configured for this demo, so the live      BLOCKED    |
|    run is off.                                                            |
|  [ Describe it live ] (disabled)                                          |
```

## State machine

```text
  blocked <---- a face re-opened, from any state that is not waiting ----+
     |                                                                   |
     | every face answered                                               |
     v                                                                   |
   idle --requested--> queued --polled--> warming --polled--> describing |
     ^                    \                  |                 /         |
     |                     +-----------------+----------------+          |
     |                                  |                                |
     |            polled(complete, tier final_gpu) -> ready -------------+
     |            polled(complete, any other tier) -> degraded ----------+
     |            polled(complete, no text)        -> unavailable -------+
     |            polled(failed) / submit or poll error -> unavailable --+
     |            polled(cancelled)                -> cancelled ---------+
     |            tick past the deadline           -> timed_out ---------+
     |            Stop waiting                     -> cancelled ---------+
     |                                                                   |
     +------- requested, from any terminal state ------------------------+
```

`ready` and `degraded` are mutually exclusive outcomes of the same completion: the item's `tier` alone decides which one, and there is no edge between them. Terminal states ignore `polled` and `cancelled` actions entirely, so a late poll cannot reanimate a finished run. Within the wait the status only moves forward — `queued` → `warming` → `describing` — so an out-of-order poll cannot walk the screen backwards.

Terminal states are `ready`, `degraded`, `timed_out`, `unavailable`, `cancelled`. Every one of them leaves the saved draft and the Apply button exactly as they were, and the only way out of any of them is the learner pressing the button again — or re-opening a face, which sends the panel to `blocked` — which is **INT-10** status-predict-stop and **HAI-12** output is a proposal.

## Bounds

Every wait is bounded twice, in the browser and at the server, and the browser limit is the one the learner is shown. The elapsed time and the ceiling are both visible from the first second, so the learner can decide to stop instead of guessing (**INT-08**: progress over one second, a side-effect-free cancel over two).

| Bound | Value |
|---|---|
| Submit request timeout | 185 s, deliberately above the WP proxy's 180 s description budget |
| Status poll request timeout | 10 s |
| Poll backoff | 500 ms, doubling to a 5 s ceiling |
| Cancel request timeout | 30 s |
| Client wait ceiling, GPU cold or unknown at submit | 510 s |
| Client wait ceiling, GPU reported ready at submit | 180 s |
| Retries after a terminal failure | operator-pressed only, never automatic |

The warm pin is a guess made from the submit response. A later poll reporting a colder GPU raises the deadline back toward 510 s; the deadline never shrinks under a learner who is already waiting.

There is no automatic retry. A GPU burst costs money, and an automatic retry on a timeout is the classic way to pay for the same work twice while the first run is still going.

## Accessibility

The status line, the elapsed line and the live sentence sit inside one `role="status" aria-live="polite"` region named "Live run status", mounted for the panel's whole life. A live region has to exist before its contents change, so a result blockquote that appears carrying its own `aria-live` would be announced by nothing (**A11Y-21**).

Focus is never moved. The learner may be reading the saved draft while the run finishes, and the live region announces the result without stealing the caret (**A11Y-20**).

Every state pairs a glyph with its sentence, and no state is carried by colour alone (**A11Y-06**, repo rule sr-004). The glyph is `aria-hidden`; the sentence carries the meaning, so nothing is announced twice.

The elapsed indicator is plain text — `1:12 of up to 8:30` — not a progress bar. There is no `role="progressbar"` and no `aria-value*` pair, because the honest quantity here is elapsed time against a ceiling, not a percentage of work done.

The disabled button points `aria-describedby` at the status line, so the reason it is disabled is reachable from the control itself rather than only from the sentence beside it.

## What a live run sends, and what it cannot send

A live run sends one thing: the sample photo's attachment id, on the admin bulk describe run route. The whole payload is `{ media_ids: [mediaId] }`. It cannot send the names the learner confirmed on this screen, because no describe request accepts caller-supplied person names. Naming happens on the server, from the roster projection, gated by the person-naming policy option.

That is not a limitation to hide behind vague wording. The panel says it, in every state:

```text
|  --- See it run live --------------------------------------------------   |
|  A live run never changes the draft above, and it never changes what      |
|  Apply would write.                                                       |
|  Names come from your roster on the server, not from this page.           |
|  Confirmed here: Katy Perry, Justin Trudeau.                              |
```

With nothing confirmed on the screen yet, the second line ends `You have not confirmed anyone here yet.` instead. Either way the confirmations are a disclosure of what the learner did here, not a payload: if this photo's people are not confirmed in the server roster, the live description describes them without naming them.

The face decisions therefore gate the live run for a different reason than supplying names: they keep the model's sentence from arriving while a human judgment is still open. The gate is about order, not about payload.

A live run never writes alt text. It produces a draft the learner can read and discard. Applying anything to the practice copy stays a separate, explicit press, exactly as it is today.

## What the panel does not offer

There is no replacement control. The live sentence appears in a quote beside the saved draft, and no state in the panel offers to put it into the draft. Replacing the draft from a live run would put a model sentence into the one artifact the lesson asks the learner to judge, so the panel keeps the proposal beside the draft rather than in it (**HAI-12**: output is a proposal).

There is no separate retry control either. The same **Describe it live** button starts the next run from any terminal state.

## Operator setup

The live run is off unless an operator names one attachment for it. It is a single WordPress
option holding a positive attachment id; anything else — unset, zero, a float, a string that is
not a number, or an id whose post type is not `attachment` — reads as "no live photo", and the
panel says so instead of submitting a run that can only fail. A deleted attachment or an id
copied from another environment fails the same way: well-formed, but not a subject.

```sh
wp option update acx_guided_live_media_id 4211
```

Use the attachment id of the bundled guided sample photo in the Media Library of the demo site.
Turn the live run off again without touching the page:

```sh
wp option delete acx_guided_live_media_id
```

Names come from the server-side roster, not from the practice answers, so an operator who wants
the live sentence to name the two people has to confirm those faces in the roster for the demo
tenant as well. Without that, the live description is accurate but unnamed — which is a
defensible demo state, and the panel already says which of the two is happening.

The GPU itself is a separate switch. A live run on a stopped burst instance pays the cold-start
minutes the WARMING frame describes; a run with the GPU unavailable comes back as `provisional_cpu`
and lands on the DEGRADED frame. Neither state needs an operator to intervene mid-demo.

## Request and poll shape

| Step | Call | Reads |
|---|---|---|
| Submit | `POST acx/v1/recognition/describe/runs` with one media id | `run_id`, `status`, `phase`, `gpu_state` |
| Poll | `GET acx/v1/recognition/describe/runs/{run_id}` | `status`, `phase`, `gpu_state` |
| Result | `GET acx/v1/recognition/describe/runs/{run_id}/items` | `alt_text_draft`, `tier` |
| Stop | `POST acx/v1/recognition/describe/runs/{run_id}/cancel` | — |

`tier` is the only signal that decides the outcome: `final_gpu` is READY, `provisional_cpu` is the CPU fallback the DEGRADED screen names, and a missing tier is DEGRADED-unattributed. `gpu_state` is advisory and explicitly untrusted by the existing admin client, so the screen treats it as a label for the wait and as the input to the wait ceiling, never as proof about the result. The items read is keyed to this photo's media id: a run that returned nothing for it lands on UNAVAILABLE rather than showing a confident sentence about a different photograph.

The run's own terminal `status` outranks `phase`. A run can settle as failed or cancelled while `phase` still reads as a running sub-phase; without that precedence the screen would poll a finished run all the way to its client deadline and report a timeout that never happened.

Unlike the public demo, this route has a real cancel. Pressing Stop ends the browser's wait immediately and, when the run id is already known, sends the cancel at the same time. Press Stop while the submit is still in flight and there is no run id to cancel yet: the screen goes to CANCELLED at once, and the cancel is sent as soon as the submit resolves and names the run — a burst the submit started must not keep costing money because the learner looked away. If the submit fails outright there is no run to cancel, and the panel lands on UNAVAILABLE instead.
