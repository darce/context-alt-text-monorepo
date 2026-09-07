# GPUOPS-1 lane brief: the API-side intent writer

Lane: `gpuops-1-intent` · Owned paths: `apps/prototype-description-service/scene/application/gpu_intent.py` and its tests under `apps/prototype-description-service/scene/tests/`.
Self-verify: `python3 -m pytest apps/prototype-description-service/scene/tests -q`

Three open high findings, all in one file. Read their full text and evidence
from the handoff DB before starting — the ids you own are GR-01, GR-02 and
GR-03, and nothing else:

    python3 -c "from workbay_handoff_mcp import *; configure_runtime(RuntimeConfig.for_repo(__import__('pathlib').Path('.'))); import json; print(json.dumps(list_review_findings(task_ref='GPUOPS-1', status='open', detail='full', limit=60), default=str))"

## The one that makes the feature not work at all (GR-01)

`write_gpu_intent()` emits an intent with no `sequence` field. The lifecycle
reader, `infra.oci.gpu_lifecycle.intent._read_one()`, requires it and reports
`sequence must be an integer >= 1`. The net effect today is that a POST returns
an accepted intent, the operator believes the GPU was commanded, and the reaper
treats the effective intent as `auto` and ignores it. Every operator command on
this path is silently dropped.

Fix by conforming the writer to the reader. Allocate the sequence from **one**
authoritative monotonic allocator, held under the same writer lock that guards
the intent file, and carry it through the shared dataclass, the response
payload and the JSON schema. Sequence values must not regress across a service
restart, so the allocator's state has to be durable and derived from what is
already on disk rather than from process memory. If allocation fails, return
503 — do not publish a sequence-less intent.

Add a positive end-to-end test: POST an intent, then read it back through
`infra.oci.gpu_lifecycle.intent._read_one()` and assert it is accepted and
effective. The absence of that test is why this shipped broken.

**Do not modify `infra/oci/gpu_lifecycle/**`.** A separate lane owns it in this
same wave and the reader's contract is the fixed point you are conforming to.

## Blocking flock on the event loop (GR-02)

`gpu-intent.json.lock` is acquired with a blocking `fcntl.flock(LOCK_EX)`, and
the synchronous writer is called from an async route. One stalled lock holder
therefore blocks the whole service event loop, not just this request. Use
`LOCK_NB` with a monotonic deadline bounded by the API timeout, return a
controlled 503 when the deadline passes, and get the file write off the event
loop — either offload it to a thread or make it genuinely async. A test should
hold the lock from another process and assert the route returns 503 within the
deadline instead of hanging.

## tmpfs is not durable (GR-03)

Intent is written to `/run/acx-write`, a tmpfs runtime path, with no fsync of
either the file or its parent directory, and the durable mirror is only copied
by a later reaper cycle. A reboot between the API response and that cycle
erases the authorising intent while the operator has already been told the
start was accepted. Either publish synchronously to the provisioned persistent
intent directory, or fsync a durable mirror before responding. Either way,
fsync the temp file and the containing directory before the response is sent.
Being told "accepted" must mean the fact survives a power cut.

## Boundaries

Only `apps/prototype-description-service/scene/application/gpu_intent.py` and
its tests. Do not edit `infra/oci/**`, `apps/prototype-wp-alt-context/**`,
`scripts/**`, or `docs/workbay/contracts/**` — contract and rule files are
tracked but live under gitignored directories, and the sandbox returns them as
new-file creates, which rejects the entire patch.

No AI or model attribution trailers in the commit message.
