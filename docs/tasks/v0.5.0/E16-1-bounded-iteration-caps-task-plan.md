# Task Plan — E16-1. Bounded iteration caps across REST + repos + lifecycle migration + contracts

> **Metadata**
>
> - **Date**: 2026-04-27
> - **Author**: Claude Opus 4.7
> - **Owning Epic**: `docs/epics/v0.5.0/cross-cutting-refactor-epic.md` _(proposed E16 — not yet allocated; see `Status` below)_
> - **Epic Short ID**: `E16` _(proposed; pending epic doc allocation per scope §8)_
> - **Target Branch**: `feature/e16-1-bounded-iteration-caps`
> - **Review Coverage Target**: 2
>
> **Status**: In Progress — Slice 1 is now complete on the `GET /recognition/clusters` canary path, DB-5 chunked legacy migration is landed, and the partial DB-1 cluster-only snapshot batching seam is in place. Remaining REST/repository propagation work in Slices 2-3 and the manual Slice 4 runtime-parity check are still open.

## E16-1. Bounded iteration caps across REST + repos + lifecycle migration + contracts

## Objective

Every REST controller, repository, and lifecycle-migration site listed under §3.1 (RX-3, RX-4) and §3.2 (DB-1, DB-3, DB-5) of the cross-cutting assessment gains a typed `MAX_*` cap and surfaces a `limit` / `total` / `truncated` triple in its response envelope. The matching contract surfaces under `docs/agentic/contracts/` and `packages/shared-contracts/` are updated in the same slice. The result is bounded iteration across the plugin's hottest read paths and a verified single canonical owner for the multipart cap.

## Intake

- **Scope one-pager**: [`docs/scopes/v05-cross-cutting-refactor-scope.md`](../../scopes/v05-cross-cutting-refactor-scope.md)
- **Source assessment**: [`docs/assessments/wp-alt-context-cross-cutting-assessment.md`](../../assessments/wp-alt-context-cross-cutting-assessment.md)
- **Key Q&A decisions**: Recorded under `SCOPE-v05-cross-cutting-20260427` (intake answers: whole-assessment phased, v0.5.0 horizon, all four artifacts, neutral rename).
- **Not-Doing** (inherited from scope §4): no recognition algorithm changes, no asyncio adoption, no net-new features, no backward-compat shims for schema reshapes, no recognition-service contract changes, no benchmarking infrastructure, no multisite hardening.

## Problem Statement

The assessment identifies five iteration sites that are unbounded or weakly bounded today:

- **RX-3** REST controllers that return list responses without an explicit `MAX_*` ceiling on the request side or a `limit`/`total`/`truncated` triple on the response side. Callers (the React SPA, MCP tooling, future cron consumers) cannot detect when results were silently capped, and a malformed query can scan an entire table.
- **RX-4** REST controllers whose pagination contract is partial: a cap exists but is not surfaced in the envelope, or `total` is computed but `truncated` is not, leaving consumers unable to drive a "load more" affordance correctly.
- **DB-1** Repository methods that return all rows for a tenant or status without a hard ceiling.
- **DB-3** Repository methods that paginate but leak the underlying count strategy (e.g. unbounded `COUNT(*)` on hot paths).
- **DB-5** `class-life-cycle-manager.php`'s `migrate_legacy_roster_data()` that iterates legacy rows during activation without a bounded chunk strategy or an idempotent resume token.

Without bounded iteration the v0.5.0 stability work in Phase B (circuit breaker unification, async retry) cannot rest on a known-bounded request shape, and the contract surfaces in `packages/shared-contracts/` will continue to drift from runtime behaviour.

## Constraints

- **Greenfield Policy applies**: no production data exists. Migrations may reshape tables directly; no backfill window. Compatibility shims are explicitly forbidden by the scope's Not-Doing list.
- **Plugin Boundary Rule**: changes are confined to `apps/prototype-wp-alt-context/`, `docs/agentic/contracts/`, `packages/shared-contracts/`. The recognition service wire contract is out of scope.
- **Same-slice contract rule** (per `docs/agentic/rules/planning-review-guide.md`): any controller/repo behaviour change ships with its matching contract update in the same slice.
- **Single canonical owner for the multipart cap**: `MULTIPART_MAX_IMAGES` (PHP) remains the canonical owner; `maxMediaPerBatch` (FE-7) is removed or renamed in the same epic (delegated to E16-2, but verified-not-touched here).
- **Activation-time migration safety**: DB-5 changes must not extend activation runtime past the WordPress admin request budget; chunked iteration is mandatory.
- **No new endpoints, no new admin pages**: refactor only.

## Workflow Principles

- **Bounded iteration is a contract**, not a defensive habit. Every list-returning function declares its cap in code AND in the contract document.
- **One canonical owner per limit**: when two surfaces appear to own the same number, one is the owner and the other reads from it.
- **Tests cover the boundary, not the happy path**: the cap-equals-limit and cap-plus-one cases are the primary assertions.
- **Contracts ship with code**: a slice that updates a controller without updating its contract document fails review on the same-slice contract rule.

## Terminology

- **Bounded iteration site**: a function or method that returns a list whose size is determined by external input (request, table size, cron batch).
- **Envelope triple**: the `{ limit, total, truncated }` triple that callers use to drive paging UI and detect silent caps.
- **Cap owner**: the single PHP constant or schema field that declares the maximum-permitted size for a given iteration site.
- **Resume token**: an opaque cursor (typically `(id, updated_at)`) that lets a chunked migration restart without scanning the prefix it has already processed.

## Current State Analysis

- **What works today**: the proxy controller (`class-abstract-recognition-proxy-controller.php`) and the multipart endpoint already surface `MULTIPART_MAX_IMAGES`; this is the proof-of-pattern for the rest of the slice work.
- **What is broken or drifting**:
  - Several REST controllers under `apps/prototype-wp-alt-context/src/api/` return lists without surfacing `total` or `truncated`, so the SPA cannot tell a complete page from a capped page.
  - Repository methods under `apps/prototype-wp-alt-context/src/sovereign/repositories/` return arrays without an explicit ceiling.
  - `migrate_legacy_roster_data` in `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php` iterates legacy rows without a chunk size or resume token.
  - Contract files under `docs/agentic/contracts/` (e.g. `cluster-snapshot-api.md`, `clustering-api.md`, `curation-sync-api.md`) document fields that runtime no longer exactly returns, and do not document the envelope triple as required.
  - `packages/shared-contracts/` schema files do not declare the `limit`/`total`/`truncated` triple.
- **What assumptions/tests/docs are currently misleading**:
  - The frontend `maxMediaPerBatch` (`js/admin/api/config.ts`) reads as a co-equal to `MULTIPART_MAX_IMAGES`; it is not, and E16-2 removes the duplication. This plan only verifies that the duplication exists and points at it — the resolution belongs to E16-2.

## Target Outcome

After this task lands, every list-returning REST controller and repository method has:

1. A typed `MAX_*` constant declared at the surface that owns the cap.
2. A response envelope that includes `limit`, `total`, and `truncated`.
3. A contract document under `docs/agentic/contracts/` and a schema file under `packages/shared-contracts/` that declare the same envelope shape.
4. A boundary test that exercises both the under-cap and at-cap cases.

`migrate_legacy_roster_data` iterates in chunks bounded by a typed `MAX_LEGACY_MIGRATION_CHUNK` constant, with a resume token in the form `(legacy_id, legacy_updated_at)`.

`MULTIPART_MAX_IMAGES` remains the single canonical cap-owner for multipart uploads. The plan does not remove `maxMediaPerBatch` here (E16-2 owns that), but flags it.

## Context Loading

- Rules:
  - `docs/agentic/rules/planning-review-guide.md` (same-slice contract rule, envelope-triple requirement)
  - `docs/agentic/rules/backend-php-guidelines.md`
  - `docs/agentic/rules/testing-php.md`
  - `docs/agentic/constitution.md` (sr-007 canonical enums; sr-008 parameter slippery slope)
- Contracts:
  - `docs/agentic/contracts/cluster-snapshot-api.md`
  - `docs/agentic/contracts/clustering-api.md`
  - `docs/agentic/contracts/curation-sync-api.md`
  - `packages/shared-contracts/` (schema surface for envelope shape)
- Handoff/MCP state: open findings on `SCOPE-v05-cross-cutting-20260427`; the scope-note review pass already addressed `SCOPE-V05-PLAN-01..04`.
- Source assessment: §3.1 (RX-3, RX-4) and §3.2 (DB-1, DB-3, DB-5) of `docs/assessments/wp-alt-context-cross-cutting-assessment.md`.
- External docs via `ctx7` only if: a WordPress dbDelta or WP_REST_Response shape question cannot be resolved from the codebase. (Likely not needed.)

## Contract and Boundary Impact

| Boundary                        | Owner   | Current Contract                                                | Expected Change                                                              | Compatibility Needed?                       | Verification                                                          |
| ------------------------------- | ------- | --------------------------------------------------------------- | ---------------------------------------------------------------------------- | ------------------------------------------- | --------------------------------------------------------------------- |
| `acx/v1/*` (list endpoints)     | backend | `docs/agentic/contracts/cluster-snapshot-api.md` and siblings   | Every list endpoint declares `limit` / `total` / `truncated` in its envelope | No (greenfield; SPA updates in same slice)  | PHPUnit boundary tests + contract diff on each endpoint               |
| Repository read methods         | backend | `apps/prototype-wp-alt-context/src/sovereign/repositories/*`    | Each list method takes a typed cap and returns the envelope triple           | No (in-process; callers updated together)   | PHPUnit repository tests asserting cap-equals-limit and cap-plus-one  |
| Activation-time legacy migration | backend | `class-life-cycle-manager.php::migrate_legacy_roster_data`      | Chunked iteration with `MAX_LEGACY_MIGRATION_CHUNK` and resume token         | No (greenfield; activation can re-run safely) | PHPUnit lifecycle test + manual activation observation                |
| Shared contracts (TS/JS)        | shared  | `packages/shared-contracts/`                                    | Schema declares the envelope triple as required                              | No (consumers updated in same slice)        | TS type check + contract-fixture diff                                 |

## Proposed Solution

Land the work in four bounded slices: (1) declare the cap-owner pattern and apply it to one canary controller end-to-end (REST + repo + contract + SPA consumer + tests), (2) propagate the same pattern across the remaining REST controllers (RX-3, RX-4), (3) propagate it across the remaining repository methods (DB-1, DB-3), (4) introduce the chunked-migration pattern for DB-5 with its resume token. Each slice closes with executable proof.

## Files and Surfaces to Change

| Surface  | File                                                                                          | Change                                                                                                            |
| -------- | --------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| backend  | `apps/prototype-wp-alt-context/src/api/` (RX-3, RX-4 controllers identified by assessment)    | Add `MAX_*` constants; surface `limit` / `total` / `truncated` in envelopes                                        |
| backend  | `apps/prototype-wp-alt-context/src/sovereign/repositories/` (DB-1, DB-3 list methods)         | Accept typed cap parameter; return envelope triple                                                                 |
| backend  | `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php`                      | Introduce chunked `migrate_legacy_roster_data` with `MAX_LEGACY_MIGRATION_CHUNK` and `(legacy_id, updated_at)` resume token |
| docs     | `docs/agentic/contracts/cluster-snapshot-api.md`, `clustering-api.md`, `curation-sync-api.md` | Document envelope triple per endpoint                                                                              |
| shared   | `packages/shared-contracts/`                                                                  | Update schemas to require `limit` / `total` / `truncated` on list responses                                       |
| frontend | `apps/prototype-wp-alt-context/js/` (SPA consumers of list endpoints)                         | Read `truncated` to drive empty-state vs partial-state UI; no new components                                       |
| tests    | PHPUnit suites for each touched controller and repository method                              | Boundary cases: cap-equals-limit, cap-plus-one, malformed `limit` query                                            |
| tests    | Lifecycle PHPUnit test                                                                         | Resume-token round-trip; chunk-size respected                                                                      |

## Related Files

| File                                                                          | Note                                                                                              |
| ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | Already uses `MULTIPART_MAX_IMAGES`; pattern reference                                            |
| `apps/prototype-wp-alt-context/js/admin/api/config.ts`                         | Holds `maxMediaPerBatch`; flagged but not removed here (E16-2 owns)                               |
| `docs/scopes/v05-cross-cutting-refactor-scope.md`                              | §3 success criteria; §6 candidate stub; §8 epic-allocation gate                                   |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && composer test -- --testsuite=api`
  - `cd apps/prototype-wp-alt-context && composer test -- --testsuite=repositories`
  - `cd apps/prototype-wp-alt-context && composer test -- --testsuite=lifecycle`
  - `cd apps/prototype-wp-alt-context && npm run typecheck`
- Runtime-parity / environment checks:
  - Manual LocalWP activation of the plugin to observe chunked migration on a seeded legacy fixture
- Contract/fixture verification:
  - `make contracts-check` (or equivalent diff between contract docs and shared schema)
  - Fixture round-trip: capture a real REST response per touched endpoint and assert envelope shape
- Manual verification:
  - Open the SPA, drive each list view to its cap, observe the truncated-state affordance

## Slice Delivery

### Slice 1: Canary endpoint — pattern proof on one controller end-to-end

**Goal**: Use `GET /recognition/clusters` as the canary controller path and apply the full pattern: cap constant, envelope triple, contract update, shared-schema update, SPA consumer update, and boundary tests.

**Status note**: Slice 1 is complete on `ClustersController::list_clusters()`. The canary path uses the existing `LIST_CLUSTERS_MAX_LIMIT` cap owner, returns the canonical `{ clusters, limit, total, truncated }` envelope, documents that shape in `clustering-api.md`, and now has a matching shared schema plus golden fixture under `packages/shared-contracts/`.

Changes:

- Confirm `LIST_CLUSTERS_MAX_LIMIT` on `ClustersController` is the canary cap owner for `GET /recognition/clusters`.
- Surface `limit` / `total` / `truncated` in the `GET /recognition/clusters` response envelope for local and proxied reads.
- Update `docs/agentic/contracts/clustering-api.md` to document the canonical cluster-list envelope.
- Add `recognition-cluster-list-response.schema.json` and `cluster-list-response.golden.json` under `packages/shared-contracts/`.
- Keep the SPA consumer (`listRecognitionClusters`) aligned to the envelope contract.
- Cover the canary path with PHPUnit and Vitest boundary/contract tests.

Proof:

- PHPUnit: `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit/ClustersControllerTest.php` passes.
- Vitest: `cd apps/prototype-wp-alt-context && npx vitest run js/admin/api/__tests__/recognitionApi.test.ts js/admin/api/__tests__/clusterListContract.test.ts` passes.
- Contract diff: the same triple appears in `clustering-api.md`, `recognition-cluster-list-response.schema.json`, and `cluster-list-response.golden.json`.

### Slice 2: Propagate envelope triple across remaining REST controllers (RX-3, RX-4)

**Goal**: Apply the canary pattern to every remaining list endpoint identified by assessment §3.1.

Changes:

- For each controller in the RX-3 / RX-4 set, declare its `MAX_*` constant and surface the envelope triple.
- Update each touched contract under `docs/agentic/contracts/` and the matching shared schema.
- Update SPA consumers to read `truncated`.
- Boundary tests for each endpoint.

Proof:

- PHPUnit api suite passes.
- Contract diff per endpoint: triple present in markdown, schema, fixture.

### Slice 3: Propagate envelope triple across repository methods (DB-1, DB-3)

**Goal**: Apply the same pattern at the repository layer so callers cannot bypass the cap by going around the controller.

Changes:

- For each list method in the DB-1 / DB-3 set, accept a typed cap parameter and return the envelope triple.
- Update PHPUnit repository tests with boundary cases.
- Verify all REST callers pass through the cap from request to repository (no silent re-capping).

Proof:

- PHPUnit repositories suite passes.
- A trace test demonstrates the cap value propagates from request to SQL.

### Slice 4: Chunked legacy migration (DB-5) with resume token

**Goal**: Replace the unbounded `migrate_legacy_roster_data` loop with a chunked iterator and a resume token.

Changes:

- Introduce `MAX_LEGACY_MIGRATION_CHUNK` in `class-life-cycle-manager.php`.
- Refactor `migrate_legacy_roster_data` to iterate in chunks with a `(legacy_id, legacy_updated_at)` resume token.
- Add lifecycle PHPUnit test exercising round-trip on a seeded fixture (resume mid-batch).
- Document the activation-safe runtime budget assumption inline (no external runbook entry — that belongs to E16-6).

Proof:

- PHPUnit lifecycle suite passes.
- Manual LocalWP activation against a seeded legacy fixture completes without exceeding the WP admin request budget.

---

## Consolidated Checklist

> Checklist describes work being delivered, not finding status. Finding status is queried via `review_findings(review={"operation":"list","status":"open","task_ref":"E16-1"})`.

## Context and Ownership

- [x] Loaded scope note, source assessment, planning-review-guide, and the canary controller's current contract.
- [x] Confirmed `ctx7` is not required (or recorded the specific dependency reason if it becomes required mid-slice).
- [x] Recorded boundary ownership (backend owns envelope; shared-contracts mirrors; SPA consumes) with the canonical cap owner per surface.

### Checklist for Slice 1: Canary endpoint

- [x] Confirm `LIST_CLUSTERS_MAX_LIMIT` on `ClustersController` as the canary cap owner.
- [x] Surface `limit` / `total` / `truncated` in the `GET /recognition/clusters` envelope.
- [x] Update `docs/agentic/contracts/clustering-api.md` to document the triple.
- [x] Add the matching shared schema and golden fixture in `packages/shared-contracts/`.
- [x] Keep the SPA consumer `listRecognitionClusters` aligned to the envelope metadata.
- [x] Add PHPUnit/Vitest boundary coverage for the cluster-list envelope.
- [x] Add a shared golden fixture showing the triple and cluster-summary payload shape.

### Checklist for Slice 2: Remaining REST controllers (RX-3, RX-4)

- [x] Apply the cap-and-envelope pattern to every controller in the RX-3 / RX-4 set.
- [x] Update each controller's contract document and shared schema in the same slice.
- [x] Update SPA consumers of each touched endpoint to read `truncated`.
- [x] Add boundary tests per endpoint.

### Checklist for Slice 3: Repository methods (DB-1, DB-3)

- [x] Apply the typed-cap-and-envelope pattern to every list method in the DB-1 / DB-3 set completed so far in this branch (`ClustersRepository::merge_snapshot_for_tenant()`, `IdentityMembersRepository::list_for_cluster()`, and the split-topology drain caller path).
- [x] Verify request-to-SQL cap propagation with a trace test for the split-topology drain caller path.
- [x] Add repository boundary tests for the Slice 3 seams completed so far in this branch.

### Checklist for Slice 4: Chunked legacy migration (DB-5)

- [x] Introduce `MAX_LEGACY_MIGRATION_CHUNK` constant.
- [x] Refactor `migrate_legacy_roster_data` to iterate in chunks with the `(legacy_id, legacy_updated_at)` resume token.
- [x] Add lifecycle round-trip PHPUnit test.
- [ ] Manually verify activation completes within budget against a seeded legacy fixture.

## Review Readiness

- [ ] No controller change has merged without its matching contract document and shared-schema update in the same slice.
- [ ] Runtime-parity check (LocalWP activation) was exercised for Slice 4 and the result captured as a handoff note.
- [ ] Handoff decision per slice records the change, the verification, and any contract implications.

## Stretch Goals

- [ ] Generate a contract-fixture diff helper that asserts every list endpoint's runtime envelope matches its declared schema.
- [ ] Capture a single-page summary of cap-owners per surface for the eventual E16 epic doc.

## Success Criteria

- [ ] Every site listed in RX-3 / RX-4 / DB-1 / DB-3 / DB-5 has a typed `MAX_*` cap and surfaces the `limit` / `total` / `truncated` triple.
- [ ] Each touched contract document and shared schema declares the triple in the same slice as the runtime change.
- [ ] `MULTIPART_MAX_IMAGES` remains the single canonical owner for the multipart cap (verified-not-touched here; E16-2 owns the `maxMediaPerBatch` resolution).
- [ ] Boundary tests pass on every touched endpoint and repository method.
- [x] `migrate_legacy_roster_data` iterates in bounded chunks with a working resume token.
