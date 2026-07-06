# Identity Schema Single Source of Truth — Scope One-Pager

**Date**: 2026-07-05 · **Intake decision**: handoff decision #1229 (`scope_intake_identity_schema_ssot_20260705`) · **Source assessment**: `docs/assessments/current/identity-schema-truth-divergence-assessment-2026-07-05.md`
**Answers derived from**: `literature/extracted/refactoring/distilled/` (Modern Software Engineering, Release It!, Refactoring, DDIA) per operator instruction — no live user Q&A.

## Problem (one line)

Identity schema has three hand-synchronized truths (`001_identity_schema.py` DDL, `Base.metadata` ORM, `EXPECTED_SCHEMA_TABLES` name list) with no enforced consistency relation; the E15-33 boot self-heal automated the divergence (crash-loop risk, RLS-less tenant tables on prod, matview-as-table).

## MVP scope (must-have, slice order)

1. **CI consistency assertions** — cheap, immediate ratchet: every `tenant_id` ORM table ∈ `TENANT_TABLES` ∪ documented allowlist; every runtime-written ORM table has migration DDL; `EXPECTED_SCHEMA_TABLES` reconciles with creatable surfaces. (MSE Ch 8: verify the invariant, not a proxy.)
2. **PG-backed test substrate** — local Postgres (existing `make postgres-start` convention) behind a pytest marker for RLS/matview/advisory-lock paths; sqlite stays for pure-table logic. (MSE Ch 8: control the variables; prerequisite for 3–5.)
3. **Idempotent DDL refactor** — `001_identity_schema.py` decomposed into idempotent `ensure_*` helpers; `upgrade()` and the boot self-heal call the same DDL. One canonical representation (MSE Ch 13 DRY; DDIA system-of-record). Retires PA-05.
4. **Verify upgraded to the real invariant** — assert RLS enabled+forced on tenant tables and `relkind='m'` for the matview; fail-closed on policy drift. (Release It §17.5: monitoring can't detect what it doesn't measure.)
5. **Adopt observability tables** — `assignment_decisions`, `clustering_job_reports` get migration DDL + RLS; allowlist entries removed (ratchet tightens).
6. **Prod remediation (deploy-gated final slice)** — audited one-time RLS application to the E15-29-created tables, verified by the upgraded verify against live prod.

## Interim disposition (owned by `feature/e15-33`, not this task)

- Unwire `python -m scripts.sync_identity_schema` from the Dockerfile CMD on `feature/e15-33` → verify-only boot (pre-task safe state). Smallest reversible step; "nothing is as permanent as a temporary fix" (Release It Ch 7). e15-33 slices 2–4 merge on their own merits.

## Success criteria

- Boot heal from an **empty PG database** converges to a state that passes the upgraded verify (Fail Fast is valid only when the fast path reaches a good state, Release It §5.5).
- PG test dropping one RLS policy → verify exits 1.
- Regression test reproducing the BR2-01 missing-`identity_cluster_refresh_queue` heal gap passes.
- CI consistency assertions green in the standard `make test` path (no PG needed).
- Prod audit evidence: `relrowsecurity=true` and `relforcerowsecurity=true` on all tenant tables.

## Non-functional constraints

- DDL helpers idempotent; safe under concurrent boots via the existing advisory lock; at-least-once + idempotence (exactly-once not required).
- Non-convergent heal → container exits non-zero **before accepting traffic** (Release It §14.3).
- Schema-version-check-at-startup posture retained (Release It §18.2).

## Not-Doing

- No Alembic multi-revision migration chain — greenfield policy keeps single-file `001` at constant revision; the fix is idempotent re-appliable DDL, not migration history.
- No RLS on the materialized view (Postgres unsupported) — `mv_*` read-path isolation is a separate concern, out of scope.
- No RLS on `api_keys` (intentional: key-hash lookup precedes tenant context) — documented allowlist entry instead.
- No changes to e15-33 slices 2–4 content.
- No zero-downtime three-phase deploy machinery (YAGNI; single-tenant demo scale).
- No tenant-isolation model redesign.

## Assumptions (explicit, not user-confirmed)

- Task ref **E15-34** under the E15 epic (prod remediation is entangled with the E15 demo deployment). Rename is cheap if the operator prefers E21-x.
- Single-tenant demo scale means prod remediation urgency is moderate; ordering it last is acceptable.
- Repo convention (Homebrew local Postgres via `make postgres-start`) satisfies the assessment's "PG-backed tests" intent; docker-compose PG is not required.
