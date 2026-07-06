# Identity Schema Truth Divergence — Root-Cause Assessment

**Date**: 2026-07-05 · **Origin**: E15-33 BR2 review (findings E15-33-BR2-01/02/04, umbrella E15-33-INV-01) · **Status**: investigation confirmed; fix requires a dedicated planned task
**Evidence anchors**: worktree `feature/e15-33` @ `bdb65d9a0de08ba46b42f5663315ff682f8198d7`; handoff decisions 1194/1197/1203 (E15-29)

## Verdict

The E15-33 Slice 1 self-heal (`create_all(Base.metadata)` at container boot) is **not a local bug — it is the first automated consumer of a pre-existing architectural smell**: the identity schema has **three partially-overlapping sources of truth with no enforced consistency relation**. Any mechanism built on one source alone inherits the divergence. Patching the sync script inside E15-33's auto-fix loop would re-encode the smell; the fix needs its own planned task with a security review (RLS) and a Postgres-backed test substrate.

## Symptom (what the BR2 review caught)

At `bdb65d9a`, the boot self-heal:

1. **Cannot create `identity_cluster_refresh_queue`** — required by the fail-closed verifier but raw-SQL-only (no ORM model). If that table is the missing one, self-heal exits 0 → verify exits 1 → **crash-loop**: the mechanism fails at the exact recurrence it was built to prevent (BR2-01, HIGH).
2. **Creates tenant tables without RLS** — the migration applies `ENABLE/FORCE ROW LEVEL SECURITY` + `tenant_isolation_*` policies via raw `op.execute`; `create_all` emits bare `CREATE TABLE`. Table-granular verify stays green → **silent cross-tenant read exposure** (BR2-02, HIGH).
3. **Would create the materialized view `mv_identity_cluster_centroids` as a plain table** — it is ORM-mapped as a `Table` (already flagged `info={"is_materialized_view": True}`, marker ignored); runtime `REFRESH MATERIALIZED VIEW` then fails (BR2-04, MED).

## Empirical evidence (reproducible)

```python
# .venv python, apps/prototype-description-service
import db.models; from db.base import Base; import importlib
mig = importlib.import_module('db.migrations.versions.001_identity_schema')
set(mig.EXPECTED_SCHEMA_TABLES) - set(Base.metadata.tables)
# => {'identity_cluster_refresh_queue'}          # verify demands it; create_all can never make it
set(Base.metadata.tables) - set(mig.EXPECTED_SCHEMA_TABLES)
# => {'assignment_decisions', 'clustering_job_reports', 'mv_identity_cluster_centroids'}
# tenant_id-bearing metadata tables absent from the migration's TENANT_TABLES RLS block:
# => {'api_keys', 'assignment_decisions', 'clustering_job_reports', 'mv_identity_cluster_centroids'}
```

Qualifiers:

- `api_keys` exclusion from `TENANT_TABLES` is likely **intentional** (key-hash lookup runs before tenant context is set). Postgres does not support RLS on materialized views at all, so `mv_*` exclusion is inherent (its read-path isolation is a separate concern).
- `assignment_decisions` / `clustering_job_reports` are **not test scaffolding**: written live by the recognition runtime (`recognition/application/persistence/assignment_writer.py`, `orchestration/clustering/decision_handler.py`) and purged by `purge_service.py`. They carry `tenant_id`, have **no migration DDL and no RLS anywhere**.

## Root cause — three layers

### 1. Mechanism (proximate)

`create_all(Base.metadata)` can only express the ORM's lossy subset of the real schema. It is simultaneously **too narrow** (no raw-SQL tables, no RLS policies, no matview/trigger/function DDL) and **too broad** (ships every ORM table, including ones the identity migration doesn't own).

### 2. Architecture (underlying smell)

Three schema truths, hand-synchronized, no assertions connecting them:

| Source | Owns | Blind to |
| --- | --- | --- |
| `001_identity_schema.py` (single-file greenfield migration, constant revision) | full DDL incl. RLS, matview, refresh queue, triggers | ORM-only tables (`assignment_decisions`, `clustering_job_reports`) |
| `Base.metadata` (ORM models) | app-visible tables | RLS policies, matview semantics, raw-SQL surfaces |
| `EXPECTED_SCHEMA_TABLES` (hand list in the migration, consumed by `verify_identity_schema`) | table *names* only | everything about table *contents/policies/kind*; ORM-only tables |

The greenfield policy (in-place edits to `001` under a constant revision) is the **drift generator**: an already-stamped DB never re-runs the migration, so every in-place addition silently diverges prod until something (manual repair, now self-heal) reconciles it — from whichever partial truth that something happens to read.

### 3. Process (how it got designed in)

The task plan prescribed the mechanism because it "reuses the exact mechanism used to repair prod in E15-29 (decision 1194)". That repair was a one-off **manual emergency action under human judgment**; the plan canonized it as the permanent automated path without re-examining scope (normalization of deviance). Planning-review, implementation, and the first review pass all validated the implementation *against the plan* — none validated the plan's mechanism *against the schema contract*. Consequence already live: **the E15-29 repair `create_all`-ed 4 tables onto prod, so prod today carries RLS-less tenant-data tables** (`assignment_decisions`, `clustering_job_reports`) independent of this branch.

## Smell classification (literature grounding)

From `literature/extracted/refactoring/distilled/`:

| Heuristic | Source | Application here |
| --- | --- | --- |
| DRY = one canonical representation of each decision; duplication = "insidious developmental coupling" | Modern Software Engineering, Ch 13 "Managing Coupling" | Schema decided in 3 places; every table addition must be re-entered 3× or silently diverges |
| Shotgun Surgery — "every change touches many different classes" | Refactoring (Fowler/Beck), Ch 3 | One new table ⇒ coordinated edits to migration + models + verify list; missed edit = prod drift |
| Systems of record vs derived data — matviews are derived, "technically redundant" | DDIA, Part III intro | Self-heal would materialize derived data (`mv_*`) as a fake system of record |
| "Data outlives code"; schema is versioned, migration-evolved | DDIA, Ch 4 "Through databases" | Boot-time `create_all` treats schema as recreatable rather than evolved |
| Agile databases: version table checked at startup, **automated migrations** as the legit change path | Release It!, §18.2 | Verify is a degenerate version check with no legitimate migration path behind it → crash-loop |
| Fail Fast is correct only when the fast path can reach a good state | Release It!, §5.5 | Fail-closed verify + impotent self-heal = designed crash-loop |
| "Nothing is as permanent as a temporary fix"; design failure modes deliberately | Release It!, Ch 7 + Intro | Emergency manual repair promoted to designed mechanism; produced an *undesigned* silent failure mode (RLS-less tables) |
| Monitoring "represents the system's view of itself" — can't detect what it doesn't measure | Release It!, §17.5 | Verify checks table *names*; the load-bearing invariant (RLS enforced) is unmeasured → green while exposed |
| Measuring the wrong thing gives false confidence (assertion-free tests) | Modern Software Engineering, Ch 8 | Table-count verify ≈ coverage-without-assertions |
| Introduce Assertion — enforce implicit invariants at the assignment point | Refactoring, Ch 10 | "Every tenant_id table has RLS" is implicit and asserted nowhere at creation time |
| Incidental coupling — "change together for no good reason" | MSE Ch 13, Nygard model Table 13.1 | The three sources are incidentally coupled with no mechanical linkage |

Classification: **architectural smell (divergent sources of truth + verification asymmetry), not an implementation defect.** It predates E15-33; E15-33 merely automated it.

## Why this must NOT be fixed inside E15-33's auto-fix loop

1. **Security surface**: any fix touches RLS policy application — wrong fix = silent cross-tenant exposure. Needs deliberate review, not an auto-fix iteration.
2. **Unverifiable locally**: RLS, matviews, advisory locks are Postgres-only; the branch test substrate is sqlite. A "fix" here would ship with its critical paths untested (BR2-10 already flags this for the advisory lock).
3. **Migration blast radius**: the correct fix restructures the 1,400-line `001_identity_schema.py` into idempotent, re-appliable DDL units — a refactor of the schema's source of truth, not a script patch.
4. **Prod remediation is entangled**: prod already has RLS-less tenant tables from E15-29. The fix must include a remediation + verification step against live prod, which is deploy-gated operator work.

## Recommended plan shape (dedicated task, suggested `E15-34` or `E21-x`)

1. **Single source of truth**: refactor `001_identity_schema.py` DDL into idempotent helpers (`ensure_table(x)`, `ensure_rls(table)`, `ensure_matview()`, `ensure_refresh_queue()`) that both `upgrade()` and the boot self-heal call — the self-heal *delegates to the migration's own DDL* instead of re-deriving schema from the ORM. (Also retires PA-05, the deferred "convergence second-source-of-truth" finding.)
2. **Consistency assertions in CI** (cheap, immediate):
   - `set(EXPECTED_SCHEMA_TABLES) ⊆ tables the heal can create`
   - every `Base.metadata` table with `tenant_id` ∈ `TENANT_TABLES` ∪ explicit allowlist (`api_keys`, `mv_*` with documented rationale)
   - every runtime-written ORM table has migration DDL coverage
3. **Verify upgraded to match the invariant**: assert RLS enabled+forced on tenant tables and `relkind='m'` for the matview — fail-closed on policy drift, not just name drift.
4. **Adopt observability tables into the migration** (+ RLS) — they are live tenant-data tables; today they have no creation path at all besides `create_all`.
5. **Prod remediation**: audited one-time application of RLS to the E15-29-created tables, verified via the upgraded verify against live prod.
6. **Test substrate**: PG-backed tests (dockerized postgres) for RLS/matview/advisory-lock paths; sqlite stays for pure-table logic.

### Interim disposition of `feature/e15-33`

- Slices 2 (packaging guard), 3 (compose/unit convergence), 4 (boot smoke) are **independent of the smell and sound** — mergeable on their own merits once their open BR2 findings (03/05/06/07/09/11, all bounded test/robustness gaps) are dispositioned.
- Slice 1 (self-heal) should **not reach prod as-is**: either unwire `python -m scripts.sync_identity_schema` from the Dockerfile CMD (reverting to verify-only boot, the pre-task safe state) or hold the branch until the dedicated task lands. Unwiring is the recommended cheap interim — it keeps the tests/scaffold on the branch while removing the hazard.
- **Operational follow-up now** (independent of any merge): audit live prod for the E15-29-created RLS-less tables and decide interim mitigation (single-tenant demo lowers urgency, does not eliminate it).

## References

- Findings: `E15-33-INV-01` (umbrella), `E15-33-BR2-01/02/04` (defects), `E15-33-BR2-10` (untested PG path), `PA-05` (deferred second-source-of-truth) — in handoff MCP.
- Decisions: 1194/1197/1203 (E15-29 manual repair), E15-33 slice decisions 1201–1222.
- Plan surface with the flawed prescription: `docs/tasks/15.0/E15-33-prod-deploy-convergence-task-plan.md` § Slice 1.
- Literature: `literature/extracted/refactoring/distilled/{refactoring-fowler-beck,modern-software-engineering,designing-data-intensive-applications,release-it}.md`.
