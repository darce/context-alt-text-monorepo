# DEMOLIVE-4 round 4 — Sync Health map-to-code parity guard

Lane `demolive-4`. Repair RV-16 after round 2 (`5fc0f7f8f`) inserted `confirmOpen` + `<ConfirmDialog>` and shifted every line below them.

## Edits

Every brief number was verified with `sed -n '<N>p' js/admin/pages/dashboard/DashboardSyncHealthSection.tsx` before writing. **None were wrong.**

`apps/prototype-wp-alt-context/docs/ux-maps/dashboard.md`

Branch chain:

- L263 `:56` → `:61` `isLoading`
- L264 `:58` → `:63` `isError || !syncStatus`
- L265 `:66` → `:71` `else`

Member table (no new row):

- L271 B `:96` → `:152` `acx-dashboard-sync-summary`
- L272 S `:99` → `:155` `acx-dashboard__stats-grid`
- L273 A `:68` → `:73` `showMirrorDivergenceBanner`
- L274 C `:113` → `:169` `topologyPending|Failed|Conflicts>0`
- L275 D1 `:123` → `:179` `conflictCount>0 && lastConflictDate`
- L276 E1 `:126` → `:182` `failedReplayCount>0 && lastFailureDate`
- L277 R `:129` → `:185` `acx-dashboard__actions`
- L278 D2 `:134` → `:190` `conflictCount>0`
- L279 E2 `:140` → `:196` `failedReplayCount>0`

`apps/prototype-wp-alt-context/js/admin/__tests__/dashboard-uxmap-code-parity.test.ts` RV-16 numbers only; semantics unchanged:

- L421 `(c)` `lineAt(96)` → `152` `'acx-dashboard-sync-summary'`
- L422 `(c)` `lineAt(99)` → `155` `'acx-dashboard__stats-grid'`
- L423 `(c)` `lineAt(129)` → `185` `'acx-dashboard__actions'`
- L427 `(d)` `lineAt(123)` → `179` `'conflictCount>0&&lastConflictDate'`
- L428–429 `(d)` `lineAt(134)` → `190` `'conflictCount>0?'` and `.not.toContain('lastConflictDate')`
- L430–431 `(d)` `lineAt(140)` → `196` `'failedReplayCount>0?'` and `.not.toContain('lastFailureDate')`

`DashboardSyncHealthSection.tsx` was not edited in the committed tree.

## Prose claims re-checked

Did **not** add a ConfirmDialog member-table row. The dialog renders unconditionally in the else branch; `open` is local UI state, not a data-driven modifier. Adding it would change the `2 × 2 × 3 × 3 = 36` arithmetic.

Paragraph immediately after the table (`dashboard.md` L281–284):

1. “A recency line and its CTA are gated *separately*: `[Open Conflict Inbox]` needs only `conflictCount > 0`, while `Last conflict:` additionally needs a parsable date.” — **still true.** File: L190 `{conflictCount > 0 ? (` vs L179 `{conflictCount > 0 && lastConflictDate ? (`. Failure pair L196 vs L182 matches.

2. “conflict and failure each have three reachable shapes — absent, CTA only, CTA plus recency line — and together with A and C that is 2 × 2 × 3 × 3 = 36 compositions of this one branch.” — **still true.** ConfirmDialog does not multiply the axis: it is always mounted.

Sentence *before* the table (“Two are unconditional; the rest only *add* to them.”): already slightly loose vs the table’s three unconditionals (B, S, R). Round 2 did not newly falsify the after-table claims; left it alone per do-not-widen-the-table.

## Green suites

From `apps/prototype-wp-alt-context`:

`npm run test -- js/admin/__tests__/dashboard-uxmap-code-parity.test.ts`

```
 Test Files  1 passed (1)
      Tests  9 passed (9)
   Start at  09:40:11
   Duration  1.04s (transform 122ms, setup 256ms, import 120ms, tests 23ms, environment 469ms)
```

Exit 0. After both mutants reverted (09:41:12): same 9 passed, exit 0.

Did not run `js/admin`.

## TEST-15

### M1 — map A-row cite `:73` → `:68`

Command: `npm run test -- js/admin/__tests__/dashboard-uxmap-code-parity.test.ts`

Exit code: `1`

Verbatim assertion:

```
AssertionError: map cites :68 for "showMirrorDivergenceBanner" but that line does not mention showMirrorDivergenceBanner: expected 'action={{label:__(\'Opensettings\',\'…' to contain 'showMirrorDivergenceBanner'

Expected: "showMirrorDivergenceBanner"
Received: "action={{label:__('Opensettings','alt-context'),href:toSettings()}}"

 ❯ js/admin/__tests__/dashboard-uxmap-code-parity.test.ts:417:9
```

Reverted A-row to `:73`.

### M2 — D2 gate L190 `conflictCount > 0 ?` → `conflictCount > 0 && lastConflictDate ?`

Command: `npm run test -- js/admin/__tests__/dashboard-uxmap-code-parity.test.ts`

Exit code: `1`

Verbatim assertion:

```
AssertionError: expected '{conflictCount>0&&lastConflictDate?(' to contain 'conflictCount>0?'

Expected: "conflictCount>0?"
Received: "{conflictCount>0&&lastConflictDate?("

 ❯ js/admin/__tests__/dashboard-uxmap-code-parity.test.ts:428:45
```

Assertion (d) still pins the CTA gate at `:190`. Reverted D2 to `{conflictCount > 0 ? (`.

`git status --short` after both reverts:

```
 M apps/prototype-wp-alt-context/docs/ux-maps/dashboard.md
 M apps/prototype-wp-alt-context/js/admin/__tests__/dashboard-uxmap-code-parity.test.ts
```

`DashboardSyncHealthSection.tsx` is not in the dirty list.

## Could not falsify

- RV-16 (c) still bites a stale A-row cite (`:68`).
- RV-16 (d) still bites a date-gated D2 CTA at `:190`; the `.not.toContain('lastConflictDate')` pin was not reached because the positive `toContain('conflictCount>0?')` failed first, which is the same claim.
- 36-composition arithmetic still holds; ConfirmDialog is not a modifier-axis member.
