# E21-15 round-4 fix pass

Canon cards cited: **A11Y-02**, **HAI-01**, **TEST-15**, **TEST-11**.

## Per fix

### FIX-1 — done (BR-23)
**What changed:** `useWorkbenchFindings.ts` `collectPreviews` merge loop — import `isHumanLabeledTarget` from `./suggestionProjection`; replace `merge.cluster_a_label ?? null` with:

```ts
const rawLabel = merge.cluster_a_label;
// WHY (A11Y-02 / HAI-01): cluster_a_label is the raw cluster.label column —
// the backend applies no confirmation gate — so it may be a machine auto-label.
const label = isHumanLabeledTarget(rawLabel) ? (rawLabel ?? null) : null;
```

Kept `labelIsSuggested: false`. Deleted the false “confirmed cluster name” comment.

**Tests:**
- Hook: `nulls merge cluster_a_label auto-placeholders including whitespace-padded prefix` — `'cluster-7'` and `'  cluster-7'` → `{ label: null, labelIsSuggested: false }` (whitespace case discriminates from `isMeaningfulMergeLabel`).
- Existing human-label fixtures (`Person B`, `Merge Label`) unchanged / still assert `labelIsSuggested: false`.
- Panel: `alt: merge cluster_a_label placeholder from buildWorkbenchFindings is omitted` — alt `"Detected face"`, DOM has no `cluster-7`.

**Why (A11Y-02 / HAI-01):** merge `cluster_a_label` is the raw column with no confirmation gate; announcing `cluster-7` as a person fails purpose-equivalent alt / presents a machine claim as confirmed.

**Mutation proof:** Reverted merge loop to `merge.cluster_a_label ?? null` (false comment restored). Hook + panel placeholder cases went red; restore → green.

```
 FAIL  .../useWorkbenchFindings.test.tsx > nulls merge cluster_a_label auto-placeholders including whitespace-padded prefix
AssertionError: expected { … } to match object { label: null, labelIsSuggested: false }
+   "label": "cluster-7",
+   "labelIsSuggested": false,

 FAIL  .../WorkbenchFindingsPanel.test.tsx > alt: merge cluster_a_label placeholder from buildWorkbenchFindings is omitted
AssertionError: expected { … } to match object { label: null, labelIsSuggested: false }
+   "label": "cluster-7",
```

Restore → `2 passed | 57 skipped`.

### FIX-2 — done (BR-24)
**What changed:** `WorkbenchFindingsPanel.test.tsx` — strengthened the two crop-named alt tests:
- `alt: confirmed label on a real crop uses the label alone`
- `alt: unlabeled crop uses Detected face`

Each now also asserts `faceThumbnailSpy` called with `mediaUrl` + bbox + `FINDINGS_PREVIEW_SIZE_PX`, image inside `.acx-face-thumbnail`, and no `.acx-avatar`. Existing alt assertions kept.

**Why (TEST-15 / TEST-11):** alt-only asserts were green against HEAD production (Avatar path, no FaceThumbnail crop). Crop surface asserts make the green fail when the crop branch is missing.

**Mutation proof:** Restored `git show HEAD:` for `WorkbenchFindingsPanel.tsx` and `useWorkbenchFindings.ts`. Both crop tests went red on the missing FaceThumbnail path; round-4 tree restored → green.

```
 FAIL  ... > alt: confirmed label on a real crop uses the label alone
AssertionError: expected "vi.fn()" to be called with arguments: [ ObjectContaining{…} ]
Number of calls: 0
 ❯ .../WorkbenchFindingsPanel.test.tsx:578:30
    expect(faceThumbnailSpy).toHaveBeenCalledWith(

 FAIL  ... > alt: unlabeled crop uses Detected face
AssertionError: expected "vi.fn()" to be called with arguments: [ ObjectContaining{…} ]
Number of calls: 0
 ❯ .../WorkbenchFindingsPanel.test.tsx:662:30
    expect(faceThumbnailSpy).toHaveBeenCalledWith(
```

Restore → `2 passed | 24 skipped`.

## Final gates

### 1. Full vitest
```
 Test Files  182 passed (182)
      Tests  1930 passed (1930)
   Start at  06:59:20
   Duration  216.39s
```
Delta from round-3 (1928): **+2 tests** — added hook merge placeholder nulling (incl. whitespace-padded) and panel merge placeholder alt omission. FIX-2 strengthened two existing tests (no new count).

### 2. tsc
```
npx tsc --noEmit -p tsconfig.type-check.json
TSC_EXIT:0
```

### 3. eslint (explicit changed paths)
| path | errors |
|---|---|
| `ClusterLabelingPanel.tsx` | 0 |
| `ClusterReviewPanel.tsx` | 0 |
| `TopClusterCard.tsx` | 0 |
| `WorkbenchFindingsPanel.tsx` | 0 |
| `__tests__/WorkbenchFindingsPanel.test.tsx` | 0 |
| `__tests__/useWorkbenchFindings.test.tsx` | 0 |
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
 M js/admin/pages/workbench/identity-clusters/TopClusterCard.tsx
 M js/admin/pages/workbench/identity-clusters/WorkbenchFindingsPanel.tsx
 M js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx
 M js/admin/pages/workbench/identity-clusters/__tests__/useWorkbenchFindings.test.tsx
 M js/admin/pages/workbench/identity-clusters/useWorkbenchFindings.ts
 M js/admin/styles/components/_workbench.scss
 M js/components/ui/__tests__/faceGeometry.test.ts
 M js/components/ui/faceGeometry.ts
?? FIXREPORT2.md
?? FIXREPORT3.md
?? FIXREPORT4.md
?? js/components/ui/__tests__/isDedicatedFaceThumbUrl.test.ts
?? js/components/ui/isDedicatedFaceThumbUrl.ts
```

## Anything I could not do
Nothing left incomplete. Working tree left uncommitted (no `git add` / commit), as requested. Out-of-scope surfaces (`isDedicatedFaceThumbUrl` extraction, `faceGeometry.ts`, `_workbench.scss`, `selectDiversePreviews`, `previewCaptureKey`, `dedupePreviewsByCapture`, cluster preview source) were not touched.
