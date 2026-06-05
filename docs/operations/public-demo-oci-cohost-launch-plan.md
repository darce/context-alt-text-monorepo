# Public Demo OCI Co-host Launch Plan

> **Date**: 2026-06-03  
> **Scope**: Initial live WordPress plugin demo at `demo.altcontext.com`, co-hosted on the existing OCI instance with the live recognition backend at `api.altcontext.com`  
> **Status**: Draft plan for E15 close-out and beta handout  
> **Owner surface**: E15 public-demo launch readiness, especially E15-3, E15-3a, E15-5, and E15-5a

## Decision

For the initial beta phase, run the public WordPress installation and ACX plugin on the same OCI instance that already hosts the recognition backend, behind the existing Caddy edge, using `demo.altcontext.com` for WordPress and `api.altcontext.com` for the backend API. This is a deliberate short-term override of the earlier managed/shared WordPress-host recommendation in the April launch assessment; the long-term direction remains a dedicated PHP/WordPress host once the demo is proven and beta access needs more isolation.

The co-hosted WordPress stack must stay operationally separate from the recognition stack: separate Docker Compose project, separate MariaDB volume, separate WordPress content volume, separate service unit, separate backups, and no reuse of the backend Postgres database. Caddy is the only shared front-door component.

## Source Plan Read

The v0.4.0 and v0.4.1 plans split launch readiness into a small MVP and follow-ons:

- Shipped before this plan: E15 Phase 1 security baseline, E15-1b plugin settings UX, and E15 Phase 2 observability baseline.
- MVP still needed before calling the live plugin launched: E15-3a LocalWP -> OCI gate, E15-3 WordPress provisioning, E15-5 remote E2E plus ARM evidence, and enough E15-5a OCI hygiene to keep the public demo cost-safe, reachable, and recoverable.
- Demo-visual blocker: E15-22 implementation work mostly landed, but the seeded-media/LocalWP proof capture is still required before E15-3 can claim avatar/progress readiness.
- Follow-ons after MVP: E16 keeps CI smoke automation, deeper auth hardening, worker correlation, retry dashboards, and session-lifecycle resilience outside the first launch bar.

Dashboard state at the time of this plan still shows public-demo attention items around `E15-3A-BR-21` and the workbench-avatar-progress maintenance findings. Treat those as pre-launch blockers unless a reviewer explicitly reclassifies or resolves them in MCP.

## Remaining Work To Launch

| Priority | Work | Owning artifact | Exit evidence |
| --- | --- | --- | --- |
| P0 | Finish the E15-22 seeded-media proof bundle: representative avatar evidence, monotonic processed-count evidence, and truthful `Scan complete` timing. | E15-22, E15-3a run log | Reusable proof packet with scan identifier/correlation IDs. |
| P0 | Complete E15-3a LocalWP -> OCI gate before opening `demo.altcontext.com`. | E15-3a | Settings probe, seeded scan, CORS rejection, 429 evidence, local-read fallback, and E15-22 proof bundle in `E15-3a-localwp-oci-run-log.md`. |
| P0 | Finish enough E15-5a hygiene for public demo safety. | E15-5a | Budget alerts tested, Tailscale access verified, dry-run `pg_dump` path proven, Hetzner fallback plan accepted. |
| P0 | Add a demo beta access role/capability path or explicitly accept the temporary shared-admin fallback. | New small plugin hardening slice or E15-3 host decision | Beta users can reach ACX admin pages without broad site-admin power, or the risk is accepted for a short closed cohort. |
| P0 | Stand up co-hosted WordPress at `demo.altcontext.com`. | E15-3 | DNS/TLS works, WordPress installed, ACX plugin ZIP active, backend probe succeeds. |
| P0 | Configure the production demo key server-side. | E15-3 | Raw key lives only in server-local config; run logs record fingerprint only. |
| P0 | Seed demo media and rosters. | E15-3 | 5-10 licensed/provenance-tracked images and expected identities are present. |
| P0 | Capture the live public-demo run log. | E15-3 | `E15-3-mvp-run-log.md` proves scan result, avatar/progress bundle, rollback path, and local-read fallback. |
| P0 | Run E15-5 remote E2E and ARM evidence capture. | E15-5 | `E15-5-mvp-round-trip-log.md` and `E15-5-arm-compat-evidence.md` are filed. |
| P1 | Publish the conversion page around the working demo. | E15-3 content slice | First viewport explains value, shows real screenshot/video proof, and collects beta interest. |
| P1 | Add a reset/restore rhythm for beta cohorts. | E15-3 or ops follow-up | Known-good database/content snapshot can be restored after exploratory tester sessions. |

## Co-hosted Architecture

Run WordPress as an adjacent stack on the OCI host, not inside the recognition backend compose project.

Recommended remote layout:

```text
/opt/acx-backend/              existing recognition envs and Caddy service
/opt/acx-demo-wp/              new WordPress demo stack
  compose.yml                  WordPress + MariaDB, no public ports except Caddy route
  .env                         WordPress DB credentials and local-only stack config
  wp-config.local.php          ACX_RECOGNITION_URL and ACX_RECOGNITION_API_KEY
  data/db/                     MariaDB volume
  data/wp-content/             WordPress content volume
  backups/                     SQL + wp-content snapshots
```

Recommended service shape:

- `wordpress:php8.3-apache` or equivalent PHP 8.3 image, reachable only on a Docker network or loopback-bound port.
- `mariadb:10.11` or MySQL 8-compatible database for WordPress only.
- Existing Caddy adds a `demo.altcontext.com` site block and reverse-proxies to the WordPress container.
- The backend remains on `api.altcontext.com`; do not route plugin traffic through WordPress except through the existing plugin proxy.
- Add `https://demo.altcontext.com` to `RECOGNITION_ALLOWED_ORIGINS` before the plugin settings probe.
- Keep backend deploys and WordPress deploys as separate systemd units, for example `acx-prod.service` and `acx-demo-wp.service`.

Resource guardrails for co-hosting:

- No remote image builds during a scheduled beta demo window.
- Cap WordPress/PHP memory at the container level if the stack shows pressure during the LocalWP/OCI and live-demo runs.
- Keep WordPress uploads small and provenance-controlled; this is not a public arbitrary upload service.
- Back up MariaDB and `wp-content` before every plugin upgrade and before every broader beta cohort.

## Beta Access Mechanism

Use a two-layer shared-access model for the initial beta:

1. **Edge gate:** Caddy HTTP Basic Auth, or Cloudflare Access if it is already in front of the domain, protects `wp-login.php`, `wp-admin/*`, and `wp-json/acx/v1/*`. Issue one shared cohort credential, rotate it per cohort, and keep the password hash only on the server or Cloudflare side. This is the easy handout: one URL plus one cohort passphrase.
2. **WordPress session:** Use one shared WordPress user for the cohort, but avoid giving it full administrator power if possible.

Preferred WordPress authorization hardening before external beta testers:

- Introduce an ACX-specific capability such as `acx_manage_recognition` for Dashboard, Workbench, Roster, recognition job routes, sync-status routes, and other demo actions.
- Keep plugin Settings and backend key mutation behind `manage_options` for the operator only.
- Add a demo role, for example `acx_demo_curator`, with `read`, `upload_files`, and `acx_manage_recognition`, but without `manage_options`, plugin install, theme edit, user management, or options-management capabilities.
- Create one shared WordPress user, for example `acx-beta`, assigned to `acx_demo_curator`.

Temporary fallback if the capability slice cannot land before a closed beta:

- Create one shared WordPress administrator account only for a short, known cohort.
- Keep the Caddy/Cloudflare edge gate on.
- Set `DISALLOW_FILE_EDIT` and, if operationally acceptable, `DISALLOW_FILE_MODS` in WordPress config so shared-admin testers cannot edit theme/plugin files from the browser.
- Keep the backend API key in server-local constants, not in repo files; rotate the key after the cohort if the Settings page or exports could have exposed it.
- Restore the WordPress database/content snapshot after exploratory sessions.

Do not distribute raw backend API keys to beta testers. Do not make `wp-admin` public without the edge gate. Do not create a public upload app in this phase.

## Deployment Sequence

1. Close the LocalWP/OCI proof gates: E15-22 proof capture, E15-3a run log, and any open launch-blocking findings.
2. Record an E15-3 host decision stating that the initial phase is OCI co-hosting, why the previous managed-host recommendation is deferred, and what criteria trigger moving to the dedicated PHP server.
3. Add the `demo.altcontext.com` DNS record to the existing OCI public IP.
4. Provision `/opt/acx-demo-wp` with WordPress, MariaDB, volumes, local secrets, backup directory, and systemd unit.
5. Extend Caddy with a `demo.altcontext.com` route and reload/restart `acx-caddy`.
6. Harden WordPress baseline: disable public registration, disable XML-RPC unless needed, enforce HTTPS admin cookies, set file-edit restrictions, and remove default sample content.
7. Install the ACX plugin from the release ZIP generated by `apps/prototype-wp-alt-context/scripts/release/package-plugin.sh`.
8. Configure `ACX_RECOGNITION_URL=https://api.altcontext.com` and the production demo key in server-local WordPress config. Record only the key fingerprint.
9. Add `https://demo.altcontext.com` to backend CORS allowlist and restart the relevant backend service.
10. Run the plugin Settings probe and capture the response taxonomy.
11. Seed media/rosters, run the Workbench scan, and file `E15-3-mvp-run-log.md` with the E15-22 proof bundle.
12. Create a known-good snapshot: WordPress DB dump, `wp-content` archive, plugin ZIP checksum, Caddy config checksum, and redacted `.env`/config inventory.
13. Run E15-5 remote E2E and ARM evidence capture.
14. Share the beta handout: `https://demo.altcontext.com/wp-admin/admin.php?page=alt-context-workbench`, edge-gate credential, shared WordPress user credential, scope notes, and expected reset cadence.

## Verification Checklist

- `https://demo.altcontext.com/` returns a valid TLS page.
- `https://demo.altcontext.com/wp-login.php` and `wp-admin/*` require the edge-gate credential before WordPress auth.
- The shared WordPress user can reach the ACX Workbench and run the expected demo actions.
- The shared WordPress user cannot change ACX backend URL/API key, install plugins, edit files, manage users, or change site-wide options after the preferred capability hardening lands.
- The plugin Settings probe returns `connected` against `https://api.altcontext.com`.
- A seeded scan returns results and preserves the E15-22 avatar/progress proof bundle.
- Local-read fallback works after forcing the deterministic backend timeout path and is restored afterward.
- Caddy logs and backend correlation IDs can tie a beta session to the corresponding backend requests.
- A pre-beta backup restore has been tested at least once.
- OCI budget alerts and Tailscale access are verified before opening the beta.

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| WordPress compromise affects the backend VM. | Separate compose project, separate DB, no backend secrets in WordPress except the tenant-scoped demo key, edge gate, file-edit restrictions, backups, and short beta windows. |
| Shared credentials remove per-user attribution. | Accept only for closed beta; rotate per cohort; use Caddy/backend timestamps and optional cohort-specific shared credentials for coarse attribution. |
| Shared WordPress admin can alter settings. | Prefer the `acx_manage_recognition` capability slice before external testers; otherwise use shared admin only for a short trusted cohort and restore snapshot afterward. |
| Resource contention hurts recognition latency. | Avoid builds during demo windows, watch `/metrics`, cap WordPress resources if needed, keep seed set small, and move to the dedicated PHP host if pressure appears. |
| Demo API key leaks through settings, backup, or logs. | Store raw key only in server-local config, record fingerprint only, redact backups before moving them off-host, rotate after suspicious sessions. |
| CORS/backend origin mismatch blocks the live site. | Add `https://demo.altcontext.com` to `RECOGNITION_ALLOWED_ORIGINS` before the settings probe and capture the exact env change in the run log. |
| Backups are unproven when a cohort damages state. | Dry-run restore before first beta and keep a known-good snapshot after plugin install plus seed media. |

## Not In This Phase

- Unique beta logins or a self-service account system.
- Public arbitrary uploads or a public recognition API.
- Public access to raw backend API keys.
- Multisite or network activation.
- Reusing backend Postgres for WordPress.
- Exposing phpMyAdmin or database admin tools on the public domain.
- CI smoke automation; this remains in E16 unless it becomes the fastest way to stabilize the launch.

## Move-Off Trigger

Move WordPress to the dedicated PHP host when any of these become true:

- More than one beta cohort needs concurrent access or per-user accountability.
- WordPress/PHP causes observable backend latency or memory pressure during scans.
- The shared-account model becomes insufficient for support or abuse tracking.
- The demo needs a public upload surface.
- The site needs standard WordPress hosting operations such as managed backups, staging, or one-click restores.
