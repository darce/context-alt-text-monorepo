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
4. The `altcontext.com` zone is served by Unstoppable Domains nameservers
   (`ns1.unstoppabledomains.com` and `ns2.unstoppabledomains.com`), so add
   records in that registrar's DNS panel, not in this repo or OCI. In
   **Dashboard > Domains**, copy every target exactly for these five CNAMEs:
   `clerk` (Frontend API; `frontend-api.clerk.services`), `accounts` (Account
   Portal; `accounts.clerk.services`), `clkmail`, `clk._domainkey`, and
   `clk2._domainkey` (email sending and DKIM; each has an instance-specific
   `*.clerk.services` target). Do not add an A record for `clerk`. Press
   **Verify** and wait for DNS and SSL to show ready. Existing A records
   (`api`, `app`, `demo`, and others) are unaffected. Check the Frontend API
   CNAME with:

   ```bash
   dig +short CNAME clerk.altcontext.com
   ```

   Expected output: `frontend-api.clerk.services.`
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

In **Sessions → Customize session token**, set `aud` to the production
`ACX_CLERK_AUDIENCE` manifest value (`altcontext-portal`), then set:

```json
{
  "aud": "altcontext-portal",
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
ready to materialize from the values already harvested into that manifest.
`make env-materialize ENV=prod TARGET=svc-vm` checks the runtime file against
the manifest. Resolve any reported drift and provide required host-only values
before applying; VM value harvesting is complete and is not a prerequisite.
The production values for `RECOGNITION_PORTAL_ENABLED` and
`VITE_CLERK_PUBLISHABLE_KEY` are both committed. The remaining launch steps
are to materialize the backend settings, restart the production API unit,
and deploy the portal as described in
[`app-portal-deploy.md`](app-portal-deploy.md).
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

From the repository root, check and apply the production backend manifest.
Materialization can still refuse if the runtime file has drifted or required
host-only secrets are absent; resolve those reported prerequisites first.

```bash
make env-materialize ENV=prod TARGET=svc-vm
make env-materialize ENV=prod TARGET=svc-vm APPLY=1 CONFIRM=prod
```

The portal key is public. The operator-supplied live publishable key is
committed as the `prod` value of `VITE_CLERK_PUBLISHABLE_KEY` in
`config/env/manifest.d/60-app-portal.toml`; validate the complete contract.
The validator reads the manifest and never writes runtime env files. Its
optional `--check` flag makes a bounded network request to the derived JWKS URL;
the default validation is offline.

```bash
python3 apps/prototype-description-service/scripts/configure_clerk_production.py
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

`scripts/deploy/app-portal.sh --apply` validates that reachable JavaScript
modules contain the same live key and FAPI as the production manifest before
staging the build. Billing credentials belong only in backend secret storage
or runtime injection. Use the manifest targets as the production source of
truth; do not write a separate `app-portal.env` artifact.

### Post-launch signed-in smoke check

The offline validator and the unauthenticated `/portal/me` health check
(expected `401`) cannot verify the session token's audience claim.

The account must have a primary email verified in Clerk and an existing local
tenant identity. Before this read-only check, complete the portal's first
sign-in onboarding claim (`POST /portal/onboarding/claim`) through the portal,
then reload. Do not print an API key during the check.

1. Sign in at `https://app.altcontext.com` with a real account.
2. In browser developer tools, open the **Network** tab and confirm the
   portal's own `/portal/me` request returns `200`.
3. If it returns `401`, decode the session token's payload locally and check
   that `aud` is `altcontext-portal` and `azp` is
   `https://app.altcontext.com`. Never paste a token into a website or this
   repo. Correct the session-token template in the Clerk Dashboard using
   section 2 above, then sign in again and repeat the check.
4. If it returns `403`, decode the session token's payload locally (never
   paste a token into a website or this repo) and confirm it carries `email`
   and boolean `email_verified: true`, using the section 2 template. Confirm
   the account's primary email is verified in Clerk and the portal's
   onboarding claim completed, then reload and repeat the check.
5. If it returns `503` with `portal identity unavailable`, the local identity
   store is unavailable. Check API logs and readiness; this is an identity
   store issue, not a Clerk session-token template issue.

## 5. Rotation

Use the Clerk Dashboard **API keys** page or `npx clerk@latest` as documented
in [Rotate API keys](https://clerk.com/docs/guides/secure/rotate-api-keys).
Update the appropriate manifest source, then validate and render the public
build settings again and materialize backend settings with the commands above.
Publishable keys are public; rotate the secret if it leaked.
