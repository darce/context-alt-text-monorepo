# UXW2-3-fix-r7j report

Commits by subject. PHP untouched. No 40-hex SHAs. UX maps not edited.

## Result

Both findings closed. Double-submit now has one killable sink in `submitLabel`. Visible `htmlFor` labels no longer lose to a colliding `aria-label`.

## Closure

| Finding | Clause | Commit subject | Test name | Verbatim mutant RED | GREEN selected/total |
| --- | --- | --- | --- | --- | --- |
| R6-08 / M4 | omit `aria-label` when visible label renders | `test(fe): UXW2-3-R6-08 visible label wins over aria-label` + `fix(fe): UXW2-3-R6-08 drop colliding aria-label` | `visible label Alpha wins over ariaLabel Beta and omits aria-label` | `Unable to find an accessible element with the role "combobox" and name "Alpha"` (received Name `"Beta"`, `aria-label="Beta"`) | unmutated `Tests  1 passed \| 35 skipped (36)`; restore `Tests  68 passed (68)` |
| R6-08 / M5 | `ariaLabel` still names hosts with no visible label | same pair | `ariaLabel names the input when there is no visible label` | `Unable to find an accessible element with the role "combobox" and name "Beta"` (received Name `""`, no `aria-label`) | unmutated `Tests  1 passed \| 35 skipped (36)`; restore `Tests  68 passed (68)` |
| R6-08 / M6 | ClusterEditForm must not pass `ariaLabel` | same pair | `names the person-name input from the visible label only (UXW2-3-R6-08)` | `AssertionError: expected 'Person name' to be undefined` (`nameFacePropsRef.current?.ariaLabel`) | unmutated `Tests  1 passed \| 31 skipped (32)`; restore `Tests  68 passed (68)` |
| R3-21 / M1 | `submitLabel` sink keeps `submittingRef.current` | `test(fe): UXW2-3-R3-21 pin save and rename-anyway double-submit` + `fix(fe): UXW2-3-R3-21 keep only submitLabel double-submit guard` | `Save name clicked twice in the same tick fires the mutation once (UXW2-3-R3-21)` | `AssertionError: expected "vi.fn()" to be called 1 times, but got 2 times` | unmutated `Tests  1 passed \| 55 skipped (56)`; restore `Tests  1 passed \| 55 skipped (56)` |
| R3-21 / M2 | `finally` must release `submittingRef` | same pair | `Save name after a settled submit fires again (UXW2-3-R3-21)` | `AssertionError: expected "vi.fn()" to be called 2 times, but got 1 times` | unmutated `Tests  1 passed \| 55 skipped (56)`; restore `Tests  1 passed \| 55 skipped (56)` |
| R3-21 / M3 | extra stacked copies | `fix(fe): UXW2-3-R3-21 keep only submitLabel double-submit guard` | n/a — copies deleted | n/a | `ClusterLabelingPanel.test.tsx` after collapse `Tests  56 passed (56)` |

Unmutated filters each selected 1 test (not 0) before the mutant.

Subjects verified with `git log --format=%s --fixed-strings --grep="<subject>"` (one hit each).

R6-08 tests 5 and 7 were RED on the pre-fix tree (aria-label won). R3-21 tests 1–4 were already GREEN on the stacked-guard tree; they exist to pin the remaining sink after the extra copies were deleted.

## Gate

Before first code commit, from `apps/prototype-wp-alt-context`:

```
 Test Files  211 passed (211)
      Tests  2463 passed (2463)
```

After last code commit (`fix(fe): UXW2-3-R3-21 keep only submitLabel double-submit guard`):

```
 Test Files  211 passed (211)
      Tests  2470 passed (2470)
```

Delta: +7 tests (NameFaceControl 34→36, ClusterEditForm 31→32, ClusterLabelingPanel 52→56). No tests lost.

`npm run typecheck` (`tsc --noEmit --project tsconfig.type-check.json`) — exit 0.

## file:line

Re-derived with `sed -n '<N>p' <file>` after the last code commit.

`ClusterLabelingPanel.tsx`:

- `:121` `const submittingRef = useRef(false);`
- `:381` `if (submittingRef.current || isBusy) {`
- `:384` `submittingRef.current = true;`
- `:421` `submittingRef.current = false;`
- `:425` `const resolveCommit = (resolution: NameFaceResolution): void => {`
- `:456` `const handleOptionConfirm = (option: ComboboxOption): void => {`
- `:457` `handleSelectOption(String(option.value));`
- `:460` `const handleSelectOption = (optionValue: string): void => {`
- `:747` `void submitLabel(duplicateGuard.label, { skipDuplicateGuard: true });`

`grep -n submittingRef ClusterLabelingPanel.tsx` after collapse: `:121`, `:381`, `:384`, `:421` only. No copies on `resolveCommit` / `handleOptionConfirm` / `handleSelectOption`.

`NameFaceControl.tsx`:

- `:190` `ariaLabel?: string;`
- `:192` `visibleLabel?: string;`
- `:513` `{visibleLabel && inputId ? (`
- `:514` `<label htmlFor={inputId} className={`${classPrefix}__visible-label`}>`
- `:538` `aria-label={visibleLabel && inputId ? undefined : ariaLabel}`

`ClusterEditForm.tsx`:

- `:190` `visibleLabel={__('Person name', 'alt-context')}`
- no `ariaLabel=` on the control

`PersonCommitControl.tsx:205` still `visibleLabel={__('Name this person', 'alt-context')}` only. Untouched.

`ClusterLabelingPanel` still uses an external `<label htmlFor="cluster-label-input">` and does not pass `ariaLabel`. Untouched.

Tests:

- `NameFaceControl.test.tsx:572` `visible label Alpha wins over ariaLabel Beta and omits aria-label`
- `NameFaceControl.test.tsx:584` `ariaLabel names the input when there is no visible label`
- `ClusterEditForm.test.tsx:583` `names the person-name input from the visible label only (UXW2-3-R6-08)`
- `ClusterLabelingPanel.test.tsx:1349` `Save name clicked twice in the same tick fires the mutation once (UXW2-3-R3-21)`
- `ClusterLabelingPanel.test.tsx:1366` `Save name clicked again while the first write is in flight fires once (UXW2-3-R3-21)`
- `ClusterLabelingPanel.test.tsx:1385` `Rename anyway clicked twice in the same tick fires the mutation once (UXW2-3-R3-21)`
- `ClusterLabelingPanel.test.tsx:1403` `Save name after a settled submit fires again (UXW2-3-R3-21)`

## Undone

- PHP untouched. No `composer test`.
- UX maps not edited (forbidden). Visible UI did not change; R6-08 is accessible-name sourcing only.
- M3: `resolveCommit`, `handleOptionConfirm`, and `handleSelectOption` each had a stacked `submittingRef.current || isBusy` copy. Isolated deletion of those copies left the new tests GREEN (the sink still caught the second write). They were deleted rather than kept. No extra copy remains to mutant.
- Test 2 (`Save name clicked again while the first write is in flight`) is also gated by `NameFaceControl` `isPending` / disabled commit. M1 is pinned by test 1 (same-tick, `isBusy` still false).
- Handoff MCP / `workbay_handoff_mcp` Python package unavailable in this throwaway mirror. No `record_event`. This report is the lane record.
