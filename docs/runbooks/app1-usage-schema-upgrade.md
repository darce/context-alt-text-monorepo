# APP-1 usage schema upgrade (drained writers)

Existing databases cannot take the usage identity `NOT NULL` contract or
global-counter enforcement while old API/worker writers are still running.
Those writers omit `operation_id` / `request_fingerprint` / `fence_token` and
do not update `usage_admission_global_state`. Adding nullable or defaulted
columns would look compatible while old writers bypass global caps
(`[DATA-03]`, `[RES-05]`). Fresh empty databases upgrade automatically and
must not set the drain flag.

## Fence and legacy markers (schema/runtime alignment)

Migration backfills missing identity fields only. It does **not** invent
modern operation/fingerprint values.

| Stored shape | Meaning | Migration rewrite under drain |
| --- | --- | --- |
| missing/blank `operation_id` or `request_fingerprint` | pre-identity legacy row | `idempotency_key` |
| missing/blank `fence_token`, or `fence_token` equals reservation UUID | legacy fence provenance | `{epoch}:legacy:{reservation UUID}` |
| unprefixed UUID not equal to reservation id | modern token from an earlier writer | `{epoch}:{uuid}` (invalidates the old token deliberately) |
| `{positive-epoch}:{uuid}` | modern epoch-prefixed token | preserved exactly |
| `{positive-epoch}:legacy:{uuid}` | explicit migrated legacy token | preserved exactly |
| any other marker/epoch | malformed | fail closed; operator must repair the row |

`epoch` is the locked `usage_admission_global_state.fence_epoch` (`>= 1`).
Runtime must check the stored epoch against that locked global epoch on every
settlement path, plus the exact provided token when required. Blank-identity
compatibility is allowed only when the stored token has the explicit
`:legacy:` marker **and** the row still matches the legacy tuple
(`operation_id` / `request_fingerprint` = `idempotency_key`). Do not treat a
modern row as legacy just because `operation_id` equals `idempotency_key`.

## Exact existing-DB upgrade

1. Stop old API and worker writers (scale to 0 / drain in-flight reservation
   INSERTs). New writers must not start yet.
2. Inspect live `usage_reservation` rows:
   - `RESERVED` rows with unknown `queue_bytes` (column missing or NULL) are
     fail-closed. Drain/release them or set `queue_bytes` explicitly. The
     migration will not invent per-row usage receipts.
   - Chargeable (`reserved` + `committed`) current-period `cost_units` and
     `RESERVED` inflight/queue counters are aggregated under the migration
     lock into `usage_admission_global_state`. Config limits, `stop_requested`,
     `fence_epoch`, `config_version`, and period bounds are preserved.
3. Inspect `billing_checkout_attempt` duplicates of
   `(provider, environment, seller_account, idempotency_key)`. Spec 5.1 is
   seller-wide (no `tenant_id`). Duplicate live rows fail with SQLSTATE 23505
   and an operator-readable error. Do **not** delete or merge rows silently.
4. Run the heal with the drained-writer contract:

   ```bash
   cd /opt/acx-backend/prod
   docker compose -f docker-compose.env.yml -f docker-compose.admin.yml \
     run --rm -e ACX_USAGE_SCHEMA_WRITERS_DRAINED=1 api python -m scripts.sync_identity_schema
   ```

   Equivalent session GUC (already inside the heal transaction):

   ```sql
   SELECT set_config('app.usage_schema_writers_drained', 'true', true);
   ```

   The heal uses `SET LOCAL app.bypass_rls = 'true'` only inside the migration
   transaction, then restores the prior GUC. It never `ALTER ROLE ... BYPASSRLS`.
5. Start only upgraded writers. Old pods that omit the identity columns will
   fail every reservation `INSERT` after `NOT NULL` contraction; that is the
   intended fail-closed contract.

Re-running the heal on an already-contracted schema is a no-op for DDL and
re-aggregates global counters from current-period rows. Token expansion of
already-stored unprefixed UUIDs happens only when the drain flag is set.

## Portal invitations

`portal_tenant_invitation.tenant_id` may be NULL for a pending unbound
invitation. Existing non-NULL FK rows stay valid. Claim-service tenant minting
is not part of this upgrade.
