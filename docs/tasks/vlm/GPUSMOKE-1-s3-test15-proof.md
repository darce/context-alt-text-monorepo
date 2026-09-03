# GPUSMOKE-1 S3 TEST-15 discrimination proof

Each row was produced by temporarily mutating `scripts/gpu_burst_smoke.py`, running
`RECOGNITION_RUNTIME_MODE=development python3 -m pytest ../../scripts/test_gpu_burst_smoke.py -q`
from `apps/prototype-description-service`, observing the failure, and restoring the
production check before the next mutation.

| Mutation | Failing test | Observed assertion message |
| --- | --- | --- |
| Replace the exact requested/returned media-ID set comparison with `True`. | `test_red_missing_one_of_two_requested_media_items` | `AssertionError: assert not True` for `returned_media_ids_exact`; 1 failed, 53 passed. |
| Add `completed_with_errors` back to `SUCCESS_RUN_STATUSES`. | `test_red_completed_with_errors_is_not_success` | `AssertionError: assert 0 == 1`; the run incorrectly exited zero; 1 failed, 53 passed. |
| Replace the every-requested-item `status == completed` result with `True`. | `test_red_requested_item_final_status_is_not_completed` | `AssertionError: assert not True` for `all_items_completed`; 1 failed, 53 passed. |
| Disable recording terminal item states observed before RUNNING. | `test_red_item_terminal_before_instance_running` | `AssertionError: assert not True` for `no_item_terminal_before_running`; 1 failed, 53 passed. |
| Disable recording completed `provisional_cpu` observations as degraded. | `test_red_completed_provisional_observed_mid_run_is_degraded` | `AssertionError: assert 0 == 1`; the degraded observation incorrectly exited zero; 1 failed, 53 passed. |
| Break after the first compensating-STOP state read instead of polling to STOPPED. | `test_red_warm_start_deadline_still_issues_stop`; `test_red_instance_left_running_issues_compensating_stop`; `test_red_deadline_still_issues_stop`; `test_red_failed_stop_command_is_reported`; `test_red_stop_reverification_fails_if_compensating_stop_is_ineffective`; `test_red_compensating_stop_times_out_in_stopping` | Compensating STOP was skipped and `instance_stopped_finally` incorrectly passed with `RUNNING`; 6 failed, 48 passed. |
| Disable closing an unterminated `RUNNING` interval at the evidence timestamp. | `test_red_stop_reverification_fails_if_compensating_stop_is_ineffective` | `AssertionError: assert 0.0 > 0` for `measurements.running_seconds`; 1 failed, 53 passed. |
| Force `running_seconds_ongoing` false after STOPPED reverification fails. | `test_red_stop_reverification_fails_if_compensating_stop_is_ineffective` | `AssertionError: assert False is True` for `measurements.running_seconds_ongoing`; 1 failed, 53 passed. |
| Replace the `warm_start_running` result with `True`. | `test_red_warm_start_deadline_still_issues_stop` | `AssertionError: assert not True` for `warm_start_running`; 1 failed, 53 passed. |
| Print `app_password` to stderr at the start of `run_smoke`. | `test_application_password_is_absent_from_output_and_evidence` | `AssertionError: assert 'unique-wp-application-password' not in captured.err`; 1 failed, 53 passed. |

After all mutations were restored, the same command completed with `54 passed`.
