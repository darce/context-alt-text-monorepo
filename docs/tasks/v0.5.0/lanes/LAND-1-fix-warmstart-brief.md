# LAND-1 lane brief — `land-1-fix-warmstart` (main regression, TDD)

Task: LAND-1 · Branch: `feature/land-1-fix-warmstart` (from `main` e3017ae2883bb761ec5e95648d7330005f2bdb6b) · Finding: `LAND-1-MR-01`.

## Defect

`main` test suite is red: `apps/prototype-description-service/scene/tests/test_describe_run_worker_gpu_warmstart.py::test_default_warmup_budget_covers_start_detection_boot_and_read_timeout` fails with `installer START_INTERVAL default is missing`. The test (line ~168) regexes `^START_INTERVAL="\$\{START_INTERVAL:-(\d+)s\}"$` against `scripts/deploy/gpu-lifecycle-install.sh`, but commit a84fe61ab (GPULIFE-1 r3 wiring) changed line 327 to `START_INTERVAL="${START_INTERVAL-30s}"` (`-` instead of `:-`). The remote gate (`make check-remote`) therefore fails `test` for every branch, blocking all landings ([RES-16] gate blindness).

## Fix (pick the honest one, explain in the commit)

- If the `:-` → `-` change was intentional (allow an explicit empty START_INTERVAL), keep the installer and make the test accept both forms: `\$\{START_INTERVAL:?-(\d+)s\}`; also assert the parsed default is a positive integer.
- If it was accidental, restore `:-` in the installer (empty env must fall back to the default — check how line 428-440 validates the value and whether an empty string would be rejected there).
- Either way the test must fail before and pass after; run `python3 -m pytest scene/tests/test_describe_run_worker_gpu_warmstart.py -q` from `apps/prototype-description-service` (use `uv run` if plain python lacks deps).

## Owned paths

- `apps/prototype-description-service/scene/tests/test_describe_run_worker_gpu_warmstart.py`
- `scripts/deploy/gpu-lifecycle-install.sh` (only line 327 if you choose the installer fix)

## Rules

Commit on the lane branch with a plain message, no attribution trailers. No other files. Close `LAND-1-MR-01` via `review_findings` resolve (status fixed, verified_commit_sha) or print `FIXED: LAND-1-MR-01 <sha> <test>`.
