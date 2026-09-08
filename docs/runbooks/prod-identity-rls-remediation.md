# Runbook: Prod Identity-Schema RLS Remediation (E15-34 Slice 6)

**Why**: the E15-29 emergency repair (`create_all`, decisions 1194/1197) created
`assignment_decisions` and `clustering_job_reports` on prod **without RLS**, and
may have left other drift. E15-34 made the migration the single DDL truth: the
boot heal (`python -m scripts.sync_identity_schema`) now applies missing
tables **and** missing RLS/policies, and the boot verifier fails closed on
policy drift. This runbook remediates the live prod database once, with
before/after audit evidence.

**Prereq**: an image containing E15-34 (heal + upgraded verifier) is deployed.
Verify before §2 — the pre-E15-34 image ships the old `create_all` heal, which
is exactly the mechanism that caused this exposure and must NOT be run:

```bash
cd /opt/acx-backend/prod
docker compose -f docker-compose.env.yml -f docker-compose.admin.yml \
  run --rm --no-deps api sh -c \
  "grep -q 'heal' /app/scripts/sync_identity_schema.py && echo E15-34-HEAL-PRESENT || echo OLD-IMAGE-STOP"
```

`OLD-IMAGE-STOP` → deploy the E15-34 image first
(`CONFIRM=PROMOTE scripts/deploy/recognition-service.sh deploy prod`); the boot
path already runs heal+verify, then use this runbook for the audit evidence.

## 1. Pre-audit (read-only)

Connect as the app role (or superuser) to the prod identity DB and run:

```sql
SELECT t.relname,
       c.relrowsecurity  AS rls_enabled,      -- NULL row = table MISSING
       c.relforcerowsecurity AS rls_forced,
       (SELECT count(*) FROM pg_policies p
         WHERE p.schemaname = 'public' AND p.tablename = t.relname) AS policies
FROM unnest(ARRAY[
    'media_identities','identity_clusters','identity_members','identity_scan_jobs',
    'identity_scan_job_items','identity_cluster_representatives','identity_clustering_jobs',
    'identity_suggestions','cluster_merge_suggestions','name_suggestions',
    'identity_cluster_blocks','identity_constraints','recognition_runs','recognition_events',
    'clustering_feedback','audit_events','curation_replay_records','export_jobs',
    'image_descriptions','clustering_job_reports','assignment_decisions']) AS t(relname)
LEFT JOIN pg_class c
  ON c.relname = t.relname
 AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
ORDER BY t.relname;
```

The `LEFT JOIN` guarantees **21 rows always**: a row with NULL `rls_enabled`
means the table itself is missing (do not read absence as success).

Save the output. Expected pre-state: `assignment_decisions` and
`clustering_job_reports` show `rls_enabled = f` (or are missing policies);
other rows should already be `t/t/1`.

## 2. Apply the heal (one-shot, idempotent)

On the prod VM, in the api container context (same env as boot):

```bash
cd /opt/acx-backend/prod
docker compose -f docker-compose.env.yml -f docker-compose.admin.yml \
  run --rm api python -m scripts.sync_identity_schema
```

The heal takes the boot advisory lock, creates any missing tables, enables +
forces RLS, and (re)creates every `tenant_isolation_*` policy. Re-running is a
no-op. (Equivalent: any restart through the normal deploy path — the CMD runs
the same module — but the one-shot keeps the evidence isolated.)

## 3. Post-audit + verify

Re-run the §1 SQL and save the output: every listed table must show
`rls_enabled = t, rls_forced = t, policies >= 1`. Then run the fail-closed
verifier:

```bash
cd /opt/acx-backend/prod
docker compose -f docker-compose.env.yml -f docker-compose.admin.yml \
  run --rm api python -m scripts.verify_identity_schema; echo "EXIT=$?"
```

Expected: `identity schema verified: ...` and `EXIT=0`. Exit `1` means
heal-repairable drift remains (re-run §2 and re-audit); exit `2` names an
operator-required condition (revision mismatch or a non-matview relation named
`mv_identity_cluster_centroids` — see below).

## 4. Record evidence

Record the before/after audit output and the verify exit code as an MCP
`test_result` on task `E15-34` (command: this runbook's §2–3; result: pasted
audit rows), then disposition findings E15-33-BR2-02 / INV-01 accordingly.

## 5. Rollback note

RLS enablement is non-destructive (no rows are modified). If the application
misbehaves post-remediation (e.g. a code path reads without tenant context),
the statements below revert a single table while the fix is investigated —
**caveat**: the boot CMD runs the heal *before* the verifier, so ANY container
restart re-enables RLS and recreates the policy — the revert does not survive
restarts and the verifier will pass again after the heal re-runs. A revert is
therefore only stable while the containers stay up; for a longer investigation
window, stop the affected read path instead of relying on the revert:

```sql
ALTER TABLE <table> NO FORCE ROW LEVEL SECURITY;
ALTER TABLE <table> DISABLE ROW LEVEL SECURITY;
-- optional, only if the policy itself is implicated:
DROP POLICY tenant_isolation_<table> ON <table>;
```

## Column drift (MAINT-TPR-01)

**Symptom**: a table and its alembic revision look healthy, yet every ORM path
selecting one table 500s — e.g. prod `whoami` and `manage_api_keys tenant list`
fail because the running image's ORM selects `tenants.naming_agreement_enabled`
but the live column is absent. Root cause: `_ensure_table` no-ops on an already
existing table, so an expand-first column added to the model after the table was
first created never lands (PA-03; the stamped-alembic upgrade is a no-op).

**Fix**: the heal (`sync_identity_schema` → migration `heal()` → `_ensure_columns`)
now adds any missing ORM-declared column additively (`ADD COLUMN`, server default
from the model), and the verifier fails closed (exit `1`) naming
`column_gaps: <table> missing <cols>`. Remediation is identical to §2–3 — run the
heal, then verify:

```bash
cd /opt/acx-backend/prod
docker compose -f docker-compose.env.yml -f docker-compose.admin.yml \
  run --rm api python -m scripts.sync_identity_schema
docker compose -f docker-compose.env.yml -f docker-compose.admin.yml \
  run --rm api python -m scripts.verify_identity_schema; echo "EXIT=$?"
```

Any restart through the deploy path also converges it (the boot CMD runs the same
heal before the verifier). Confirm recovery with `curl -s .../recognition/tenant/whoami`
(HTTP 200, key-canonical `tenant_id`) and `manage_api_keys tenant list`. Additive
only: a missing NOT NULL column with no server default, or a missing primary key,
raises for operator remediation instead of guessing a backfill (non-additive drift
→ reset per greenfield policy, `scripts/reset_dev_db.sh` locally / a fresh prod DB).

## Known operator-required conditions

- **Matview impostor** (`verify` exit 2 naming `matview_relkind`): a plain
  table occupies `mv_identity_cluster_centroids`. Confirm it holds no needed
  data, `DROP TABLE mv_identity_cluster_centroids;`, re-run §2 (heal recreates
  the real matview), then `REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids;`.
- **Revision mismatch** (`verify` exit 2 with `actual_revision`): the DB is not
  stamped at `001_identity_schema` — investigate before healing; do not stamp
  blindly.
- **Table vector typmod gap** (`verify` exit 2 naming `media_identities.embedding`
  or `identity_cluster_representatives.embedding`): a `vector(N)` column does not
  match `PGVECTOR_DIM`. Do **not** paste
  `ALTER ... TYPE vector(N) USING embedding::vector(N)` — a vector-to-vector(N)
  cast cannot change dimension and Postgres rejects it. Re-embed the rows (or
  NULL them), then `ALTER TABLE <t> ALTER COLUMN embedding TYPE vector(N);`,
  then re-run §2. Derived matview centroid drift is heal-rebuildable; table
  embeddings are not.
