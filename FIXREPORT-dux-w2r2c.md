# FIXREPORT — lane dux-w2r2c

Base: `5da328f3a893980b4bffd96965e026f6c5c7ff36`
HEAD: `274f73daa4e879be495920c0894a47cf5a064efb`
Branch: `fix/dux-w2r2`

## Suite totals

```
cd apps/prototype-wp-alt-context && npx vitest run \
  js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx \
  js/admin/pages/workbench/identity-clusters/__tests__/useBulkReviewCommit.test.tsx \
  js/admin/pages/workbench/__tests__/mediaFooterSinglePrimary.dom.test.tsx
```

**169 passed / 0 failed** (3 files)

## DUX-W2R2-RV-04 — STATUS: fixed

HAI-17 gate was bypassable on `initiateBulkFromItems` / unmount drain; optional `isApprovalBlocked` failed open; unknown ids allowed.

### RED proof (quoted)

`initiateBulkFromItems` (HEAD before fix):
```
AssertionError: expected [ 'a', 'b' ] to deeply equal []
```

Unmount drain:
```
AssertionError: expected [ 'a' ] to deeply equal []
```

Omitted predicate (fail-open):
```
AssertionError: expected [ 'a', 'b', 'c' ] to deeply equal []
```

Close Match Confirm (`ReviewQueue`):
```
AssertionError: expected "vi.fn()" to not be called at all, but actually been called 3 times
Received: sugg-1, sugg-2, sugg-3
```

### Fix

- `isApprovalBlocked` **required**; runtime missing predicate blocks writes
- Gate `initiateBulk` / `initiateBulkFromItems` / unmount drain / `retryBulk`
- Host + tray: unknown suggestion id → **block** (fail closed)
- All-or-nothing: any blocked item aborts the set

### Commits

- `6234084c` test(admin,DUX-W2R2-RV-04): RED …
- `ad098d63` fix(admin,DUX-W2R2-RV-04): …
- `274f73da` test: close-match seed default `identityCount: 1` (gated case sets 5)

### Residual risk

Timer `fireHeldBulk` path does not re-check the gate mid-hold (only initiate + drain + retry). If approval state flips during an open hold, timer fire could still POST until drain/unmount. Mitigated by tray/initiate gates and fail-closed unknown ids.

## DUX-W2R2-RV-05 — STATUS: fixed

Retry had aria-disabled + describedby but no onClick guard; reason only mounted while tray expanded → dangling describedby when collapsed.

### RED proof (quoted)

```
AssertionError: expected null not to be null
❯ … reasonCollapsed = document.getElementById(reasonId!)
```
(after collapsing selection tray while Retry still referenced the id)

### Fix

- Retry `onClick` returns early when `storedFaceSelectionBlocksCommit`
- Hoist stored-face reason `<p>` outside the expanded panel so it mounts whenever any control references it

### Commits

- `0a1588b9` test(admin,DUX-W2R2-RV-05): RED …
- `cb74b45f` fix(admin,DUX-W2R2-RV-05): …

### Residual risk

Low. Reason is visible even when tray collapsed while gated; acceptable for a11y association.

## Canon cites

- [TEST-15] (`~/heuristics-canon/lexicons/engineering.md#test-15`) — RED before GREEN on each write path
- BR-74 — project control pattern (not in heuristics-canon INDEX); applied as specified

## Handoff

`workbay_handoff_mcp` not importable in this lane shell (`ModuleNotFoundError`). No decision/finding writes recorded.
