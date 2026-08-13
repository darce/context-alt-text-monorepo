# E21-15 round-5 fix pass

Canon cards cited: **A11Y-02**, **HAI-01**, **TEST-15**.

## Per fix

### FIX-1 — done (BR-25)
**What changed:** `MergeSuggestionCard.tsx` — import `isHumanLabeledTarget` from `./suggestionProjection`; gate both cluster legs before display/alt:

```ts
const humanLabelA = isHumanLabeledTarget(suggestion.cluster_a_label)
  ? suggestion.cluster_a_label
  : null;
// …same for B…
const clusterALabel = humanLabelA ?? __('Unnamed cluster', 'alt-context');
const clusterAAlt = humanLabelA ?? __('Detected face', 'alt-context');
```

Visible face label uses **Unnamed cluster**; crop `alt` (and lightbox label via `onOpen`) uses **Detected face**. Identity-count suffix unchanged. Left `resolveMergeSurvivor.ts` / `isMeaningfulMergeLabel` alone.

**Tests** (`__tests__/MergeSuggestionCard.test.tsx`):
- `gates auto cluster-* labels to Unnamed cluster / Detected face alt` — `cluster-7` / `cluster-9` absent from text + alt; alts are `Detected face`; counts still render.
- `gates whitespace-padded cluster-* the same as bare auto-labels` — `'  cluster-7'` discriminates trimming `isHumanLabeledTarget` from non-trimming `isMeaningfulMergeLabel`.
- `keeps human labels as visible text and crop alt with identity count` — `'Ada Lovelace'` still visible + alt.

**Why (A11Y-02 / HAI-01):** merge suggestion `cluster_*_label` is the raw column with no confirmation gate; announcing `cluster-7` as a person fails purpose-equivalent alt and presents a machine claim as confirmed.

**Mutation proof:** Replaced the human-label gate with raw null-coalesce (`clusterALabel = suggestion.cluster_a_label ?? …`, `clusterAAlt = clusterALabel`). Auto + whitespace tests went red; restore → green.

```
 FAIL  .../MergeSuggestionCard.test.tsx > gates auto cluster-* labels to Unnamed cluster / Detected face alt
AssertionError: expected 'cluster-7 (2)cluster-9 (5)Are these t…' not to contain 'cluster-7'
 ❯ .../MergeSuggestionCard.test.tsx:84:39
    expect(container.textContent).not.toContain('cluster-7');

 FAIL  .../MergeSuggestionCard.test.tsx > gates whitespace-padded cluster-* the same as bare auto-labels
AssertionError: expected '  cluster-7 (3)cluster-9 (4)Are these…' not to contain 'cluster-7'
 ❯ .../MergeSuggestionCard.test.tsx:109:39
    expect(container.textContent).not.toContain('cluster-7');
```

Restore → `3 passed | 2 skipped` (human-label case stayed green under mutation).

### FIX-2 — done (BR-26)
**What changed:** test-only — `__tests__/useWorkbenchFindings.test.tsx`. No production change to `suggestionReviewItems.ts` or `useWorkbenchFindings.ts` (upstream `isHumanLabeledTarget` remains the single gate).

**Test:** `produces no assignment preview for auto cluster_* labels (upstream gate provenance)` — pending assignment with `cluster_label: 'cluster-7'` + media → zero `assignment-*` previews; no preview label contains `cluster-7`.

**Why (A11Y-02 / HAI-01 / TEST-15):** defense-in-depth provenance that the assignments findings source never surfaces auto-labels if the upstream filter regresses.

**Mutation proof:** Relaxed `buildSuggestionReviewItems` eligible filter to `hasSuggestionId` only. Provenance test went red; restore → green.

```
 FAIL  .../useWorkbenchFindings.test.tsx > produces no assignment preview for auto cluster_* labels (upstream gate provenance)
AssertionError: expected [ { …(6) } ] to have a length of +0 but got 1
 ❯ .../useWorkbenchFindings.test.tsx:950:87
    expect(model.previews.filter((preview) => preview.key.startsWith('assignment-'))).toHaveLength(0);
```

Restore → `1 passed | 33 skipped`.

## Final gates

### 1. Full vitest
```
 Test Files  182 passed (182)
      Tests  1934 passed (1934)
   Start at  07:59:49
   Duration  235.15s
```
Delta from round-4 (1930): **+4 tests** —
1. `gates auto cluster-* labels to Unnamed cluster / Detected face alt`
2. `gates whitespace-padded cluster-* the same as bare auto-labels`
3. `keeps human labels as visible text and crop alt with identity count`
4. `produces no assignment preview for auto cluster_* labels (upstream gate provenance)`

### 2. tsc
```
npx tsc --noEmit -p tsconfig.type-check.json
TSC_EXIT:0
```

### 3. eslint (explicit changed paths)
| path | errors |
|---|---|
| `MergeSuggestionCard.tsx` | 0 |
| `__tests__/MergeSuggestionCard.test.tsx` | 0 |
| `__tests__/useWorkbenchFindings.test.tsx` | 0 |
| `ClusterLabelingPanel.tsx` | 0 |
| `ClusterReviewPanel.tsx` | 0 |
| `TopClusterCard.tsx` | 0 |
| `WorkbenchFindingsPanel.tsx` | 0 |
| `__tests__/WorkbenchFindingsPanel.test.tsx` | 0 |
| `useWorkbenchFindings.ts` | 0 |
| `_workbench.scss` | 0 errors (1 warning: file ignored — no SCSS eslint config) |
| `__tests__/faceGeometry.test.ts` | 0 |
| `faceGeometry.ts` | **5** (pre-existing `func-style` baseline; unchanged this round) |
| `__tests__/isDedicatedFaceThumbUrl.test.ts` | 0 |
| `isDedicatedFaceThumbUrl.ts` | 0 |

`faceGeometry.ts` detail:
```
  30:1  error  Expected a function expression  func-style
  35:8  error  Expected a function expression  func-style
  48:8  error  Expected a function expression  func-style
  71:8  error  Expected a function expression  func-style
  85:8  error  Expected a function expression  func-style
✖ 5 problems (5 errors, 0 warnings)
```

### 4. mode summary
```
git diff HEAD --summary
(empty — no mode changes)
```

### 5. git status --short
```
 M js/admin/pages/workbench/identity-clusters/ClusterLabelingPanel.tsx
 M js/admin/pages/workbench/identity-clusters/ClusterReviewPanel.tsx
 M js/admin/pages/workbench/identity-clusters/MergeSuggestionCard.tsx
 M js/admin/pages/workbench/identity-clusters/TopClusterCard.tsx
 M js/admin/pages/workbench/identity-clusters/WorkbenchFindingsPanel.tsx
 M js/admin/pages/workbench/identity-clusters/__tests__/MergeSuggestionCard.test.tsx
 M js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx
 M js/admin/pages/workbench/identity-clusters/__tests__/useWorkbenchFindings.test.tsx
 M js/admin/pages/workbench/identity-clusters/useWorkbenchFindings.ts
 M js/admin/styles/components/_workbench.scss
 M js/components/ui/__tests__/faceGeometry.test.ts
 M js/components/ui/faceGeometry.ts
?? FIXREPORT2.md
?? FIXREPORT3.md
?? FIXREPORT4.md
?? FIXREPORT5.md
?? js/components/ui/__tests__/isDedicatedFaceThumbUrl.test.ts
?? js/components/ui/isDedicatedFaceThumbUrl.ts
```

## Anything I could not do
Nothing left incomplete. Working tree left uncommitted (no commit), as requested. Out-of-scope surfaces (`resolveMergeSurvivor.ts`, `isMeaningfulMergeLabel`, `suggestionReviewItems.ts` production code, `faceGeometry.ts`, `_workbench.scss`, rounds 1–4 production paths) were not modified except FIX-1’s card gate and FIX-2’s test-only addition.
