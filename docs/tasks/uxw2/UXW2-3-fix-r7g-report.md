# UXW2-3-fix-r7g report

Commits by subject. PHP untouched. No 40-hex SHAs.

## Result

Suite green. Cluster-card locator matches `Create person "Alex"`. Arrow-active preview uses the same `resolveNameFaceInput` as the typed-draft path, so the button names the row Enter/Save will confirm.

## Closure

| Item | Commit subject | Test | Verbatim RED | GREEN selected/total |
| --- | --- | --- | --- | --- |
| 1 locator | `test(fe): query Create person Alex on cluster-card commit` | `person-commit succeeded on a CLUSTER card (markerless success surface): footer re-owns the single accent primary (BR-81)` | `TestingLibraryElementError: Unable to find role="button" and name "Save name"` (button was `Create person "Alex"`) | file `Tests  11 passed (11)` |
| 2 / M1 | `test(fe): pin arrow-active commit preview to the row` + `fix(fe): preview arrow-active row via one resolver` | `arrow-active row previews the row bind not the typed draft` | `TestingLibraryElementError: Unable to find an accessible element with the role "button" and name "Save as Grace Hopper"` (mutant button `Create person "Gra"`) | `Tests  1 passed \| 33 skipped (34)` |
| 2 / M2 | same | `arrow-active row previews the row bind not the typed draft` | `TestingLibraryElementError: Unable to find an accessible element with the role "button" and name "Save as Grace Hopper"` (mutant button `Create person "Grace Hopper"`) | `Tests  1 passed \| 33 skipped (34)` |
| 2 / M3 | same | `pendingLabel wins over arrow-active preview` | `TestingLibraryElementError: Unable to find an accessible element with the role "button" and name "Saving name…"` (mutant button `Save as Grace Hopper`) | `Tests  1 passed \| 33 skipped (34)` |

Unmutated filters each selected 1 test before the mutant (not 0). NameFaceControl file after restore: `Tests  34 passed (34)`.

Exact string `Create person "Alex"` — not `/Create person/`. A regex would still pass if the preview named the wrong person.

Subjects verified with `git log --format=%s --fixed-strings --grep="<subject>"` (one hit each).

## Precedence

`commitButtonLabel` (`NameFaceControl.tsx:283`), in order:

1. `isPending && pendingLabel` → `pendingLabel` (`:284-285`)
2. `previewCommit` and an arrow-active row (`listOpen && !isLoading && activeIndex >= 0`) → `resolveNameFaceInput(options, activeOption.label)` (`:289-293`)
3. typed-draft `commitResolution` = `resolveNameFaceInput(options, value)` (`:278`, `:294`)
4. `commitLabel` for `ambiguous` / `null` / `previewCommit` off

One resolver. Active-row and typed-draft both call `resolveNameFaceInput`. No second path. `previewCommit` stays default `false` (`:220`).

Gating the active row on `listOpen` (not `overlayOpen`): `overlayOpen` is false while pending, so that gate would skip the highlighted row and M3 would fall through to the typed draft. Escape still sets `listOpen` false, so the preview then matches Enter (`commitValue(value)`).

## Gate

r7f baseline (this clone, before this lane):

```
Test Files  1 failed | 210 passed (211)
      Tests  1 failed | 2447 passed (2448)
```

This lane, from `apps/prototype-wp-alt-context` after the last code commit:

```
Test Files  211 passed (211)
      Tests  2453 passed (2453)
```

Delta: the mediaFooter file went from `1 failed | 10 passed (11)` to `11 passed (11)`. NameFaceControl gained 3 tests (31 → 34). `npm run typecheck` (`tsc --noEmit --project tsconfig.type-check.json`) — exit 0.

## file:line

Re-derived with `sed -n '<N>p' <file>` after `fix(fe): preview arrow-active row via one resolver`.

`NameFaceControl.tsx`:

- `:220` `previewCommit = false,`
- `:238` `const [activeIndex, setActiveIndex] = useState(-1);`
- `:278` `const commitResolution = React.useMemo(`
- `:284` `if (isPending && pendingLabel) {`
- `:285` `return pendingLabel;`
- `:290` `listOpen && !isLoading && activeIndex >= 0 ? displayedOptions[activeIndex] : undefined;`
- `:293` `? resolveNameFaceInput(options, activeOption.label)`
- `:294` `: commitResolution;`
- `:384` `if (overlayOpen && activeIndex >= 0 && displayedOptions[activeIndex]) {`
- `:385` `confirmDisplayedOption(displayedOptions[activeIndex]);`
- `:458` `if (e.key === 'Enter') {`
- `:464` `confirmDisplayedOption(displayedOptions[activeIndex]);`
- `:467` `commitValue(value);`

`mediaFooterSinglePrimary.dom.test.tsx`:

- `:407` `const confirm = await screen.findByRole('button', { name: 'Create person "Alex"' });`

`NameFaceControl.test.tsx`:

- `:484` `it('arrow-active row previews the row bind not the typed draft', async () => {`
- `:506` `it('arrow-active same-fold row keeps commitLabel', async () => {`
- `:518` `it('pendingLabel wins over arrow-active preview', async () => {`

## Undone

- PHP untouched. No `composer test`.
- UX maps not edited (forbidden). Queue-card button copy is now also arrow-active-row-dependent when `previewCommit` is on. A follow-up that owns `docs/ux-maps/**` should add that state.
- `ClusterLabelingPanel` / `ClusterEditForm` still do not pass `previewCommit`. Sibling-owned.
- `previewCommit` default remains `false`. Library `/^Save name$/` pins stay green.
- Active-row preview resolves `activeOption.label` against the **full** options list. Two same-fold people still return `ambiguous` → `commitLabel`, even though Enter on that row binds via `confirmDisplayedOption`. Button is already disabled (`isAmbiguous`). Same-fold + ArrowDown test pins that we do not claim `Save as` / `Create person` off the raw label.
- M2 mutant used the option's raw `label` in the create template (`Create person "Grace Hopper"` vs resolver `Save as Grace Hopper`). A `Save as ${label}` mutant would stay green on the unique-person row (resolver `name` is `label.trim()`); the same-fold test is the pin for that shape.
- Handoff MCP / `workbay_handoff_mcp` Python package unavailable in this throwaway mirror. No `record_event`. This report is the lane record.
