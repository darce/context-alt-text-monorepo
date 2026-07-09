# Scope: Secrets & Auth Consolidation

> **Task:** `MAINT-secrets-consolidation-20260708` · branch `feature/maint-secrets-consolidation-20260708`
> **Type:** Scope note (pre-assessment intake). Downstream: per-phase task plans.
> **Date:** 2026-07-08
> **Intake decision:** `claude_scope_intake_secrets_consolidation` (id 1717) — read live via `search_handoff`.

## Goal

Reign in scattered `.env`/secret authentication across the three services so that (1) local onboarding is one documented step, (2) every secret has one documented owner and source of truth, and (3) production/demo secret rotation is a single-place operation. Make `/admin` (DB-backed keys) the single source of truth for tenant API keys.

## Intake answers (operator-confirmed 2026-07-08)

- **Primary driver:** all three co-equal — local-dev onboarding friction, no single source of truth, prod/demo rotation & drift.
- **In scope:** all four secret classes — app-auth, infra, test creds, WP/human accounts.
- **Static allowlist `RECOGNITION_ALLOWED_API_KEYS`:** retire; DB-only via `/admin` (delete-over-flag, greenfield).
- **Ceiling:** external secrets manager, **OCI Vault**-leaning (already on OCI; shipping to prod soon).

## Assessment — the real problem

There is not one secrets problem but **five trust domains** smeared across files with no ownership map. Consolidation ≠ one file (a DB password ≠ a human login ≠ a machine key); it = **one documented owner per secret + one fetch mechanism + one manager for prod**.

| # | Trust domain | Secrets | Canonical source (target) | Scattered today |
|---|---|---|---|---|
| 1 | Infra | `PG*` / `APP_PG*`, OCI/deploy | env (local) / **OCI Vault** (prod) | `apps/prototype-description-service/.env`, `infra/oci/demo/.env` |
| 2 | Service root-of-trust | `RECOGNITION_ADMIN_TOKEN` | env / **OCI Vault** | service `.env` |
| 3 | **Tenant API keys** (plugin→service) | minted keys | **service DB via `/admin`** | *both* DB **and** static `RECOGNITION_ALLOWED_API_KEYS` env ← the drift |
| 4 | Human accounts | WP admin user/pass | WordPress user store (per site) | `infra/oci/demo/.env` (`acx-demo-admin`), LocalWP |
| 5 | Test creds | `ACX_E2E_WP_ADMIN_*` | gitignored `.env.local` | `apps/prototype-wp-alt-context/.env.local` |

**Root cause:** no documented source-of-truth per secret; domain #3 has *two* sources (env allowlist + DB) — the exact thing `/admin` exists to own. Plus a **dead root `.env`** and undocumented `.env.example`s.

**Grounding (verified):**
- `/admin` (`recognition/interface_adapters/http/routers/admin.py`) mints/revokes tenant API keys in the service DB; gated by `RECOGNITION_ADMIN_TOKEN` (header) or HTTP Basic (browser console) via `deps/admin_auth.py`.
- Plugin→service auth resolves (precedence) `ACX_RECOGNITION_API_KEY` constant → `acx_recognition_api_key` filter → `acx_recognition_api_key` WP option (Settings page). Not a `.env`.
- `apps/prototype-description-service/.env` holds `PG*`/`APP_PG*`, `RECOGNITION_ADMIN_TOKEN`, `RECOGNITION_RUNTIME_MODE`, `RECOGNITION_AUTH_ENABLED`, `RECOGNITION_API_KEY_HEADER`, `RECOGNITION_ALLOWED_API_KEYS`.
- Root `.env` is empty/dead. `wp-alt-context/.env.local` holds only Playwright creds.

## Off-the-shelf secrets managers (options)

| Option | Fit | Trade-off |
|---|---|---|
| **OCI Vault + KMS** ⭐ | Native to OCI. VM fetches secrets via **instance principals** → no bootstrap secret on host. KMS-backed, IAM-scoped, rotation-capable, ~free. | OCI lock-in; weak local-dev story → keep env for local. |
| **SOPS (age/KMS)** | Encrypted secrets *in git*; great for the demo `docker-compose` path + excellent local story (one age key). | Static (no dynamic rotation); still a file. Complement to Vault, not a replacement. |
| **Doppler / Infisical** | Best DX; one system for local+prod+rotation, CLI injection. | External SaaS (Doppler) / self-hosted service (Infisical) — new dependency & trust surface, not OCI-native. |
| **HashiCorp Vault** | Most powerful (dynamic/leased secrets). | Heavy ops cost — overkill now (YAGNI). |

**Recommendation:** **OCI Vault** for the OCI-hosted runtime (instance principals = only the VM's *identity* unlocks secrets; nothing plaintext ships in compose/systemd), **env for local/CI**, optionally **SOPS(age)** to encrypt the demo compose `.env` in git in the interim. Adopt Vault **behind an abstraction seam** so it is never a big-bang.

## Plan — phased (engineering heuristics)

Heuristics: *be a pessimist → smallest shippable cut*; *branch-by-abstraction* (never big-bang a secrets backend); *parallel change / expand-contract* (retire the allowlist safely); *config validated at load time* (rg-008); *smaller batches are reversible*; *YAGNI*.

### Phase 1 — Hygiene MVP (no new infra; ship first)
1. **Secrets-ownership matrix** → `docs/.../secrets-inventory.md` (authoritative version of the table above).
2. **Delete dead root `.env`.**
3. **One documented `.env.example` per deployable** — each var annotated with domain + source + consumer.
4. **Load-time validation (rg-008):** each service fails fast with a clear message on a missing *required* secret; no silent empty defaults.
5. **Retire `RECOGNITION_ALLOWED_API_KEYS`** via expand→contract: confirm the DB-key path covers every live key → migrate the one active key into the DB via `/admin` → delete the env read + config field. Bootstrap stays clean: `RECOGNITION_ADMIN_TOKEN` mints the first key.
6. **One onboarding command** (`make dev-setup`): copies examples, prompts for values.

*Success:* new dev runs one command; `grep -r RECOGNITION_ALLOWED_API_KEYS` = 0; every service errors clearly on a missing secret.

### Phase 2 — SecretProvider seam (branch-by-abstraction; pure refactor)
- Introduce `SecretProvider.get_secret(name)` in the description-service (WP equivalent as needed); default `EnvSecretProvider`. Route **all** secret reads through it — no `os.getenv` for secrets outside the provider. Zero behavior change.

*Success:* the seam exists; Phase 3 can swap backends without touching consumers.

### Phase 3 — OCI Vault backend (prod), env for local
- Add `OciVaultSecretProvider` behind the seam, selected by `RECOGNITION_SECRET_BACKEND=oci_vault|env`.
- On the VM: **instance principals** fetch DB creds + admin token from Vault → compose/systemd carry no plaintext secrets.
- Local/CI stay on `EnvSecretProvider`.
- **Failure-mode decision:** Vault unreachable at boot → **fail-fast** (do not serve without secrets), surfaced explicitly.

*Success:* prod boots and pulls secrets via instance principal; no plaintext on host; rotating a secret is a single Vault operation.

## Not-doing (MVP boundary / YAGNI)

- Dynamic/leased secrets (Vault advanced features).
- A secrets manager for *local* dev (env stays).
- Merging human WP accounts into the machine-key system.
- Re-architecting the plugin's WP-option key storage (Settings page is already the right home).
- Auto-provision "pair with service" flow (separate feature — see Forward-looking §A).

## Success criteria (overall)

- Single documented onboarding path (one command).
- Zero duplicated/undocumented secrets; a living ownership matrix.
- Tenant keys DB-only (static allowlist gone).
- Prod: no plaintext secrets on host; fetched from OCI Vault via instance principal.
- Rotation of admin token / DB cred / tenant key is a documented single-place operation.

---

## Forward-looking (tech-debt / future-proofing — NOT this task's MVP)

These are recorded so the Phase-2 seam and Phase-3 Vault namespacing do not foreclose them. Each has an explicit **trigger** — do not build ahead of it.

### §A. Multi-tenant demo provisioning (per-tenant + dev demos)

**Observed today:** the `/admin` console already lists per-tenant demo tenants with URLs like `smoke-<uuid>.example.test` — i.e. demos are already minted per tenant, but the surrounding auth (WP admin account, tenant key injection, service URL, demo stack) is assembled by hand. This does not scale past a handful.

**Future shape** (when self-serve signup exists): a **provisioning pipeline** —
```
signup → mint tenant (/admin) → mint tenant API key (DB, /admin) →
stand up / attach demo (shared multi-tenant WP with tenant-scoped data, OR a per-tenant stack) →
store that tenant's secrets in Vault under a per-tenant namespace (secret/tenants/<id>/*) →
configure the demo (URL, key) programmatically — never by hand-editing wp-config/.env
```
**Design ties to this task:**
- The **SecretProvider seam** (Phase 2) is what lets per-tenant secrets be fetched by namespace without touching consumers.
- OCI Vault (Phase 3) gives a natural **per-tenant secret namespace** + rotation per tenant.
- `/admin` remains the tenant-key source of truth; provisioning calls it rather than writing env.

**Decision — shared vs per-tenant demo stack:**
- *Shared multi-tenant WP + tenant-scoped data* (leverages existing RLS/tenant identity, E15-24): cheaper, one stack, but demo blast-radius is shared.
- *Per-tenant stack* (compose/subdomain per tenant): stronger isolation, but N× infra + N× secrets to manage → only viable with the Vault namespacing + automated provisioning above.

**Trigger:** move from hand-made demos to **self-serve tenant signup**, or when the number of live demos exceeds what one operator can hand-configure (~5–10). Until then: document the manual runbook (`infra/oci/demo/tenant-mint-runbook.md` already exists) and keep secrets in Vault namespaces once Phase 3 lands.

**Dev demo:** treat "a demo for dev" as just another tenant namespace (`tenants/dev/*`) provisioned by the same pipeline — no bespoke path.

### §B. When to bring in a 3rd-party auth vendor

Separate **two distinct auth concerns** — they have opposite answers:

1. **Machine / tenant auth** (service-to-service API keys): **keep homegrown.** `/admin` + DB keys + Vault is the right tool; an external vendor here rarely pays off. No trigger to adopt one.
2. **Human identity / authN** (who logs into WP-admin, or a *future* customer dashboard): **this is where an IdP earns its keep** at SaaS scale.

**Adopt a human-identity IdP when ANY of these trigger:**
- You build a **customer-facing dashboard/login** beyond WP-admin (a real product surface with signup).
- You need **B2B SSO / SAML / SCIM** for enterprise customers.
- You need **MFA, social / passwordless login, or SOC2-grade audit trails**.
- **Multiple apps** (WP + dashboard + API) must share one identity + RBAC.

**Do NOT adopt one** while the only human surface is WP-admin for a few operators (WP's own auth suffices), or for machine/tenant keys.

**Vendor shortlist (evaluate in this order given OCI + ship-soon):**

| Vendor | Best for | Note |
|---|---|---|
| **OCI IAM Identity Domains** (ex-IDCS) | OCI-native IdP, included with OCI | Evaluate **first** — avoids a second vendor; full OIDC/SAML/MFA. |
| **WorkOS** | B2B SSO/SCIM specifically | Cleanest enterprise-SSO story; pay-per-connection. |
| **Clerk** | Fast B2C/B2B dashboard DX | Great DX, newer; good if building a React dashboard. |
| **Auth0 / Okta** | Full-featured, mature | Expensive at scale; classic default. |
| **AWS Cognito** | Cheap, AWS-native | Rough DX; off-cloud from OCI. |
| **Ory (Kratos/Hydra)** | Open-source / self-host, no vendor | Highest ops cost; if avoiding SaaS lock-in. |

**Recommendation:** default to **OCI IAM Identity Domains** first (native, no new vendor, shipping-soon-friendly); reach for **WorkOS** only if/when enterprise B2B SSO is a sales requirement. This decision is **out of scope for the secrets-consolidation task** — recorded here as a trigger so Phase 2/3 keep human-auth and machine-auth cleanly separated (they already are).

## Open questions / assumptions

- **A1 (assumption):** exactly one live tenant key is in real use (the `/admin` list shows one active STANDARD key on tenant `…00aa`); Phase-1 allowlist retirement must first confirm no other consumer relies on the static env list. *Verify before contract step.*
- **A2 (assumption):** the prod/demo VM can be granted an OCI **dynamic group + instance-principal policy** to read the Vault secret compartment. *Confirm OCI IAM access before Phase 3.*
- **Q1:** for prod, one Vault compartment shared across services, or per-service compartments? (affects blast radius + IAM policy granularity).
- **Q2:** SOPS(age)-encrypted compose `.env` in git as an interim (Phase 1.5), or jump straight to Vault (Phase 3)?
