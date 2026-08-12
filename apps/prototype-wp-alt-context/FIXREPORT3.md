# E21-15 round-3 fix pass

Canon cards cited: **HAI-01**, **HAI-17**, **A11Y-02**, **TEST-15**, **TEST-11**.

## Per fix

### FIX-1 — done (supersedes round-2 FIX-A step 1)
**What changed:** `useWorkbenchFindings.ts` — deleted `upgradeNullBboxInPlace` and its call inside `dedupePreviewsByCapture`. `dedupePreviewsByCapture` is now the exact-capture-key loop only. `selectDiversePreviews` / `PREVIEW_LIMIT` unchanged. Tests: BR-12 kept with `bbox === null` assertion; deleted in-window merge + “two later distinct after null upgrade”; added anti-merge case (Person A null / Person B croppable → A keeps `bbox: null`).

**Why (HAI-01):** copying a later bbox onto an earlier same-`mediaUrl` row mis-crops a different face under the earlier label.

**Mutation proof:** Restored `upgradeNullBboxInPlace` + wired it into `dedupePreviewsByCapture`. BR-12 null assertion + anti-merge went red; restore → green.

```
 FAIL  ... > keeps an early null-bbox photo when its boxed twin is past the preview cap
AssertionError: expected { Object (x, y, ...) } to be null
 ❯ .../useWorkbenchFindings.test.tsx:526:33
    expect(photoXPreview?.bbox).toBeNull();

 FAIL  ... > does not copy a later croppable bbox onto an earlier null-bbox row for the same mediaUrl
AssertionError: expected { Object (x, y, ...) } to be null
 ❯ .../useWorkbenchFindings.test.tsx:562:27
    expect(personA?.bbox).toBeNull();
```

Restore → `2 passed | 30 skipped`.

### FIX-2 — done (BR-16 corrected)
**What changed:** `useWorkbenchFindings.ts` `collectPreviews` cluster loop — `const label = cluster.suggested_label ?? null` with WHY comment naming the top-unlabeled contract; `labelIsSuggested: Boolean(label)`. Deleted `isClusterLabelSuggested`. Tests: placeholder `{ label: 'cluster-7', suggested_label: null }` → `{ label: null, labelIsSuggested: false }`; `suggested_label: 'Ada Lovelace'` → hedged. Panel asserts alt `"Detected face"` / never `cluster-7`, and hedged suggested alt.

**Why (A11Y-02 / HAI-01):** endpoint `label` is null-or-placeholder; announcing `cluster-7` as a person fails purpose-equivalent alt.

**Mutation proof:** Reverted to `cluster.label ?? cluster.suggested_label ?? null`. Hook + panel placeholder cases went red; restore → green.

```
 FAIL  .../useWorkbenchFindings.test.tsx > ignores cluster.label placeholder...
 FAIL  .../useWorkbenchFindings.test.tsx > marks labelIsSuggested from suggested fields...
AssertionError: expected { … } to match object { label: null, labelIsSuggested: false }
+   "label": "cluster-7",
+   "labelIsSuggested": true,

 FAIL  .../WorkbenchFindingsPanel.test.tsx > alt: cluster placeholder label from buildWorkbenchFindings is omitted
AssertionError: expected { … } to match object { label: null, labelIsSuggested: false }
+   "label": "cluster-7",
```

Restore → `3 passed | 54 skipped` (hook+panel filter) / panel alone `1 passed | 24 skipped`.

### FIX-3 — done (sr-007)
**What changed:** `previewCaptureKey` — bbox key only when `isCroppableBbox(bbox)` (imported from `faceGeometry.ts`). Non-croppable / null / `{0,0,0,0}` share one key. Added collapse test for null + zero-extent on the same `mediaUrl`.

**Mutation proof:** Reverted keying to `bbox != null`. Collapse test went red; restore → green.

```
 FAIL  ... > collapses null-bbox and zero-extent sentinel bbox on the same mediaUrl to one preview
AssertionError: expected [ { …(6) }, { …(6) } ] to have a length of 1 but got 2
 ❯ .../useWorkbenchFindings.test.tsx:592:28
```

Restore → `1 passed | 31 skipped`.

### FIX-4 — done (TEST-15)
**What changed:** `WorkbenchFindingsPanel.test.tsx` — preview with `bbox: {0,0,0,0}` must call `Avatar` (spy) and must not call `FaceThumbnail`. Production already used `isCroppableBbox`; this pins the guard.

**Mutation proof:** Swapped panel `isCroppableBbox(preview.bbox)` for `preview.bbox != null`. Zero-extent test went red; restore → green.

```
 FAIL  ... > renders Avatar for a zero-extent bbox instead of FaceThumbnail
AssertionError: expected "spy" to not be called at all, but actually been called 1 time
 ❯ .../WorkbenchFindingsPanel.test.tsx:680:34
    expect(faceThumbnailSpy).not.toHaveBeenCalled();
```

Restore → `1 passed | 24 skipped`.

### FIX-5 — done (TEST-11 / TEST-15)
**What changed:** Distinct-bbox and distinct-face-thumb cases already carry same-key duplicate siblings. Ran the whole dedupe/label suite against `git show HEAD:…/useWorkbenchFindings.ts`. Every selected case was red (none green against the no-dedupe baseline).

**HEAD-restored production output (dedupe/label filter):**

```
 Test Files  1 failed (1)
      Tests  9 failed | 23 skipped (32)

     × dedupes previews that resolve to the same capture before applying the preview limit
     × keeps an early null-bbox photo when its boxed twin is past the preview cap
     × does not copy a later croppable bbox onto an earlier null-bbox row for the same mediaUrl
     × collapses null-bbox and zero-extent sentinel bbox on the same mediaUrl to one preview
     × gives the seventh distinct photograph a slot instead of an early same-photo duplicate
     × prefers a distinct seventh capture over a same-photo face-thumb + boxed pair
     × keeps two distinct non-null bboxes on the same mediaUrl as separate previews
     × keeps two dedicated face-thumb URLs distinct even when mediaUrl matches and bbox is null
     × ignores cluster.label placeholder and only surfaces suggested_label for cluster previews
```

Sibling discrimination on the two “keeps distinct” cases:

```
 FAIL  ... > keeps two distinct non-null bboxes...
+   "assignment-face-a-dup",

 FAIL  ... > keeps two dedicated face-thumb URLs distinct...
+   "assignment-face-thumb-a-dup",
```

Restore → green (full file under round-3 production).

### FIX-6 — done
**What changed:** Verified `git diff HEAD --summary` empty (no mode-change lines). `useWorkbenchFindings.ts` is `-rw-r--r--` (100644).

## Final gates

### 1. Full vitest
```
 Test Files  182 passed (182)
      Tests  1928 passed (1928)
   Start at  06:41:53
   Duration  232.19s
```
Delta from round-2 (1926): **+2 tests** — added anti-merge, null/zero collapse, panel zero-extent, panel placeholder + suggested cluster alts; removed in-window merge, post-upgrade two-bbox, and the old auto-label hedged panel case.

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
| `faceGeometry.ts` | **5** (pre-existing `func-style` baseline; unchanged) |
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
?? js/components/ui/__tests__/isDedicatedFaceThumbUrl.test.ts
?? js/components/ui/isDedicatedFaceThumbUrl.ts
```

## Anything I could not do
Nothing left incomplete. Working tree left uncommitted (no `git add` / commit), as requested.
