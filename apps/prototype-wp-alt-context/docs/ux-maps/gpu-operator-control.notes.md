# gpu-operator-control — ASCII screens, canon critique

Source of truth: `gpu-operator-control.uxmap.json` (authored 2026-09-06 for GPUOPS-1; render with `docs/ux-maps/render_ux_maps.py gpu-operator-control`). Predecessor: `describe-gpu-tier` open question HAI-04. Contracts C1–C7 in `docs/tasks/v0.5.0/GPUOPS-1-gpu-operator-control-and-named-captions-task-plan.md`.

## Vocabulary

State chip reuses `gpuStatePresentation` (`unknown | stopped | starting | warming | ready | degraded`). Intent copy: "Automatic", "Start requested until HH:MM", "Stop requested", "Stop pending: describe run in flight". Reasons (from `last_transition_reason`): "started for work", "started by operator", "stopped when idle", "stopped at lease cap", "start failed".

## Screen 1 — stopped, automatic (zero state; Start reachable, rg-003)

```
┌ Settings › Burst GPU ────────────────────────────────────────── aria-live=polite ┐
│ ⚡ GPU: stopped        · snapshot 12 s ago                                       │
│ Intent: Automatic — starts when a describe run needs it, stops after idle.       │
│ Lease: —                     Load: no work in flight (load snapshot 8 s ago)     │
│ Cost: ≈$2.00 / GPU-hour · warm-up ≈2 min · never runs longer than the 60 min cap │
│                                                                                  │
│ [ ▶ Start GPU ]   [ ■ Stop GPU ]disabled: already stopped   [ ↻ Refresh ]        │
└──────────────────────────────────────────────────────────────────────────────────┘
```

## Screen 2 — Start confirm strip (INT-07 preview, CARD-15, A11Y-18)

```
│ [ ▶ Start GPU ]  ...                                                              │
│ ┌ Confirm start ─────────────────────────────────────────────────────────────┐   │
│ │ Starts the A10 now (≈$2.00/h). Ready in about 2 min. Returns to automatic  │   │
│ │ after 30 min unless work keeps it busy; the 60 min lease cap still applies.│   │
│ │                                          [ Confirm start ]   [ Cancel ]    │   │
│ └────────────────────────────────────────────────────────────────────────────┘   │
```

## Screen 3 — starting → warming (bounded wait, INT-08, CARD-09)

```
│ ⚡ GPU: warming        · snapshot 4 s ago      (polling every 5 s)               │
│ Intent: Start requested until 22:40 · honoured 22:10:14                          │
│ Lease: running since 22:10:14 · auto-stops by 23:10 (lease cap)                  │
│ Load: no work in flight                                                          │
│ ⏳ Warming… about 1 min 20 s left                                                 │
│ [ ▶ Start GPU ]disabled: already starting  [ ■ Stop GPU ]  [ ↺ Return to auto ]  │
```

## Screen 4 — ready, work in flight, Stop blocked (FLOW-08 deferred, not dropped)

```
│ ⚡ GPU: ready          · snapshot 6 s ago                                        │
│ Intent: Automatic                                                                │
│ Lease: running since 22:12:01 · auto-stops by 23:12 (lease cap)                  │
│ Load: describe run in flight (load snapshot 3 s ago)                             │
│ [ ▶ Start GPU ]disabled: already running                                         │
│ [ ■ Stop GPU ]disabled: a describe run is in flight — stops once it finishes     │
│ [ → Go to Workbench ]                                                            │
```

## Screen 5 — stop requested but pending (intent_status blocked_work_in_flight → degraded canonical)

```
│ ⚡ GPU: ready          · snapshot 5 s ago                                        │
│ ⚠ Intent: Stop pending — a describe run is in flight; the GPU stops when it ends.│
│ [ ↺ Return to auto ]   [ ↻ Refresh ]                                             │
```

## Screen 6 — snapshot stale / service unreachable (OBS-08, CAL-02)

```
│ ⚡ GPU: not reported   · last snapshot 4 min ago (stale)                         │
│ Intent: Automatic (from last snapshot)                                           │
│ ⚠ Lifecycle telemetry is stale. Controls stay available; results may be delayed. │
```
```
│ ✖ Could not reach the description service (502). Retrying in 15 s.  [ ↻ Retry ] │
```

## Canon critique

- INT-10 status–predict–stop: every state line carries a time anchor (snapshot age, lease expiry, ETA) and one stop affordance.
- HAI-04 activate–operate–override: automatic is the default and the "Return to automatic" control is always one click when an intent is set.
- COST-10 / CARD-15: cost, warm-up and cap appear before the commit, not after.
- RES-10: the UI copy names the lease cap as overriding the operator start; the backend enforces it.
- A11Y-18: Stop and Start are confirmable; both are reversible (Return to automatic), so no destructive styling.
- rg-003: Start is reachable from the stopped zero state without any selection.
- rg-015: every value shown maps to a field in C2/C3; nothing is computed client-side except relative times.
