# APP-1 C0 billing recovery contract

Date: 2026-09-22. Status: implemented C0 contract/persistence. Not R1, not live Polar, not N1 writer wiring.

This document is the handoff surface for R1 and namespace N1. It distinguishes **implemented C0** from **future consumers**. Current typed `BillingProvider` methods remain authority. `create_checkout_session` and `EnumerationPage(items, next_cursor, exhausted)` construction are preserved.

Rules used: DDIA ch7/8/11 (atomic lease txn, fencing, idempotent sinks); RES-01/RES-02 (idempotent item progress, bounded failure); DATA-03 (migration/model parity); PERF-13 (page limit 50 vs Polar 100); GRPH-09/GRPH-31 (disjoint C0 vs R1 ownership; no lock across vendor I/O).

## Implemented now (C0)

Owned paths only:

- `recognition/domain/portal_contracts.py` — types, bounds, `BillingProvider`, `BillingReconciliationRepository` protocol
- `recognition/infrastructure/billing/polar_provider.py` — typed page observations; no silent drop
- `db/models/portal_billing.py` — cursor/quarantine/progress models; nullable inbox/projection namespace columns
- `db/migrations/versions/001_identity_schema.py` — fresh+heal tables, operator-scope RLS, additive namespace columns
- `recognition/infrastructure/repositories/billing_reconciliation_repository.py` — fenced persistence
- tests listed in the C0 TEST_CMD

Not implemented here, and not to be inferred as shipped:

- `scripts/billing_reconcile.py` (R1)
- `billing_repository.py`, webhook router, entitlement service, portal composition
- known-projection / inbox item leases
- Polar sandbox or live vendor evidence
- namespace isolation on existing inbox/projection uniqueness

## Exact caller signatures

`BillingProvider` (unchanged checkout / retrieve / enumerate kwargs):

```python
async def create_checkout_session(
    self, *, tenant_id: UUID, plan_code: str, success_url: str, cancel_url: str,
    idempotency_key: str, attempt_id: UUID,
) -> CheckoutSession

async def retrieve_state(
    self, *, provider_customer_id: str, provider_subscription_id: str | None,
    request_timeout: float,
) -> BillingState

async def retrieve_checkout(
    self, *, provider_checkout_id: str, request_timeout: float,
) -> Mapping[str, object]

async def enumerate_subscriptions(
    self, *, cursor: str | None, limit: int, request_timeout: float,
) -> EnumerationPage
```

`EnumerationPage` compatible constructor: `EnumerationPage(items, next_cursor, exhausted)`. `observations` defaults to `()`. Invalid vendor items are `EnumerationObservation` values (bounded `remote_id`, reason enum, small string details). Missing vendor ids use `digest:<sha256>` — never a payload/email copy. One bad item does not abort good items. A malformed whole page (`items` not a list, invalid pagination, `len(items) > limit`) raises `PolarEnumerationError`. Tenant identity is an environment-scoped UUID from `customer.external_id` / metadata `tenant_id` only. Email and request context are not tenants.

`BillingReconciliationRepository` (R1 calls these; C0 does not run the worker):

```python
async def acquire_lease(self, key, *, owner: str, lease_ttl: timedelta, now: datetime) -> ReconciliationLease | None
async def heartbeat(self, lease, *, now: datetime, lease_ttl: timedelta) -> ReconciliationLease
async def complete_item(self, lease, *, remote_id: str, now: datetime) -> None
async def quarantine_item(self, lease, *, observation: EnumerationObservation, now: datetime) -> QuarantineRecord
async def advance_cursor(self, lease, *, next_cursor: str | None, exhausted: bool, page_remote_ids: tuple[str, ...], now: datetime) -> ReconciliationLease
async def record_page_failure(self, lease, *, failure_class: str, now: datetime) -> ReconciliationLease
async def audited_retry(self, lease, *, remote_id: str, operator_identity: str, operator_reason: str, now: datetime) -> QuarantineRecord
async def get_quarantine(self, key, remote_id: str) -> QuarantineRecord | None
```

Cursor PK: `(provider, environment, seller_account, kind)` with `kind in {subscriptions, ambiguous_checkouts}`. This is seller-wide control, **not** a fake tenant. Known-inbox / known-projection leases need a **separate typed contract** (not these kinds).

Bounds for R1: `RECONCILIATION_PAGE_LIMIT=50`, `RECONCILIATION_MAX_PAGES_PER_RUN=20`, `RECONCILIATION_DEFAULT_LEASE_SECONDS=30`, `RECONCILIATION_PROVIDER_TIMEOUT_SECONDS=8.0`.

## Transaction ownership (R1 must follow)

| Step | Transaction | Network | Fence |
| --- | --- | --- | --- |
| `acquire_lease` | Short txn; `SET LOCAL app.bypass_rls='true'` | None | Increments monotonic `fence`; conditional UPDATE. Postgres uses `FOR UPDATE SKIP LOCKED` so a concurrent in-flight acquire is not waited out. |
| **Caller COMMIT** | Ends SET LOCAL and row lock | **Required before vendor I/O** | Lease is durable only after commit |
| Vendor GET (`enumerate_subscriptions` / `retrieve_checkout` / `retrieve_state`) | **No open cursor txn** | Yes, `request_timeout` | Timeout is page failure, not success |
| `complete_item` / `quarantine_item` | New short txn, same owner+fence, `lease_until > now` | None | Reject expired/stolen/same-owner old generation |
| `advance_cursor` | Short txn after every `page_remote_ids` entry is in item progress | None | Refuses skip of unprocessed ids; repeated page is safe |
| `heartbeat` / `record_page_failure` / `audited_retry` | Short txn, fenced | None | Failure metadata is bounded; `record_page_failure` does not set `last_progress_at` |
| Rollback of uncommitted acquire | No durable lease | n/a | Another worker may acquire fence=1 |

Do not use `lease_until` as the fence. Fence is the integer generation. Same owner with an old generation is rejected. Audited retry records operator identity+reason, increments attempt, sets `retry_pending`. It cannot manufacture a tenant column or call `apply_billing_state`.

## Operator RLS

Recovery tables are `OPERATOR_SCOPE_TABLES`. ENABLE+FORCE RLS. Policy body is only `app.bypass_rls`, never `tenant_id = ...` and never `ALTER ROLE ... BYPASSRLS`. Request-tenant sessions without bypass see zero cursor/quarantine rows. Repository methods call `enable_rls_bypass` (`SET LOCAL`) per transaction.

Usage-schema writer drain (`ACX_USAGE_SCHEMA_WRITERS_DRAINED` / `app.usage_schema_writers_drained`), global counter seed, fence-token rewrite, and nullable `portal_tenant_invitation.tenant_id` are unchanged.

## N1 namespace follow-up (not live, not C0 isolation)

C0 additively publishes nullable `environment` and `seller_account` on `billing_webhook_inbox` and `billing_subscription_projection`. **No guessed backfill.** Legacy NULL remains non-authoritative. Existing uniques stay `(provider, provider_event_id)` and `(provider, provider_customer_id)`. Do not claim namespace isolation until N1.

N1 must, before live multi-account use:

1. Wire inbox and projection **writers** to persist environment+seller from the configured adapter (not request tenant, not email).
2. Wire **readers** to treat NULL as unknown / quarantine-for-mapping, never as `sandbox`/`live` inference.
3. After an audited mapping of legacy rows (or quarantine of unmappable ones), replace inbox uniqueness with `(provider, environment, seller_account, provider_event_id)` and projection customer uniqueness with the same namespace. That unique change is **not** additive while NULL duplicates can exist — do not infer it in C0.
4. Keep known-projection reads working until writers are deployed; a uniqueness flip without writer drain would break `billing_repository.py`.

Checkout uniqueness (already landed, asserted by C0 tests): two distinct contracts.

- Tenant-scoped client key: `uq_billing_checkout_attempt_client_key` includes `tenant_id`.
- Seller-wide provider key: `uq_billing_checkout_attempt_provider_key` is `(provider, environment, seller_account, idempotency_key)` and must not be loosened to include `tenant_id`.

## Future consumers

| Consumer | May start after C0 | Must not do |
| --- | --- | --- |
| **R1** worker | Consume signatures above; lease, commit, enumerate/retrieve, per-item complete/quarantine, then advance; non-zero `--once` if no `last_progress_at` / exhausted cursor | Edit C0 schema/repository; hold DB lock across Polar; invent tenant from email; grant paid from retry |
| **N1** | Namespace writer/reader + uniqueness after audited mapping | Guess legacy environment/seller; silently break known projection reads |
| **K / H / U** | Unchanged inbox/projection reads | Treat nullable namespace columns as authoritative |
| **V** | Later Polar sandbox | Treat C0 fake-provider tests as live vendor evidence |
