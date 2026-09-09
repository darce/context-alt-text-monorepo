# GPUOPS-1-R4. Reaper start-failure attribution

Fix wave lane. Base: `feature/gpuops-1`. Owned files only:
`infra/oci/gpu_lifecycle/reaper.py`, `infra/oci/gpu_lifecycle/tests/test_start_actuator.py`.

**Do not edit `infra/oci/gpu_lifecycle/intent.py`** — another lane owns it this wave.
**Do not edit anything under `docs/workbay/`.** Read
`docs/workbay/contracts/gpu-lifecycle.md` for the frozen contract.

## Defect to close

**H-03 — a failed START is not recorded as failed.** Around `reaper.py:1708-1729`, when
`actuator.start_instance` raises `subprocess.SubprocessError` and the follow-up
reconciliation cannot prove the instance reached RUNNING, the code records an error and
continues *without* appending the instance to `start_failed`. The emitted snapshot therefore
omits the FALLBACK decision with `reason=start_failed` that the contract requires, so the
CPU fallback tier is never signalled and the operator's status view shows no failure.

Append the instance to `start_failed` on an unreconciled subprocess failure. Keep the
existing behaviour for the reconciled case, where reconciliation *does* prove RUNNING —
that path must still not report a failure.

## Definition of done

- TDD: a regression test in `tests/test_start_actuator.py` that drives
  `start_instance` to raise `subprocess.SubprocessError`, leaves reconciliation unable to
  prove RUNNING, and asserts the emitted snapshot carries the FALLBACK decision with
  `reason=start_failed`. Add the mirror test for the reconciled-success case so the fix
  cannot over-fire.
- `python3 -m pytest infra/oci/gpu_lifecycle/tests/test_start_actuator.py infra/oci/gpu_lifecycle/tests/test_cpu_fallback.py -q -p no:cacheprovider` green.
- Commit on `feature/gpuops-1-r4-reaper-start` with subject
  `gpu lifecycle: record start_failed on unreconciled start subprocess failure`.
- **Commit early and often** — first commit inside the first quarter of the turn. Never end
  on `needs_guidance` with uncommitted work.
- No AI attribution trailers.
