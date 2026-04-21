# E15-3a LocalWP -> OCI Round-Trip Run Log

> **Task**: [E15-3a-localwp-oci-roundtrip-task-plan.md](./E15-3a-localwp-oci-roundtrip-task-plan.md)
> **Status**: in progress
> **Operator**: `Daniel`
> **Execution Date**: `2026-04-21`
> **LocalWP Site**: `wp-context-alt-text`
> **LocalWP Origin**: `http://localhost:10010`
> **Backend Base URL**: `https://api.altcontext.com`
> **Plugin Build Source**: `apps/prototype-wp-alt-context/`

This run log is the single evidence surface for the full LocalWP plugin ->
OCI backend -> recognition round trip. Record only key fingerprints, never raw
API keys or secrets.

## Evidence Index

| Artifact | Status | Notes |
| --- | --- | --- |
| Production API key fingerprint recorded | ☐ | Fingerprint only |
| Slice 1 successful `/settings/test` probe | ☐ | Include outcome + backend correlation ID |
| Slice 2 green scan round-trip | ☐ | Include screenshots + redacted payload snapshot |
| Slice 3 CORS rejection evidence | ☐ | Include response evidence from non-allowlisted origin |
| Slice 3 rate-limit 429 evidence | ☐ | Include headers/body + throwaway key lifecycle |
| Slice 4 offline fallback evidence | ☐ | Include screenshot / annotated transcript |
| Representative backend correlation IDs captured from OCI stdout | ☐ | Plugin proxy does not surface these in-browser |
| Representative latency evidence captured from `/metrics` | ☐ | P50/P95 at minimum |
| Final gate verdict recorded | ☐ | Pass only when all six MVP exit criteria are met |

## Operator Setup

| Field | Value |
| --- | --- |
| Plugin version / commit | `0.0.2 / 695ee966` |
| Production API key fingerprint | `877684081a57` (stored LocalWP option; backend currently rejects it) |
| Throwaway rate-limit test key fingerprint | `<fill during Slice 3>` |
| Throwaway rate-limit test key id | `<fill during Slice 3>` |
| OCI environment | `prod` |
| OCI log surface used | `cd /opt/acx-backend/prod && docker compose -f docker-compose.env.yml logs -f` |
| Metrics surface used | `GET /metrics` with production API key |

## MVP Exit Criteria Ledger

| Exit Criterion | Evidence | Status |
| --- | --- | --- |
| 1. LocalWP plugin installed/configured and probe succeeds | [Slice 1](#slice-1--localwp-configuration--connection-probe) | ☐ |
| 2. Workbench scan returns recognition results from OCI | [Slice 2](#slice-2--scan-round-trip-against-seeded-media) | ☐ |
| 3. CORS rejects non-allowlisted privileged origin | [Slice 3A](#slice-3a--cors-rejection-check) | ☐ |
| 4. Per-key rate limiting produces deterministic 429 | [Slice 3B](#slice-3b--rate-limit-check) | ☐ |
| 5. Local read path renders cached state during outage simulation | [Slice 4](#slice-4--sovereign-local-read-fallback-rfc5737-timeout) | ☐ |
| 6. Run log captures fingerprints, correlation IDs, latency, CORS/429/fallback evidence | This document | ☐ |

## Slice 1 — LocalWP Configuration + Connection Probe

### Settings Applied

| Setting | Value |
| --- | --- |
| Backend URL | `https://api.altcontext.com` |
| API key fingerprint | `877684081a57` |
| LocalWP origin | `http://localhost:10010` |
| ACX plugin active | `yes` |

### CORS Allowlist Pre-Check

| Item | Value |
| --- | --- |
| `RECOGNITION_ALLOWED_ORIGINS` inspected | `not yet` |
| LocalWP origin already present | `unknown` |
| OCI env file touched | `/opt/acx-backend/prod/.env` or `n/a` |
| `acx-prod.service` restarted | `yes / no` |
| Decision record needed | `yes / no` |
| Decision record path | `docs/tasks/15.0/E15-3a-cors-origin-decision.md` or `n/a` |

### Probe Result

| Field | Value |
| --- | --- |
| Probe time | `2026-04-21 12:35:14 EDT` |
| Probe outcome | `invalid_key` |
| HTTP status code | `401` |
| `retry_after_seconds` | `n/a` |
| Backend correlation ID | `not yet captured` |
| OCI log excerpt reference | `pending OCI-side log capture after valid production key is configured` |

### Notes

Paste or summarize the exact plugin-visible `/settings/test` outcome and the
matching OCI-side correlation evidence here.

```text
Packaged plugin artifact `dist/alt-context-0.0.2.zip` from the `E15-3a`
worktree was installed into LocalWP, replacing the previous stable-checkout
symlink that carried `.env.local` dev overrides.

Current plugin-visible settings after ZIP install:
- `url=https://api.altcontext.com` (`url_source=option`)
- `api_key_set=true` (`key_source=option`, fingerprint `877684081a57`)

`POST /acx/v1/settings/test` now reaches `api.altcontext.com`, but the backend
responds with:

```json
{"outcome":"invalid_key","status_code":401,"detail":"invalid authorization scheme"}
```

This blocks Slice 1 completion until the correct production API key is supplied
to the LocalWP plugin settings and the OCI logs are checked for the matching
request/correlation evidence.
```

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

### Notes

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

### Captured Evidence

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

### Captured Evidence

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
| All six MVP exit criteria satisfied | `yes / no` |
| E15-3 unblocked | `yes / no` |
| Follow-up task needed | `<none or task ref>` |

## Open Issues / Follow-Ons

- `<none yet>`
