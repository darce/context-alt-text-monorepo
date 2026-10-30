# gpu-operator-control — ASCII screens, canon critique

Source of truth: `gpu-operator-control.uxmap.json` (authored for GPUOPS-1; E15-38 cold-start and beta update). Only JSON and these notes are authored in this lane; the coordinator owns generated renders and their contract.

## Vocabulary and producer evidence

`GpuControlCard` reads `GpuStatusResponse` from `gpuApi.ts` through `useGpuControl`: snapshot freshness gates the displayed state, and pending intent is separate from lifecycle state. This payload has no warm-up ETA. `ActivityStatusStrip` keeps its run-scoped waiting, overdue, unknown and outage observations and Cancel run / Check status actions. A shared lifecycle warming state alone does not make a run busy.

C1 (exact shared vocabulary): The first description after a quiet period starts the GPU and can take several minutes. After that, each image takes seconds.

## Screen 1 — stopped, automatic (zero state; Start reachable)

```
│ Settings › Description Service                                                   │
│ ■ Service: stopped · snapshot 12 s ago                                           │
│ Intent: Automatic — starts when a describe run needs it, stops after idle.       │
│ Run limit: —                  Load: no work in flight                            │
│ Cost: ≈$2.00 / service-hour · never runs longer than the 60-minute maximum       │
│ [ Start service ]  [ Stop service ] (held: already stopped)  [ Refresh ]         │
```

## Screen 2 — Start confirm strip

```
│ Starts the description service now (≈$2.00/h).                                   │
│ It can take several minutes to be ready.                                         │
│ Returns to automatic after 30 min unless work keeps it busy; the 60-minute       │
│ maximum still applies.                                                           │
│ [ Confirm start ]   [ Cancel ]                                                   │
```

## Screen 3 — starting → warming

```
│ ◌ Service: warming · snapshot 4 s ago                                            │
│ Intent: Start requested until 22:40                                              │
│ The first description after a quiet period starts the GPU and can take           │
│ several minutes. After that, each image takes seconds.                           │
│ [ Start service ] (held: already warming)  [ Stop service ]                      │
│ [ Return to automatic ]   [ Refresh ]                                            │
```

## Screen 4 — ready, work in flight; Stop stays reachable

```
│ ⚡ Service: ready · snapshot 6 s ago                                              │
│ Load: describe run in flight                                                     │
│ [ Start service ] (held: already running)  [ Stop service ]                      │
│ Stop preview: Stop after the current run finishes?                               │
│ [ Confirm stop ]   [ Cancel ]   [ Go to Workbench ]                              │
```

## Screen 5 — stop requested, pending current work

```
│ ⚡ Service: ready · snapshot 5 s ago                                              │
│ Intent: Stopping after the current work finishes until idle                      │
│ [ Stop service ] (held: stop already requested)                                  │
│ [ Return to automatic ]   [ Refresh ]                                            │
```

## Screen 6 — stale / unknown / unavailable

```
│ ? Service: not reported · last snapshot 4 min ago (stale)                        │
│ Service status is out of date. Refresh before starting the service.              │
│ Stop and automatic requests may be delayed.                                      │
│ Start / Stop hidden; [ Return to automatic ] when manual intent is set           │
│ [ Refresh ]                                                                      │
```

For unavailable status, preserve the existing cause, last-checked time and actual retry interval. Pending intent, unavailable observation and stale snapshot never imply readiness. No new countdown or service action is introduced here.

## Existing Workbench exit — beta disclosure states

```
│ Review Queue                                                                     │
│ Beta: descriptions are AI-generated drafts to review before publishing.          │
│ > What to expect (closed initially)                                              │
│ Existing panels, navigation, status and cancel controls follow.                  │
```

Expanding **What to expect** reveals correction guidance, exact C1, and the user's choice to edit and publish drafts. Native summary remains focusable; this informational disclosure has no alert role. Existing per-result review controls remain the verification surface.

## Canon critique — Canon v0.26.2

- [HAI-05] **Imperceptible AI is not ethical**, *Human-Centered AI*: disclose AI drafts above the panels without claiming a model winner. [HAI-12] **Output is a proposal, not the answer**, *Designing AI Interfaces (Macfadyen 2026)*: ask for review before publishing.
- [HAI-13] **User is the last error detector**, *Designing AI Interfaces (Macfadyen 2026), § surfacing-state*: keep the standing stage notice compact and quiet, with expanded guidance optional; preserve existing per-result review/edit controls. This notice does not replace verification at the output.
- [INT-10] **Status–predict–stop**, *Human-Centered AI*: status, next step and existing Stop / Cancel / Check status controls stay together. A retry interval is not a readiness prediction.
- [RLSE-04] **Undesigned state is a bug**, practice label `bootstrap`: stale, unknown, unavailable and pending remain explicit; C1 replaces fixed startup promises. Native details supplies both collapsed and expanded states without changing the navigation or control composition.

Bounded manual critique before composition: the existing map implies an ETA absent from the operator payload, and the old notes disabled Stop during work although the real producer allows a deferred stop. The sketches above correct both using `gpuApi.ts`, `useGpuControl.ts` and `GpuControlCard.tsx`. No new map or generated output is authored. The Design Canvas critique CLI/MCP is unavailable in this worker; this is a source-based critique, not a claimed engine run.
