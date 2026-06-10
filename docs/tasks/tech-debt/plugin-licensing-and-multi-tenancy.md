# Plugin Usage, Licensing, and Multi-Tenancy Models

> **Type**: tech-debt registry + today's-default decision
> **Date**: 2026-06-08
> **Owner task**: `MAINT-demo-usage-model-20260608`
> **Scope**: How end users consume the ACX plugin (tenancy ownership × licensing/entitlement), which model the **public demo uses today**, and which richer models are **parked** as future goals.
> **Related**: [public-demo-oci-cohost-launch-plan.md](../../operations/public-demo-oci-cohost-launch-plan.md) · [E16 SaaS Foundation epic](../../epics/v0.3.1/saas-foundation-epic.md) · [roadmap-saas-operations.md](../../roadmaps/roadmap-saas-operations.md) · [self-hosting-epic.md](../../epics/v0.3.1/self-hosting-epic.md) · [E15-3](../15.0/E15-3-wordpress-demo-provisioning-task-plan.md)

---

## Decision — today's default (fastest path to a published demo)

For the initial public demo at `demo.altcontext.com`, use the **single-tenant, shared-login, password-gated** model exactly as the [OCI co-host launch plan](../../operations/public-demo-oci-cohost-launch-plan.md) already specifies:

- **Topology**: one co-hosted WordPress install (`acx-demo-wp` compose stack + its own MariaDB) on the existing OCI VM, behind the existing Caddy edge.
- **Backend tenancy**: one existing backend tenant + one server-side demo API key. No per-demo tenant provisioning.
- **Content**: one seeded media library + roster (the E15-3 / E15-3a seed set).
- **Access (hard requirement met)**: Caddy HTTP Basic Auth edge gate over `wp-login.php`, `wp-admin/*`, and `wp-json/acx/v1/*`, plus one shared WordPress login. If the demo-curator capability/role is not yet built, use a single shared admin with `DISALLOW_FILE_EDIT` / `DISALLOW_FILE_MODS` and snapshot/restore between cohorts (the co-host plan's documented temporary fallback).

**Why this is fastest**: it reuses the already-written co-host plan verbatim and requires **zero net-new plugin code** — no capability/role layer, no multi-tenant key plumbing, no WordPress Multisite, no per-demo isolation. The only net-new monorepo edits are the small Caddy `demo.altcontext.com` site block (+ basicauth) and the demo-stack compose. It also aligns with the co-host plan's existing "Not in this phase" boundary (no unique logins, no multisite), so nothing has to be reversed.

**Scope honesty**: the user's *intended* eventual model is per-demo isolated content (multi-tenant); that is parked below as the highest-priority un-park candidate, not abandoned.

## What today's default does NOT remove

The model choice does **not** unblock the demo on its own. Independent of tenancy model, these pre-publish gates still own the launch. Live status is in `DASHBOARD.txt` / the cited plans — not snapshotted here, which would rot:

| Gate | Blocks |
| ---- | ------ |
| E15-22 seeded-media/LocalWP proof capture | E15-3a Slice 2 |
| E15-3a operator round-trip (Slices 2–4 + browser-origin CORS) | E15-3 provisioning |
| E15-5a budget alerts + Tailscale two-network verification | safe public exposure |
| E15-5 remote E2E + ARM-compat evidence | launch sign-off |
| E15-7 local-sync correctness/audit closure | "backend down → cached" demo story |
| Topology reconciliation: the epic's "WP on separate shared hosting" decision + "Shared PHP hosting provisioned" deliverable/checklist contradict the co-host override (the surfaces the co-host plan flags for reconciliation) | co-host override validity |
| Demo-stack infra (Caddy `demo.altcontext.com` edge-gate block + `acx-demo-wp` compose) not yet tracked in repo | reproducible/reviewable provisioning |

## Usage / licensing model space

Two coupled axes: **deployment/tenancy** × **licensing/entitlement mechanism**.

| Model | Tenancy shape | Backend today | Plugin/license today | Status |
| ----- | ------------- | ------------- | -------------------- | ------ |
| Single-site, shared-login demo | 1 install → 1 tenant, password-gated | supported | API key only | **DEFAULT (today)** |
| Single-site SaaS ("one license per install") | 1 site → 1 tenant, self-serve | supported | API key only; no activation/updates/support gating | owned by E16 (planning) |
| Per-demo / per-client isolated content | 1 owner → N isolated tenants | data isolation supported; no org-above-tenant | none | **PARKED — intended next** |
| Agency / multi-site license (one entity, many independent sites) | 1 account → N tenants + central mgmt | data isolation supported; no org layer | no multi-site tier | PARKED |
| WordPress Multisite network (subsite per client) | 1 network → N subsites→tenants | supported | no network-activation support | PARKED |
| Reseller / white-label | partner → many sub-accounts | partial (keys) | no branding/sub-accounts | PARKED (far) |
| Self-hosted / sovereign backend | 1 site → self-run backend | runs | no software-license/update channel | PARKED (self-hosting epic covers deploy only) |

## Parked future goals (possible, not committed)

Captured so the demo's shortcut does not erase the larger product question. Each is a candidate task, not active scope.

**1. Per-demo / per-client isolated content (multi-tenant).** Bind each demo/site to its own backend tenant + key. Backend already isolates identities/clusters/jobs by `tenant_id`; `scripts.manage_api_keys` provisions keys per environment, and tenant rows are created lazily on first authenticated request today — a dedicated multi-tenant provisioning runbook is itself parked work, not existing tooling. Remaining work is WP-side, gated on a WP isolation-mechanism choice (separate installs vs Multisite vs single-install per-demo profiles). Highest-priority un-park candidate.

**2. Plugin licensing / activation layer.** None exists today (Settings holds only a backend URL + API key). WordPress commercial norm is a license key gating updates + support and counting activations (1-site / 5-site / 25-site / agency). Core decision: is the backend API key the entitlement (SaaS-native, simplest) or is there a separate license key for updates/support/seat-counting (needed for self-hosted/perpetual)? Likely both, split by model.

**3. Account → many-tenant (org) hierarchy.** E16 hard-codes one auth-user ↔ exactly one tenant ("no cross-tenant admin surface in Phase 1"). The agency case needs `account → org → tenant(s) → key(s)` with the org as billing/management parent. This is the structural change behind both the agency model and the per-demo model.

**4. WordPress Multisite support.** Network activation, per-subsite `acx_*` option scoping, per-subsite REST registration, per-subsite key binding. Reverses the co-host plan's current "no multisite" stance when picked up.

**5. Cross-cutting policy decisions.** License↔API-key conflation; activation/seat enforcement; identity-sharing policy across an agency's sites (default strict per-tenant isolation, optional shared public-figures roster); plugin distribution channel (wordpress.org freemium vs Freemius/EDD vs self-hosted license-gated update server); agency pricing axis (per-site bundle vs aggregate volume vs per-seat).

## Current support baseline (what already exists)

- **Backend multi-tenancy**: deep — `tenant_id` on identities, clusters, jobs, centroids, merge-suggestions, cluster-blocks, clustering reports/feedback, audit events, with tenant-scoped repos/routers and per-tenant purge/export services.
- **Key provisioning**: `scripts/manage_api_keys` supports tenant list plus key create/revoke per environment; tenant rows themselves are lazy-bootstrapped on first authenticated request.
- **Single-site SaaS path**: owned by the E16 SaaS Foundation epic (planning; not started) and `roadmap-saas-operations.md` — self-serve signup → tenant → key → metered Free/Pro/Business tiers, vendor auth (WorkOS/Clerk), billing (Polar).
- **Not present**: any plugin license/activation layer; any org/account-above-tenant hierarchy; any WordPress Multisite support.

## Promotion criteria (when to un-park)

Promote a parked model to a dated task plan when its trigger fires (mirrors the co-host plan's Move-Off triggers):

- More than one demo cohort needs concurrent, content-isolated access → un-park model 1 (+ WP isolation-mechanism decision).
- First paying multi-site/agency customer is in sight → un-park models 2 + 3.
- A customer requires WordPress Multisite → un-park model 4.
- E16 implementation begins → fold models 2 + 3 decisions into its account/key design before the 1:1 user↔tenant assumption hardens.
