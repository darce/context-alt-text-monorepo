# UXW2-3-fix-r7c report

Panel double-submit cases now click a real Confirm-match / Save twice. Enter routing is pinned from the mutation shape. Library overlay header is `People`. PHP untouched.

## Gate

From `apps/prototype-wp-alt-context` after the last code commit:

```
Test Files  211 passed (211)
      Tests  2437 passed (2437)
```

`npm run typecheck` (`tsc --noEmit --project tsconfig.type-check.json`) — exit 0.

PHP not run. No PHP files touched.

## Closure

| Finding | Commit subject | Proving test | Verbatim RED | GREEN |
| --- | --- | --- | --- | --- |
| UXW2-3-R3-21 | `test(fe): UXW2-3-R3-21 pin panel Confirm-match and Save double-submit` | `two rapid Confirm-match clicks fire the bind once (UXW2-3-R3-21)`; `two rapid Save clicks fire the create write once (UXW2-3-R3-21)` | Isolated mutants of `resolveCommit` / `handleOptionConfirm` / `handleSelectOption` stayed GREEN (see §1). `submitLabel` early-return delete: Rename anyway `AssertionError: expected "vi.fn()" to be called 1 times, but got 2 times`. New Confirm-match and Save stayed GREEN on that mutant. | Filter `UXW2-3-R3-21\|two rapid Enter\|two rapid Rename`: `Tests  4 passed \| 44 skipped (48)`. File `Tests  48 passed (48)` |
| UXW2-3-R1-08(a) | `test(fe): UXW2-3-R1-08a pin panel Enter create vs roster routing` | `type + Enter commits the typed name (UXW2-3-R1-08a)`; `type + Enter on a single roster person binds that rosterEntryId (UXW2-3-R1-08a)` | Always-create and `skipPersonOnlyGuard` drop: `AssertionError: expected "vi.fn()" to be called with arguments: [ { …(2) } ]` / `Number of calls: 0` | Filter `UXW2-3-R1-08a\|UXW2-3-R1-08c`: `Tests  3 passed \| 46 skipped (49)` |
| UXW2-3-R1-16(b) | `fix(fe): UXW2-3-R1-16b Library overlay header is People` | `roster-only Library overlay is headed People (UXW2-3-R1-16b)` | `Error: expect(element).toHaveTextContent()` / `Expected element to have text content:` / `  People` / `Received:` / `  Suggested` | File `Tests  31 passed (31)` |
| UXW2-3-R1-16(j)(k) | `docs(uxw2): UXW2-3-R1-16j R1-16k refresh stale plan paragraphs` | n/a | n/a | docs only |
| type fixture | `test(fe): UXW2-3-R1-08a type roster fixture as mutable arrays` | n/a | n/a | `tsc` exit 0 |

Subjects verified with `git log --format=%s --fixed-strings --grep="<subject>"`.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## Design changes to existing assertions

| Test | Was | Now | Why |
| --- | --- | --- | --- |
| `a second checkmark during an in-flight write is ignored (UXW2-3-R3-21)` | `updateClusterLabel` times 1 after Enter + optional missing option | replaced by Confirm-match ×2; `commitClusterToRosterEntry` times 1 with `rosterEntryId: 42` | old body never found an option (`queryByRole` + `if (option)` skip) |
| `a second option selection during an in-flight write is ignored (UXW2-3-R3-21)` | same Enter/Enter tautology | replaced by Save ×2; `updateClusterLabel` times 1; bind not called | cluster row-select does not write; Save is the reachable `resolveCommit` twin |

No other existing assertion changed.

---

## 1. UXW2-3-R3-21 — double-submit on Confirm-match and Save

Guards after last code commit (`sed -n`):

- `submitLabel` — `ClusterLabelingPanel.tsx:359-361`
- `resolveCommit` — `:404-406`
- `handleOptionConfirm` — `:438-440`
- `handleSelectOption` — `:445-447`

`submitLabel` (Enter/Enter) already covered by `two rapid Enter presses fire the mutation once (UXW2-3-R1-04 / R2-02)`.

Shipped R3-21 tests typed `'Pat Rivera'` with an empty roster, then `queryByRole('option')` + `if (option)`. No row existed. They were Enter/Enter again. Deleting `handleOptionConfirm` or `handleSelectOption` left them green.

**Confirm-match ×2.** One person (`Alex Carter` / id 42 — no same-fold twin). Hang `commitClusterToRosterEntry`. Type `Alex`. `findByRole('option', { name: /Confirm match with Alex Carter/i })`, `fireEvent.click` twice inside the existing 80ms `act` harness. Bind called once with `{ clusterId: 'source-cluster-id', rosterEntryId: 42 }`. Person ✓ goes through `NameFaceControl.confirmDisplayedOption` → `onCommit` → `resolveCommit`, not `handleOptionConfirm`.

**Save ×2.** Novel `'Pat Rivera'`. Hang `updateClusterLabel`. Two `fireEvent.click` on `button` name `Save name` (panel passes that `commitLabel` explicitly; assertion is on the mutation, not sibling-lane button copy). Create write once. Path is `handleSaveClick` → `commitValue` → `onCommit` → `resolveCommit`.

**Dropped: cluster option-select ×2.** `handleOptionConfirm` only forwards non-person rows to `handleSelectOption`. That path primes `setDuplicateGuard` (`:456-480`) and never writes. Same click target as Confirm-match (`role="option"`). No second row-select affordance in the rendered DOM. A write-count case cannot go RED if those handlers lose their latch. Did not poke `submittingRef` from the test.

### TEST-15 mutants (one handler each, restored)

Delete `if (submittingRef.current || isBusy) { return; }` only.

| Mutant | Confirm-match ×2 | Save ×2 | Enter/Enter | Rename anyway |
| --- | --- | --- | --- | --- |
| `resolveCommit` | GREEN | GREEN | GREEN | GREEN |
| `handleOptionConfirm` | GREEN | GREEN | GREEN | GREEN |
| `handleSelectOption` | GREEN | GREEN | GREEN | GREEN |
| `submitLabel` (control) | GREEN | GREEN | GREEN | **RED** |

`resolveCommit` and `submitLabel` are stacked. Second Enter/Save/✓ hits whichever latch is still present. Isolated delete of `resolveCommit` cannot make a write-count case RED. Isolated delete of `submitLabel` still leaves `resolveCommit` to catch those three; only Rename anyway (calls `submitLabel` directly) goes RED:

```
AssertionError: expected "vi.fn()" to be called 1 times, but got 2 times
```

Restore: `git diff` on `ClusterLabelingPanel.tsx` empty. File `Tests  48 passed (48)` after the R3-21 commit.

UX map: no new zone/state. Write-latch tests only.

---

## 2. UXW2-3-R1-08(a) — Enter routing

Finding claimed the suite had **zero** Enter keypresses. `git grep -n "Enter" -- <the test file>` at lane start: **14** hits. Not only the placeholder (`:702` now). Real `{Enter}` / `key: 'Enter'` already existed (R1-08a/c, R1-12, Enter/Enter). After this lane: **12** hits (inert R3-21 Enters removed; typed-roster Enter added).

`resolveCommit` already reads `resolution.kind` (`:414-419`): roster + no cluster collision → `skipPersonOnlyGuard: true` + `rosterEntryId`; else create/label with optional id.

Named case `typing an existing roster name + Enter commits with rosterEntryId` was **not** in the file. Closest was `prefilled roster name + Enter binds via the label write (UXW2-3-R1-08c)` — that is (2) via prefill, not type-then-Enter. Added the type-then-Enter case. Spent the rest on (1) + mutants.

1. Novel `'Pat Rivera'` (nothing in options folds to it) + Enter → `updateClusterLabel(..., 'Pat Rivera', ...)`. `commitClusterToRosterEntry` not called. No `rosterEntryId` on the write.
2. Type `'Alex Carter'` (single person option, id 42) + Enter → `commitClusterToRosterEntry({ clusterId: 'source-cluster-id', rosterEntryId: 42 })`. `updateClusterLabel` not called. `already exists` absent.

Routing asserted from the mutation call shape, not the typed string.

### TEST-15 mutant 1 — ignore `resolution.kind`, always create

`resolveCommit` body replaced with `void submitLabel(resolution.name);`.

- (1) novel Enter stayed GREEN.
- (2) typed roster Enter and R1-08c went RED:

```
AssertionError: expected "vi.fn()" to be called with arguments: [ { …(2) } ]

Number of calls: 0
```

Person-only collision armed the duplicate guard (`A name matching "Alex Carter" already exists`). Restore.

### TEST-15 mutant 2 — drop `skipPersonOnlyGuard`

Roster branch became `void submitLabel(resolution.name, { rosterEntryId });`.

Same two tests RED, same verbatim:

```
AssertionError: expected "vi.fn()" to be called with arguments: [ { …(2) } ]

Number of calls: 0
```

Already pinned by R1-08c and the new type-then-Enter (`already exists` must stay absent). Did not add a third assertion. Restore. `git diff` on the panel empty.

GREEN: `Tests  3 passed | 46 skipped (49)`.

---

## 3. UXW2-3-R1-16(b) — Library overlay header

`ClusterEditForm` did not pass `suggestionsHeader`. Default in `NameFaceControl` is `Suggested`. Queue card already passes `People` (`PersonCommitControl.tsx:202`). Did not edit `NameFaceControl.tsx`.

`ClusterEditForm.tsx:189`: `suggestionsHeader={__('People', 'alt-context')}`.

Pin: roster-only option `{ value: 'person:42', label: 'Pat Roster' }`, input `Pat`, header `.acx-identity-cluster__suggestions-header` is `People`. `Suggested` absent.

TEST-06 RED (assertion present, prop absent) and TEST-15 mutant (prop removed) are the same:

```
Error: expect(element).toHaveTextContent()

Expected element to have text content:
  People
Received:
  Suggested
```

Restore. File `Tests  31 passed (31)`.

No new zone/state. Overlay heading copy only. `docs/ux-maps/**` not edited (lane forbidden). `act-name-cluster` already says `Save name (NameFaceControl)`; it does not name the overlay heading.

---

## 4. UXW2-3-R1-16(j) and (k) — planning docs

**(j)** `git grep -n "label-only rename" -- docs` does not hit E21-5 (lowercase). Case-insensitive hit: `docs/tasks/21.0/E21-5-unified-review-queue-task-plan.md:124` — contract row `Label-only rename` / `demoted to tertiary "just label" action`.

Rewrote that row only. Shipped behaviour: person-row confirm binds via `commitClusterToRosterEntry`; the label string is written only on the explicit rename path. Did not rewrite Problem Statement, G2, or later “just label” narrative.

**(k)** UXW2-3 plan (`docs/tasks/uxw2/UXW2-3-one-naming-surface-task-plan.md`) slices 1–3 were already `[x]`. This mirror’s `git log` has no slice-delivery subjects (only the u3 base + this lane). Left them checked and put the slice-heading subject in each item body as the evidence anchor. Left the E21-5 Success Criteria / operator-gate rows unchecked (no delivered subject in this clone). No finding-id trailers. No finding list.

---

## Undone

- `handleOptionConfirm` (`ClusterLabelingPanel.tsx:438`) and `handleSelectOption` (`:445`) still have unused write-latch early returns. They do not write. A DOM test cannot make those mutants RED. Follow-up: delete the dead latches, or give cluster-row confirm a write and pin it.
- Isolated `resolveCommit` mutant stays GREEN because `submitLabel` is stacked immediately under it. Unstacking (one latch, one handler) is a production edit this lane does not own.
- Queue-card Confirm-match + prefill-roster Enter (R1-08 remains on `PersonCommitControl`) not in this lane. Sibling owns that file.
- E21-5 Problem Statement (`:27`) and later “just label” / tertiary narrative still describe the old world. Only the contract-table row was rewritten.
- UXW2-3 slice evidence subjects are the plan headings, not `git log` hits on this throwaway clone. Integrator can replace them with the transplanted subjects if they differ.
- `docs/ux-maps/**` not updated for the Library `People` header (forbidden). If a follow-up owns the map, add the overlay heading to the Library naming zone.
- Handoff MCP / `workbay_handoff_mcp` Python package unavailable in this throwaway mirror. No `record_event`. This report is the lane record.
