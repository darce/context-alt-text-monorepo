# APP-1 offline cross-slice validation receipt

- Date: 2026-09-22
- Current SHA: `c1f0982d4f1d8a0f249ecc555a75773ffa85cf0d`
- Import origin (existing lane interpreter): `/home/gate/grok-sandbox/.venv-lane-feature-app-1-offline-cross-slice-valida-2206d2aa/bin/python`; `recognition` loaded from `/home/gate/grok-sandbox/feature-app-1-offline-cross-slice-valida-2206d2aa/apps/prototype-description-service/recognition/__init__.py`.

## Exact TEST_CMD

```sh
IDENTITY_PG_REQUIRED=1 uv run --directory apps/prototype-description-service --extra dev python -m pytest recognition/tests/unit/test_app1_billing_reconcile.py recognition/tests/unit/test_app1_billing_reconcile_recovery.py recognition/tests/integration/test_app1_billing_reconcile_postgres.py recognition/tests/integration/test_app1_billing_namespace_postgres.py recognition/tests/integration/test_app1_billing_recovery_postgres.py recognition/tests/integration/test_app1_usage_worker_postgres.py recognition/tests/integration/test_app1_usage_recovery_postgres.py -q -p no:randomly --timeout=60
```

## Result

- Exit status: `2`
- Timing: `120 ms`
- Collected: `0`; passed: `0`; failed: `0`; skipped: `0`; errors: `0`
- Command/infra failures: `1`
- Failure: `error: failed to remove file /home/gate/grok-sandbox/.venv-lane-feature-app-1-offline-cross-slice-valida-2206d2aa/lib/python3.12/site-packages/../../../bin/alembic: Read-only file system (os error 30)`

The failure occurred during `uv` environment preparation, before pytest import or collection. All seven listed tests were unexecuted; no application cross-slice owner is implicated. Route this receipt to the coordinator/lane-environment owner for the read-only uv constraint; no source repair or harmonizing integration conclusion is made.
