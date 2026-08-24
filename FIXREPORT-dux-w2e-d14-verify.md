LANE: dux-w2e-d14-verify
STATUS: verified — no repair commits required
BASE: 5da328f3a893980b4bffd96965e026f6c5c7ff36
PRIOR FIX: 5aa6977257f1e2a646628bb36684e0dca9854dbb (map align) + e1933fe9 (RED tests)
TESTS: uxmap-render-parity + uxmap-parity + dashboard-uxmap-code-parity — 19 passed / 0 failed
       DashboardPage + dashboard/__tests__ — 85 passed / 0 failed
       Combined (those + related) earlier pass: 104 passed / 0 failed
TS: no TS source changed this lane — `tsc --noEmit` skipped
HOUSE: TEST-15 scratch RED for uxmap-render-parity; sr-001 untouched; BR-74 not in ~/heuristics-canon (house rule only; no gated-control edits)

## uxmap-render-parity — not a tautology (re-proven)

Scratch copy at `/tmp/uxmap-parity-red.yeCOVR/docs/ux-maps` (repo map untouched). Temp test pointed `uxMapsDir` at scratch, then deleted.

Absent `dashboard.uxmap.json` → 3 failed / 8 passed:
```
FAIL  keeps every owned map json and sibling md on disk (fail-closed)
AssertionError: dashboard.uxmap.json is missing — OWNED_MAPS cannot silently skip an absent SSOT: expected false to be true
FAIL  dashboard.uxmap.json validates against the canonical UxMap schema
Error: ENOENT: no such file or directory, open '/tmp/uxmap-parity-red.yeCOVR/docs/ux-maps/dashboard.uxmap.json'
```

Malformed `{ "map_ref": 1, "not": "a-uxmap" }` → 2 failed / 9 passed:
```
FAIL  dashboard.uxmap.json validates against the canonical UxMap schema
AssertionError: dashboard.uxmap.json: 3 schema errors: expected [ …(3) ] to deeply equal []
+   "not | extra_forbidden | a-uxmap",
+   "map_ref | string_type | 1",
+   "product | missing | undefined",
FAIL  loadOwnedMap: dashboard.uxmap.json fails canonical UxMap schema (3 errors)
```

No strengthen needed.

## DUX-W2D14-RV-01 — STATUS: fixed

`DashboardPage.tsx` h1 + WP menu = `Overview`; `retentionCardCopy.ts` = `Data Retention` / `Open Data Retention`. Map title, `z-retention-posture` label, `act-open-retention` verb, and default ASCII match. No `Retention Posture` / `[Retention settings]`.

## DUX-W2D14-RV-02 — STATUS: fixed

Shell states: `default|loading|error|first_time|degraded` only. No `#### Empty` / `#### Offline`. Offline stays Sync Health zone/summary (`getDashboardSyncHealthSummary` / `offlineSummary`) + degraded parenthetical `(attention / offline)`, not a shell branch.

## DUX-W2D14-RV-03 — STATUS: fixed

Code: `assigned_clusters_count > 0` → `FIRST_NAMED` → orientation `HIDDEN`. Default sketch: Assigned 20, no Getting Started. First-time: Assigned 0 + Getting Started + `[Start your first scan]`. Compositions the priority model can produce.

## DUX-W2D14-RV-04 — STATUS: fixed

`z-recent-activity` includes `error` (`historySource === 'unavailable'`); Error sketch has durable-unavailable copy. Hero states `['default']` only (unconditional hero). Library coverage `['default','loading']` only (zeros use default grid).

## DUX-W2D14-RV-05 — STATUS: fixed

Required verbs present in JSON + state sketches; bidirectional sketch↔action check green. Targets match `toWorkbench` / `toRoster` / overlay hrefs (`#/workbench?tab=scan&panel=conflicts|dead-letter`, `advanced=open`, `status=missing`, `personFilter=unassigned`).

## DUX-W2D14-RV-06 — STATUS: fixed

`exit-workbench`, `exit-retention`, `exit-roster` are `kind:exit` with route/wp_page/code_ref/zones like peers. Flows land on exits: first-recognition + review → `exit-workbench`; maintenance → `exit-workbench` then `exit-retention`. `exit-roster` unused by a flow (same orphan pattern as peer `exit-settings`).

## DUX-W2D14-RV-07 — STATUS: fixed

`OrientationCard` is `toWorkbench({ tab: 'scan' })` + `Start your first scan`. Map: `costly:false`, `preview_required:false`. Cost stays on `act-reset-mirror` (real mutate).

## Residual risk

- Retention loading / `available:false` still renders `<></>`; map `loading`/`empty` = absence (open question).
- Identity `!identityStats` path uses `Retry identity stats` (not in map; Error sketch documents `Retry` for `isIdentityError` only).
- Open Review Queue (`tab=scan`) vs Go to Review Queue (`advanced=open`) are two real code paths — map mirrors both.
- No product TS/behavior change this verify lane; prior handoff DB still lacks DUX-W2D14 task on this worktree.
