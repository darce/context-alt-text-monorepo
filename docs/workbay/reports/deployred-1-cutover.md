# DEPLOYRED-1 cutover failure classification

## Commands run

The default reproduction was run on the cutover file; it attempted the product's documented SSH manifest preflight and failed before reaching the simulated rollback assertions:

```sh
LC_ALL=C uv run --no-project --with pytest --with 'oci>=2.126.0,<3.0.0' python -m pytest \
  scripts/deploy/tests/test_cutover_recovery_residuals.py::test_partial_rollback_restores_prior_sticky_repo_while_preserving_failure \
  scripts/deploy/tests/test_cutover_recovery_residuals.py::test_rollback_real_initial_fence_preserves_refusal_without_sticky_cleanup \
  -q -p no:cacheprovider --tb=short
```

Then, to diagnose the unit-test setup without invoking the manifest preflight, ran these target selectors separately by file with `ACX_ENV_PREFLIGHT=0`:

- `test_cutover_recovery_residuals.py`: 6 passed.
- `test_deploy_env_lease.py`: 2 passed.
- `test_interrupt_compensation.py`: 2 passed.
- `test_promote_source_sha.py`: 3 failed after reaching the still-unmocked deploy lease SSH call.
- `test_verify_classification.py`: 3 failed before the expected record file was created, after its still-unmocked deploy lease call failed.

```sh
ACX_ENV_PREFLIGHT=0 LC_ALL=C uv run --no-project --with pytest --with 'oci>=2.126.0,<3.0.0' python -m pytest \
  scripts/deploy/tests/test_cutover_recovery_residuals.py::test_partial_rollback_restores_prior_sticky_repo_while_preserving_failure \
  scripts/deploy/tests/test_cutover_recovery_residuals.py::test_rollback_real_initial_fence_preserves_refusal_without_sticky_cleanup \
  -q -p no:cacheprovider --tb=short
ACX_ENV_PREFLIGHT=0 LC_ALL=C uv run --no-project --with pytest --with 'oci>=2.126.0,<3.0.0' python -m pytest \
  scripts/deploy/tests/test_deploy_env_lease.py::test_lost_lease_before_restart_stops_without_compensation \
  scripts/deploy/tests/test_deploy_env_lease.py::test_lost_lease_after_promote_gate_stops_before_tag_push \
  -q -p no:cacheprovider --tb=short
ACX_ENV_PREFLIGHT=0 LC_ALL=C uv run --no-project --with pytest --with 'oci>=2.126.0,<3.0.0' python -m pytest \
  scripts/deploy/tests/test_interrupt_compensation.py::test_ship_interrupt_between_push_and_restart \
  scripts/deploy/tests/test_interrupt_compensation.py::test_ship_tag_push_failure_skips_rollback_after_lease_loss \
  -q -p no:cacheprovider --tb=short
ACX_ENV_PREFLIGHT=0 LC_ALL=C uv run --no-project --with pytest --with 'oci>=2.126.0,<3.0.0' python -m pytest \
  scripts/deploy/tests/test_promote_source_sha.py::test_promote_refuses_source_commit_mismatch \
  scripts/deploy/tests/test_promote_source_sha.py::test_promote_proceeds_when_source_commit_matches \
  scripts/deploy/tests/test_promote_source_sha.py::test_promote_fails_closed_when_source_commit_unreadable \
  -q -p no:cacheprovider --tb=short
ACX_ENV_PREFLIGHT=0 LC_ALL=C uv run --no-project --with pytest --with 'oci>=2.126.0,<3.0.0' python -m pytest \
  scripts/deploy/tests/test_verify_classification.py::test_ship_expectation_error_exits_2_without_rollback \
  scripts/deploy/tests/test_verify_classification.py::test_ship_failed_verification_still_rolls_back \
  -q -p no:cacheprovider --tb=short
```

The repo sanity check passed:

```sh
uv run --no-project --with pytest python -m pytest scripts/test_check_lane_manifest_overlaps.py -q
```

## Summary

| Class | Count |
| --- | ---: |
| ENV | 0 |
| HARNESS | 16 |
| STALE | 0 |
| REGRESSION | 0 |

The common failure is that deploy and promote drivers mock individual network-facing steps but omit `preflight_env_manifest`. The documented default is enabled, and that function launches `scripts/env/materialize_remote.sh --check`, which uses SSH to the configured backend (`recognition-service.sh:73-74,989-1023`; `materialize_remote.sh:93`). The test runs therefore fail on hostname resolution before their target assertions. This is a harness isolation defect: the preflight is part of the deliberate deploy contract, but these focused unit drivers do not replace it. The promotion-source and verify drivers also need to stub `deploy_env_lease`; bypassing the manifest check exposed that second live dependency.

## Test classifications

| Test id | Class | Root cause (file:line evidence) | Proposed fix (one sentence) | Proposed owned paths |
| --- | --- | --- | --- | --- |
| `scripts/deploy/tests/test_cutover_recovery_residuals.py::test_partial_rollback_restores_prior_sticky_repo_while_preserving_failure[0-do_deploy dev]` | HARNESS | `_run_partial_rollback` mocks deploy preflights at `test_cutover_recovery_residuals.py:269-279` but omits `preflight_env_manifest`; deploy calls it at `recognition-service.sh:4835`. | Stub `preflight_env_manifest` in the generated driver so this test reaches its rollback assertions offline. | `scripts/deploy/tests/test_cutover_recovery_residuals.py` |
| `scripts/deploy/tests/test_cutover_recovery_residuals.py::test_partial_rollback_restores_prior_sticky_repo_while_preserving_failure[0-do_promote dev staging]` | HARNESS | `_run_partial_rollback` mocks deploy preflights at `test_cutover_recovery_residuals.py:269-279` but omits `preflight_env_manifest`; promote calls it at `recognition-service.sh:5004`. | Stub `preflight_env_manifest` in the generated driver so this test reaches its rollback assertions offline. | `scripts/deploy/tests/test_cutover_recovery_residuals.py` |
| `scripts/deploy/tests/test_cutover_recovery_residuals.py::test_partial_rollback_restores_prior_sticky_repo_while_preserving_failure[1-do_deploy dev]` | HARNESS | `_run_partial_rollback` mocks deploy preflights at `test_cutover_recovery_residuals.py:269-279` but omits `preflight_env_manifest`; deploy calls it at `recognition-service.sh:4835`. | Stub `preflight_env_manifest` in the generated driver so this test reaches its rollback assertions offline. | `scripts/deploy/tests/test_cutover_recovery_residuals.py` |
| `scripts/deploy/tests/test_cutover_recovery_residuals.py::test_partial_rollback_restores_prior_sticky_repo_while_preserving_failure[1-do_promote dev staging]` | HARNESS | `_run_partial_rollback` mocks deploy preflights at `test_cutover_recovery_residuals.py:269-279` but omits `preflight_env_manifest`; promote calls it at `recognition-service.sh:5004`. | Stub `preflight_env_manifest` in the generated driver so this test reaches its rollback assertions offline. | `scripts/deploy/tests/test_cutover_recovery_residuals.py` |
| `scripts/deploy/tests/test_cutover_recovery_residuals.py::test_rollback_real_initial_fence_preserves_refusal_without_sticky_cleanup[do_deploy dev]` | HARNESS | `_run_partial_rollback` mocks deploy preflights at `test_cutover_recovery_residuals.py:269-279` but omits `preflight_env_manifest`; deploy calls it at `recognition-service.sh:4835`. | Stub `preflight_env_manifest` in the generated driver so this test reaches its rollback assertions offline. | `scripts/deploy/tests/test_cutover_recovery_residuals.py` |
| `scripts/deploy/tests/test_cutover_recovery_residuals.py::test_rollback_real_initial_fence_preserves_refusal_without_sticky_cleanup[do_promote dev staging]` | HARNESS | `_run_partial_rollback` mocks deploy preflights at `test_cutover_recovery_residuals.py:269-279` but omits `preflight_env_manifest`; promote calls it at `recognition-service.sh:5004`. | Stub `preflight_env_manifest` in the generated driver so this test reaches its rollback assertions offline. | `scripts/deploy/tests/test_cutover_recovery_residuals.py` |
| `scripts/deploy/tests/test_deploy_env_lease.py::test_lost_lease_before_restart_stops_without_compensation` | HARNESS | `_run_driver` has a local `ssh` function at `test_deploy_env_lease.py:43-50`, but the separate materializer process still SSHes; the test stubs other preflights at `:502-508` and omits `preflight_env_manifest`, called from deploy at `recognition-service.sh:4835`. | Stub `preflight_env_manifest` in the deploy driver while retaining its simulated lease loss. | `scripts/deploy/tests/test_deploy_env_lease.py` |
| `scripts/deploy/tests/test_deploy_env_lease.py::test_lost_lease_after_promote_gate_stops_before_tag_push` | HARNESS | The test stubs `preflight_ssh` and adjacent checks at `test_deploy_env_lease.py:544-550` but not `preflight_env_manifest`, which deploy invokes at `recognition-service.sh:4835`. | Stub `preflight_env_manifest` in the deploy driver while retaining its simulated lease loss. | `scripts/deploy/tests/test_deploy_env_lease.py` |
| `scripts/deploy/tests/test_interrupt_compensation.py::test_ship_interrupt_between_push_and_restart` | HARNESS | The scenario mocks deploy calls at `test_interrupt_compensation.py:539-554` but not `preflight_env_manifest`, which deploy invokes at `recognition-service.sh:4835`. | Stub `preflight_env_manifest` in the generated driver so the interrupt is exercised without the manifest SSH preflight. | `scripts/deploy/tests/test_interrupt_compensation.py` |
| `scripts/deploy/tests/test_interrupt_compensation.py::test_ship_tag_push_failure_skips_rollback_after_lease_loss` | HARNESS | `_run_lease_driver` defines an SSH function at `test_interrupt_compensation.py:78-104`, but the child materializer uses its own SSH process; the scenario omits `preflight_env_manifest` at `:578-594`, called at `recognition-service.sh:4835`. | Stub `preflight_env_manifest` in the lease driver while preserving the foreign-lease simulation. | `scripts/deploy/tests/test_interrupt_compensation.py` |
| `scripts/deploy/tests/test_promote_source_sha.py::test_promote_refuses_source_commit_mismatch` | HARNESS | `_promote_driver` stubs promotion steps at `test_promote_source_sha.py:44-61` but omits `preflight_env_manifest` and `deploy_env_lease`, both called before source validation at `recognition-service.sh:5004-5006`. | Stub both external preflights in `_promote_driver` so the assertion tests source-commit refusal only. | `scripts/deploy/tests/test_promote_source_sha.py` |
| `scripts/deploy/tests/test_promote_source_sha.py::test_promote_proceeds_when_source_commit_matches` | HARNESS | `_promote_driver` stubs promotion steps at `test_promote_source_sha.py:44-61` but omits `preflight_env_manifest` and `deploy_env_lease`, both called before source validation at `recognition-service.sh:5004-5006`. | Stub both external preflights in `_promote_driver` so the assertion tests the matching-source promotion flow only. | `scripts/deploy/tests/test_promote_source_sha.py` |
| `scripts/deploy/tests/test_promote_source_sha.py::test_promote_fails_closed_when_source_commit_unreadable` | HARNESS | `_promote_driver` stubs promotion steps at `test_promote_source_sha.py:44-61` but omits `preflight_env_manifest` and `deploy_env_lease`, both called before source validation at `recognition-service.sh:5004-5006`. | Stub both external preflights in `_promote_driver` so the assertion tests unreadable-source refusal only. | `scripts/deploy/tests/test_promote_source_sha.py` |
| `scripts/deploy/tests/test_verify_classification.py::test_ship_expectation_error_exits_2_without_rollback[0]` | HARNESS | `_run_ship` mocks its deploy flow at `test_verify_classification.py:142-160` but omits `preflight_env_manifest` and `deploy_env_lease`, called at `recognition-service.sh:4835,4840` before verification. | Stub both external preflights in `_run_ship` so the test reaches expectation-error classification. | `scripts/deploy/tests/test_verify_classification.py` |
| `scripts/deploy/tests/test_verify_classification.py::test_ship_expectation_error_exits_2_without_rollback[1]` | HARNESS | `_run_ship` mocks its deploy flow at `test_verify_classification.py:142-160` but omits `preflight_env_manifest` and `deploy_env_lease`, called at `recognition-service.sh:4835,4840` before verification. | Stub both external preflights in `_run_ship` so the test reaches expectation-error classification. | `scripts/deploy/tests/test_verify_classification.py` |
| `scripts/deploy/tests/test_verify_classification.py::test_ship_failed_verification_still_rolls_back` | HARNESS | `_run_ship` mocks its deploy flow at `test_verify_classification.py:142-160` but omits `preflight_env_manifest` and `deploy_env_lease`, called at `recognition-service.sh:4835,4840` before verification. | Stub both external preflights in `_run_ship` so the test reaches rollback after failed verification. | `scripts/deploy/tests/test_verify_classification.py` |

## Proposed fix lanes

All five fixes are harness-only changes to distinct test files, so no lane ordering is required.

1. **Cutover recovery residuals** — own `scripts/deploy/tests/test_cutover_recovery_residuals.py`; stub the manifest preflight in its generated driver. Required command: `LC_ALL=C uv run --no-project --with pytest --with 'oci>=2.126.0,<3.0.0' python -m pytest scripts/deploy/tests/test_cutover_recovery_residuals.py -q -p no:cacheprovider`.
2. **Deploy environment lease** — own `scripts/deploy/tests/test_deploy_env_lease.py`; stub the manifest preflight for the deploy-flow scenarios. Required command: `LC_ALL=C uv run --no-project --with pytest --with 'oci>=2.126.0,<3.0.0' python -m pytest scripts/deploy/tests/test_deploy_env_lease.py -q -p no:cacheprovider`.
3. **Interrupt compensation** — own `scripts/deploy/tests/test_interrupt_compensation.py`; stub the manifest preflight in the affected drivers. Required command: `LC_ALL=C uv run --no-project --with pytest --with 'oci>=2.126.0,<3.0.0' python -m pytest scripts/deploy/tests/test_interrupt_compensation.py -q -p no:cacheprovider`.
4. **Promote source SHA** — own `scripts/deploy/tests/test_promote_source_sha.py`; stub both manifest preflight and lease acquisition in `_promote_driver`. Required command: `LC_ALL=C uv run --no-project --with pytest --with 'oci>=2.126.0,<3.0.0' python -m pytest scripts/deploy/tests/test_promote_source_sha.py -q -p no:cacheprovider`.
5. **Verify classification** — own `scripts/deploy/tests/test_verify_classification.py`; stub both manifest preflight and lease acquisition in `_run_ship`. Required command: `LC_ALL=C uv run --no-project --with pytest --with 'oci>=2.126.0,<3.0.0' python -m pytest scripts/deploy/tests/test_verify_classification.py -q -p no:cacheprovider`.
