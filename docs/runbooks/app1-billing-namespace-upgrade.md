# APP-1 billing namespace upgrade (drained writers)

Existing databases still have global uniqueness on
`(provider, provider_event_id)` and `(provider, provider_customer_id)`. Those
keys collide across Polar sandbox/live and seller accounts. Fresh empty
databases take namespaced uniqueness automatically and must not set a drain
flag. This runbook does **not** apply mappings live; dry-run is the default.

Rules: [DATA-03] expand/backfill/validate, [RES-01] idempotent mapping,
[DDIA] atomic lease/fence, transaction-local `app.bypass_rls` only (never
`ALTER ROLE ... BYPASSRLS`). Usage-schema writer drain
(`ACX_USAGE_SCHEMA_WRITERS_DRAINED` / `app.usage_schema_writers_drained`) is
unchanged.

## What changes

| Surface | Before (C0) | After N1 |
| --- | --- | --- |
| Inbox unique | `(provider, provider_event_id)` | `(provider, environment, seller_account, provider_event_id)` |
| Projection customer unique | `(provider, provider_customer_id)` | `(provider, environment, seller_account, provider_customer_id)` |
| NULL `environment` / `seller_account` | Additive, non-authoritative | Unmapped / quarantined. Never inferred as sandbox/live |
| Known-item leases | n/a | `billing_known_item_lease` PK `(provider, environment, seller_account, kind, remote_id)` |

Writers persist the **configured** Polar environment and seller account. Invoice
and webhook payload metadata cannot choose seller or environment. Bound
repository methods refuse NULL-legacy as current. Tenant projection rows that
already belong to another namespace fail closed before a paid grant.

## Exact existing-DB upgrade

1. Stop API and worker writers that insert inbox/projection rows (scale to 0 /
   drain in-flight Polar webhooks). New namespaced writers must not start yet.
2. Inspect live NULL-namespace rows (read-only):

   ```bash
   cd apps/prototype-description-service
   python scripts/billing_namespace_migrate.py
   ```

   Default is dry-run and rolls back. Unmapped rows stay unavailable for paid
   authority.
3. Build a mapping file of **verified row IDs** with operator evidence. Do not
   guess. `environment` must be the exact string `sandbox` or `live`.
   `seller_account` must be a nonempty string of at most 128 characters. JSON
   `null`, numbers, objects, booleans, and empty/whitespace values are
   rejected before any database write (they are not stringified to `None`).
   Do not map a projection onto a different `tenant_id`. Do not merge two
   customers that collide in the same namespace.

   ```json
   {
     "operator_identity": "ops-oncall",
     "evidence": "Polar org_xxx sandbox dashboard 2026-09-22; row IDs from dry-run",
     "inbox": [
       {"id": "11111111-1111-1111-1111-111111111111", "environment": "sandbox", "seller_account": "org_xxx"}
     ],
     "projection": [
       {"id": "22222222-2222-2222-2222-222222222222", "environment": "sandbox", "seller_account": "org_xxx"}
     ]
   }
   ```

   Dry-run the mapping (still no write). With `--mapping`, dry-run runs the
   **same** row existence, namespace, tenant, and collision checks as apply,
   then rolls back. A missing row, tenant mismatch, or collision fails closed
   with no mutation. Mapped counts are entries that passed those checks, not
   a raw list length.

   ```bash
   python scripts/billing_namespace_migrate.py --mapping mapping.json
   ```

4. Apply only after review, with writers still drained/stopped, an explicit
   `--apply` flag, and the same audited mapping file. The apply transaction
   uses `SET LOCAL app.bypass_rls = 'true'` and restores the prior GUC.
   Every mapping entry is validated before the first `UPDATE`. Collisions
   fail closed (SQL / explicit error) and the transaction rolls back; there
   are no durable partial writes. Re-running a successful mapping is
   idempotent for rows already in the target namespace. Partial NULL unique
   may coexist with remaining unmapped rows.

   ```bash
   python scripts/billing_namespace_migrate.py --mapping mapping.json --apply
   ```

5. Drop legacy global uniques only after writers are drained and remaining
   unmapped rows are accepted as quarantined:

   ```bash
   cd /opt/acx-backend/prod
   docker compose -f docker-compose.env.yml -f docker-compose.admin.yml run --rm -e ACX_BILLING_NAMESPACE_WRITERS_DRAINED=1 api python -m scripts.sync_identity_schema
   ```

   The api container runs the heal from the backend image. The environment
   flag is read by the migration during the heal transaction; a GUC set in a
   separate SQL session does not reach it. Heal never `ALTER ROLE ...
   BYPASSRLS`. Rolling back the heal transaction restores the old unique if
   the drain step is aborted.

6. Start only upgraded writers. Bound `BillingRepository(session,
   environment=..., seller_account=...)` is required for paid authority.

## Known-item leases (R1)

`claim_reconcile_item` is a short transaction. **Caller COMMIT before any
provider GET.** `lock_reconcile_item` / projection / entitlement /
`mark_webhook_processed` / `finish_reconcile_item` share one later database
transaction. Vendor I/O is outside the lock. Stale or stolen fences cannot
mark processed, quarantine, or apply paid state. On failure, rollback before a
bounded failure mark.

## Rollback

- Mapping apply: abort the transaction (the command rolls back on error).
  Already-committed mappings are reversed only by an explicit inverse mapping
  of the same row IDs; do not guess.
- Unique-constraint drop: roll back the heal transaction, or re-add
  `uq_billing_webhook_inbox_provider_event` /
  `uq_billing_subscription_projection_provider_customer` only if no
  namespaced duplicates exist. Do not re-introduce a global unique after
  two sellers share an event or customer id.
- Schema downgrade of `billing_known_item_lease` follows
  `DOWNGRADE_TABLE_ORDER` in `001_identity_schema.py`.

## Verify

- Role is `NOSUPERUSER` / `NOBYPASSRLS`.
- `billing_known_item_lease` has ENABLE+FORCE RLS; policy body is only
  `app.bypass_rls`. Tenant sessions see zero lease rows.
- Two seller/environment pairs can store the same Polar event id and customer
  id without cross-projection.
- NULL-legacy inbox/projection rows are not returned by bound readers.
- Duplicate delivery in one namespace inserts once.
- Expired lease can be stolen; the old owner cannot lock or finish.
