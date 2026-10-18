# UXW2-3-fix-r7f report

Commits by subject. PHP untouched. No 40-hex SHAs.

## Gate

From `apps/prototype-wp-alt-context` at the last code commit:

```
Test Files  1 failed | 210 passed (211)
      Tests  1 failed | 2447 passed (2448)
```

`npm run typecheck` (`tsc --noEmit --project tsconfig.type-check.json`) — exit 0.

The one red test is out of lane: `mediaFooterSinglePrimary.dom.test.tsx` still queries `PERSON_COMMIT_CONFIRM_COPY` (`Save name`) on a CLUSTER card whose field is prefilled `Alex`. Queue-card preview makes that button `Create person "Alex"`. See Undone.

Subjects verified with `git log --format=%s --fixed-strings --grep="<subject>"` (one hit each).

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## Closure table

| Finding | Commit subject | Proving test | Verbatim RED | GREEN |
| --- | --- | --- | --- | --- |
| UXW2-3-R1-07 residual A | `fix(fe): UXW2-3-R1-07 preview create-vs-bind on commit button` + `fix(fe): UXW2-3-R1-07 queue-card previewCommit and ComboboxOption map` | `exact roster match previews Save as the option label` | `Unable to find an accessible element with the role "button" and name "Save as Ada Lovelace"` (button was `Save name`) | 31 passed in NameFaceControl file after restore |
| UXW2-3-R1-07 residual A (same-fold) | same | `two same-fold entries keep commitLabel and do not claim a bind` | `Unable to find an accessible element with the role "button" and name "Save name"` (mutant-2 button was `Save as Alex Carter`) | same file green |
| UXW2-3-R1-07 residual B | `fix(fe): UXW2-3-R1-07 feed PersonCommitControl from buildNamingOptions` | `omits whitespace-only roster names via buildNamingOptions (UXW2-3-R1-07)` | `expected [ <div …(6)>…(4)</div>, …(1) ] to have a length of 1 but got 2` | PersonCommitControl file 24 passed |
| UXW2-3-R1-16b (header) | same | `defaults the overlay header to People when no Suggested group is present (UXW2-3-R1-16b)` | `Unable to find an element with the text: People` (header was `Suggested`) | NameFaceControl file green |
| UXW2-3-R1-08b case 1 | `test(fe): UXW2-3-R1-08b live Confirm match and prefill-roster bind` | `clicking Confirm match on a visible roster row binds rosterEntryId (UXW2-3-R1-08b)` | `expected "vi.fn()" to be called with arguments: [ { clusterId: 'cluster-1', …(1) } ]` / `Number of calls: 0` | already green on unmutated tree; mutant restored |
| UXW2-3-R1-08b case 2 | same | `prefill that matches a roster entry + Enter binds rosterEntryId, not a create (UXW2-3-R1-08b)` | `rosterEntryId: 42` expected, received `newEntryName: "Alex Carter"` | already green on unmutated tree; id-recovery mutant restored |

## Design changes to existing assertions

| Test | Was | Now | Why |
| --- | --- | --- | --- |
| `Save name button commits a novel name` | `getByRole('button', { name: PERSON_COMMIT_CONFIRM_COPY })` | `Create person "Pat Rivera"` | Queue card opts into preview; typed novel name is a create |
| `reserved name via Save name button rejects` | `PERSON_COMMIT_CONFIRM_COPY` | `Create person "cluster-7"` | same |
| `create name is trimmed before the reserved gate` | `PERSON_COMMIT_CONFIRM_COPY` | `Create person "cluster-7"` | preview uses `resolution.name` (trimmed) |
| `valid name Pat Rivera proceeds to onCommit (control)` | `PERSON_COMMIT_CONFIRM_COPY` | `Create person "Pat Rivera"` | same |
| `reserved error clears when the draft is edited after a reject` | `PERSON_COMMIT_CONFIRM_COPY` | `Create person "cluster-7"` | same |

No assertion deleted. `PERSON_COMMIT_CONFIRM_COPY` import dropped from `PersonCommitControl.test.tsx` because nothing queries the static copy after a non-empty draft.

## 1. UXW2-3-R1-07 residual A — create-vs-bind preview

`NameFaceControl.tsx:279-303` derives `commitButtonLabel` from the same `resolveNameFaceInput(options, value)` the commit path uses (`:283-284`). No second resolver.

- `kind === 'roster'` → `Save as %s` (`:287-292`)
- `kind === 'create'` → `Create person "%s"` (`:294-299`)
- `kind === 'ambiguous'` / `null` → `commitLabel` (`:301`)
- `pendingLabel` still wins while `isPending` (`:284-286`)

`previewCommit` (`:180`, default `false` at `:220`) gates the derived copy. Library / labeling-panel callers keep passing `commitLabel` / `pendingLabel` and stay on that static text. `PersonCommitControl.tsx:202` passes `previewCommit` so the queue card is the surface that shows the preview.

Live region (`:619-621`) already announces `commitButtonLabel` only while `isPending` (`:314-315`). Pending wins, so the idle preview is not double-announced. No second live region.

**Mutant 1** — preview always returns `commitLabel`. Filter `-t 'exact roster match previews Save as'`:

```
TestingLibraryElementError: Unable to find an accessible element with the role "button" and name "Save as Ada Lovelace"
```

Button name received: `Save name`. Restored.

**Mutant 2** — preview via `options.find(o => o.label === value)` instead of `resolveNameFaceInput`. Filter `-t 'two same-fold entries keep commitLabel'`:

```
TestingLibraryElementError: Unable to find an accessible element with the role "button" and name "Save name"
```

Button name received: `Save as Alex Carter` while the status still said `Multiple people match. Choose one.` Restored.

## 2. UXW2-3-R1-07 residual B — one options pipeline

`buildNamingOptions` signature (`buildNamingOptions.ts:41-50`, impl `:136-142`):

```
readonly rosterEntries: readonly RosterNamingEntry[];
readonly labelMatches: readonly ClusterNamingEntry[];
readonly filter?: string;
readonly limit?: number | null;
readonly excludeClusterId?: string | null;
```

`labelMatches` is required. The queue card has no cluster/similarity source. Called with `labelMatches: []` and `limit: null` (`PersonCommitControl.tsx:90-103`) so the helper does not fabricate scores, does not fetch, and does not slice the roster (clause 4). Rows are mapped `{ value, label, source }` so `NamingOption` satisfies `ComboboxOption`.

`namingOptionValue('person', id)` still round-trips through `parseNamingOptionValue` inside `resolveNameFaceInput` (`NameFaceControl.tsx:110-115`).

Helper does not set `group`. Overlay header on this surface stays `People` via `suggestionsHeader` (`PersonCommitControl.tsx:209`). Default in `NameFaceControl.tsx:525` is now content-derived (`:480-484`): `Suggested` only when a displayed row has `group === NAMING_GROUP_SUGGESTED`, else `People`. That is the NameFaceControl half of R1-16b.

No labelled-group row is offered here. That would need cluster data this control does not have.

**Mutant** — revert to the roster-only mapper. Filter `-t 'omits whitespace-only'`:

```
AssertionError: expected [ <div …(6)>…(4)</div>, …(1) ] to have a length of 1 but got 2
```

Restored. Header-default mutant (hardcoded `Suggested`) separately redded `defaults the overlay header to People` with `Unable to find an element with the text: People`. Restored.

## 3. UXW2-3-R1-08b — live check-click / prefill-roster

`PersonCommitControl` still passes no `onOptionConfirm`. Person rows go through `confirmDisplayedOption` (`NameFaceControl.tsx:344-362`).

Case 1 (`PersonCommitControl.test.tsx:180`) — overlay open, click `Confirm match with Alex Carter` → `{ clusterId, rosterEntryId: 42 }`, not `newEntryName`. **Already green on the unmutated tree.**

**Mutant** — person branch replaced with `onValueChange(option.label)`:

```
AssertionError: expected "vi.fn()" to be called with arguments: [ { clusterId: 'cluster-1', …(1) } ]

Number of calls: 0
```

Restored.

Case 2 (`:196`) — `suggestedCreateName='Alex Carter'` + roster `(42, 'Alex Carter')` + Enter → `rosterEntryId: 42`. **Already green on the unmutated tree** via `commitValue` → `resolveNameFaceInput` (activeIndex stays `-1`, so Enter does not go through `confirmDisplayedOption`).

**Mutant** — drop `parseNamingOptionValue` id recovery in `resolveNameFaceInput` (`Number.parseInt('', 10)`):

```
-     "rosterEntryId": 42,
+     "newEntryName": "Alex Carter",
```

Restored.

## Already-closed R1-07 clauses

Re-derived with `sed -n` after the last code commit. Not re-implemented.

### 1. NFC normalize — proven

`normalizeNameFaceLabel` (`NameFaceControl.tsx:30-31`) and `resolveNameFaceInput` (`:100`) both `raw.normalize('NFC')`.

**Mutant:** strip both NFC calls. Test `normalises NFC + case + whitespace before comparing` (`NameFaceControl.test.tsx:146`):

```
AssertionError: expected 'café' to be 'café' // Object.is equality

Expected: "café"
Received: "café"
```

Restored.

### 2. Multi-match is ambiguous — proven

`matches.length > 1` → `{ kind: 'ambiguous' }` (`:107-109`). `commitValue` returns on it (`:336-337`).

**Mutant:** treat `matches.length >= 1` as a bind (first id). Test `forces an explicit choice when two roster people fold to the same name` (`:274`):

```
AssertionError: expected "vi.fn()" to not be called at all, but actually been called 1 times
```

Received `{ kind: 'roster', name: 'Alex Carter', rosterEntryId: 1 }`. Restored.

### 3. `includes`, not `startsWith` — unproven until this lane

`matchingOptionsFor` (`:141-149`) filters with `.includes(folded)`.

**Mutant:** `.startsWith(folded)`. Existing test `typed Zed shows Zed Offslice; typed Gra does not` (`:162`) **stayed GREEN** — both queries are prefix/non-match, so they do not distinguish `includes` from `startsWith`.

Added `typed Hopper (mid-label) shows Grace Hopper (UXW2-3-R1-07 includes)` (`:157`). Same mutant:

```
TestingLibraryElementError: Unable to find an accessible element with the role "option" and name `/Grace Hopper/`
```

Restored. Clause 3 is now proven.

### 4. Full roster vs overlay budget — proven

`PersonCommitControl.tsx:90-103` feeds the full helper result (`limit: null`). Overlay still budgets display.

**Mutant:** `resolveNameFaceInput` matches against `budgetOverlayOptions(options)` instead of the full list. Test `binds a roster person who fell outside the unfiltered display budget` (`:184`):

```
-     "kind": "roster",
-     "name": "Zed Offslice",
-     "rosterEntryId": 99,
+     "kind": "create",
+     "name": "zed offslice",
```

Restored.

### 5. Enter confirms the active row — proven

`handleKeyDown` `'Enter'` (`:439-448`) → `confirmDisplayedOption(displayedOptions[activeIndex])` when `activeIndex >= 0`.

**Mutant:** Enter always `commitValue(value)`. Test `type Gra, ArrowDown, Enter binds Grace and never a non-match` (`:212`):

```
-     "kind": "roster",
-     "name": "Grace Hopper",
-     "rosterEntryId": 2,
+     "kind": "create",
+     "name": "Gra",
```

Restored.

## PHP

Untouched. No PHP files in this lane.

## UX maps

Not edited. Forbidden for this lane. Queue-card button copy is now state-dependent (`Save name` / `Save as <label>` / `Create person "<value>"`) when `previewCommit` is on. A follow-up that owns `docs/ux-maps/**` should add those commit-button states.

## Undone

- `mediaFooterSinglePrimary.dom.test.tsx:407` still does `findByRole('button', { name: PERSON_COMMIT_CONFIRM_COPY })` on a CLUSTER card with `suggested_label: 'Alex'`. After this lane the button reads `Create person "Alex"`. That file is out of lane. Follow-up: change the query to `Create person "Alex"` (or `/Create person/`). That is the only remaining FE red (`1 failed | 2447 passed`).
- `ClusterLabelingPanel` and `ClusterEditForm` do not pass `previewCommit`. Their commit button stays the static `commitLabel`. They cannot opt in from this lane (sibling owns those files). Follow-up: pass `previewCommit` there after updating their `Save name` queries.
- Queue card cannot offer labelled-group rows. `buildNamingOptions` requires `labelMatches` (`buildNamingOptions.ts:42`); this control has no cluster list, so it passes `[]`. Do not fabricate similarity or add a fetch.
- `buildNamingOptions` person-preferred case-insensitive dedupe collapses two same-fold roster people to the first id. `resolveNameFaceInput` still returns `ambiguous` when both options are fed; the queue card no longer feeds both. Follow-up: a helper flag to keep person-person duplicates, or accept the shared-pipeline collapse.
- When `previewCommit` is on and a row is arrow-active, the button still previews `resolveNameFaceInput(value)` (e.g. `Create person "Gra"`) but Save/Enter confirms the active row (`Grace Hopper`). Spec required one resolver, not a second active-row preview. Residual COG-02 disagreement.
- `previewCommit` default is `false` so Library R1-16i `/^Save name$/` pins stay green. A later lane can flip the default once every `Save name` query that runs against a non-empty draft is updated.
- Handoff MCP / `workbay_handoff_mcp` Python package unavailable in this throwaway mirror. No `record_event`. This report is the lane record.
