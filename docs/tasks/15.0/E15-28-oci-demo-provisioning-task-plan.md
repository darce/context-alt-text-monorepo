# E15-28. OCI-Hosted WordPress Demo Provisioning (E15-3 Revision)

> **Metadata**
>
> - **Date**: 2026-06-10
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Target Branch**: `feature/e15-28`
> - **Review Coverage Target**: 2
> - **Companion assessment**: [E15-24-architecture-coherence-assessment.md](E15-24-architecture-coherence-assessment.md)
> - **Supersedes**: the shared-PHP-hosting topology in [E15-3-wordpress-demo-provisioning-task-plan.md](E15-3-wordpress-demo-provisioning-task-plan.md). E15-3's exit criteria and pre-provisioning gates carry over; its hosting decision does not.
> - **Literature citation convention**: short form `release-it.md §Bulkheads` refers to `literature/extracted/refactoring/distilled/release-it.md`. **The `literature/` directory is gitignored and exists only in the root checkout** (`~/Development/context-alt-text-monorepo/literature/...`) — read it from there, not from your task worktree.

## Objective

`demo.altcontext.com` serves a public WordPress site with the ACX plugin, hosted as containers on the existing OCI A1 VM behind the existing Caddy, talking to `api.altcontext.com` with a properly provisioned demo tenant + API key. Self-hosted user plugins connecting to the central service remain the product model; the demo is just the first such "user."

## Problem Statement

The epic's Phase 3 plan assumed ~$2–5/mo shared PHP hosting with the design rationale "inference VPS should not run PHP." Direction has changed: OCI hosts both the recognition service and the WP demo. The epic's Design Decisions table and E15-3's deliverables (Hostinger, Cloudflare-fronted external host) no longer match intent. The A1.Flex VM (4 ARM cores / 24GB) has ample headroom for a WP + MariaDB container pair, the Caddy reverse proxy already terminates TLS for three API subdomains and can route a fourth, and an all-OCI topology removes a vendor, a payment, and a DNS seam — at the price of colocating demo load with inference (mitigated below with container resource limits, per Release It's bulkhead pattern).

## Constraints

- $0/mo target: stay within OCI Always Free allowances; no new paid services.
- Pre-provisioning gates from the epic still bind: E15-3a LocalWP→OCI round-trip gate must pass, and the Workbench avatar/review-drawer proof must pass, before public exposure (the epic's "truthful demo surface" rule).
- Bulkhead: WP containers get CPU/memory limits so demo traffic cannot starve inference (Release It: bulkheads; chain-reaction risk on a single VM).
- Demo tenant uses the E15-24 identity model: explicit tenant + key minted via `manage_api_keys`, never URL-derived/JIT.
- Plugin reaches the API via public DNS (`api.altcontext.com`), not the docker network — the demo must exercise the same path a self-hosted user does (E15-5 round-trip realism).
- Security posture from E15-1 applies: demo origin added to CORS allowlist; demo key rate-limited like any tenant key.

## Workflow Principles

- The demo is a tenant, not a special case: no service-side code branches for the demo site (rg-009 — no task-specific logic in generic modules).
- Everything reproducible from the repo: compose file, Caddy block, WP bootstrap script, seed content all under `infra/oci/` or `apps/` — `make deploy-demo` shape, no snowflake VM state.
- Demo content is fixture data: deterministic seed media with known faces so E2E assertions and demo walkthroughs are repeatable.

## Terminology

- **Demo stack**: `wordpress` (php-fpm/apache official image, ARM64) + `mariadb` containers in their own compose project + docker network, systemd unit `acx-demo.service`.
- **Demo tenant**: tenant row + API key minted explicitly for `https://demo.altcontext.com`.
- **Seed bundle**: versioned set of demo media (faces) + WXR/import script.

## Current State Analysis

- VM topology (infra/oci/README.md): prod/staging/dev API stacks as systemd-managed compose projects; Caddy (`acx-caddy.service`) routes three subdomains; DNS A records exist for api subdomains — `demo` record needs adding.
- E15-3 plan (shared hosting) drafted but not started; no money spent — clean pivot point.
- E15-3a round-trip and E15-22 avatar gates: pending; unchanged by this revision.
- Plugin install path: monorepo plugin needs a build/package step to land in the WP container (`wp-content/plugins/alt-context`).

## Target Outcome

`make deploy-demo` (or documented compose equivalent) brings up the demo stack on the VM; Caddy serves `https://demo.altcontext.com` with Let's Encrypt TLS; WP is installed/configured non-interactively (wp-cli in container) with the ACX plugin activated, `ACX_RECOGNITION_URL=https://api.altcontext.com`, `ACX_RECOGNITION_SOURCE=service` and the demo API key set via constants in `wp-config.php` (read-only in UI by design — operators see provenance per E15-25); seed media imported; scan → recognition → curation walkthrough works end-to-end; container limits keep inference SLO intact under demo load.

## Context Loading

- Rules: `docs/workstate/rules/development-workflow.md`, `infra/oci/README.md` (deployment workflow, env layout)
- Contracts: E15-1 security baseline (CORS/rate limits), E15-24 tenant identity plan, E15-3a proof bundle checklist
- Handoff/MCP: E15-28 ref; E15-3/E15-3a/E15-5 plans for carried-over exit criteria.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Caddyfile routing | infra | 3 API subdomains | + demo vhost → WP container | yes — must not disturb API vhosts | caddy validate + smoke curl all 4 hosts |
| CORS allowlist | service env | API-consumer origins | + `https://demo.altcontext.com` | yes — additive env change | pytest config + manual preflight |
| Plugin packaging | plugin | LocalWP symlink dev flow | reproducible build artifact into container volume | no — additive packaging path | install smoke in compose |
| Epic Phase 3 | docs | shared-hosting deliverables | revised topology recorded in epic | n/a docs | planning review |

## Proposed Solution

Slice 1: infra — demo compose project (`docker-compose.demo.yml` parameterized like `docker-compose.env.yml`), DNS record, Caddy vhost, systemd unit, container resource limits, `make deploy-demo`. Slice 2: WP bootstrap — non-interactive install via wp-cli, plugin build+install step, constants-based configuration (tenant/key/URL from the secrets `.env`), demo tenant + key minting runbook step via `manage_api_keys`. Slice 3: content + proof — seed bundle import, demo walkthrough runbook, E2E smoke against the public URL (reusing E15-5/E15-6 evidence shapes), epic Phase 3 text updated to the new topology.

## Junior Implementer Guide

> Read this before touching anything. This task touches LIVE infrastructure — the same VM serves prod. **Rule zero: never run a command against the VM whose blast radius you cannot state.** Anything that restarts `acx-prod.service`, edits prod's `.env`, or touches `prod-pgdata` is out of scope and requires the operator. If a step requires it, STOP and record a blocker.

### Why this task exists (didactic)

Colocating the demo WP with inference on one VM is a deliberate trade. `release-it.md §Bulkheads (5.3)` is the mitigation: partition capacity (container CPU/memory limits) so demo traffic cannot starve inference; §Chain Reactions (4.2) is the failure mode being prevented — on a shared host, one overloaded service drags down its neighbors. §Configuration Files (14.2) drives the per-env secrets layout (config outside the image, version-controlled templates, secrets chmod 600), and the staged bring-up (staging API first, then prod) is the §Zero-Downtime expand/rollout/cleanup shape applied to provisioning. The "demo is a tenant, not a special case" principle is rg-009 in product form, and `designing-data-intensive-applications.md §Offline-Capable Replicas` is what the kill-the-API sovereignty walkthrough in Slice 3 demonstrates to visitors.

### Assumed setup

`make task-start TASK=E15-28 …` → repo work in the worktree; VM work over SSH (Tailscale per E15-5a; check `infra/oci/README.md` § SSH access). Per slice: `record_event(test_result)` → `close_slice` → `render_handoff(kind='dashboard')`.

### Verified context anchors (re-verify each — infra docs drift)

| What | Where | Re-verify with |
| --- | --- | --- |
| Three-env topology (prod/staging/dev, subdomains, systemd units, pgdata paths) | `infra/oci/README.md` ~§324-333 | open the README; sections move |
| Parameterized compose template | `apps/prototype-description-service/docker-compose.env.yml` (`ACX_ENV`, `ACX_IMAGE_TAG`, `ACX_PGDATA_PATH`, `ACX_NETWORK_NAME`, per-env secrets `.env`) | read the file — your demo compose copies this parameterization style |
| VM layout | README ~§595-616 (`/opt/acx-backend/{prod,staging,dev}/`, `data/`, Caddyfile, `docker-compose.caddy.yml`) | read on the VM: `ls /opt/acx-backend/` |
| Deploy workflow + image tagging | README ~§379-422 (`make deploy-dev`, `REMOTE_BUILD=1`, `:ENV_TAG` + `:SHA`) | read the Makefile targets |
| Key minting CLI | `manage_api_keys` (README ~§569) — **known quirk: requires `--env prod` even when targeting staging/dev DSNs** | try `--help` on the VM before scripting it; if the quirk blocks demo-tenant minting, record a finding, don't patch around it silently |
| CORS allowlist | env var `RECOGNITION_ALLOWED_ORIGINS` — comma-separated origin list parsed at `apps/prototype-description-service/recognition/config/security.py` ~68-73; a field validator REJECTS `*` (explicit origins only); applied in `api/main.py` `allow_origins=` | `grep -n "RECOGNITION_ALLOWED_ORIGINS" apps/prototype-description-service/recognition/config/security.py` |
| Plugin packaging script | `apps/prototype-wp-alt-context/scripts/release/package-plugin.sh`, run as `npm run release:package` FROM the plugin dir; writes `<repo-root>/dist/alt-context-<version>.zip` + `.sha256`; aborts if `alt-context.php` header Version ≠ `package.json` version; runs `npm run build` + `composer install --no-dev` unless `--no-build` | `grep -n "release:package" apps/prototype-wp-alt-context/package.json` |
| UFW rules — **only 22/tcp and 443/tcp are open; port 80 is NOT** | `infra/oci/cloud-init.yaml` ~lines 86-90 | read before assuming a port is reachable |

### Slice 1 notes — demo stack infrastructure

- Model `docker-compose.demo.yml` on `docker-compose.env.yml`'s parameterization (own project name, own network `acx-demo-net`, own data dirs `demo-wpdata`/`demo-dbdata` under `/opt/acx-backend/data/`). Services: `wordpress` (official image, pick the current `php8.x-apache` tag — it is multi-arch and runs on ARM64/A1) + `mariadb` (11.x, also multi-arch). Verify image availability for `linux/arm64` with `docker manifest inspect <image> | grep arm64` before committing to tags.
- Bulkhead limits: non-swarm compose supports `cpus:` and `mem_limit:` per service — cap WP+MariaDB well below the 4-core/24GB envelope (suggested start: WP 1.0 cpu / 2g, MariaDB 0.5 cpu / 1g; record actuals in the slice decision). Verify post-deploy with `docker stats --no-stream`.
- Caddy: the live Caddyfile (`apps/prototype-description-service/Caddyfile`, the repo-tracked source of truth — currently 3 vhosts) already routes three subdomains. Add the `demo.altcontext.com` vhost there with `reverse_proxy demo-wp:80` (this plan's drift rule: VM-local Caddyfile edits forbidden).
- Caddy networking (catastrophic if skipped): Caddy reaches each upstream only because `docker-compose.caddy.yml` joins that env's external network; today it joins `acx-prod-net`/`acx-staging-net`/`acx-dev-net` ONLY. You MUST (a) add `acx-demo-net` (`external: true`) to `docker-compose.caddy.yml`'s `services.caddy.networks` and its top-level `networks:` block, and (b) give the demo WP service the network alias `demo-wp` on `acx-demo-net`. A config-only `caddy reload` CANNOT attach a new docker network to the running Caddy container — after adding `acx-demo-net` you must RECREATE Caddy (`cd /opt/acx-backend && docker compose -f docker-compose.caddy.yml up -d`, which recreates on the network change), not reload-only. Skip this and the demo vhost returns 502 (upstream `demo-wp` unresolvable). Plain vhost edits against an already-joined network may use `caddy reload`.
- No existing Caddyfile deploy automation: `mk/deploy.mk` and `scripts/deploy/` carry no Caddyfile rsync/reload (the VM Caddyfile is hand-maintained), so `make deploy-demo` must build the rsync + validate + Caddy-recreate path from scratch, modeled on the env-compose deploy (`scripts/deploy/sync-compose.sh` is the closest existing shape).
- **Caddy change procedure (follow in order — prod traffic flows through this container):**
  1. Stage rollback on the VM first: `cp /opt/acx-backend/Caddyfile /opt/acx-backend/Caddyfile.bak && cp /opt/acx-backend/docker-compose.caddy.yml /opt/acx-backend/docker-compose.caddy.yml.bak`.
  2. Bring the demo stack up BEFORE touching Caddy — `acx-demo-net` must already exist (`docker network ls | grep acx-demo-net`) or the Caddy recreate fails on the external-network reference and prod routing goes down with it.
  3. Rsync the repo-tracked `Caddyfile` + `docker-compose.caddy.yml` to `/opt/acx-backend/`.
  4. Validate config syntax: `docker run --rm -v /opt/acx-backend/Caddyfile:/etc/caddy/Caddyfile:ro caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile` (the VM has no host `caddy` binary — validate inside the image Caddy actually runs).
  5. Recreate: `cd /opt/acx-backend && docker compose -f docker-compose.caddy.yml up -d` (compose recreates on the network change; reload-only CANNOT join a new network).
  6. Smoke all FOUR vhosts immediately: `for h in api staging.api dev.api demo; do curl -fsS -o /dev/null -w "%{http_code} $h\n" https://$h.altcontext.com/ || echo "FAIL $h"; done` (demo's host is `demo.altcontext.com`, adjust the loop accordingly).
  7. Any API vhost broken → rollback NOW: restore both `.bak` files, `docker compose -f docker-compose.caddy.yml up -d`, re-smoke, then record a blocker with the failing output. Do not debug forward while prod is dark.
- Port 80 is firewalled (UFW allows only 22/443 — cloud-init ~86-90) even though the Caddy compose publishes `80:80`. Consequences: ACME HTTP-01 cannot work — Caddy issues certs via TLS-ALPN-01 on 443 (that is why the existing three vhosts have TLS), and `http://demo.altcontext.com` will never connect or redirect. Both are expected; do NOT "fix" by editing UFW (operator decision, out of scope) and do not misread a hanging port-80 curl as a Caddy failure.
- DNS: `demo` A record to the OCI IP — operator action (external dependency); request it early, note it in the run log. Until DNS resolves AND the record propagates, Caddy cannot complete the TLS-ALPN challenge for the demo vhost — expect cert errors on the demo host (only) in the interim; the API vhosts must stay green throughout.
- systemd unit `acx-demo.service`: copy an existing env unit (`systemctl cat acx-staging.service` on the VM) and substitute paths.

### Slice 2 notes — WP bootstrap + tenant + hardening

- **Bootstrap sequence (numbered — `bootstrap-wp.sh` implements exactly this order):**
  1. Wire WP↔MariaDB via the standard official-image env vars, all sourced from `demo/secrets/.env` via `env_file:`: MariaDB gets `MARIADB_DATABASE/MARIADB_USER/MARIADB_PASSWORD/MARIADB_ROOT_PASSWORD`; WordPress gets the matching `WORDPRESS_DB_HOST=<mariadb-service-name>`, `WORDPRESS_DB_NAME`, `WORDPRESS_DB_USER`, `WORDPRESS_DB_PASSWORD`.
  2. Give MariaDB a healthcheck (`healthcheck: test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]` — shipped in the official mariadb image) and make `wordpress` `depends_on: condition: service_healthy`, mirroring the postgres pattern in `docker-compose.env.yml` ~20-33.
  3. Wait for WP itself before wp-cli: the WP entrypoint copies core files into the volume on first boot; poll until `wp core is-installed` exits 0 or 1 cleanly (vs. DB-connection errors) before running install.
  4. One-shot wp-cli: define a `wpcli` service in the same compose file (`image: wordpress:cli`, same `volumes:`, same network, same `env_file:`, `profiles: ["tools"]` so it does not start with `up`), then `docker compose -f docker-compose.demo.yml run --rm wpcli wp core install --url=https://demo.altcontext.com --title="ACX Demo" --admin_user="$WP_ADMIN_USER" --admin_password="$WP_ADMIN_PASSWORD" --admin_email="$WP_ADMIN_EMAIL" --skip-email`. `wp core install` is idempotent-safe to gate on `wp core is-installed`.
  5. Install + activate plugin: `run --rm wpcli wp plugin install /tmp/alt-context.zip --activate` (bind-mount the packaged zip into the wpcli service) or unzip directly into the volume at `wp-content/plugins/alt-context` and `wp plugin activate alt-context`.
- Plugin constants: the official WP image supports the `WORDPRESS_CONFIG_EXTRA` env var (arbitrary PHP appended to `wp-config.php`) — define `ACX_RECOGNITION_URL`, `ACX_RECOGNITION_SOURCE` ('service'), `ACX_RECOGNITION_API_KEY`, `ACX_RECOGNITION_TENANT_ID` there from the secrets env. Constant provenance renders read-only in the settings UI by design (E15-25's `isReadOnly()` path) — that is the desired demo posture. **Quoting trap:** compose interpolates `$` inside YAML values, and the PHP you embed (e.g. `define('ACX_RECOGNITION_API_KEY', '...')`) plus any literal `$` must survive two layers. Safest: set `WORDPRESS_CONFIG_EXTRA` in the secrets `.env` file (env-file values are NOT compose-interpolated) and reference it as `WORDPRESS_CONFIG_EXTRA=${WORDPRESS_CONFIG_EXTRA}`; if you must inline it in YAML, escape literal dollars as `$$`. Verify the rendered result inside the container: `docker compose exec wordpress php -r "require '/var/www/html/wp-config.php'; var_export(ACX_RECOGNITION_URL);"`.
- Plugin packaging: an existing path already ships — `apps/prototype-wp-alt-context/scripts/release/package-plugin.sh`, invoked as `npm run release:package` from `apps/prototype-wp-alt-context/` (NOT a repo-root script). It runs `npm run build` + `composer install --no-dev` into a staging tree and writes `<repo-root>/dist/alt-context-<version>.zip` + `.sha256`; it hard-fails if the `alt-context.php` header Version and `package.json` version disagree — check both before building. Reuse/extend it (do NOT add a new build script); `make deploy-demo` ships the `dist/` zip to the VM.
- Demo tenant + key: the demo must NEVER depend on URL-derived/JIT identity. Note the trap: the documented reset workflow (`scripts/deploy/_derive_tenant_id.py`, README §561-568) DERIVES the tenant UUID from `site_url` by default, so "mint with `site_url=…`" alone yields a URL-derived UUID and silently violates this constraint. Instead, create the tenant with an EXPLICIT non-derived UUID — `tenant create --tenant <explicit-uuid> --site-url https://demo.altcontext.com`, then `manage_api_keys --env prod create --tenant <explicit-uuid>` (the `--env prod` quirk applies). Set that same UUID as the `ACX_RECOGNITION_TENANT_ID` constant via `WORDPRESS_CONFIG_EXTRA`. The plugin already supports this constant — E15-24 has landed (`apps/prototype-wp-alt-context/src/api/class-tenant-identity.php` `resolve()`/`get_constant_value('ACX_RECOGNITION_TENANT_ID')`). Pairing proof: `TenantIdentity::is_auto_derived_identity()` MUST return false for the demo tenant and the settings pairing test MUST pass.
- Bring-up order (staged rollout): first configure against `staging.api.altcontext.com` with a staging key; only after the full walkthrough passes re-point constants to `api.altcontext.com` with the prod demo key.
- Hardening checklist is normative, not optional: generated strong admin creds in secrets env; xmlrpc disabled (block `/xmlrpc.php` at the Caddy vhost — simpler and stronger than a WP plugin); login rate limiting deferred (the `rate_limit` directive is the third-party caddy-ratelimit module, absent from stock `caddy:2-alpine`; enabling it requires a custom xcaddy image — do not add the directive to the stock-image Caddyfile or `caddy validate` fails for every vhost); WP auto-updates on (`WP_AUTO_UPDATE_CORE` constant via `WORDPRESS_CONFIG_EXTRA`); nightly content-reset documented as optional runbook step.
- CORS: append `https://demo.altcontext.com` to `RECOGNITION_ALLOWED_ORIGINS` (comma-separated; the validator at `recognition/config/security.py` ~75-82 rejects `*`, so list the origin explicitly — scheme + host, no trailing slash, no path) in the target env's secrets `.env`; restart that env's stack per README workflow (staging first).

### Slice 3 notes — seed + proof + epic revision

- Seed bundle: deterministic media with known faces under `infra/oci/demo/seed/` + wp-cli import script. Faces must be license-clean (generated or public-domain); record provenance in the seed README — a public demo with unlicensed faces is a launch blocker of its own.
- E2E evidence: reuse the E15-5 evidence format (`docs/tasks/15.0/E15-5-mvp-round-trip-log.md` shows the shape). The sovereignty demonstration: `docker stop` the API container (staging first!), show curated data still readable + degraded banner (E15-26), restart, show recovery.
- Epic edit: revise Phase 3 + the Design Decisions row ("WP on separate shared hosting" → OCI colocated with bulkheads) and run `make plan-review DOC=docs/epics/v0.4.0/public-demo-launch-readiness-epic.md` on the edit — epic revisions take the planning-review gate.

### Pitfalls / stop conditions

- The pre-provisioning gates still bind: E15-3a round-trip + Workbench avatar proof must pass before the demo DNS goes public. Going live with placeholder thumbs violates the epic's truthful-demo rule.
- Never `docker compose down -v` anything under `/opt/acx-backend` — `-v` deletes named volumes; prod/staging data lives there.
- Secrets never enter git: templates (`.env.example`) in repo, real values only on the VM. Run `git diff --staged` before every commit in this task specifically to check for leaked values.
- If the A1 VM lacks headroom (check `free -h`, `nproc`, `df -h /opt` before Slice 1), record a blocker with the numbers — do not shrink inference's resources to make room.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Compose | `apps/prototype-description-service/docker-compose.demo.yml` (new) or `infra/oci/demo/` | WP+MariaDB stack, limits |
| Caddy (vhost) | `apps/prototype-description-service/Caddyfile` (repo-tracked source of truth) | add `demo.altcontext.com` vhost → `reverse_proxy demo-wp:80`; VM-local edits forbidden (drift guard) |
| Caddy (network) | `apps/prototype-description-service/docker-compose.caddy.yml` | add `acx-demo-net` (external) to caddy networks; deploy recreates Caddy (not reload-only) so it joins the new net |
| Make | `mk/deploy.mk` (included by root `Makefile`; alongside `deploy-dev/staging/prod`) | `deploy-demo` target: rsync Caddyfile+caddy compose, validate, recreate Caddy |
| Bootstrap | `infra/oci/demo/bootstrap-wp.sh` (new) | wp-cli install + plugin + constants |
| Packaging | `apps/prototype-wp-alt-context/scripts/release/package-plugin.sh` (existing; `npm run release:package` from the plugin dir → `dist/alt-context-<version>.zip`) | reuse/extend for container-install artifact (no new script) |
| Seed | `infra/oci/demo/seed/` | media bundle + import script |
| Docs | epic Phase 3 + `infra/oci/README.md` | revised topology + runbook |

## Verification Strategy

- Deterministic tests: compose config validation (`docker compose config`), bootstrap script shellcheck, packaging build in CI-equivalent (`make check-all` surfaces).
- Runtime-parity: staged bring-up on the VM against `staging.api` first, then re-point to prod API for launch.
- Contract/fixture: curl matrix — all four vhosts TLS-valid; CORS preflight from demo origin passes; API rate-limit headers present on demo key.
- Manual: full walkthrough — upload seed media, trigger scan, see recognition results, curate, kill API container, verify sovereign local-read + degraded banner (E15-26), restore.

## Slice Delivery

### Slice 1: Demo stack infrastructure

**Goal**: `https://demo.altcontext.com` serves a stock WP install behind Caddy with bulkhead limits.

Changes: compose + Caddy vhost + Caddy `acx-demo-net` join (compose recreate) + DNS + systemd + make target + limits.
Proof: curl matrix green (all four vhosts, incl. demo via `demo-wp` upstream); `docker stats` shows limits; API latency unchanged under demo load (basic ab/hey check).

### Slice 2: WP bootstrap + tenant provisioning + WP hardening

**Goal**: WP configured non-interactively with the ACX plugin against the live API using an explicitly minted demo tenant/key, hardened for public exposure.

WP hardening deliverables (the epic's security baseline covers only the API; a public WP admin is its own attack surface): generated strong admin credentials stored in the secrets `.env`, xmlrpc disabled, login rate limiting deferred pending a custom xcaddy Caddy image (stock caddy:2-alpine lacks the rate_limit module), WP core/plugin auto-updates enabled, and an optional nightly demo-content reset documented as a runbook step.

Changes: bootstrap script; plugin packaging; constants config; key-minting runbook; CORS entry; hardening steps above.
Proof: fresh `make deploy-demo` from clean state reaches a configured admin; settings page shows constant-provenance config; `/settings/test` passes against prod API.

### Slice 3: Seed content + end-to-end proof + epic revision

**Goal**: a visitor-facing demo with repeatable content and recorded E2E evidence; epic reflects the topology.

Changes: seed bundle + import; walkthrough runbook; smoke evidence (E15-5 format); epic Phase 3 update.
Proof: scan-to-curation walkthrough recorded; offline sovereignty demonstration recorded; planning-review pass on epic edit.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded infra README, E15-1 security contracts, E15-24 identity plan.
- [ ] Confirmed E15-3a + Workbench gates status before public DNS cutover.
- [ ] Boundary rows recorded in slice-close decisions.

### Checklist for Slice 1: Infrastructure

- [ ] Demo compose + Caddy + DNS + systemd + limits landed in repo
- [ ] curl matrix + load sanity evidence captured
- [ ] Evidence recorded

### Checklist for Slice 2: Bootstrap + tenant

- [ ] Non-interactive bootstrap + packaging + constants config working from clean state
- [ ] Demo tenant/key minted via CLI; CORS updated
- [ ] WP hardening landed (creds in secrets env, xmlrpc off, auto-updates, reset runbook; login rate limit deferred — needs custom xcaddy image)
- [ ] Evidence recorded

### Checklist for Slice 3: Content + proof

- [ ] Seed bundle + walkthrough + smoke evidence captured
- [ ] Epic Phase 3 revised; planning review run
- [ ] Slice-complete decision + dashboard render

## Review Readiness

- [ ] No demo-specific branches in service or plugin code.
- [ ] Reproducibility: clean-VM bring-up documented and tested.
- [ ] Handoff decisions per slice.

## Success Criteria

- [ ] Public visitor loads `https://demo.altcontext.com`, sees the plugin demo with real recognition results from `api.altcontext.com`.
- [ ] Demo runs at $0/mo incremental cost with inference SLO protected by container limits.
- [ ] Killing the API container leaves the demo's curated data readable with an honest degraded banner.
