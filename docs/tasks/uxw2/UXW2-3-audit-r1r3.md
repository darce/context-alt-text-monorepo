# UXW2-3 board audit — R1/R3 leftovers

Read-only re-check of six leftover findings against this tree. Line numbers below are from the files as they sit now, not from the filing commits.

| Finding | Verdict | One-line reason |
|---|---|---|
| UXW2-3-R1-02 | PARTIAL | Race + degraded notice + panel roster invalidation are closed; Library `useClusterMutations` still omits `roster.entries()`. |
| UXW2-3-R1-07 | PARTIAL | NFC / ambiguous-refuse / includes-filter / full-options resolve are closed; queue card is still roster-only and the button never previews Create vs Save-as. |
| UXW2-3-R1-08 | PARTIAL | Panel Enter + person-row check-click exist; queue-card Confirm-match and prefill-matches-roster are still untested, and novel-name Enter does not pin `resolution.kind`. |
| UXW2-3-R1-16 | PARTIAL | 8/11 letters closed; survivors are (b) header, (h) heading stub, (i) Save vs Save name. |
| UXW2-3-R3-12 | PARTIAL | Person rows now emit `rosterEntryId` even with `onOptionConfirm`; panel and Library still write a string and drop the id. |
| UXW2-3-R3-21 | PARTIAL | Enter/Enter and Rename-anyway are pinned; the two checkmark tests never click an option, and Save is untested. |

## Tally

FIXED: 0 | PARTIAL: 6 | OPEN: 0 | STALE-PREMISE: 0 | UNKNOWN: 0

---

## UXW2-3-R1-02 — PARTIAL

Assertions:

1. `rosterQuery.isLoading` / `isError` never read — **closed** at `PersonCommitControl.tsx:115` and `:164`.

```
if (isBusy || rosterQuery.isLoading || rosterQuery.isError) {
  return;
}
```

```
{rosterQuery.isError ? (
  <div className="acx-person-commit__failure" role="alert">
    <p className="acx-person-commit__failure-message">
      {__('Unable to load people. Retry before naming someone new.', 'alt-context')}
```

2. Type an existing name and Save before the query settles (or after error) → `{kind:'create'}` duplicate — **closed**. Commit is gated above; `NameFaceControl` also disables the input while `isLoading` (`NameFaceControl.tsx:236-237`, `:302-304`) and the error branch unmounts the control (`PersonCommitControl.tsx:188`).

3. No degraded-state notice (contrast panel `'People list unavailable'`) — **closed**. Copy is now `'Unable to load people. Retry before naming someone new.'` with Retry (`PersonCommitControl.tsx:164-178`). Panel uses the same sentence (`ClusterLabelingPanel.tsx:599-614`).

4. Live region says `'0 naming options'` while loading — **closed**. Loading announcement is exclusive:

```
if (isLoading) {
  return __('Loading people…', 'alt-context');
}
```

at `NameFaceControl.tsx:280-282`. Wired as `isLoading={rosterQuery.isLoading}` at `PersonCommitControl.tsx:187`.

5. Label/rename success never invalidates `queryKeys.roster.entries()` (staleTime 30s) via the `invalidateSuggestionProjection` seam — **not fully closed**.

Closed on the panel label path:

```
void queryClient.invalidateQueries({ queryKey: queryKeys.roster.entries() });
void invalidateSuggestionProjection(queryClient);
```

at `ClusterLabelingPanel.tsx:141-142` (`handleLabelSuccess`). Presence-asserted by `'successful label invalidates roster.entries (UXW2-3-R2-04)'` (`ClusterLabelingPanel.test.tsx:1317-1325`). Queue-card success also invalidates (`PersonCommitControl.tsx:77-82`; test `:289-308`).

Still open: Library rename. `useClusterMutations.ts:50-57` still has no `roster.entries()` key:

```
const invalidateQueries = useCallback(() => {
  void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
  void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.labels() });
  void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
  void invalidateSuggestionProjection(queryClient);
  void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.mergePending() });
}, [queryClient]);
```

The seam itself (`suggestionProjection.ts:320-323`) still invalidates only `queryKeys.suggestions.projection.all`. A person created through Library write-through stays invisible to the queue-card matcher until `staleTime` 30s elapses.

6. Tests hide the race by `await findByText` before typing — **partially closed**. The original bind test still waits (`PersonCommitControl.test.tsx:91-92`). A dedicated suite exists (`:245-313`): loading pins `Loading people…` + disabled combobox; error pins the alert and hidden combobox. That would go red if `isLoading` were not passed. Residual: no test actually attempts commit during load and asserts `onCommit` is not called with `newEntryName` (the RED named in the filing). Input-disabled is a stronger user-visible pin of the same race; I do not treat that residual as keeping the race open.

**Remains for a fix lane:** add `queryKeys.roster.entries()` to `useClusterMutations.invalidateQueries` (or fold it into `invalidateSuggestionProjection` with a presence assert). Optional: a commit-during-load `onCommit` assertion.

---

## UXW2-3-R1-07 — PARTIAL

Assertions:

1. Queue card builds options with `startsWith` over roster only, not `buildNamingOptions(roster + labelled groups + similarity)` — **not closed**. `PersonCommitControl.tsx:84-93` still maps the roster only (`namingOptionValue`, no `buildNamingOptions`, no labelled groups, no similarity). Overlay filter moved into the shared control (see 3).

2. `resolveNameFaceInput` binds on `trim().toLowerCase()`, no Unicode normalisation, `options.find` first match — **closed**.

```
export const normalizeNameFaceLabel = (raw: string): string =>
  raw.normalize('NFC').replace(/\s+/g, ' ').trim().toLocaleLowerCase();
```

(`NameFaceControl.tsx:30-31`.) Resolve uses the full fed list, unique person match, two-or-more → `ambiguous` (`:96-117`). Pinned: `'normalises NFC + case + whitespace'` and `'forces an explicit choice when two roster people fold to the same name'` (`NameFaceControl.test.tsx:142-152`, `:266-275`).

3. Overlay can show `'Alex Carter'` while Enter creates `'Alex'` because there is no highlighted row / no arrow-select — **closed as the E21-5-BR-35 create-on-substring path, with arrow-select now present**. Filter is `includes` on the folded label (`matchingOptionsFor`, `:141-150`). Enter with `activeIndex >= 0` confirms the active row (`:409-418`). Without a highlight, Enter still creates the typed string — that is the create-on-substring affordance the filing asked to keep. Pinned: `'type Gra, ArrowDown, Enter binds Grace'` (`NameFaceControl.test.tsx:204-218`).

4. NFD vs NFC duplicate — **closed** (assertion 2).

5. Two case-only entries bind arbitrarily — **closed** (`ambiguous`; Save disabled while ambiguous, `:594`).

6. One `buildNamingOptions(+similarity)` helper feeding all three surfaces; drop the roster-only mapper — **not closed**. Panel uses `buildNamingOptions` (`ClusterLabelingPanel.tsx:212-225`). Queue card does not (assertion 1).

7. Preview `'Create person <name>'` vs `'Save as <existing>'` on the primary button — **not closed**. All three surfaces keep a static commit label (`Save name` / `Save`). Grep finds no `Create person` / `Save as` copy.

**Remains:** either feed the queue card through `buildNamingOptions` (plus similarity) or record a deliberate roster-only exception; add Create vs Save-as button copy if that preview is still wanted.

---

## UXW2-3-R1-08 — PARTIAL

Assertions:

1. Panel suite has zero Enter keypresses; `onCommit` discards `resolution.kind`, so `resolveNameFaceInput` always returning `{kind:'create'}` keeps every panel test green — **partially closed**.

Enter tests now exist:

- `'type + Enter commits the typed name (UXW2-3-R1-08a)'` (`ClusterLabelingPanel.test.tsx:978-985`) — novel name `'Pat Rivera'` → `updateClusterLabel(..., 'Pat Rivera')`. Create and roster both call `submitLabel(resolution.name)` (`ClusterLabelingPanel.tsx:389-393`), so this would **stay green** if resolve always returned `create`. Tautology for kind-routing.
- `'prefilled roster name + Enter binds via the label write (UXW2-3-R1-08c)'` (`:1009-1055`) — **does have kill power**. Roster kind takes `skipPersonOnlyGuard: true`; a forced-create path would arm the person-only duplicate guard and skip the write. `already exists` must stay absent.

2. `PersonCommitControl.test.tsx` has no Confirm-match / `role=option` click, so breaking `handleConfirmOptionClick` keeps the queue-card suite green — **not closed at the queue-card suite**. The file still has no `Confirm match` / option click. Control-level coverage lives in `NameFaceControl.test.tsx` (`:221-240`, person `onCommit` with `rosterEntryId: 2`). Panel check-click is `'confirm on a person row writes a bind (UXW2-3-R2-07)'` (`ClusterLabelingPanel.test.tsx:1057-1087`). The live queue-card path (`PersonCommitControl` passes no `onOptionConfirm`; person rows go through `confirmDisplayedOption` → `onCommit`) is not integration-tested.

3. Prefill matching a roster entry + Enter → `{rosterEntryId}`, not `newEntryName` — **closed on the panel** (R1-08c). **Not closed on the queue card.** `PersonCommitControl.test.tsx:159-171` prefills the novel name `'Pat Rivera'` and expects `newEntryName`. There is no `suggestedCreateName='Alex Carter'` + `rosterEntry(42,'Alex Carter')` case.

**Remains:**

- Queue-card: click Confirm match on `'Alex Carter'` → `onCommit({rosterEntryId:42})`.
- Queue-card: prefill exact roster name + Enter → `{rosterEntryId:42}`, not `newEntryName`.
- Panel R1-08a: assert kind-routing (roster vs create), not only the typed string.

---

## UXW2-3-R1-16 — PARTIAL

| Letter | Verdict | One-line |
|---|---|---|
| (a) | FIXED | No `<form>`; Enter is the control's only submit path. |
| (b) | OPEN | Header is configurable but still `'Suggested'` over All-Labels / roster rows. |
| (c) | FIXED | Default prefix has CSS; mixin applied to every live prefix. |
| (d) | FIXED | Queue card has a visible `<label htmlFor>`; panel omits `ariaLabel`. |
| (e) | FIXED | Success link uses `toRosterPerson(uuid)` when known. |
| (f) | FIXED | `isLoading={rosterLoading}` and `searchPlaceholder` restored. |
| (g) | FIXED | Read-only `TopClusterCard` no longer takes `onLabel`; curate is live on the person-commit control. |
| (h) | OPEN | Heading test still does not stub `fetchClusterMembers`. |
| (i) | OPEN | Library default commit label is still `'Save'`. |
| (j) | FIXED | E21-5 terminology now describes write-through, not label-only. |
| (k) | FIXED | UXW2-3 slice checklist is ticked. |

### (a) FIXED

`ClusterLabelingPanel.tsx` has no `<form>` / `onSubmit`. Wrapper is a class-named div (`:598`). Pinned: `'does not wrap naming in a form (UXW2-3-R1-16a)'` (`ClusterLabelingPanel.test.tsx:1089-1092`).

### (b) OPEN

Proposed: `'Suggested'` only when a `NAMING_GROUP_SUGGESTED` row is present, else `'People'`.

`NameFaceControl.tsx:488-490` still defaults to `'Suggested'`. Panel empty state forces it even though every option is tagged `NAMING_GROUP_ALL_LABELS` (`ClusterLabelingPanel.tsx:227-236`, `:636-640`):

```
suggestionsHeader={
  labelInput.trim()
    ? __('Matches', 'alt-context')
    : __('Suggested', 'alt-context')
}
```

The named test **pins the defect**: `'uses a per-state suggestions header (UXW2-3-R1-16b)'` (`ClusterLabelingPanel.test.tsx:1094-1121`) expects `'Suggested'` with a roster-only Ada row and empty input. Queue card does pass `'People'` (`PersonCommitControl.tsx:198`) — that surface only.

### (c) FIXED

`classPrefix` still defaults to `'acx-name-face'` (`NameFaceControl.tsx:224`) but `_name-face.scss:131-140` now compiles that prefix, plus panel and person-commit. Library include: `_identity-cluster-list.scss:126` inside `.acx-identity-cluster`. Source pin: `name-face-surface.test.ts:64-68` expects three `@include`s in `_name-face.scss` plus the list include.

### (d) FIXED

Queue card: `visibleLabel` + `inputId` (`PersonCommitControl.tsx:193-195`) → `<label htmlFor>` (`NameFaceControl.tsx:452-456`). Test: `'the name input has a visible associated label (UXW2-3-R3-26)'` (`PersonCommitControl.test.tsx:137-141`). Panel: external `<label htmlFor="cluster-label-input">` (`ClusterLabelingPanel.tsx:617`) and no `ariaLabel` on the control. Residual: queue card still also sets `ariaLabel` to the same string; not the missing-label defect.

### (e) FIXED

```
export const viewInRosterHref = (personUuid?: string | null): string =>
  personUuid ? toRosterPerson(personUuid) : toRoster();
```

(`personCommitCopy.ts:19-20`.) Success href uses `boundPersonUuid` (`PersonCommitControl.tsx:144-146`). Test: `:309-312` expects `'#/roster?person=person-uuid-42'`.

### (f) FIXED

`isLoading={rosterLoading}` and `searchPlaceholder={__('Enter name...', 'alt-context')}` (`ClusterLabelingPanel.tsx:625, 633`). Control announces `'Loading people…'` and disables the input (`NameFaceControl.tsx:280-282, 433-437`).

### (g) FIXED

CLUSTER card:

```
<TopClusterCard
  cluster={cluster}
  isReadOnly
  onReview={onReview}
```

(`ReviewQueue.tsx:1911-1915`) — no `onLabel`. `onLabel` is `onCurateGroup` on `PersonCommitControl` (`:1688`), which renders `'Merge or split this group'`. `TopClusterCard` still *accepts* `onLabel` but the read-only title is a `<span>` (`TopClusterCard.tsx:181-193`).

### (h) OPEN

```
it('headline uses plain language: Review these faces (UXW2-3 / NAV-13)', async () => {
  renderPanel();
  expect(
    await screen.findByRole('heading', { level: 2, name: 'Review these faces' }),
  ).toBeInTheDocument();
});
```

(`ClusterReviewPanel.test.tsx:258-264`.) `fetchClusterMembers` is `vi.fn()` with no `mockResolvedValue` here; later tests stub `makeClusterMembersResponse(...)`. Heading is rendered unconditionally (`ClusterReviewPanel.tsx:116`), so the name assertion can go green while `queryFn` still returns `undefined`. Proposed stub was never added. Vitest was not run in this checkout (see Undone).

### (i) OPEN

Proposed: `'Save name'` / `'Saving name…'` on all three surfaces.

| Surface | Idle | Pending |
|---|---|---|
| Queue card | `Save name` (`PersonCommitControl.tsx:189`) | `Saving name…` (`:190`) |
| Panel | `Save name` (`ClusterLabelingPanel.tsx:628`) | `Saving...` / `Merging...` (`:629-631`) |
| Library | `saveLabel ?? 'Save'` (`ClusterEditForm.tsx:80`) | `Saving…` |

`IdentityClusterItem.tsx:289-301` returns `undefined` unless queued/saved/matched, so the Library default is `'Save'`.

### (j) FIXED

E21-5 terminology (`docs/tasks/21.0/E21-5-unified-review-queue-task-plan.md`, Person-commit bullet) now says a successful label `PATCH` also create/binds a roster person (E21-9) and there is no label-only path. The Current State "Person-commit vs label write-through" block describes the shared `NameFaceControl` and write-through, not "label-only rename with no roster person".

### (k) FIXED

`docs/tasks/uxw2/UXW2-3-one-naming-surface-task-plan.md` slices 1–3 are `[x]`. Work checklist only; no finding-status trailers.

**Remains:** (b) derive overlay header from `NAMING_GROUP_SUGGESTED` presence (and stop pinning `'Suggested'` over roster-only rows); (h) stub members before the heading test; (i) `'Save name'` / `'Saving name…'` on Library (and panel pending, if that copy is in scope).

---

## UXW2-3-R3-12 — PARTIAL

Assertions:

1. `NameFaceControl` returns immediately when `onOptionConfirm` exists, so only `PersonCommitControl` (no override) keeps the roster id — **closed for person rows**. Person source now binds via `onCommit` *before* the override:

```
if (optionSource(option) === 'person') {
  const parsed = parseNamingOptionValue(String(option.value));
  const rosterEntryId = Number.parseInt(parsed?.id ?? '', 10);
  if (Number.isFinite(rosterEntryId) && !isPending && !isLoading) {
    setChosenOptionValue(String(option.value));
    onCommit({ kind: 'roster', rosterEntryId, name: option.label.trim() });
  }
  return;
}
if (onOptionConfirm) {
  onOptionConfirm(option);
  return;
}
```

(`NameFaceControl.tsx:314-328`.) R2-01b still forces `onOptionConfirm: undefined` (`NameFaceControl.test.tsx:221-226`); that is no longer required for person rows, but the id *is* asserted on `onCommit`.

2. Panel rebuilds `{kind:'roster',...}` then `submitLabel(resolution.name)` drops the id — **not closed**. `handleOptionConfirm` now only forwards cluster rows to `handleSelectOption` (`ClusterLabelingPanel.tsx:411-416`). Person check-click hits `resolveCommit`, which still writes the **name**:

```
if (resolution.kind === 'roster' && !hasClusterCollision) {
  void submitLabel(resolution.name, { skipPersonOnlyGuard: true });
  return;
}
void submitLabel(resolution.name);
```

(`:389-393`.) `updateClusterLabel` is the write; `commitClusterToRosterEntry` is not called from this file. The named panel test `'checkmark on the second same-fold person carries that id into the write (UXW2-3-R3-12)'` (`ClusterLabelingPanel.test.tsx:1130-1184`) pins `'Alex\tCarter'` vs `'Alex Carter'` — a **label string**, not `rosterEntryId`. Two people with the same folded-equal *visible* name would not distinguish ids.

3. `ClusterEditForm` calls `onPersonSelect(option.label)` / `onSave(option.label)` — **not closed**. Comment at `:101-102` claims "bind the chosen roster id (R3-12)"; the code then does:

```
if (onPersonSelect) {
  onPersonSelect(resolution.name);
} else {
  onSave(resolution.name);
}
```

(`ClusterEditForm.tsx:106-110`.) `onPersonSelect` is typed `(label: string) => void` (`:44`). The form test `'clicking the second of two same-fold people binds that roster id'` (`ClusterEditForm.test.tsx:121-139`) expects `onPersonSelect('ALEX CARTER')`, not an id. Downstream `handlePersonSelect` in `useClusterSaveAction` is name-in, rename/create-out.

**Remains:** thread `rosterEntryId` through panel `submitLabel` / Library `onPersonSelect` (or call `commitClusterToRosterEntry` on person bind). Tests must assert the id in the write, not a distinguishing label string. Queue card already keeps the id (`PersonCommitControl.tsx:121-124`).

---

## UXW2-3-R3-21 — PARTIAL

Assertions:

1. Double-submit TEST-15 covers only Enter/Enter — **partially closed**. Enter/Enter still exists (`'two rapid Enter presses fire the mutation once (UXW2-3-R1-04 / R2-02)'`, `ClusterLabelingPanel.test.tsx:1265-1289`) and still uses a real 80ms timer. Latch is `submittingRef` + `labelMutation.isPending` in `submitLabel` / `resolveCommit` (`ClusterLabelingPanel.tsx:338-341`, `:378-380`).

2. Checkmark unguarded; removing `submittingRef` from `handleOptionConfirm` / `handleSelectOption` stays green — **not closed**. Two tests are *named* R3-21:

```
it('a second checkmark during an in-flight write is ignored (UXW2-3-R3-21)', async () => {
  ...
  await typePanelName('Pat Rivera');
  const input = screen.getByRole('combobox', { name: 'Name' });
  const option = screen.queryByRole('option', { name: /confirm match/i });
  await act(async () => {
    fireEvent.keyDown(input, { key: 'Enter' });
    if (option) {
      fireEvent.click(option);
    }
    fireEvent.keyDown(input, { key: 'Enter' });
```

(`:1210-1228`; the sibling at `:1237-1255` double-clicks `option` inside the same `if`.) Default roster mock is `data: []` (`:119-126`). `'Pat Rivera'` therefore matches no overlay row, `queryByRole` is `null`, the `if (option)` body never runs. These are Enter/Enter again. A filter `-t 'second checkmark'` would select a test that cannot go red if `handleOptionConfirm` / `handleSelectOption` lost their latch. Person check-click writes through `onCommit` → `resolveCommit`, not those two handlers; a mutant that only strips `submittingRef` from them would stay green even with a real option present.

3. Save (primary button) unguarded — **not closed**. No two-click Save test.

4. Rename-anyway unguarded — **closed**. `'two rapid Rename anyway clicks fire the mutation once (UXW2-3-R3-06)'` (`:1186-1207`) finds the button, `fireEvent.click` twice, expects `updateClusterLabel` once. That would go red if the latch were removed from `submitLabel`.

**Remains:** rewrite the two R3-21 tests so an option actually exists (roster person on the overlay), click it, then click again / Save while the write is in-flight. Add a two-click Save case. Drop the `if (option)` skip. Keep the R3-06 pin.

---

## Undone

- Vitest was not executed. This checkout has no `apps/prototype-wp-alt-context/node_modules`; no install was run. Kill-power judgements for R1-08a/c, R1-16b, R3-12, and R3-21 come from reading assertion bodies, not from a revert-and-run mutant.
- R3-21 checkmark tautology was not proven RED/GREEN by reverting `submittingRef`; the `if (option)` skip with empty roster is enough to call those two tests inert.
- R1-16(h): could not confirm whether React Query still throws `'Query data cannot be undefined'` on the unstubbed heading case. The missing stub is a fact; the throw is unproven here.
- Concurrent fix lanes' work is not in this tree and was not compared.

## Incidental observations

Not part of the six verdicts; same evidence bar.

- `ClusterEditForm.tsx:101-102` comments that same-fold confirm "must still bind the chosen roster id (R3-12)" and then passes `resolution.name`. The comment overclaims; it is the R3-12 remainder, not a new finding.
- `_name-face.scss` header comment lists `acx-identity-cluster` among the file's own selectors; the Library mixin live in `_identity-cluster-list.scss:126`. Comment drift only.
