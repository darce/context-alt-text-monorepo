# E15-29. Public Demo Go-Live + Clustering Seed Execution

> **Metadata**
>
> - **Date**: 2026-06-13
> - **Author**: Claude Opus 4.8 (claude-opus-4-8)
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Target Branch**: `feature/e15-29`
> - **Target Worktree**: `/Users/daniel/Development/context-alt-text-monorepo-e15-29`
> - **Review Coverage Target**: 2
> - **Builds on (executes, does not re-implement)**: [E15-28-oci-demo-provisioning-task-plan.md](E15-28-oci-demo-provisioning-task-plan.md) — E15-28 built and **merged** the deployment mechanism (`docker-compose.demo.yml`, the `demo.altcontext.com` Caddy vhost, `mk/deploy.mk:deploy-demo`, `scripts/deploy/sync-demo.sh`, `infra/oci/demo/bootstrap-wp.sh`, `infra/oci/demo/seed/import.sh`, tenant-mint/walkthrough/content-reset runbooks). E15-29 **runs** that kit against the VM and adds the one net-new deliverable (the 100-image clustering seed selector). It calls the kit's commands; it does not restate the kit's deliverables.

## Objective

Take the alt-context recognition demo from "kit built, not deployed" to a **live public WordPress site** seeded with **100 celeb images (≥5 per person)** so face **clustering** is the visible story. Backend is unchanged (recognition-only on `api.altcontext.com`).

## Intake (decision 794)

- **Key Q&A decisions**: handoff decision `claude_intake_e15-29_public_demo_go_live_scope` (id 794).
- **Answers**: DNS = operator will set `demo.altcontext.com`; deploy on the `sslip.io` interim now (`altcontext.com/demo` is off-VM — see Constraints); capability = recognition-only (no VLM); API = production `api.altcontext.com` directly; seed = **100 images, ≥5/person** from `celebs01` to showcase clustering; seed licensing = **fair-use/editorial demo, accepted** (blocker 7 closed — see Open Risks).
- **Not-Doing**: VLM/captioning/GPU host (v0.5+); account DB / signup; CI E2E smoke gate (E16/v0.4.1 Theme D); plugin structural refactor (E18/REFA); any new deploy mechanism (reuse E15-28 kit); any edit to prod/staging/dev API `.env` beyond the single additive CORS origin.

## Problem Statement

E15-28 merged every reusable surface but **none of it has been executed against the VM**. Verified 2026-06-13: `demo.altcontext.com` does **not** resolve (no A-record; `api.altcontext.com` → `129.213.40.111`); `infra/oci/demo/seed/media/` holds only `.gitkeep`; no demo tenant minted; `/opt/acx-backend/demo/secrets/.env` unpopulated; demo origin absent from prod CORS. So the remaining work is **execution + one net-new deliverable**: the 100-image clustering seed. The 100-image ≥5/person target is a **new requirement from intake decision 794** that supersedes E15-28's placeholder "5–10 faces" seed; E15-29 owns the clustering selector and provenance, and reuses E15-28's `seed/import.sh` unchanged.

## Constraints

- **$0/mo incremental** — colocate on the running A1.Flex VM; OCI Always Free; bulkhead container limits already in `docker-compose.demo.yml` protect inference SLO.
- **Live-infra discipline (E15-28 "rule zero")** — never run a VM command whose blast radius you cannot state. Tenant minting and the CORS edit touch **prod** stacks → operator-executed (see Workflow Principles); STOP and record a blocker rather than improvise.
- **Explicit tenant identity** — `00000000-0000-4000-8000-000000000001`, `--site-url <chosen-url>`, never URL-derived/JIT (E15-24); `TenantIdentity::is_auto_derived_identity()` must be false.
- **Constants are the only operative config** — plugin reads PHP `define()`s injected via `WORDPRESS_CONFIG_EXTRA` in `secrets/.env`; no standalone `ACX_*` env vars.
- **Port 80 firewalled** (UFW 22/443 only) — Caddy issues TLS via TLS-ALPN-01 on 443; `http://` demo will not connect; do not edit UFW.
- **Secrets never enter git** — `.env.example` templates only; real values live on the VM (`chmod 600`); seed images stay uncommitted until licensed.
- **Seed glob is jpg/jpeg/png** — both `seed/import.sh:29` and `sync-demo.sh:60` exclude `.webp`; the selector must emit only jpg/jpeg/png (celebs01 has 29 `.webp` to avoid).
- **Apex is off-VM** — `altcontext.com`/`www` → `66.241.124.177` (marketing host), **not** the demo VM `129.213.40.111`. The OCI Caddy serves only `*.altcontext.com` vhosts it terminates; serving `altcontext.com/demo` would require the marketing host to reverse-proxy `/demo/*` → the VM (operator, separate repo) plus a WP subdirectory install. The VM-native interim is `sslip.io`.

## Terminology

- **Demo stack**: `wordpress` + `mariadb` (+ `wpcli` one-shot) from `docker-compose.demo.yml` on external `acx-demo-net`; data under `/opt/acx-backend/data/demo-{wpdata,dbdata}`.
- **Demo tenant**: the explicit tenant row + API key minted for the demo (`00000000-0000-4000-8000-000000000001`).
- **Seed bundle**: the deterministic set of demo face images under `infra/oci/demo/seed/media/` plus the provenance table.
- **Clustering seed selector**: `infra/oci/demo/seed/select-clustering-seed.sh` (net-new) — picks N persons × M images from a source dir to make clustering visible.
- **WP_URL**: the `bootstrap-wp.sh` **shell env var** that drives `wp core install --url=…` (kit default `https://demo.altcontext.com`); distinct from the WordPress `WP_HOME`/`WP_SITEURL` constants.

## Workflow Principles

- **Demo is a tenant, not a special case** — no service-side branches for the demo (rg-009).
- **Execute, don't re-spec** — E15-29 calls `make deploy-demo` / `seed/import.sh` verbatim; it edits the kit only to point at the interim URL until `demo.altcontext.com` DNS lands.
- **Agent vs operator split**: the agent authors/dry-runs commands and records evidence; the **operator executes** any command that mutates a prod stack — minting the demo tenant/key (`manage_api_keys` on the prod VM) and the prod CORS edit + `acx-prod.service` restart. The agent records minted-identity references (never the raw key) in a handoff decision.
- **Slices ↔ epic phase**: Slices 0–4 close the epic's **Phase 3** (WP Demo Provisioning); Phase 4 verification remains E15-4/5/5a per the epic.

## Current State Analysis

- **Works**: backend live (`api.altcontext.com` → `129.213.40.111`); E15-28 kit merged incl. the `demo` Caddy vhost (`Caddyfile:17-27`, with `/xmlrpc.php` 403); `make deploy-demo` (`mk/deploy.mk:158`); plugin builds to `dist/alt-context-0.0.4.zip` (`alt-context.php` Version == `package.json` `0.0.4`).
- **Not done**: `demo.altcontext.com` unresolved; seed empty; tenant unminted; VM `secrets/.env` unpopulated; demo origin not in prod CORS; clustering never exercised on real seed.
- **Misleading if unchecked**: the kit defaults `WP_URL`/`--site-url`/Caddy host to `demo.altcontext.com` — if Slice 0 picks the fallback, those must change in lockstep or TLS/redirects break.

## Open Risks / Launch Blockers

> Tracked live in handoff (blocker id 7, findings `E15-29-PA-*`); not duplicated as a status list here.

1. **Seed licensing — RESOLVED via documented fair-use acceptance (blocker id 7 closed; decision recorded).** `seed/README.md` advises public-domain/generated faces; the operator accepted using `celebs01` celebrity photos under a documented **editorial/fair-use demo rationale** (non-commercial product demonstration, attributed in the provenance table, **takedown-on-request** posture). Every provenance `Source/license` cell records `celebs01 — editorial/fair-use demo (takedown on request)`. Residual likeness/biometric exposure on a public face-recognition page is **accepted for the demo**; revisit if the demo becomes promotional. No longer gates public DNS.
2. **Pre-provisioning gates (E15-28 carry-over) — status known.** **E15-22** (Workbench avatars + honest progress) is **done** (2026-06-12) ✅. **E15-3a** (LocalWP→`api.altcontext.com` round-trip) was a *vendor-spend gate* ("don't buy WP hosting until proven") with no closed handoff row; the $0 colocation topology (no hosting purchase) **obviates its spend rationale**, and its end-to-end proof is **superseded by E15-29 S4's live walkthrough**. Not a real blocker — see Slice 0 gating rule.
3. **Prod CORS restart blast radius.** Appending the demo origin requires restarting `acx-prod.service`; operator-executed; rollback in Rollback Strategy.
4. **DNS / TLS + interim URL.** `demo.altcontext.com` is unset (operator will add the A-record → `129.213.40.111`). The apex `altcontext.com`/`www` → `66.241.124.177` (marketing host, **off-VM**), so `altcontext.com/demo` is **not** servable from the demo VM without a marketing-host proxy (operator, cross-repo). VM-native interim available today: `https://129-213-40-111.sslip.io` (Caddy ALPN-issues a real LE cert, no external DNS). Until the chosen host resolves+propagates, only the demo vhost shows cert errors; **API vhosts must stay green throughout**.

## Deployment Topology (recap — unchanged from E15-28)

Single OCI A1.Flex VM `129.213.40.111`; one Caddy terminates TLS for `api` / `staging.api` / `dev.api` / `demo`, each to a localhost upstream. Demo stack on external `acx-demo-net`. Plugin calls `https://api.altcontext.com` over public DNS (same path a real self-hosted user takes); auth = explicit tenant UUID + minted key; CORS-gated.

## Context Loading

- **Rules**: `docs/workstate/rules/development-workflow.md` (branch isolation, pre-merge gate), `infra/oci/README.md` (env layout, deploy + CORS restart SOP).
- **Contracts/runbooks**: `infra/oci/demo/tenant-mint-runbook.md`, `infra/oci/demo/walkthrough-runbook.md`, E15-1 security baseline (CORS/rate limits), E15-24 tenant identity.
- **Handoff/MCP**: task `E15-29` — decision 794 (intake), blocker 7 (licensing), findings `E15-29-PA-*`; E15-28 plan for carried-over exit criteria.
- **ctx7**: not required (no upstream-library behavior in scope).

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| CORS allowlist | service env (`recognition/config/security.py`) | API-consumer origins; validator rejects `*` | + `https://<demo-host>` (additive) | yes — additive only; explicit origin (scheme+host, no trailing slash) | preflight `curl -X OPTIONS` from demo origin returns `Access-Control-Allow-Origin: <demo>` |
| Caddy demo vhost | infra (`apps/prototype-description-service/Caddyfile`) | `demo.altcontext.com` vhost already present (E15-28) | none, unless Slice 0 picks fallback host (edit host token) | yes — must not disturb 3 API vhosts | `caddy validate` + four-vhost curl matrix |
| Tenant identity | service (`manage_api_keys`) | explicit-UUID tenants | + demo tenant row + key | no — additive | `is_auto_derived_identity()` == false; `/settings/test` connected |
| Plugin packaging | plugin | `npm run release:package` → `dist/alt-context-0.0.4.zip` | none — reuse | no | zip exists + sha256; version header matches |

## Proposed Solution

Run the merged E15-28 kit end-to-end after producing the clustering seed: Slice 0 decides the URL and unblocks DNS; Slice 1 produces the 100-image seed (the only net-new code); Slice 2 stages everything `deploy-demo` consumes (zip, VM secrets, minted tenant); Slice 3 executes CORS + `make deploy-demo` + `seed/import.sh`; Slice 4 proves recognition + clustering end-to-end and closes the pre-merge gate.

## Slice Delivery

### Slice 0 — URL decision + interim deploy target (first; unblocks TLS timing)

**Goal**: Lock the public URL, hand the operator the DNS request, and pick a working interim that needs no external DNS.

- Confirm DNS state: `dig +short demo.altcontext.com` (empty); `dig +short api.altcontext.com` (`129.213.40.111`); `dig +short altcontext.com` (`66.241.124.177` — marketing host, **off-VM**).
- **Target `https://demo.altcontext.com`** (operator-owned): operator adds the A-record `demo` → `129.213.40.111` at the DNS provider (`ns1.unstoppabledomains.com`). Kit defaults already match — **no kit edits** when it lands. Expected propagation: minutes–hours.
- **Interim now (recommended, VM-native): `https://129-213-40-111.sslip.io`** — sslip.io resolves the embedded IP; Caddy ALPN-issues a real LE cert; no external DNS. Edit in lockstep: demo Caddy vhost host token (`Caddyfile`), `WP_URL`/`--site-url` (`bootstrap-wp.sh` env / `secrets/.env`), the tenant `--site-url`, and the CORS origin. Record before/after in the Slice 0 decision.
- **`altcontext.com/demo` (operator-coordinated variant only)**: apex is off-VM, so this needs the **marketing host** (`66.241.124.177`) to reverse-proxy `/demo/*` → `129.213.40.111` (operator, separate repo) **plus** a WP subdirectory install (`WP_HOME`/`WP_SITEURL` = `https://altcontext.com/demo`; Caddy `handle_path /demo/*` on an `altcontext.com` vhost). Out of scope for the VM-side kit; do not attempt VM-only.
- **Record** the URL choice + interim as a handoff decision; file an E15 follow-on to cut the interim over to `demo.altcontext.com` once the A-record propagates.
- **Gate-task check (Risk 2)**: E15-22 is **done** ✅; E15-3a has no closed row but is obviated by $0 colocation and superseded by S4. **Gating rule**: proceed — capture S4's live walkthrough as the E15-3a-equivalent round-trip evidence, or record an explicit operator-waiver decision. Do **not** block on E15-3a.

**Proof**: `dig` output captured; URL + interim decision recorded; operator DNS request noted; gate-task disposition recorded.

### Slice 1 — Clustering seed curation (net-new deliverable)

**Goal**: 100 deterministic images, ≥5 per person, jpg/jpeg/png, staged for import, provenance filled.

- Author `infra/oci/demo/seed/select-clustering-seed.sh` (params via env or flags): `SRC` (default the celebs01 path), `PERSONS` (default 20), `PER_PERSON` (default 5), `OUT` (default `infra/oci/demo/seed/media`). **Selection rule**: rank persons by count of eligible (`.jpg/.jpeg/.png`, excluding `.webp`) images **descending**; ties broken alphabetically by person key; take the top `PERSONS`; copy the first `PER_PERSON` eligible files each as `<person>_<n>.<ext>` into `OUT`. **Error path**: refuse (exit 2) if fewer than `PERSONS` persons have ≥`PER_PERSON` eligible files. Idempotent (clears prior `OUT` selection on re-run). Source verified: 110 persons have ≥5 eligible images.
- Emit `infra/oci/demo/seed/clustering-manifest.txt` — one line per person, `<person> <count>` — and **commit** it (the image files stay uncommitted).
- Fill the provenance table in `seed/README.md` for all 100 (File · Subject label · Source/license · Added). Example row: `al_pacino_10.jpg | Al Pacino | celebs01 — editorial/fair-use demo (takedown on request) | 2026-06-13`. Verify completeness: no `_(operator fills)_` placeholder rows remain.
- **Sanity** (verification commands in Verification Strategy): `ls OUT | wc -l` == 100; every person has ≥5 files (`for p in $(cut -d' ' -f1 clustering-manifest.txt); do find OUT -name "${p}_*" | wc -l; done` all ≥5); zero `.webp` in `OUT`; ≥2 distinct persons. "Distinct images" = ≥5 files with distinct basenames per person.

**Proof**: selector shellcheck-clean; `OUT` has exactly 100 jpg/jpeg/png; per-person ≥5; manifest committed; provenance table complete.

### Slice 2 — Pre-flight provisioning (zip, VM secrets, tenant/key)

**Goal**: Everything `make deploy-demo` consumes exists; demo tenant minted; VM headroom confirmed.

- Build the plugin artifact: from `apps/prototype-wp-alt-context/`, `npm run release:package` → `dist/alt-context-0.0.4.zip` (+`.sha256`). Pre-check versions agree (the script hard-fails on mismatch): `grep -m1 'Version:' apps/prototype-wp-alt-context/alt-context.php` vs `grep -m1 '"version"' apps/prototype-wp-alt-context/package.json` (both `0.0.4`).
- **VM headroom precheck** before colocating: `ssh ubuntu@129.213.40.111` then `free -h` (>1GB free), `df -h /opt` (>20GB free for demo-{wpdata,dbdata}), `docker stats --no-stream` baseline. Record in the smoke log; abort + blocker if insufficient (never shrink inference limits).
- Populate `/opt/acx-backend/demo/secrets/.env` (`chmod 600`) from `infra/oci/demo/.env.example`: strong `WP_ADMIN_*`, MariaDB/WordPress DB passwords, and a single-line `WORDPRESS_CONFIG_EXTRA` with `define('ACX_RECOGNITION_URL','https://api.altcontext.com')`, `ACX_RECOGNITION_SOURCE='service'`, `ACX_RECOGNITION_API_KEY` (prod-minted), `ACX_RECOGNITION_TENANT_ID='00000000-0000-4000-8000-000000000001'`, and `define('WP_AUTO_UPDATE_CORE', true)` (a WordPress core define, not an ACX constant).
- **Mint demo tenant + key (operator-executed)**: the agent prepares the exact `tenant-mint-runbook.md` commands (explicit UUID, `--site-url <chosen-url>`, `manage_api_keys --env prod` quirk); the **operator** runs the final `tenant create` + `create` against the **prod** stack on the VM and pastes the key into `secrets/.env` `WORDPRESS_CONFIG_EXTRA` only. Agent records a handoff decision noting the minted tenant UUID (not the key).
- **Staging dry-run (skip-decision)**: intake chose prod-direct. Either run the optional staging dry-run (re-point `WORDPRESS_CONFIG_EXTRA` to `staging.api.altcontext.com` with a staging key, walk through, re-point to prod) **or** record a `staging-dryrun-skipped-risk-accepted` handoff decision with justification before Slice 3.

**Proof**: `dist/alt-context-0.0.4.zip` + `.sha256` present; VM headroom recorded; `secrets/.env` keys non-empty (names only in evidence); tenant row + key minted; `is_auto_derived_identity()` == false; staging-dry-run done or skip-decision recorded.

### Slice 3 — Execute merged kit: CORS + deploy + seed import

**Goal**: demo stack live behind Caddy with TLS, plugin active, 100 images imported. (Reuses the E15-28 kit; no re-implementation.)

- **CORS (operator-executed)**: append `https://<demo-host>` to `RECOGNITION_ALLOWED_ORIGINS` in `/opt/acx-backend/prod/secrets/.env` (comma-separated, scheme+host, no trailing slash); restart `acx-prod.service` per `infra/oci/README.md`. **Verify**: `systemctl status acx-prod` active, `curl -fsS -o /dev/null -w '%{http_code}' https://api.altcontext.com/health` == 200, demo-origin preflight returns the allow-origin header. Rollback in Rollback Strategy.
- **Deploy (agent)**: `PLUGIN_ZIP=dist/alt-context-0.0.4.zip make deploy-demo`. This runs `sync-demo.sh`: rsync compose/bootstrap/seed/Caddy → create `acx-demo-net` → demo stack up → `bootstrap-wp.sh` (core install + plugin activate) → `caddy validate` + promote → recreate Caddy onto `acx-demo-net` → four-vhost smoke.
- **Seed import (agent)**: on the VM, `cd /opt/acx-backend/demo && ./seed/import.sh` → 100 `wp media import`.
- **Confirm constants in-container**: `docker compose -f docker-compose.demo.yml exec wordpress php -r "require '/var/www/html/wp-config.php'; var_export(ACX_RECOGNITION_URL);"` → `https://api.altcontext.com`.

**Proof**: four-vhost curl matrix green (commands in Verification Strategy; demo TLS valid once DNS propagated); `wp media list` == 100; settings page shows constant-provenance config; `/settings/test` connected against prod; CORS preflight from demo origin passes.

### Slice 4 — E2E proof + clustering verification + close

**Goal**: recorded evidence that recognition **and clustering** work on the live URL.

- Run the walkthrough against the live URL: `ACX_PLAYWRIGHT_TASK_REF=E15-29 WP_BASE_URL=<chosen-url> make demo-walkthrough-proof` (or manual `walkthrough-runbook.md`). **Both overrides are required**: `mk/deploy.mk:167-168` defaults `ACX_PLAYWRIGHT_TASK_REF ?= E15-28` (else artifacts land under `E15-28/`) and `WP_BASE_URL ?= https://demo.altcontext.com` (which won't resolve during the sslip.io interim). Needs `ACX_E2E_WP_ADMIN_USER`/`ACX_E2E_WP_ADMIN_PASS`. Artifacts then land under `apps/prototype-wp-alt-context/local/playwright/E15-29/evidence/`.
- **Clustering assertion (the point of the ≥5/person seed)**: Workbench → trigger scan → wait for completion → confirm the Top Clusters panel shows **multi-image clusters** (≥2 images of one person), not 100 singletons; open the Review drawer for the top cluster; curate by renaming ≥1 cluster to its person label. Capture `evidence/top-cluster.png`, `evidence/review-drawer.png`, `evidence/curated-cluster.png`.
- **Clustering acceptance gate**: ≥1 multi-image cluster must appear. If only singletons despite ≥5/person seed → investigate face-detection rate / embedding dispersion / dataset quality, record a finding, and escalate to owner — do **not** silently pass.
- **Sovereignty check**: `docker stop` the API (staging-safe first if a staging stack exists), confirm curated data still readable + honest degraded banner (E15-26 — banner states data is from local cache and recognition is paused; capture `evidence/degraded-banner.png`), restart, confirm recovery (`evidence/recovered.png`).
- Paste evidence into `docs/tasks/15.0/E15-29-demo-smoke-log.md` (reuse E15-5/E15-28 headings); link handoff decision IDs.
- **Pre-merge gate**: ≥1 review pass with findings recorded in MCP, fresh `test_result` tied to HEAD, slice-complete decision, `handoff_close_check(enforce=True)` passes.

**Proof**: smoke log filled; multi-image cluster screenshot; degraded-banner + recovery screenshots; `handoff_close_check(enforce=True)` passes.

## Rollback Strategy

- **`make deploy-demo` fails after Caddy promote**: `sync-demo.sh` already stages `Caddyfile.bak.*` / `docker-compose.caddy.yml.bak.*`; if an API vhost breaks, restore the `.bak` and `docker compose -f docker-compose.caddy.yml up -d`, re-smoke, record a blocker. Do not debug forward while an API vhost is dark.
- **Demo stack itself wedged**: `docker compose -f docker-compose.demo.yml down` (**never** `-v` — that deletes the demo volumes); fix; re-run.
- **Seed import fails mid-run**: confirm plugin active (`wp plugin list`), re-run `./seed/import.sh` in isolation (idempotency: dedupe by re-checking `wp media list` count).
- **CORS restart leaves API red**: restore the prior `RECOGNITION_ALLOWED_ORIGINS` value, restart `acx-prod.service`, re-check `/health`; operator verifies no typo before retrying.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Seed selector (new) | `infra/oci/demo/seed/select-clustering-seed.sh` | deterministic N-persons × M-images picker, jpg/jpeg/png only |
| Seed manifest (new, committed) | `infra/oci/demo/seed/clustering-manifest.txt` | `<person> <count>` per line |
| Seed provenance | `infra/oci/demo/seed/README.md` | fill provenance table for 100 images; note ≥5/person clustering intent |
| Smoke log (new) | `docs/tasks/15.0/E15-29-demo-smoke-log.md` | E2E + clustering + sovereignty evidence |
| Caddy / compose / bootstrap (fallback only) | `Caddyfile`, `bootstrap-wp.sh`/`secrets/.env` | host-token + `WP_URL`/`--site-url` edits **only if** Slice 0 picks sslip.io |
| Epic | `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md` | mark Phase 3 live once Slice 4 passes (planning-review gate on the edit) |

## Related Files

| File | Note |
| --- | --- |
| `infra/oci/README.md` | env layout + CORS restart SOP (operator) |
| `infra/oci/demo/tenant-mint-runbook.md` | explicit-UUID tenant + key minting (operator-executed) |
| `infra/oci/demo/walkthrough-runbook.md` | E15-28 deliverable, reused for Slice 4 evidence shape |
| `infra/oci/demo/bootstrap-wp.sh` / `seed/import.sh` / `scripts/deploy/sync-demo.sh` | the merged kit E15-29 executes |
| `docs/tasks/15.0/E15-28-oci-demo-provisioning-task-plan.md` | prerequisite mechanism + carried-over exit criteria |
| `docs/tasks/15.0/E15-5-mvp-round-trip-log.md` | prior smoke-log format to mirror |

## Verification Strategy

- **Deterministic (repo/CI-equivalent)**:
  - `shellcheck infra/oci/demo/seed/select-clustering-seed.sh`
  - selector output: `ls infra/oci/demo/seed/media | wc -l` == 100; `find infra/oci/demo/seed/media -iname '*.webp' | wc -l` == 0; per-person `find … -name '<person>_*' | wc -l` ≥ 5
  - `docker compose -f apps/prototype-description-service/docker-compose.demo.yml config`
  - `make check-all`
- **Runtime-parity**: optional staging dry-run (or recorded skip-decision) before prod cutover.
- **Contract/fixture**: four-vhost matrix — `for h in api staging.api dev.api <demo-host>; do printf '%s ' "$h"; curl -fsS -o /dev/null -w '%{http_code}\n' "https://$h.altcontext.com/" || echo FAIL; done` (api/staging.api/dev.api expect 200/redirect; demo expects 200 once DNS+TLS land). CORS preflight: `curl -fsS -D - -o /dev/null -X OPTIONS 'https://api.altcontext.com/recognition/health' -H 'Origin: https://<demo-host>' -H 'Access-Control-Request-Method: GET'` → `Access-Control-Allow-Origin: https://<demo-host>`.
- **Manual**: scan → recognition → **clustering** (≥1 multi-image cluster) → curation; kill-API sovereignty banner; recovery.

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded `infra/oci/README.md`, tenant-mint + walkthrough runbooks, E15-1/E15-24 contracts, E15-28 carry-over criteria.
- [ ] Confirmed `ctx7` not required.
- [ ] Recorded CORS + Caddy boundary ownership/compatibility in slice-close decisions.

### Slice 0: DNS + URL decision

- [ ] `dig` baseline captured; UD A-record editability spiked.
- [ ] URL choice recorded as a handoff decision (fallback edits listed if sslip.io).
- [ ] Gate-task (E15-3a/E15-22) status + gating decision recorded.

### Slice 1: Clustering seed curation

- [ ] `select-clustering-seed.sh` authored, shellcheck-clean, idempotent, with the documented selection rule + error path.
- [ ] 100 jpg/jpeg/png in `seed/media`, ≥5/person, zero webp; `clustering-manifest.txt` committed.
- [ ] `seed/README.md` provenance table complete (no placeholder rows).

### Slice 2: Pre-flight provisioning

- [ ] `dist/alt-context-0.0.4.zip` built; version headers match.
- [ ] VM headroom (`free`/`df`/`docker stats`) recorded.
- [ ] `secrets/.env` populated; demo tenant + key minted by operator (explicit UUID); `is_auto_derived_identity()` false.
- [ ] Staging dry-run done OR skip-decision recorded.

### Slice 3: Execute kit (CORS + deploy + import)

- [ ] Prod CORS appended + restarted (operator) with verification green; API vhosts stayed up.
- [ ] `make deploy-demo` succeeded; four-vhost matrix green; constants confirmed in-container.
- [ ] `./seed/import.sh` imported 100; `/settings/test` connected.

### Slice 4: Proof + close

- [ ] Walkthrough evidence captured; ≥1 multi-image cluster screenshot (clustering acceptance gate met).
- [ ] Sovereignty degraded-banner + recovery captured; smoke log filled + decision IDs linked.
- [ ] Pre-merge gate: review pass + fresh test_result at HEAD + slice-complete decision + `handoff_close_check(enforce=True)` passes.

## Review Readiness

- [ ] CORS + Caddy boundary changes have matching verification evidence (preflight header + four-vhost matrix).
- [ ] Runtime-parity covered (staging dry-run or recorded skip) so the manual walkthrough is not masked by fixtures.
- [ ] Handoff decisions record DNS choice, tenant mint (UUID only), CORS restart, and each slice close.
- [ ] Licensing blocker (id 7) dispositioned (fair-use demo accepted) with provenance table filled.

## Success Criteria

- [ ] A public visitor loads the live demo URL (the `sslip.io` interim now; `demo.altcontext.com` once the operator's A-record lands) over valid TLS and sees the plugin with **real recognition results** from `api.altcontext.com`.
- [ ] The media library holds **100 seed images, ≥5 per person**, and the Workbench **clusters** them by identity (≥1 multi-image cluster, not singletons).
- [ ] Seed licensing dispositioned (blocker 7) — **documented fair-use demo, accepted** — with the provenance table filled.
- [ ] Demo runs at $0/mo incremental with inference SLO intact (`docker stats` within limits).
- [ ] Killing the API container leaves curated data readable with an honest degraded banner.
- [ ] `handoff_close_check(enforce=True)` passes; epic Phase 3 marked live.
