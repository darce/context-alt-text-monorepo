# GPUUX-1 lane G2 report

GPUUX1-H-03 is fixed by separating lifecycle state from API-published load:

- `/run/acx` is owned by `ubuntu:ubuntu`, contains `gpu-state.json`, and is
  mounted read-only in the API container.
- `/run/acx-write` is owned by `root:10001`, contains `describe-load.json`, and
  is the API container's only writable snapshot mount.
- Both lifecycle services read `/run/acx-write/describe-load.json`; the deploy
  checker validates both paths, both mounts, and rejects a shared directory.

The existing writer was inspected without modification. It creates a temporary
file beside `gpu-state.json` and publishes with `os.replace`, so publication
changes the path's inode. The added contract test preserves a link to the old
inode and proves it remains stale after a second publication, confirming why a
file-level bind mount is not viable.

Baseline verification passed 43 shell cases and 12 Python tests. Final
verification passed 46 shell cases and 13 Python tests. No staleness budget or
fail-closed reader behavior changed.

```json
{"findings":[],"blockers":[],"tests_run":"Before: bash scripts/deploy/tests/test-check-gpu-snapshots.sh (43 PASS cases); .venv/bin/python -m pytest infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py -q (12 passed). After: bash scripts/deploy/tests/test-check-gpu-snapshots.sh (46 PASS cases); .venv/bin/python -m pytest infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py -q (13 passed).","handoff_action":"merge_ready"}
```
