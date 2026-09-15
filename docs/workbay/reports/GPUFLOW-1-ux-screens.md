FINDINGS: [{"id":"GPUFLOW-1-UXS-R-01","severity":"medium","file_path":"apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md","line":20,"summary":"The current service-card screen still says Settings › Burst GPU instead of the frozen plain-language title.","evidence":"The map inventory names settings-burst-gpu as Settings › Burst GPU at line 20, while the frozen plan requires Settings › Description Service at lines 298-301 and says primary copy must avoid GPU jargon at line 69."},{"id":"GPUFLOW-1-UXS-R-02","severity":"medium","file_path":"apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md","line":29,"summary":"The service-card action state list has no explicit unavailable/operator-STOP state or recovery copy.","evidence":"The current action states are stopped, unknown, starting, warming, ready, degraded; the frozen A3 contract requires a plain-language service state and distinguishes unavailable responses with no ETA at plan lines 300-301 and 316."},{"id":"GPUFLOW-1-UXS-R-03","severity":"medium","file_path":"apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.md","line":20,"summary":"Retention Retry fetching is absent from the current UX-map screen and zone inventory.","evidence":"The current describe map lists only Workbench media selection, Description History review, Dashboard describe, and the tier-transition toast at lines 20-23; the frozen plan explicitly requires Retention Retry fetching at lines 300-303."},{"id":"GPUFLOW-1-UXS-R-04","severity":"medium","file_path":"apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.md","line":33,"summary":"The current describe map has progress and provenance but no wire-backed timing line or run timing summary.","evidence":"The bulk zones at lines 33-36 and single provenance at lines 92-93 do not name queue, ramp-up, processing, startup, or absent-timing behavior; B2 requires the display and evidence mapping at plan lines 328-341."},{"id":"GPUFLOW-1-UXS-R-05","severity":"medium","file_path":"apps/prototype-wp-alt-context/docs/ux-maps/workbench-identity-chips.md","line":20,"summary":"The current identity map has chip screens but no NameFaceControl closed-listbox or preview/agreement state.","evidence":"The screen inventory at lines 20-24 contains media chips, face-group review, and person workspace only; C1 requires listOpen=false and the fallback preview chain at plan lines 343-354."},{"id":"GPUFLOW-1-UXS-R-06","severity":"medium","file_path":"apps/prototype-wp-alt-context/docs/ux-maps/workbench-identity-chips.md","line":20,"summary":"The current identity map has no SuggestionCards candidate-versus-representative or null-placeholder screen.","evidence":"The current screen inventory at lines 20-24 and representative avatar zone at line 36 do not specify candidate exclusion, a null placeholder, or the croppable-image gate; C2 requires all three at plan lines 356-364."},{"id":"GPUFLOW-1-UXS-R-07","severity":"medium","file_path":"apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.md","line":168,"summary":"The current degraded flow says warming exceeds >180 s, conflicting with the frozen A3 120 s client ceiling.","evidence":"The current map flow says gpu-warming exceeds bound (>180 s) at line 168, while the frozen plan says Suggest retries only until the 120 s public ceiling and then offers still starting — try again at lines 300-301."}]
SCREENS: 21

# GPUFLOW-1 UX screen inventory

This is the handoff artifact for the SPA and UX lanes. It inventories the target
states from the frozen GPUFLOW-1 plan and sketches the operator-visible copy;
the four current UX maps remain read-only. Boxes use the existing 62-column
frame convention: 60 characters between the outer bars.

## Scope and state model

The target surface is split into finite control states and data rendered inside
those states. `warmup_eta_seconds`, `Retry-After`, attempt countdowns, media
counts, and timing values are data, not new enum members [GRPH-26]. A missing
wire value stays absent; the client may format a value but must not invent it.

| Slice / screen and zone | Current label | Target label and status wording | Target states | Trigger -> exit | Owning lane |
| --- | --- | --- | --- | --- | --- |
| A3 `#/settings`, service card `z-gpu-state-chip` + `z-gpu-intent` | `Settings › Burst GPU`; GPU state chip; effective intent | `Settings › Description Service`; `Service stopped`; `Automatic` | stopped/auto (default), starting (loading), ready (default), unavailable (error/degraded), unknown (empty/error) | Initial status or refresh -> Start/Auto/Refresh; ready -> Workbench | `spa-description-service`; `ux-service` |
| A3 `#/settings`, `z-gpu-cost` + `z-gpu-controls` | `Cost: ... GPU-hour`; Start GPU / Stop GPU / Return to automatic | `Cost and service controls`; disclose cost and warm-up before Start; use Description Service in primary copy | default, loading, error, degraded | User opens Start preview or control -> confirm, cancel, or Return to automatic | `spa-description-service`; `ux-service` |
| A3 `#/workbench`, Suggest status `z-suggest-status` | Generic Suggest pending/error; no explicit `description_service_starting` state in the map | `Description Service is starting - about N s` and `Retrying automatically in N s` | warming/loading | 503 with `code=description_service_starting` -> Retry-After retry, ready draft, cancel, or 120 s ceiling | `spa-suggest-warming-timing`; `ux-suggest` |
| A3 `#/workbench`, Suggest retry `z-suggest-retry` | No retry countdown zone | `Retrying automatically in N s`; the delay comes from `Retry-After` | warming/loading, ceiling | Retryable 503 -> timer reaches zero -> next request; cancel -> idle | `spa-suggest-warming-timing`; `ux-suggest` |
| A3 `#/workbench`, Suggest ceiling `z-suggest-ceiling` | No ceiling action | `Description Service is still starting - try again`; `Automatic retries stopped after 120 s` | ceiling/error | 120 s client budget -> Try again or return to selected media; preserve input | `spa-suggest-warming-timing`; `ux-suggest` |
| A3 `#/workbench`, Suggest error `z-suggest-error` | Generic `Could not reach the description service` copy | `Description service error (502)`; `The service could not describe this image.` | error | Typed 502 after service readiness or realizer failure -> Try again, preserving media | `spa-suggest-warming-timing`; `ux-suggest` |
| A3 `#/retention`, Retry status `z-retention-retry` | Retry exists without an explicit fetching surface; no screen in current maps | `Fetching retention status...`; retain `Last error` until replacement data arrives | default, loading, error | Retry click -> fetching -> loaded or inline error; saved rows remain visible | `spa-description-service`; `ux-service` |
| B2 `#/workbench`, bulk CTA/progress `z-bulk-cta` + `z-bulk-progress` | Describe selected CTA; progress phases include starting/warming/describing | `Describe N selected`; `Queued`; `Waiting for Description Service`; `Processing` | default, queued/loading, ramp-up/loading, processing/loading, error, degraded | Submit -> queue/ramp-up/processing; Cancel -> cancelled; failure -> Retry | `spa-bulk-timing`; `ux-suggest` |
| B2 `#/workbench`, bulk timing `z-run-timing` | No timing zone | `Queue 0.8 s`; `Waited for service 1 m 42 s` once; `Median per image 6.1 s`; `Slowest 8.4 s` | queued, ramp-up, processing, terminal, untimed | Run/item `timing` arrives -> format wire values -> Review results; no timing object -> render no timing row | `spa-bulk-timing`; `ux-suggest` |
| B2 `#/`, single describe `z-provenance` + `z-single-timing` | Provenance includes a broad `Latency` label | `Waited for service 1 m 42 s - described in 6.1 s`; optional `Started in 1 m 50 s` only when `startup_ms` is known | default/result, loading, untimed | Describe returns -> result timing line; absent timing -> omit line, never show zero | `spa-suggest-warming-timing`; `ux-suggest` |
| A3/B2 public demo `z-status` | OBSERVED polite queued/warming/describing/error status | Preserve public status boundary; typed `502 description_service_error` is an error, and `gpu_state` never supplies a result tier | default, loading/warming, error, degraded | 503/502 or timeout -> same-page retry with retained in-memory key; no GPU-tier inference | `ux-public`; input from `spa-suggest-warming-timing` |
| C1 `#/workbench?media=`, naming input/listbox | `NameFaceControl`; listbox opens on mount in current source | `Name this group`; listbox closed on mount; visible label and keyboard path | closed/default, open/loading, error | Typing or ArrowDown -> open; choose/cancel/escape -> closed | `spa-naming-control`; UX handoff `ux-identity` |
| C1 `#/workbench?media=`, group preview/agreement | Group preview can be empty | `Preview: apply “Alex” to 4 faces`; fallback representative face -> first member -> placeholder | default, agreement, placeholder, error | Candidate label selected -> preview -> Apply name or Cancel; underlying change is explicit | `spa-naming-control`; UX handoff `ux-identity` |
| C2 `#/workbench?media=`, suggestion card `z-candidate` + `z-representative` | Suggestion card can show a representative equal to the candidate | `Candidate: Alex`; `Representative: Jamie`; two distinct identity labels and evidence | default, loading, error, degraded | Suggestion details load -> Review, Accept, Reject, or Dismiss; candidate identity is excluded | `spa-suggestion-cards` + `svc-suggestion-rep`; UX handoff `ux-identity` |
| C2 `#/workbench?media=`, suggestion fallback `z-representative-placeholder` | Missing representative may render blank or an unsafe thumbnail | `Representative preview unavailable`; no FaceThumbnail for a non-croppable bbox; candidate remains named | placeholder/empty, degraded, error | Null representative or invalid bbox -> explicit placeholder -> Review or Dismiss | `spa-suggestion-cards`; UX handoff `ux-identity` |

## Interaction and copy contract

- Service lifecycle exposes activation, an in-run operating status, and a stop
  or return path [HAI-04]. Automatic intent is visible; `operator STOP` is a
  reason, not a synonym for unknown telemetry.
- Every wait longer than about one second has a progress sentence and, when
  interruptible, a visible Cancel action [INT-08]. The Suggest retry timer is
  driven by the response header and the 120 s ceiling; it is not a silent poll.
- Put new status beside the action/result that caused it [PERC-05]. Suppress
  per-poll or per-item toasts; reserve an interrupt for a rare, consequential
  transition [PERC-07].
- State text includes an icon or shape and text, not color alone [VIZ-07]. A
  stale or unknown state has its own `?`/unknown mark and does not become ready
  by default [PERC-02].
- A typed 502 is inline, names the operation and the fix, and remains visible
  while the user edits or retries [FORM-05]. A warm-up 503 is not presented as
  a realizer error.
- AI/service activity is disclosed and can be disabled through the explicit
  lifecycle controls [HAI-05]. Drafts remain proposals with an edit/review
  path [HAI-13]; a suggestion representative is evidence, not proof.
- Naming preview states the deferred effect before Apply [HAI-18]. The control
  needs a visible label and keyboard/touch route [FORM-01] [INT-04].

## ASCII screens

Each screen below is one target state or state transition. Dynamic numbers are
illustrative wire values only; they are not latency promises. `role=status`
means routine progress, while the typed 502 uses an inline actionable error.

### Screen 01 - Settings › Description Service - stopped / automatic

Trigger: fresh stopped snapshot with Auto intent. Exit: Start opens the cost
preview; Refresh reads a new snapshot.

Canon: [HAI-04] [HAI-05] [PERC-02] [VIZ-07]

```
+------------------------------------------------------------+
| Settings › Description Service  [screen]  #/settings       |
| [■] Service stopped                         snapshot 12 s  |
| Intent: Automatic - starts when a describe run needs it    |
| Lease: none        Load: no work in flight                 |
| Cost: about $2/GPU-hour - warm-up about 2 min              |
| [Start service] [Return to automatic] [Refresh status]     |
| status: stopped / auto  (text + shape; not color alone)    |
+------------------------------------------------------------+
```

### Screen 02 - Settings › Description Service - starting with ETA

Trigger: Start or Auto demand is accepted and the service reports an ETA. Exit:
poll to ready, Stop, Return to automatic, or Refresh.

Canon: [HAI-04] [INT-08] [PERC-05] [VIZ-07]

```
+------------------------------------------------------------+
| Settings › Description Service  [screen]  #/settings       |
| [~] Description Service is starting - about 48 s           |
| Intent: Start requested until 22:40                        |
| Status: starting; last snapshot 4 s ago                    |
| Progress: waiting for the service to become ready          |
| [Stop service] [Return to automatic] [Refresh status]      |
+------------------------------------------------------------+
```

### Screen 03 - Settings › Description Service - starting, no ETA

Trigger: a starting snapshot has no `warmup_eta_seconds`. Exit: ready, Stop,
Return to automatic, or Refresh; do not substitute a guessed duration.

Canon: [INT-08] [PERC-02] [VIZ-07] [GRPH-26]

```
+------------------------------------------------------------+
| Settings › Description Service  [screen]  #/settings       |
| [~] Description Service is starting                        |
| Intent: Automatic                                          |
| Status: starting; estimate unavailable                     |
| Progress: waiting for the service to become ready          |
| [Stop service] [Return to automatic] [Refresh status]      |
+------------------------------------------------------------+
```

### Screen 04 - Settings › Description Service - ready

Trigger: fresh ready snapshot. Exit: Stop preview, Return to automatic, or Go
to Workbench; the ready label never claims a description is final by itself.

Canon: [HAI-04] [HAI-05] [PERC-02] [VIZ-07]

```
+------------------------------------------------------------+
| Settings › Description Service  [screen]  #/settings       |
| [OK] Description Service ready                snapshot 6 s |
| Intent: Automatic       Load: no work in flight            |
| Cost: about $2/GPU-hour - idle reap applies                |
| The service is ready for AI descriptions.                  |
| [Stop service] [Return to automatic] [Go to Workbench]     |
+------------------------------------------------------------+
```

### Screen 05 - Settings › Description Service - unavailable, operator STOP

Trigger: the lifecycle reports unavailable with an operator STOP reason. Exit:
Start is an explicit override, Return to automatic clears the intent, Refresh
checks again; this is not the same as unknown telemetry.

Canon: [HAI-04] [HAI-05] [PERC-02] [VIZ-07]

```
+------------------------------------------------------------+
| Settings › Description Service  [screen]  #/settings       |
| [!] Description Service unavailable                        |
| Reason: operator STOP - automatic starts are paused        |
| Estimate: unavailable; no warm-up promise                  |
| [Start service] [Return to automatic] [Refresh status]     |
| status: unavailable / operator STOP (icon + text)          |
+------------------------------------------------------------+
```

### Screen 06 - Settings › Description Service - unknown

Trigger: status snapshot is missing, stale, or malformed. Exit: Refresh can
recover a known state; Return to automatic is safe; Start stays held until the
fresh state permits it.

Canon: [HAI-04] [PERC-02] [PERC-05] [VIZ-07]

```
+------------------------------------------------------------+
| Settings › Description Service  [screen]  #/settings       |
| [?] Description Service status unknown                     |
| Last status: unavailable or stale; age not trusted         |
| We cannot confirm whether the service is running.          |
| [Return to automatic] [Refresh status]                     |
| Start service: unavailable until status is known           |
+------------------------------------------------------------+
```

### Screen 07 - Suggest - warming with ETA and auto-retry

Trigger: Suggest receives `503 description_service_starting` with an ETA and
`Retry-After`. Exit: a retry succeeds, the user cancels, or the 120 s ceiling.

Canon: [INT-08] [HAI-04] [PERC-05] [GRPH-26]

```
+------------------------------------------------------------+
| Suggest one image                         role=status      |
| [~] Description Service is starting - about 42 s           |
| Retrying automatically in 5 s (Retry-After)                |
| Your image is still selected; no duplicate request made.   |
| [Cancel request]                                           |
| status: warming; countdown is data, not a new state        |
+------------------------------------------------------------+
```

### Screen 08 - Suggest - warming with no ETA

Trigger: the same typed warming response omits `warmup_eta_seconds`. Exit: the
header-controlled retry, Cancel, or the ceiling; omit an estimate entirely.

Canon: [INT-08] [PERC-02] [PERC-05] [GRPH-26]

```
+------------------------------------------------------------+
| Suggest one image                         role=status      |
| [~] Description Service is starting                        |
| Retrying automatically in 5 s (Retry-After)                |
| No start estimate is available yet.                        |
| [Cancel request]                                           |
| status: warming; ETA omitted because the wire value is null|
+------------------------------------------------------------+
```

### Screen 09 - Suggest - warming ceiling reached

Trigger: bounded auto-retry reaches the 120 s public ceiling. Exit: Try again
starts a deliberate new attempt; Back returns to the selected image unchanged.

Canon: [INT-08] [INT-11] [PERC-05] [FORM-05]

```
+------------------------------------------------------------+
| Suggest one image                         role=status      |
| [!] Description Service is still starting — try again      |
| Automatic retries stopped after 120 s.                     |
| Your selected image is still here.                         |
| [Try again]                        [Back to selected media]|
| status: ceiling; no silent retry and no lost input         |
+------------------------------------------------------------+
```

### Screen 10 - Suggest - typed 502 error

Trigger: a ready service returns `502 description_service_error`. Exit: inline
Try again keeps the image and the typed error until a new result replaces it.

Canon: [FORM-05] [PERC-05] [HAI-13] [VIZ-07]

```
+------------------------------------------------------------+
| Suggest one image                         role=alert       |
| [X] Description service error (502)                        |
| The service could not describe this image.                 |
| Code: description_service_error                            |
| [Try again]                         [Edit selected image]  |
| status: error; this is not a warming estimate              |
+------------------------------------------------------------+
```

### Screen 11 - Retention Retry - fetching

Trigger: the operator activates Retry after a retention read failure. Exit:
loaded data replaces the status; an error preserves the prior error and saved
rows, so a request in flight is not mistaken for a blank page.

Canon: [INT-08] [PERC-05] [FORM-05] [VIZ-07]

```
+------------------------------------------------------------+
| Retention                                #/retention       |
| [~] Fetching retention status...          role=status      |
| Last error: Could not load retention records               |
| Saved rows remain visible while this request runs.         |
| [Retry disabled while fetching]                            |
| status: fetching; completion or error will replace this    |
+------------------------------------------------------------+
```

### Screen 12 - Bulk describe - queued

Trigger: `Describe N selected` is submitted and the run is accepted. Exit:
worker pickup moves to ramp-up; Cancel is available while queued.

Canon: [INT-08] [HAI-04] [PERC-05] [VIZ-07]

```
+------------------------------------------------------------+
| Workbench - bulk describe                 role=status      |
| [~] Queued for description                                 |
| 0 of 3 images processed                                    |
| Queue: 0.8 s     GPU tier: not reported                    |
| The run is waiting for a worker.                           |
| [Cancel run]                                               |
+------------------------------------------------------------+
```

### Screen 13 - Bulk describe - ramp-up / waiting for service

Trigger: the worker is waiting for the Description Service to become ready.
Exit: readiness moves to processing; Cancel stops the run without hiding the
measured ramp-up value.

Canon: [INT-08] [HAI-04] [PERC-05] [GRPH-26]

```
+------------------------------------------------------------+
| Workbench - bulk describe                 role=status      |
| [~] Waiting for Description Service - about 1 m 20 s       |
| Queue: 0.8 s     Waited for service: in progress           |
| 0 of 3 images processed                                    |
| [Cancel run]                                               |
| status: ramp-up; one run-level value, not per-image work   |
+------------------------------------------------------------+
```

### Screen 14 - Bulk describe - processing with run summary

Trigger: service readiness is observed and item dispatch begins. Exit: terminal
Review results, Cancel, or a typed run error. Median/max use only timed items.

Canon: [INT-08] [HAI-05] [PERC-05] [VIZ-07]

```
+------------------------------------------------------------+
| Workbench - bulk describe                 role=status      |
| [>] Processing 2 of 3 images                               |
| Queue: 0.8 s     Waited for service: 1 m 42 s              |
| Median per image: 6.1 s     Slowest: 8.4 s                 |
| 2 of 3 processed                         [Cancel run]      |
| [Review results] when terminal; timing is wire-backed      |
+------------------------------------------------------------+
```

### Screen 15 - Single describe - timing present

Trigger: a successful single response carries `ramp_up_ms`, `processing_ms`,
and a known `startup_ms`. Exit: edit/review the draft or Describe again.

Canon: [HAI-05] [HAI-13] [PERC-05] [VIZ-07]

```
+------------------------------------------------------------+
| Dashboard - Describe with AI              role=region      |
| Draft ready: A person walking beside a lake.               |
| Timing: Waited for service 1 m 42 s - described in 6.1 s   |
| Started in 1 m 50 s  (shown only when startup_ms is known) |
| Adapter: gpu_qwen30b     Tier: final GPU                   |
| [Edit draft] [Describe again]                              |
+------------------------------------------------------------+
```

### Screen 16 - Single describe - timing absent

Trigger: a legacy or untimed response omits `timing`. Exit: edit the draft or
Describe again; there is deliberately no placeholder latency or invented zero.

Canon: [HAI-05] [HAI-13] [GRPH-26] [VIZ-07]

```
+------------------------------------------------------------+
| Dashboard - Describe with AI              role=region      |
| Draft ready: A person walking beside a lake.               |
| Adapter: gpu_qwen30b     Tier: processing tier unavailable |
|                                                            |
| No timing supplied; timing line is not rendered.           |
| [Edit draft] [Describe again]                              |
+------------------------------------------------------------+
```

### Screen 17 - Naming control - closed with representative preview

Trigger: the group editor mounts. Exit: typing or ArrowDown opens the listbox;
the initial closed state does not reveal options or steal focus.

Canon: [FORM-01] [INT-04] [PERC-02] [VIZ-07]

```
+------------------------------------------------------------+
| Name this group                           listbox: closed  |
| Preview: [face] Trudeau - representative face              |
| Group: 4 faces                                             |
| Name [ Enter a name... ]                                   |
| Choose a name to preview the change.                       |
| [Open options with ArrowDown]                 [Cancel]     |
+------------------------------------------------------------+
```

### Screen 18 - Naming control - preview and agreement

Trigger: the operator types or selects a name. Exit: Apply name commits the
explicit choice; Cancel or Escape returns to the closed input without mutation.

Canon: [FORM-01] [FORM-05] [HAI-18] [INT-09] [INT-04]

```
+------------------------------------------------------------+
| Name this group                           listbox: open    |
| [face] Preview: apply “Alex” to 4 faces                    |
| > Alex - existing person                                   |
|   Alexandra - existing person                              |
| Agreement: this changes the group label, not the evidence. |
| [Apply name] [Cancel]                    [Escape closes]   |
+------------------------------------------------------------+
```

### Screen 19 - Suggestion card - distinct representative

Trigger: tenant-scoped suggestion details load with a noncandidate member and a
croppable representative bbox. Exit: review, accept, reject, or dismiss.

Canon: [HAI-05] [HAI-13] [PERC-02] [VIZ-07] [INT-04]

```
+------------------------------------------------------------+
| Suggested match                             role=group     |
| Candidate: [face] Alex                                     |
| Representative: [face] Jamie                               |
| Evidence: two different people; representative is a crop   |
| Suggestion: Alex                                           |
| [Review] [Accept suggestion] [Reject] [Dismiss]            |
+------------------------------------------------------------+
```

### Screen 20 - Suggestion card - explicit representative placeholder

Trigger: no tenant-scoped noncandidate exists, or the representative bbox is
not croppable. Exit: review faces or dismiss; never render the candidate as its
own representative.

Canon: [HAI-05] [HAI-13] [PERC-02] [VIZ-07] [FORM-05]

```
+------------------------------------------------------------+
| Suggested match                             role=group     |
| Candidate: [face] Alex                                     |
| Representative preview unavailable                         |
| No different person has usable representative evidence.    |
| No FaceThumbnail rendered for the invalid crop.            |
| [Review faces] [Dismiss]                                   |
+------------------------------------------------------------+
```

### Screen 21 - Public demo - typed service error boundary

Trigger: public demo receives a typed 502 or failed response. Exit: same-page
retry keeps the in-memory key; a full refresh remains the documented exit and
must not be presented as durable resume.

Canon: [FORM-05] [PERC-05] [PERC-07] [VIZ-07] [HAI-05]

```
+------------------------------------------------------------+
| Public demo - Describe an image            data-state=error|
| [X] Description service error (502)                        |
| The image could not be described. Try again.               |
| Code: description_service_error                            |
| [Describe selected image]  same-page retry; key retained   |
| gpu_state is telemetry only; it does not label the result  |
+------------------------------------------------------------+
```

## Timing and evidence-bundle mapping

The following is the field-to-copy contract for the operator smoke. It is a
mapping, not a promise that every response has every field.

| Wire location | Meaning | UI rendering |
| --- | --- | --- |
| Multipart `timing.queue_ms` | Run enqueue to worker pickup when applicable | `Queue {duration}` in bulk progress/summary; absent means omit |
| Multipart `timing.ramp_up_ms` | This operation's wait for first service readiness | `Waited for service {duration}`; zero is rendered as zero, null is omitted |
| Multipart `timing.processing_ms` | One image from actual dispatch through result | `described in {duration}` in the single timing line |
| Multipart `timing.startup_ms` | Whole startup only when its start was observed | `Started in {duration}` only when non-null |
| Multipart `timing.server_elapsed_ms` | Service acceptance through response completion | Retain in evidence; do not call it client render latency |
| Run `timing.queue_ms` | Run queue time, counted once | `Queue {duration}` once in run summary |
| Run `timing.ramp_up_ms` | Run-level service readiness wait | `Waited for service {duration}` once, never once per image |
| Run `timing.processing_ms_p50` / `processing_ms_max` | Median and slowest measured per-image processing | `Median per image` and `Slowest`; qualify with `items_timed` |
| Run `timing.items_timed` | Count of measured items | Scope for median/slowest; no values inferred for untimed items |
| Run `timing.startup_ms` / `server_elapsed_ms` | Shared startup and server elapsed evidence | Startup copy only when known; server elapsed stays evidence metadata |
| Run item `processing_ms` | Per-item measured processing | Item detail/timing evidence; never sum concurrent items as run elapsed |

For the cold smoke record: selected media, request/operation ID, response code,
`Retry-After`, `warmup_eta_seconds`, `queue_ms`, `ramp_up_ms`,
`processing_ms`, `startup_ms`, and `server_elapsed_ms`. For the warm smoke,
record the same fields and expect a zero readiness wait only when the wire says
zero. An omitted `timing` object renders no timing line [GRPH-26] [PERC-02].

## Handoff notes for UX-* lanes

- `ux-service`: add the Description Service title, six state sketches, and the
  unavailable-versus-unknown distinction to `gpu-operator-control`.
- `ux-suggest`: add the Suggest warming/no-ETA/ceiling/502 states and bulk
  queue/ramp-up/processing timing to `describe-gpu-tier`; keep the one-shot
  toast policy quiet while the progress surface is mounted [PERC-07].
- `ux-public`: preserve the public observed state boundary, add typed error
  wording only where the public fixture supplies it, and keep same-page retry
  separate from refresh [FORM-05] [PERC-05].
- `ux-identity` is the frozen-plan owner of `workbench-identity-chips`; it is
  called out here because the short task owner list names the SPA C1/C2 lanes
  but omits this map lane. Add the closed listbox, fallback preview, distinct
  representative, and explicit placeholder without editing another map pair.
- All UX-map additions must be made as the canonical `.uxmap.json` and Markdown
  pair and then checked by `render_ux_maps.py --check`; this report is not a
  substitute for that parity check.

## Findings detail

### GPUFLOW-1-UXS-R-01 — medium

The current `settings-burst-gpu` screen and primary copy still expose GPU
jargon. Rename the screen title and visible status copy to Description Service;
keep cost disclosure in the preview, not in the headline. This is a medium map
gap because it directly changes the label consumed by `spa-description-service`
and `ux-service` [HAI-05].

### GPUFLOW-1-UXS-R-02 — medium

Add an unavailable state with the reason `operator STOP`, no ETA, and a clear
recovery action. Keep unknown for missing/stale telemetry and do not merge the
two states. The distinction gives the operator a predictable next action
[HAI-04] [PERC-02].

### GPUFLOW-1-UXS-R-03 — medium

Add the Retention Retry screen/zone and its fetching state. Keep saved rows and
the previous error visible while the read is in flight, with status near the
Retry action [INT-08] [PERC-05].

### GPUFLOW-1-UXS-R-04 — medium

Add timing zones to the Suggest, bulk, and single surfaces, with the wire field
mapping above. The current progress and broad Latency labels cannot tell the
operator waiting-for-service from per-image processing [INT-08] [HAI-05].

### GPUFLOW-1-UXS-R-05 — medium

Add C1 naming screens: listbox closed by default, explicit open-on-intent, and
preview/agreement before the name mutation. The fallback chain must be visible
as a non-empty preview contract [FORM-01] [HAI-18].

### GPUFLOW-1-UXS-R-06 — medium

Add C2 suggestion screens for a distinct representative and the null/invalid
placeholder. The placeholder is an explicit state; an absent crop is not a
reason to reuse the candidate thumbnail [VIZ-07] [HAI-13].

### GPUFLOW-1-UXS-R-07 — medium

Replace the current `>180 s` degraded-flow wording with the frozen 120 s
client ceiling and the manual “still starting - try again” recovery. Keep the
server warm-up deadline separate from the client retry budget [INT-08]
[PERC-05].
