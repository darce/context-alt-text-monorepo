# describe-gpu-tier — ASCII screens, canon critique, lane DAG

Source of truth: `describe-gpu-tier.uxmap.json` (hand-authored 2026-09-02; no `ux-map` CLI installed locally — render by hand, re-render via `ux-map render` once the Design Canvas CLI ships).
Predecessor finding: `DEMO-UX-1-GPU-01` (open, db id 10035). Reserved wire field: `DescribeRunResponse.gpu_state` (WBUX-3, typed `null` both sides).

## Proposed `gpu_state` vocabulary (sr-007: `StrEnum` backend / `as const` TS)

| value      | meaning                                              | who writes it                          |
| ---------- | ---------------------------------------------------- | -------------------------------------- |
| `unknown`  | no snapshot / stale > 120 s (CAL-02: unknown is valid) | API when `/run/acx/gpu-state.json` missing/stale |
| `stopped`  | instance STOPPED, no start requested                 | lifecycle starter/reaper cycle         |
| `starting` | OCI START issued, instance not RUNNING yet           | starter (writes lease tag + state)     |
| `warming`  | RUNNING, llama-server `/health` not 200 yet          | starter probe (30×10 s)                |
| `ready`    | `/health` 200 within last probe window               | starter/reaper cycle                   |
| `degraded` | START failed / probe timed out / unreachable         | starter (fail loud: OBS-08, RLSE-05)   |

One writer (DATA-14): the lifecycle unit owns `gpu-state.json`; the API only reads. `tier` on each item stays `provisional_cpu | final_gpu`.

## Screen 1 — Workbench, GPU cold, before commit (INT-07 preview, INT-06 label, CARD-15)

```
┌ Workbench › Media ───────────────────────────────────────────────────────────┐
│ [x] 12 selected                                     ┌──────────────────────┐ │
│                                                     │ ⚡ GPU tier: stopped  │ │
│ ┌───────────────────────────────────────────────┐   │ Will warm on start   │ │
│ │ ▶ Describe 12 selected                        │   │ (~2 min, ≈$0.07)     │ │
│ │   GPU will warm first · CPU drafts arrive     │   └──────────────────────┘ │
│ │   meanwhile · you can cancel any time         │                            │
│ └───────────────────────────────────────────────┘                            │
└──────────────────────────────────────────────────────────────────────────────┘
```
Zones: `z-bulk-cta` (gpu-cold-preview), `z-gpu-tier-chip` (stopped). No modal (not_doing).

## Screen 2 — Warming, then provisional → final (INT-08, INT-10, CARD-09 bounded wait)

```
┌ Bulk describe ─────────────────────────────── role=status aria-live=polite ─┐
│ ⏳ Warming GPU … about 1 min 30 s left        [Cancel run]                    │
│ [██████░░░░░░░░░░░░░░░░░░]  0 of 12 processed                                │
│ ⚡ GPU tier: warming · started 22:31:04                                       │
│ CPU drafts will appear first; final descriptions replace them when ready.   │
└──────────────────────────────────────────────────────────────────────────────┘
        ▼ 40 s later
┌ Bulk describe ──────────────────────────────────────────────────────────────┐
│ ◐ Describing (CPU drafts) · 7 of 12 drafted     [Cancel run]  [Use CPU      │
│ [██████████████░░░░░░░░░░]  58%                                drafts now]  │
│ ⚡ GPU tier: ready · final descriptions in progress 3/12                     │
└──────────────────────────────────────────────────────────────────────────────┘
        ▼ terminal
┌ Bulk describe ──────────────────────────────────────────────────────────────┐
│ ✔ Complete · 12 final (GPU) · 0 provisional · 0 failed   [Review results →] │
│ [████████████████████████] 100%                                             │
└──────────────────────────────────────────────────────────────────────────────┘
```
Countdown ticks in an `aria-hidden` span; the announced sentence is static (A11Y-21, same pattern as the cooldown notice in `BulkDescribeProgress`). Icon + colour (A11Y-06, sr-004). "Use CPU drafts now" = INT-11 refine-over-restart: the provisional work is never thrown away.

## Screen 3 — Degraded: GPU never came up (COST-10 graceful degradation, RLSE-04 designed state)

```
┌ Bulk describe ───────────────────────────── role=status (NOT alert) ────────┐
│ ⚠ GPU unavailable — kept 12 CPU drafts. Final descriptions will not upgrade.│
│ [████████████████████████] 12 of 12 processed (provisional)                 │
│ ⚡ GPU tier: degraded · start timed out after 180 s        [Review results →]│
└──────────────────────────────────────────────────────────────────────────────┘
```
Not `role=alert`: the run *succeeded* at the CPU tier; alert is reserved for a lost run (PERC-07 don't habituate alarms). Wording names the state and the consequence (FORM-05 / A11Y-17 shape applied to status).

## Screen 4 — Dashboard single describe when GPU is stopped (HAI-05 imperceptible AI is not ethical)

```
┌ Describe with AI ───────────────────────────────────────────────────────────┐
│ Media ID [ 4711 ]   [Describe with AI]                                       │
│ ┌ role=alert ─────────────────────────────────────────────────────────────┐ │
│ │ ✖ GPU tier is stopped. Single-image describe uses the GPU directly;     │ │
│ │   start a bulk run from the Workbench to warm it, or wait ~2 min.       │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│ Provenance   Adapter: gpu_qwen30b   Model: Qwen3-VL-30B-A3B Q4   Source: —   │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Toast policy (overlay `toast-gpu-transition`; `ToastContext` 5 s, success/error/info)

| transition                         | toast? | variant | when                                                          |
| ---------------------------------- | ------ | ------- | ------------------------------------------------------------- |
| stopped → starting/warming         | no     | —       | progress zone is the fovea (PERC-05); chip + progress line     |
| warming → ready while on screen    | no     | —       | polite region already announces; avoid double read (A11Y-21)  |
| warming → ready, operator navigated away | yes | info   | "GPU ready — final descriptions in progress" (once per run)   |
| run complete (all final)           | yes    | success | "12 final descriptions ready · Review" (once; link action)    |
| → degraded                         | yes    | error   | "GPU unavailable — CPU drafts kept" (once; PERC-07 rare+worse) |
| run cancelled                      | yes    | info    | "Run cancelled — 7 drafts kept" (INT-11)                      |
| every poll / per-item tier change  | never  | —       | PERC-07 habituation                                            |

Implementation seam: a `useGpuStateToasts(run)` hook keyed on `(run_id, gpu_state)` edge transitions, mounted at the SPA shell (not inside `BulkDescribeProgress`) so it survives navigation; `phasePresentation.ts` strategy-map gains `gpu_state` rows (REF-02, no switch); `SYNC_VOCABULARY` gains the say/don't-say strings (NAV-13: say "GPU tier", "CPU draft", "final"; don't say "burst host", "llama", "provisional" in operator copy).

## Canon critique of the current build (IDs verified against heuristics-canon-research 2026-09-02)

| rule / card | finding against current code | seam |
| --- | --- | --- |
| RLSE-04 undesigned state | `gpu_state: null` both sides; warming/stopped/degraded have no designed UI state | `describeApi.ts:250`, `DescribeRunResponse` |
| INT-08 / CARD-09 | cold start ≈100 s renders as a stalled 0 % bar; no bound, no cancel affordance tied to warm-up | `BulkDescribeProgress` |
| INT-10 status–predict–stop | operator cannot see GPU state, predict when finals arrive, or stop the GPU | chip zone missing |
| HAI-05 / HAI-08 / PROV-06 | tier (`provisional_cpu`/`final_gpu`) never reaches the UI; drafts and finals look identical | `DescribeRunApplyView.tsx`, PHP proxy |
| INT-07 / CARD-15 | CTA does not disclose that clicking starts a $2/hr instance | `z-bulk-cta` label |
| OBS-08 / RLSE-05 / CARD-07 | lifecycle: missing load snapshot → reaper exits 1 silently every 2 min; only max-lease STOP acts, computed from `time-created` (July) | `reaper.py:355-360`, `controller.py:127` |
| RES-20 finish what you start | START actuator never writes the lease it later reads | `reaper.py:273-312` |
| RES-02 / RES-03 | GPU endpoint 5 s connect timeout surfaces as generic failure, not "GPU stopped" (slow ≠ down not distinguished) | `settings.py:48`, `gpu_remote_adapter.py` |
| DATA-14 | two candidate writers for GPU state (API probe vs lifecycle) — decide one | contract |
| CAL-02 / CARD-03 designed unknown | stale snapshot must render as `unknown`, not as `ready` or `stopped` | API reader |
| COST-03 / COST-10 | no cheaper reserved path on prod image (florence_small not deployable, torch-free) → degraded = keep CPU drafts, not silent 500 | producer + FE |
| TEST-15 | every new state needs a red-able assertion (mutant: swap `warming`↔`ready`) | lane tests |

## Lane DAG (grok-remote flocks, ≤3 concurrent, each lane commits in <10 min)

```
        L0 contract (coordinator, local): gpu_state enum + tier passthrough + lease tag
        │
   ┌────┼────────────┐
   A    B            │            A: reaper lease tag write/read + fail-loud lease (reaper.py, tests)
   │    │            │            B: producer/mount — rebase WBUX-6 uid fix, prod /run/acx mount + ACX_GPU_* env,
   │    │            │               .env.prod.example, freshness check script
   F    │            C ── D       C: API gpu_state reader (gpu-state.json → DescribeRunResponse) + tier on items
   │    │            │    │       D: PHP proxy passthrough (rg-015: no invented fields)
   │    │            └────E       E: FE vocabulary + phasePresentation rows + useGpuStateToasts + tests
   └────┴──────┬──────────┘       F: starter writes gpu-state.json each cycle; probe → warming/ready/degraded
               G                  G: VM smoke/e2e: start → probe :8000 → describe run → tiers → stop; test_result
Waves: W1 {A, B} · W2 {C, D, F} · W3 {E} · W4 {G}
```

## Screen 5 — GPU-state toasts, operator navigated away (E2 `useGpuStateToasts`, 2026-09-03 iteration)

Scope: only `gpu_state` edge transitions of the *active* describe run. Run-complete / cancelled toasts stay with the existing bulk-describe flow (not this hook).

```
┌ Alt Context › People (operator left the Workbench mid-run) ──────────────────┐
│ … page content …                                                             │
│                                                        ┌───────────────────┐ │
│                                                        │ ℹ GPU ready       │ │
│                                                        │ Final descriptions│ │
│                                                        │ in progress ·     │ │
│                                                        │ [Back to run]     │ │
│                                                        └───────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
   variant=info · fires once per (run_id, warming→ready) · 5 s · role=status

┌ … any page … ────────────────────────────────────────────────────────────────┐
│                                                        ┌───────────────────┐ │
│                                                        │ ✖ GPU unavailable │ │
│                                                        │ CPU drafts kept · │ │
│                                                        │ [Review results]  │ │
│                                                        └───────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
   variant=error · fires once per (run_id, *→degraded) · icon + colour (A11Y-06)

┌ Workbench (BulkDescribeProgress mounted) ────────────────────────────────────┐
│ ⏳ Warming GPU … about 1 min 30 s left        [Cancel run]                    │
│ ⚡ GPU tier: warming → ready                      (no toast: PERC-05 fovea,   │
│                                                    A11Y-21 no double read)   │
└──────────────────────────────────────────────────────────────────────────────┘
```

Edge table (hook input = previous `gpuState`, next `gpuState`; keyed on `run_id`):

| prev → next | toast | note |
| --- | --- | --- |
| `unknown` → anything, anything → `unknown` | never | CAL-02: unknown is not an event |
| `stopped`/`starting` → `warming` | info, only if progress zone NOT mounted | "GPU warming — CPU drafts first" |
| `warming` → `ready` | info, only if progress zone NOT mounted | once per run_id |
| any → `degraded` | error, always (also when progress mounted: PERC-07 rare + worse) | once per run_id |
| `ready` → `ready` (poll) | never | habituation |
| new `run_id` | reset edge memory | a second run may toast again |

Mount point: SPA shell beside `ToastProvider` (`js/admin/App.tsx`), never inside `BulkDescribeProgress`, so the edge memory survives route changes. Strings come from `GPU_STATE_VOCABULARY` (NAV-13 say "GPU tier"/"CPU draft"/"final"). Mutants a lane must kill (TEST-15): swap `warming`↔`ready` in the edge table; drop the `run_id` reset; drop the progress-mounted suppression.
