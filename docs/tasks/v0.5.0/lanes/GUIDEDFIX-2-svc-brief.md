# GUIDEDFIX-2 lane `guidedfix-2-svc`: idempotent describe-run accept + disclosed deadline

Branch `feature/guidedfix-2-svc` @ `ed48d331ffff19af12739ea4e76b93df23c2a089`.
Findings id range if you must record a blocker: `GUIDEDFIX-2-SVC-01` .. `GUIDEDFIX-2-SVC-09`. Do not reuse other ids.
Owned paths: `apps/prototype-description-service/scene/**` only. Do not touch `recognition/**` or the WP plugin.

## Two verified defects (coordinator-verified against the tree, not hypotheses)

### A. `POST /scene/describe/run` is not idempotent — a lost 202 + blind retry double-executes a paid GPU run

`scene/interface_adapters/http/routers/describe_run.py:269-330` (`create_describe_run`) reads `tenant_id`, `media_ids`,
`recognition_enabled`, and image parts from the multipart form and unconditionally creates a new run. Nothing keys the
accept on a caller-supplied token, so if the 202 is lost in transit (WP timeout, proxy reset, worker death) the caller's
retry spends a second run. Canon: [RES-01] retry without idempotency double-applies (DDIA ch-8); [API-02] non-idempotent
POST needs a client token; [FLOW-05] at-least-once delivery must be paired with an idempotent consumer; [COST-10] paid
work must not be spendable twice by a network fault.

The WP layer already computes and *tries* to pass this token — `class-public-demo-describe-controller.php:226` sets
`idempotency_key` on the request it forwards — and the WP describe controller is being fixed in a sibling lane to forward
it as multipart form field `idempotency_key`. Your job is the server half.

### B. The server never discloses its own generation budget, so the client guesses

`scene/config/settings.py:66-67` — `DescriptionSettings.generation_timeout_seconds` (default 180, env
`ACX_DESCRIPTION_TIMEOUT_SECONDS`) is the real bound on how long a run can take. `DescribeRunResponse`
(`scene/interface_adapters/http/schemas/responses.py:156-176`) does not carry it. The guided client therefore waits on a
locally invented ceiling (510 s cold / 180 s warm) and cannot know when the server has already given up. Canon: [RES-02]
the bound on a wait must be disclosed by the party that enforces it (Release It! ch-5); [PERF-09] a client cannot beat a
server budget it cannot see; CARD-09 feedback-bounded-waiting.

## Wire contract (pinned by the coordinator — do not rename these fields)

Inbound multipart form field: `idempotency_key` — optional string, 16..128 chars, charset `[A-Za-z0-9_-]`. Anything else
present-but-invalid → 422 naming the field. Absent → today's behaviour (no dedupe), unchanged.

Outbound `DescribeRunResponse` gains exactly one field:

```
deadline_seconds: float | None = None
```

Populated on the submit 202 and on every subsequent GET status with the value of
`DescriptionSettings().generation_timeout_seconds` that was in force when the run was accepted (persist it with the run;
do not re-read settings on each poll — the client must see one stable number for one run). `extra="forbid"` stays.

## Required semantics for A

1. Dedupe scope is `(tenant_id, idempotency_key)`. Same tenant, same key → return the existing run's current
   `DescribeRunResponse` with status 202 (**not** 200 — the client must not be able to distinguish a replay from a first
   accept). Do no new work: no image reads, no worker enqueue, no background task.
2. Same tenant, same key, **different `media_ids`** → 409 with a body that names the conflict. Mirror the public demo's
   `IDEMPOTENCY_CONFLICT` semantics.
3. The reservation must be atomic with run creation. Do not check-then-insert across two statements without a unique
   constraint backing it — two concurrent retries must produce one run, not two. Use a unique index on
   `(tenant_id, idempotency_key)` (nullable key; NULLs distinct) in the existing schema module — greenfield policy, no
   migration file — and let the constraint violation be the dedupe signal on the race. Look at how
   `scene/application/describe_run_repository.py` persists runs today and extend that path.
4. Keys are not immortal: they expire with the run's retention. Do not add a second TTL mechanism.
5. Read `apps/prototype-wp-alt-context/src/api/class-public-demo-describe-controller.php:149-284` (read-only) before
   designing. It is the proven idiom for the same problem one layer up: reserve-before-dispatch, fail closed on
   uncertainty, conflict on key/media mismatch. Match its shape; do not invent a different one.

## Required semantics for B

- Add `deadline_seconds` to the domain run record (`scene/domain/describe_run.py`) and to persistence, populated at accept.
- Every response builder that emits `DescribeRunResponse` populates it from the stored value.
- `None` is only legal for runs persisted before this change — there are none (greenfield), so a test may assert it is
  always a positive float on any run created through the route.

## Test obligations (acceptance bar — failing-first, [TEST-06]/[TEST-15])

New file `scene/tests/test_describe_run_idempotency.py`:
- replay with same key returns 202, same `run_id`, and the worker/enqueue seam is invoked exactly once
- same key + different media_ids → 409
- same key + different tenant → two distinct runs
- malformed key (too short, bad charset) → 422 naming `idempotency_key`
- concurrent race: two coroutines submit the same key simultaneously against the real session; exactly one run row exists
  after both settle, both responses carry that run_id

New file `scene/tests/test_describe_run_deadline.py`:
- submit 202 carries `deadline_seconds == DescriptionSettings().generation_timeout_seconds`
- GET status for the same run carries the identical value even after the env var is changed mid-test
  (monkeypatch `ACX_DESCRIPTION_TIMEOUT_SECONDS` between submit and poll)

Mutation checks you must run yourself before committing: delete the unique constraint → the race test must go red;
remove the `deadline_seconds` persistence → the mid-test env-change test must go red. State in your report which
mutation you ran and what failed.

Existing `scene/tests/test_describe_run_routes.py` must stay green, untouched except where a fixture needs the new
field. Never weaken or delete a test.

## Commit

One commit, subject `guidedfix-2(svc): idempotent describe-run accept and disclosed deadline`. No attribution trailers.
Lane test command: `python -m pytest apps/prototype-description-service/scene/tests -q`. Report the pass count.
