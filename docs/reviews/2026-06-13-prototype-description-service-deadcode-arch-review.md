# prototype-description-service — Dead Code, Obsolete Docs & Architecture-Navigability Review

**Date:** 2026-06-13 · **Scope:** `apps/prototype-description-service` · **Branch:** `feature/maint-descsvc-deadcode-20260613`
**Driver:** `/review-parallel` (literature-grounded), concentrate on dead code, obsolete documentation, and "architecture easier to reason about instead of deep implementations where agents get lost."

> **Findings-of-record caveat:** the `workbay-handoff-mcp` MCP tools and the local Python API were unavailable during the review (the package is not installed in this checkout). The slice-complete decision was later recorded via `uvx --from mcp-workbay-handoff` under task `MAINT-descsvc-deadcode-20260613`, but the 96 individual findings were not batch-recorded. This report is the durable findings artifact; when MCP tooling is restored, backfill the surviving findings via `review_findings(operation="batch_record")` under this branch's task ref.

## Execution status (this branch)

| Slice | Status | Commit |
|---|---|---|
| Review report | ✅ landed | `73e7ffc0` |
| Slice 3 — obsolete-doc fixes (9 docs) | ✅ landed | `25c7ff9e` |
| Slice 1a — verified dead-module deletion (900 LOC) | ✅ landed | `08763c6c` |
| Slice 1b — `db_export.py` + `ScheduledDisposalWorker` (454 LOC) | ✅ landed | `466ab50f` |
| Slice 2a — small dead-symbol sweep, no-test-edit items (174 LOC) | ✅ landed | `92d042b5` |
| Slice 2b — dead background fn + 2 logger methods (test-edit items) | ✅ landed | `7184e834` |
| Branch review — parallel re-review of the cleanup (pass_with_findings) → 3 in-place fixes (TRANSFORMERS_CACHE config lockstep, orphan logger stub, dead `TypeVar`) | ✅ landed | `160ae3fd` |
| Slice 4 — indirection collapse (inline shim, delete `DiscoveryAlgorithm` ABC + `ClusterVisualizer` + 3 dead params + leaf shim, 228 LOC) | ✅ landed | `144ff3a2` |
| Slice 5 — domain-boundary move (DOMAIN-1: 5 impure services `domain/services/` → `application/services/`) | ✅ landed | `485c06e6` |
| Branch re-review fixes (DESC-REV-B-01..04: dead matplotlib dep + MPLCONFIGDIR config, stale `.dockerignore scene/tests`, ruff format, test typing) | ✅ landed | `a0ce0c43` |
| Dead clustering-residue config prune (mypy overrides for deleted modules + `onnxruntime.*`/`sklearn.*` globs; dead direct `scikit-learn` dev dep) | ✅ landed | `9cf931ed` |
| Slice 6 — `clusters.py` router split (4 concern routers + `assert_tenant_match` shared dep; route surface byte-identical, 39/39 bodies verified faithful) | ✅ landed | `85400e40` |
| Slice 7 — DI consolidation: collapse 3 re-export surfaces to one canonical `deps/__init__`, delete `dependencies.py` + `suggestion_details` shim, repoint 49 files (route surface byte-identical) | ✅ landed | `c48ba534` |
| Slice 7 — parallel branch re-review (2 reviewers, **pass**, 0 findings: union complete, dependency identity preserved, zero residual refs) | ✅ verified | `66d996b7` |
| Slice 8a — `ScanWorker._process_pending_clustering_jobs` phase extraction (WORKEROBS-6): claim/dispatch/failure-recovery seams + 6 unit tests; behaviour-preserving | ✅ landed | `11ae8ee0` |
| Slice 8a parallel re-review (2 reviewers; **pass_with_findings**) → 2 in-place fixes: ruff-format drift the slice's "ruff clean" missed (BR-01) + orchestrator `except` `# pragma: no cover` removed with 3 wiring tests (BR-02) | ✅ verified | `5a421e10` |
| Slice 8b — ORCH-4 (partial): extract `evaluate_chunk_candidates` + `partition_unclustered` chunk seams from `_process_chunks` into `discovery_pipeline.py` + 5 unit tests; behaviour-preserving (suite 1070) | ✅ landed | `de0e2187` |
| Slice 8b parallel re-review (2 reviewers; **pass_with_findings**) → 1 in-place fix: unit-pin `partition_unclustered` multi-proposal/multi-member flatten (BR-01) | ✅ verified | `b8e6cbbf` |
| Slice 8c — ORCH-4 finish: `_process_chunks` 233L→71L thin loop + `_process_single_chunk` orchestrator + 3 named phase methods (`_persist_accepted_assignments`, `_create_new_clusters_for_chunk`, `_commit_chunk_progress`) + 4 unit tests; behaviour-preserving (suite 1075) | ✅ landed | `c23bf65c` |
| ORCH-4 final parallel review (2 reviewers; REV-A 0 findings end-to-end behaviour-preservation, REV-B **pass_with_findings**) → 1 in-place fix: 2 unit tests pinning the graph-fallback→HAC exclusion (BR-01) | ✅ verified | `cd58d973` |
| Slice 8 — PERSREG-5 (`generate_canonical_report` phase extraction) + BR-01/02 fixes | ✅ landed | `16a74b83` |
| Slice 8 — INFRA-5 (`refresh_centroids_view` fail-fast: repo propagates, purge warns) | ✅ landed | `81602226` |
| INFRA-5 parallel re-review (2 reviewers; **pass_with_findings**) → best-effort post-merge refresh so a transient MV hiccup no longer rolls back a completed user-facing merge/bulk-batch (REVA-01/02, REVB-01) + happy-path/RLS-order test (REVB-02) | ✅ verified | `f0d0fb6d` |
| Slice 8 remainder — INFRA-3 (`ensure_media_identity` placeholder fabrication dropped from prod write paths → moved to `recognition/tests/db_seed.py` + `seed_media_identity` fixture; FK enforces integrity, new `test_repository_fk_integrity.py`; suite 1115) → parallel review (2 reviewers; **pass**, 0 findings) | ✅ landed | `0d1a667d` |
| INFRA-3 deeper re-review (5 lenses A/D/E via workflow + inline B/C after usage-limit; **pass_with_findings**) → 1 low finding INFRA3-RR-01: suggestion write path lost its FK-contract test (symmetric removal, asymmetric coverage) → added `test_create_suggestion_with_unknown_identity_raises_fk_error` | ✅ verified | `3dbe9a4e` |
| Follow-up — `_NotImplemented*` retention 503 path: `get_retention_policy_service` raises **503** on breaker-open (was misleading 501); 5 dead stub classes + `except ModuleNotFoundError` fallbacks removed; new TDD test pins 503 (45 tests green) | ✅ landed | `40276ab8` |
| Full 5-lens dual re-review (workflow, 15 agents): INFRA-3 changeset **pass** (0 findings; 2 candidates refuted) + retention-503 slice **pass_with_findings** → RET503-RR-01 (501→503 pinned only at factory unit) → added router-level 503 integration test | ✅ verified | `10a34a73` |
| Slice 9 increment 1 — centralize `CLUSTERING_JOB_TYPES` frozenset (2 dup sites in `job_repository.py` → `domain/job.py` beside `TERMINAL_JOB_STATUSES`); behaviour-preserving; new membership + re-dup-guard tests | ✅ landed | `a8d76622` |
| Slice 9 increment 2 — extract `CentroidMaintainer` from `AssignmentWriter` (`recompute_centroid` + MV-refresh seam → own class; AssignmentWriter delegates, public API preserved across 9 callers); behaviour-preserving, 56 tests green | ✅ landed | `ebd60730` |
| Slice 9 remaining — extract `RepresentativeSelector` from `AssignmentWriter` (`_should_add_representative`/`_select_*`/`recompute_representatives` + rep helpers; entangled with `self._last_*` state, more involved); `ClusterRepository` Protocol prefix-seam split (**high risk** — DOMAIN-5 refuted the broad split, ~20 direct consumers; needs explicit go-ahead) | ⏳ planned | — |

**Intentional non-removals** (verified by the re-review): `get_cluster_service` + `InMemoryJobService` deferred to **Slice 7** (only on the `dependencies.py` re-export surface that slice deletes; `InMemoryJobRepository` at the adjacent line is **live** — do not confuse); `compute_centroid` left (live test helper); `retry_matching` kept (live, `curation_job` calls it — review over-bundled it).

Validation per landed slice: repo-wide reference grep (zero residual refs), `ruff` (incl. autofix), `pytest --collect-only` (whole-tree import safety), and `pytest` against a live Postgres. Closing gate: **full suite green — 1046 passed, 2 skipped** at `9cf931ed` (net cleanup since the branch opened: ~−1,600 LOC). **No merge to `main`** — the pre-merge gate (`handoff_close_check`) requires MCP, which was degraded; merge when MCP is restored.

## Method & provenance

Parallel multi-agent review: literature rubric distilled from `literature/extracted/refactoring/distilled/` (Fowler/Beck *Refactoring*, *Modern Software Engineering*, *Using Asyncio in Python*, *Release It!*) → **11 partition reviewers** over the service → **per-finding adversarial verification** (every finding got an independent skeptic instructed to refute it; dead-code claims required a repo-wide reachability proof) → synthesis.

- **Agents:** 133 · **Tool calls:** ~1,250 · **Reviewer tokens:** ~7M
- **Raw findings:** 119 → **refuted by verification:** 23 (19%) → **surviving:** 96 (**80 confirmed**, 16 uncertain)
- Verification mattered: it rejected several *plausible but wrong* recommendations that would have caused regressions — e.g. "delete legacy response fields" (NAV-13) would break the live TypeScript contract; "split ClusterRepository port" (DOMAIN-5) has a ~20-consumer blast radius; "ClusterService is a Middle Man, inline it" (ORCH-1/NAV-7) is false (≥4 methods carry real orchestration). See [Refuted findings](#appendix-b--refuted-findings-do-not-action).

## Executive summary

`recognition` (~38K non-test LOC) has accreted two structural problems that match the stated concern ("deep implementations where agents get lost"):

1. **God-files / god-classes** concentrating divergent-change risk with no boundary to stop at: `clusters.py` router (1,679 LOC), `cluster_repository.py` + its `ClusterRepository` Protocol (1,439 LOC / 45 methods), `assignment_writer.py` (1,097 LOC), `report_builder.py` (718 LOC, with a 394-line god-function), `orchestrator._process_chunks` (233-line method).
2. **Indirection without payoff:** pure re-export shims (`incremental_clustering.py`, triple-hop `suggestion_details`, a 3-way DI re-export surface drifted by 18 symbols), illusory abstractions (`DiscoveryAlgorithm` ABC typed `Any→Any` with no polymorphic caller; unreachable `_NotImplemented*` retention stubs), and **~15 fully-dead modules/symbols (~1,500+ LOC)**.

The **greenfield policy** (no prod users, delete-over-flag, no migrations) makes most of this low-risk. There is substantial safe, mechanical dead-code-and-doc cleanup plus a smaller set of higher-payoff structural splits.

**Health:** moderately healthy but trending toward navigation debt. Positives — consistent hexagonal layering, 0 TODO/FIXME, strong path-based HTTP tests that decouple endpoint behavior from internal structure (so router/internal splits are low-risk), greenfield posture. Negatives concentrate in the two areas above plus several **actively-misleading docs** an agent will trust wrongly (e.g. `db/README` says embedding dim **1024**; every code constant says **512**).

## Priority 1 — Dead code to delete (verified confirmed + safe)

Each item below has verdict=`confirmed` and `safe_to_action=true` (final on-disk re-confirmation required before `rm`). Delete each accompanying test alongside its symbol.

### Large modules (~900+ LOC, near-zero risk)
| Item | Location | Risk |
|---|---|---|
| `RepresentativeOnlyClustering` (304 LOC) — also imports a renamed-away module, would `ModuleNotFoundError` if touched | `recognition/application/clustering/representative_only_clustering.py` | Negligible (unreachable, no callers/tests) |
| `representatives/` package (`RepresentativeMatcher`, 138 LOC) + its only test | `recognition/application/representatives/` ; `tests/unit/test_representative_matcher.py` | Low (test-only; behavior covered by live discovery path) |
| `settings/adaptive.py` + `settings/experiments.py` (471 LOC closed dead loop) + 2 `__init__` exports + test | `recognition/application/settings/{adaptive,experiments}.py` | Low (closed loop, test-only) |
| `scene/` package (5 files) + `Dockerfile:72` COPY + `pyproject.toml:48` entry | `scene/**` | Negligible (phantom subsystem, unmounted, no external importers) |
| `db_export.py` (128 LOC, test-only, duplicates `report_builder`'s query) + its test assertions | `recognition/application/regression_harness/db_export.py` | Low |
| `ScheduledDisposalWorker` (~55 LOC, unwired background worker) + tests | `recognition/domain/services/purge_service.py:380-434` | Low |

### Smaller confirmed-dead items
| Item | Location | Risk |
|---|---|---|
| `cancelable_jobs.py` (16 LOC: `CANCELED_JOBS`, `mark_canceled`, `is_canceled`) | `recognition/infrastructure/repositories/cancelable_jobs.py` | Negligible |
| `db/models.py` DEPRECATED shim (unreachable; package `db/models/` shadows it) | `db/models.py` | Low (forbidden back-compat shim under greenfield) |
| `DecisionHandler.evaluate_and_handle` (54 LOC) + its `persist_assignment(batch_mode=True)` call site | `recognition/application/orchestration/clustering/decision_handler.py:123-176` | Negligible |
| `ClusterVisualizer` (100 LOC matplotlib surface) + wiring + the 3 unread `ClusterService` params (`visualizer`/`decision_store`/`observability_repo`) + test. **Keep** `get_decision_store`/`ObservabilityRepository` (still live via diagnostics router) | `recognition/observability/visualization.py`; `deps/services.py:403`; `cluster_service.py:101-119` | Low |
| `_NotImplemented*` retention stubs (4 classes ~50 LOC) + `try/except ModuleNotFoundError` wrappers (dead branch). **But** replace the reachable `session=None` stub-return with an explicit **503** (path is reachable when the DB breaker opens) | `recognition/interface_adapters/http/deps/services.py:112-157,255-325` | Low-medium |

### Small-symbol sweep (bundle by file; negligible-to-low each)
`IdentityMember` dataclass (`assignment_writer.py:33-42`, shadows ORM); `_locator_sort_key` (`report_builder.py:123-131`); `run_background_retry` + `ClusterServiceProtocol.retry_matching` (`tasks/clustering.py:22-48`); `run_background_refresh_suggestions` + test (`tasks/clustering.py:199-219`); `centroid_utils.update_centroid_incremental` (unref) + `compute_centroid` (test-only); `match_single_to_anchors` (`discovery/graph/helpers.py:90`); `SplitScope` enum + `SplitPlan`/`SplitStrategy` exports (`split/plan.py`); `CurationActionType.NEW_IDENTITY`/`BLOCK` (`curation/cluster_mutations.py:270-274`); `get_cluster_service` wrapper + 3 re-exports; `InMemoryJobService` + 2 `__all__`; `_normalize_tenant_id` alias; `ClusteringLogger.log_batch_start` + `log_cluster_merged`; `configure_dev_cache` no-op (`config/cache.py` + `main.py:110`); `JobHandler` dead `TypeVar T` + import (`worker/handlers/base.py:6,10`); `SuggestionExtensionServiceProtocol`; `domain/__init__` unused `__all__`; `SuggestionRefreshService` `run_context` plumbing; dead list-comp `scan/service.py:153`; `reset_idempotency_cache()` no-op (`roster/.../curation_sync_service.py:192-194`); empty `api/schemas/` package; orphaned `check_health()`/`HealthReport` web (`scene`/`roster`/`recognition` `health.py`, `shared/health.py:21-37`).

## Priority 2 — Obsolete documentation to fix (9 docs)

| Doc | Problem | Fix |
|---|---|---|
| `db/README.md` (embedding dim) | States `VECTOR(1024)` / `PGVECTOR_DIM=1024` in 3 places; code is **512** (`001_identity_schema.py EMBEDDING_DIMENSION=512`, `settings.py` default 512, `similarity.py FACE_EMBEDDING_DIM=512`). Also references removed `media_faces` table. | Replace all three `1024`→`512`; update `media_faces` → `media_identities.embedding`. **(highest-trust-risk item)** |
| `db/README.md` (conn vars) | Presents `POSTGRES_DSN`/`POSTGRES_SYNC_DSN` as primary; canonical contract is `PGUSER/PGPASSWORD/PGHOST/PGPORT/DB_NAME`. | Reframe §2 around `PG*`; demote `POSTGRES_DSN` to "optional override." |
| `regression_harness/WORKFLOW.md` | L248/L384 document `python -m scripts.evaluate_run` and `scripts/audit_cluster_quality.py` — both deleted (commit `155b7d25`); fail immediately. | Delete the two sections or repoint to the working in-process Option B one-liner. |
| `scripts/README.md` | Cites nonexistent `scripts/mcp/unified_server.py` (deleted `2f835a61`), dead `/compare-embeddings`/`/db-query`/`/db-reset` workflows; dir block omits `deploy-env.sh`, `manage_api_keys.py`, `verify_identity_schema.py`. | Delete stale MCP/workflow notes; regenerate dir block from actual contents. |
| `http/router.py:2` | Docstring `"Minimal FastAPI router … (stub endpoints)."` over 10 fully-implemented routers (`clusters.py` = 1,679 LOC). Misdirects at the HTTP front door. | `"Aggregates the recognition sub-routers into a single APIRouter mounted by api/main.py under /recognition."` |
| `cluster_repository.py:1-5` | `"This is scaffolding only; methods are implemented in Phase 5."` atop 1,439 implemented lines. | Delete the scaffolding/Phase-5 sentence. |
| `infrastructure/__init__.py` + `embeddings/__init__.py` | Promise providers that don't exist (ArcFace, MediaPipe, Chinese Whispers); only InsightFace + HDBSCAN ship. | Trim `future:` lists to what ships; move roadmap items out of `__init__`. |
| `domain/__init__.py:17-28` "See Also" | Points to nonexistent `embedding/service.py`, missing UML, and `EmbeddingService.to_media_identities()` (no such class/method). | Repoint to real seam (`embedding/__init__.py`, `detector.py`, `generator.py`) or delete. |
| `README.md` cache config | Lists HF-deprecated `TRANSFORMERS_CACHE` for a library not installed; no code consumes documented cache names. | Drop `TRANSFORMERS_CACHE` (HF_HOME + HF_HUB_CACHE suffice). Low priority. |

## Priority 3 — Architecture: easier to reason about

Ordered by payoff/effort. Each ties to a literature principle.

1. **[M→High] Restore the domain boundary (DOMAIN-1).** 5 of 6 files in `recognition/domain/services/` import `db.models`, `sqlalchemy`, and `recognition.infrastructure` — directly contradicting `domain/__init__`'s "technology-agnostic" claim. `git mv export_service.py / purge_service.py / retention_policy_service.py / import_service.py / audit_service.py` out of `domain/services/` into `application/` (or `infrastructure/`). *Highest structural payoff for navigability* — it restores the abstraction boundary an agent relies on. (Information Hiding + Loose Coupling.)
2. **[L→High] Split the `clusters.py` god-router (IFACE-1/NAV-1).** 1,679 LOC, 21 endpoints, 4 change-axes (admission/locking, WP snapshots, topology mutations, centroid maintenance). Split into sibling routers sharing the `/clusters` prefix (`clusters_admission`, `clusters_snapshot`, `clusters_topology`, `clusters_maintenance`), re-mounted on `router.py`; extract the per-mutation dependency that absorbs the ~12× auth-match and ~9× replay/commit boilerplate. De-risked by the path-based HTTP test suite. (Large Class; Divergent Change; SoC.)
3. **[M→Med] Collapse illusory / single-impl abstractions (MICRO-7/IFACE-4/NAV-2).** Delete the `DiscoveryAlgorithm` ABC (`Any→Any`, 3 incompatible concrete signatures, no polymorphic caller — *Collapse Hierarchy*). Delete the dead retention `try/except` + stubs (keep the reachable path as an explicit 503). (Speculative Generality; YAGNI.)
4. **[M→Med] Extract phase functions from long methods (ORCH-4/PERSREG-5/WORKEROBS-6).** `_process_chunks` (233), `generate_canonical_report` (394) + `_build_pre_curation_state` (178), `ScanWorker._process_pending_clustering_jobs` (134) — they delimit phases with comment headers ("Phase 3:", "Seam 4"), the classic *extract-method* signal. Mirror the codebase's own `discovery_pipeline.py` extraction pattern; unblocks unit-testing the untested risky internals. (Long Method; Manageable Complexity.)
5. **[S→Med] One canonical DI surface (IFACE-2/NAV-5).** Three parallel re-export surfaces (`dependencies.py` vs `deps/__init__` vs `deps/services.__all__`) have **drifted by 18 symbols**. Delete `dependencies.py` (whose own docstring says "do not use"), point all 10 routers at `deps/*`, keep a single `deps/__init__ __all__`. Delete the zero-importer `suggestion_details` leaf shim. (Middle Man; Lazy Element; one source of truth.)
6. **[L→Med] Split the `ClusterRepository` fat Protocol (NAV-4/INFRA-2).** 45-method Protocol / 1,439-line impl across 5+ sub-domains. Split along method-name prefixes into focused ports (`ClusterCrud`, `ClusterMembership`, `RepresentativeRepository`, `CentroidMaintenance`, `SnapshotReader`); split `domain/repositories.py` one-module-per-Protocol. (Interface Segregation; Cohesion.) *Note:* DOMAIN-5's broader "split everything" framing was refuted (~20-consumer blast radius) — keep this scoped to the prefix seams.
7. **[M→Med] Fail-fast vs silent-fallback at integration points (INFRA-5/INFRA-3/INFRA-11).** `refresh_centroids_view` swallows a failed MV `REFRESH` (stale centroids silently feed downstream) → make it propagate/return bool and have callers act. Move `ensure_media_identity`'s placeholder-row fabrication into a test fixture and let the FK enforce integrity. (Fail-fast over silent fallback; every integration point eventually fails.)

## Proposed maintenance slices (low → high risk)

Each is independently mergeable and gated by the repo's pre-merge handoff check. **Recommend landing Slices 1–3 first** (pure deletion + docs, near-zero risk) for immediate navigability gains, then 4–7 for structural payoff. Defer Slice 9.

1. **[low] Large dead-module deletion** — the 6 large modules above + `cancelable_jobs.py`, `db/models.py` shim, `evaluate_and_handle`. Full test suite + real import/boot check.
2. **[low] Small dead-symbol sweep** — the bundled-by-file symbols; delete accompanying tests.
3. **[low] Obsolete-doc fixes** — all 9 docs. Docs-only, no behavior change.
4. **[medium] Indirection collapse** — `ClusterVisualizer` + ORCH-3 params; inline `incremental_clustering.py`; delete `suggestion_details` leaf shim; collapse `_NotImplemented*` (→503); delete `DiscoveryAlgorithm` ABC.
5. **[medium] Domain boundary move (DOMAIN-1)** — `git mv` 5 services; rewrite ~5 prod + ~10 test imports; verify mypy + retention API tests + DI factories.
6. **[medium] `clusters.py` router split** — 4 concern routers + shared per-mutation dependency; preserve all paths; lean on HTTP tests.
7. **[medium] DI surface consolidation** — delete `dependencies.py`, repoint 10 routers, single `deps/__init__ __all__`.
8. **[medium] Long-method extraction + fail-fast** — under TDD (new unit tests first): extract phase functions; make `refresh_centroids_view` fail-fast; move `ensure_media_identity` placeholder to a fixture.
9. **[high, later] Repository + AssignmentWriter split** — split `ClusterRepository` Protocol/impl + `domain/repositories.py`; extract `RepresentativeSelector`/`CentroidMaintainer` from `AssignmentWriter`; centralize the clustering `job_type` frozenset. Largest effort, lowest confidence — defer until 1–8 land.

## Lower-confidence items (verdict=uncertain — assess before acting)

`clusters.py`/`cluster_repository.py`/`AssignmentWriter` god-file framings (NAV-1/4/11, INFRA-2) — real but bigger than a sweep; the splits above are the actioned form. `IFACE-3` `recover_orphan_identities` orphaned handler (WP proxy removed in 4.13.0) — verify before deleting. `INFRA-11` `coerce_uuid` deterministic-UUID-from-bad-input, `MICRO-9`/`SUGSCAN-11` duplicated best-cosine-match loops, `SUGSCAN-5/6` divergent scan phase-mapping, `ORCH-10/11/13` best-effort side-effect suppression — judgment calls, low priority.

---

## Appendix A — Surviving findings (96)

Sorted by severity. `Safe` = `safe_to_action`. Full evidence/recommendation per finding lived in the workflow result (handoff DB when restored).

| ID | Cat | Sev | Verdict | Safe | Finding | Location |
|---|---|---|---|---|---|---|
| DOCS-2 | obsolete_doc | high | confirmed | Y | WORKFLOW.md documents two commands for scripts that do not exist | `apps/prototype-description-service/recognition/application/regression_harness/WO` |
| DOMAIN-1 | architecture | high | confirmed | Y | domain/services/ files import infrastructure and SQLAlchemy directly — dependency inversion; they are not domain services | `apps/prototype-description-service/recognition/domain/services/{export_service.p` |
| IFACE-1 | architecture | high | confirmed | Y | clusters.py is a 1679-line god-router mixing 4 unrelated concerns + inlined admission-control plumbing | `recognition/interface_adapters/http/routers/clusters.py:1-1680` |
| MICRO-1 | dead_code | high | confirmed | Y | RepresentativeOnlyClustering (304 LOC) is fully dead and imports a non-existent module | `recognition/application/clustering/representative_only_clustering.py` |
| MICRO-2 | dead_code | high | confirmed | Y | representatives/ package (RepresentativeMatcher, 138 LOC) is test-only and superseded by discovery_pipeline | `recognition/application/representatives/representative_matcher.py` |
| PERSREG-5 | code_smell | high | confirmed | Y | generate_canonical_report is a 394-line god-function mixing query, transform, dedup, and metrics | `recognition/application/regression_harness/report_builder.py:313-707` |
| DOCS-1 | obsolete_doc | medium | confirmed | Y | db/README.md states embedding dimension 1024 in 3 places; code is 512 | `apps/prototype-description-service/db/README.md:10,29 (vs db/migrations/versions` |
| DOMAIN-2 | dead_code | medium | confirmed | Y | ScheduledDisposalWorker is unwired across the entire monorepo (dead background worker) | `apps/prototype-description-service/recognition/domain/services/purge_service.py:` |
| DOMAIN-4 | obsolete_doc | medium | confirmed | Y | domain/__init__.py 'See Also' points to a non-existent seam file and a missing UML doc | `apps/prototype-description-service/recognition/domain/__init__.py:26-28` |
| DOMAIN-6 | code_smell | medium | confirmed | Y | Identical _get_tenant body duplicated verbatim across three domain services | `apps/prototype-description-service/recognition/domain/services/purge_service.py:` |
| IFACE-2 | architecture | medium | confirmed | n | Three parallel re-export surfaces for the same ~30 DI factories (dependencies.py vs deps/__init__.py vs deps/services.__all__) | `recognition/interface_adapters/http/dependencies.py:1-132; recognition/interface` |
| INFRA-1 | dead_code | medium | confirmed | Y | repositories/cancelable_jobs.py is fully dead (zero references repo-wide) | `apps/prototype-description-service/recognition/infrastructure/repositories/cance` |
| INFRA-3 | risk | medium | confirmed | Y | ensure_media_identity fabricates placeholder MediaIdentity rows inside every write path (silent fallback, masks FK integrity failures) | `apps/prototype-description-service/recognition/infrastructure/repositories/_help` |
| INFRA-5 | code_smell | medium | confirmed | Y | refresh_centroids_view / _concurrent swallow all exceptions and return None/False (failed MV refresh is invisible) | `apps/prototype-description-service/recognition/infrastructure/repositories/clust` |
| INFRA-8 | code_smell | medium | confirmed | Y | _to_domain is a 127-line method assembling deeply-nested debug_metrics inline | `apps/prototype-description-service/recognition/infrastructure/repositories/clust` |
| MICRO-4 | dead_code | medium | confirmed | Y | centroid_utils.update_centroid_incremental is unreferenced; compute_centroid is test-only | `recognition/application/clustering/centroid_utils.py:33,51` |
| MICRO-5 | dead_code | medium | confirmed | Y | Backward-compat aliases EmbeddingGenerator (empty subclass) and FaceDetector kept alive only by legacy tests | `recognition/application/embedding/generator.py:186-189; recognition/application/` |
| NAV-1 | architecture | medium | confirmed | n | clusters.py router is a 1679-line god file mixing 8 unrelated concerns across 4 layers | `recognition/interface_adapters/http/routers/clusters.py` |
| NAV-3 | dead_code | medium | confirmed | Y | RepresentativeMatcher is test-only / dead at runtime | `recognition/application/representatives/representative_matcher.py (138 lines)` |
| NAV-4 | architecture | medium | confirmed | n | ClusterRepository is a 45-method god-Protocol; SqlAlchemyClusterRepository a 51-method 1439-line god class | `recognition/domain/repositories.py:56-372 (Protocol); recognition/infrastructure` |
| NAV-6 | dead_code | medium | confirmed | Y | Triple-hop suggestion_details schema re-export shims; outer shim has zero importers | `recognition/interface_adapters/http/schemas/suggestion_details.py (9L) and recog` |
| ORCH-2 | dead_code | medium | confirmed | Y | DecisionHandler.evaluate_and_handle is fully dead (54 lines, no callers in runtime or tests) | `recognition/application/orchestration/clustering/decision_handler.py:123-176` |
| ORCH-3 | dead_code | medium | confirmed | Y | Three ClusterService constructor params are write-only dead state, constructed with side effects then never read | `recognition/application/orchestration/cluster_service.py:101-119 (params visuali` |
| ORCH-4 | architecture | medium | confirmed | Y | IncrementalClusteringRunner._process_chunks is a 233-line Long Method mixing 6 phases at mixed abstraction levels | `recognition/application/orchestration/clustering/orchestrator.py:412-644` |
| ORCH-6 | dead_code | medium | confirmed | Y | ClusterService._get_chunk_size (and get_chunk_size_op import) is exercised only by tests | `recognition/application/orchestration/cluster_service.py:230-233; get_chunk_size` |
| PERSREG-1 | dead_code | medium | confirmed | Y | Unused IdentityMember dataclass shadows the live db.models ORM class of the same name | `recognition/application/persistence/assignment_writer.py:33-42` |
| PERSREG-2 | dead_code | medium | confirmed | Y | run_background_retry and its ClusterServiceProtocol.retry_matching member are fully unreferenced | `recognition/application/tasks/clustering.py:22-48 (ClusterServiceProtocol.retry_` |
| PERSREG-3 | dead_code | medium | confirmed | Y | db_export.py (fetch_canonical_labels / fetch_predicted_clusters) is test-only and duplicates report_builder's DB query logic | `recognition/application/regression_harness/db_export.py (entire 128-line module)` |
| SAT-3 | dead_code | medium | confirmed | Y | db/models.py unreachable; same-named package db/models/ shadows it | `db/models.py vs db/models/__init__.py` |
| WORKEROBS-1 | dead_code | medium | confirmed | Y | ClusterVisualizer is instantiated and wired but its methods are never invoked at runtime | `recognition/observability/visualization.py (whole file, 100 LOC); wired at recog` |
| WORKEROBS-6 | architecture | medium | confirmed | Y | ScanWorker._process_pending_clustering_jobs is a 134-line god-method mixing claim, dispatch, rollback, retry classification, and durable persistence | `recognition/worker/scan_worker.py:257-388` |
| DOCS-3 | obsolete_doc | low | confirmed | Y | scripts/README.md references nonexistent MCP server path and dead /db-query, /db-reset, /compare-embeddings workflows | `apps/prototype-description-service/scripts/README.md:9-10,19-20` |
| DOCS-4 | dead_code | low | uncertain | Y | scene/ package is a dead 10-LOC scaffold; main README falsely implies it is a live-then-consolidated subsystem | `apps/prototype-description-service/scene/ (5 files, 10 LOC) and README.md:195` |
| DOCS-5 | obsolete_doc | low | confirmed | Y | scripts/README.md directory-structure block omits 3 real scripts and misrepresents the inventory | `apps/prototype-description-service/scripts/README.md:7-17` |
| DOCS-6 | obsolete_doc | low | confirmed | Y | db/README.md presents POSTGRES_DSN as the primary connection var; canonical contract is now the PG* variables | `apps/prototype-description-service/db/README.md:27-28 (vs .env.example:18-37, db` |
| DOCS-7 | obsolete_doc | low | confirmed | Y | README cache config lists HF-deprecated TRANSFORMERS_CACHE and no code consumes the documented cache env names directly | `apps/prototype-description-service/README.md:125,145` |
| DOMAIN-3 | dead_code | low | confirmed | Y | SuggestionExtensionServiceProtocol has zero references anywhere — unused single-impl-less Protocol | `apps/prototype-description-service/recognition/domain/services/suggestion_extens` |
| DOMAIN-7 | dead_code | low | confirmed | Y | domain/__init__.py re-export surface (__all__, 8 symbols) has zero package-root importers | `apps/prototype-description-service/recognition/domain/__init__.py:31-51` |
| DOMAIN-8 | architecture | low | confirmed | Y | AuditService is a thin middle-man forwarding to AuditRepository.create_event | `apps/prototype-description-service/recognition/domain/services/audit_service.py ` |
| IFACE-10 | dead_code | low | confirmed | Y | Vestigial backward-compat module-level aliases: _normalize_tenant_id (0 uses), plus _validate_uuid / _job_to_response alias hops | `recognition/interface_adapters/http/deps/tenant.py:14; recognition/interface_ada` |
| IFACE-3 | dead_code | low | uncertain | n | recover_orphan_identities handler is orphaned — WP proxy was already removed in task 4.13.0 | `recognition/interface_adapters/http/routers/clusters.py:499-522 (POST /clusters/` |
| IFACE-4 | dead_code | low | confirmed | Y | _NotImplemented* retention fallback classes + except-ModuleNotFoundError branches are unreachable (all target modules exist) | `recognition/interface_adapters/http/deps/services.py:112-157, 255-325` |
| IFACE-5 | dead_code | low | confirmed | Y | get_cluster_service is dead at runtime (test-only + re-export lists), a thin pass-through over build_cluster_service | `recognition/interface_adapters/http/deps/services.py:410-416` |
| IFACE-6 | dead_code | low | confirmed | Y | InMemoryJobService is exported through both DI facades but never instantiated anywhere | `recognition/interface_adapters/http/deps/stores.py (class + __all__); dependenci` |
| IFACE-7 | architecture | low | confirmed | Y | Four-deep suggestion_details re-export chain with a zero-importer leaf module | `recognition/interface_adapters/http/schemas/suggestion_details.py (9 LOC, 0 impo` |
| IFACE-8 | code_smell | low | confirmed | Y | get_job_service_dependency has an identical try/except — the except branch is a no-op that can only re-raise the same error | `recognition/interface_adapters/http/deps/services.py:583-588` |
| INFRA-10 | dead_code | low | confirmed | Y | InsightFaceAdapter.model_info() and analyze() are low-value (model_info test-only; analyze a 1-line pass-through) | `apps/prototype-description-service/recognition/infrastructure/embeddings/__init_` |
| INFRA-11 | code_smell | low | uncertain | n | coerce_uuid silently derives a deterministic UUID from invalid input (deterministic on_failure default masks bad IDs) | `apps/prototype-description-service/recognition/infrastructure/repositories/_help` |
| INFRA-2 | architecture | low | uncertain | n | cluster_repository.py is a 1439-line god repository (~51 methods, many unrelated concerns) | `apps/prototype-description-service/recognition/infrastructure/repositories/clust` |
| INFRA-6 | obsolete_doc | low | confirmed | Y | Stale 'scaffolding only; methods are implemented in Phase 5' docstring on a fully-implemented 1439-line file | `apps/prototype-description-service/recognition/infrastructure/repositories/clust` |
| INFRA-7 | obsolete_doc | low | confirmed | Y | infrastructure/__init__.py and embeddings docstrings promise providers (ArcFace, MediaPipe, Chinese Whispers) that do not exist | `apps/prototype-description-service/recognition/infrastructure/__init__.py:11-12;` |
| INFRA-9 | code_smell | low | confirmed | Y | assignment_writer duck-types the ClusterRepository port it declares (getattr(self._clusters, 'refresh_centroids_view', None)) | `apps/prototype-description-service/recognition/application/persistence/assignmen` |
| MICRO-10 | risk | low | confirmed | Y | EventBroadcaster uses unbounded per-subscriber asyncio.Queue (no back-pressure) | `recognition/application/events/broadcaster.py:45,90` |
| MICRO-3 | dead_code | low | confirmed | Y | settings/adaptive.py + settings/experiments.py (471 LOC) are a dead cluster — runtime-unreachable | `recognition/application/settings/adaptive.py; recognition/application/settings/e` |
| MICRO-6 | dead_code | low | confirmed | Y | discovery/graph/helpers.match_single_to_anchors is unreferenced | `recognition/application/discovery/graph/helpers.py:90` |
| MICRO-7 | architecture | low | confirmed | Y | DiscoveryAlgorithm ABC provides illusory polymorphism — never used through its interface | `recognition/application/discovery/base.py (ABC); consumed in orchestration/clust` |
| MICRO-9 | code_smell | low | uncertain | n | Best-cosine-match-over-embedding-dict loop duplicated across 3+ sites | `discovery/centroid.py:63 (_find_best_centroid_match); clustering/representative_` |
| NAV-10 | obsolete_doc | low | confirmed | Y | http/router.py docstring still claims 'stub endpoints' while mounting 10 real routers | `recognition/interface_adapters/http/router.py:2` |
| NAV-11 | architecture | low | uncertain | n | AssignmentWriter god class: 1097 lines, 25 methods, imported by 17 modules — the persistence-layer single point everything reaches into | `recognition/application/persistence/assignment_writer.py (1097 lines)` |
| NAV-12 | architecture | low | uncertain | n | Two parallel schema directories (interface_adapters/schemas vs interface_adapters/http/schemas) split DTOs by no clear rule | `recognition/interface_adapters/schemas/ vs recognition/interface_adapters/http/s` |
| NAV-2 | architecture | low | uncertain | n | Retention _NotImplemented* Protocol/stub scaffold: dead fallback branches + speculative indirection wired into live routers | `recognition/interface_adapters/http/deps/services.py:67-325 (and re-exported via` |
| NAV-5 | architecture | low | uncertain | n | Deprecated http/dependencies.py re-export hub is still THE import path for all 10 routers despite its own 'do not use' docstring | `recognition/interface_adapters/http/dependencies.py (131 lines, 49 re-exported n` |
| NAV-8 | architecture | low | confirmed | Y | incremental_clustering.py is a 7-line facade re-exporting from clustering/, used by one caller | `recognition/application/orchestration/incremental_clustering.py (7 lines)` |
| ORCH-10 | code_smell | low | uncertain | Y | Silent except-and-swallow around centroid/merge-suggestion side effects hides post-clustering failures | `recognition/application/orchestration/cluster_service.py:188-226; curation_job.p` |
| ORCH-11 | architecture | low | uncertain | n | run_curation_job uses getattr-by-string duck typing to reach across cluster_service internals (Message Chain / fragile coupling) | `recognition/application/orchestration/curation_job.py:96,130-131,170,277-282` |
| ORCH-13 | code_smell | low | uncertain | n | assign_outlier_to_cluster recomputes curation similarity after the membership write purely for a log line | `recognition/application/orchestration/curation/cluster_mutations.py:359-395` |
| ORCH-5 | architecture | low | confirmed | Y | incremental_clustering.py is a pure re-export shim adding a hop with no payoff | `recognition/application/orchestration/incremental_clustering.py:1-7` |
| ORCH-7 | dead_code | low | confirmed | Y | SplitScope enum unused; SplitPlan/SplitStrategy exported but never constructed at runtime | `recognition/application/orchestration/split/plan.py:9-33; split/__init__.py:4-6` |
| ORCH-8 | dead_code | low | confirmed | Y | CurationActionType has two dead enum members (NEW_IDENTITY, BLOCK) | `recognition/application/orchestration/curation/cluster_mutations.py:270-274` |
| PERSREG-11 | risk | low | confirmed | Y | Blocking shutil.rmtree runs in async chain_populate_and_process (FastAPI BackgroundTask) | `recognition/application/tasks/scan.py:290-300 (store.cleanup) -> storage/filesys` |
| PERSREG-4 | dead_code | low | confirmed | Y | _locator_sort_key is defined but never called | `recognition/application/regression_harness/report_builder.py:123-131` |
| PERSREG-6 | code_smell | low | uncertain | n | _build_pre_curation_state is 178 lines with a 60-line nested closure and a repeated event-type switch | `recognition/application/regression_harness/report_builder.py:134-310 (nested _ma` |
| PERSREG-7 | dead_code | low | confirmed | Y | run_background_refresh_suggestions is test-only (no runtime caller) | `recognition/application/tasks/clustering.py:199-219` |
| PERSREG-8 | code_smell | low | confirmed | Y | _compute_fingerprint duplicated verbatim in two in-scope modules | `recognition/application/persistence/assignment_writer.py:45-51 and recognition/a` |
| PERSREG-9 | dead_code | low | confirmed | Y | Speculative report scaffolding: include_crop_hash param never set, cluster_outcomes/embedding_model fields permanently empty | `recognition/application/regression_harness/report_builder.py:107-120 (include_cr` |
| SAT-1 | dead_code | low | confirmed | Y | scene package is entirely dead scaffolding | `scene/** (5 files), api/main.py:172-173, Dockerfile:72, pyproject.toml:48` |
| SAT-2 | dead_code | low | confirmed | Y | Health dead-code web: 3 check_health() + HealthReport orphaned by Slice 2.5b | `scene/roster/recognition health.py, shared/health.py:21-37, recognition/applicat` |
| SAT-4 | dead_code | low | confirmed | Y | reset_idempotency_cache() no-op shim with zero callers | `roster/application/curation_sync_service.py:192-194` |
| SAT-5 | dead_code | low | confirmed | Y | Vestigial empty api/schemas/ package | `api/schemas/__init__.py` |
| SAT-7 | obsolete_doc | low | confirmed | Y | scripts/README.md cites nonexistent /compare-embeddings workflow | `scripts/README.md; scripts/utilities/compare_media_embeddings.py` |
| SAT-8 | architecture | low | confirmed | Y | Empty hexagonal skeletons create phantom subsystems | `scene+roster application/interface_adapters __init__.py trees` |
| SUGSCAN-1 | dead_code | low | confirmed | Y | SuggestionRefreshService run_context plumbing is entirely dead (param + field + bind_run_context) | `recognition/application/suggestions/refresh_service.py:69,80,82-84` |
| SUGSCAN-11 | code_smell | low | uncertain | n | Cluster representative-embedding extraction duplicated three times across suggestions | `recognition/application/suggestions/refresh_service.py:139-141,306-308 and label` |
| SUGSCAN-2 | dead_code | low | confirmed | Y | _find_best_cluster_match: dead exclude_cluster_ids param and dead representatives-None re-fetch branch | `recognition/application/suggestions/refresh_service.py:110-152` |
| SUGSCAN-3 | dead_code | low | confirmed | Y | ScanQueueRepository.create_job (bare, no-message) is test-only; production uses create_job_with_message | `recognition/application/scan/queue_repository.py:39-46` |
| SUGSCAN-4 | dead_code | low | confirmed | Y | Discarded list-comprehension computes media ids and throws them away | `recognition/application/scan/service.py:153` |
| SUGSCAN-5 | architecture | low | uncertain | Y | Two divergent phase-mapping functions for scan jobs (derive_job_phase vs scan_phase_for_status) | `recognition/application/scan/progress.py:13-29 and recognition/interface_adapter` |
| SUGSCAN-6 | code_smell | low | uncertain | Y | ANALYZE status poll issues 4 item-aggregate queries where 2 suffice (duplicate progress builders) | `recognition/application/scan/progress.py:49-122 and recognition/interface_adapte` |
| SUGSCAN-7 | code_smell | low | confirmed | Y | label_inference.py: 252-line single function mixing 5 inference strategies; unreachable-in-practice DB-fallback tail | `recognition/application/suggestions/label_inference.py:21-252` |
| WORKEROBS-10 | architecture | low | confirmed | Y | Worker splits scan-item vs job dispatch across a held _scan_handler and a separate _job_handlers dict with two parallel claim paths | `recognition/worker/scan_worker.py:120-124 (_job_handlers dict), 184-192 (_scan_h` |
| WORKEROBS-2 | dead_code | low | confirmed | Y | ClusteringLogger.log_batch_start has no callers anywhere in the repo | `recognition/observability/logging.py:101-117` |
| WORKEROBS-3 | dead_code | low | confirmed | Y | ClusteringLogger.log_cluster_merged is test-only (no runtime caller) | `recognition/observability/logging.py:229-271` |
| WORKEROBS-4 | dead_code | low | confirmed | Y | Dead module-level TypeVar T shadowed by PEP 695 class syntax in JobHandler base | `recognition/worker/handlers/base.py:6,10` |
| WORKEROBS-5 | code_smell | low | confirmed | Y | configure_dev_cache is a no-op Lazy Element called once at startup | `recognition/config/cache.py (whole 8-line file); called at api/main.py:110` |
| WORKEROBS-8 | code_smell | low | confirmed | Y | Identical 8-argument ScanItemHandler constructor duplicated across two sites (shotgun-surgery hazard) | `recognition/worker/scan_worker.py:112-119 (__init__) and 224-231 (_ensure_embedd` |
| WORKEROBS-9 | code_smell | low | confirmed | Y | ClusteringLogger has 9 near-identical log_* methods that each rebuild an extra-dict by hand (Repeated Switches over event shape) | `recognition/observability/logging.py:40-352 (whole class, 332 LOC)` |

## Appendix B — Refuted findings (do NOT action)

Verification rejected these 23. Acting on several would cause regressions.

- **ORCH-1** — ClusterService is a Middle Man facade: ~15 methods forward one-for-one to sibling free functions
  - Why refuted: The finding's load-bearing claims are materially false. (1) Headcount: 11 public methods, not 15; the finding itself lists only 10 names. (2) "All 15...are thin wrappers" is false for at least 4 methods carrying real orchestration the *_op functions do not: cluster_unclustered_identities (78 lines: builds ClusteringDependencies/RuntimeConfig/Context, runs post-op suggestion bac
- **ORCH-9** — orchestrator.py embeds finding/seam/investigation tracking notes in code comments (status belongs in handoff DB)
  - Why refuted: The finding miscites its governing rule. CLAUDE.md "Review Findings Placement" and its enforcement hook (scripts/hooks/guard-task-plan-findings.py, _PATH_FILTER_SUBSTRINGS = "/docs/tasks/","/docs/epics/" + *task-plan*.md/*-plan.md) scope source code OUT — the rule forbids pasting finding BODIES into task-plan markdown, not annotating source comments. No repo rule bans architect
- **ORCH-12** — orchestration/protocols.py defines 4 Protocols each with exactly one runtime implementation
  - Why refuted: The finding's central hypothesis (the Protocols break an orchestration<->suggestions import cycle) is FALSE: suggestions/service.py, refresh_service.py and merge_suggestions.py contain no module-level import of orchestration — the only 'orchestration' token in refresh_service.py is its module docstring (line 1). The real, load-bearing reason for the Protocols is dependency inve
- **SUGSCAN-8** — run_scan_three_phase helper adds indirection without removing duplicated try/except at both call sites
  - Why refuted: Both recommended actions are unsound. (1) 'Inline the 3-line sequence': would break the two phase-split tests that monkeypatch the shared helper to assert identical phase ordering/no-DB-gap timing across both callers, removing the single assertable seam for negligible gain. (2) 'Push the shared try/except + mark_job_failed into the helper': not feasible cleanly because the two
- **SUGSCAN-9** — MergeSuggestionService.delete_by_cluster is a one-line pass-through bypassed by most callers
  - Why refuted: The finding's factual premise is inverted. It claims the service method is a 'Middle Man' used by only one of three callers; in reality the service is the delegation path for the 3 orchestration sites, and only the 2 routers bypass it — and they bypass it for a sound reason: they already construct a repo instance for adjacent operations, while orchestration code does not. The s
- **SUGSCAN-10** — tenant_id property annotated str|None but stores/returns a non-optional str
  - Why refuted: The finding is refuted as a worthwhile issue on three grounds. (1) Its stated harm is fabricated: ZERO production callers None-guard the service `.tenant_id` property (grep for `.tenant_id is None`/`if ...tenant_id` yields only test-fake repo-model comparisons and unrelated `request.`/`auth.`/`model.` accesses). The claimed "spurious None-guards downstream" do not exist. (2) Th
- **PERSREG-10** — regression_harness/__init__ re-export surface is unused indirection
  - Why refuted: The architectural judgment is unsound. The re-export __init__.py with __all__ is the deliberate, dominant convention across recognition/application/: settings, labeling, embedding, discovery, similarity, assignment, storage, integrations, orchestration, events all use it. Crucially, sibling packages `embedding` and `labeling` have rich re-export __init__ files yet ALSO have ZER
- **PERSREG-12** — Stale comment in scan.py references a non-existent investigation doc path
  - Why refuted: Two of the finding's claims are false/misleading. (1) "Links to a missing doc" — the doc EXISTS; it was archived under docs/archive/tasks/4.0/4.11.0/, only the path prefix is stale (docs/tasks -> docs/archive/tasks). (2) The recommendation to DELETE the NOTE block is unsound and would lose information: this is a legitimate WHY comment that records an intentional MVP decision to
- **MICRO-8** — GraphAlgorithm port has a single runtime implementation (HdbscanGraphAlgorithm); rest are test stubs
  - Why refuted:
- **IFACE-9** — Single-implementation Protocols in services.py add a navigation layer with no polymorphism payoff
  - Why refuted: The premise "single-implementation, no polymorphism payoff" is factually wrong. The Protocols are a working test seam: the retention router depends on the abstraction, production binds the DB-backed domain service, and the API test suite binds session-free in-memory fakes (FakeRetention*Service / FakeAuditRepository) by structural typing — letting the router be tested over HTTP
- **IFACE-11** — Two parallel split mutation planes both delegate to cluster_service.split_cluster (divergent-change risk)
  - Why refuted: The finding's core premises are factually wrong. (1) "A change to split semantics must be made in two handlers" is false: split semantics live in a single shared service method, cluster_service.split_cluster (recognition/application/orchestration/cluster_service.py:470, backed by split/executor.py:144). Both handlers already delegate to it, so a semantics change is one edit, no
- **INFRA-4** — Suggestion domain fragmented across 3 infra files with duplicated expiry logic (divergent change)
  - Why refuted: The finding's central factual premise is false. It claims expiry filtering is "duplicated between the service and the repos," but both named suggestion repositories contain no expiry logic at all; the predicate is already centralized in a single helper (_active_expiry_clause) reused for all three suggestion types in the service. The recommendation to "centralize the expiry pred
- **DOMAIN-5** — repositories.py is a god-file of 9 ports / 87 methods; ClusterRepository alone has 45 methods across many concerns
  - Why refuted: The recommendation is premature/opinion-driven with high regression risk and speculative payoff. Splitting ClusterRepository into 5 ports has broad blast radius: ~20 non-test consumers annotate `cluster_repository: ClusterRepository` / `cluster_repo: ClusterRepository` directly (application/orchestration/curation/*, assignment/gate.py, suggestions/*, persistence/assignment_writ
- **DOMAIN-9** — TenantPurgeService._delete_rows commits per batch inside a method whose caller also commits — partial-purge on mid-loop failure
  - Why refuted: The finding's substantive premise is false and self-contradictory. Evidence claims the purge is "not idempotently resumable," but the recommendation itself calls it "resumable-by-rerun." The latter is correct: every delete predicate is a deterministic filter (scope="disposed" → disposed_at IS NOT NULL; scope="all" → tenant_id), independent of any progress marker. A re-run (the
- **WORKEROBS-7** — Finding-id and Seam status trailers embedded as source comments (status-in-source, against project rule)
  - Why refuted: The finding misattributes a rule. CLAUDE.md 'Review Findings Placement' and its hook (scripts/hooks/guard-task-plan-findings.py) are explicitly and exclusively scoped to task-plan/epic MARKDOWN (_PATH_FILTER_SUBSTRINGS = '/docs/tasks/','/docs/epics/'; globs '*task-plan*.md','*-plan.md'); the hook does not scan .py files and the rule text says 'Never paste a finding list into a
- **WORKEROBS-11** — RecognitionRunContext.flush_pending_events swallows all exceptions and silently discards events
  - Why refuted: The finding's core justification is factually wrong. It claims the blanket except 'hides bugs in event construction, not just DB faults.' But event construction (parse_optional_uuid + RecognitionEvent(...) at lines 66-80) happens entirely inside add_event(), which is called during clustering — OUTSIDE the try block. By flush time, _pending_events already holds fully-built Recog
- **SAT-6** — Orphan .pyc with deleted source files
  - Why refuted: Recommendation is moot/non-actionable. (1) "gitignore __pycache__" is ALREADY DONE: root .gitignore lines 85-86 contain `__pycache__/` and `*.pyc`; git status --ignored reports all three named dirs as ignored (!!); `git ls-files | grep .pyc` returns 0 tracked .pyc across the entire repo. (2) "Remove stale .pyc" fixes nothing: these are local-only, git-ignored build artifacts th
- **SAT-9** — 001_identity_schema.py is a 1373-line single-migration god file
  - Why refuted: The finding refutes itself: its recommendation is "Accept as trade-off ... split into named helpers IF it grows" — i.e. take no action now. There is no concrete, scoped change to make. The file is not tangled: it has clean module-level constants (TENANT_TABLES, EXPECTED_SCHEMA_TABLES, DOWNGRADE_TABLE_ORDER) and two single functions upgrade()/downgrade() containing a flat sequen
- **SAT-10** — shared/ collapses to a single enum after health cleanup
  - Why refuted: The finding is a conditional musing premised entirely on SAT-2 "removing HealthReport," but that premise is unverified and likely unsound: no SAT-prefixed findings exist in the handoff DB (checked all 18 candidate task_refs), so SAT-2 is an in-flight hypothesis with no recorded approval, and HealthReport has three live consumers that a removal would have to rewrite. Even granti
- **NAV-7** — ClusterService is a Middle Man: methods forward one-for-one to free-function *_op operations in sibling modules
  - Why refuted:
- **NAV-9** — Single-impl orchestration *ServiceProtocol family: DI seams never substituted, pure indirection tax
  - Why refuted: The finding's central inference is wrong: Python `Protocol` is STRUCTURALLY typed, so a substituted fake never references the Protocol name. Grepping for the name proves nothing. Tests DO inject alternate impls through these exact seams: test_cluster_service.py:242 `suggestion_service=Mock()`; test_merge_ordering.py:45,91 `suggestion_service=Mock()`; test_cluster_service_merge.
- **NAV-13** — responses.py carries explicit 'Legacy fields for backward compatibility' in a greenfield project with no external clients
  - Why refuted: The recommendation ("delete fields and aliases no consumer reads; the WP contract tests in test_wordpress_contract.py are the real contract") is unsound and misscoped. test_wordpress_contract.py references neither field (0 hits) and is not the relevant contract — the relevant TS contract (cluster.ts) and the router both DO carry these fields. Applying "delete the alias" to _val
- **NAV-14** — regression_harness lives under application/ but is dev/CLI tooling, not a request-path concern
  - Why refuted: The recommendation's premise — that application/ should be "exclusively request-path use-cases" — is not grounded in any documented convention and is contradicted by the directory's actual contents. application/__init__.py describes only an "Application layer entrypoint", no request-path-only contract. application/ already houses other non-request-path siblings: tasks/ (backgro
