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

_Pending. To be captured against `dev.api.altcontext.com` after the next
`make reset-remote ENV=dev CONFIRM_REMOTE_RESET=RESET` + bootstrap, with the
plugin recognition source set to `service`._

Required contents (mirror the local-mode block above):

- Reset command + timestamp + operator.
- `/health` and `/ready` 200 responses against `https://dev.api.altcontext.com`.
- Service `commit_sha` from `/health`.
- Plugin Test Connection screenshot or quoted result with API URL set to the
  hosted dev endpoint and the API key minted via `manage_api_keys --env dev create`.
