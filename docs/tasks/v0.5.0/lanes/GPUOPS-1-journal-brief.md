# GPUOPS-1 lane brief — gpuops-1-journal

Branch `feature/gpuops-1-journal`, based on `feature/gpuops-1` @ `40d633f01`.
Test command: `python -m pytest infra/oci/gpu_lifecycle/tests -q` (248 passing at base — keep them all green).

## Why this lane exists

Three review findings against `docs/workbay/contracts/gpu-lifecycle.md` are still open. They
are all one defect family: the operator's intent to start or stop a $2/hr A10 is recorded
somewhere that does not survive, and nothing records what the controller did about it.

- **CANON-03 (high)** — the intent is a write-ahead record for a durable external mutation,
  but it lives on tmpfs at `/run/acx-write/<ACX_ENV>/gpu-intent.json`, which
  `gpu-lifecycle-install.sh` recreates empty at every boot. What it authorises is *not*
  ephemeral: the A10 keeps running in OCI and the lease is durable at
  `/var/lib/acx-gpu/running-since.json`. After a backend reboot the durable half survives
  while the intent and its `requested_by` vanish, so a `start` that was suppressing idle
  reap silently reverts to `auto` and the GPU is reaped mid-demo, with
  `last_transition_reason` recording `idle` rather than `operator`.
- **CANON-06 (medium)** — a deferred stop is dropped without a trace. The controller defers
  a `stop` while work is in flight (`intent_status=blocked_work_in_flight`), but the same
  intent carries `expires_at` with a 1800s default. A describe run longer than the TTL
  means the deferred stop is never honoured: the intent goes `expired` and the GPU runs to
  the lease cap. No drop counter, no correction event, no re-arm.
- **CANON-08 (medium)** — no reconstructable record of an automated decision that spends
  money. One tmpfs intent file per env, overwritten per POST, `requested_by` clobbered by
  the next write; the durable half (`honoured_nonce`) carries no requester and no outcome.
  "Who started the A10 at 03:00, and did the controller honour it?" is unanswerable after
  two clicks or one reboot.

## What already landed — build on it, do not replace it

`feature/gpuops-1` @ `40d633f01` already carries `IntentAuthorityStore` in
`infra/oci/gpu_lifecycle/intent.py`: a monotonic sequence plus nonce, with
`read_effective_intent` ordering by sequence rather than wall clock, and
`_resolve_effective_intent` in `reaper.py` falling back to `auto` when authority is
unreadable. That closed CANON-04 and its tests must stay green. Extend it; do not rewrite
the sequence.

A monotonic sequence orders publications. It does not make an already-spent grant
unspendable, and that is what CANON-03 names. Note also that a monotonic counter resets to
zero at reboot, so a reset sequence can read as *older*, not newer — whatever you build has
to be correct across that reset.

## Prior art available for reference

Branch `feature/gpuops-1-intent-journal` @ `4c4c5ea` is a quarantined, unmerged candidate
implementation of exactly this. It is reference material, not a target to merge. Read it,
take what is right, discard what is not. Its notable pieces:

- `infra/oci/gpu_lifecycle/intent_journal.py` — append-only journal on durable storage with
  a burned-nonce terminal ledger: once a grant is honoured its nonce is recorded as spent
  and can never be honoured again, which is the property a sequence alone does not give.
- `infra/oci/gpu_lifecycle/hostclock.py` — `read_host_boot_id` / `acquire_flock_with_timeout`
  extracted out of `reaper.py` to break an import cycle. The exact
  `BootIdentityUnavailableError` message text is asserted by two existing tests; preserve it.
- boot_id revocation: an intent granted under a previous boot id is revoked with an ERROR
  log naming the original `requested_by`, rather than silently surviving.
- `infra/oci/gpu_lifecycle/tests/test_intent_journal.py` — 17 behavioural tests. These are
  the most reusable part. Mutation-verified: forcing a wall-clock-only fence turned 9 of 17
  red; removing the write-ahead OBSERVED append turned 8 of 17 red.

Its `docs/workbay/contracts/gpu-lifecycle.md` section is **superseded** — the contract text
on `feature/gpuops-1` is the one that counts. If you write contract prose, write it against
what is on this branch, and do not let a test assert on prose that another lane owns.

## One decision you must make explicitly

Journal-append failure policy. The landed code surfaces the failure in `result.errors`; the
quarantined candidate logs it and continues (per rg-007, one unit's failure must not halt
the others). Both are defensible; they cannot both be true. Pick one, implement it once,
and state it in the contract so the next reader does not have to infer it.

## Definition of done

- Each of CANON-03, CANON-06, CANON-08 closed behind a test that was verified failing first
  (write the test, watch it go red, then fix).
- `python -m pytest infra/oci/gpu_lifecycle/tests -q` green, ≥248 tests.
- Committed on `feature/gpuops-1-journal`. No AI attribution trailers in the commit message.
