# E15-3a. LocalWP -> OCI Backend Round-Trip Verification (MVP-critical gate)

> **Task Short ID**: E15-3a
> **Status**: in-progress -- BR-* remediation shipped; operator roundtrip (Slices 1-4) pending
> **Epic**: [E15. Public Demo Launch Readiness](../../epics/v0.4.0/public-demo-launch-readiness-epic.md) Phase 3 (pre-provisioning gate)
> **Predecessors**: E15-1 (security baseline) merged; E15-2 (observability baseline) merged. OCI backend live at `api.altcontext.com`.
> **Blocks**: [E15-3](./E15-3-wordpress-demo-provisioning-task-plan.md) (WP demo provisioning). A failing gate here means the OCI backend cannot yet serve a real ACX plugin instance, which makes buying shared PHP hosting premature.
> **Sibling (runs in parallel)**: [E15-5a](./E15-5a-oci-operational-hygiene-task-plan.md) (OCI budget alerts + Tailscale + Hetzner fallback plan).
> **Format Note**: This is an operator gate plan, so it intentionally uses a condensed checklist-first format instead of mirroring every heading in `docs/workbay/templates/TASK_PLAN.template.md`. Review it against the slice gates, evidence requirements, and handoff steps below.

---

## Objective

Prove the full **LocalWP plugin -> `api.altcontext.com` -> recognition -> response** round trip works end-to-end against a real ACX plugin instance running in LocalWP, **before** provisioning any paid shared PHP hosting. This is a vendor-spend gate: do not buy WP hosting until this passes.

## MVP Exit Criteria

1. A LocalWP-resident WordPress instance has the ACX plugin installed, configured with production API key and `api.altcontext.com`, and reports a successful backend connection probe.
2. A curator can trigger a scan from the plugin Workbench against seeded local media and receive recognition results produced by OCI.
3. CORS correctly rejects a non-allowlisted browser origin for privileged endpoints.
4. Per-key rate limiting produces deterministic HTTP 429 under sustained load against a single key.
5. Sovereign local-read path renders cached state when the backend is unreachable via a deterministic connect-timeout simulation.
6. A run log captures: API key fingerprint, **backend-side** correlation IDs for representative requests (sourced from OCI stdout — the plugin proxy does not currently forward `X-Request-ID` to the browser; see Non-Goals), observed latency, CORS rejection evidence, rate-limit 429 evidence, the fallback-render screenshot / transcript, and the full E15-22 proof bundle for the same seeded-media run.

All six are required. Partial completion does not unblock E15-3.

## Non-Goals (explicit)

- Provisioning public shared PHP hosting -- owned by [E15-3](./E15-3-wordpress-demo-provisioning-task-plan.md).
- Capturing ARM compatibility evidence -- owned by [E15-5](./E15-5-manual-remote-e2e-task-plan.md) Deliverables.
- OCI budget alerts / Tailscale / Hetzner fallback plan -- owned by [E15-5a](./E15-5a-oci-operational-hygiene-task-plan.md).
- Automated E2E smoke gate -- E15-6 owns the docs/operator-evidence v1 slice in v0.4.0 ([E15-6. Playwright Operator-Evidence Harness](./E15-6-playwright-operator-evidence-harness-task-plan.md)); the durable CI smoke-gate automation is deferred to [E16](../../epics/v0.4.1/public-demo-followons-epic.md).
- Surfacing backend correlation IDs through the WordPress plugin (browser network tab / plugin debug log) -- deferred. The current proxy controller `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` only forwards `Retry-After`. Plugin-side `X-Request-ID` forwarding is a follow-on against [E15-1b](./E15-1b-plugin-settings-ux-task-plan.md) (settings UX / proxy header allowlist), not E15-3a.

## Slice Plan

### Slice 1 -- LocalWP configuration + connection probe

- Install/activate ACX plugin in LocalWP against the current tracked build (`apps/prototype-wp-alt-context/`).
- Configure plugin Settings:
  - Backend base URL: `https://api.altcontext.com`
  - API key: production key (fingerprint only in run log; never raw).
- Run the plugin's `/settings/test` connection probe.
- Confirm the LocalWP origin is on the backend CORS allowlist. The production configuration surface is `RECOGNITION_ALLOWED_ORIGINS` in the per-environment env file on the OCI host, `/opt/acx-backend/prod/.env` (a symlink to `secrets/.env`; see E15-5a), which is loaded by the compose file `docker-compose.env.yml` (see `apps/prototype-description-service/.env.prod.example` for the field contract and `docs/workbay/contracts/security.md`). If the origin is missing, capture the pre-change allowlist value in the run log, edit that env file, and restart the `acx-prod.service` systemd unit (`sudo systemctl restart acx-prod`) before retrying the probe; see `infra/oci/README.md` for the canonical per-environment layout. If the origin addition is only temporary for this gate, restore the pre-change allowlist immediately after Slice 3 and record the rollback timestamp; if it remains approved, record that disposition in `docs/tasks/15.0/E15-3a-cors-origin-decision.md`.

Exit: Settings page reports a successful probe; connection attempt logged with a correlation ID visible via `cd /opt/acx-backend/prod && docker compose -f docker-compose.env.yml logs -f` (see `infra/oci/README.md` for the per-environment log surface) or the equivalent stdout log view documented in `docs/operations/observability-runbook.md`.

### Slice 2 -- Scan round-trip against seeded media

- Seed the LocalWP media library with ~5-10 recognizable, non-sensitive images (reuse the same provenance-tracked set E15-3 will ship on the public demo).
- Trigger a scan from the plugin Workbench.
- Capture in the run log:
  - Backend correlation IDs for representative requests (grep the OCI stdout logs per `docs/operations/observability-runbook.md#tracing-a-request-by-correlation-id`). The plugin proxy does not currently forward `X-Request-ID` to the browser, so backend stdout is the sole source for this gate — see Non-Goals.
  - Observed P50/P95 latency for the representative calls, derived from `/metrics` histogram buckets with the PromQL examples in `docs/operations/observability-runbook.md#promql-quantiles-from-the-histogram`.
  - Recognition result payload snapshot (redact any face embeddings; keep counts + labels).
  - Screenshot or annotated transcript proving at least one visible top-cluster card or review-drawer avatar renders from the backend-served `thumb_url` surface in the authenticated admin session, or that the explicit unavailable-image fallback is what the operator sees when no representative image is available.
  - Screenshot or annotated transcript showing the processed counter increasing without decreasing and showing `Scan complete` only after the Workbench enters the UI-ready completion state.
  - Enough metadata to reuse the same artifact bundle in E15-3 and E15-5 without recapturing a second definition of avatar/progress success.

Exit: green round-trip; run log has before/after screenshots of plugin state.

### Slice 3 -- Security boundary checks

- CORS rejection: from a second browser profile with a non-allowlisted origin (e.g. a throwaway `127.0.0.1:4000` dev server), issue a privileged request to the API. Capture the rejection response. Per `docs/workbay/contracts/security.md`, the expected result is that the response omits `Access-Control-Allow-Origin` for the non-allowlisted origin.
- Before the rate-limit test, identify the correct production tenant UUID with `cd apps/prototype-description-service && python -m scripts.manage_api_keys --env prod tenant list --limit 20`, then provision a throwaway production-scoped test key via `cd apps/prototype-description-service && python -m scripts.manage_api_keys --env prod create --tenant <tenant_uuid>` (module-form invocation + explicit `--env prod` are mandated by the script's own usage block; the DSN host guard refuses to run otherwise). Record only the tenant UUID and key fingerprint in the run log and note that the key will be revoked immediately after the slice.
- Rate limiting: issue sustained load against that single temporary key until a 429 is observed; cap the drive at 50 requests or 5 minutes, whichever comes first. If no 429 arrives inside that bound, stop the slice, record the observed headers/body, and file a blocker or follow-up instead of looping indefinitely. On success, capture request count plus the expected `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0`, and `{"detail":"rate limit exceeded"}` evidence documented in `docs/workbay/contracts/security.md`.
- Revoke the throwaway test key immediately after evidence capture via `cd apps/prototype-description-service && python -m scripts.manage_api_keys --env prod revoke --key-id <id>` and record the revocation timestamp in the run log.

Exit: CORS rejection evidence + 429 evidence filed in the run log.

### Slice 4 -- Sovereign local-read fallback (public-firewall deterministic timeout)

- Before changing the backend URL, read the effective key source in Settings > Alt Context and record it with the current production API key fingerprint in the run log (fingerprint only, never the raw key). Identify the owning configuration: option, constant, environment, or filter. Settings reports environment-managed keys as `constant`; distinguish them using the deployment configuration. Also record the effective production URL and its owning source for restoration.
- Replace the effective API key with the obviously fake, non-empty placeholder `acx_offline_probe_placeholder` at its owning source: for an option-managed key, use the Settings field; for a constant, change `ACX_RECOGNITION_API_KEY` in `wp-config.php`; for an environment-managed key, change the PHP runtime's `ACX_RECOGNITION_API_KEY` variable; for a filter-managed key, change the code providing `acx_recognition_api_key`. Reload/restart the PHP runtime if needed to apply the change. Before changing the URL, reload Settings and confirm the same reported key source and the placeholder's fingerprint (the masked suffix is `****lder`). If either does not match, restore and stop. Keep this effective placeholder set throughout the offline probe so no real credential can be sent to the test endpoint.
- Choose the public (global) IP of an operator-owned OCI instance and one of WordPress's default safe-request ports, **80, 443, or 8080**, that its VCN security list does not open (commonly **8080**); OCI silently drops unsolicited SYNs to that port. Never use a third-party address. An arbitrary port can be rejected by `wp_safe_remote_request` before connecting. RFC 5737/3849 documentation addresses fail before any connection with `acx_egress_denied` and cannot stand in for the timeout path. Replace ADDRESS and PORT below with those operator-chosen values.
- On the WordPress host itself (the LocalWP machine, not only a separate operator laptop), run `curl -sS --connect-timeout 5 --max-time 10 -o /dev/null -w '%{time_connect}\n' https://ADDRESS:PORT/` against that exact port. Proceed only if it exits 28 with a connect-phase error ("Connection timed out after ..." or "Failed to connect ... Timeout was reached") and prints `0.000000` for `time_connect`. "Operation timed out ... bytes received", a TLS error, or any other result does not prove the connect-timeout path: choose another eligible port and repeat the pre-check; do not proceed.
- With the effective placeholder key confirmed, temporarily set the backend URL to the verified `https://ADDRESS:PORT/` through its owning source: the Settings URL option only for option-managed keys; for deployment-managed keys, use `ACX_RECOGNITION_URL` in `wp-config.php` or the code providing the `acx_recognition_base_url` filter. Do not rely on a saved URL option with a deployment-managed key. Reload Settings and confirm the effective target URL matches the probe URL before triggering a request.
- Before triggering the probe, create `wp-content/mu-plugins/acx-offline-probe-log.php` on the LocalWP machine (create the `mu-plugins` directory if absent) with only the following content. The `acx_sync_pull_failed` payload exposes `context` and `message`, but sync status stores only the failure classification; see `apps/prototype-wp-alt-context/src/sovereign/sync/class-sync-pull-job.php:144-151` and `:196-199`. Log only those two fields, never request arguments, headers, or the key. Do not use `http_api_debug`, whose arguments include the Authorization header.

  ```php
  <?php
  add_action( 'acx_sync_pull_failed', static function ( $payload ) {
      error_log( 'acx_sync_pull_failed ' . $payload['context'] . ': ' . $payload['message'] );
  } );
  ```

- In the plugin Workbench already used for the seeded-media run, click **Sync now** once to trigger one sync pull. Copy the single `acx_sync_pull_failed` line from the WordPress/PHP error log beside the fallback UI evidence. Require **cURL error 28 with connect-timeout text** (not a TLS or response-transfer timeout); the shell pre-check alone does not establish the PHP transport's result. If there is no line, or the message names URL validation, a blocked port, `acx_egress_denied`, `acx_egress_pin_failed`, or any other failure instead, the probe is invalid: restore the production configuration, remove the temporary logger as below, and stop.
- Confirm the plugin renders cached state and surfaces the canonical outage-facing sync status (`sync_health=offline`, headline **Recognition service unreachable — showing your local copy.**, badge **Offline**; see `docs/workbay/contracts/conflict-resolution-sync-contract.md` and `apps/prototype-wp-alt-context/js/admin/pages/workbench/syncVocabulary.ts:21-22`). Capture the fallback-render screenshot / annotated transcript together with the plugin connect-timeout log line.
- Before finishing (including if any probe step or fallback verification fails), restore the original production URL (`https://api.altcontext.com`) at the same URL source first, then restore the real API key at the same key source. Reload/restart the PHP runtime if needed. Delete `wp-content/mu-plugins/acx-offline-probe-log.php` and confirm the file is gone. Confirm in Settings that the effective URL and its source, the original key source, and the original key fingerprint all match the recorded values before closing the slice.

Configuration rules: proxy key resolution is in `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php:320-340`; environment injection, Settings key-source reporting, and deployment-managed edit restrictions are in `apps/prototype-wp-alt-context/src/api/class-settings-controller.php:95`, `:143`, `:196-218`, `:258-270`, `:290-296`, and `:1168-1190` (environment keys report `constant`). URL-source precedence and the deployment-key URL restriction are in `apps/prototype-wp-alt-context/src/api/class-recognition-endpoint-resolver.php:60-80` and `:191-195`; safe-request transport is in `apps/prototype-wp-alt-context/src/support/class-recognition-transport.php:219`.

Exit: fallback behavior verified with the plugin's connect-timeout log line; temporary mu-plugin removed and confirmed absent; production URL and real API key restored at their original sources, with matching effective URL/source and key fingerprint/source.

## Deliverables

- `docs/tasks/15.0/E15-3a-localwp-oci-run-log.md` (single run log covering all four slices; redacted where appropriate).
- `docs/tasks/15.0/E15-3a-localwp-oci-run-log.md` contains an explicit `E15-22 proof bundle` subsection naming: representative avatar evidence (`thumb_url` or explicit fallback), monotonic processed-count evidence, `Scan complete` timing evidence, and the seeded-media scan identifier/correlation IDs tying those artifacts to the backend run.
- If a CORS-allowlist addition was needed for the LocalWP origin, a decision record under `docs/tasks/15.0/E15-3a-cors-origin-decision.md` capturing the exact origin added, who approved it, and its lifetime (temporary vs. permanent).
- Production API key fingerprint logged against the E15-1 key lifecycle surface.
- A slice-complete MCP handoff write after each slice (`close_slice` or `record_event` with a `slice_complete_*` decision), not just at task end.

## Dependencies Not Owned Here

- OCI backend live at `api.altcontext.com` (confirmed via E14-1).
- Production API key provisioned from the E15-1 key lifecycle surface.
- LocalWP install running locally on the operator workstation.

## Risks

- **LocalWP origin not on production CORS allowlist** -- probe returns CORS error, gate fails spuriously. Mitigation: Slice 1 includes an allowlist-update step before calling the gate failed, requires the pre-change allowlist to be captured in the run log, and defines the rollback path for temporary origins.
- **Raw API key leak into run log / repo** -- production key exposure. Mitigation: fingerprint-only in run log (same discipline as E15-3); run log reviewed before commit.
- **Offline probe leaks credentials or exercises the wrong failure phase** -- deployment-managed keys override stored options, arbitrary ports can fail WordPress safe-request validation, documentation addresses return `acx_egress_denied`, and curl exit 28 alone can reflect a timeout after TCP connection. Mitigation: follow Slice 4 to replace the effective key at its owning source and confirm the placeholder fingerprint/source before changing the URL at its owning source. Use only an operator-owned OCI public IP on an unopened WordPress-permitted port (80, 443, or 8080; commonly 8080). Require both the LocalWP shell connect-phase pre-check and the plugin's own cURL error 28 connect-timeout text captured by the temporary `acx_sync_pull_failed` logger beside the fallback UI evidence; validation, egress, TLS, or transfer failures invalidate the probe. Restore the original URL and real key at the same sources, checking effective URL/source and key fingerprint/source, and delete `wp-content/mu-plugins/acx-offline-probe-log.php`, confirming it is gone, even if verification fails. Capture the actual fallback UX; any gap vs. the canonical outage status (`sync_health=offline`, headline **Recognition service unreachable — showing your local copy.**, badge **Offline**) per `docs/workbay/contracts/conflict-resolution-sync-contract.md` and `apps/prototype-wp-alt-context/js/admin/pages/workbench/syncVocabulary.ts:21-22` becomes a new finding against E15-7 (local sync correctness), not a gate failure here.
- **Slice 3 rate-limit test burns production key budget** -- only relevant if the key has a cost ceiling. Mitigation: use a throwaway production-scoped test key whose revocation is scheduled immediately after the slice, and bound the drive to 50 requests / 5 minutes so a misconfigured limiter cannot run indefinitely.

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Do not add rows like `(BR-04 closed)` or "resolve handoff issue X"; finding status lives in MCP / `DASHBOARD.txt`.

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, and handoff state before running the gate.
- [ ] Confirmed no extra external dependency context is required beyond the cited OCI, security, and sync contract docs.
- [ ] Kept ownership boundaries intact: E15-3a covers the LocalWP -> OCI gate only; E15-3, E15-5, E15-5a, and E15-6 stay in their declared scopes.

### Checklist for Slice 1: LocalWP configuration + connection probe

- [ ] Install and activate the current ACX plugin build in LocalWP and configure `https://api.altcontext.com` plus the production API key. *See `E15-3a-localwp-oci-run-log.md` Settings Applied (Slice 1) and Operator Setup.*
- [ ] Confirm the LocalWP origin is present in `RECOGNITION_ALLOWED_ORIGINS` (`/opt/acx-backend/prod/.env` on the OCI host); if not, add it and restart `acx-prod.service` (`sudo systemctl restart acx-prod`), then retry the probe. *Server-side settings probe did not exercise browser CORS; keep unchecked until Slice 3A browser-origin proof.*
- [ ] Capture a successful probe with a visible correlation ID in the OCI log surface. *See `E15-3a-localwp-oci-run-log.md` Probe Result (Slice 1) and OCI log excerpt.*

### Checklist for Slice 2: Scan round-trip against seeded media

- [ ] Seed the LocalWP media library with the provenance-tracked demo image set and run a Workbench scan.
- [ ] Capture backend correlation IDs, latency evidence, and a redacted recognition payload snapshot in `E15-3a-localwp-oci-run-log.md` (backend-only source per the Non-Goals note).
- [ ] Record before/after screenshots showing the green round-trip state, representative avatar rendering from `thumb_url` or the explicit fallback state, and monotonic progress/completion semantics.
- [ ] Package those screenshots/transcripts as the named E15-22 proof bundle so E15-3 and E15-5 can reuse the exact same evidence set.

### Checklist for Slice 3: Security boundary checks

- [ ] Capture privileged-endpoint CORS rejection evidence from a non-allowlisted origin.
- [ ] Create a throwaway production-scoped test key, drive a deterministic 429 on that key, and record the rate-limit headers/body evidence.
- [ ] Revoke the throwaway key immediately after capture and record the revocation timestamp in the run log.

### Checklist for Slice 4: Sovereign local-read fallback (public-firewall deterministic timeout)

- [ ] Read the effective key source in Settings > Alt Context and record it with the original key fingerprint; identify the owning option, constant, environment (reported as `constant`), or filter, and record the production URL and its source.
- [ ] Replace the effective key at its owning source with `acx_offline_probe_placeholder` (Settings field, `ACX_RECOGNITION_API_KEY` constant in `wp-config.php`, PHP runtime environment variable, or `acx_recognition_api_key` filter); reload Settings and require the same key source and placeholder fingerprint (`****lder`) before changing the URL. Restore and stop on a mismatch.
- [ ] Choose an operator-owned OCI instance's public (global) IP and a WordPress-permitted port (80, 443, or 8080; commonly 8080) unopened in its VCN security list, which silently drops unsolicited SYNs; never use a third-party address. RFC 5737/3849 documentation addresses fail with `acx_egress_denied` and cannot stand in for this timeout path.
- [ ] Replace ADDRESS and PORT with the chosen values and, on the LocalWP machine itself, run `curl -sS --connect-timeout 5 --max-time 10 -o /dev/null -w '%{time_connect}\n' https://ADDRESS:PORT/` on that exact port; require exit 28, a connect-phase error ("Connection timed out after ..." or "Failed to connect ... Timeout was reached"), and `time_connect=0.000000`. For "Operation timed out ... bytes received", a TLS error, or any other result, choose another eligible port and repeat; do not proceed.
- [ ] With the effective placeholder key confirmed, set the verified `https://ADDRESS:PORT/` at the owning URL source (Settings option only for option-managed keys; otherwise `ACX_RECOGNITION_URL` or `acx_recognition_base_url` filter); confirm the effective target URL in Settings before triggering a request.
- [ ] Install the literal temporary `wp-content/mu-plugins/acx-offline-probe-log.php` shown in Slice 4 on the LocalWP machine; log only `acx_sync_pull_failed` context/message, never request arguments, headers, or the key.
- [ ] Click **Sync now** once in the existing plugin Workbench to trigger one sync pull; copy the single `acx_sync_pull_failed` cURL error 28 connect-timeout log line beside the cached-state screenshot / annotated transcript and outage-facing sync status (`sync_health=offline`, headline **Recognition service unreachable — showing your local copy.**, badge **Offline**; `apps/prototype-wp-alt-context/js/admin/pages/workbench/syncVocabulary.ts:21-22`). No line, URL validation, a blocked port, `acx_egress_denied`, `acx_egress_pin_failed`, other egress errors, TLS/transfer timeouts, or any other failure invalidate the probe: restore, remove the logger, and stop.
- [ ] Restore the original production URL (`https://api.altcontext.com`) at the same URL source first, then the real API key at the same key source, including if verification fails; delete `wp-content/mu-plugins/acx-offline-probe-log.php` and confirm it is gone; reload Settings and confirm the original effective URL/source and key fingerprint/source before closing the slice.

## Review Readiness

- [ ] Every slice leaves matching evidence in the run log or decision record before the next slice starts.
- [ ] Any CORS allowlist change, temporary key lifecycle action, or fallback UX discrepancy is documented on the same pass that discovers it.
- [ ] MCP handoff records one slice-complete write per slice plus the final gate verdict.

## Success Criteria

- [ ] All six E15-3a MVP exit criteria are satisfied with one redacted run log covering all four slices.
- [ ] The run log proves representative avatar visibility via the backend `thumb_url` path or explicit fallback behavior, plus a monotonic processed indicator with `Scan complete` appearing only at UI-ready completion.
- [ ] E15-3 is explicitly unblocked only after the LocalWP -> OCI gate passes end to end.

## Handoff

After each slice, record the outcome in MCP handoff (`close_slice` or `record_event` with a `slice_complete_*` decision) before moving on to the next slice.

When done, set `E15-3a` status to `done`, archive task state, and notify E15-3 that WP-host provisioning is unblocked. If the gate fails, file a blocker against the active handoff and stop; **do not start E15-3**.
