# Task Plan: E15-34 Identity Schema Single Source of Truth

> **Metadata**
>
> - **Date**: 2026-07-05 22:15 EST
> - **Author**: claude-fable-5
> - **Owning Epic**: docs/epics/v0.4.0/public-demo-launch-readiness-epic.md
> - **Epic Short ID**: E15
> - **Target Branch**: `feature/e15-34`
> - **Review Coverage Target**: 2

---

## E15-34. Identity Schema Single Source of Truth

## Objective

Collapse the identity schema's three partially-overlapping truths (migration DDL, ORM metadata, `EXPECTED_SCHEMA_TABLES`) into one canonical, idempotent DDL surface that both `upgrade()` and the boot self-heal call, with CI assertions and a policy-aware verifier that fail closed on drift. Finish with an audited RLS remediation of the prod tables created by the E15-29 emergency repair.

## Intake

- **Scope one-pager**: `docs/scopes/identity-schema-single-source-of-truth-scope.md`
- **Key Q&A decisions**: decision #1229 (`scope_intake_identity_schema_ssot_20260705`)
- **Not-Doing**: no Alembic multi-revision chain (greenfield `001` stays constant-revision); no RLS on the materialized view (Postgres unsupported) or on `api_keys` (pre-tenant-context lookup, documented allowlist); no `mv_*` read-path isolation work; no changes to e15-33 slices 2–4; no zero-downtime three-phase deploy machinery; no tenant-isolation model redesign.

## Problem Statement

`docs/assessments/current/identity-schema-truth-divergence-assessment-2026-07-05.md` (root cause of umbrella finding E15-33-INV-01) confirmed: schema truth lives in three hand-synchronized places with no enforced consistency relation. Consequences already observed: a boot self-heal that cannot create `identity_cluster_refresh_queue` (crash-loop, finding E15-33-BR2-01), `create_all` emitting tenant tables without RLS (silent cross-tenant exposure, E15-33-BR2-02; already live on prod via the E15-29 manual repair), and the materialized view creatable as a plain table (E15-33-BR2-04). Any mechanism built on one truth alone inherits the divergence; the fix is a single canonical DDL source plus verification of the actual invariant (RLS enforced), not another sync script.

## Constraints

- **Greenfield migration policy**: schema changes go directly into `001_identity_schema.py` under its constant revision. The refactor makes its DDL idempotent and re-appliable; it does not introduce a revision chain.
- **Security surface**: every slice that touches RLS requires review before merge (pre-merge gate, ≥2 review passes per this plan's coverage target).
- **Test substrate**: RLS, materialized views, and advisory locks are Postgres-only. They must be verified against local Postgres (repo convention: `make -C apps/prototype-description-service postgres-start`, Homebrew). sqlite remains the substrate for pure-table logic.
- **Prod entanglement**: prod already carries RLS-less `assignment_decisions` / `clustering_job_reports` (E15-29 repair). Remediation is deploy-gated operator work and is the final slice.
- **Coordination with `feature/e15-33`** (unmerged at plan time): `scripts/sync_identity_schema.py` exists only on that branch. Slice 3 authors the delegating replacement in this branch. If e15-33 merges first, Slice 3 rewrites the merged file in place; if not, Slice 3 introduces it fresh. Either way the `create_all`-based heal never reaches prod (interim unwiring of the Dockerfile CMD is owned by e15-33, not this task).

## Workflow Principles

- One canonical representation of every schema decision; the heal path delegates to the migration's own DDL, never re-derives schema from the ORM (DRY, MSE Ch 13; DDIA system-of-record).
- Ratchet, don't flag-day: CI assertions land first with explicit, documented allowlists for known divergence, and later slices shrink the allowlists to empty.
- Fail fast only into a reachable good state: verify may only fail closed on conditions the heal (or a documented operator runbook) can repair (Release It §5.5).
- Verify the invariant, not a proxy: table-name checks are replaced by policy-level assertions (Release It §17.5; MSE Ch 8).

## Terminology

- **Truth A / B / C**: migration DDL in `001_identity_schema.py` / ORM `Base.metadata` / `EXPECTED_SCHEMA_TABLES` name list consumed by the verifier.
- **Heal**: boot-time schema reconciliation entrypoint (today `scripts/sync_identity_schema.py` on e15-33, `create_all`-based; after Slice 3, a thin caller of the migration's `ensure_*` helpers).
- **Ratchet allowlist**: named constant in the Slice-1 test module listing tables temporarily exempt from an assertion, each entry carrying a `# removed in Slice N` comment.

## Current State Analysis

- `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` (1,411 lines): monolithic `upgrade()` (line 92) with raw-SQL RLS loops over `TENANT_TABLES` (line 18), matview + trigger + `identity_cluster_refresh_queue` DDL; `EXPECTED_SCHEMA_TABLES` (line 40) is a hand list.
- `apps/prototype-description-service/scripts/verify_identity_schema.py` (87 lines): checks table names only; blind to RLS state and relation kind. Unit test: `recognition/tests/scripts/test_verify_identity_schema.py`.
- `db/models/observability.py` defines `assignment_decisions` / `clustering_job_reports`: written live by the recognition runtime, `tenant_id`-bearing, **no migration DDL, no RLS anywhere**.
- `db/models/identity.py` line 222 maps the matview as a `Table` with `info={"is_materialized_view": True}`; nothing consumes the marker.
- Dockerfile line 91 CMD (main): `alembic upgrade head && python -m scripts.verify_identity_schema && uvicorn ...` — no heal on main; e15-33 wires the hazardous `create_all` heal.
- Empirical divergence (assessment, reproducible): `EXPECTED_SCHEMA_TABLES − Base.metadata = {identity_cluster_refresh_queue}`; `Base.metadata − EXPECTED = {assignment_decisions, clustering_job_reports, mv_identity_cluster_centroids}`; `tenant_id` tables missing from `TENANT_TABLES` = those plus `api_keys` (intentional).

## Target Outcome

`001_identity_schema.py` exposes idempotent `ensure_*` helpers (tables, RLS, matview, refresh queue, triggers) that `upgrade()` composes; the heal entrypoint calls the same helpers under the existing advisory lock, so healing from any partial state — including an empty database — converges to the full schema **with RLS**. The verifier asserts the load-bearing invariant (RLS enabled+forced on every `TENANT_TABLES` member, `relkind='m'` for the matview, refresh queue present) and fails closed. CI asserts the three truths' consistency relations on every test run with no database. The observability tables become first-class migration citizens with RLS. Prod is remediated and re-verified.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`
- Assessment: `docs/assessments/current/identity-schema-truth-divergence-assessment-2026-07-05.md`
- Scope: `docs/scopes/identity-schema-single-source-of-truth-scope.md`
- Handoff/MCP: task ref `E15-34`; related findings E15-33-INV-01, E15-33-BR2-01/02/04/10, PA-05 (query live: `review_findings(review={"operation":"list","task_ref":"E15-33"})`); decisions 1194/1197/1203 (E15-29 repair), #1229 (intake).
- Prior plan surface (flawed mechanism prescription, for contrast): `docs/tasks/15.0/E15-33-prod-deploy-convergence-task-plan.md` § Slice 1.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Identity Postgres schema (internal to description service) | backend | `001_identity_schema.py` | Same logical schema; DDL becomes idempotent; observability tables adopted | no — greenfield, no external consumer reads the migration | PG-backed tests + upgraded verifier |
| Container boot sequence (Dockerfile CMD) | backend | `alembic upgrade head && verify && uvicorn` | heal step delegates to migration helpers (replaces e15-33 `create_all` heal) | no | boot-path PG test + compose smoke |

## Proposed Solution

Refactor the migration into composable idempotent DDL units and make every other schema consumer delegate to them. Land the cheap consistency ratchet first, stand up the PG substrate second, then refactor, then tighten verification, then adopt the orphan tables, then remediate prod. Each slice is independently reviewable and keeps CI green.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` | Decompose into `ensure_tables()`, `ensure_rls()`, `ensure_matview()`, `ensure_refresh_queue()`, `ensure_triggers()`; add `heal(connection)`; `upgrade()` composes the same helpers; adopt observability-table DDL + RLS |
| backend | `apps/prototype-description-service/scripts/sync_identity_schema.py` | New/rewritten thin entrypoint: advisory lock + `heal()`; no `create_all` |
| backend | `apps/prototype-description-service/scripts/verify_identity_schema.py` | Assert RLS enabled+forced per `TENANT_TABLES`, matview `relkind='m'`, refresh queue exists; fail-closed exit codes distinguishing heal-repairable vs operator-required |
| tests | `apps/prototype-description-service/recognition/tests/schema/test_schema_truth_consistency.py` | New: no-DB set-relation assertions between the three truths (ratchet allowlists) |
| tests | `apps/prototype-description-service/recognition/tests/schema/test_identity_schema_pg.py` | New: PG-marked tests — empty-DB heal convergence, idempotent re-run, dropped-policy verify failure, matview relkind, BR2-01 queue-table regression |
| tests | `apps/prototype-description-service/recognition/tests/conftest.py` | Add PG session fixture (env `IDENTITY_PG_TEST_URL`, default `postgresql+psycopg://localhost:5432/acx_identity_test`, sync; skip if unreachable) |
| tests | `apps/prototype-description-service/pyproject.toml` | Register `pg` marker in `[tool.pytest.ini_options].markers` |
| tests | `apps/prototype-description-service/recognition/tests/scripts/test_verify_identity_schema.py` | Extend for new verifier assertions/exit codes |
| docs | `docs/runbooks/prod-identity-rls-remediation.md` | New: audited prod remediation runbook (Slice 6) |
| backend | `apps/prototype-description-service/Dockerfile` | CMD heal step calls the delegating `sync_identity_schema` (only after Slice 3 proof) |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/db/models/observability.py` | Source of the two orphan tenant tables |
| `apps/prototype-description-service/db/models/identity.py` | Matview `Table` mapping (line 222 marker) |
| `apps/prototype-description-service/db/tenant_context.py` | RLS session-context mechanics the policies rely on |
| `apps/prototype-description-service/recognition/application/persistence/assignment_writer.py` | Runtime writer of `assignment_decisions` (Slice 5 RLS check) |
| `apps/prototype-description-service/recognition/application/orchestration/clustering/decision_handler.py` | Runtime writer of `clustering_job_reports` (Slice 5 RLS check) |
| `apps/prototype-description-service/recognition/application/services/purge_service.py` | Purges both observability tables (Slice 5 RLS check) |
| `apps/prototype-description-service/db/docker-init/`, `db/docker-prod-init/` | Boot-time init scripts that may reference schema state |

## Verification Strategy

- Deterministic tests (no DB): `make -C apps/prototype-description-service test` (runs `uv run pytest`; includes the truth-consistency module)
- PG-backed tests: `make -C apps/prototype-description-service postgres-start` then `cd apps/prototype-description-service && VIRTUAL_ENV= uv run --locked --extra dev pytest -m pg recognition/tests/schema/`
- Contract/fixture verification: truth-consistency assertions are the contract check (no fixture drift possible — they import the live modules)
- Runtime parity: compose boot smoke — build the service image, boot against an empty PG volume, assert verify passes and the app serves `/health` (reuse the e15-33 Slice 4 smoke pattern if merged; otherwise `docker compose up` + curl)
- Manual verification (Slice 6 only): operator runs the runbook against prod, captures `pg_class.relrowsecurity/relforcerowsecurity` audit output before/after

## Slice Delivery

### Slice 1: Truth-consistency CI ratchet

**Goal**: Every future divergence between the three schema truths fails CI immediately, with today's known divergence held in explicit shrinking allowlists.

Changes:

- New `recognition/tests/schema/test_schema_truth_consistency.py` importing `db.models`, `db.base.Base`, and `db.migrations.versions.001_identity_schema` (via `importlib`, no DB) asserting: (a) every `Base.metadata` table carrying a `tenant_id` column is in `TENANT_TABLES` or in `RLS_EXEMPT_ALLOWLIST = {"api_keys": "<rationale>", "mv_identity_cluster_centroids": "<rationale>", "assignment_decisions": "removed in Slice 5", "clustering_job_reports": "removed in Slice 5"}`; (b) every table in `EXPECTED_SCHEMA_TABLES` is ORM-creatable or in `RAW_SQL_TABLES = {"identity_cluster_refresh_queue"}` (constant exported from the migration in this slice); (c) every ORM table written by runtime code (`assignment_decisions`, `clustering_job_reports` — listed as `RUNTIME_WRITTEN_ORM_TABLES`) appears in `EXPECTED_SCHEMA_TABLES` or in a `MIGRATION_GAP_ALLOWLIST` emptied in Slice 5. Note in the test module that `EXPECTED_SCHEMA_TABLES` membership is a **proxy** for migration DDL coverage until Slice 3 tightens (c) to "creatable by the `ensure_*` helpers".
- Export `RAW_SQL_TABLES` from `001_identity_schema.py` next to `EXPECTED_SCHEMA_TABLES`.

Proof:

- `make -C apps/prototype-description-service test` green; temporarily deleting one allowlist entry makes the suite fail with a message naming the divergent table.

### Slice 2: PG test substrate

**Goal**: Postgres-only schema behavior is testable locally and in review evidence.

Changes:

- `pg` marker registered in `apps/prototype-description-service/pyproject.toml` `[tool.pytest.ini_options].markers` (next to the existing `integration` marker); the conftest holds only the fixture.
- Session fixture creates/drops `acx_identity_test` from `IDENTITY_PG_TEST_URL` (default `postgresql+psycopg://localhost:5432/acx_identity_test` — **sync** psycopg URL; DDL and verifier run on sync engines. Derive the asyncpg variant inside tests only where an async runtime writer is exercised), skipping cleanly when PG is unreachable.
- Baseline PG test: apply the migration to the empty test DB via `alembic.command.upgrade(Config("db/alembic.ini"), "head")` with `sqlalchemy.url` overridden to the fixture URL; assert all `EXPECTED_SCHEMA_TABLES` exist, RLS is enabled+forced on `TENANT_TABLES` (raw `pg_class`/`pg_policies` query), and `mv_identity_cluster_centroids` has `relkind='m'`.

Proof:

- `make -C apps/prototype-description-service postgres-start && VIRTUAL_ENV= uv run --locked --extra dev pytest -m pg recognition/tests/schema/` green; suite skips (not fails) without PG.

### Slice 3: Idempotent DDL helpers + delegating heal

**Goal**: One canonical DDL surface; the heal can create everything the verifier demands, with RLS, and is safe to re-run.

Changes:

- Decompose `upgrade()` into idempotent `ensure_*` helpers (`CREATE TABLE IF NOT EXISTS` / catalog-checked `ALTER`/`CREATE POLICY`/`CREATE MATERIALIZED VIEW IF NOT EXISTS`); `upgrade()` composes them; behavior on an empty DB is unchanged (Slice 2 baseline test still green).
- Add `heal(connection)` in the migration module composing the same helpers.
- Author `scripts/sync_identity_schema.py` as a thin caller: existing advisory-lock pattern (port from e15-33 `bdb65d9a` if unmerged) around `heal()`; exit non-zero if post-heal verify still fails. No `create_all` anywhere.
- Tighten Slice-1 assertion (c): replace the `EXPECTED_SCHEMA_TABLES`-membership proxy with "creatable by the `ensure_*` helpers" now that `heal()` exists.
- Wire the Dockerfile (line 91) CMD in this slice, after the PG proofs pass, to exactly: `alembic -c db/alembic.ini upgrade head && python -m scripts.sync_identity_schema && python -m scripts.verify_identity_schema && uvicorn api.main:app --host 0.0.0.0 --port 8000` — alembic stays for the empty-DB/stamp path; heal covers drift on already-stamped DBs; verify gates boot.

Proof:

- PG tests: heal from empty DB → upgraded-verify-equivalent checks pass; running `heal()` twice is a no-op (second run emits no DDL errors, schema unchanged); BR2-01 regression — drop `identity_cluster_refresh_queue`, heal recreates it; BR2-02 regression — heal-created tenant tables have RLS enabled+forced; concurrency — two concurrent `heal()` invocations serialize on the advisory lock, both exit 0, schema intact (closes the E15-33-BR2-10 untested-lock gap).

### Slice 4: Verifier asserts the real invariant

**Goal**: Verification fails closed on policy drift, not just name drift.

Changes:

- `verify_identity_schema.py`: keep name checks; add per-`TENANT_TABLES` assertion of `relrowsecurity AND relforcerowsecurity` plus presence of the `tenant_isolation_*` policy; assert matview `relkind='m'`; assert refresh queue exists. Distinct exit codes/messages for heal-repairable vs operator-action conditions (rg-008 spirit: fail fast, name the gap).
- Extend `recognition/tests/scripts/test_verify_identity_schema.py` and add a PG test: drop one policy → verify exits 1 with the table named.

Proof:

- PG test demonstrating dropped-policy detection; unit tests for exit-code mapping; `make -C apps/prototype-description-service test` green.

### Slice 5: Adopt observability tables

**Goal**: `assignment_decisions` and `clustering_job_reports` become migration-owned tenant tables with RLS; ratchet allowlists shrink to their permanent core.

Changes:

- Add both tables' DDL to the migration helpers; add both to `TENANT_TABLES` and `EXPECTED_SCHEMA_TABLES`; RLS policies applied by the shared `ensure_rls()`.
- Remove their entries from `RLS_EXEMPT_ALLOWLIST` and `MIGRATION_GAP_ALLOWLIST` (permanent residue: `api_keys`, `mv_*` with rationale strings only).
- Confirm runtime writers (`recognition/application/persistence/assignment_writer.py`, `recognition/application/orchestration/clustering/decision_handler.py`, `recognition/application/services/purge_service.py`) still pass under RLS with tenant context set (PG test).

Proof:

- Truth-consistency module green with shrunken allowlists; PG test writing/purging both tables under two tenants shows isolation (tenant B cannot read tenant A rows).

### Slice 6: Prod remediation (deploy-gated)

**Goal**: Live prod tables created RLS-less by the E15-29 repair are remediated and re-verified; recurrence is impossible while the upgraded verifier gates boot.

Changes:

- `docs/runbooks/prod-identity-rls-remediation.md`: pre-audit SQL (`SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class JOIN pg_namespace ... WHERE relname = ANY(TENANT_TABLES)`), the exact `heal()` invocation (or one-shot `python -m scripts.sync_identity_schema`) to apply, post-audit SQL, rollback note (RLS enable is non-destructive; disable statements listed).
- Operator executes against prod; evidence (before/after audit output, upgraded verify exit 0) recorded as an MCP test_result on E15-34.

Proof:

- Post-remediation audit shows `relrowsecurity=t, relforcerowsecurity=t` for all `TENANT_TABLES` including the adopted tables; upgraded verify passes against prod.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded assessment, scope one-pager, backend/testing rules, and E15-33 findings context before editing.
- [ ] Recorded boundary expectations (schema internal; boot CMD change) in the first slice decision.

### Checklist for Slice 1: Truth-consistency CI ratchet

- [ ] `RAW_SQL_TABLES` exported from `001_identity_schema.py`.
- [ ] `test_schema_truth_consistency.py` with three set-relation assertions + documented allowlists.
- [ ] `make -C apps/prototype-description-service test` evidence captured; deliberate-breakage check demonstrated.

### Checklist for Slice 2: PG test substrate

- [ ] `pg` marker + session fixture with unreachable-skip behavior.
- [ ] Baseline empty-DB `upgrade()` test asserting tables + RLS + relkind.
- [ ] PG run evidence captured.

### Checklist for Slice 3: Idempotent DDL helpers + delegating heal

- [ ] `ensure_*` helpers extracted; `upgrade()` composes them; Slice 2 baseline still green.
- [ ] `heal()` + thin `sync_identity_schema.py` under advisory lock; no `create_all` remains.
- [ ] Slice-1 assertion (c) tightened from the EXPECTED-membership proxy to heal-creatable tables.
- [ ] Double-heal idempotence, BR2-01/BR2-02 regressions, and concurrent-heal advisory-lock test green; Dockerfile CMD wired to the exact documented string.

### Checklist for Slice 4: Verifier asserts the real invariant

- [ ] RLS enabled+forced + policy-presence + relkind + queue assertions in verifier with distinct exit codes.
- [ ] Dropped-policy PG test and exit-code unit tests green.

### Checklist for Slice 5: Adopt observability tables

- [ ] Both tables migration-owned, in `TENANT_TABLES` + `EXPECTED_SCHEMA_TABLES`, RLS applied.
- [ ] Allowlists shrunk to permanent core; two-tenant isolation test green.
- [ ] Runtime writer/purge paths verified under RLS.

### Checklist for Slice 6: Prod remediation (deploy-gated)

- [ ] Runbook authored with pre/post audit SQL and rollback note.
- [ ] Operator execution evidence (before/after audit, verify exit 0) recorded as MCP test_result.

## Review Readiness

- [ ] No RLS-touching slice merged without a review pass recorded in MCP.
- [ ] Runtime-parity compose boot smoke included where sqlite tests could mask PG behavior.
- [ ] Handoff decision per slice records change, verification, and contract implications.

## Stretch Goals

- [ ] Compose boot smoke wired into CI (not just local evidence).
- [ ] `test_key_rotation` flake triage if the full-suite run trips it (pre-existing, not a blocker).

## Success Criteria

- [ ] Heal from an empty PG database converges to a schema that passes the upgraded verifier (including RLS and matview kind).
- [ ] CI fails on any new divergence between migration DDL, ORM metadata, and `EXPECTED_SCHEMA_TABLES` without a documented allowlist entry.
- [ ] Dropped-RLS-policy drift on any tenant table is detected fail-closed at boot.
- [ ] `assignment_decisions` / `clustering_job_reports` are migration-owned with enforced RLS.
- [ ] Prod audit evidence shows RLS enabled+forced on all tenant tables; PA-05 and the E15-33 BR2 schema findings can be dispositioned against this task's ref.
