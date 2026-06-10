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

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Compose | `apps/prototype-description-service/docker-compose.demo.yml` (new) or `infra/oci/demo/` | WP+MariaDB stack, limits |
| Caddy | repo-tracked Caddyfile (source of truth); `make deploy-demo` rsyncs it to `/opt/acx-backend/Caddyfile` + `caddy reload` | demo vhost; VM-local Caddyfile edits forbidden (drift guard) |
| Make | root `Makefile` | `deploy-demo` target |
| Bootstrap | `infra/oci/demo/bootstrap-wp.sh` (new) | wp-cli install + plugin + constants |
| Packaging | plugin build script | zip/dist artifact for container install |
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

Changes: compose + Caddy vhost + DNS + systemd + make target + limits.
Proof: curl matrix green; `docker stats` shows limits; API latency unchanged under demo load (basic ab/hey check).

### Slice 2: WP bootstrap + tenant provisioning + WP hardening

**Goal**: WP configured non-interactively with the ACX plugin against the live API using an explicitly minted demo tenant/key, hardened for public exposure.

WP hardening deliverables (the epic's security baseline covers only the API; a public WP admin is its own attack surface): generated strong admin credentials stored in the secrets `.env`, xmlrpc disabled, login rate limiting at the Caddy vhost, WP core/plugin auto-updates enabled, and an optional nightly demo-content reset documented as a runbook step.

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
- [ ] WP hardening landed (creds in secrets env, xmlrpc off, login rate limit, auto-updates, reset runbook)
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
