# E15-27 Deferred Quality Backlog (post-demo)

**Inventory snapshot:** 2026-06-13 · **Source of truth:** Workstate handoff DB. This doc is a static navigation aid; status is **not** tracked here — query live.

## Context

E15-27 shipped green; its final full-diff review (decision 729) deferred 21 medium/low quality findings as non-blocking backlog — test-coverage gaps, contract docs, enum consolidation, and minor cleanups, none of them behavioral bugs. Per the 2026-06-11 MVP strategy assessment ("ship the demo URL, stop polishing the chassis past it"), task **E15-30** cherry-picked only the demo-visible findings and deferred the rest.

- **Done — integrated at `13dea547`** (E15-30, slice decision `787`): `E15-27-BR-11` (scan error UX no longer leaks raw HTTP text), `E15-27-BR-21` (scan phase→status mapping made exhaustive).
- **Remaining: 19** (11 medium, 8 low) — listed below.

The remaining items live as `deferred` review findings on reviewer refs `E15-27-REV-A` / `E15-27-REV-B`. Query current status live (do not track it in this file):

```
review_findings(review={"operation":"list","task_ref":"E15-27-REV-A","status":"deferred"})
review_findings(review={"operation":"list","task_ref":"E15-27-REV-B","status":"deferred"})
```

Paths below are as recorded on the finding (a mix of repo-relative and service-relative); resolve against `apps/prototype-description-service/` or `apps/prototype-wp-alt-context/` as needed.

## Remaining work (19)

### Documentation & contracts (4)

| ID | Sev | Surface | Subject |
|----|-----|---------|---------|
| E15-27-BR-04 | med | docs/workstate/contracts/ | Boundary contracts/runbook not updated for the `embedding_runtime` health field + analyze 503 shape |
| E15-27-BR-14 | med | docs/workstate/contracts/ | No owning contract documents the additive `progress_envelope` JobStatusResponse read shape |
| E15-27-BR-22 | med | docs/workstate/contracts/ | clustering/job contract docs omit `completed_with_errors`, `rejected`, `progress_envelope` |
| E15-27-BR-23 | med | recognition/tests/fixtures/scan_progress_envelope.json | Fixture documents only the running state; no terminal envelope examples for E15-22 consumers |

### Test coverage (6)

| ID | Sev | Surface | Subject |
|----|-----|---------|---------|
| E15-27-BR-05 | med | recognition/application/scan/capability.py | No test for the `publish_embedding_runtime_capability` worker upsert path |
| E15-27-BR-06 | med | recognition/interface_adapters/http/routers/analyze_multipart.py | Multipart analyze intake-gate rejection path untested |
| E15-27-BR-15 | med | recognition/tests/api/test_api_analyze.py | No HTTP integration test asserts `progress_envelope` on GET /jobs/{id} |
| E15-27-BR-09 | low | recognition/tests/api/test_scan_capability_intake.py | Stale-heartbeat rejection unit-tested only, not at the HTTP intake layer |
| E15-27-BR-12 | low | js/admin/hooks/useJobStateMachineMutations.ts | `onScanError` wiring untested beyond the scanApiError unit tests |
| E15-27-BR-18 | low | recognition/tests/fixtures/scan_progress_envelope.json | Published fixture not validated against `ScanProgressEnvelopeResponse` in pytest |

### Enum consolidation & cleanups (6)

| ID | Sev | Surface | Subject |
|----|-----|---------|---------|
| E15-27-BR-17 | med | recognition/infrastructure/repositories/scan_queue_repository.py | Item-row paths use `JobStatus` instead of `ScanItemStatus` (sr-007 consolidation incomplete) |
| E15-27-BR-26 | low | recognition/infrastructure/repositories/scan_queue_repository.py | `get_job_item_identities_detected` filters with `JobStatus.COMPLETED` not `ScanItemStatus.COMPLETED` |
| E15-27-BR-19 | low | recognition/interface_adapters/http/job_utils.py | `job_to_response` duplicates `get_job_item_status_counts` on the poll path |
| E15-27-BR-28 | low | recognition/interface_adapters/http/job_utils.py | `ValueError` building `progress_envelope` is silently swallowed (no log) |
| E15-27-BR-08 | low | recognition/application/scan/capability.py | `read_embedding_runtime_capability` docstring inaccurate (uses `WorkerCapability` ORM) |
| E15-27-BR-10 | low | recognition/worker/scan_worker.py | Worker `__aenter__` double-publishes the capability heartbeat (redundant DB write) |

### Behavior / robustness (3)

| ID | Sev | Surface | Subject |
|----|-----|---------|---------|
| E15-27-BR-03 | med | recognition/application/scan/capability.py | `embedding_runtime_unavailable` 503 lacks `Retry-After`; WP proxy retries 503 up to 3x |
| E15-27-BR-07 | med | api/main.py | `/ready` probes API-local model cache only; worker `embedding_runtime` only on auth-gated `/health/detailed` |
| E15-27-BR-13 | med | recognition/application/scan/capability.py | `HEARTBEAT_STALE_SECONDS=90` TTL/shape decision not recorded in handoff (record a decision) |

## Picking this up (post-demo)

1. Start a **new** task (E15-30 is archived; do not reopen it) and load the live deferred lists above.
2. Work in bounded TDD slices (RED→GREEN); group by the sections here if useful.
3. As each is addressed, flip its handoff status `deferred` → `fixed` with a `verified_commit_sha`; on merge it auto-promotes to `integrated`. **This doc needs no update** — the DB is canonical.
4. Re-evaluate the behavior items (`BR-03`, `BR-07`) against the live demo before investing — they may stay deferred if off the critical path.
