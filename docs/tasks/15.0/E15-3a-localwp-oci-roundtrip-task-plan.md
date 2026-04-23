# E15-3a. LocalWP -> OCI Backend Round-Trip Verification (MVP-critical gate)

> **Task Short ID**: E15-3a
> **Status**: in-progress -- BR-* remediation shipped; operator roundtrip (Slices 1-4) pending
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
6. A run log captures: API key fingerprint, **backend-side** correlation IDs for representative requests (sourced from OCI stdout — the plugin proxy does not currently forward `X-Request-ID` to the browser; see Non-Goals), observed latency, CORS rejection evidence, rate-limit 429 evidence, and the fallback-render screenshot / transcript.

All six are required. Partial completion does not unblock E15-3.

## Non-Goals (explicit)

- Provisioning public shared PHP hosting -- owned by [E15-3](./E15-3-wordpress-demo-provisioning-task-plan.md).
- Capturing ARM compatibility evidence -- owned by [E15-5](./E15-5-manual-remote-e2e-task-plan.md) Deliverables.
- OCI budget alerts / Tailscale / Hetzner fallback plan -- owned by [E15-5a](./E15-5a-oci-operational-hygiene-task-plan.md).
- Automated E2E smoke gate -- deferred to [E16](../../epics/v0.4.1/public-demo-followons-epic.md) under E15-6.
- Surfacing backend correlation IDs through the WordPress plugin (browser network tab / plugin debug log) -- deferred. The current proxy controller `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` only forwards `Retry-After`. Plugin-side `X-Request-ID` forwarding is a follow-on against [E15-1b](./E15-1b-plugin-settings-ux-task-plan.md) (settings UX / proxy header allowlist), not E15-3a.

## Slice Plan

### Slice 1 -- LocalWP configuration + connection probe

- Install/activate ACX plugin in LocalWP against the current tracked build (`apps/prototype-wp-alt-context/`).
- Configure plugin Settings:
  - Backend base URL: `https://api.altcontext.com`
  - API key: production key (fingerprint only in run log; never raw).
- Run the plugin's `/settings/test` connection probe.
- Confirm the LocalWP origin is on the backend CORS allowlist. The production configuration surface is `RECOGNITION_ALLOWED_ORIGINS` in the per-environment env file on the OCI host, `/opt/acx-backend/prod/.env`, which is loaded by the compose file `docker-compose.env.yml` (see `apps/prototype-description-service/.env.prod.example` for the field contract and `docs/agentic/contracts/security.md`). If the origin is missing, edit that env file and restart the `acx-prod.service` systemd unit (`sudo systemctl restart acx-prod`) before retrying the probe; see `infra/oci/README.md` for the canonical per-environment layout.

Exit: Settings page reports a successful probe; connection attempt logged with a correlation ID visible via `cd /opt/acx-backend/prod && docker compose -f docker-compose.env.yml logs -f` (see `infra/oci/README.md` for the per-environment log surface) or the equivalent stdout log view documented in `docs/operations/observability-runbook.md`.

### Slice 2 -- Scan round-trip against seeded media

- Seed the LocalWP media library with ~5-10 recognizable, non-sensitive images (reuse the same provenance-tracked set E15-3 will ship on the public demo).
- Trigger a scan from the plugin Workbench.
- Capture in the run log:
  - Backend correlation IDs for representative requests (grep the OCI stdout logs per `docs/operations/observability-runbook.md#tracing-a-request-by-correlation-id`). The plugin proxy does not currently forward `X-Request-ID` to the browser, so backend stdout is the sole source for this gate — see Non-Goals.
  - Observed P50/P95 latency for the representative calls, derived from `/metrics` histogram buckets with the PromQL examples in `docs/operations/observability-runbook.md#promql-quantiles-from-the-histogram`.
  - Recognition result payload snapshot (redact any face embeddings; keep counts + labels).

Exit: green round-trip; run log has before/after screenshots of plugin state.

### Slice 3 -- Security boundary checks

- CORS rejection: from a second browser profile with a non-allowlisted origin (e.g. a throwaway `127.0.0.1:4000` dev server), issue a privileged request to the API. Capture the rejection response. Per `docs/agentic/contracts/security.md`, the expected result is that the response omits `Access-Control-Allow-Origin` for the non-allowlisted origin.
- Before the rate-limit test, provision a throwaway production-scoped test key via `cd apps/prototype-description-service && python -m scripts.manage_api_keys --env prod create --tenant <id>` (module-form invocation + explicit `--env prod` are mandated by the script's own usage block; the DSN host guard refuses to run otherwise); record only its fingerprint in the run log and note that the key will be revoked immediately after the slice.
- Rate limiting: issue sustained load against that single temporary key until a 429 is observed; capture request count plus the expected `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0`, and `{"detail":"rate limit exceeded"}` evidence documented in `docs/agentic/contracts/security.md`.
- Revoke the throwaway test key immediately after evidence capture via `cd apps/prototype-description-service && python -m scripts.manage_api_keys --env prod revoke --key-id <id>` and record the revocation timestamp in the run log.

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
- **RFC5737 timeout misreads as hard failure** -- plugin might render a different error state than the canonical outage status (`sync_health=offline`, "Waiting for service…") per `docs/agentic/contracts/conflict-resolution-sync-contract.md` and the `SyncStatus` surface. Mitigation: Slice 4 captures whatever the plugin actually does, and any gap vs. the expected fallback UX becomes a new finding against E15-7 (local sync correctness), not a gate failure here.
- **Slice 3 rate-limit test burns production key budget** -- only relevant if the key has a cost ceiling. Mitigation: use a throwaway production-scoped test key whose revocation is scheduled immediately after the slice.

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Do not add rows like `(BR-04 closed)` or "resolve handoff issue X"; finding status lives in MCP / `DASHBOARD.txt`.

## Context and Ownership

- [x] Loaded the minimum authoritative rules, contracts, and handoff state before running the gate.
- [x] Confirmed no extra external dependency context is required beyond the cited OCI, security, and sync contract docs.
- [x] Kept ownership boundaries intact: E15-3a covers the LocalWP -> OCI gate only; E15-3, E15-5, E15-5a, and E15-6 stay in their declared scopes.

### Checklist for Slice 1: LocalWP configuration + connection probe

- [ ] Install and activate the current ACX plugin build in LocalWP and configure `https://api.altcontext.com` plus the production API key.
- [ ] Confirm the LocalWP origin is present in `RECOGNITION_ALLOWED_ORIGINS` (`/opt/acx-backend/prod/.env` on the OCI host); if not, add it and restart `acx-prod.service` (`sudo systemctl restart acx-prod`), then retry the probe.
- [ ] Capture a successful probe with a visible correlation ID in the OCI log surface.

### Checklist for Slice 2: Scan round-trip against seeded media

- [ ] Seed the LocalWP media library with the provenance-tracked demo image set and run a Workbench scan.
- [ ] Capture backend correlation IDs, latency evidence, and a redacted recognition payload snapshot in `E15-3a-localwp-oci-run-log.md` (backend-only source per the Non-Goals note).
- [ ] Record before/after screenshots showing the green round-trip state.

### Checklist for Slice 3: Security boundary checks

- [ ] Capture privileged-endpoint CORS rejection evidence from a non-allowlisted origin.
- [ ] Create a throwaway production-scoped test key, drive a deterministic 429 on that key, and record the rate-limit headers/body evidence.
- [ ] Revoke the throwaway key immediately after capture and record the revocation timestamp in the run log.

### Checklist for Slice 4: Sovereign local-read fallback (RFC5737 deterministic timeout)

- [ ] Point the plugin temporarily at `https://192.0.2.1` to force the deterministic connect-timeout path.
- [ ] Capture the observed cached-state render plus the current degraded sync-status evidence.
- [ ] Restore `https://api.altcontext.com` before closing the slice and attach the fallback screenshot / annotated transcript.

## Review Readiness

- [ ] Every slice leaves matching evidence in the run log or decision record before the next slice starts.
- [ ] Any CORS allowlist change, temporary key lifecycle action, or fallback UX discrepancy is documented on the same pass that discovers it.
- [ ] MCP handoff records one slice-complete write per slice plus the final gate verdict.

## Success Criteria

- [ ] All six E15-3a MVP exit criteria are satisfied with one redacted run log covering all four slices.
- [ ] E15-3 is explicitly unblocked only after the LocalWP -> OCI gate passes end to end.

## Handoff

After each slice, record the outcome in MCP handoff (`close_slice` or `record_event` with a `slice_complete_*` decision) before moving on to the next slice.

When done, set `E15-3a` status to `done`, archive task state, and notify E15-3 that WP-host provisioning is unblocked. If the gate fails, file a blocker against the active handoff and stop; **do not start E15-3**.
