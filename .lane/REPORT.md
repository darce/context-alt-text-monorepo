# FIR-12 lane F31 — BR-44 closed

**Finding:** FIR-12-BR-44 (low, TEST-15)
**Change:** parametrize `test_two_boxes_same_subject_one_search_max_score` over `high_then_low` / `low_then_high`. Helper `max_score_per_search_unit` and e2e `searches_from_run_records` (`faces` list) both see both orderings; both must yield `s_high`. `assert s_high > s_low` kept. Production `fir_search_adapter.py` untouched.

## Full suite

```
4 failed, 1327 passed, 4 skipped, 10 warnings in 50.61s
```

Baseline at cbeab50a: 4 failed / 1326 passed / 4 skipped. +1 pass is the new ordering case. The 4 failures are the pre-existing PGPASSWORD production-boot tests (`test_create_app_registers_route_and_upload_cap`, `test_startup_reclaim_failure_does_not_block_boot_and_is_wired`, `test_startup_boot_order_reclaim_then_purge_then_snapshot`, `test_startup_purge_or_snapshot_failure_does_not_block_boot`). Not mine.

Command:

```
cd /home/ubuntu/l1/fir12-n2/apps/prototype-description-service && PYTHONPATH=$PWD /home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv/bin/python -m pytest scene/tests -q -p no:cacheprovider
```

## Mutants (adapter restored after each; `git diff --exit-code` on `fir_search_adapter.py` clean)

Command each: `pytest scene/tests/test_eval_harness_fir_search_adapter.py::test_two_boxes_same_subject_one_search_max_score -q -p no:cacheprovider`

| id | mutation | summary | verdict |
|----|----------|---------|---------|
| m1 | `if current is None or s_max > current[0]:` → `if current is None:` (first-wins / f6b) | `1 failed, 1 passed in 0.60s` | **RED** |
| m2 | same → `if True:` (last-wins) | `1 failed, 1 passed in 0.59s` | **RED** |
| m3 | `s_max > current[0]` → `s_max < current[0]` (min-wins / f6) | `2 failed in 0.57s` | **RED** |

None survived.

m1 kills `low_then_high` only (`assert 0.3 == 0.95`). m2 kills `high_then_low` only. m3 kills both. That is the whole point of parametrizing both orderings.

## Canon

- **TEST-15** — a test that stays green under its mutant is not a test; first-wins was GREEN before this pin.
- **EVAL-18** / **JANUS IET (FNIR vs FPI)** — under-reporting `top1_score` on multi-box search units biases FNIR upward at every τ.
- **EVAL-16** / **JANUS end-to-end identification** — the reduction is proven through `searches_from_run_records` (detector box order), not only the helper.

No production behaviour change.
