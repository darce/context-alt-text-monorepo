# Production Clerk authentication (app.altcontext.com)

Bootstrap the first production Clerk instance and write env files consumed by
the description-service portal verifier. There is **no** committed
`apps/app-portal` in this tree; the frontend env artifact is prepared for a
later Vite build. This script does **not** mint Clerk secrets.

Official references:

- [Clerk environment variables](https://clerk.com/docs/guides/development/clerk-environment-variables)
- [How Clerk works](https://clerk.com/docs/guides/how-clerk-works/overview)
- [Rotate API keys](https://clerk.com/docs/guides/secure/rotate-api-keys)
- [Change domain](https://clerk.com/docs/guides/development/deployment/changing-domains)
- [Allowed Subdomains](https://clerk.com/docs/guides/dashboard/dns-domains/subdomain-allowlist)
- [Customize session tokens](https://clerk.com/docs/guides/sessions/customize-session-tokens)

## 1. Create the production instance (Dashboard)

Credentials do not exist until this step. In the [Clerk Dashboard](https://dashboard.clerk.com/):

1. Create a **production** instance (Development keys `pk_test_` / `sk_test_`
   are refused by the bootstrap CLI).
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
verified official CLI is `npx clerk@latest` (for example
`npx clerk@latest env pull --instance prod` writes Clerk's own variable
names into a local env file). That pull does **not** write `ACX_CLERK_*` and
is not a substitute for the bootstrap below.

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

Production compose (`docker-compose.env.yml`) uses `env_file: .env` in the
environment directory. `env_to_remote_dir(prod)` is `/opt/acx-backend/prod`.
The live backend file is `/opt/acx-backend/prod/.env` (ubuntu, mode 0600).
Compose does **not** automatically read `.env.prod`.

The CLI refuses symlinks. If `.env` is a symlink, pass the real file path.

Frontend remains undeployed. Pass an explicit `--frontend-env` artifact (for
example `/opt/acx-backend/prod/app-portal.env`) and bake `VITE_*` into a
future frontend build. Do not claim a deployed portal.

## 4. Bootstrap command

Never put keys on argv. Write them to owner-only files (or export them in the
shell) and point the CLI at those files.

```bash
# On the VM, from a checkout of this repo. Dry-run is the default.
umask 077
install -m 600 /dev/null /tmp/clerk-pk
# paste pk_live_… via an editor; do not echo the key
python3 apps/prototype-description-service/scripts/configure_clerk_production.py \
  --publishable-key-file /tmp/clerk-pk \
  --audience altcontext-portal \
  --backend-env /opt/acx-backend/prod/.env \
  --frontend-env /opt/acx-backend/prod/app-portal.env \
  --check

# Review the plan (keys are redacted). Then write:
python3 apps/prototype-description-service/scripts/configure_clerk_production.py \
  --apply \
  --publishable-key-file /tmp/clerk-pk \
  --audience altcontext-portal \
  --backend-env /opt/acx-backend/prod/.env \
  --frontend-env /opt/acx-backend/prod/app-portal.env
shred -u /tmp/clerk-pk
```

Optional secret (backend only): `--secret-key-file` or `CLERK_SECRET_KEY` in
the environment. Publishable key may also come from `CLERK_PUBLISHABLE_KEY`.

`--check` GETs the derived JWKS URL with a **2s total deadline** (not only a
per-socket idle timeout) and a bounded body. Slow trickles that stay under the
socket timeout still fail if they exceed 2s wall time. It does not rotate,
delete, or otherwise mutate Clerk. A failed check never writes.

The CLI is idempotent: a second `--apply` with the same inputs rewrites the
managed keys in place and leaves unrelated env content alone. Contradictory
duplicate keys and newline injection are refused. Destinations are replaced
atomically at mode 0600.

Frontend artifacts are validated against backend-only secret boundaries
**before any write**. A prepopulated `CLERK_SECRET_KEY` (or `sk_live_` /
`sk_test_` material) in `--frontend-env` is refused; both destination files
stay unchanged and the error names the key, never the secret value. Legitimate
public `VITE_*` settings are preserved. `--apply` with both backend and
frontend files is a staged transaction: if the second write fails, the first
is rolled back. If rollback itself fails, the CLI exits with an explicit
"recovery cannot be guaranteed" error instead of leaving a silent partial
config.

## 5. Runtime / rebuild

Backend: `api` and `worker` read `.env` through Compose. After `--apply`,
restart the prod unit so the process environment refreshes:

```bash
sudo systemctl restart acx-prod
```

Frontend: `VITE_CLERK_PUBLISHABLE_KEY` (and `VITE_CLERK_FAPI`) are public
build-time values. They take effect only when a future app-portal image is
built with that env file. Restarting the backend does not publish them.

## 6. What the CLI writes

Backend (no browser publishable key):

- `ACX_CLERK_ISSUER`
- `ACX_CLERK_JWKS_URL`
- `ACX_CLERK_AUDIENCE`
- `ACX_CLERK_AUTHORIZED_PARTIES` (default `https://app.altcontext.com`)
- `CLERK_SECRET_KEY` only when an `sk_live_` value was supplied

Frontend artifact:

- `VITE_CLERK_PUBLISHABLE_KEY`
- `VITE_CLERK_FAPI` (`https://` + decoded FAPI host)

## 7. Rotation

This script never rotates or deletes keys. Use the Clerk Dashboard **API keys**
page or `npx clerk@latest` as documented in
[Rotate API keys](https://clerk.com/docs/guides/secure/rotate-api-keys), then
re-run `--apply` with the new protected input so the env files converge.
Publishable keys are public; rotate the secret if it leaked.
