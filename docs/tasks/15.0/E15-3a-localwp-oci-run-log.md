# E15-3a LocalWP -> OCI Round-Trip Run Log

> **Task**: [E15-3a-localwp-oci-roundtrip-task-plan.md](./E15-3a-localwp-oci-roundtrip-task-plan.md)
> **Status**: Slice 1 complete; Slices 2-4 pending
> **Operator**: `Daniel`
> **Execution Dates**: Slice 1 `2026-04-23`; Slices 2-4 `<pending>`
> **LocalWP Site**: `wp-context-alt-text`
> **LocalWP Origin**: `http://localhost:10010`
> **Backend Base URL**: `https://api.altcontext.com`
> **Plugin Build Source**: `apps/prototype-wp-alt-context/` (build `28d78e6a`, packaged as `dist/alt-context-0.0.2.zip`)

This run log is the single evidence surface for the full LocalWP plugin ->
OCI backend -> recognition round trip. Record only key fingerprints, never raw
API keys or secrets. MCP handoff remains the durable task-state surface for
slice-complete decisions, test results, and final gate verdicts; this markdown
log carries the redacted operator evidence and artifact locations that those
handoff entries should reference.

Run the local PostgreSQL preflight in [E15-3a-localwp-proof-bundle-capture-checklist.md](./E15-3a-localwp-proof-bundle-capture-checklist.md) before opening OCI log tails or metrics for Slice 2. The remote proof packet starts only after the local DB path is green.

## Run Metadata

| Field | Value |
| --- | --- |
| Run date | Slice 1 `2026-04-23`; Slices 2-4 `<pending>` |
| Operator | `Daniel` |
| Task ref | `E15-3a` |
| Branch / build under test | `feature/e15-22` / plugin build `28d78e6a` |
| LocalWP site URL | `http://localhost:10010` |
| Backend base URL | `https://api.altcontext.com` |
| Production API key fingerprint | `short_id=7592` / UI `****I-xM` |
| Proof-bundle artifact bundle ID | `<pending>` |
| Source scan run identifier | `<pending>` |
| Seeded-media set identifier | `<pending>` |
| E15-11 hosted transport proof reference | `<pending>` |

## Evidence Index

| Artifact | Status | Notes |
| --- | --- | --- |
| Local PostgreSQL preflight complete | [ ] | Record whether native `localhost:5432` or Docker `localhost:55432` was used before OCI capture |
| Production API key fingerprint recorded | [x] | `short_id=7592`, UI `****I-xM`, `key_id=3a5d9583-25f8-4dfb-a07b-4129708bd4ef` |
| Slice 1 successful `/settings/test` probe | [x] | outcome=`connected`, 200, correlation_id `req-069ea56c-bb67-7398-8000-58009f0df015` |
| Slice 2 green scan round-trip | [ ] | Include screenshots + redacted payload snapshot |
| Slice 3 CORS rejection evidence | [ ] | Include response evidence from non-allowlisted origin |
| Slice 3 rate-limit 429 evidence | [ ] | Include headers/body + throwaway key lifecycle |
| Slice 4 offline fallback evidence | [ ] | Include screenshot / annotated transcript |
| Representative backend correlation IDs captured from OCI stdout | [x] (Slice 1) / [ ] (Slices 2-3) | Plugin proxy does not surface these in-browser |
| Representative latency evidence captured from `/metrics` | [ ] | P50/P95 at minimum (Slice 2) |
| Final gate verdict recorded | [ ] | Pass only when all six MVP exit criteria are met |

## Seeded-Media Proof-Bundle Capture Packet

Use one seeded-media Workbench scan to populate every E15-22 proof row below. Record the same `proof-bundle artifact bundle ID` and `source scan run identifier` in each subsection so E15-3 and E15-5 can reuse the packet without redefining avatar/progress success.

Use the operator checklist in [E15-3a-localwp-proof-bundle-capture-checklist.md](./E15-3a-localwp-proof-bundle-capture-checklist.md) to execute this packet directly in capture order.

| Step | Required capture | Status | Notes |
| --- | --- | --- | --- |
| 1 | Pre-scan state showing build, seeded-media set, and the Workbench route under test | [ ] | Same operator session as the scan below |
| 2 | Representative avatar visible on a top-cluster card or review drawer, or the explicit unavailable-image fallback on that same surface | [ ] | Capture from the same seeded-media scan run |
| 3 | Mid-run progress checkpoint showing the processed count increasing and no `Scan complete` state yet | [ ] | Keep the visible count/checkpoint text in-frame |
| 4 | UI-ready completion checkpoint showing `Scan complete` only after clustering/projection is ready | [ ] | Pair with the prior mid-run checkpoint |
| 5 | Backend correlation IDs, latency evidence, and a redacted payload snapshot tied to the same scan run | [ ] | OCI stdout + `/metrics` + redacted payload summary |

## Operator Setup

| Field | Value |
| --- | --- |
| Plugin version / commit | `0.0.2 / 28d78e6af452650d2a8e7250268149c9b5232b73` |
| Plugin ZIP SHA256 | `5c9ab7cd572e2caca641e00d630e0fc5901da52969ce5c1bac81f93beed9f486` |
| Backend image SHA | `c13e28fc1d4909250398c0cf3c28fd197a3611fd` (verified via `GET /version`) |
| Tenant UUID | `c0ce73dc-1c66-56a4-ae32-6eb966810988` (SHA1-derived from `http://localhost:10010`) |
| Production API key fingerprint | `short_id=7592` / UI `****I-xM` / `key_id=3a5d9583-25f8-4dfb-a07b-4129708bd4ef` |
| Throwaway rate-limit test key fingerprint | `<fill during Slice 3>` |
| Throwaway rate-limit test key id | `<fill during Slice 3>` |
| Local PostgreSQL mode | `<native localhost:5432 / docker localhost:55432 / pending>` |
| OCI environment | `prod` |
| OCI log surface used | `cd /opt/acx-backend/prod && docker compose -f docker-compose.env.yml logs -f` |
| Metrics surface used | `GET /metrics` with production API key |

## MVP Exit Criteria Ledger

| Exit Criterion | Evidence | Status |
| --- | --- | --- |
| 1. LocalWP plugin installed/configured and probe succeeds | [Slice 1](#slice-1--localwp-configuration--connection-probe) | [x] |
| 2. Workbench scan returns recognition results from OCI | [Slice 2](#slice-2--scan-round-trip-against-seeded-media) | [ ] |
| 3. CORS rejects non-allowlisted privileged origin | [Slice 3A](#slice-3a--cors-rejection-check) | [ ] |
| 4. Per-key rate limiting produces deterministic 429 | [Slice 3B](#slice-3b--rate-limit-check) | [ ] |
| 5. Local read path renders cached state during outage simulation | [Slice 4](#slice-4--sovereign-local-read-fallback-rfc5737-timeout) | [ ] |
| 6. Run log captures fingerprints, correlation IDs, latency, CORS/429/fallback evidence | This document | partial (Slice 1 only) |

## Slice 1 — LocalWP Configuration + Connection Probe

### Settings Applied

| Setting | Value |
| --- | --- |
| Backend URL | `https://api.altcontext.com` |
| API key fingerprint | `short_id=7592` / UI `****I-xM` |
| LocalWP origin | `http://localhost:10010` |
| ACX plugin active | `yes` (build `28d78e6a` via `dist/alt-context-0.0.2.zip`) |

### CORS Allowlist Pre-Check

The Slice 1 probe is server-side (`wp_remote_get` in the PHP plugin controller,
not a browser XHR), so CORS was not gated on this request. CORS rejection
behavior for real browser-origin XHRs is exercised in Slice 3A.

| Item | Value |
| --- | --- |
| `RECOGNITION_ALLOWED_ORIGINS` inspected | `n/a for server-side probe` |
| LocalWP origin already present | `n/a` |
| OCI env file touched | `n/a` |
| `acx-prod.service` restarted | `no` |
| Decision record needed | `no` |
| Decision record path | `n/a` |

### Probe Result

| Field | Value |
| --- | --- |
| Probe time | `2026-04-23 17:28:44 UTC` |
| Probe outcome | `connected` |
| HTTP status code | `200` |
| `retry_after_seconds` | `n/a` |
| Backend correlation ID | `req-069ea56c-bb67-7398-8000-58009f0df015` |
| OCI log excerpt reference | See "OCI log excerpt" below |
| Plugin UI message | `Connection successful. The plugin authenticated against the recognition service and the pool is healthy.` |

### OCI log excerpt

```text
api-1  | INFO:     172.18.0.2:55556 - "GET /health/detailed HTTP/1.1" 200 OK
api-1  | {"correlation_id": "req-069ea56c-bb67-7398-8000-58009f0df015",
         "name": "recognition.interface_adapters.http.deps.session",
         "message": "session_dependency_timing dependency=get_observability_session
                     available=True tenant_id= total_ms=77.06 probe_ms=36.21
                     tenant_context_ms=n/a conn_id=0xe941e9dd5c70"}
api-1  | {"correlation_id": "req-069ea56c-bb67-7398-8000-58009f0df015",
         "name": "recognition.interface_adapters.http.deps.session",
         "message": "session_dependency_timing dependency=get_optional_session
                     available=True tenant_id=c0ce73dc-1c66-56a4-ae32-6eb966810988
                     total_ms=317.00 probe_ms=44.56 tenant_context_ms=0.96
                     conn_id=0xe941ebc84620"}
```

### Slice 1 Notes

Slice 1 was initially blocked because the plugin was probing the removed
endpoint `/recognition/health/pool` (consolidated into `/health/detailed` in
backend Slice 2.5), which returned 404 and was classified as `SERVER_ERROR` by
`classify_http_status` in `class-settings-controller.php`. That was recorded as
finding `E15-3a-BR-19` and fixed on commit `28d78e6a` (plugin now probes
`/health/detailed`; existing `X-API-Key` + `X-Tenant-ID` headers already satisfy
the backend `require_auth` dependency).

After the fix was packaged into `dist/alt-context-0.0.2.zip` and installed into
the LocalWP site, and after the leaked initial key was rotated (revoked; new
key `short_id=7592` issued scoped to tenant `c0ce73dc-...`), the probe returned
the successful response above.

### Operator-visible notes (non-blocking)

- Startup log banner still prints `Git: unknown (unknown)` (from
  `api/main.py::_log_startup_info`). The `/version` endpoint correctly returns
  `c13e28fc1d4909250398c0cf3c28fd197a3611fd` via `_resolve_version_commit_sha`
  (reads `APP_GIT_COMMIT_SHA` env var, baked in at build time via BR-03 wiring).
  The startup banner uses `_get_git_info()` which shells out to `git` inside the
  container and has no `.git` dir, so it always falls through to `"unknown"`.
  This is a cosmetic log-banner bug (BR-03 follow-up), not a functional failure.
  See finding `E15-3a-BR-20` for the post-gate cleanup item.

## Slice 2 — Scan Round-Trip Against Seeded Media

### Seed Media Set

| Field | Value |
| --- | --- |
| Media provenance set | `<source / path / note>` |
| Media count | `<n>` |
| Sensitive/copyright review complete | `yes / no` |

### Scan Result

| Field | Value |
| --- | --- |
| Scan start time | `<timestamp>` |
| Scan completion time | `<timestamp>` |
| Source scan run identifier | `<pending>` |
| Representative backend correlation IDs | `<req-...>, <req-...>` |
| Recognition result summary | `<counts + labels only>` |
| Errors observed | `<none or summary>` |

### Latency Evidence

Record the PromQL or equivalent query used and the observed values. Keep the
query aligned with `docs/operations/observability-runbook.md`.

| Metric Window | Route | P50 | P95 | Notes |
| --- | --- | --- | --- | --- |
| `<5m>` | `<path label>` | `<value>` | `<value>` | `<optional note>` |

### Screenshots / Transcript

| Evidence | Location / Note |
| --- | --- |
| Before screenshot | `<path or note>` |
| After screenshot | `<path or note>` |
| Redacted payload snapshot | `<path or inline summary>` |

## E15-22 Proof Bundle

### Representative Avatar Evidence

| Field | Value |
| --- | --- |
| Proof-bundle artifact bundle ID | `<pending>` |
| Source scan run identifier | `<pending>` |
| Capture checkpoint | `<top-cluster visible / review drawer open / explicit fallback>` |
| Surface shown | `<top-cluster card / review drawer / other>` |
| Representative source | `<thumb_url / explicit fallback>` |
| Representative cluster / media reference | `<cluster id / media id / note>` |
| Screenshot / transcript path | `<path or note>` |
| Reusable in E15-3 | `<yes / no>` |
| Reusable in E15-5 | `<yes / no>` |

### Monotonic Processed-Count Evidence

| Field | Value |
| --- | --- |
| Proof-bundle artifact bundle ID | `<pending>` |
| Source scan run identifier | `<pending>` |
| Screenshot / transcript path | `<path or note>` |
| Capture checkpoints | `<submitted -> mid-run -> clustering/projecting -> complete>` |
| Processed-count checkpoints | `<list or summary>` |
| Notes | `<pending>` |

### Scan Complete Timing Evidence

| Field | Value |
| --- | --- |
| Proof-bundle artifact bundle ID | `<pending>` |
| Source scan run identifier | `<pending>` |
| Pre-completion checkpoint path | `<path or note>` |
| Completion checkpoint path | `<path or note>` |
| `scanProgress.phase` / UI-ready state at completion capture | `<pending>` |
| Notes | `<pending>` |

### Reuse Metadata

| Field | Value |
| --- | --- |
| Artifact bundle ID | `<pending>` |
| Source scan run identifier | `<pending>` |
| Reused by E15-3 | `<yes / no>` |
| Reused by E15-5 | `<yes / no>` |
| Reasons to recapture | `<none or summary>` |

### Slice 2 Notes

```text
<scan transcript / plugin observations / OCI observations>
```

## Slice 3A — CORS Rejection Check

### Non-Allowlisted Origin Setup

| Field | Value |
| --- | --- |
| Test origin | `<scheme://host[:port]>` |
| Browser / profile | `<name>` |
| Privileged endpoint exercised | `<path>` |

### Expected Result

Per `docs/agentic/contracts/security.md`, the rejection evidence is that the
response omits `Access-Control-Allow-Origin` for the non-allowlisted origin.

### CORS Captured Evidence

| Field | Value |
| --- | --- |
| Request time | `<timestamp>` |
| Response status | `<status>` |
| `Access-Control-Allow-Origin` present | `yes / no` |
| Browser / network transcript reference | `<path or note>` |
| Backend correlation ID (if available) | `<req-... or unavailable>` |

```text
<header dump / concise transcript>
```

## Slice 3B — Rate-Limit Check

### Throwaway Key Lifecycle

| Field | Value |
| --- | --- |
| Create command | `cd apps/prototype-description-service && python -m scripts.manage_api_keys --env prod create --tenant <id>` |
| Created at | `<timestamp>` |
| Key id | `<uuid>` |
| Key fingerprint | `<fingerprint only>` |
| Revocation command | `cd apps/prototype-description-service && python -m scripts.manage_api_keys --env prod revoke --key-id <id>` |
| Revoked at | `<timestamp>` |

### 429 Evidence

| Field | Value |
| --- | --- |
| Endpoint under load | `<path>` |
| Sustained load method | `<command / script / browser action>` |
| Request count before first 429 | `<n>` |
| Response status | `429` |
| `Retry-After` | `<value>` |
| `X-RateLimit-Limit` | `<value>` |
| `X-RateLimit-Remaining` | `0` |
| Response body | `{"detail":"rate limit exceeded"}` |
| Backend correlation ID(s) | `<req-...>` |

```text
<rate-limit transcript / headers / notes>
```

## Slice 4 — Sovereign Local-Read Fallback (RFC5737 Timeout)

### Timeout Simulation

| Field | Value |
| --- | --- |
| Temporary backend URL | `https://192.0.2.1` |
| Production URL restored after test | `yes / no` |
| Cached state existed before test | `yes / no` |

### Expected UI Contract

The current UI contract expects the degraded status to surface as
`sync_health=offline` with the label `Waiting for service…`.

### Fallback Captured Evidence

| Field | Value |
| --- | --- |
| Test time | `<timestamp>` |
| Observed `sync_health` | `<value>` |
| Observed label | `<value>` |
| Screenshot / transcript reference | `<path or note>` |
| Gap vs expected contract | `<none or summary>` |

```text
<fallback transcript / notes>
```

## Final Verdict

| Item | Result |
| --- | --- |
| All six MVP exit criteria satisfied | `pending Slices 2-4` |
| E15-3 unblocked | `pending` |
| Follow-up task needed | `E15-3a-BR-20 (cosmetic startup log banner) scheduled post-gate` |

## Open Issues / Follow-Ons

- `E15-3a-BR-20`: startup log banner in `api/main.py::_log_startup_info` prints
  `Git: unknown (unknown)` because it calls `_get_git_info()` (shells out to
  `git` inside the container and finds no `.git`). `/version` correctly returns
  `APP_GIT_COMMIT_SHA`; only the banner is affected. Non-blocking; scheduled
  for post-gate cleanup.
