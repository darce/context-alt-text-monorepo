# Production Clerk authentication (app.altcontext.com)

Configure Clerk for the production portal. The React/Vite source is committed
under `apps/app-portal/`, and `scripts/deploy/app-portal.sh` deploys its build
to the existing edge. This runbook covers Clerk claims and the manifest-owned
runtime and build settings; it does **not** mint Clerk secrets.

Official references:

- [Clerk environment variables](https://clerk.com/docs/guides/development/clerk-environment-variables)
- [How Clerk works](https://clerk.com/docs/guides/how-clerk-works/overview)
- [Rotate API keys](https://clerk.com/docs/guides/secure/rotate-api-keys)
- [Change domain](https://clerk.com/docs/guides/development/deployment/changing-domains)
- [Allowed Subdomains](https://clerk.com/docs/guides/dashboard/dns-domains/subdomain-allowlist)
- [Customize session tokens](https://clerk.com/docs/guides/sessions/customize-session-tokens)

## 1. Create the production instance (Dashboard)

Credentials do not exist until this step. In the [Clerk Dashboard](https://dashboard.clerk.com/):

1. Create a **production** instance. The production portal build requires a
   `pk_live_` publishable key; do not use development keys.
2. Set the application home URL to `https://app.altcontext.com`.
3. When Clerk asks Primary vs Secondary for the `app.` subdomain, choose
   **Primary application**: users hit `app.altcontext.com`; Clerk FAPI stays
   on the root domain as `clerk.altcontext.com`.
4. Configure DNS as the Dashboard shows (CNAME for FAPI, plus email DNS for
   `@altcontext.com`). Wait until Clerk reports DNS/SSL ready.
5. Enable **Allowed Subdomains** and allowlist `app.altcontext.com`. The
   primary domain remains allowed; other subdomains are rejected.
6. Copy the **publishable** key (`pk_live_…`) from **API keys**. Optionally
   copy a **secret** key (`sk_live_…`). JWT verification in this service does
   **not** need the secret; if you store it, it belongs only on the backend.

Do **not** invent a local API that mints `sk_live_` without Clerk auth. The
official `npx clerk@latest env pull --instance prod` command writes Clerk's
own variable names to a local env file; it does not write the service's
`ACX_CLERK_*` settings or replace the environment manifest.

## 2. Session token claims (required)

`PortalAuthSettings.from_env` requires **all four** of `ACX_CLERK_ISSUER`,
`ACX_CLERK_JWKS_URL`, `ACX_CLERK_AUDIENCE`, and `ACX_CLERK_AUTHORIZED_PARTIES`.
`aud` and `azp` are distinct: do not copy one into the other.

Clerk session tokens include `azp` by default. They do **not** include `aud`,
`email`, or boolean `email_verified` unless you add them.

In **Sessions → Customize session token**, set:

```json
{
  "aud": "<the same string you will pass as --audience>",
  "email": "{{user.primary_email_address}}",
  "email_verified": "{{user.email_verified}}"
}
```

Keep the dashboard-template quotes around `{{user.email_verified}}`. Clerk
[JWT template shortcodes](https://clerk.com/docs/guides/sessions/jwt-templates#shortcodes)
retain the underlying type when quoted, so the **decoded JWT** claim is a
boolean (`true`/`false`), not the string `"true"`/`"false"`. The quoted form is
also what Clerk shows in
[How we roll JWT SSO](https://clerk.com/blog/how-we-roll-jwt-sso). Do **not**
remove those quotes from the dashboard JSON; do not confuse the template
document with the verified token payload. First-claim in the portal rejects
unverified email. Authorized party for this product is the exact origin
`https://app.altcontext.com` (no path, no trailing slash).

The issuer is **derived from the live publishable key** (base64 FAPI hostname
ending in `$` → `https://<host>`), not typed by hand. JWKS is
`https://<host>/.well-known/jwks.json`.

## 3. Where files live

Production Compose (`docker-compose.env.yml`) reads `.env` from the
environment directory. `env_to_remote_dir(prod)` is
`/opt/acx-backend/prod`, and the runtime file is
`/opt/acx-backend/prod/.env` (ubuntu, mode 0600). Compose does **not**
automatically read `.env.prod`.

Backend Clerk settings are owned by
`config/env/manifest.d/30-portal-backend.toml` for target `svc-vm` and are
materialized to the production runtime file with `make env-materialize`.
The four required verifier settings are `ACX_CLERK_ISSUER`,
`ACX_CLERK_JWKS_URL`, `ACX_CLERK_AUDIENCE`, and
`ACX_CLERK_AUTHORIZED_PARTIES`. An optional Clerk secret, if configured,
belongs on the backend only.

`VITE_CLERK_PUBLISHABLE_KEY` and `VITE_CLERK_FAPI` are public build-time
values. The `app-portal-build` manifest target renders them into
`apps/app-portal/.env.production.local`; the publishable key must start with
`pk_live_` for production. Vite embeds these values in the browser bundle, so
never put a Clerk secret in this target.

## 4. Materialize and build

From the repository root, check then apply the production backend manifest:

```bash
make env-materialize ENV=prod TARGET=svc-vm
make env-materialize ENV=prod TARGET=svc-vm APPLY=1 CONFIRM=prod
```

Render the public portal build environment and build the committed app:

```bash
make env-render ENV=prod TARGET=app-portal-build
npm ci --prefix apps/app-portal
npm --prefix apps/app-portal run build
```

The build writes `apps/app-portal/dist/`; deploy that directory with
[`app-portal-deploy.md`](app-portal-deploy.md). Backend `api` and `worker`
read `.env` through Compose. After applying backend values, restart the
production API unit on the VM so its process environment refreshes:

```bash
sudo systemctl restart acx-prod
```

The existing `configure_clerk_production.py` environment writers remain in
this checkout for now and are scheduled for retirement in a later wave. Use
the manifest targets above as the production source of truth; do not pass
`--frontend-env` or write a separate `app-portal.env` artifact.

## 5. Rotation

Use the Clerk Dashboard **API keys** page or `npx clerk@latest` as documented
in [Rotate API keys](https://clerk.com/docs/guides/secure/rotate-api-keys).
Update the appropriate manifest source, then render the public build settings
again and materialize backend settings with the commands above. Publishable
keys are public; rotate the secret if it leaked.
