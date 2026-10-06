# E15-3. WordPress Demo Provisioning (MVP-critical)

> **Task Short ID**: E15-3
> **Status**: scoped -- not started
> **Epic**: [E15. Public Demo Launch Readiness](../../epics/v0.4.0/public-demo-launch-readiness-epic.md) Phase 3
> **Predecessors**: E15-1 (security baseline) merged; E15-2 (observability baseline) merged; [E15-22](./E15-22-workbench-avatar-and-progress-readiness-task-plan.md) demo-critical Workbench UI gate passed locally, with entity avatars, Top Cluster face samples, and Review Cluster member rows rendering from seeded media; [E15-3a](./E15-3a-localwp-oci-roundtrip-task-plan.md) LocalWP -> OCI round-trip verification gate passed. Backend at `api.altcontext.com` verified.
> **Blocks**: E15-5 (remote E2E verification) -- needs a WP origin to round-trip against. MVP completion signal.
> **Provider stance**: provider-agnostic. Concrete host selected at task-start via an ADR-lite decision record. Scope covers requirements, not a vendor.

---

## Objective

Stand up a publicly accessible WordPress instance running the ACX plugin, pointed at the live recognition backend, such that a product demo URL can be shared and a curator can trigger a scan that round-trips through the backend.

Do not purchase or provision the shared WP host until [E15-3a](./E15-3a-localwp-oci-roundtrip-task-plan.md) LocalWP -> OCI round-trip verification passes and local/LocalWP evidence shows the Workbench entity-avatar path is demo-ready: populated clusters must show real thumbnails in entity avatars and Top Cluster cards, and the Review Cluster drawer must list member faces instead of "No members found" for clusters with face counts.

This task does not claim demo readiness from request success alone. Before the public demo is treated as ready, the manual run log must also carry the avatar/progress proof bundle defined by [E15-22](./E15-22-workbench-avatar-and-progress-readiness-task-plan.md): representative avatar rendering from the backend `thumb_url` path or an explicit fallback state, a monotonic processed indicator, and `Scan complete` appearing only when the Workbench is actually UI-ready.

## MVP Exit Criteria

The task is complete when all of the following are true:

1. A public URL loads a WordPress site with the ACX plugin installed and active.
2. The plugin Settings page shows a successful backend connection probe against `api.altcontext.com` with a production API key.
3. A curator can open the plugin Workbench, trigger a scan against seeded media, and see recognition results returned with entity avatar thumbnails, Top Cluster face samples, and Review Cluster member rows rendered, with the run log carrying the avatar/progress proof bundle required by [E15-22](./E15-22-workbench-avatar-and-progress-readiness-task-plan.md).
4. HTTPS is enforced (Cloudflare Full/Strict or host-native TLS).
5. The host selection and configuration is captured in a short decision record co-located with this plan.

Anything beyond these five items (CI smoke harness, multi-site, custom theme, public DNS on a branded domain) is out of scope for MVP.

## Non-Goals (explicit)

- Automated E2E smoke gate -- owned by [E15-6](./E15-6-e2e-smoke-gate-automation-stub.md) and deferred to [E16. Public Demo Follow-Ons](../../epics/v0.4.1/public-demo-followons-epic.md).
- Local-sync audit closure -- owned by [E15-7](./E15-7-local-sync-completion-and-audit-closure-task-plan.md) (E15 Phase 6, in progress) and therefore not in E15-3 scope.
- User-account database / multi-tenant seating -- deferred per E14 "Deferred Follow-On: User-Account Database".
- VLM / Phi-3.5 captioning -- out of MVP per E15 constraint "Recognition-only".

---

## Host Selection Criteria (provider-agnostic)

The chosen host MUST satisfy all of the following. Vendor is decided at task-start by writing a one-page decision record (`docs/tasks/15.0/E15-3-host-decision-record.md`) that captures the chosen vendor, the plan tier, and how each criterion is met.

| Criterion | Requirement |
| --------- | ----------- |
| PHP | 8.1+ with `curl`, `json`, `mbstring`, `xml`, `gd` or `imagick` |
| MySQL / MariaDB | 8.0+ / 10.6+ |
| HTTPS | Let's Encrypt, Cloudflare, or host-native TLS |
| Cron | Real system cron OR a reliable WP-Cron external ping |
| Resource floor | >= 512MB PHP memory_limit, >= 1GB disk for WP core + plugin + seed media |
| Plugin policy | Allows custom plugin installs (WordPress.com lower tiers are disqualified) |
| Outbound | Can reach `api.altcontext.com` over HTTPS without vendor-level egress filtering |
| Budget | <= $5/mo per E15 constraint |

Candidate pool documented in [self-hosting-epic.md § Frontend Tier](../../epics/v0.3.1/self-hosting-epic.md#frontend-tier-wordpress-hosting----recommended-shared-phpmysql): Hostinger Premium, Namecheap Stellar, IONOS Essential, DreamHost Shared Starter, or Oracle VPS co-hosting. The decision record MUST state why the chosen option was preferred over the others.

## Slice Plan

### Slice 1 -- Host decision + provisioning

- Confirm the local/LocalWP Workbench UI gate is already evidenced: seeded-media clusters render entity avatars, Top Cluster face samples, and Review Cluster member rows without placeholder/error thumbnails for populated clusters.
- Write `E15-3-host-decision-record.md` capturing chosen vendor, plan, annual cost, and criterion matrix.
- Purchase/provision hosting.
- Confirm PHP version, MySQL version, cron mode, HTTPS, and egress to `api.altcontext.com` from host shell (`curl -sSf https://api.altcontext.com/health/detailed`).
- Place Cloudflare in front if host-native TLS is not viable; otherwise use host TLS directly.

Exit: `curl -I https://<chosen-wp-host>/` returns 200 on the default WP page with a valid cert.

### Slice 2 -- WordPress + ACX plugin install

- Install WordPress via host tooling or WP-CLI.
- Upload ACX plugin from this monorepo (`apps/prototype-wp-alt-context/`) as a deployable ZIP produced by the existing build pipeline; document the exact build command used.
- Activate plugin; confirm no PHP fatal errors in host error log.
- Configure plugin Settings:
  - Backend base URL: `https://api.altcontext.com`
  - API key: freshly provisioned production key (recorded in the decision record with key fingerprint only, never the raw key).
- Run the plugin's `/settings/test` connection probe; capture the outcome-taxonomy response in the run log.

Exit: Settings page reports a successful probe against the live backend.

### Slice 3 -- Demo content seed + manual round-trip

- Seed ~5-10 images into the WP media library using a recognizable sample set (non-sensitive, non-copyrighted; document provenance).
- Open the plugin Workbench, trigger a scan, observe recognition results rendered for the seed media.
- Capture a short run log (`E15-3-mvp-run-log.md`) with: scan timestamp, number of images, observed latency, any errors, and a screenshot or annotated transcript.
- Include the [E15-22](./E15-22-workbench-avatar-and-progress-readiness-task-plan.md) proof bundle in that run log: at least one representative avatar render from the backend `thumb_url` path or an explicit fallback screenshot/transcript, the processed-count progression, and the point at which `Scan complete` appears.
- Reuse the E15-3a seeded-media proof artifacts when they still match the public-demo build; if any artifact must be recaptured on the public site, keep the same proof-bundle headings so E15-5 can consume the public-demo evidence without redefining acceptance criteria.
- Verify the sovereign local-read path renders cached state when the backend is intentionally unreachable:
  - Before changing the backend URL, read the effective key source in Settings > Alt Context and record it with the current production API key fingerprint in the run log (fingerprint only, never the raw key). Identify the owning configuration: option, constant, environment, or filter. Settings reports environment-managed keys as `constant`; distinguish them using the deployment configuration. Also record the effective production URL and its owning source for restoration.
  - Replace the effective API key with the obviously fake, non-empty placeholder `acx_offline_probe_placeholder` at its owning source: for an option-managed key, use the Settings field; for a constant, change `ACX_RECOGNITION_API_KEY` in `wp-config.php`; for an environment-managed key, change the PHP runtime's `ACX_RECOGNITION_API_KEY` variable; for a filter-managed key, change the code providing `acx_recognition_api_key`. Reload/restart the PHP runtime if needed to apply the change. Before changing the URL, reload Settings and confirm the same reported key source and the placeholder's fingerprint (the masked suffix is `****lder`). If either does not match, restore and stop. Keep this effective placeholder set throughout the offline probe so no real credential can be sent to the test endpoint.
  - Choose the public (global) IP of an operator-owned OCI instance and one of WordPress's default safe-request ports, **80, 443, or 8080**, that its VCN security list does not open (commonly **8080**); OCI silently drops unsolicited SYNs to that port. Never use a third-party address. An arbitrary port can be rejected by `wp_safe_remote_request` before connecting. RFC 5737/3849 documentation addresses fail before any connection with `acx_egress_denied` and cannot stand in for the timeout path. Replace ADDRESS and PORT below with those operator-chosen values.
  - On the WordPress host itself (the demo WordPress VM, not the operator laptop), run `curl -sS --connect-timeout 5 --max-time 10 -o /dev/null -w '%{time_connect}\n' https://ADDRESS:PORT/` against that exact port. Proceed only if it exits 28 with a connect-phase error ("Connection timed out after ..." or "Failed to connect ... Timeout was reached") and prints `0.000000` for `time_connect`. "Operation timed out ... bytes received", a TLS error, or any other result does not prove the connect-timeout path: choose another eligible port and repeat the pre-check; do not proceed.
  - With the effective placeholder key confirmed, temporarily set the backend URL to the verified `https://ADDRESS:PORT/` through its owning source: the Settings URL option only for option-managed keys; for deployment-managed keys, use `ACX_RECOGNITION_URL` in `wp-config.php` or the code providing the `acx_recognition_base_url` filter. Do not rely on a saved URL option with a deployment-managed key. Reload Settings and confirm the effective target URL matches the probe URL before triggering a request.
  - Before triggering the probe, create `wp-content/mu-plugins/acx-offline-probe-log.php` on the demo WordPress VM (create the `mu-plugins` directory if absent) with only the following content. The `acx_sync_pull_failed` payload exposes `context` and `message`, but sync status stores only the failure classification; see `apps/prototype-wp-alt-context/src/sovereign/sync/class-sync-pull-job.php:144-151` and `:196-199`. Log only those two fields, never request arguments, headers, or the key. Do not use `http_api_debug`, whose arguments include the Authorization header.

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

Exit: run log filed with the E15-22 avatar/progress proof bundle; local-read path verified; Phase 3 MVP exit criteria fully satisfied.

## Deliverables

- `docs/tasks/15.0/E15-3-host-decision-record.md` (host selection ADR-lite)
- `docs/tasks/15.0/E15-3-mvp-run-log.md` (manual round-trip evidence, including the E15-22 avatar/progress proof bundle that E15-5 reuses during live-demo execution)
- `docs/tasks/15.0/E15-3-mvp-run-log.md` keeps a named `E15-22 proof bundle` section with: representative avatar evidence (`thumb_url` or explicit fallback), monotonic processed-count evidence, `Scan complete` timing evidence, and the run identifier/correlation notes tying the screenshots/transcript to the seeded-media scan.
- Host decision record (or adjacent operator note) includes the plugin update/rollback procedure used after initial provisioning.
- Demo URL + WP admin URL recorded in the handoff (as task state, not checked into the repo)
- Production API key fingerprint logged against the key lifecycle surface from E15-1

## Dependencies Not Owned Here

- DNS pointing a public hostname at the WP host (recorded in the decision record; if using a subdomain of a domain the team already controls, no action needed beyond an A/CNAME record).
- Cloudflare account (free tier acceptable).
- Production API key provisioned from the E15-1 key lifecycle surface.

## Risks

- **Shared hosting PHP constraint surprises** -- disk or memory limits break scan path. Mitigation: host selection criteria above, plus a pre-install `phpinfo()` capture in the decision record.
- **Outbound egress blocked by host** -- shared hosts sometimes block outbound HTTPS on non-standard ports. Mitigation: the backend only uses 443, which is universally allowed; the host-shell `curl` check in Slice 1 catches this before WP install.
- **API key exposure** -- raw key could end up in site exports or backups. Mitigation: key fingerprint only in decision record; raw key stored in host env/config only; never committed.

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Do not add rows like `(BR-04 closed)` or "resolve handoff issue X"; finding status lives in MCP / `DASHBOARD.txt`.

## Context and Ownership

- [ ] Loaded the host-selection constraints, backend contract anchors, and handoff state before provisioning.
- [ ] Verified the Workbench entity-avatar/review-drawer gate locally before any host purchase or provisioning work.
- [ ] Confirmed no extra external dependency context is required beyond the cited self-hosting epic, backend health surface, and WP host constraints.
- [ ] Kept task ownership clean: E15-3 provisions the public WP demo, while E15-5, E15-5a, E15-6, and E15-7 stay in their declared scopes.

### Checklist for Slice 1: Host decision + provisioning

- [ ] Capture local/LocalWP seeded-media proof that entity avatars, Top Cluster face samples, and Review Cluster member rows render for populated clusters.
- [ ] Write `E15-3-host-decision-record.md` with the vendor, plan tier, annual cost, and criterion matrix.
- [ ] Provision the chosen host and verify PHP/MySQL/cron/HTTPS plus outbound reachability to `api.altcontext.com`.
- [ ] Capture a valid-cert `curl -I https://<chosen-wp-host>/` success result before moving on.

### Checklist for Slice 2: WordPress + ACX plugin install

- [ ] Install WordPress, upload the deployable ACX plugin ZIP from `apps/prototype-wp-alt-context/`, and activate it without PHP fatals.
- [ ] Configure the plugin to use `https://api.altcontext.com` plus a freshly provisioned production key, recording only the fingerprint.
- [ ] Capture a successful `/settings/test` probe in the run log with the exact build command used.

### Checklist for Slice 3: Demo content seed + manual round-trip

- [ ] Seed the demo media library with the provenance-tracked image set and run a manual Workbench scan.
- [ ] File `E15-3-mvp-run-log.md` with timestamp, image count, latency, errors, and screenshot or annotated transcript evidence.
- [ ] Include the E15-22 avatar/progress proof bundle in that run log: representative avatar render from `thumb_url` or explicit fallback evidence, monotonic processed-count evidence, and the `Scan complete` timing.
- [ ] Preserve the E15-22 proof-bundle headings so E15-5 can reuse the artifact without redefining avatar/progress success criteria.
- [ ] Read the effective key source in Settings > Alt Context and record it with the original key fingerprint; identify the owning option, constant, environment (reported as `constant`), or filter, and record the production URL and its source.
- [ ] Replace the effective key at its owning source with `acx_offline_probe_placeholder` (Settings field, `ACX_RECOGNITION_API_KEY` constant in `wp-config.php`, PHP runtime environment variable, or `acx_recognition_api_key` filter); reload Settings and require the same key source and placeholder fingerprint (`****lder`) before changing the URL. Restore and stop on a mismatch.
- [ ] Choose an operator-owned OCI instance's public (global) IP and a WordPress-permitted port (80, 443, or 8080; commonly 8080) unopened in its VCN security list, which silently drops unsolicited SYNs; never use a third-party address. RFC 5737/3849 documentation addresses fail with `acx_egress_denied` and cannot stand in for this timeout path.
- [ ] Replace ADDRESS and PORT with the chosen values and, on the demo WordPress VM itself, run `curl -sS --connect-timeout 5 --max-time 10 -o /dev/null -w '%{time_connect}\n' https://ADDRESS:PORT/` on that exact port; require exit 28, a connect-phase error ("Connection timed out after ..." or "Failed to connect ... Timeout was reached"), and `time_connect=0.000000`. For "Operation timed out ... bytes received", a TLS error, or any other result, choose another eligible port and repeat; do not proceed.
- [ ] With the effective placeholder key confirmed, set the verified `https://ADDRESS:PORT/` at the owning URL source (Settings option only for option-managed keys; otherwise `ACX_RECOGNITION_URL` or `acx_recognition_base_url` filter); confirm the effective target URL in Settings before triggering a request.
- [ ] Install the literal temporary `wp-content/mu-plugins/acx-offline-probe-log.php` shown in Slice 3 on the demo WordPress VM; log only `acx_sync_pull_failed` context/message, never request arguments, headers, or the key.
- [ ] Click **Sync now** once in the existing plugin Workbench to trigger one sync pull; copy the single `acx_sync_pull_failed` cURL error 28 connect-timeout log line beside the cached-state screenshot / annotated transcript and outage-facing sync status (`sync_health=offline`, headline **Recognition service unreachable — showing your local copy.**, badge **Offline**; `apps/prototype-wp-alt-context/js/admin/pages/workbench/syncVocabulary.ts:21-22`). No line, URL validation, a blocked port, `acx_egress_denied`, `acx_egress_pin_failed`, other egress errors, TLS/transfer timeouts, or any other failure invalidate the probe: restore, remove the logger, and stop.
- [ ] Restore the original production URL (`https://api.altcontext.com`) at the same URL source first, then the real API key at the same key source, including if verification fails; delete `wp-content/mu-plugins/acx-offline-probe-log.php` and confirm it is gone; reload Settings and confirm the original effective URL/source and key fingerprint/source before closing the slice.

## Review Readiness

- [ ] The decision record, run log, and handoff state together capture host choice, live probe success, and manual round-trip proof.
- [ ] No public-demo boundary is left undocumented when a host, TLS, DNS, or API-key choice changes.
- [ ] The public-demo operations surface includes a tested plugin hotfix/rollback path, not just the initial install command.
- [ ] E15-5 is expected to consume the same E15-3/E15-22 proof bundle during live-demo execution instead of redefining avatar/progress success criteria.
- [ ] E15-5 is notified only after all five MVP exit criteria are evidenced.

## Success Criteria

- [ ] A public WordPress demo URL is live with the ACX plugin active and successfully probing `api.altcontext.com`.
- [ ] A curator can run the seeded-media demo path and see recognition results, entity avatar thumbnails, Top Cluster face samples, and Review Cluster member rows on the live site with the evidence checked into the named docs.
- [ ] Operators can promote a plugin hotfix to the live demo and roll back to the prior ZIP using the documented procedure captured during Slice 2.
- [ ] The demo proof bundle is strong enough that E15-5 can reuse it for live-demo execution without redefining avatar/progress correctness, including the backend-`thumb_url` representative evidence.

## Handoff

When done, set `E15-3` status to `done`, archive task state, and notify E15-5 that it is unblocked.
