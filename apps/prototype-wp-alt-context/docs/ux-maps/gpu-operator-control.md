# UX Map — gpu-operator-control

**Product:** `alt-context WP plugin admin SPA — Settings › Description Service operator control (start / stop / automatic)`
**Source fixture:** `apps/prototype-wp-alt-context/js/admin/pages/SettingsPage.tsx`

## Goals
- Operator can always see Description Service state, effective intent, activity and load freshness in one place (INT-10 status–predict–stop, OBS-08 stale is shown as unknown with age).
- Operator can request Start, Stop or Return to automatic; each request is acknowledged within one poll and its outcome (honoured, pending, blocked) is visible (HAI-04 activate–operate–override).
- Cost is disclosed before commitment; the user is never surprised by an hourly charge (INT-07, CARD-15, COST-10).
- Stop intent can be requested while busy and shutdown is deferred until idle. Stale or unknown telemetry blocks Start; unavailable with operator STOP is distinct from unknown (INT-10, FLOW-08, A11Y-18, PERC-02).

## Jobs
- `job-prewarm-gpu` — Pre-warm Description Service before a demo so the first describe run is fast
- `job-stop-gpu` — Stop Description Service now to end spend
- `job-return-auto` — Return Description Service to automatic lifecycle

## Screens
| id | kind | route | title |
| --- | --- | --- | --- |
| `settings-burst-gpu` | screen | `#/settings` | Settings › Description Service |
| `gpu-start-confirm` | overlay | `#/settings (inline strip; no dedicated route)` | Confirm Start |
| `gpu-stop-confirm` | overlay | `#/settings (inline strip; no dedicated route)` | Confirm Stop |
| `exit-workbench` | exit | `#/workbench` | Workbench |

### Settings › Description Service (`settings-burst-gpu`)

Purpose: Card on the Settings page showing Description Service state, intent, activity and load, with Start / Stop / Return to automatic controls. Domain vocabulary behind the canonical states: stopped and ready = default; starting and warming = loading; snapshot missing = empty; service unreachable or unavailable (operator STOP) = error; lifecycle degraded or intent blocked = degraded. Primary copy uses Service: stopped / starting / warming / ready / unavailable; ETA and Retry-After are data, not extra states.

Action states: stopped, unknown, starting, warming, ready, degraded, unavailable

| zone id | label | role | states |
| --- | --- | --- | --- |
| `z-gpu-state-chip` | Service status chip — Service: not reported / stopped / starting / warming / ready / degraded / unavailable with snapshot age (icon + text) | status | default, loading, empty, error, degraded |
| `z-gpu-intent` | Effective intent and expiry — automatic / start until HH:MM / stop (pending, blocked: describe run in flight) | status | default, loading, degraded |
| `z-gpu-lease` | Service activity — idle or running since, auto-stops by HH:MM (run limit); never show lease ids | status | default, empty |
| `z-gpu-load` | Describe load — work in flight yes/no with load snapshot freshness | status | default, empty, degraded |
| `z-gpu-cost` | Cost disclosure — hourly rate and warm-up time before Start, not in the headline | content | default |
| `z-gpu-controls` | Start service / Stop service / Return to automatic | form | default, loading, error, degraded |

```
+------------------------------------------------------------+
| Settings › Description Service  [screen]  #/settings       |
| Card on the Settings page showing Description Service stat…|
+------------------------------------------------------------+
| ZONES                                                      |
|   - Service status chip — Service: not reported / stopped …|
|   - Effective intent and expiry — automatic / start until …|
|   - Service activity — idle or running since, auto-stops b…|
|   - Describe load — work in flight yes/no with load snapsh…|
|   - Cost disclosure — hourly rate and warm-up time before …|
|   - Start service / Stop service / Return to automatic (fo…|
+------------------------------------------------------------+
| ACTIONS                                                    |
| when stopped                                               |
|   [PRIMARY] Start service                                  |
|   [secondary] Return to automatic                          |
|   [tertiary] Refresh status                                |
| when unknown                                               |
|   [secondary] Return to automatic                          |
|   [tertiary] Refresh status                                |
| when starting                                              |
|   [secondary] Stop service                                 |
|   [secondary] Return to automatic                          |
|   [tertiary] Refresh status                                |
| when warming                                               |
|   [secondary] Stop service                                 |
|   [secondary] Return to automatic                          |
|   [tertiary] Refresh status                                |
| when ready                                                 |
|   [secondary] Stop service                                 |
|   [secondary] Return to automatic                          |
|   [tertiary] Refresh status                                |
|   [secondary] Go to Workbench                              |
| when degraded                                              |
|   [PRIMARY] Start service                                  |
|   [secondary] Stop service                                 |
|   [secondary] Return to automatic                          |
|   [tertiary] Refresh status                                |
| when unavailable                                           |
|   [PRIMARY] Start service                                  |
|   [secondary] Return to automatic                          |
|   [tertiary] Refresh status                                |
+------------------------------------------------------------+
| states: default | loading | empty | error | degraded       |
+------------------------------------------------------------+
```

### Confirm Start (`gpu-start-confirm`)

Purpose: Inline confirm strip below the controls: names the hourly cost, the warm-up time and the intent TTL after which lifecycle returns to automatic. Stays until confirmed or dismissed.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `z-start-preview` | Start preview — cost per hour, warm-up estimate, auto-return after TTL | content | default |
| `z-start-actions` | Confirm start / Cancel | form | default, loading, error |

```
+------------------------------------------------------------+
| Confirm Start  [overlay]  #/settings (inline strip; no ded…|
| Inline confirm strip below the controls: names the hourly …|
+------------------------------------------------------------+
| ZONES                                                      |
|   - Start preview — cost per hour, warm-up estimate, auto-…|
|   - Confirm start / Cancel (form) states=[default,loading,…|
+------------------------------------------------------------+
| ACTIONS                                                    |
|   [PRIMARY] Confirm start -> POST recognition/gpu/intent {…|
|   [secondary] Cancel -> settings-burst-gpu                 |
+------------------------------------------------------------+
| states: default | loading | error                          |
+------------------------------------------------------------+
```

### Confirm Stop (`gpu-stop-confirm`)

Purpose: Inline confirm strip: explains that a stop is honoured only when no describe run is in flight, otherwise it is deferred and shown as pending.

| zone id | label | role | states |
| --- | --- | --- | --- |
| `z-stop-preview` | Stop preview — immediate when idle, deferred while a describe run is in flight | content | default, degraded |
| `z-stop-actions` | Confirm stop / Cancel | form | default, loading, error |

```
+------------------------------------------------------------+
| Confirm Stop  [overlay]  #/settings (inline strip; no dedi…|
| Inline confirm strip: explains that a stop is honoured onl…|
+------------------------------------------------------------+
| ZONES                                                      |
|   - Stop preview — immediate when idle, deferred while a d…|
|   - Confirm stop / Cancel (form) states=[default,loading,e…|
+------------------------------------------------------------+
| ACTIONS                                                    |
|   [PRIMARY] Confirm stop -> POST recognition/gpu/intent {a…|
+------------------------------------------------------------+
| states: default | loading | error | degraded               |
+------------------------------------------------------------+
```

### Workbench (`exit-workbench`)

Purpose: Go describe media once Description Service is ready

url_params: `run_id`

| zone id | label | role | states |
| --- | --- | --- | --- |
| `z-wb-entry` | Workbench entry | nav | default |

```
+------------------------------------------------------------+
| Workbench  [exit]  #/workbench                             |
| Go describe media once Description Service is ready        |
+------------------------------------------------------------+
| ZONES                                                      |
|   - Workbench entry (nav) states=[default]                 |
+------------------------------------------------------------+
| states: default                                            |
+------------------------------------------------------------+
```

## Actions

| id | verb | target | hierarchy | costly | irreversible | preview required | screen id | when (recovery state) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `act-gpu-start` | Start service | `gpu-start-confirm` | primary | yes | no | yes | `settings-burst-gpu` | stopped, degraded, unavailable |
| `act-gpu-confirm-start` | Confirm start | `POST recognition/gpu/intent {action: start}` | primary | yes | no | no | `gpu-start-confirm` | always |
| `act-gpu-stop` | Stop service | `gpu-stop-confirm` | secondary | no | no | yes | `settings-burst-gpu` | starting, warming, ready, degraded |
| `act-gpu-confirm-stop` | Confirm stop | `POST recognition/gpu/intent {action: stop}` | primary | no | no | no | `gpu-stop-confirm` | always |
| `act-gpu-auto` | Return to automatic | `POST recognition/gpu/intent {action: auto}` | secondary | no | no | no | `settings-burst-gpu` | always |
| `act-gpu-refresh` | Refresh status | `GET recognition/gpu/status` | tertiary | no | no | no | `settings-burst-gpu` | always |
| `act-cancel-confirm` | Cancel | `settings-burst-gpu` | secondary | no | no | no | `gpu-start-confirm` | always |
| `act-goto-workbench` | Go to Workbench | `exit-workbench` | secondary | no | no | no | `settings-burst-gpu` | ready |

## Flows
### Pre-warm before a demo (`flow-prewarm`)

```mermaid
flowchart TD
  %% flow: Pre-warm before a demo job=job-prewarm-gpu
  %% steps: [{"screen_id":"settings-burst-gpu","branch_label":"state stopped → Start service"},{"screen_id":"gpu-start-confirm","branch_label":"preview cost + TTL → Confirm start (202)"},{"screen_id":"settings-burst-gpu","branch_label":"intent start (pending) → starting → warming (bounded ETA) → ready"},{"screen_id":"exit-workbench","branch_label":"Go to Workbench"}]
  n_settings_burst_gpu["Settings › Description Service (screen)"]
  n_gpu_start_confirm["Confirm Start (overlay)"]
  n_settings_burst_gpu -->|state stopped → Start service| n_gpu_start_confirm
  n_gpu_start_confirm -->|preview cost + TTL → Confirm start (202)| n_settings_burst_gpu
  n_exit_workbench["Workbench (exit)"]
  n_settings_burst_gpu -->|intent start (pending) → starting → warming (bounded ETA) → ready| n_exit_workbench
```

### Stop while a describe run is in flight (`flow-stop-blocked`)

```mermaid
flowchart TD
  %% flow: Stop while a describe run is in flight job=job-stop-gpu
  %% steps: [{"screen_id":"settings-burst-gpu","branch_label":"state ready, load.has_work → Stop service disabled with reason"},{"screen_id":"settings-burst-gpu","branch_label":"run finishes → Stop service enabled"},{"screen_id":"gpu-stop-confirm","branch_label":"Confirm stop (202)"},{"screen_id":"settings-burst-gpu","branch_label":"intent stop (pending) → stopped; reason operator"}]
  n_settings_burst_gpu["Settings › Description Service (screen)"]
  n_settings_burst_gpu -->|state ready, load.has_work → Stop service disabled with reason| n_settings_burst_gpu
  n_gpu_stop_confirm["Confirm Stop (overlay)"]
  n_settings_burst_gpu -->|run finishes → Stop service enabled| n_gpu_stop_confirm
  n_gpu_stop_confirm -->|Confirm stop (202)| n_settings_burst_gpu
```

### Return to automatic (`flow-return-auto`)

```mermaid
flowchart TD
  %% flow: Return to automatic job=job-return-auto
  %% steps: [{"screen_id":"settings-burst-gpu","branch_label":"intent start until HH:MM → Return to automatic"},{"screen_id":"settings-burst-gpu","branch_label":"intent automatic; idle reap resumes"}]
  n_settings_burst_gpu["Settings › Description Service (screen)"]
  n_settings_burst_gpu -->|intent start until HH:MM → Return to automatic| n_settings_burst_gpu
```

## Open questions
- Should Start service be offered on the Workbench media selection as well as Settings? Current recommendation: Settings only; Workbench keeps enqueue-triggered start and the cold-start cost hint (describe-gpu-tier not_doing).
- Default intent TTL is 30 min server-clamped to 120 min; confirm against the measured cold-start and typical demo length.

## Parity index

Machine-checked by `js/admin/__tests__/uxmap-parity.test.ts` and
`js/admin/__tests__/uxmap-render-parity.test.ts`: every id, state, and verbatim label
below must exist in the sibling `.uxmap.json`, and no `z-*`/`act-*` id may appear here
that the JSON does not define. Regenerate with `docs/ux-maps/render_ux_maps.py` — never
hand-edit one side.

Zone ids: z-gpu-state-chip z-gpu-intent z-gpu-lease z-gpu-load z-gpu-cost z-gpu-controls z-start-preview z-start-actions z-stop-preview z-stop-actions z-wb-entry

Action ids: act-gpu-start act-gpu-confirm-start act-gpu-stop act-gpu-confirm-stop act-gpu-auto act-gpu-refresh act-cancel-confirm act-goto-workbench

Zone labels (verbatim; the tables above escape `|` for markdown, this list does not):

- Service status chip — Service: not reported / stopped / starting / warming / ready / degraded / unavailable with snapshot age (icon + text)
- Effective intent and expiry — automatic / start until HH:MM / stop (pending, blocked: describe run in flight)
- Service activity — idle or running since, auto-stops by HH:MM (run limit); never show lease ids
- Describe load — work in flight yes/no with load snapshot freshness
- Cost disclosure — hourly rate and warm-up time before Start, not in the headline
- Start service / Stop service / Return to automatic
- Start preview — cost per hour, warm-up estimate, auto-return after TTL
- Confirm start / Cancel
- Stop preview — immediate when idle, deferred while a describe run is in flight
- Confirm stop / Cancel
- Workbench entry

States (all zones and screens): default loading empty error degraded

## Not doing
- No modal dialog; confirmation is an inline strip (consistent with describe-gpu-tier not_doing).
- No per-poll toasts; useGpuStateToasts already covers transitions. Suppress toasts while a warming progress surface is mounted (GPUUX-1, PERC-07).
- No direct OCI calls from PHP or the SPA; every field is pass-through from gpu-state.json and the intent file (rg-015).
- Primary copy never names leases, lease ids, or demand-lease internals; those stay on the wire (UXSCRE-M-08).
