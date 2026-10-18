# GPUOPS-1 lane L2 — installer: intent dir, path unit, one reaper owner

Branch `feature/gpuops-1-installer`, worktree `context-alt-text-monorepo-gpuops-1-installer`. Owns `scripts/deploy/gpu-lifecycle-install.sh`, `infra/oci/cloud-init.yaml`, `scripts/deploy/tests/test_gpu_lifecycle_*.py`, `scripts/deploy/tests/test_cloud_init_*.py`, and any `docs/runbooks/*gpu*.md` a parity test forces you to update.

## Goal

The installed units pass `--intent-dir /run/acx-write` (contract C1, flag name frozen; L1 implements it in parallel), a systemd path unit reacts to intent writes within seconds, and exactly one reaper unit can ever be enabled on acx-backend (closes OPSGPU-R3-02).

## Current anchors

- `scripts/deploy/gpu-lifecycle-install.sh`: start `ExecStart` ~:704 (`flock --wait 120 /var/lib/acx-gpu/lifecycle.lock python3 -m infra.oci.gpu_lifecycle --mode start ... --load-dir /run/acx-write ...`), reap `ExecStart` ~:740, `OnUnitActiveSec` ~:716 and ~:751, stale-unit purge lists ~:196 and ~:237. No mention of `acx-gpu-idle-reaper`.
- `infra/oci/cloud-init.yaml` :29-59 defines `acx-gpu-idle-reaper.service` / `.timer` and :167 enables it. This is the second reaper.
- Tests: `scripts/deploy/tests/test_gpu_lifecycle_install.py`, `test_gpu_lifecycle_deploy_wiring.py`, `test_cloud_init_test_citations.py`, `test_gpu_cost_runbook_matches_verified_state.py`, `test_gpu_lifecycle_contract_ownership.py`.

## Deliverables

1. Both `ExecStart` lines gain `--intent-dir /run/acx-write`. Keep every existing flag.
2. New `acx-gpu-intent.path` unit: one `PathChanged=/run/acx-write/<env>/gpu-intent.json` line per environment the installer already knows (dev, staging, prod), `Unit=acx-gpu-start.service`. Ensure the per-env directories exist at install time (the installer already creates the load directories; reuse that step). The flock in `ExecStart` serialises the path-triggered run with the timer run (RES-14).
3. Remove the `acx-gpu-idle-reaper` service and timer from `cloud-init.yaml` and its `systemctl enable` line. Add `acx-gpu-idle-reaper.service` and `.timer` to the installer purge lists (`disable --now`, remove unit files, `daemon-reload`) so an already-provisioned host converges to one reaper.
4. Single-owner guard test: parse both files and assert exactly one reaper timer name is defined or enabled across the installer and cloud-init (ARCH-13). It must fail if someone re-adds either unit.

## Tests

`LC_ALL=C python3 -m pytest scripts/deploy/tests/test_gpu_lifecycle_install.py scripts/deploy/tests/test_gpu_lifecycle_deploy_wiring.py scripts/deploy/tests/test_cloud_init_test_citations.py scripts/deploy/tests/test_gpu_cost_runbook_matches_verified_state.py -q -p no:cacheprovider`

Assert: `--intent-dir /run/acx-write` on both ExecStart lines, path unit content and enablement, purge of the idle reaper, no idle-reaper text left in cloud-init, single-owner guard. If a runbook parity test breaks, update the runbook it checks.

## Non-goals

Python lifecycle code (L1), running the installer against any host, editing prod compose files.
