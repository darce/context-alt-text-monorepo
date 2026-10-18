# SUITERED-1-F-02: aiosqlite worker-thread hang root cause

## Executive conclusion

The primary defect is a same-session self-deadlock in the SQLite fallback of
`ScanService`'s per-media persistence lock.  It is not a SQLite query that is
stuck in the aiosqlite worker.  The first `process_media_item()` call flushes
work but deliberately keeps the non-PostgreSQL `asyncio.Lock` until the root
transaction ends.  Each affected test calls `process_media_item()` a second
time for the same `(tenant_id, media_id)` before committing.  The second call
waits forever on the same non-reentrant lock.

The aiosqlite worker thread seen in the dump is an important symptom but not
the owner of the deadlock: after the first flush, no second SQL operation has
been queued.  The worker is idle in `SimpleQueue.get()` while the event loop
is idle in `select()` waiting for the coroutine whose `asyncio.Lock.acquire()`
can never complete.  This is a Python-level await, not a C-level SQLite call;
the configured signal timeout can therefore bound it, but the timeout only
reports the symptom.

## 1. Mechanism

The relevant interleaving is:

1. The `db_session` fixture creates `sqlite+aiosqlite:///:memory:` with
   `poolclass=StaticPool` (`recognition/tests/conftest.py:70-77`).  StaticPool
   means one SQLAlchemy connection is shared, and that connection has one
   aiosqlite worker thread.  The fixture starts a nested transaction at
   `conftest.py:131-133` and installs a restart listener at `conftest.py:135-138`.
2. `ScanService.process_media_item()` reaches `_persist_identities()` at
   `recognition/application/scan/service.py:469-519` and enters
   `_media_persist_lock()` at `service.py:554-573`.
3. SQLite is not PostgreSQL, so `_media_persist_lock()` takes the process-local
   path (`service.py:73-81`, `service.py:124-134`).  The registry is keyed only
   by `(tenant UUID, media ID)` (`service.py:84-96`), and the first call owns
   the resulting `asyncio.Lock`.
4. The first call performs its SELECT and flush (`service.py:583-589` and
   `service.py:697-702`).  `process_media_item()` is explicitly flush-only;
   its docstring says the handler owns the durable commit
   (`service.py:489-492`).  On leaving `_media_persist_lock()`, the fallback
   registers a root-transaction release listener (`service.py:172-175`) and
   observes that the session transaction is still open
   (`service.py:177-184`).  Consequently it does not release the lock.
5. The second call with the same key enters the same registry entry and awaits
   `lock.acquire()` at `service.py:132-136`.  `asyncio.Lock` is not reentrant,
   so the same coroutine/task waits for a release that can only happen when
   the root transaction ends.  That transaction cannot end because the test
   is waiting inside the second call.

The savepoint listener is a participant in the transaction shape, not the
primary waiter.  Its `begin_nested()` restart at `conftest.py:135-138` keeps a
nested savepoint available after nested transaction end; it does not release
the root transaction.  The lock's own `_release()` also ignores child
transactions (`service.py:150-159`) and releases only at the root boundary.
Thus the savepoint loop makes the intended "hold until commit" lifetime
visible, but the deadlock is the non-reentrant process-local lock.  Removing
the listener alone would not be a sound fix while the service remains
flush-only and the root transaction remains open.

StaticPool is also not the direct waiter for this trace.  It selects the
SQLite fallback and gives all operations one aiosqlite worker, which makes the
thread dump look like a connection hang.  The worker is actually waiting for
another queue item (`aiosqlite/core.py:59`); the blocked coroutine is waiting
on the process-local lock before it can enqueue one.  This distinction matters
because changing `:memory:` to a file URL while retaining SQLite and the same
lock code still takes `_media_persist_lock()`'s non-PostgreSQL branch.

The stack classification is therefore Python-level:

* worker: `aiosqlite._connection_worker_thread` waiting on its queue;
* event loop: `selectors.select()` / `asyncio._run_once()`;
* suspended test coroutine: `asyncio.Lock.acquire()` in the fallback lock.

It is not a blocked `sqlite3` C call.  The existing `timeout_method=signal`
bound should be able to interrupt this class of wait; the 240-second
faulthandler dump is observation, and the 300-second pytest timeout is only a
bound on the symptom.

## 2. Why the reported test varies

The vulnerable interleaving is deterministic once one of these tests reaches
its second same-key call.  The apparent variation is at the suite/xdist level:
the three tests are independently vulnerable, and worker scheduling determines
which worker reaches a second call first and is the one whose nodeid appears
to wedge.  A run stopped at the first blocked worker may never reach the other
two.  A transaction boundary introduced by a caller, fixture teardown, or an
exception/rollback can release the lock and let a particular run pass, which
also makes the symptom load-sensitive.

This mechanism does **not** predict that a fixed, serial invocation of one
isolated test will randomly alternate between different outcomes: that would
be evidence against the lock diagnosis.  The cross-run variation described in
the gate evidence is explained by scheduling and which vulnerable test is
observed first, not by nondeterministic execution inside SQLite.

## 3. Why these three tests

All three tests make two persistence calls on the same `db_session` and the
same media key without a commit between them:

* `test_factor_update_branch_round_trip` calls media `4444` first at
  `recognition/tests/integration/test_factor_round_trip.py:162-166`, then
  creates a second `ScanService` and calls media `4444` again at
  `:176-185`.  The detector's same bbox is intended to exercise the update
  branch, but the second call blocks before matching code runs.
* `test_scan_service_same_bbox_replay_reuses_existing_media_identity_row`
  calls media `123` at
  `recognition/tests/integration/test_scan_service_pose_quality.py:93-97`
  and again at `:105-109`.  The intervening SELECT at `:99-103` is read-only
  and does not commit the transaction.
* `test_scan_service_low_iou_replay_replaces_media_identity_row` calls media
  `123` at `:126-130` and again at `:138-142`, also without a commit.  The
  changed bbox affects the intended reconcile branch only after the lock is
  acquired.

The other tests in these files make one persistence call: the pose test uses
`:66-70`, `test_factor_round_trip_via_scan_and_repository` uses
`test_factor_round_trip.py:83-87`, and the InsightFace-null test uses
`:124-128`.  They therefore leave the lock held until fixture teardown but do
not attempt the second acquisition during the test.  The detector choice,
factor columns, and IoU branch are not the cause; the repeated same-key call
is the distinguishing operation.

## 4. Minimal reproducer

The smallest in-repository reproducer is the existing same-bbox test reduced
to the two calls and a bounded wait:

```python
@pytest.mark.asyncio
async def test_same_sqlite_transaction_can_rescan_one_media_item(db_session, tenant):
    service = ScanService(
        session=db_session,
        detector=PoseDetector(),
        generator=StubEmbeddingGenerator(embedding_dim=512),
    )
    await service.process_media_item(
        tenant_id=str(tenant.id),
        media_id=123,
        media_url="http://example.test/image.jpg",
    )
    await asyncio.wait_for(
        service.process_media_item(
            tenant_id=str(tenant.id),
            media_id=123,
            media_url="http://example.test/image.jpg",
        ),
        timeout=1.0,
    )
```

No reproducer file was added because this lane owns only the report.  The
source-level interleaving above is sufficient to predict the timeout.  A
bounded attempt to run the existing target test in this sandbox did not reach
the test body: the fixture setup stalled while opening aiosqlite, and a
separate inline `aiosqlite.connect(":memory:")` probe stalled immediately
after printing its pre-connect marker.  The target attempt did produce the
reported shape at the observation layer (worker at `aiosqlite/core.py:59`,
event loop in `select()`), but because this sandbox cannot establish an
aiosqlite connection, it is not claimed as a clean end-to-end reproduction.
The gate/macOS executions and the source interleaving are the evidence for the
defect; this sandbox limitation is recorded rather than conflated with a
passing or failing test result.

## 5. Remediation, ranked

### 1. Make the SQLite fallback transaction-owner aware and reentrant

Keep the cross-session serialization guarantee, but record the owning
SQLAlchemy sync session/root transaction and a re-entry depth in the registry
entry.  A second call from that same session and root transaction should reuse
the ownership instead of awaiting its own `asyncio.Lock`; only the root
transaction-end callback should release the underlying lock and clear the
ownership/depth.  A different session must still wait.  Cancellation before
ownership, cancellation while waiting, rollback, and listener removal need
balanced bookkeeping.

This is the minimal production-safe code change because it preserves the
flush-only transaction contract and the reason the lock is held until commit.
Cost: moderate application-lock bookkeeping and focused cancellation/rollback
tests.  Residual risk: an `AsyncSession` is not generally safe for concurrent
tasks, so owner identity must not accidentally let an unrelated task sharing
one session bypass the lock; this also does not address the separate
`:memory:` connection-invalidation failure.

**Proof test:** add one bounded test that performs two sequential
`process_media_item()` calls for the same `(tenant, media)` on one SQLite
`db_session`, asserts the second call completes, and checks the intended UUID
reuse/update result.

### 2. Put a transaction boundary between the two test/worker operations

For tests that model separate worker-handler invocations, commit (or close and
open a new session) after the first `process_media_item()` call.  That matches
the service's documented handler-owned commit boundary and releases the lock
before the second invocation.  Cost: low fixture/test churn.  Residual risk:
this is a test/workflow workaround, not a general application fix; any caller
that legitimately performs two same-key flush-only calls in one transaction
can still deadlock.

**Proof test:** run the two-call replay scenario with an explicit
`await db_session.commit()` between calls and a one-second wait around the
second call; it should complete and retain the expected row semantics.

### 3. Apply the prior task's file-backed + StaticPool fixture hardening, but
only as a companion change

The prior MAINT-GATE-FLAKES evidence remains valid for a different failure:
`:memory:` plus StaticPool lets cancellation/invalidation destroy the only
database and its schema; file backing preserves the schema, while StaticPool
avoids introducing a second SQLite writer and the observed `database is
locked` race.  The savepoint loop does not change that conclusion for
connection invalidation.

It is **not sufficient for SUITERED-1-F-02 by itself**.  File-backed
`StaticPool` is still a non-PostgreSQL engine, so the second same-key call still
enters the same fallback lock and waits until root commit.  Pair this fixture
hardening with remediation 1 if the suite must also be resilient to cancelled
aiosqlite operations.  Cost: temporary-file lifecycle and cleanup, plus
additional cancellation coverage.  Residual risk: the previously recorded
unknown remains whether an invalidated cancelled connection releases the file
lock before replacement writes; that must be measured rather than assumed.

**Proof test:** use the file-backed `StaticPool` fixture to cancel an in-flight
SQLite operation, then assert that a subsequent schema query and write
complete.  A two-call, no-commit replay test is deliberately not the proof for
this option: it should still expose the fallback-lock deadlock unless option 1
is also present.

Replacing StaticPool with a pooled multi-connection SQLite engine alone is
also not a fix for this report: it leaves the same non-PostgreSQL process lock
in place and reintroduces the prior `database is locked` risk under writes.
Removing only the savepoint-restart listener is likewise insufficient unless
the transaction model is changed so the root transaction actually ends between
same-key operations.

## 6. What would falsify this answer

Instrument the second `_media_persist_lock()` entry and show that it passes
`service.py:134` (the lock is acquired), while the coroutine then blocks in an
`AsyncSession.execute()`/`flush()` with a pending aiosqlite future or a
`sqlite3` C stack; that would falsify the self-deadlock diagnosis and point to
the StaticPool/savepoint or cancellation path instead.  Likewise, if an
isolated single-call test hangs reproducibly, or if an explicit commit between
the two same-key calls still hangs at the same location, this report is wrong.
Conversely, observing that a file-backed StaticPool fixture still blocks on
the no-commit two-call reproducer would confirm that file backing is an
orthogonal cancellation/schema fix, not a remediation for this lock.
