# APP-1 billing reconciliation (R1 worker)

Operator runbook for the bounded billing recovery worker. This is not Polar
sandbox evidence. N1 item-lease methods are landed; the worker constructs a
namespaced `BillingRepository` and PostgreSQL tests witness claim / lock /
finish against that production seam.

Rules used: DDIA ch7/8/11 (lease, fence, commit-before-GET); Release It ch4/5
(timeouts, bulkheads); RES-01/02/05; DATA-03; PERF-11/13; GRPH-09/31.

## What it does

From the service deployment directory (for example, `/opt/acx-backend/prod`),
run the worker in the API container, following the existing compose pattern:

```sh
docker compose -f docker-compose.env.yml exec -T api python -m scripts.billing_reconcile --once
```

The worker drains, in one bounded cycle:

1. Known webhook inbox rows (N1 `claim` / commit / GET / `lock` / write / `finish`).
2. Known projections in the configured seller namespace (same N1 fence).
3. Remote subscription orphans via C0 `kind=subscriptions` cursor lease.
4. Ambiguous / `provider_requested` checkouts older than the provider timeout.

`--dry-run` reports without writes. `--loop --max-cycles N` is the bounded poll.
Exit `0` is healthy progress or an exhausted empty verified page. Exit `1` is
stall, timeout, or zero verified page progress. Exit `2` is configuration.

## Runtime wiring

The worker constructs Polar from configured `environment` and
`POLAR_ORGANIZATION_ID` (`seller_account`). It never derives namespace from a
webhook, email, or request tenant. `BillingRepository` is constructed with
those validated values. Missing `claim_reconcile_item` / `lock_reconcile_item` /
`finish_reconcile_item` / `list_known_projections` **fail closed**. Do not run
unfenced.

Required:

- `BILLING_RECONCILE_PROVIDER_TIMEOUT_SECONDS` (contract default 8s)
- `POLAR_WEBHOOK_SECRET`, `POLAR_ACCESS_TOKEN`, `POLAR_PRODUCT_IDS`
- `POLAR_ORGANIZATION_ID`
- `POLAR_ENVIRONMENT` (`sandbox` or `live`; must match API host)

Bounds: page limit 50, max 20 pages per `--once`, lease 30s. Vendor GET never
runs in an open cursor transaction. Heartbeat/lock is taken again in the same
DB transaction as projection / entitlement / item complete.

## Orphans and quarantine

Good remote items need a local tenant mapping in the same environment/seller.
NULL legacy projection namespace is not current. Email is not a tenant. One
bad observation is quarantined; the rest of the page continues. Item
idempotency uses provider event position, not “this subscription id was seen
forever”. After a cycle exhausts, the next scheduled scan restarts at the
first page. The opaque cursor is persisted between bounded runs.

Ambiguous checkouts are recovered with `retrieve_checkout` only. Missing
`provider_checkout_id` is quarantined for manual resolution. A success URL or
redirect is not paid. Paid requires authoritative `retrieve_state` then
`TenantEntitlementService.apply_billing_state`. API keys are unchanged. Beta
is not debt recovery.

## Audited retry

From the same service deployment directory, run the retry worker in the API
container:

```bash
docker compose -f docker-compose.env.yml exec -T api python -m scripts.billing_reconcile_retry \
  --remote-id sub-x \
  --environment sandbox \
  --seller-account "$POLAR_ORGANIZATION_ID" \
  --operator-identity ops@example.test \
  --operator-reason "seller confirmed mapping"
```

Default is dry-run. `--apply` records `retry_pending` under a C0 lease. It
cannot grant paid and must not print tokens.

## Failure and stall

Timeout or zero verified page progress makes `--once` non-zero. Acquiring or
renewing a lease is not progress. A stale fence cannot mark processed,
quarantine, or apply paid state; rollback first. Poison inbox rows isolate;
they do not abort the batch.

## N1 status

N1 `BillingRepository` item-lease methods are landed. The R1 worker runtime
constructs the repository with configured `environment` / `seller_account`.
Unit tests still use local seam doubles; PostgreSQL C0 tests use the real
namespaced repository and worker. Polar live/sandbox provider evidence is
still out of scope. An old repository without those methods remains
unsupported.
