# UXW2-2 audit r9 shard B — board vs current tree

Read-only re-check. Verdicts from source as it exists now. Line cites re-derived immediately before this file was written. No test suite was run; kill-power arguments are from reading assertions against the named mutants.

### UXW2-2-R5-05 — FIXED

**Claim:** No `__tests__` caller hits `applyTopUnlabeledTombstones` / `applyAssignmentTombstones` / `applyNameTombstones` directly, so reinstating `has_clusters: filtered.length > 0` inside `applyTopUnlabeledTombstones` stays GREEN; only `dropClusterFromReviewCaches` is guarded.

**Evidence:** Direct unit file `suggestionProjection.tombstones.test.ts`. Production select still spreads the page and rewrites only `clusters` + `total`:

```
486|  return {
487|    ...page,
488|    clusters: filtered,
489|    total: Math.max(0, page.total - removed),
490|  };
```

(`suggestionProjection.ts:486-490`)

Emptied-page test calls the select and pins passthrough:

```
59|  it('R5-05: applyTopUnlabeledTombstones keeps has_clusters when the served page is emptied', () => {
72|    const next = applyTopUnlabeledTombstones(queryClient, page);
74|    expect(next).toEqual({
75|      ...page,
76|      clusters: [],
77|      total: 10,
78|      has_clusters: true,
79|    });
```

(`suggestionProjection.tombstones.test.ts:59-79`)

Sibling cases call `applyAssignmentTombstones` (`:82-94`) and `applyNameTombstones` (`:97-128`). Partial-page case also pins `expect(next.total).toBe(11)` and `expect(next.has_clusters).toBe(true)` (`:40-56`).

**Verdict rationale:** The named mutant writes `has_clusters: filtered.length > 0` onto the emptied-page return. `filtered` is `[]`, so `has_clusters` becomes `false` while the assertion still demands `true` (and `toEqual` would also mismatch `total: 10`). That is a concrete RED from the assertion, the compared value, and the production line the mutant would change. Assignment/name selects have no `has_clusters`/`total` fields; they now have direct drop-and-sibling tests as the FIX asked.

### UXW2-2-R5-06 — PARTIAL

**Claim:** `useClusterMutations` invalidates five keys but the R3-05 test mounts one identities observer, so `refetchType: 'none'` on any of the other four stays GREEN.

**Evidence:** Production still invalidates five keys with no `refetchType: 'none'`:

```
50|    void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
51|    void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.labels() });
52|    void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
```

plus `queryKeys.suggestions.projection.all` and `queryKeys.suggestions.mergePending()` (`useClusterMutations.ts:49-58`).

The R3-05 case now mounts five `useQuery` observers (`useClusterMutations.test.tsx:57-77`) and asserts all five fetchers (`:104-109`). It never spies `invalidateQueries`. Key prefix: `queryKeys.clusters.all` is `['clusters']`; `queryKeys.clusters.labels()` is `[...queryKeys.clusters.all, 'labels']` (`queryKeys.ts:24,31`).

**Verdict rationale:** The single-observer claim is now false. Restoring `refetchType: 'none'` on identities, `clusters.all`, projection, or mergePending would leave the matching fetcher uncalled and trip `:105/:107/:108/:109`. Surviving: `refetchType: 'none'` on the `labels()` call still leaves `fetchLabels` called, because the `clusters.all` invalidation prefix-matches `['clusters','labels']`. That fifth key is still asserted in name only (see R8-04).

### UXW2-2-R5-07 — PARTIAL

**Claim:** The R1-24/R5-07 bulk-accept test only asserts `namePending` cache length and never renders `ReviewQueue` or `.acx-review-queue__count`; the header (`filteredQueue.length`) is unproven.

**Evidence:** Header still gates on `length > 0` and prints `filteredQueue.length`:

```
447|    const length = filteredQueue.length;
988|          {length > 0 ? (
989|            <span className="acx-review-queue__count" aria-hidden="true">
```

(`ReviewQueue.tsx:447,988-989`)

`useSuggestionReviewMutations.test.tsx` still has zero `ReviewQueue` / `.acx-review-queue__count` hits. The bulk-accept name case still does cache + invalidate only:

```
1913|    expect(queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey)?.suggestions).toHaveLength(2);
1914|    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: namePendingKey });
```

(`useSuggestionReviewMutations.test.tsx:1913-1914`)

No test named `R5-07` exists. `ReviewQueue.test.tsx:1055` still asserts `queryByText('Bulk accept')` is absent. `useBulkReviewCommit.ts:6` still says `Zero calls to legacy bulk-accept`. A later case does render the header, but through per-item Accept, not bulk accept (`ReviewQueue.test.tsx:3166-3221`, `R7-06: queue header decrements after accepting names through ReviewQueue`).

**Verdict rationale:** The “never touches the header” claim is no longer globally true — R7-06 reads `.acx-review-queue__count` after Accept. Surviving: bulk accept is still not driven through `ReviewQueue`; the hook file still never mounts the header; there is still no Bulk-accept chrome to call `mutations.bulkAccept`. The original “header decrements after bulk accept / per suggestion_type” brief is still unproven.

### UXW2-2-R5-10 — FIXED

**Claim:** `UXW2-2-fe-report.md` still carries eight unresolvable full-length SHAs as dead weight next to subject-line citations.

**Evidence:** Report header is now subject-only:

```
1|# REPORT — UXW2-2 FE fix lane
3|Cite commits by **subject line** only.
7|| Finding | Subject | Mutant killed |
```

(`docs/tasks/uxw2/UXW2-2-fe-report.md:1-7`)

A Python scan of `\b[0-9a-f]{40}\b` over that file returned count 0. The same scan over every `docs/tasks/uxw2/*.md` on this tree also returned count 0. Residual prose at `:65` says “labelled lane SHAs only” but there is no SHA column and no forty-hex token to resolve.

**Verdict rationale:** The eight-SHA column the finding describes is gone. Subject-line citations remain. The report can no longer trip a forty-hex provenance lint via this file.

### UXW2-2-R5-11 — OPEN

**Claim:** `__(REVIEW_QUEUE_LABEL_SAVED_ANNOUNCE, 'alt-context')` passes a constant, so no gettext extractor can see the msgid; the brief asked for inline literals.

**Evidence:** Constant definition `ReviewQueue.tsx:103`:

```
103|export const REVIEW_QUEUE_LABEL_SAVED_ANNOUNCE = 'Name saved. Back to review suggestions.';
```

Call site still wraps the constant, not a literal:

```
207|                  announceReviewLifecycle(__(REVIEW_QUEUE_LABEL_SAVED_ANNOUNCE, 'alt-context'));
```

(`ScanTabContent.tsx:207`)

No `gettext-literals` test exists in this tree. r3 report Undone still records this as deliberately unpatched (`UXW2-2-fe-r3-report.md:82`).

**Verdict rationale:** The extractor-blind constant is still the live call. The recommended “do not patch this one site; track systemically on uxw2-3” was followed, which leaves the claim true. OPEN, not a silent close.

### UXW2-2-R7-03 — FIXED

**Claim:** UXW2-2-R7-01 has no kill-power on either surface: the R5-02 ReviewQueue fixture has `filteredQueue.length === topUnlabeledClusters.length === 0` so swapping both `gatedClusterCopy` servedCount args for `length` stays GREEN, and the findings-panel R2-12 case only used `/missing face data/i`, so dropping the panel `servedCount` arg also stays GREEN.

**Evidence:** Helper branches (`representativeVocabulary.ts:16-45`): `servedCount === 0` → elsewhere; `truncated` → on this page; else plain. ReviewQueue callers pass `topUnlabeledClusters.length` (`ReviewQueue.tsx:591` and `:1358`). Panel caller passes `zeroEvidenceClusterCount` (`WorkbenchFindingsPanel.tsx:434`). Queue construction drops zero-evidence clusters (`reviewQueueDriver.ts:345-346`).

R5-02 still uses empty names + empty clusters and only `expect(repair).not.toHaveTextContent(/on this page/)` (`ReviewQueue.test.tsx:2880-2899`) — that case still would not kill `servedCount = length`.

Covering tests that would:

- ReviewQueue R8-01 (`ReviewQueue.test.tsx:2788-2877`): three `identity_count: 0` clusters, empty suggestions. `filteredQueue.length` is 0 (zeros filtered out of the queue); `topUnlabeledClusters.length` is 3. Exact copy `'3 groups missing face data'` plus `not.toMatch(/elsewhere/)`. Mutant `servedCount = length` yields `gatedClusterCopy(3, false, 0)` = `'3 groups elsewhere are missing face data'` → those exact asserts go red.
- Panel R2-12 (`WorkbenchFindingsPanel.test.tsx:1154-1172`): zeros=0, unlabeled=5, truncated, empty previews. Exact `'5 groups elsewhere are missing face data'`. Dropping the servedCount arg uses default `-1`, skips the `=== 0` arm, and with `truncated: true` produces the on-this-page sentence → the elsewhere exact string is missing.
- Helper exact sentences (`representativeVocabulary.test.ts:20-31`) compare servedCount 0 vs 2 vs 3 as different strings.
- Panel R7-03 cases (`WorkbenchFindingsPanel.test.tsx:1972-2017`) pin `'At least 3 groups on this page missing face data'` vs plain `'3 groups missing face data'` and reject elsewhere / unlabeled-7 wordings.

**Verdict rationale:** The finding’s “no covering test on either surface” is now false. The R5-02 caller remains a weak fixture, but it is no longer the only guard. Named mutants (ReviewQueue `servedCount → length`; panel drop servedCount) have assertions that compare a wording the mutant cannot produce.

### UXW2-2-R7-05 — PARTIAL

**Claim:** The partial-accept test asserts only `namePendingKey` invalidate plus cache identity, so deleting the `top-unlabeled` invalidate leaves GREEN; `renderMutations()` has no observer, so “refetches” is unobserved.

**Evidence:** Production still invalidates both keys on any `accepted_count > 0`:

```
1024|      void queryClient.invalidateQueries({ queryKey: namePendingKey });
1026|      void queryClient.invalidateQueries({
1027|        queryKey: [...queryKeys.clusters.all, 'top-unlabeled'],
1028|      });
```

(`useSuggestionReviewMutations.ts:1024-1028`)

The named test now spies both:

```
1840|    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: namePendingKey });
1841|    expect(invalidateSpy).toHaveBeenCalledWith({
1842|      queryKey: [...queryKeys.clusters.all, 'top-unlabeled'],
1843|    });
```

(`useSuggestionReviewMutations.test.tsx:1813-1843`)

`renderMutations` is still hook-only (`:186-187`): `renderHook(() => useSuggestionReviewMutations(...))` with no `useQuery` observer. Cache rows are still asserted unchanged (`:1844-1849`).

**Verdict rationale:** Deleting production `:1026-1028` would fail the new `toHaveBeenCalledWith` on the top-unlabeled key — that named mutant is now killable. Surviving: no observer, so `invalidateQueries` still triggers no refetch; the test name’s “refetches” remains a spy on invalidate, not a fetch. Cache-identity checks still prove nothing was evicted.

### UXW2-2-R7-06 — OPEN

**Claim:** The r3 report says the queue header decrements after a full bulk accept, but the test does not drive bulk accept through ReviewQueue; the pasted `length >= 0` RED (`expected <span …(2)></span> to be null`) is the wrong mutant’s output.

**Evidence:** r3 row still:

```
13|| R5-07 | `fix(fe): UXW2-2-R5-07 assert the real header count after full bulk accept` | `R5-07: the queue header count decrements after a full bulk accept` (renders `.acx-review-queue__count`; drives `bulkAcceptSuggestions` `{accepted_count:2,skipped_count:0}` on the shared QueryClient) | `length >= 0` so the span renders at zero → `AssertionError: expected <span …(2)></span> to be null` | …
```

(`docs/tasks/uxw2/UXW2-2-fe-r3-report.md:13`)

That test name does not exist in `*.ts`/`*.tsx`. ReviewQueue still has no Bulk-accept control (`ReviewQueue.test.tsx:1055`). Header decrement that does exist is per-item Accept (`ReviewQueue.test.tsx:3166-3221`). r4 report already admits the mismatch and that r3 was not edited (`UXW2-2-fe-r4-report.md:64`).

**Verdict rationale:** Report honesty is still broken on the r3 row: it still claims a bulk-accept header drive and still pastes the skipped-drop RED. The later R7-06 header test does not make that citation true. OPEN.

### UXW2-2-R8-04 — OPEN

**Claim:** The five-observer R5-06 test cannot independently kill `refetchType: 'none'` on `queryKeys.clusters.labels()` because `clusters.all` (`['clusters']`) prefix-matches `labels()` (`['clusters','labels']`); the test asserts refetch, not `invalidateQueries` arguments.

**Evidence:** Same test as R5-06: five observers, five `toHaveBeenCalled()` on fetchers, zero `invalidateQueries` spies (`useClusterMutations.test.tsx:57-109`). Prefix is structural (`queryKeys.ts:24,31`). Production still issues both invalidations (`useClusterMutations.ts:51-52`). r4 Undone already records this (`UXW2-2-fe-r4-report.md` TEST-15 notes / Undone).

**Verdict rationale:** Setting `refetchType: 'none'` only on the `labels()` invalidate still leaves `fetchLabels` called via the `clusters.all` invalidate. Without an argument-level spy (or a labels observer whose key is not a `clusters.all` prefix), that fifth key is still un-killed. OPEN.

### UXW2-2-R8-08 — PARTIAL

**Claim:** `UXW2-2-r4-fix-report.md` tells the integrator that `docs/workbay/contracts/clustering-api.md` is gitignored / not in git, which is false on the canonical tracked file.

**Evidence:** That gitignored sentence is absent from the current r4 report (scan of `gitignored` / `not in git` / `workbay overlay` in `UXW2-2-r4-fix-report.md` is empty). r5 PHP report records the deletion (`UXW2-2-r5-fix-report.md:56`). `git ls-files -- docs/workbay/contracts/clustering-api.md` prints the path — the file is tracked. Overlay ignore is still present:

```
165|/docs/workbay/contracts
```

(`.gitignore:165`; also `UXW2-2-r5-fix-report.md:108`). No `vmlane.sh` exists in this tree.

**Verdict rationale:** The false integrator instruction is gone; the contract file is tracked. Surviving: the overlay ignore line is still in `.gitignore`, so a future lane clone can still *see* the file as ignored even though git tracks it. The FIX’s `vmlane.sh` force-add cannot be confirmed here because that script is not in this repository.

### UXW2-2-R9-01 — OPEN

**Claim:** `Uxw2ReportShaLintTest` requires every forty-hex token in `docs/tasks/uxw2/*.md` to resolve via `git cat-file -e`, with no allowlist for deliberately quoted mutant payloads, so merge onto a tree that already contains such a quoted token goes red.

**Evidence:** The lint still has no allowlist marker, skip, or quoted-payload exception:

```
17|    private const REPORTS_GLOB = 'docs/tasks/uxw2/*.md';
35|            preg_match_all('/\b[0-9a-f]{40}\b/', $content, $matches);
36|            foreach ($matches[0] as $sha) {
37|                $this->assertTrue(
38|                    $this->shaResolves($git, $root, $sha),
```

(`Uxw2ReportShaLintTest.php:17-38`)

On this tree the glob currently matches reports with zero forty-hex tokens, so the local sweep would be clean. The test is still repo-wide by construction.

**Verdict rationale:** The missing allowlist is still missing. A quoted non-commit forty-hex payload in any `docs/tasks/uxw2/*.md` would still fail `shaResolves`. Sibling-branch reports were not opened (lane rule: do not leave this cwd), so the specific uxw2-5 quoted-mutant file is not re-confirmed here; the lint defect does not depend on that confirmation.

### UXW2-2-R9-02 — OPEN

**Claim:** The r5 report’s `R8-02 follow` RED cell is prose rather than a verbatim assertion, so a reviewer cannot re-run the failure that supposedly closed that row.

**Evidence:** Table still:

```
13|| R8-02 follow | `fix(fe): UXW2-2-R8-02 re-announce repair copy without first-mount drain` | UI-04 hold stayed on the card when first-mount empty always announced |
```

(`docs/tasks/uxw2/UXW2-2-fe-r5-report.md:13`)

Every other Closed RED cell on that table quotes an assertion string. Undone still describes the first-mount drain / UI-04 accept-hold clash in prose (`:62`). The live UI-04 test is `UI-04: drain announcement uses error copy when top-unlabeled failed` (`ReviewQueue.test.tsx:2423-2424`) — a different assertion than “hold stayed on the card”.

**Verdict rationale:** The row is still the only closure cell without a verbatim failure string. The underlying announce path may be correct (out of this finding’s claim); the citation gap the finding named is unchanged.

## Tally

FIXED: 3 | PARTIAL: 4 | OPEN: 5 | UNVERIFIABLE: 0

## Undone

- No mutant was executed; all TEST-15 kill-power calls are from reading assertions against the named production lines.
- Sibling uxw2 worktrees were not opened, so R9-01’s merge-order payload in another branch’s report is not re-listed here; the lint’s missing allowlist was judged from this tree’s PHP test alone.
- `vmlane.sh` is not in this repository; R8-08’s force-add half could not be inspected beyond `.gitignore:165`.
- Vitest / composer were not run (board rule).
- Findings outside this shard were not audited.
