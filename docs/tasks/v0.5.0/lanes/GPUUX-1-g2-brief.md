# GPUUX-1 lane G2 — restore the single-writer boundary for gpu-state.json

Branch `feature/gpuux-1-g2`, worktree `context-alt-text-monorepo-gpuux-1-g2`, base `56a3d288a`.

One finding, GPUUX1-H-03 (high), in
`apps/prototype-description-service/docker-compose.env.yml:59-64`.

## The defect

The compose file mounts the **same host directory twice**:

```yaml
- /run/acx:/run/acx-write        # read-write
- /run/acx:/run/acx:ro           # read-only
```

Its own comment states the intent: "Mount the same host directory again at the
reader path as read-only so the API cannot overwrite lifecycle state while load
publication stays RW."

That intent is not achieved. `:ro` constrains only the *container path*, not the
host directory. The API container writes `/run/acx-write/describe-load.json`,
which is host `/run/acx/describe-load.json` — so it can equally write
`/run/acx-write/gpu-state.json`, which is host `/run/acx/gpu-state.json`. The
read-only alias is cosmetic and the documented single-writer boundary is defeated.
A compromised or buggy API process can forge lifecycle state.

## Intended ownership

- API container (uid/gid 10001) is the **only** writer of `describe-load.json`.
- Host lifecycle systemd units are the **only** writers of `gpu-state.json`.
- API container reads `gpu-state.json` (`ACX_GPU_STATE_PATH=/run/acx/gpu-state.json`).
- Host units read `describe-load.json` (`--load-json /run/acx/describe-load.json`).

## Constraint that rules out the obvious fix

Do **not** try to fix this with a file-level bind mount of `gpu-state.json`.
`infra/oci/gpu_lifecycle/state_snapshot.py::write_gpu_state_snapshot` publishes
atomically via temp-file + `rename`. A single-file bind mount pins an inode, so
the rename would swap the host file underneath and the container would read a
permanently stale snapshot. Verify this claim yourself before relying on it.

## Required approach: two separate host directories

Give each file a directory with a single writer, e.g. host `/run/acx` (host-owned,
mounted `:ro`, holds `gpu-state.json`) and host `/run/acx-write` (container-owned,
mounted RW, holds `describe-load.json`).

This is a cross-file change. All of the following must move together or the deploy
check will fail:

- `apps/prototype-description-service/docker-compose.env.yml` — the two mounts.
- `scripts/deploy/gpu-lifecycle-install.sh:122,153` — both `ExecStart` lines
  hardcode `--load-json /run/acx/describe-load.json`.
- `scripts/deploy/check-gpu-snapshots.sh:63` — currently *enforces* the very
  coupling you are removing:
  `die "GPU state and describe-load units do not share one snapshot directory"`.
  That rule must become a two-directory rule that still verifies each unit path
  agrees with its env var. Do not simply delete the check (sr-001) — replace it
  with one that enforces the new, stronger invariant.
- `scripts/deploy/tests/test-check-gpu-snapshots.sh` — fixtures and assertions.
- `infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py:109-112` —
  asserts `ACX_DESCRIBE_LOAD_PATH=/run/acx-write/describe-load.json` and
  `- /run/acx:/run/acx-write`.

Also confirm host-side directory ownership/permissions still let uid 10001 write
the load dump while the units own the state dir (see
`gpu-lifecycle-install.sh:169`).

## Requirements

- Add a regression test that fails on the old layout: assert the compose file does
  not mount one host path at two container paths with differing `:ro`, or more
  directly that the state directory is not writable by the API service.
- Keep both snapshot readers fail-closed on missing/stale files. Do not weaken the
  staleness budgets.
- rg-006: any command in docs must run exactly as written after your change.
- rg-008: config consumed by multiple modules validates at load time.

## Do NOT

- Do not touch `infra/oci/gpu_lifecycle/state_snapshot.py` or `reaper.py` — lane G1
  owns those files and will conflict.
- Do not edit any frontend/JS or PHP file.
- Do not modify the GPUUX-1 task plan.
- Do not relax a failing check to make the suite pass (sr-001).

## Verify

`bash scripts/deploy/tests/test-check-gpu-snapshots.sh` (bash 3.2 compatible; note
this suite is NOT safe to run under `make -n`) and
`python -m pytest infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py -q`.
Both must pass. Report counts before and after.

## Harvest contract (MANDATORY)

The orchestrator's automatic findings harvest is broken for this backend, so you
must deliver findings twice:

1. Write `docs/tasks/v0.5.0/lanes/GPUUX-1-g2-report.md`, commit it on this branch,
   and end that file with a fenced ```json block:
   `{"findings": [{"finding_id": "...", "severity": "high|medium|low", "file_path": "...", "description": "...", "fix": "..."}], "blockers": [], "tests_run": "...", "handoff_action": "..."}`
2. Repeat that identical JSON verbatim in your final handoff summary text.

If you found no new issues, emit `{"findings": [], ...}` explicitly. Never omit
the block.
