# E15-12 Slice 3 — Reset Smoke Proofs

Captured per [`docs/operations/reset-smoke-runbook.md`](../../operations/reset-smoke-runbook.md).
Each entry is the post-reset, plugin-connectivity smoke that closes the
matching Slice 3 checklist item in
[`E15-12-standard-deployment-reset-and-recognition-source-task-plan.md`](./E15-12-standard-deployment-reset-and-recognition-source-task-plan.md).

---

## Local-mode smoke (after `make reset-local`)

- **Date**: 2026-05-02
- **Operator**: daniel
- **Reset command**: `make reset-local WP_PATH="$HOME/Development/wp-context-alt-text/app/public" CONFIRM_LOCAL_RESET=RESET`
- **Service HEAD at smoke time**: `97643826` (root `main`; running uvicorn was restarted from the root worktree after the local DB reset so its asyncpg pool reconnected)
- **Plugin recognition source**: `local` — `API URL = http://localhost:8000`
- **API key (hash tail)**: `hash:dbfb` — created via `python -m scripts.manage_api_keys --env local create --tenant c0ce73dc-1c66-56a4-ae32-6eb966810988 --tier STANDARD`
- **API key (raw tail printed once at create)**: `****Ks8U`
- **Tenant UUID derivation**: `sha1('acx-site-tenant:http://localhost:10010')` shaped to v5-style — deterministic from the WordPress site URL via `apps/prototype-wp-alt-context/src/api/class-tenant-identity.php`.

### Service liveness/readiness probes

```
$ curl -sS -i http://localhost:8000/health
HTTP/1.1 200 OK
content-type: application/json
x-request-id: req-069f6aa6-2e73-77c9-8000-c9e1463914c6

{"status":"ok","timestamp":"2026-05-03T01:52:35.011236+00:00","commit_sha":"97643826"}

$ curl -sS -i http://localhost:8000/ready
HTTP/1.1 200 OK
content-type: application/json
x-request-id: req-069f6aa6-3163-7315-8000-f99eccb908b0

{"status":"ok","checks":[
  {"name":"database","status":"ok","detail":"reachable"},
  {"name":"breaker","status":"ok","detail":"closed"},
  {"name":"model_cache","status":"ok","detail":"5 bundle file(s)"}
],"timestamp":"2026-05-03T01:52:35.136044+00:00"}
```

### Plugin Test Connection

WordPress admin — Alt Context Settings → Recognition API Settings:

```
API URL    http://localhost:8000           (Saved in database)
API Key    Current: ****Ks8U               (Saved in database)

[Test Connection] → "Connection successful."
```

**Result**: PASS. Plugin authenticated against the local recognition service and
the asyncpg pool was healthy.

### Notes

- The first attempt with key `****Ks8U` was rejected with a 403 because the
  running uvicorn (PID 53707, started prior to `make reset-local`) held a
  stale asyncpg pool referencing the dropped DB. Restarting the service
  fixed it; the same key then authenticated successfully.
- This incident motivated **E15-12-BR-04** — `manage_api_keys list` previously
  emitted a bare last-4-of-hash column that could be misread as the raw-key
  tail. Fixed at commit
  [`f252e882`](https://github.com/darce/context-alt-text-monorepo/commit/f252e882):
  the column is now self-labelled `hash:<tail>` so operators cannot confuse
  it with the unrecoverable raw-key tail. Test:
  `recognition/tests/scripts/test_manage_api_keys.py::test_list_masks_hash`.

---

## Service-mode smoke (after `make reset-remote ENV=dev`)

- **Date**: 2026-05-02
- **Operator**: daniel
- **Reset command**: `make reset-remote ENV=dev CONFIRM_REMOTE_RESET=RESET`
- **SSH target**: `ubuntu@acx-backend.tail1a44b8.ts.net`
- **Service HEAD at smoke time** (from `/health`): `1043946953644164...` (10439469)
- **Tenant UUID**: `00000000-0000-7000-8000-000000000000` — created idempotently by the post-reset bootstrap (`tenant create --tenant <uuid> --site-url https://dev.api.altcontext.com`).
- **API key (raw tail printed once at create)**: `****vMo` — `key_id=c935ff2b-95c5-4b7c-b75b-8503bc119f2a`.

### Reset readiness

Captured live from the `make reset-remote ENV=dev CONFIRM_REMOTE_RESET=RESET`
run on 2026-05-02:

```
==> Verifying readiness at https://dev.api.altcontext.com/ready
curl: (56) The requested URL returned error: 502
==> Readiness not yet reported (attempt 1/6); retrying in 5s
... (attempts 2 + 3 also 502 while the unit settled) ...
{"status":"ok","checks":[
  {"name":"database","status":"ok","detail":"reachable"},
  {"name":"breaker","status":"ok","detail":"closed"},
  {"name":"model_cache","status":"ok","detail":"5 bundle file(s)"}
],"timestamp":"2026-05-03T02:07:51.027722+00:00"}
==> Reset complete.
```

### Service liveness/readiness probes

```
$ curl -sS -i https://dev.api.altcontext.com/health
HTTP/2 200
content-type: application/json
x-request-id: req-069f6af0-1e70-7ed9-8000-63936c9274b1

{"status":"ok","timestamp":"2026-05-03T02:12:17.907448+00:00",
 "commit_sha":"10439469536441644ade4be9a89861edefc8fe30"}

$ curl -sS -i https://dev.api.altcontext.com/ready
HTTP/2 200
content-type: application/json
x-request-id: req-069f6af0-2146-7b32-8000-9769df187c4a

{"status":"ok","checks":[
  {"name":"database","status":"ok","detail":"reachable"},
  {"name":"breaker","status":"ok","detail":"closed"},
  {"name":"model_cache","status":"ok","detail":"5 bundle file(s)"}
],"timestamp":"2026-05-03T02:12:18.083745+00:00"}
```

### Wire-level auth probe (matches what the plugin's Test Connection sends)

The plugin's `test_connection` REST handler hits `/health/detailed` with
`X-Tenant-ID` (derived from the WordPress site URL) and `X-API-Key` (resolved
from settings) — see
[`apps/prototype-wp-alt-context/src/api/class-settings-controller.php`](../../../apps/prototype-wp-alt-context/src/api/class-settings-controller.php) `test_connection()`.

```
$ curl -sS -i \
    -H "X-Tenant-ID: 00000000-0000-7000-8000-000000000000" \
    -H "X-API-Key: ****vMo" \
    https://dev.api.altcontext.com/health/detailed
HTTP/2 200
content-type: application/json

{"status":"ok",...,"breaker_state":"closed",
 "model_cache":{"model_name":"buffalo_l","status":"ok","detail":"5 bundle file(s)"}}
```

`/health/detailed` 200 with the bootstrapped key and the deterministic tenant
UUID confirms the plugin's exact Test Connection request shape works against
freshly reset dev.

### Plugin Test Connection (manual UI check)

Operator action: in WordPress admin → Alt Context Settings → Recognition API
Settings, set Recognition source = `service`, API URL =
`https://dev.api.altcontext.com`, paste the API key (raw tail `****vMo`), Save,
then click **Test Connection**. Expected outcome: `Connection successful.`
(matching the local-mode result above). The wire-level probe above already
proves the same request will succeed; the UI step is the operator-facing
confirmation.

### Notes

- The bootstrap's `tenant create` ran during reset, but the second
  `manage_api_keys create` step did not print an `api_key=` line. Root cause:
  `scripts/deploy/recognition-service.sh:509` delivered the bootstrap as
  `ssh ... bash -s <<<"${bootstrap_cmd}"`, and each
  `docker compose exec -T api ...` call inside that heredoc consumed bash's
  stdin — the first exec swallowed the remaining lines so the key-create
  silently never ran. Filed as **E15-12-BR-05**; fix landed in the same
  slice by adding `< /dev/null` to each exec invocation, with a regression
  test at
  `scripts/test_recognition_service_reset_subcommand.py::test_reset_dev_dry_run_bootstrap_redirects_exec_stdin`.
  The key captured in this proof was minted by re-running the missing
  `manage_api_keys --env prod create` over SSH manually with the
  same `< /dev/null` guard.
