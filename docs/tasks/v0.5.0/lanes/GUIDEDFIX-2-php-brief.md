# GUIDEDFIX-2 lane `guidedfix-2-php`: honour the idempotency key on admin describe-run submit

Branch `feature/guidedfix-2-php` @ `ed48d331ffff19af12739ea4e76b93df23c2a089`.
Findings id range if you must record a blocker: `GUIDEDFIX-2-PHP-01` .. `GUIDEDFIX-2-PHP-09`. Do not reuse other ids.
Owned paths: `apps/prototype-wp-alt-context/src/api/class-describe-controller.php` and
`apps/prototype-wp-alt-context/tests/Unit/**` only. Do not touch `js/**`, the description service, or
`class-public-demo-describe-controller.php`.

## The defect (coordinator-verified against the tree)

`class-describe-controller.php:360-419` (`submit_describe_run`) accepts a request that may carry an `idempotency_key`
parameter and **never reads it**. `grep -n idempotency class-describe-controller.php` returns nothing. The multipart body
built at lines 377-381 forwards `tenant_id`, `media_ids`, `recognition_enabled` and image parts — the key is dropped on
the floor.

Two consequences:

1. `class-public-demo-describe-controller.php:226` does `$pipeline_request->set_param('idempotency_key', ...)` and then
   calls this method believing its defence-in-depth second layer is live. It is inert. The code lies about its own
   guarantees — CARD-07 fail-loudly-succeed-quietly: a parameter that is accepted and silently ignored is the worst of
   both.
2. The admin guided panel (`POST /acx/v1/recognition/describe/runs`) has **no** dedupe at all. A lost 202 + browser
   retry = two GPU runs, two charges. Canon: [RES-01] retry without idempotency (DDIA ch-8); [API-02] non-idempotent
   POST needs a client token; [FLOW-05] at-least-once requires an idempotent consumer; [COST-10].

## Wire contract (pinned by the coordinator — do not rename)

Inbound REST param `idempotency_key`: optional string, 16..128 chars, charset `[A-Za-z0-9_-]`. Present-but-invalid → 400
`WP_Error` code `invalid_idempotency_key` naming the constraint. Absent → forward nothing (server treats absent as
no-dedupe; that is unchanged behaviour and stays legal).

Outbound to the backend: multipart form field `idempotency_key`, the validated string, added to `$multipart_body`
alongside `tenant_id`. The scene backend (sibling lane) dedupes on `(tenant_id, idempotency_key)` and returns the same
`run_id` with 202 on replay, 409 on key/media mismatch.

Pass-through: the backend's `DescribeRunResponse` now carries `deadline_seconds: float|null`. `submit_describe_run` and
the run-status proxy must let that field through the envelope unchanged. If any allow-list or envelope normaliser in this
file strips unknown fields, add `deadline_seconds` to it; if nothing strips, add a test proving the field survives.

## Required semantics

- Validate at the boundary with explicit checks and `WP_Error` — not assertions.
- The 409 from the backend must surface to the caller as a 409 with a stable error code, not be laundered into a generic
  502. Check how `proxy_recognition_request` maps upstream statuses and make sure 409 is preserved.
- `store_run_media_ids( $run_id, $media_ids )` at line 407 must remain safe on a replayed 202: the backend returns the
  same `run_id`, so the second write must be idempotent (same key, same value → no error, no duplicate). Read it before
  you decide; if it is already upsert-shaped, add the test that proves it; if not, make it so.
- Read `class-public-demo-describe-controller.php:149-284` (read-only) first. It is the correct idiom for this problem
  one layer up. You are **not** re-implementing its transient reservation here — the durable dedupe now lives in the
  backend — you are making this method an honest conduit for the key it already receives.

## Test obligations (acceptance bar — failing-first, [TEST-06]/[TEST-15])

New `tests/Unit/DescribeRunIdempotencyTest.php` (extend an existing describe-controller test class if one already
covers `submit_describe_run` — check `tests/Unit/` first; do not create a parallel harness):
- valid key present → the multipart body handed to the proxy seam contains `idempotency_key` with that exact value
- key absent → the multipart body has no `idempotency_key` entry
- key 15 chars / 129 chars / contains `.` → 400 `invalid_idempotency_key`, proxy seam never called
- backend replies 409 → caller receives 409 with the backend's error code, `store_run_media_ids` not called
- backend replies 202 twice with the same `run_id` (simulated replay) → `store_run_media_ids` tolerates the second write
- backend 202 carries `deadline_seconds: 180.0` → the WP response data still contains `deadline_seconds => 180.0`

Mutation check you must run before committing: delete the line that adds `idempotency_key` to `$multipart_body` → the
first test must go red. State that you ran it.

Existing tests stay green. `PublicDemoDescribeControllerTest.php` is untouched. Never weaken or delete a test.

## Commit

One commit, subject `guidedfix-2(php): honour the idempotency key on admin describe-run submit`. No attribution trailers.
Lane test command: `composer -d apps/prototype-wp-alt-context test`. Report the pass count.
