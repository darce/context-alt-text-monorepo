# GPUOPS-1 lane brief: reaper durability and fencing

Lane: `gpuops-1-reaper` · Owned paths: `infra/oci/gpu_lifecycle/**` only.
Self-verify: `python3 -m pytest infra/oci/gpu_lifecycle/tests -q`

Five open high findings on this lane, all in `reaper.py` and `intent.py`. They
interlock, so fix them as one coherent change rather than five patches. Read the
full text and evidence from the handoff DB before starting:

    python3 -c "from workbay_handoff_mcp import *; configure_runtime(RuntimeConfig.for_repo(__import__('pathlib').Path('.'))); import json; print(json.dumps(list_review_findings(task_ref='GPUOPS-1', status='open', detail='full', limit=50), default=str))"

The ids you own are GR-04, GR-05, GR-06, GR-07 and GR-14. Do not touch findings
outside that set; other lanes own them and share no files with you.

## What the five findings are actually about

There is one theme: **the reaper mutates the cloud before it makes the
authorising fact durable, and its fencing token comparisons are not tight
enough to reject stale or replayed authority.**

### Durability ordering (GR-04)

`actuator.start_instance()` is issued before the running-since lease and the
honoured nonce are written. A crash in that window leaves an A10 running with
no durable lease cap and no honoured marker — the code even logs that lease
protection is disabled and carries on. Write and fsync a *pending* lease and
authority record before the OCI mutation, then commit the outcome after it
returns. An interrupted START must be reconcilable on the next cycle from the
pending record alone; add a test that kills the process between the pending
write and the commit and asserts the next cycle reconciles rather than
double-starting or losing the cap.

### Atomic-write primitive (GR-05)

`RunningSinceLeaseStore` uses `write_text()` + `replace()` with no fsync of
either the temp file or the parent directory. The nonce ledger, failure-count
and removal records repeat the pattern. Centralise this: one durable-atomic-write
helper that opens with a restrictive mode, writes, flushes, fsyncs the file,
replaces, then fsyncs the parent directory. Route every store through it. A
helper that exists but is bypassed by one caller is not a fix — grep for
`write_text` and `replace(` in the package afterwards and make the remaining
hits deliberate.

### Nonce replay (GR-06)

The authority store accepts a nonce that was already used, provided the
sequence is higher. Writing nonce N at sequence 1 and then nonce N at sequence 2
yields an effective start at sequence 2. Either persist an immutable nonce
ledger and reject reuse at *every* sequence, or make an exact duplicate
publication strictly idempotent (same nonce and same sequence returns the
already-recorded decision unchanged). A new intent must require a fresh nonce.
Pick one of the two and say in the commit body which and why.

### Equal-sequence supersession (GR-07)

Deferred-stop supersession compares sequence with `>` only, so a START at
sequence 5 with a different nonce does not displace a deferred STOP at
sequence 5. Reject duplicate sequence values at publication time, compare the
full fencing token (sequence and nonce together) atomically, and clear or
retain deferred state only after the supersession decision itself is durable.

### Rearm failure is not fail-closed (GR-14)

When rearming a deferred stop raises, the exception is logged and the original,
possibly expired, intent is returned. The explicit STOP then dissolves into
ordinary idle handling with no durable trace that an instruction was dropped.
Fail closed: on rearm failure, refuse automatic actuation for that cycle and
append a durable drop record carrying nonce, sequence, reason and the error.
Losing a stop instruction silently is the failure mode this whole subsystem
exists to prevent.

## Boundaries

Only `infra/oci/gpu_lifecycle/**`. Do not edit `apps/**`, `scripts/**` or
`docs/workbay/contracts/**` — contracts and rules files are tracked but sit
under gitignored directories and the sandbox returns them as new-file creates,
which rejects the whole patch.

The on-disk intent file format is a contract shared with
`apps/prototype-description-service/scene/application/gpu_intent.py`, which
another lane is changing in the same wave to start emitting the monotonic
`sequence` that `intent._read_one()` already requires. **Do not change what
`_read_one` accepts.** The writer is being made to conform to the reader, not
the other way round. If you believe the reader's contract is itself wrong, stop
and say so in the result rather than changing it.

No AI or model attribution trailers in the commit message.
