# UXW2-4-R7E-02 — `formatClusterLabel` no longer synthesizes a machine id

## Result

Unlabeled clusters no longer render as `cluster-<32 hex>`. `formatClusterLabel` returns `null` for that case; `IdentityClusterItem` now reaches `__('Unlabeled identity')`. Auto-shape `rawLabel` still does not leak as a person name. `!clusterId` still returns `rawLabel` untouched.

`file:line` cites below were re-derived with `sed -n '<N>p' <file>` after the last code/test commit.

## Callers

`git grep -n formatClusterLabel -- js` from `apps/prototype-wp-alt-context` (production + tests). Production consumers only:

| Call site | handles null? | change made |
| --- | --- | --- |
| `utils.ts:24` definition | n/a — producer | final line is `return null` (`:37`). Doc comment now says the caller owns unlabeled copy (`:14`). |
| `IdentityClusterItem.tsx:62` | **yes.** Display: `derivedLabel ?? __('Unlabeled identity')` (`:76`). Edit seed: `derivedLabel ?? ''` (`useClusterEditState.ts:117`). Revert source: `derivedLabel ?? null` (`useClusterLabelMutations.ts:148`). Both hooks already typed `derivedLabel: string \| null`. | none on the component. Fallback was already written; it was dead because the helper never returned null when `clusterId` was set. |
| `index.ts:41` re-export | n/a — not a consumer. No other production importer. | none |
| `utils.test.ts` | asserts the contract | rewritten in the same commit as `utils.ts`. Auto-shape still must not equal `cluster-7`. Unlabeled is `null`. |
| `IdentityClusterItem.test.tsx` | rendering consumer | added unlabeled + auto-shape render cases |
| `IdentityClusterList.test.tsx` | list mounts `IdentityClusterItem` | unlabeled-edit matcher `/cluster-clust/` → `/Unlabeled identity/` |

No other production caller. A raw `null` cannot render as empty text at the item: the `??` fallback owns the copy.

## Closure

Unmutated targeted run (non-zero before mutants): `utils.test.ts` + `IdentityClusterItem.test.tsx` → **14 / 14**.

| Mutant | verbatim RED | GREEN selected/total |
| --- | --- | --- |
| **M1** restore `return \`cluster-${normalizedId}\`;` as the final line | `AssertionError: expected 'cluster-aaaaaaaabbbbccccddddeeeeeeeee…' to be null` / `- Expected:` `null` / `+ Received:` `"cluster-aaaaaaaabbbbccccddddeeeeeeeeeeee"` | `-t "returns null for unlabeled clusters"` **1 / 7** (`1 passed \| 6 skipped (7)`) |
| **M2** drop `?? __('Unlabeled identity', 'alt-context')` in `IdentityClusterItem.tsx` | `TestingLibraryElementError: Unable to find an accessible element with the role "button" and name "Unlabeled identity"` (empty label button, `Name ""`) | `-t "renders Unlabeled identity when the cluster has a UUID"` **1 / 7** (`1 passed \| 6 skipped (7)`) |
| **M3** delete the `isHumanLabeledTarget(rawLabel)` guard | `AssertionError: expected 'cluster-7' not to be 'cluster-7' // Object.is equality` | `-t "does not treat auto-shape cluster-7"` **1 / 7** (`1 passed \| 6 skipped (7)`) |

Each mutant restored after the RED. Production `git diff` after restore was the intended change only.

`IdentityClusterList.test.tsx` after matcher update: **24 / 24**.

## Gate

From `apps/prototype-wp-alt-context`, on original HEAD (stash off):

```
 Test Files  208 passed (208)
      Tests  2340 passed (2340)
```

After the three code/test commits:

```
 Test Files  208 passed (208)
      Tests  2344 passed (2344)
```

Delta: **+0 files, +4 tests**. The four new cases are the two `formatClusterLabel` contract tests and the two `IdentityClusterItem` unlabeled/auto-shape render tests. No test vanished.

`npm run typecheck`: clean (`tsc --noEmit --project tsconfig.type-check.json`).

## file:line

| Claim | `sed -n` |
| --- | --- |
| Caller owns unlabeled copy | `utils.ts:14` `Otherwise returns null; the caller owns unlabeled copy` |
| E21-15-BR-27 comment kept | `utils.ts:17` `` (`cluster-*`) must not render as confirmed person names (E21-15-BR-27). `` |
| `!clusterId` still returns `rawLabel` | `utils.ts:29-30` |
| `isHumanLabeledTarget` guard kept | `utils.ts:33` `if (rawLabel && !isAutoLabel && isHumanLabeledTarget(rawLabel))` |
| Unlabeled is `null` | `utils.ts:37` `return null;` |
| Only production call | `IdentityClusterItem.tsx:62` |
| Designed copy now reachable | `IdentityClusterItem.tsx:76` `derivedLabel ?? __('Unlabeled identity', 'alt-context')` |
| Null-safe edit seed | `useClusterEditState.ts:86`, `:117` |
| Null-safe revert source | `useClusterLabelMutations.ts:27`, `:148` |
| Barrel re-export only | `index.ts:41` |
| Auto-shape does not leak | `utils.test.ts:34-35` |
| Unlabeled unit pin | `utils.test.ts:52` |
| Rendering pin | `IdentityClusterItem.test.tsx:234` |
| List click pin | `IdentityClusterList.test.tsx:963` |

## Undone

- **PHP / contract.** Untouched. Sibling lane. `composer test` not run.
- **`docs/ux-maps/`.** Untouched (not owned). This is display copy on the existing cluster item, not a new screen/zone/flow. Designed unlabeled copy already existed in the component; it was unreachable.
- **`banned-vocabulary.test.tsx`.** Not tightened. `WorkbenchPage` mocks `ScanTabContent`, so `IdentityClusterItem` unlabeled copy never mounts in the page sweep. Adding `cluster-` to `BANNED_STRINGS` would false-positive internal keys (`key: cluster-${id}`) and the existing `Remove from Cluster` action. `UUID_REGEX` does not match the hyphenless 32-hex form. Source sweep already targets toast jargon (`for cluster %s`), not this helper. Coverage is the unit + render + list tests above.
- **Handoff.** Isolated lane clone has no `workbay_handoff_mcp`. Integrator records the decision after transplant.

## Commits (subjects)

- `fix(fe): return null instead of synthesizing cluster-hex labels`
- `test(fe): prove Unlabeled identity copy is reachable`
- `test(fe): click Unlabeled identity instead of synthesized cluster-hex`
- this report commit
