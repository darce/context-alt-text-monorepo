# APP-1 billing reconciliation (R1 worker)

Operator runbook for the bounded billing recovery worker. This is not Polar
sandbox evidence and does not claim N1 production integration until the
coordinator records that receipt.

Rules used: DDIA ch7/8/11 (lease, fence, commit-before-GET); Release It ch4/5
(timeouts, bulkheads); RES-01/02/05; DATA-03; PERF-11/13; GRPH-09/31.

## What it does

`python -m scripts.billing_reconcile --once` drains, in one bounded cycle:

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
those values when N1 accepts them. Until N1 lands, missing
`claim_reconcile_item` / `lock_reconcile_item` / `finish_reconcile_item` /
`list_known_projections` **fail closed**. Do not run unfenced.

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

```bash
python -m scripts.billing_reconcile_retry \
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

R1 fakes the frozen N1 item-lease seam in tests. Production verification of
namespace-bound inbox/projection writers is a coordinator receipt after N1
lands. Until then, an old repository without those methods is unsupported.
