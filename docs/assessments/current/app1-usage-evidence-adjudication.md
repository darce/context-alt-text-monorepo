# APP-1 usage and evidence adjudication

Planning-only contract amendment for Plan0002 P02/P05. This document records the
implementation contract and acceptance evidence required for APP-1; it makes no
production change.

## Decision

Beta compute must have one tenant-scoped operation identity, one durable usage
reservation, one persisted job binding, and one fenced terminal settlement. A retry
may reuse an operation only when its canonical request fingerprint is identical. A
new operation is an intentional resubmission and must be charged independently. An
HTTP 202 is admission acknowledgement, never terminal success.

Every compute entry point must call the same admission contract or explicitly reject
beta before it can do work. Read-only status polling remains free. Tenant allowance,
global daily cost, global in-flight count, bounded queue state, and stop/fencing state
must be checked atomically. Missing limits or missing required evidence are fail-closed
conditions, not unlimited access and not a green evaluation.

## Bounded review basis

The exact current symbols used below were checked in the existing tree:

- `recognition/domain/portal_contracts.py`: `UsageAdmissionService`, `UsageTicket`,
  and `UsageReservationStatus`.
- `db/models/portal_billing.py`: `UsageReservation`, `TenantEntitlement`, and the
  tenant/idempotency uniqueness constraint.
- `scene/interface_adapters/http/routers/describe.py`: `AsyncAdmissionGate`,
  `_ASYNC_ADMISSION`, `_accept_operation`, `describe_image_multipart`,
  `enqueue_describe_image`, `get_describe_job`, and the GPU lifecycle helpers.
- `scene/interface_adapters/http/routers/describe_run.py`:
  `create_describe_run`, `get_describe_run`, `list_describe_run_items`, and
  `cancel_describe_run`.
- `scene/application/describe_run_repository.py`: `create_run` and
  `create_single_run`.
- `recognition/interface_adapters/http/deps/demo_quota.py`:
  `maybe_consume_demo_quota` and `consume_demo_quota_units`.
- `scene/interface_adapters/http/routers/gpu.py`: `get_gpu_status` at
  `/gpu/status` and `post_gpu_intent` at `/gpu/intent`.
- `recognition/interface_adapters/http/routers/clusters_admission.py` and
  `cluster_revert.py`: mutation/compute cluster route surfaces, including
  `/clusters/recover-orphans` and `/clusters/{cluster_id}/revert-merge`.
- `scripts/eval_harness/gate_contract.py`: `GateContract`, `GateContract.__post_init__`,
  and `load_gate_contract`; `scripts/eval_harness/tests/test_eval_exit_contract.py`:
  the shared exit-code contract.

The supplied feature commit IDs `1a3f51fe4` and `8f12a1e8` are not resolvable in this
worktree, so this assessment treats the current tree and the supplied conclusions as
the source of truth rather than claiming those commits were inspected.

## Findings and implementation contracts

### F1. Identity must distinguish retries from intentional resubmissions

**Current risk.** `UsageReservation` currently keys uniqueness by
`(tenant_id, idempotency_key)`, while `UsageTicket` has no operation or request
fingerprint. `/describe/multipart` passes `submission.operation_id` through
`_accept_operation`, and `/describe/run` has an optional `idempotency_key` and
`request_digest`, but `enqueue_describe_image` creates a `create_single_run` job
without binding that operation identity. A client that times out after a 202 can
therefore retry the async path and create another job or charge at a different
layer.

**Contract to implement.** Define the compute identity as
`(tenant_id, operation_id, request_fingerprint)`, with `operation_id` explicit on
all three compute submissions: `/describe/multipart`, `/describe/async`, and
`/describe/run`. The fingerprint must be canonical and include the normalized route
mode, media identifiers and bytes/digests, context, recognition/tier options, and
any other input that changes work. Store it with the reservation and job binding.

- Same tenant + operation ID + same fingerprint: return the existing reservation
  and job; do not charge or dispatch another job.
- Same tenant + operation ID + different fingerprint: return a deterministic 409;
  do not charge and do not create a job.
- Same payload with a new operation ID: treat it as an intentional resubmission and
  reserve/charge it independently.
- Operation IDs are tenant-scoped; a value from another tenant cannot replay or
  inspect a reservation.

Extend `UsageTicket` and `UsageAdmissionService.reserve` so the returned ticket
contains the operation/fingerprint and durable job binding. Preserve the existing
unique database guard as a last line of defense, but make the service's collision
path read the winner and verify the fingerprint rather than blindly retrying.

**Failure scenario.** The caller receives `202 Accepted` from
`enqueue_describe_image`, loses the response, and retries the same logical request.
The second call has no durable operation key in `create_single_run`; it can enqueue
and meter a second single-run job. Conversely, treating every equal payload as a
replay would make a user-requested second run free. The operation ID is the required
boundary between those cases.

**Acceptance assertions.**

- `scene/tests/test_describe_run_idempotency.py` and the async/multipart route tests
  prove concurrent same-operation requests converge on one job and one reservation.
- A same-operation/different-fingerprint request is 409 with zero new reservation
  rows; a new operation ID creates a second reservation even for an equal payload.
- A tenant A operation ID cannot return, mutate, or reuse tenant B's reservation.
- The assertions exercise both a response-loss retry and a database uniqueness race,
  not only a sequential happy path.

### F2. Reserve before dispatch and settle only at a worker terminal outcome

**Current risk.** `create_describe_run` inserts and commits a run, then calls
`maybe_consume_demo_quota`; `enqueue_describe_image` consumes quota before
`_ASYNC_ADMISSION.try_acquire`; `describe_image_multipart` consumes in
`_before_compute`. The in-memory admission gate and the durable demo quota are not a
single reservation, and `_run_async_describe_job_and_release` releases only the
process-local image-byte/job counter. The run repository's `create_run`/
`create_single_run` records do not persist a `UsageReservation` binding.

**Contract to implement.** Use one transactionally durable `reserve` operation before
queue admission, background dispatch, or remote/GPU work. The reservation must carry
a non-null binding to the job/run identity (generate the job ID before reservation,
or bind both rows in one transaction). Dispatch is allowed only after that
transaction commits. The worker, not the HTTP handler, owns terminal settlement:

| Worker outcome | Required reservation settlement |
| --- | --- |
| Successful terminal result | `committed`, once |
| Worker failure after pickup/compute began | `committed`, once, because work was attempted |
| Cancellation before pickup/compute | `released`, once |
| Cancellation after pickup/compute | `committed`, once, unless a separately ratified refund policy says otherwise |
| Reclaim after restart with no work performed | `released` or `expired`, according to the persisted reclaim state; never left `reserved` |

Use a fenced, idempotent settlement keyed by reservation/job ID so a retrying worker
or a duplicate terminal callback cannot settle twice. Persist the reservation state
with the same tenant scope as the job. `DescribeRunRepository` terminal transitions,
`run_describe_job`, `_run_async_describe_job_and_release`, and the recognition worker
terminal handlers must all reach that settlement edge.

The response from `create_describe_run` and `enqueue_describe_image` may remain 202
with a pending result, but 202 must not call `commit`. Free polling routes may read
the result without changing reservation state; `cancel_describe_run` must request
cancel and drive the same terminal settlement path.

**Failure scenario.** `/describe/async` charges demo quota, then
`_ASYNC_ADMISSION.try_acquire` returns “queue is full”; or the process dies after
the HTTP 202 and before its background task starts. The caller is charged without a
job attempt and no worker can settle the charge. The inverse failure—worker success
without a committed reservation—also makes billing and allowance disagree.

**Acceptance assertions.**

- A reservation row and its job binding exist before dispatch is observable.
- Queue rejection, process restart before pickup, worker success, worker failure,
  and cancellation each produce exactly one terminal reservation state.
- HTTP 202, result reads, and status polling never mark usage committed.
- A duplicate worker/retry callback is a no-op after the first fenced settlement;
  a stale worker cannot settle a newer retry's reservation.

### F3. The route matrix must be explicit, including operator surfaces

**Contract to implement.** Maintain a route census that maps every compute-capable
entry point to the common admission service. The initial APP-1 census is:

| Surface | Current symbol/path | Beta contract |
| --- | --- | --- |
| Synchronous/multipart compute | `describe_image_multipart` — `POST /describe/multipart` | Reserve before real compute; cache/decorative zero-compute paths remain uncharged. |
| Async single compute | `enqueue_describe_image` — `POST /describe/async` | Reserve before bounded-queue admission and persist the operation/job binding. |
| Bulk/run compute | `create_describe_run` — `POST /describe/run` | Reserve before background dispatch; idempotency and fingerprint rules from F1 apply. |
| Bulk result reads | `get_describe_run` — `GET /describe/run/{run_id}` and `list_describe_run_items` — `GET /describe/run/{run_id}/items` | Free, tenant-scoped reads; no reservation mutation. |
| Async result read | `get_describe_job` — `GET /describe/jobs/{job_id}` | Free polling; terminal observation does not charge. |
| Cancellation | `cancel_describe_run` — `DELETE /describe/run/{run_id}` | No new charge; settle the bound reservation through F2. |
| GPU lifecycle read | `get_gpu_status` — `GET /gpu/status` | Free operator status polling. |
| GPU lifecycle mutation | `post_gpu_intent` — `POST /gpu/intent` | Operator-only; either use the common admission policy if it starts billable work or reject beta explicitly before writing intent. |
| Cluster mutation/compute | `recognition/interface_adapters/http/routers/clusters_admission.py` route handlers, including `POST /clusters/recover-orphans`; `revert_merge_cluster` — `POST /clusters/{cluster_id}/revert-merge` | Every route that starts clustering/recompute must be admitted, or beta must return an explicit deny before work. Read-only cluster projections are not compute admission. |

The route-level `maybe_consume_demo_quota` calls are not a substitute for this
matrix: they skip when the session is unavailable, apply only to demo registry keys,
and do not bind a reservation to the worker job. Any future alias must be added to the
census test before beta is enabled.

**Failure scenario.** A request uses `/describe/async` or an operator cluster route
that bypasses the portal reservation while `/describe/multipart` is metered. The
tenant allowance and global in-flight budget then describe only one ingress family.
Alternatively, a supposedly free `/describe/jobs/{job_id}` poll accidentally shares
the compute dependency and charges on every status refresh.

**Acceptance assertions.**

- Route-census tests enumerate the three scene compute POSTs, all operator cluster
  mutation/compute routes, and `/gpu/intent`; each is either wired to common
  admission or has a stable beta-denied response before any side effect.
- `/gpu/status`, `/describe/jobs/{job_id}`, `/describe/run/{run_id}`, and
  `/describe/run/{run_id}/items` remain free and tenant-scoped under repeated polling.
- Decorative/cache-hit branches prove no reservation is created when no costly work
  runs; a real compute branch proves exactly one reservation.

### F4. Global limits and queue state must be atomic and fail closed

**Current risk.** `AsyncAdmissionGate`/`_ASYNC_ADMISSION` uses a process-local lock,
environment-derived defaults, and counters reset on process restart. It tracks pending
jobs and retained image bytes but not a PostgreSQL-global daily cost, global in-flight
cost, or persisted stop/fencing epoch. `UsageReservation` tracks tenant period and
`cost_units` only. `maybe_consume_demo_quota` explicitly returns without enforcement
when its session is unavailable. Those paths permit per-process oversubscription and
turn absent enforcement state into a successful request.

**Contract to implement.** Add a durable global admission state keyed by the UTC
period/limit version, with at least daily cost reserved/settled, in-flight units,
queue count/byte bounds, stop-requested state, and a fencing epoch. In one PostgreSQL
transaction, lock or otherwise serialize the tenant allowance row and the global
state row, validate all limits, then insert the reservation and increment the global
counters. Settlement decrements/releases the corresponding counters exactly once.
The process-local `AsyncAdmissionGate` may remain a fast backpressure hint, but it is
not authoritative and must never be the only bound.

At startup, the API enforcement dependency and `ScanWorker` startup/loop must reject
compute when required limit rows, configuration, database connectivity, or the
fencing/stop state are absent. On restart, reconcile persisted non-terminal jobs and
reservations before accepting new work; do not reset counters to zero. A stop request
must prevent new reservations while allowing the terminal settlement of admitted
work.

Relevant amendment points are `scene/interface_adapters/http/routers/describe.py`
(`AsyncAdmissionGate`, `_async_admission_gate`, `_ASYNC_ADMISSION`, `_stop_requested`),
`recognition/interface_adapters/http/deps/demo_quota.py` (`maybe_consume_demo_quota`),
`recognition/worker/scan_worker.py` (`ScanWorker.__aenter__`, `run_forever`, and job
claim/terminal methods), `db/models/portal_billing.py`, and
`db/migrations/versions/001_identity_schema.py`.

**Failure scenario.** Two API processes each observe an empty local gate and accept
work beyond the global daily cost or in-flight limit. A restart clears the counters
while the old jobs still execute. If the database session is missing,
`maybe_consume_demo_quota` skips and the route can continue instead of refusing beta.

**Acceptance assertions.**

- A real PostgreSQL race with concurrent reservations proves tenant and global caps
  are not oversubscribed; SQLite-only tests do not satisfy this assertion.
- Daily cost, in-flight, queue, and stop-state counters remain correct after an API
  or worker restart and after duplicate settlement/reclaim attempts.
- Missing limits, missing fencing state, unavailable persistence, and startup
  reconciliation failure return a stable 503/refusal and start no compute.
- The declared global limit is enforced across processes, not merely by
  `_ASYNC_ADMISSION` in one interpreter.

### F5. Evaluation must be complete, evidence-backed, and never green on skips

**Current risk.** `GateContract`/`load_gate_contract` structurally validate the
existing contract fields, while `test_eval_exit_contract.py` verifies shared numeric
exit codes and wrapper wiring. Neither fact by itself proves that every APP-1 case
was executed, that PostgreSQL race/restart evidence exists, or that a skipped case
cannot produce a clean result.

**Contract to implement.** Extend the evaluator contract loaded by
`load_gate_contract` and validated by `GateContract.__post_init__` with a non-empty,
versioned declaration of required cases and required evidence artifacts. The run
ledger must record each declaration as `passed`, `failed`, `skipped`, or `not_run`,
with command, environment/database identity, commit, and artifact digest. The
evaluator must refuse or return a non-clean exit for any missing declaration,
`skipped`/`not_run` case, missing artifact, or evidence that claims PostgreSQL while
running on SQLite. The report must make the missing item visible; it must not silently
drop it.

The required APP-1 evidence set includes, at minimum, genuine PostgreSQL concurrent
reservation/race evidence, PostgreSQL restart/reclaim evidence, route-census
coverage, retry-versus-resubmission behavior, terminal settlement behavior, and
missing-limit fail-closed behavior. A clean result is permitted only when every
declared case and artifact is present and passes. Keep the shared exit contract in
`scripts/eval_harness/tests/test_eval_exit_contract.py`; add discrimination tests for
missing, skipped, and SQLite-substituted evidence.

**Failure scenario.** A structurally valid gate is loaded and unit tests pass, but a
PostgreSQL race test was skipped because no database was available. The harness emits
the same green status as a complete run, allowing an unverified release objective to
pass. Conversely, a report that omits the skipped case hides the missing evidence.

**Acceptance assertions.**

- Removing any declared required case or evidence artifact makes the evaluator
  non-clean and identifies the missing item.
- Marking a required case `skipped` or `not_run` cannot yield exit code 0.
- PostgreSQL race and restart artifacts contain verifiable database/runtime identity,
  scenario result, and provenance digest; a SQLite run cannot satisfy those fields.
- A complete, all-green run is the only input accepted as release-ready; no-green-on-
  skips is tested as a negative contract.

## Path-disjoint implementation groups and required edges

The groups below are path-disjoint ownership areas. Cross-group behavior is expressed
as explicit edges rather than an invitation to perform a broad repository tour.

| Group | Owned paths/symbols | Required edge |
| --- | --- | --- |
| Identity and ledger | `recognition/domain/portal_contracts.py` (`UsageAdmissionService`, `UsageTicket`); `db/models/portal_billing.py` (`UsageReservation`, `TenantEntitlement`); the usage migration in `db/migrations/versions/001_identity_schema.py` | normalized tenant/operation/fingerprint → one reservation row |
| Scene admission | `scene/interface_adapters/http/routers/describe.py` (`_accept_operation`, three compute handlers); `scene/interface_adapters/http/routers/describe_run.py` (run handler and idempotency helpers) | route payload → canonical fingerprint → reserve before dispatch |
| Worker lifecycle | `scene/application/describe_run_repository.py`; `scene/application/describe_run_worker.py`; `recognition/worker/scan_worker.py` | reservation/job binding → pickup fence → terminal outcome → settlement |
| Operator surfaces | `scene/interface_adapters/http/routers/gpu.py`; `recognition/interface_adapters/http/routers/clusters_admission.py`; `recognition/interface_adapters/http/routers/cluster_revert.py` | operator compute route → common admission or explicit beta deny; status route → no charge |
| Evaluation | `scripts/eval_harness/gate_contract.py`; its evaluator/exit-contract tests and report wrapper | declared case/evidence → executed ledger → non-clean on missing/skip |

Required edges, in order:

1. `tenant_id + operation_id + request_fingerprint` must be resolved before any
   costly read, queue slot, provider call, or job dispatch.
2. A successful reservation transaction must persist the job binding before dispatch;
   a reservation collision must replay only the fingerprint-matching winner.
3. The worker pickup fence must be durable and must lead every success, failure,
   cancellation, and restart-reclaim path to one idempotent settlement.
4. Every compute/operator mutation route must reach admission or a beta-denied
   branch; status/polling routes must not reach admission.
5. Tenant allowance, global daily/in-flight state, queue/stop state, and fencing must
   be checked/updated atomically, and absent state must stop startup/enforcement.
6. The evaluator must join each declared case to its result and evidence digest before
   choosing a clean exit.

## Evidence and citation status

The supplied prior-art references remain useful design constraints: APP1 decisions
12900, 13218, and 13223; W4USAG findings 15849–15856 and existing finding 15497;
DDIA transactions/fencing/idempotent sinks; Release It! timeouts/bulkheads; GRPH09
disjoint ownership; GRPH31 critical path; PERF11 verified-release objective; and
PERF13 headroom. Their full source records or MCP embedding payloads are not present
in this lane, and no external retrieval or tool installation was performed. They are
therefore marked **source unavailable locally**, not cited as independently verified
evidence.

The local source anchors listed in the bounded review basis are implementation
locations, not proof that the contracts are already satisfied. The focused portal
contract test proves frozen boundary dataclasses, runtime protocols, fail-safe default
entitlement, and database enum/positive-cost checks; it does not prove the five
adjudicated findings. Plan0002 P02/P05 should not be marked complete until the
acceptance assertions and required PostgreSQL evidence above are recorded.
