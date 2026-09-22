# APP-1 offline cross-slice validation receipt

- Date: 2026-09-22
- Current SHA (tested snapshot): `c1f0982d4f1d8a0f249ecc555a75773ffa85cf0d`
- Import origin (existing lane interpreter): `/home/gate/grok-sandbox/.venv-lane-feature-app-1-offline-cross-slice-valida-2206d2aa/bin/python`; `recognition` loaded from `/home/gate/grok-sandbox/feature-app-1-offline-cross-slice-valida-2206d2aa/apps/prototype-description-service/recognition/__init__.py`.

## Exact TEST_CMD

```sh
IDENTITY_PG_REQUIRED=1 uv run --directory apps/prototype-description-service --extra dev python -m pytest recognition/tests/unit/test_app1_billing_reconcile.py recognition/tests/unit/test_app1_billing_reconcile_recovery.py recognition/tests/integration/test_app1_billing_reconcile_postgres.py recognition/tests/integration/test_app1_billing_namespace_postgres.py recognition/tests/integration/test_app1_billing_recovery_postgres.py recognition/tests/integration/test_app1_usage_worker_postgres.py recognition/tests/integration/test_app1_usage_recovery_postgres.py -q -p no:randomly --timeout=60
```

## Result

- Exact command exit status: `2`; `0 collected`; `0 passed`; `0 failed`; `0 skipped`; `0 errors`; timing: `120 ms`.
- Exact command could not prepare the lane environment: `uv` failed to remove `.../site-packages/__editable__.prototype_description_service-0.4.2.4.pth` with `Read-only file system (os error 30)`.
- Read-only fallback command: `UV_NO_SYNC=1` plus the exact command above; exit status: `1`; timing: `1.74s` pytest time.
- Fallback collection: `61 collected`; `46 passed`; `0 failed`; `0 skipped`; `15 errors`.
- All 15 errors were setup failures with `(psycopg.OperationalError) connection is bad: no error details available`, followed by `Postgres unreachable at postgresql+psycopg://localhost:5432/postgres; start it with make postgres-start (IDENTITY_PG_REQUIRED=1: the pg suite may not skip)`.
- The 15 unexecuted PostgreSQL tests were: `test_postgres_real_repo_claim_commit_before_get_apply_finish`, `test_postgres_stale_inbox_lease_refuses_paid_and_failure_marks`, `test_postgres_stale_projection_lease_refuses_paid_state`, `test_postgres_namespace_isolation_on_real_repository`, `test_postgres_namespace_isolation_legacy_fail_closed_leases_and_rls`, `test_existing_unique_drop_requires_drain_and_rolls_back`, `test_postgres_operator_bypass_restored_after_every_path`, `test_postgres_same_session_returning_lease_is_fresh`, `test_postgres_recovery_fencing_isolation_and_page_idempotency`, `test_postgres_acquire_rollback_releases_cursor`, `test_postgres_same_session_reacquire_returns_fresh_fence`, `test_postgres_operator_bypass_restored_and_rejects_tenant_bound`, `test_postgres_worker_usage_lifecycle`, `test_postgres_epoch_advance_old_callback_rejects_and_recovery_settles_once`, and `test_postgres_recovery_mismatch_concurrency_and_period_fail_closed`.

This receipt records the actual current run. The fallback reached the declared 61-test collection, but the required local PostgreSQL fixture was unavailable; no application cross-slice owner is implicated and no source repair or harmonizing integration conclusion is made. Provider accounts were not used and no live requests were made.
