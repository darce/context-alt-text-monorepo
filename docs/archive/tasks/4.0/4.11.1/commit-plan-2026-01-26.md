# Commit Plan (Excluding P0/P1 Files)

Date: 2026-01-26

This plan lists atomic commit statements for all modified/untracked files **except** those tied to P0/P1 in `false-positive-analysis.md`.

## Excluded (P0/P1) files
Do **not** stage/commit these in the steps below:

- `apps/prototype-wp-alt-context/js/admin/styles/components/_media-selection.scss`
- `apps/prototype-wp-alt-context/src/api/class-api.php`
- `apps/prototype-description-service/recognition/application/settings/clustering.py`
- `apps/prototype-description-service/recognition/application/orchestration/curation/cluster_mutations.py`
- `apps/prototype-description-service/recognition/domain/suggestion.py`
- `apps/prototype-description-service/recognition/domain/repositories.py`
- `apps/prototype-description-service/recognition/application/suggestions/merge_suggestions.py`
- `apps/prototype-description-service/recognition/infrastructure/repositories/merge_suggestion_repository.py`
- `apps/prototype-description-service/recognition/infrastructure/repositories/__init__.py`
- `apps/prototype-description-service/recognition/application/orchestration/cluster_service.py`
- `apps/prototype-description-service/recognition/application/orchestration/protocols.py`
- `apps/prototype-description-service/recognition/interface_adapters/http/deps/services.py`
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/suggestions.py`
- `apps/prototype-description-service/recognition/interface_adapters/http/schemas/responses.py`
- `apps/prototype-description-service/recognition/tests/unit/test_merge_suggestions.py`
- `apps/prototype-description-service/recognition/tests/integration/test_curation_logic.py`
- `apps/prototype-description-service/recognition/tests/unit/test_curriculum_thresholds.py`
- `apps/prototype-wp-alt-context/js/admin/api/recognition/identityApi.ts`
- `apps/prototype-wp-alt-context/js/admin/api/recognition/types/suggestion.ts`
- `apps/prototype-wp-alt-context/js/admin/api/recognition/index.ts`
- `apps/prototype-wp-alt-context/js/admin/api/queryKeys.ts`
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/SuggestionReviewPanel.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/SuggestionReviewPanel.test.tsx`
- `apps/prototype-wp-alt-context/src/admin/class-admin.php`
- `apps/prototype-wp-alt-context/src/api/class-recognition-controller.php`

## Local artifacts (recommended to keep out of history)
If you want a clean commit series, remove or ignore these instead of committing:

- `apps/prototype-description-service/.docker-compose.db.yml.swp`
- `apps/prototype-description-service/logs/archive/`
- `apps/prototype-description-service/logs/scan_worker.log`
- `apps/prototype-description-service/logs/recognition.log`
- `apps/prototype-description-service/recognition/application/labeling/__pycache__/`

## Commit statements

### 1) Ignore editor settings and MCP logs

```
git restore --staged apps/prototype-wp-alt-context/vite.config.ts || true
git add .gitignore
git commit -m "chore: ignore editor settings and MCP logs"
```

### 2) Add recognition log management targets

```
git add apps/prototype-description-service/Makefile
git commit -m "chore: add recognition log maintenance targets"
```

### 3) Default InsightFace device to CPU on macOS

```
git add apps/prototype-description-service/recognition/config/settings.py
git commit -m "fix(insightface): default to cpu to avoid CoreML errors"
```

### 4) Configurable maturity thresholds + quality adjustments

```
git add \
  apps/prototype-description-service/recognition/domain/maturity.py \
  apps/prototype-description-service/recognition/application/assignment/quality.py \
  apps/prototype-description-service/recognition/application/assignment/checks/confidence.py \
  apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py \
  apps/prototype-description-service/recognition/tests/unit/test_confidence_check.py \
  apps/prototype-description-service/recognition/tests/unit/test_identity_quality.py \
  apps/prototype-description-service/recognition/tests/unit/test_assignment_gate.py \
  apps/prototype-description-service/recognition/tests/unit/test_assignment_gate_defaults.py \
  apps/prototype-description-service/recognition/tests/unit/test_assignment_writer_interface.py \
  apps/prototype-description-service/recognition/tests/unit/test_centroid_discovery.py \
  apps/prototype-description-service/recognition/tests/unit/test_centroid_recomputation.py \
  apps/prototype-description-service/recognition/tests/unit/test_graph_discovery.py \
  apps/prototype-description-service/recognition/tests/unit/test_representative_discovery.py \
  apps/prototype-description-service/recognition/tests/unit/test_representative_lifecycle.py \
  apps/prototype-description-service/recognition/tests/unit/test_representative_matcher.py \
  apps/prototype-description-service/recognition/tests/unit/test_cluster_service.py

git commit -m "feat(recognition): make maturity + quality adjustments configurable"
```

### 5) Auto-labeling + eligibility and assignment writer updates

```
git add \
  apps/prototype-description-service/recognition/application/labeling/*.py \
  apps/prototype-description-service/recognition/application/persistence/assignment_writer.py \
  apps/prototype-description-service/recognition/application/settings/__init__.py \
  apps/prototype-description-service/recognition/application/suggestions/eligibility.py \
  apps/prototype-description-service/recognition/tests/unit/test_auto_labeler.py \
  apps/prototype-description-service/recognition/tests/unit/test_eligibility.py \
  apps/prototype-description-service/recognition/tests/integration/test_auto_label_integration.py

git commit -m "feat(recognition): add auto-labeling and eligibility support"
```

### 6) Split execution refactor + stronger split/merge assertions

```
git add \
  apps/prototype-description-service/recognition/application/orchestration/split/executor.py \
  apps/prototype-description-service/recognition/tests/integration/test_split_worker.py \
  apps/prototype-description-service/recognition/tests/integration/test_cluster_operations.py

git commit -m "refactor(recognition): extract split helpers and tighten assertions"
```

### 7) Suggestion list returns details + API contract updates

```
git add \
  apps/prototype-description-service/recognition/infrastructure/repositories/suggestion_repository.py \
  apps/prototype-description-service/recognition/application/suggestions/service.py \
  apps/prototype-description-service/recognition/application/suggestions/refresh_service.py \
  apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py \
  apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py \
  apps/prototype-description-service/recognition/interface_adapters/http/schemas/requests.py \
  apps/prototype-description-service/recognition/tests/api/conftest.py \
  apps/prototype-description-service/recognition/tests/api/test_api_clusters.py \
  apps/prototype-description-service/recognition/tests/api/test_wordpress_contract.py \
  apps/prototype-description-service/recognition/tests/conftest.py

git commit -m "refactor(suggestions): return pending details and update API tests"
```

### 8) Recognition pipeline and task updates

```
git add \
  apps/prototype-description-service/recognition/application/clustering/constrained_hac.py \
  apps/prototype-description-service/recognition/application/tasks/scan.py \
  apps/prototype-description-service/recognition/worker/handlers/clustering.py \
  apps/prototype-description-service/recognition/tests/integration/test_assignment_writer.py \
  apps/prototype-description-service/recognition/tests/integration/test_cluster_repository.py \
  apps/prototype-description-service/recognition/tests/integration/test_end_to_end.py \
  apps/prototype-description-service/recognition/tests/integration/test_pipeline_integration.py

git commit -m "feat(recognition): tune clustering workflow and integration tests"
```

### 9) Schema/model updates for identity clustering

```
git add \
  apps/prototype-description-service/db/migrations/versions/001_identity_schema.py \
  apps/prototype-description-service/db/models.py \
  apps/prototype-description-service/db/models/__init__.py \
  apps/prototype-description-service/db/models/constraints.py \
  apps/prototype-description-service/db/models/identity.py \
  apps/prototype-description-service/db/models/tenant.py

git commit -m "feat(db): update identity cluster schema and defaults"
```

### 10) Script cleanup + formatting tweaks

```
git add -A apps/prototype-description-service/scripts scripts

git commit -m "chore(scripts): prune obsolete diagnostics utilities"
```

### 11) Workbench pagination, progress UI, and related tests

```
git add \
  apps/prototype-wp-alt-context/js/admin/hooks/useWorkbenchMedia.ts \
  apps/prototype-wp-alt-context/js/admin/hooks/useJobProgressStream.ts \
  apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useWorkbenchMedia.test.tsx \
  apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useJobProgressStream.test.tsx \
  apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx \
  apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx \
  apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx \
  apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx \
  apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/WorkbenchPage.integration.test.tsx \
  apps/prototype-wp-alt-context/js/admin/pages/roster/utils/mediaMeta.ts \
  apps/prototype-wp-alt-context/js/admin/styles/components/_workbench.scss \
  apps/prototype-wp-alt-context/package.json \
  apps/prototype-wp-alt-context/vite.config.ts

git commit -m "feat(workbench): add page-size controls and progress UX"
```

### 12) MVP batch-limit removal + PHP test scaffolding

```
git add \
  apps/prototype-wp-alt-context/js/admin/api/config.ts \
  apps/prototype-wp-alt-context/js/admin/api/recognition/scanApi.ts \
  apps/prototype-wp-alt-context/src/support/trait-batch-limits.php \
  apps/prototype-wp-alt-context/phpunit.xml.dist \
  apps/prototype-wp-alt-context/tests/TestCase.php \
  apps/prototype-wp-alt-context/tests/stubs/wp.php \
  apps/prototype-wp-alt-context/tests/Unit

git commit -m "feat(batch-limits): disable tier caps for MVP and update tests"
```

### 13) Documentation updates (contracts, diagrams, task notes)

```
git add \
  docs/agentic \
  docs/architecture/rules \
  docs/tasks/4.0/4.10.3 \
  docs/tasks/4.0/4.11.0 \
  docs/tasks/4.0/4.11.1 \
  docs/troubleshooting

git commit -m "docs: refresh contracts, diagrams, and task notes"
```

