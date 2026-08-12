# E21-15 round-2 fix pass

## Per fix

### FIX-A — done
**What changed:** `js/admin/pages/workbench/identity-clusters/useWorkbenchFindings.ts` — replaced the drop-based `dedupePreviewsByCapture` pre-pass + `.slice(0, PREVIEW_LIMIT)` with three ordered steps: `upgradeNullBboxInPlace` (keep early null-bbox slot; copy first later non-null bbox / dedicated face-thumb), exact-key `dedupePreviewsByCapture` (unchanged `previewCaptureKey` three-branch keys), and named `selectDiversePreviews` (HAI-17 WHY comment; pass-1 unseen photograph, pass-2 fill skipped rows). Tests rewritten/added in `useWorkbenchFindings.test.tsx` for BR-12, in-window merge, two later distinct bboxes, seventh-distinct, and BR-15.

**Mutation proof:**

1. Reverted step 1 to continue-drop when any boxed twin exists for the same `mediaUrl`. BR-12 test went red; restore → green.

```
 FAIL  ... > keeps an early null-bbox photo when its boxed twin is past the preview cap
AssertionError: expected undefined to be defined
 ❯ .../useWorkbenchFindings.test.tsx:523:27
    522|     const photoXPreview = model.previews.find((preview) => preview.med…
    523|     expect(photoXPreview).toBeDefined();
       |                           ^
```

Restore → `1 passed | 31 skipped`.

2. Reverted step 3 to plain `.slice(0, PREVIEW_LIMIT)`. Seventh-distinct + BR-15 went red; restore → green.

```
 FAIL  ... > gives the seventh distinct photograph a slot instead of an early same-photo duplicate
AssertionError: expected [ …(6) ] to deeply equal [ …(6) ]
- Expected
+ Received
  [
    "http://example.test/photo-a.jpg",
+   "http://example.test/photo-a.jpg",
    "http://example.test/photo-b.jpg",
    ...
-   "http://example.test/photo-f.jpg",
  ]

 FAIL  ... > prefers a distinct seventh capture over a same-photo face-thumb + boxed pair
AssertionError: expected [ { …(6) }, { …(6) } ] to have a length of 1 but got 2
```

Restore → `2 passed | 30 skipped`.

3. Collapsed distinct non-null bboxes to `m:${mediaUrl}` only. Two-faces tests went red; restore → green.

```
 FAIL  ... > keeps two later distinct non-null bboxes ... after null upgrade
AssertionError: expected [ { …(6) } ] to have a length of 2 but got 1

 FAIL  ... > keeps two distinct non-null bboxes on the same mediaUrl as separate previews
AssertionError: expected [ 'assignment-face-a' ] to deeply equal [ 'assignment-face-a', 'merge-face-b' ]
```

Restore → `2 passed | 30 skipped`.

### FIX-B — done
**What changed:** `useWorkbenchFindings.test.tsx` — rewrote the false-green null-bbox drop test into the FIX-A cases above; paired `keeps two distinct non-null bboxes...` and `keeps two dedicated face-thumb URLs distinct...` with same-key duplicate siblings so length/key assertions fail under a no-dedupe baseline.

**Mutation proof:** Restored `git show HEAD:js/admin/pages/workbench/identity-clusters/useWorkbenchFindings.ts` into the working tree. Both rewritten “keeps distinct” tests went red (duplicate siblings survived); restore → green.

```
 FAIL  ... > keeps two distinct non-null bboxes on the same mediaUrl as separate previews
AssertionError: expected [ 'assignment-face-a', …(2) ] to deeply equal [ 'assignment-face-a', 'merge-face-b' ]
+   "assignment-face-a-dup",

 FAIL  ... > keeps two dedicated face-thumb URLs distinct even when mediaUrl matches and bbox is null
AssertionError: expected [ 'assignment-face-thumb-a', …(2) ] to deeply equal [ 'assignment-face-thumb-a', …(1) ]
+   "assignment-face-thumb-a-dup",
```

Restore → `2 passed | 30 skipped`.

### FIX-C — done
**What changed:** `useWorkbenchFindings.ts` — cluster `labelIsSuggested` now comes from `isClusterLabelSuggested` (`Boolean(label) && !cluster.user_confirmed`) with A11Y-02 / HAI-01 WHY comment. Confirmed fixture sets `user_confirmed: true`. Added provenance cases for auto-label / unconfirmed / operator-confirmed. `WorkbenchFindingsPanel.test.tsx` adds renderer assertion that `buildWorkbenchFindings` auto-label payload yields hedged alt (`Face image, possibly Machine Person`).

**Mutation proof:** Forced `labelIsSuggested: false` in the cluster source. Auto-label provenance test + renderer assertion went red; restore → green.

```
 FAIL  .../WorkbenchFindingsPanel.test.tsx > alt: auto-labelled cluster payload from buildWorkbenchFindings is hedged
AssertionError: expected { key: 'cluster-cluster-auto', …(5) } to match object { label: 'Machine Person', …(1) }
-   "labelIsSuggested": true,
+   "labelIsSuggested": false,

 FAIL  .../useWorkbenchFindings.test.tsx > marks cluster labelIsSuggested from user_confirmed provenance...
AssertionError: expected { key: 'cluster-cluster-auto', …(5) } to match object { label: 'Machine Person', …(1) }
-   "labelIsSuggested": true,
+   "labelIsSuggested": false,
```

Restore → `2 passed | 53 skipped`.

### FIX-D — done
**What changed:** `chmod 644 js/admin/pages/workbench/identity-clusters/useWorkbenchFindings.ts` only (no content change for the mode fix).

**Mutation proof:** `git diff HEAD --summary` previously reported `mode change 100644 => 100755` on that file; after chmod, `git diff HEAD --summary` shows no mode changes. File mode is `-rw-r--r--` (100644).

## Final gates

### 1. Full vitest
```
 Test Files  182 passed (182)
      Tests  1926 passed (1926)
   Start at  06:22:04
   Duration  213.41s
```
Delta from baseline 182/1920: **+6 tests** (1926), same file count. Accounted for by new FIX-A/B/C cases (BR-12, in-window merge, two later bboxes, seventh-distinct, BR-15, cluster provenance, renderer auto-label alt) minus replacement of the old drop-based null-bbox test.

### 2. tsc
```
./node_modules/.bin/tsc --noEmit --project tsconfig.type-check.json
TSC_EXIT:0
```
(no diagnostics)

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

## Anything I could not do
Nothing left incomplete from the six findings. Working tree left uncommitted (no `git add` / commit), as requested.
