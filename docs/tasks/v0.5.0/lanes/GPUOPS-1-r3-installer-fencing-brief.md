# GPUOPS-1-R3. Installer intent-path fencing and env allowlist

Fix wave lane. Base: `feature/gpuops-1`. Owned files only:
`scripts/deploy/gpu-lifecycle-install.sh`,
`scripts/deploy/tests/test_gpu_lifecycle_install.py`,
`scripts/deploy/tests/test_gpu_cost_runbook_matches_verified_state.py`,
`docs/runbooks/oci-instance-state-and-cost.md`.

**Never run the installer against any host.** Tests only. **Do not edit anything under
`docs/workbay/`** — read `docs/workbay/contracts/gpu-lifecycle.md`, do not modify it.

## Defects to close

**H-01 — `acx-gpu-intent.path` is not fenced during upgrade.** The installer enables the
path watcher after fencing only the start timer/service, so an intent write can launch GPU
startup while unit files are being replaced, and a failed activation leaves the watcher
enabled against a partial deployment. Disable and stop `acx-gpu-intent.path` *before*
mutating the release, keep it fenced through verification, and re-enable it only after a
successful activation. The failure-cleanup path must leave it disabled, not enabled.

**M-02 — intent path units generated for out-of-contract envs.** Path entries are generated
for every registered deployment including `dev-fir`, but the lifecycle contract allows only
`dev`, `staging` and `prod` as intent environments. A `dev-fir` intent file can trigger a
start and win effective-intent selection outside the contract. Introduce one shared
allowlist constant in the installer (`dev staging prod`) and generate intent units only for
members of it. Add a test asserting the allowlist matches the contract doc's list.

**CANON-02 — the cost-runbook guard asserts a truth GPUOPS-1 has retired.**
`test_gpu_cost_runbook_matches_verified_state.py:73` pins the literal string
"no automatic gpu cost cap" into `docs/runbooks/oci-instance-state-and-cost.md`, and a
sibling assertion requires every reaper mention there to stay qualified as not-live (the
runbook at ~:148 says "Do not wait for a reaper to catch it - there is none installed").
GPUOPS-1 installs a live reaper and the SPA confirm strip promises a 60-minute lease cap.
Rewrite the runbook prose to the post-GPUOPS-1 truth (live idle reaper + max-lease cap,
with the exact numbers taken from the installer, not invented) and re-point the guard test
at that new truth in the same change. The guard must stay a real guard — it should still
fail if the runbook and the installed units disagree. Do not delete assertions to make it
pass (sr-001).

## Definition of done

- `LC_ALL=C python3 -m pytest scripts/deploy/tests/test_gpu_lifecycle_install.py scripts/deploy/tests/test_gpu_lifecycle_deploy_wiring.py scripts/deploy/tests/test_gpu_cost_runbook_matches_verified_state.py scripts/deploy/tests/test_gpu_lifecycle_single_reaper_owner.py -q -p no:cacheprovider` green.
- Commit on `feature/gpuops-1-r3-installer-fencing` with subject
  `gpu lifecycle installer: fence intent path on upgrade, restrict intent envs`.
- **Commit early and often** — first commit inside the first quarter of the turn. Never end
  on `needs_guidance` with uncommitted work.
- No AI attribution trailers.
