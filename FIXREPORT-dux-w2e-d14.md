LANE: dux-w2e-d14
STATUS: complete
COMMITS: e1933fe9f7ba413df406d202ddf6e442cf7f8334 test(admin,DUX-W2D14-RV-01..07): RED dashboard uxmap code parity
5aa6977257f1e2a646628bb36684e0dca9854dbb fix(admin,DUX-W2D14-RV-01..07): align dashboard uxmap with rendered code
TESTS: focused Vitest dashboard-uxmap-code-parity + uxmap-render-parity + uxmap-parity — 19 passed / 0 failed (v4.1.5)
RED: dashboard-uxmap-code-parity.test.ts 7 failed / 0 passed against map HEAD a6e9e4ee before the fix commit
HOUSE RULES: sr-001 no assertion weakening; TEST-15 RED proven (map-absent + malformed JSON + per-finding); names taken from DashboardPage / retentionCardCopy / OrientationCard; no product-behavior change

## DUX-W2D14-RV-01 — STATUS: fixed

Map screen title is now `Overview` (DashboardPage.tsx h1 / menu_title). Retention zone label and `act-open-retention` verb are `Data Retention` / `Open Data Retention` from retentionCardCopy.ts. ASCII default sketch uses those strings; `Retention Posture` / `[Retention settings]` removed.

RED proof:
```
FAIL  dashboard-uxmap-code-parity.test.ts > RV-01: screen/zone/action names come from the rendered component strings
AssertionError: map title must match DashboardPage h1: expected 'Dashboard' to be 'Overview'
Expected: "Overview"
Received: "Dashboard"
```

## DUX-W2D14-RV-02 — STATUS: fixed

Dropped screen states `empty` and `offline`. No exclusive shell branch and no ASCII `#### Empty` / `#### Offline`. Offline remains a Sync Health zone/summary tag on the Degraded sketch (parenthetical, not a control). Shell states: default, loading, error, first_time, degraded.

RED proof:
```
FAIL  ... RV-02: screen states only name exclusive shell branches the code can take
AssertionError: empty is not an exclusive dashboard-shell branch: expected [ 'default', 'loading', 'empty', …(4) ] to not include 'empty'
```

## DUX-W2D14-RV-03 — STATUS: fixed

Default sketch is first_named only: Assigned 20, no Getting Started. First-time sketch is unscanned: Assigned 0 + orientation + `[Start your first scan]`. Matches `assigned_clusters_count > 0 => FIRST_NAMED => orientation HIDDEN`.

RED proof:
```
FAIL  ... RV-03: default and first_time sketches are compositions the priority model can produce
AssertionError: expected '+------------------------------------…' not to match /Getting Started with Identity Recogni…/
Received default sketch included both Getting Started and Assigned 20
```

## DUX-W2D14-RV-04 — STATUS: fixed

`z-recent-activity` now includes `error` (unavailable branch already drawn in Error sketch). `z-dashboard-hero` and `z-library-coverage` dropped `first_time` (hero is always the same; coverage has only default/loading).

RED proof:
```
FAIL  ... RV-04: zone state matrices match exclusive component branches
AssertionError: expected [ 'default', 'empty', 'degraded' ] to deeply equal ArrayContaining{…}
-   "error",
```

## DUX-W2D14-RV-05 — STATUS: fixed

Added actions and sketch brackets for: Open Failed Sync Queue, View Results, Retry, Dismiss getting started, Go to Review Queue, Review unassigned persons, Go to Scan tab. Bidirectional: every `[control]` in state sketches is an action verb; every action verb appears in a sketch. `[x]` replaced with `[Dismiss getting started]`.

RED proof:
```
FAIL  ... RV-05: every sketch control has an action, and every action appears in a sketch
AssertionError: act-view-results missing or misnamed: expected undefined to be 'View Results'
```

## DUX-W2D14-RV-06 — STATUS: fixed

Added kind:`exit` screens `exit-workbench`, `exit-retention`, `exit-roster` matching peer schema (route, wp_page, code_ref, entry zone). Flows now land on them: flow-first-recognition and flow-dashboard-review → exit-workbench; flow-dashboard-maintenance → exit-workbench then exit-retention.

RED proof:
```
FAIL  ... RV-06: off-surface destinations are kind:exit screens and flows land on them
AssertionError: expected [] to deeply equal [ 'exit-retention', 'exit-roster', 'exit-workbench' ]
```

## DUX-W2D14-RV-07 — STATUS: fixed

`act-start-first-scan` verb is `Start your first scan`; `costly` and `preview_required` are false. Control is OrientationCard hash link `#/workbench?tab=scan`, not a scan commit. Cost flags stay on workbench commit actions.

RED proof:
```
FAIL  ... RV-07: act-start-first-scan is a hash navigation, not a costly scan commit
AssertionError: expected 'Start first scan' to be 'Start your first scan'
```

## uxmap-render-parity (dashboard ownership) — not a tautology

OWNED_MAPS includes `dashboard`. Added fail-closed existsSync, absent-file discrimination (`readMapJson('__absent-owned-map__')` throws ENOENT), and malformed-payload schema rejection.

RED when `dashboard.uxmap.json` was moved aside:
```
FAIL  keeps every owned map json and sibling md on disk (fail-closed)
AssertionError: dashboard.uxmap.json is missing — OWNED_MAPS cannot silently skip an absent SSOT: expected false to be true
FAIL  dashboard.uxmap.json validates against the canonical UxMap schema
Error: ENOENT: no such file or directory, open '.../docs/ux-maps/dashboard.uxmap.json'
```

RED when the file was replaced with `{ "map_ref": 1, "not": "a-uxmap" }`:
```
FAIL  dashboard.uxmap.json validates against the canonical UxMap schema
AssertionError: dashboard.uxmap.json: 3 schema errors
  not | extra_forbidden | a-uxmap
  map_ref | string_type | 1
  product | missing | undefined
FAIL  loadOwnedMap: dashboard.uxmap.json fails canonical UxMap schema (3 errors)
```

GREEN: 19 passed / 0 failed.

## Residual risk

- Retention loading / `available:false` still render no panel; map keeps loading/empty states as absence, not a visible empty shell (open question unchanged).
- Degraded `[attention / offline]` tag was unbracketed so it is not mistaken for a control; Sync Health offline is still a summary branch, not a shell.
- `act-reset-mirror` remains costly/preview_required (real mutate). Orientation dismiss and identity Retry are in-page, not exits.
- Handoff DB has no DUX-W2D14 / DEMO-UX-1 task on this worktree (only DUX-W2R1 / DUX-W2R2); findings were not marked fixed in MCP from this lane.
