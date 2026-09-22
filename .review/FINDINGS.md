# APP-1 R1 reconciliation review

Verdict: changes_requested

GROK_REVIEW_FINDINGS_JSON
[
  {
    "finding_id": "APP1-RECONCILE-RV01",
    "severity": "medium",
    "category": "bounded_work",
    "file_path": "apps/prototype-description-service/scripts/billing_reconcile.py",
    "line_start": 1087,
    "line_end": 1124,
    "description": "Known-projection reconciliation fetches pages of 50 but loops until the repository is empty, with no per-run page, item, or total-time bound. A large configured namespace can therefore make one --once invocation perform unbounded provider GETs and delay the other recovery phases.",
    "fix": "Apply the same bounded page/time policy used by orphan recovery to known projections, with a durable continuation cursor or an explicit non-healthy continuation result when the bound is reached."
  },
  {
    "finding_id": "APP1-RECONCILE-RV02",
    "severity": "medium",
    "category": "item_isolation",
    "file_path": "apps/prototype-description-service/scripts/billing_reconcile.py",
    "line_start": 1210,
    "line_end": 1219,
    "description": "The page loop calls remote_id_from_state before entering a per-item fenced handler. A malformed enumerated BillingState with neither subscription nor customer id raises ValueError into the page-level handler, records a page failure, and stops processing later valid items instead of quarantining only the bad item.",
    "fix": "Turn malformed items into a durable EnumerationObservation/quarantine result inside the item boundary, append its id only after that outcome is committed, and continue with the remaining page items."
  },
  {
    "finding_id": "APP1-RECONCILE-RV03",
    "severity": "medium",
    "category": "failure_signaling",
    "file_path": "apps/prototype-description-service/scripts/billing_reconcile.py",
    "line_start": 1174,
    "line_end": 1181,
    "description": "Known-projection failures are caught, logged, and returned as False without incrementing unresolved_failures; ReconcileReport.exit_code only considers stalled or unresolved_failures. Thus a failed provider refresh can return exit 0 when another phase advances (or when recovery is not configured), silently leaving stale billing state. The analogous checkout/page catches only increment failed and have the same masking risk.",
    "fix": "Propagate every failed recovery/projection/checkout phase into the unresolved failure set (or make failed affect exit_code) while preserving durable progress from other items."
  },
  {
    "finding_id": "APP1-RECONCILE-RV04",
    "severity": "medium",
    "category": "ambiguous_checkout_progress",
    "file_path": "apps/prototype-description-service/scripts/billing_reconcile.py",
    "line_start": 1418,
    "line_end": 1429,
    "description": "Ambiguous checkout selection is limited to 50 rows, but the recovery cursor is always advanced as exhausted with no attempt cursor. An open/provider_requested checkout remains stale because _recover_checkout_attempt does not change its attempt status; if the first 50 remain open, every bounded run selects the same 50 and later stale attempts are starved indefinitely.",
    "fix": "Persist and use a stable attempt cursor (updated_at,id), or record a durable retry/backoff position/status so advancing past one bounded page cannot repeatedly select the same unresolved rows."
  },
  {
    "finding_id": "APP1-RECONCILE-RV05",
    "severity": "high",
    "category": "tenant_data_integrity",
    "file_path": "apps/prototype-description-service/scripts/billing_reconcile.py",
    "line_start": 1149,
    "line_end": 1170,
    "description": "The known-projection path requests state for the projection customer but never verifies that the returned provider_customer_id matches that context before upsert and entitlement application. _normalize_state validates tenant_id for typed state but not customer identity, unlike the inbox path's explicit check; a mismatched provider response can rebind a tenant projection and apply billing to the wrong customer.",
    "fix": "Require normalized returned customer and subscription identifiers to match the requested projection context before lock/write/apply, and fail or quarantine the item on mismatch."
  },
  {
    "finding_id": "APP1-RECONCILE-RV06",
    "severity": "medium",
    "category": "retry_cli_runtime",
    "file_path": "apps/prototype-description-service/scripts/billing_reconcile_retry.py",
    "line_start": 62,
    "line_end": 71,
    "description": "The real retry CLI builds the full billing runtime with provider=None even though it only needs the recovery repository and explicit namespace. This requires Polar webhook/access/product/organization configuration and creates a provider HTTP client before either dry-run or audited retry, so a DB-only operator retry fails closed on unrelated provider secrets/configuration.",
    "fix": "Construct a recovery-only runtime/repository for this command; validate the supplied namespace but do not load provider credentials or instantiate network transport for dry-run or retry bookkeeping."
  },
  {
    "finding_id": "APP1-RECONCILE-RV07",
    "severity": "medium",
    "category": "transaction_ordering",
    "file_path": "apps/prototype-description-service/scripts/billing_reconcile.py",
    "line_start": 1527,
    "line_end": 1544,
    "description": "When an ambiguous checkout's paid payload omits customer_id, the worker opens a repository transaction in _get_projection to find the customer and then calls _retrieve_state without committing or rolling back that read transaction. That provider GET therefore runs with an open database transaction after the lease commit, violating the no-network-under-transaction ordering contract.",
    "fix": "Finish the lookup transaction before retrieve_state (or carry only a detached snapshot), then open a fresh transaction for the fenced projection/entitlement write."
  },
  {
    "finding_id": "APP1-RECONCILE-RV08",
    "severity": "medium",
    "category": "idempotency",
    "file_path": "apps/prototype-description-service/scripts/billing_reconcile.py",
    "line_start": 1302,
    "line_end": 1324,
    "description": "Orphan application substitutes the local wall clock for a missing provider event_position when building the event id and projection position. A repeated full scan of an item without a verified provider position therefore looks like a new event on every run and can repeatedly update the projection and entitlement instead of being safely deduplicated or quarantined.",
    "fix": "Require a verified provider event position for an applicable orphan; quarantine malformed/missing-position items rather than synthesizing now."
  }
]
