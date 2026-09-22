# APP-1 offline cross-slice validation receipt

- Date: 2026-09-22
- Authoritative native VM validation: the exact declared 61-test command exited `0`; `61 passed in 19.94s`; no tests were skipped.
- Authoritative receipt: coordinator `.task-state/app1-resume-offline-cross-slice-validation/actual-selfverify-v5-green.json`.
- Tested-source provenance (native VM snapshot; hashes intentionally differ from feature refs): agent spec head `9cca9a2f7425f4b04b6fd7fb5cc48593c10ba9fd`; remote source commit `9cca9a2f7425f4b04b6fd7fb5cc48593c10ba9fd`; remote source tree `89a3f19b0e1649e7941db3ca2368f94ccbaaaaa3`; dispatch ref `refs/heads/feature-app-1-offline-cross-slice-valida-2206d2aa-65200-b19e9c7b3fe49246`; dispatch nonce `65200-b19e9c7b3fe49246`; requested branch/ref `feature/app-1-offline-cross-slice-validation` / `refs/heads/feature/app-1-offline-cross-slice-validation`; sandbox base commit/tree `243b4b32a2d57f9fb99f416e35f94c3b05c5bf25` / `89a3f19b0e1649e7941db3ca2368f94ccbaaaaa3`; history stripped: `true`; model process started: `true`.
- Feature integration prerequisite: PostgreSQL fixture fix `8fbdc701ad554a74eba03b2d8c299ebbaa21b146`; this evidence lane contains no production or test edits.

## Exact TEST_CMD

```sh
IDENTITY_PG_REQUIRED=1 uv run --directory apps/prototype-description-service --extra dev python -m pytest recognition/tests/unit/test_app1_billing_reconcile.py recognition/tests/unit/test_app1_billing_reconcile_recovery.py recognition/tests/integration/test_app1_billing_reconcile_postgres.py recognition/tests/integration/test_app1_billing_namespace_postgres.py recognition/tests/integration/test_app1_billing_recovery_postgres.py recognition/tests/integration/test_app1_usage_worker_postgres.py recognition/tests/integration/test_app1_usage_recovery_postgres.py -q -p no:randomly --timeout=60
```

## Result

- Native VM exact command exit status: `0`; `61 passed`; `0 failed`; `0 skipped`; timing: `19.94s`.
- Native VM output tail: `receipt=/tmp/prototype-description-service-pytest-collection-scope-4146206-1790084895954617102.json` and `61 passed in 19.94s`.
- Earlier restrictive model-sandbox attempt (not the authoritative result): `uv` could not prepare the lane because it failed to remove `.../site-packages/__editable__.prototype_description_service-0.4.2.4.pth` with `Read-only file system (os error 30)`; its `UV_NO_SYNC=1` fallback collected 61 tests, with `46 passed`, `0 failed`, `0 skipped`, and `15 PostgreSQL setup errors` because PostgreSQL was unavailable in that sandbox.
- The earlier sandbox limitation does not establish that native VM tests were unavailable and is not a current failure or blocker. Provider accounts were not used and no live requests were made.
