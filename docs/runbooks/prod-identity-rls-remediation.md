# Runbook: Prod Identity-Schema RLS Remediation (E15-34 Slice 6)

**Why**: the E15-29 emergency repair (`create_all`, decisions 1194/1197) created
`assignment_decisions` and `clustering_job_reports` on prod **without RLS**, and
may have left other drift. E15-34 made the migration the single DDL truth: the
boot heal (`python -m scripts.sync_identity_schema`) now applies missing
tables **and** missing RLS/policies, and the boot verifier fails closed on
policy drift. This runbook remediates the live prod database once, with
before/after audit evidence.

**Prereq**: an image containing E15-34 (heal + upgraded verifier) is deployed,
or you run the commands from a checkout at ≥ this runbook's commit on the VM.

## 1. Pre-audit (read-only)

Connect as the app role (or superuser) to the prod identity DB and run:

```sql
SELECT c.relname,
       c.relrowsecurity  AS rls_enabled,
       c.relforcerowsecurity AS rls_forced,
       (SELECT count(*) FROM pg_policies p
         WHERE p.schemaname = n.nspname AND p.tablename = c.relname) AS policies
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname = ANY(ARRAY[
    'media_identities','identity_clusters','identity_members','identity_scan_jobs',
    'identity_scan_job_items','identity_cluster_representatives','identity_clustering_jobs',
    'identity_suggestions','cluster_merge_suggestions','name_suggestions',
    'identity_cluster_blocks','identity_constraints','recognition_runs','recognition_events',
    'clustering_feedback','audit_events','curation_replay_records','export_jobs',
    'image_descriptions','clustering_job_reports','assignment_decisions'])
ORDER BY c.relname;
```

Save the output. Expected pre-state: `assignment_decisions` and
`clustering_job_reports` show `rls_enabled = f` (or are missing policies);
other rows should already be `t/t/1`.

## 2. Apply the heal (one-shot, idempotent)

On the prod VM, in the api container context (same env as boot):

```bash
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
expect the boot verifier to fail closed (exit 1) while any of these are in
effect, so pin the deploy or set the investigation window accordingly:

```sql
ALTER TABLE <table> NO FORCE ROW LEVEL SECURITY;
ALTER TABLE <table> DISABLE ROW LEVEL SECURITY;
-- optional, only if the policy itself is implicated:
DROP POLICY tenant_isolation_<table> ON <table>;
```

## Known operator-required conditions

- **Matview impostor** (`verify` exit 2 naming `matview_relkind`): a plain
  table occupies `mv_identity_cluster_centroids`. Confirm it holds no needed
  data, `DROP TABLE mv_identity_cluster_centroids;`, re-run §2 (heal recreates
  the real matview), then `REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids;`.
- **Revision mismatch** (`verify` exit 2 with `actual_revision`): the DB is not
  stamped at `001_identity_schema` — investigate before healing; do not stamp
  blindly.
