# E15-3a. LocalWP -> OCI Backend Round-Trip Verification (MVP-critical gate)

> **Task Short ID**: E15-3a
> **Status**: scoped -- not started
> **Epic**: [E15. Public Demo Launch Readiness](../../epics/v0.4.0/public-demo-launch-readiness-epic.md) Phase 3 (pre-provisioning gate)
> **Predecessors**: E15-1 (security baseline) merged; E15-2 (observability baseline) merged. OCI backend live at `api.altcontext.com`.
> **Blocks**: [E15-3](./E15-3-wordpress-demo-provisioning-task-plan.md) (WP demo provisioning). A failing gate here means the OCI backend cannot yet serve a real ACX plugin instance, which makes buying shared PHP hosting premature.
> **Sibling (runs in parallel)**: [E15-5a](./E15-5a-oci-operational-hygiene-task-plan.md) (OCI budget alerts + Tailscale + Hetzner fallback plan).

---

## Objective

Prove the full **LocalWP plugin -> `api.altcontext.com` -> recognition -> response** round trip works end-to-end against a real ACX plugin instance running in LocalWP, **before** provisioning any paid shared PHP hosting. This is a vendor-spend gate: do not buy WP hosting until this passes.

## MVP Exit Criteria

1. A LocalWP-resident WordPress instance has the ACX plugin installed, configured with production API key and `api.altcontext.com`, and reports a successful backend connection probe.
2. A curator can trigger a scan from the plugin Workbench against seeded local media and receive recognition results produced by OCI.
3. CORS correctly rejects a non-allowlisted browser origin for privileged endpoints.
4. Per-key rate limiting produces deterministic HTTP 429 under sustained load against a single key.
5. Sovereign local-read path renders cached state when the backend is unreachable via a deterministic connect-timeout simulation.
6. A run log captures: API key fingerprint, correlation IDs for representative requests, observed latency, CORS rejection evidence, rate-limit 429 evidence, and the fallback-render screenshot / transcript.

All six are required. Partial completion does not unblock E15-3.

## Non-Goals (explicit)

- Provisioning public shared PHP hosting -- owned by [E15-3](./E15-3-wordpress-demo-provisioning-task-plan.md).
- Capturing ARM compatibility evidence -- owned by [E15-5](./E15-5-manual-remote-e2e-task-plan.md) Deliverables.
- OCI budget alerts / Tailscale / Hetzner fallback plan -- owned by [E15-5a](./E15-5a-oci-operational-hygiene-task-plan.md).
- Automated E2E smoke gate -- deferred to [E16](../../epics/v0.4.1/public-demo-followons-epic.md) under E15-6.

## Slice Plan

### Slice 1 -- LocalWP configuration + connection probe

- Install/activate ACX plugin in LocalWP against the current tracked build (`apps/prototype-wp-alt-context/`).
- Configure plugin Settings:
  - Backend base URL: `https://api.altcontext.com`
  - API key: production key (fingerprint only in run log; never raw).
- Run the plugin's `/settings/test` connection probe.
- Confirm the LocalWP origin is on the backend CORS allowlist. The production configuration surface is `RECOGNITION_ALLOWED_ORIGINS` in the OCI `.env` / `.env.prod` file that feeds `apps/prototype-description-service/docker-compose.prod.yml` (see `apps/prototype-description-service/.env.prod.example` and `docs/agentic/contracts/security.md`). If the origin is missing, add it there and restart `acx-backend.service` before retrying the probe.

Exit: Settings page reports a successful probe; connection attempt logged with a correlation ID visible via `cd /opt/acx-backend && sudo docker compose logs -f` (see `infra/oci/README.md`) or the equivalent stdout log view documented in `docs/operations/observability-runbook.md`.

### Slice 2 -- Scan round-trip against seeded media

- Seed the LocalWP media library with ~5-10 recognizable, non-sensitive images (reuse the same provenance-tracked set E15-3 will ship on the public demo).
- Trigger a scan from the plugin Workbench.
- Capture in the run log:
  - Request correlation IDs (from browser network tab or plugin debug log).
  - Backend correlation IDs (grep the OCI stdout logs per `docs/operations/observability-runbook.md#tracing-a-request-by-correlation-id`).
  - Observed P50/P95 latency for the representative calls, derived from `/metrics` histogram buckets with the PromQL examples in `docs/operations/observability-runbook.md#promql-quantiles-from-the-histogram`.
  - Recognition result payload snapshot (redact any face embeddings; keep counts + labels).

Exit: green round-trip; run log has before/after screenshots of plugin state.

### Slice 3 -- Security boundary checks

- CORS rejection: from a second browser profile with a non-allowlisted origin (e.g. a throwaway `127.0.0.1:4000` dev server), issue a privileged request to the API. Capture the rejection response. Per `docs/agentic/contracts/security.md`, the expected result is that the response omits `Access-Control-Allow-Origin` for the non-allowlisted origin.
- Before the rate-limit test, provision a throwaway production-scoped test key via `apps/prototype-description-service/scripts/manage_api_keys.py create --tenant <id>`; record only its fingerprint in the run log and note that the key will be revoked immediately after the slice.
- Rate limiting: issue sustained load against that single temporary key until a 429 is observed; capture request count plus the expected `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0`, and `{"detail":"rate limit exceeded"}` evidence documented in `docs/agentic/contracts/security.md`.
- Revoke the throwaway test key immediately after evidence capture via `apps/prototype-description-service/scripts/manage_api_keys.py revoke --key-id <id>` and record the revocation timestamp in the run log.

Exit: CORS rejection evidence + 429 evidence filed in the run log.

### Slice 4 -- Sovereign local-read fallback (RFC5737 deterministic timeout)

- Temporarily set the plugin backend URL to an RFC5737 address (`https://192.0.2.1`) to force a deterministic connect timeout.
- Confirm the plugin renders cached state and surfaces the canonical outage-facing sync status used by the current UI (`sync_health=offline`, label `Waiting for service…`; see `docs/agentic/contracts/conflict-resolution-sync-contract.md` and `apps/prototype-wp-alt-context/js/admin/pages/workbench/SyncStatusIndicator.tsx`).
- Revert the URL to `https://api.altcontext.com` before finishing the slice.
- Capture fallback-render screenshot / annotated transcript.

Exit: fallback behavior verified; plugin restored to production URL.

## Deliverables

- `docs/tasks/15.0/E15-3a-localwp-oci-run-log.md` (single run log covering all four slices; redacted where appropriate).
- If a CORS-allowlist addition was needed for the LocalWP origin, a decision record under `docs/tasks/15.0/E15-3a-cors-origin-decision.md` capturing the exact origin added, who approved it, and its lifetime (temporary vs. permanent).
- Production API key fingerprint logged against the E15-1 key lifecycle surface.
- A slice-complete MCP handoff write after each slice (`close_slice` or `record_event` with a `slice_complete_*` decision), not just at task end.

## Dependencies Not Owned Here

- OCI backend live at `api.altcontext.com` (confirmed via E14-1).
- Production API key provisioned from the E15-1 key lifecycle surface.
- LocalWP install running locally on the operator workstation.

## Risks

- **LocalWP origin not on production CORS allowlist** -- probe returns CORS error, gate fails spuriously. Mitigation: Slice 1 includes an allowlist-update step before calling the gate failed; rollback path is documented.
- **Raw API key leak into run log / repo** -- production key exposure. Mitigation: fingerprint-only in run log (same discipline as E15-3); run log reviewed before commit.
- **RFC5737 timeout misreads as hard failure** -- plugin might render a different error state than the documented "degraded-sync indicator". Mitigation: Slice 4 captures whatever the plugin actually does, and any gap vs. the expected fallback UX becomes a new finding against E15-7 (local sync correctness), not a gate failure here.
- **Slice 3 rate-limit test burns production key budget** -- only relevant if the key has a cost ceiling. Mitigation: use a throwaway production-scoped test key whose revocation is scheduled immediately after the slice.

## Handoff

After each slice, record the outcome in MCP handoff (`close_slice` or `record_event` with a `slice_complete_*` decision) before moving on to the next slice.

When done, set `E15-3a` status to `done`, archive task state, and notify E15-3 that WP-host provisioning is unblocked. If the gate fails, file a blocker against the active handoff and stop; **do not start E15-3**.
