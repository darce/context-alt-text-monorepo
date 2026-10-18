# Wire Suggested Label Through Sovereign Sync

## Problem Statement

After cluster analysis completes, the SuggestionReviewPanel shows "No suggestions to review yet" instead of the expected "Is this X?" dialog. The Python backend generates `suggested_label` via `infer_suggested_label()`, but the WordPress sovereign sync layer has no mechanism to receive, store, or surface those suggestions. The PHP mapper hardcodes `suggested_label: null`.

## Workflow Principles

- Suggestions are ephemeral enrichments computed at read time; they are NOT user curation decisions and must never block or override curation state.
- `is_user_confirmed = 1` clusters must never receive a `suggested_label`; inference only applies to unlabeled, unconfirmed clusters.
- Label inference runs on the Python backend (has access to embeddings, roster, merge suggestions); the PHP layer reads pre-computed results, not re-implements inference.

## Terminology

- **suggested_label**: A label inferred by the Python backend for an unlabeled cluster, based on embedding similarity, roster matches, or pending merge suggestions.
- **label inference**: The Python-side process (`infer_suggested_label`) that computes a suggested label, source, confidence, and optional merge target for a cluster.
- **sovereign sync**: The snapshot projection mechanism that replicates backend cluster/member data into WordPress local tables.

## Current State Analysis

- Python `get_top_unlabeled_clusters` endpoint calls `infer_suggested_label()` per cluster and returns `suggested_label`, `suggested_label_source`, `suggested_label_confidence`, `suggested_target_cluster_id` in `ClusterResponse`.
- Python `get_tenant_cluster_snapshot` endpoint uses `ClusterSnapshotClusterResponse` which does NOT include suggested_label fields.
- Python `get_tenant_cluster_delta` endpoint also uses `ClusterSnapshotClusterResponse` (same response class as full snapshot); both paths must be enriched.
- PHP `wp_acx_clusters` table has no columns for suggested_label fields.
- PHP `merge_snapshot_for_tenant` does not handle suggested_label columns.
- PHP `map_top_unlabeled_clusters` in `class-cluster-response-mapper.php` hardcodes `suggested_label => null` (line ~99).
- PHP `list_top_unlabeled` SQL query (`SELECT c.*`) would automatically pick up new columns if added to the table.
- Frontend `TopUnlabeledCluster` TypeScript type already defines `suggested_label`, `suggested_label_source`, `suggested_label_confidence`, `suggested_target_cluster_id` as optional fields.
- Frontend `TopClusterCard` in `TopClustersSection.tsx` already renders "Is this X?" when `suggested_label` is non-null.

## Proposed Solution

Add suggested_label fields to the snapshot contract and flow them through the sovereign sync layer. Both the full snapshot endpoint (`get_tenant_cluster_snapshot`) and the delta endpoint (`get_tenant_cluster_delta`) will run label inference for unlabeled clusters before returning the response. Both endpoints share `ClusterSnapshotClusterResponse` and the `_build_cluster_responses` helper, so the enrichment is applied post-build on the response objects (not inside `_build_cluster_responses` itself, since `IdentityCluster` has no suggested_label fields). The PHP side stores these as advisory columns that are always overwritten on sync (never curation-guarded). The PHP mapper reads the columns from the database instead of hardcoding null.

To avoid N+1 performance issues, inference is bounded to the top N unlabeled clusters by `identity_count` (descending). Clusters beyond the cap receive null suggested_label. This matches the existing pattern in `get_top_unlabeled_clusters` which also limits inference to a small set.

This approach keeps inference logic centralized in Python, avoids duplicating embedding/similarity logic in PHP, and piggybacks on the existing snapshot sync mechanism. No new API calls are needed from the frontend or PHP layer.

## Patterns to Follow

### Python: Enrich Snapshot With Suggested Labels

The snapshot endpoint should call `infer_suggested_label` for unlabeled clusters, matching the pattern already used in `get_top_unlabeled_clusters`:

```python
# Shared helper used by BOTH get_tenant_cluster_snapshot and get_tenant_cluster_delta.
# Called AFTER _build_cluster_responses, on response objects (not domain objects).
from recognition.application.suggestions.label_inference import infer_suggested_label

_INFERENCE_CAP = 20  # Bound inference to top N unlabeled clusters by identity_count

async def _enrich_with_suggested_labels(
    cluster_responses: list[ClusterSnapshotClusterResponse],
    tenant_id: str,
    session: AsyncSession,
    repo: ClusterRepository,
    settings: ClusteringSettings,
) -> None:
    """Best-effort label inference for unlabeled clusters, bounded to top N."""
    unlabeled = [
        cr for cr in cluster_responses
        if cr.label is None and not cr.is_user_confirmed
    ]
    # Sort by identity_count descending so highest-value clusters get inference first
    unlabeled.sort(key=lambda cr: cr.identity_count, reverse=True)

    for cluster_resp in unlabeled[:_INFERENCE_CAP]:
        try:
            inferred = await infer_suggested_label(
                tenant_id=tenant_id,
                cluster_id=cluster_resp.cluster_uuid,
                session=session,
                cluster_repository=repo,
                settings=settings,
            )
            if inferred:
                cluster_resp.suggested_label = inferred.label
                cluster_resp.suggested_label_source = inferred.source.value
                cluster_resp.suggested_label_confidence = inferred.confidence
                cluster_resp.suggested_target_cluster_id = inferred.target_cluster_id
        except Exception:
            pass  # best-effort enrichment
```

### PHP: Sync Merge With Advisory Columns

Suggested_label columns are always overwritten on sync (not curation-guarded), since they are backend-computed suggestions, not user decisions:

```sql
ON DUPLICATE KEY UPDATE
    -- existing curation-guarded columns ...
    suggested_label = VALUES(suggested_label),
    suggested_label_source = VALUES(suggested_label_source),
    suggested_label_confidence = VALUES(suggested_label_confidence),
    suggested_target_cluster_id = VALUES(suggested_target_cluster_id),
```

### PHP: Clear Suggested Label On User Confirmation

When a user labels a cluster (`update_label`), the suggested_label columns should be NULLed since the suggestion is no longer relevant:

```php
// In ClustersRepository::update_label, add to the UPDATE SET clause:
'suggested_label = NULL',
'suggested_label_source = NULL',
'suggested_label_confidence = NULL',
'suggested_target_cluster_id = NULL',
```

### PHP: Mapper Reads From Database

```php
$results[] = array(
    // ... existing fields ...
    'suggested_label'             => $row['suggested_label'] ?? null,
    'suggested_label_source'      => $row['suggested_label_source'] ?? null,
    'suggested_label_confidence'  => isset( $row['suggested_label_confidence'] )
        ? (float) $row['suggested_label_confidence']
        : null,
    'suggested_target_cluster_id' => $row['suggested_target_cluster_id'] ?? null,
);
```

## Functions to Change

| File | Target | Change |
| --- | --- | --- |
| `apps/prototype-description-service/recognition/interface_adapters/http/schemas/responses.py` | `ClusterSnapshotClusterResponse` | Add `suggested_label`, `suggested_label_source`, `suggested_label_confidence`, `suggested_target_cluster_id` fields |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | `get_tenant_cluster_snapshot` | Add `session` (AsyncSession) and `clustering_settings` (ClusteringSettings) deps; call `_enrich_with_suggested_labels` after `_build_cluster_responses` |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | `get_tenant_cluster_delta` | Add `session` and `clustering_settings` deps; call `_enrich_with_suggested_labels` after `_build_cluster_responses` |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | `_enrich_with_suggested_labels` (NEW) | Shared helper: runs bounded `infer_suggested_label` on top N unlabeled response objects |
| `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php` | clusters table CREATE TABLE | Add 4 columns: `suggested_label text NULL`, `suggested_label_source varchar(30) NULL`, `suggested_label_confidence decimal(5,4) NULL`, `suggested_target_cluster_id varchar(64) NULL` |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php` | `merge_snapshot_for_tenant` | Add 4 columns to INSERT column list and VALUES; add non-guarded UPDATE clauses |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php` | `update_label` | NULL out suggested_label columns when user confirms a label |
| `apps/prototype-wp-alt-context/src/sovereign/mappers/class-cluster-response-mapper.php` | `map_top_unlabeled_clusters` | Read suggested_label fields from `$row` instead of hardcoding null |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/recognition/application/suggestions/label_inference.py` | Existing inference logic; called but not modified |
| `apps/prototype-description-service/recognition/domain/suggestion.py` | `SuggestedLabel` dataclass and `SuggestedLabelSource` enum; not modified |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/types/cluster.ts` | `TopUnlabeledCluster` type already has suggested_label fields; no changes needed |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/TopClustersSection.tsx` | Already renders "Is this X?" when suggested_label is non-null; no changes needed |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/clusterApiQueries.ts` | `normalizeTopUnlabeledCluster` passes through all fields; no changes needed |
| `docs/agentic/contracts/cluster-snapshot-api.md` | Must be updated to document the 4 new fields in the cluster snapshot response |
| `docs/agentic/contracts/cluster-delta-api.md` | Must be updated to document the 4 new fields in the cluster delta response (same fields as snapshot) |
| `packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json` | Must add the 4 new cluster-level fields to the machine-readable JSON schema (canonical alongside the markdown contract) |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php` | Passes `$snapshot['clusters']` and `$delta['clusters']` to repository; no changes needed (fields flow through array keys automatically) |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | `get_tenant_cluster_delta` already calls `_build_cluster_responses`; enrichment helper is additive |

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `backend-http` | `apps/prototype-description-service/recognition/interface_adapters/http/**` | None | `PYENV_VERSION=description-service pytest recognition/tests/unit/ -q` |
| `wp-proxy` | `apps/prototype-wp-alt-context/src/**`, `apps/prototype-wp-alt-context/tests/Unit/**` | `backend-http` (contract only) | `cd apps/prototype-wp-alt-context && vendor/bin/phpunit` |
| `frontend` | `apps/prototype-wp-alt-context/js/**` | `wp-proxy` (contract only) | `cd apps/prototype-wp-alt-context && npx vitest run` |

### Merge Order

1. `backend-http` (schema + endpoint changes)
2. `wp-proxy` (DB columns + merge + mapper)
3. `frontend` (verification only; no code changes expected)

### Manifest

```bash
make lane-manifest-init TASK=wire-suggested-label-through-sovereign-sync LANE_IDS='backend-http wp-proxy frontend' TASK_PLAN=docs/tasks/10.0/10.2/wire-suggested-label-through-sovereign-sync.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools (`worker_start_all`, `worker_status`, `worker_stop`) with `backend="codex-subagent"`. The orchestrator daemon dispatches work, intakes merge-ready lanes, and refreshes downstream dependents automatically.
- **Shell fallback**: Use `make lane-open`, `make lane-run`, `make lane-handoff`, and `make lane-intake` from the orchestrator root.

---

# Consolidated Checklist

## Completed

- [x] Frontend `TopUnlabeledCluster` type already defines suggested_label fields
- [x] Frontend `TopClusterCard` already renders "Is this X?" dialog when `suggested_label` is non-null
- [x] Python `infer_suggested_label` already works in `get_top_unlabeled_clusters` endpoint

## Phase 0: Scaffolding

- [x] Update `docs/agentic/contracts/cluster-snapshot-api.md` with the 4 new cluster fields
- [x] Update `docs/agentic/contracts/cluster-delta-api.md` with the 4 new cluster fields
- [x] Update `packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json` with the 4 new cluster fields
- [x] Add suggested_label fields to `ClusterSnapshotClusterResponse` Pydantic model
- [x] Add 4 columns to `wp_acx_clusters` CREATE TABLE in `class-life-cycle-manager.php`
- [x] Verify scaffolds compile: `mypy .` / `npm run typecheck`

## Phase 1: Python Snapshot + Delta Enrichment

- [x] Create `_enrich_with_suggested_labels` shared helper with bounded inference cap (top N unlabeled by identity_count)
- [x] Add `session` (AsyncSession) and `clustering_settings` (ClusteringSettings) dependencies to `get_tenant_cluster_snapshot` signature (repo already available)
- [x] Call `_enrich_with_suggested_labels` in `get_tenant_cluster_snapshot` after `_build_cluster_responses`
- [x] Add `session` and `clustering_settings` dependencies to `get_tenant_cluster_delta` signature
- [x] Call `_enrich_with_suggested_labels` in `get_tenant_cluster_delta` after `_build_cluster_responses`
- [x] Unit test: snapshot response includes suggested_label for unlabeled cluster
- [x] Unit test: snapshot response has null suggested_label for user-confirmed cluster
- [x] Unit test: delta response includes suggested_label for unlabeled cluster
- [x] Unit test: inference is bounded to cap (clusters beyond cap have null suggested_label)

## Phase 2: PHP Schema + Sync

- [x] Add 4 columns to clusters table in `class-life-cycle-manager.php`
- [x] Update `merge_snapshot_for_tenant` INSERT column list and VALUES with 4 new columns
- [x] Add non-guarded UPDATE clauses for suggested_label columns (always overwritten by sync)
- [x] Update `update_label` to NULL out suggested_label columns when user confirms
- [x] Update `map_top_unlabeled_clusters` to read suggested_label fields from `$row`
- [x] Unit test: merge_snapshot writes suggested_label columns
- [ ] Unit test: merge_snapshot overwrites suggested_label even for curated clusters
- [x] Unit test: update_label clears suggested_label columns
- [x] Unit test: map_top_unlabeled_clusters returns suggested_label from DB row

## Phase 3: Integration Verification

- [ ] Deactivate and reactivate plugin to trigger schema update via `dbDelta`
- [x] Run full Python test suite (390 passed, 1 skipped)
- [x] Run full PHP test suite (388 passed, 1623 assertions)
- [x] Run full Vitest suite (412 passed, 51 files; no frontend code changes expected; existing tests should pass)
- [ ] Manual smoke test: run analysis, verify "Is this X?" appears for clusters with similar labeled neighbors

## Success Criteria

- [ ] After cluster analysis, `GET /acx/v1/recognition/clusters/top-unlabeled` returns clusters with non-null `suggested_label` when inference matches exist
- [ ] SuggestionReviewPanel displays "Is this X?" dialog for clusters with inferred labels
- [ ] User-confirmed clusters never show a suggested_label
- [ ] Labeling a cluster clears its suggested_label columns
- [ ] Snapshot sync overwrites suggested_label on each pull (not curation-guarded)
