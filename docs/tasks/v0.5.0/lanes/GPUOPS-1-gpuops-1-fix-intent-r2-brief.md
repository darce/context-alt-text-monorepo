# GPUOPS-1 lane brief — `gpuops-1-fix-intent` ROUND 2 (continuation, not a restart)

Task: GPUOPS-1 · Branch: `feature/gpuops-1-fix-intent` · Worktree: `/Users/daniel/Development/context-alt-text-monorepo-gpuops-1-fix-intent`
New finding-id range if you must file new ones: `GPUOPS-1-INT-01..20`. Do not reuse any other id.

## Where round 1 stopped

Round 1 hit the 1800s wall clock and committed `2f2ed9dc3 wip(offload): gpuops-1-fix-intent checkpoint 1`: +520 lines in `infra/oci/gpu_lifecycle/intent.py` and +98 test lines in `infra/oci/gpu_lifecycle/tests/test_intent.py`. It built the machinery — `IntentAuthorityStore`, `DeferredStopStore`, `DecisionLogStore`, `_intent_file_lock`, `_atomic_write_json`, `_intent_order`, `copy_intents_to_durable_dir`, and the `DEFAULT_GPU_STATE_DIR` / `DEFAULT_INTENT_AUTHORITY_PATH` / `DEFAULT_DEFERRED_STOP_PATH` / `DEFAULT_DECISION_LOG_PATH` constants. `python3 -m pytest infra/oci/gpu_lifecycle/tests/test_intent.py -q` → 25 passed.

**Do not redo round 1.** The machinery is sound. The problem is that it is *unreached*:

```
grep -rl 'IntentAuthorityStore|DeferredStopStore|DecisionLogStore|copy_intents_to_durable_dir' --include='*.py' .
  → infra/oci/gpu_lifecycle/intent.py
  → infra/oci/gpu_lifecycle/tests/test_intent.py
```

Nothing in `reaper.py`, `controller.py` or `state_snapshot.py` calls any of it. The four findings are therefore **not closed**: a monotonic authority nobody consults does not fence anything, a durable intent nobody reads does not survive a reboot, a deferred-stop record nobody re-arms is still dropped, and a decision log nobody appends to answers no question. Round 2 is the wiring, and the wiring is where the tests must bite ([RES-10] a fence is only a fence at the point of use).

## Owned paths

- `infra/oci/gpu_lifecycle/` (all modules and tests, including `reaper.py`, `controller.py`, `state_snapshot.py`, `intent.py`)
- `scripts/deploy/tests/test_gpu_cost_runbook_matches_verified_state.py`

Nothing else. In particular do **not** touch `infra/oci/cloud-init.yaml` or `scripts/deploy/gpu-lifecycle-install.sh` this round.

## Step 1 — wire the authority into the decision path (CANON-04, high)

`reaper.py:936 _resolve_effective_intent` calls `read_effective_intent(intent_dir, now)`, which orders candidate intents by wall clock. Route it through `IntentAuthorityStore` so precedence is **highest sequence wins, wall clock is a tiebreak only**. A backwards clock correction must not re-arm an expired `start`.

Tests that must exist and fail before the change:
- two intents, the older one carrying the higher sequence → the higher sequence wins.
- an expired `start` intent plus a backwards jump in `now` → the intent stays expired; the reaper still reaps on idle.
- a `start` whose sequence is below the persisted authority high-water mark → rejected as stale, not honoured.

Precedent to mirror, already in this repo: `RunningSinceLeaseStore.age_seconds` in `reaper.py` refuses a non-monotonic origin with "Persisted lease metadata is unsafe to use as a duration origin". Apply the same discipline; do not invent a second one.

## Step 2 — make the durable intent actually load (CANON-03, high)

`copy_intents_to_durable_dir` exists but no caller invokes it and no reader prefers the durable copy. Make the load path read the durable directory under `DEFAULT_GPU_STATE_DIR` and treat the tmpfs `/run/acx-write/<ACX_ENV>/` copy as a cache, not the source of truth. Fsync before acting on a write ([RES-17] a write-ahead record for a durable external mutation must itself be durable).

Test: write an intent, simulate a reboot by clearing the tmpfs dir only, resolve again → the same effective intent, the same `requested_by`, the same sequence. Today that test fails: the intent reverts to `auto` and a GPU that was held for a demo gets reaped with `last_transition_reason='idle'`.

The systemd/tmpfiles path provisioning for the new durable dir lives in `scripts/deploy/gpu-lifecycle-install.sh`, which you must not edit. Print the exact stanza you need under a `CONTRACT-DELTA:` heading in your final report and let the code default to `DEFAULT_GPU_STATE_DIR` with a graceful fallback when the dir does not exist.

## Step 3 — re-arm or surface the deferred stop (CANON-06, medium)

`reaper.py` sets `IntentStatus.BLOCKED_WORK_IN_FLIGHT` around line 1435 when a `stop` arrives while work is in flight, and then lets the same intent expire at its TTL. A describe run longer than the TTL silently discards an explicit operator stop. Persist the deferral through `DeferredStopStore` and either re-arm it past expiry or emit an explicit drop event with a counter — never both silent ([FLOW-08] a dropped instruction must leave a trace).

Test: `stop` + work in flight + `now` advanced past `expires_at` → the stop is still honoured once work drains, **or** an explicit drop record exists that names the intent and the reason. Assert on whichever you implement; do not leave the code able to do neither.

## Step 4 — append the decision record (CANON-08, medium)

Every automated start/stop decision spends money and must be reconstructable: `requested_by`, nonce, sequence, effective intent, `intent_status`, actuation outcome, timestamp — appended to the JSONL at `DEFAULT_DECISION_LOG_PATH` on durable storage ([HAI-06] an automated decision that spends money needs a record a human can replay). Append from the point where the reaper actually decides, not from the store constructor.

Test: a full cycle (start honoured, then idle stop) produces two parseable JSONL lines that let a reader answer "who started the A10 at 03:00 and did the controller honour it".

## Step 5 — GPUOPS-1-HV-01 (medium) — `scripts/deploy/tests/test_gpu_cost_runbook_matches_verified_state.py:43-61`

`test_runbook_reaper_numbers_match_installer_defaults` fails on this branch right now (`assert None is not None`; 1 failed, 2 passed). The guard hard-codes a different shell default form per variable — `MAX_LEASE_SECONDS` expects `:-`, `IDLE_SECONDS` and `REAP_INTERVAL` expect a bare `-` — while `gpu-lifecycle-install.sh:453-455` now writes `${IDLE_SECONDS:-300}`, so `idle_seconds` parses as `None` and the assert trips. The guard pins incidental shell syntax instead of the default *value*.

Fix: one helper `_shell_default(installer, name)` matching `^NAME="\$\{NAME:?-([^}]+)\}"$` for all three variables (accept both `:-` and bare `-`), and assert on the extracted values only. Verify: `python3 -m pytest scripts/deploy/tests/test_gpu_cost_runbook_matches_verified_state.py -q` → 3 passed.

This is the same class of drift as LAND-1-MR-01 (the warmstart guard vs `START_INTERVAL`): a test that pins a syntax rather than a contract ([rg-005] contract parity must be checked against the real artefact).

## Out of scope this round

**OPSGPU-R3-02 is already fixed** on `feature/gpuops-1` by commit `00250f1d6` and is being closed by the coordinator. `infra/oci/cloud-init.yaml` no longer provisions `acx-gpu-idle-reaper`, the installer purges the unit at line 197, and `scripts/deploy/tests/test_gpu_lifecycle_single_reaper_owner.py::test_exactly_one_reaper_timer_is_owned_by_the_installer` passes. Do not re-fix it and do not edit either file.

## Verification

- `python3 -m pytest infra/oci/gpu_lifecycle -q` green, with strictly more tests than today's 25 in `test_intent.py`.
- `python3 -m pytest scripts/deploy/tests/test_gpu_cost_runbook_matches_verified_state.py -q` → 3 passed.
- Report both counts.

## Rules

- TDD: each fix gets a test that fails before and passes after, and the test must exercise the **call site**, not the store in isolation. Never weaken an existing test. Name one line whose removal makes your new test fail.
- Commit incrementally on `feature/gpuops-1-fix-intent` with plain messages. No attribution trailers of any kind. Land partial correct work rather than losing it to the wall clock — order the steps as written; steps 1 and 2 are the high findings.
- Never edit `scripts/workbay_lifecycle/**`, `Makefile.d/**`, `config/lane-orchestration/**`, `docs/workbay/contracts/**`, `docs/workbay/rules/**`. Those paths are gitignored in the sandbox mirror and any edit there gets the whole patch rejected. Contract wording goes under a `CONTRACT-DELTA:` heading in the final report.
- Never start or stop a real GPU. This lane is offline code and tests only; no OCI calls, no ssh.
- Per finding, print one line: `FIXED: <id> <40-char sha> <test name>` / `ALREADY-FIXED: <id> <evidence>` / `NOT-FIXED: <id> <why>`.
- Canon anchors: [RES-10] fence at the point of use, monotonic origin · [RES-17] a write-ahead record must be as durable as what it authorises · [FLOW-08] a dropped instruction leaves a trace · [HAI-06] a money-spending automated decision must be reconstructable · [RES-01]/[API-02] idempotent re-runs · [rg-005] contract parity against the real artefact.
