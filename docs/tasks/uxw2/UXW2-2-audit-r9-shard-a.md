# UXW2-2 audit r9 shard A

Read-only re-check of the listed findings against the current tree. Line cites re-derived immediately before this write. No tests run. No production files edited.

### UXW2-2-R1-07 — FIXED

**Claim:** Excluding `<2`-member clusters from `list_top_unlabeled` also removed them from the only page-local repair scan, `singleton_count` still trusted the stale `identity_count` column (so zero/one-member drift was never healed and the count lied), passing `PREVIEW_IDENTITIES_PER_CLUSTER` was a no-op third argument, and `repair_targeted_projection` ignored ids and ran an un-targeted full bootstrap.

**Evidence:** `ClustersReadRepository::list_top_unlabeled` still excludes `<2` observed members (`apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-read-repository.php:246-250`), but a dedicated tenant-wide scan now exists:

```246:250:apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-read-repository.php
					AND (
						SELECT COUNT(*)
						FROM %i m
						WHERE m.cluster_uuid = c.cluster_uuid
					) >= 2
```

```293:305:apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-read-repository.php
		$sql              = $this->prepare_projection_read_query(
			"SELECT c.cluster_uuid
			FROM %i c
			WHERE c.tenant_id = %s
				AND c.is_user_confirmed = 0
				AND (c.label IS NULL OR c.label = '' OR c.label LIKE 'cluster-%%')
				AND (c.curation_state IS NULL OR c.curation_state <> 'dismissed')
				AND c.identity_count <> (
					SELECT COUNT(*)
					FROM %i m
					WHERE m.cluster_uuid = c.cluster_uuid
				)
			LIMIT %d",
```

That scan is invoked from `list_top_unlabeled_clusters` (`class-cluster-read-service.php:189-194`) and merged as extras in `schedule_repair_from_mapper`. `singleton_count` is sourced from `count_top_unlabeled_singletons`, which counts `COUNT(m) <= 1`, not the `identity_count` column (`class-clusters-read-repository.php:356-360`; facade `class-cluster-facade.php:35`). `PREVIEW_IDENTITIES_PER_CLUSTER` is the fourth argument (`class-cluster-read-service.php:182-187`); mapper default is `null` (`class-cluster-response-mapper.php:104`) and a non-null `preview_limit` drives densify plus truncation (`:107-108`, `:300-302`). `repair_targeted_projection` now forwards ids (`class-cluster-projection-sync-service.php:176-189`); the cron handler calls `perform_targeted_snapshot` when ids are present (`class-api.php:122-124`; `class-cluster-projection-sync-service.php:150-152`).

**Verdict rationale:** Every original assertion is now false. Off-page identity_count/member drift is no longer trapped behind the page-local mapper; singleton count is derived from member rows; the preview const is a real truncation cap, not a no-op; targeted ids reach `perform_targeted_snapshot`. Residual ceiling/raw-array gating of that drift scan is R4-04, not this finding.

### UXW2-2-R1-08 — FIXED

**Claim:** Lane `REPORT.md` at repo root listed an unreachable report SHA and must not merge to main.

**Evidence:** `test ! -f REPORT.md` → file absent at repo root. Surviving close-out lives at `docs/tasks/uxw2/UXW2-2-r1-fix-report.md` (opening L3: `Branch \`feature/uxw2-2\``). A search of that file for a 40-character hex string returned no matches. The requested destination name `docs/tasks/uxw2/UXW2-2-php-lane-report.md` is also absent; the fold used `UXW2-2-r1-fix-report.md` instead.

**Verdict rationale:** The merge-blocking artifact (root `REPORT.md` + unreachable SHA) is gone. Filename differs from the suggested path; that is not the original defect.

### UXW2-2-R1-24 — PARTIAL

**Claim:** `acceptNameMutation.onSuccess` and `bulkAcceptMutation.onSuccess` were left unwired for group resolution, so neither called `dropClusterFromReviewCaches`, neither had a header-count test, and assignment/`topUnlabeled` rows for the accepted group stayed in the loaded queue (same B6 header-decrement miss).

**Evidence:** `acceptName` is now wired. Hold-success (`useSuggestionReviewMutations.ts:349-354`) and mutation `onSuccess` (`:986-993`) both look up `named.cluster_id` then call `dropClusterFromReviewCaches(..., { mode: REVIEW_DROP_MODE.LABEL })`. That helper decrements `topUnlabeled.total` by rows actually removed (`suggestionProjection.ts:562-566`). Test `R1-24: acceptName drops the accepted group from namePending and topUnlabeled` (`useSuggestionReviewMutations.test.tsx:1673-1702`) asserts remaining cluster **ids** only:

```1697:1702:apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/useSuggestionReviewMutations.test.tsx
    expect(
      queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['name-2']);
    expect(
      queryClient.getQueryData<TopUnlabeledClustersResponse>(topUnlabeledKey)?.clusters.map((c) => c.id),
    ).toEqual(['cluster-other']);
```

`bulkAcceptMutation.onSuccess` still does not drop (`:1007-1033`). It invalidates `namePending` and the `top-unlabeled` prefix, with an explicit rg-015 comment that `BulkAcceptResponse` has counts only. Tests `R8-03` and `R1-24: bulkAccept name type does not guess...` (`:1705-1780`) assert both caches **keep** the accepted groups. A search of that test file for `.total` returned no matches.

**Verdict rationale:** acceptName drop is implemented; a mutant that deleted the `dropClusterFromReviewCaches` call in `onSuccess` would leave `cluster-1` in the ids assertion and go red. Surviving sub-claims: (1) bulkAccept still never calls `dropClusterFromReviewCaches`, so loaded rows stay until refetch; (2) neither path asserts header `total`, so a mutant that dropped the row but skipped `total: Math.max(0, current.total - removed)` would not be killed by these tests.

### UXW2-2-R3-03 — FIXED

**Claim:** The R2-12 panel test asserted `queryByText('All caught up — no items need review')` is absent, but `WorkbenchFindingsPanel` never renders that string (empty copy is `No findings yet…`), so the assertion could not fail.

**Evidence:** The R2-12 case (`WorkbenchFindingsPanel.test.tsx:1154-1172`) no longer mentions `All caught up`. It asserts the panel's actual empty copy is absent and the repair live-region copy is present:

```1167:1172:apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx
    expect(screen.getByRole('button', { name: /^Resync findings$/ })).toBeInTheDocument();
    expect(
      screen.queryByText('No findings yet. Run a scan and new findings will appear here automatically.'),
    ).not.toBeInTheDocument();
    expect(screen.getByText('5 groups elsewhere are missing face data')).toBeInTheDocument();
    expect(screen.queryByText('5 groups missing face data')).not.toBeInTheDocument();
```

Empty copy in the panel (`WorkbenchFindingsPanel.tsx:508-511`): `No findings yet. Run a scan and new findings will appear here automatically.` Repair copy is inside the live region (`:387-435`) via `gatedClusterCopy` (`representativeVocabulary.ts:20-28`), which with `zeroEvidenceClusterCount: 0` + `topUnlabeledTruncated: true` + `unlabeledClusters: 5` yields `5 groups elsewhere are missing face data`. A file search of this test for `All caught up` returned no matches.

**Verdict rationale:** The unfalsifiable foreign-string assertion is gone. Mutant that rendered the empty copy while `hasFindings`/`repairPending` are true would fail `queryByText(...).not.toBeInTheDocument()`. Mutant that changed `gatedClusterCopy` off the "elsewhere" branch (or dropped the live-region paragraph) would fail `getByText('5 groups elsewhere are missing face data')`.

### UXW2-2-R3-04 — FIXED

**Claim:** `total` was `COUNT(*) OVER()` of the unfiltered set minus this page's mapper drops, so off-page invariant-failing rows were still counted and `total` was neither pre-drop nor post-drop consistent; FE `total > served` repair fallback and `At least N groups` copy inherited the skew.

**Evidence:** SQL `COUNT(*) OVER()` now sits on the same `COUNT(m) >= 2` predicate (`class-clusters-read-repository.php:240-250`). Local envelope does **not** subtract `$dropped` (`class-cluster-read-service.php:195-200`): when `total_count` is present, `$total = max(0, $total_count)`. Contract (`docs/workbay/contracts/clustering-api.md:308`) and schema (`packages/shared-contracts/schemas/recognition-cluster-top-unlabeled-response.schema.json:113`) both say drops set `repair_pending` and do not shrink `total`. Test `testListTopUnlabeledTotalIsPreFilterQualifyingCount` (`ClusterReadServiceTest.php:422-485`) seeds `total_count = 2`, drops one of two rows, and asserts `$data['total'] === 2` with `repair_pending` true. Proxy normalize also keeps upstream `total` (`class-cluster-response-envelope-service.php:153-161`).

**Verdict rationale:** The mixed global-minus-page-local rule is gone on the named local-projection path. `total` is documented and tested as pre-filter qualifying count; drops drive `repair_pending` only. A mutant that subtracted `$dropped` from `$total` would fail `assertSame(2, $data['total'])`. Missing-column fallback to post-drop `count($unlabeled_items)` is R4-05, not this finding.

### UXW2-2-R3-11 — FIXED

**Claim:** `_n()` in `ReviewQueue` used identical singular/plural **constants** and non-literal msgids, so wp i18n extraction could not pick them up.

**Evidence:** The only `_n()` calls in `ReviewQueue.tsx` are now inline string literals (`:990-998`):

```990:998:apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx
              {sprintf(
                filtersActive
                  ? _n('%d shown', '%d shown', length, 'alt-context')
                  : _n(
                      '%d left to review on this page',
                      '%d left to review on this page',
                      length,
                      'alt-context',
                    ),
```

**Verdict rationale:** Extraction-blocking non-literal msgids are gone. Singular and plural happen to be the same English copy, but they are literals, which is what the fix asked for. Did not run `wp i18n make-pot` (see Undone).

### UXW2-2-R3-12 — PARTIAL

**Claim:** `onLabel` announce + `focusQueueRoot` untested; ux-map card-zone states invented; `url_params` lacks `rq`.

**Evidence:** `ScanTabContent.tsx:205-208` announces `REVIEW_QUEUE_LABEL_SAVED_ANNOUNCE` then calls `focusQueueRoot` (`:61-63`). Test `announces name-saved copy and focuses the queue root after a label commit` (`ScanTabContent.labelAnnounce.test.tsx:98-106`) asserts live-region text and that `.acx-findings-detail-anchor` is `document.activeElement`. `workbench-scan.url_params` includes `rq` (`workbench-operator-loop.uxmap.json:82`). Card zone still:

```121:125:apps/prototype-wp-alt-context/docs/ux-maps/workbench-operator-loop.uxmap.json
          "id": "z-review-suggestions-group-card",
          "label": "Top-of-queue group card",
          "role": "ai_review",
          "states": ["default", "empty"],
          "code_ref": "apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/TopClusterCard.tsx"
```

Sibling render `workbench-operator-loop.md:72` repeats `states=[default,empty]`. `TopClusterCard` always requires a `cluster` (`:104-105`) and has real busy / missing-image / suggested-label branches (`:147`, `:178-201`, `:121-124`) — not an empty zone.

**Verdict rationale:** Announce/focus test and `rq` param claims are now false. Surviving: card-zone `empty` is still invented; missing-image / busy / suggested-label are still unmapped.

### UXW2-2-R4-04 — OPEN

**Claim:** `$mapper_ids` is the raw `requested_repair_cluster_ids()` array and drives both the drift-scan gate and `repair_pending`, while `schedule_repair_from_mapper` re-fetches and normalizes the same array (sanitize + drop-empty + `array_unique`). The two views diverge: 25 raw ids with duplicates skip the off-page scan while normalizing below the ceiling, and an all-blank array can set `repair_pending` true while normalized `[]` schedules nothing.

**Evidence:** Gate and flag still use the raw array (`class-cluster-read-service.php:189-203`):

```189:203:apps/prototype-wp-alt-context/src/api/services/class-cluster-read-service.php
			$mapper_ids = $this->dependencies->cluster_mapper->requested_repair_cluster_ids();
			$extra_ids  = array();
			if ( count( $mapper_ids ) < self::TARGETED_REPAIR_ID_CEILING ) {
				$extra_ids = $this->dependencies->clusters_repository->list_unlabeled_identity_count_drift( $tenant_id );
			}
			$this->schedule_repair_from_mapper( $tenant_id, $extra_ids );
			$dropped = $this->dependencies->cluster_mapper->dropped_cluster_count();
			$total   = count( $unlabeled_items );
			$total_count = null;
			if ( isset( $sovereign_data['clusters'][0]['total_count'] ) && is_numeric( $sovereign_data['clusters'][0]['total_count'] ) ) {
				$total_count = (int) $sovereign_data['clusters'][0]['total_count'];
				$total       = max( 0, $total_count );
			}
			$fetched_page = count( $sovereign_data['clusters'] );
			$repair_pending = array() !== $mapper_ids || $dropped > 0 || array() !== $extra_ids;
```

`schedule_repair_from_mapper` independently re-reads and normalizes (`:420-429`, `:437-441`). `TARGETED_REPAIR_ID_CEILING` is 25 (`:43`).

**Verdict rationale:** The split is still in the tree. Raw `count($mapper_ids)` still gates the drift scan; raw `array() !== $mapper_ids` still contributes to `repair_pending`; scheduling still uses a second normalized copy. Mapper currently skips empty ids before push (`class-cluster-response-mapper.php:311-328`), so the all-blank flag may be hard to hit from this mapper, but the duplicate-ceiling skip and the metadata/behaviour split remain as written.

### UXW2-2-R4-05 — OPEN

**Claim:** When `total_count` is absent, `$total` silently falls back to `count($unlabeled_items)` (post-drop served count), which clustering-api and schema forbid (`drops … do not shrink total`). The truncated fallback is specified (`false` when the column is missing); the total fallback is not specified, not documented, and no test covers a page with a drop and no `total_count`.

**Evidence:** Fallback is still first-assignment to the served list (`class-cluster-read-service.php:196-201`):

```196:201:apps/prototype-wp-alt-context/src/api/services/class-cluster-read-service.php
			$total   = count( $unlabeled_items );
			$total_count = null;
			if ( isset( $sovereign_data['clusters'][0]['total_count'] ) && is_numeric( $sovereign_data['clusters'][0]['total_count'] ) ) {
				$total_count = (int) $sovereign_data['clusters'][0]['total_count'];
				$total       = max( 0, $total_count );
			}
```

`truncated` is `null !== $total_count && $total_count > $fetched_page` (`:210`) — false when the column is missing. Schema (`recognition-cluster-top-unlabeled-response.schema.json:113`) and contract (`clustering-api.md:308`) still say drops do not shrink `total`. A search of `ClusterReadServiceTest.php` for a missing-column + drop total case found none; the R3-04 total test always seeds `total_count => 2`.

**Verdict rationale:** The claim still holds. A fixture/repository path that omits `total_count` and then mapper-drops a row publishes post-drop `total`, reverting the R3-04 rule with no failing test.

### UXW2-2-R4-06 — FIXED

**Claim:** `docs/tasks/uxw2/UXW2-2-r1-fix-report.md` L3 still reads `Branch \`master\``, the same falsehood previously flagged on root `REPORT.md`.

**Evidence:** Current L3 (`UXW2-2-r1-fix-report.md:3`):

```
Adversarial-review close-out. Branch `feature/uxw2-2`. Full suite: **OK (1790 tests, 8624 assertions)** (`cd apps/prototype-wp-alt-context && composer test`). `composer lint` not defined.
```

R3 header (`:201`) also names `feature/uxw2-2`.

**Verdict rationale:** The cited L3 falsehood is gone. (R2 body `:115` still says "this lane commits on `master` as specified"; that is not the L3 claim.)

### UXW2-2-R4-07 — FIXED

**Claim:** `## Undone` is `(empty)` while known-open work remained, which suppressed the reviewer-facing residual list.

**Evidence:** Current section (`UXW2-2-r1-fix-report.md:277-287`) is not `(empty)`. It lists R3-02, R3-04 proxy residual, R4-02, R4-03, R5-12, R4-04/R4-05/R1-07, and report-truth siblings.

**Verdict rationale:** The empty-Undone deferral is gone. Accuracy of those residual bullets is out of this finding's scope (several look stale against this audit).

## Tally

FIXED: 7 | PARTIAL: 2 | OPEN: 2 | UNVERIFIABLE: 0

## Undone

- No mutant was executed and no test suite was run; kill-power arguments are from reading assertions only.
- Did not run `wp i18n make-pot` to empirically confirm msgid extraction for R3-11.
- Did not execute the drift / singleton SQL against a live database.
- Findings outside this shard were not reviewed.
- R4-07's leftover bullets were not re-litigated as their own findings except where they overlap this list.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.
