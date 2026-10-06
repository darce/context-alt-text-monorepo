# AltContext account portal

Standalone React/Vite SPA for app.altcontext.com account chrome. Clerk authenticates a person. Tenant UUID comes only from same-origin `GET /portal/me`. This package does not mint keys, claim invitations, or render billing.

## Offline constraint

This slice is a manual `@clerk/react` integration. Do not run `npx clerk init`, `clerk auth login`, or accountless setup. Do not read protected env files or commit secrets. Missing `VITE_CLERK_PUBLISHABLE_KEY` is a designed unavailable screen, not a crash.

## Browser env (public only)

Copy `.env.example`. Vite bakes these at build time:

| Name                         | Required              | Purpose                                                                                            |
| ---------------------------- | --------------------- | -------------------------------------------------------------------------------------------------- |
| `VITE_CLERK_PUBLISHABLE_KEY` | yes for Clerk widgets | Publishable key. Empty → unavailable.                                                              |
| `VITE_CLERK_FAPI`            | no                    | Frontend API origin, production `https://clerk.altcontext.com`. Used by operators when wiring CSP. |
| `VITE_PORTAL_ENABLED`        | no                    | Public flag. `false`/`0`/`off` → degraded unavailable. Default on.                                 |

Never put `CLERK_SECRET_KEY`, Polar OATs, invitation tokens, or API keys in this package.

## Run against the dev API

```bash
PORTAL_API_PROXY_TARGET=https://dev.api.altcontext.com npm --prefix apps/app-portal run dev
```

The browser env comes from `make env-render ENV=local TARGET=app-portal-local` with the Clerk development publishable key.
The dev API must have the portal enabled. Never paste tokens or API keys anywhere.

## Scripts

```bash
npm --prefix apps/app-portal install
apps/app-portal/node_modules/.bin/vitest run --root apps/app-portal
npm --prefix apps/app-portal run build
npm --prefix apps/app-portal run dev
```

Production output: `apps/app-portal/dist/`. Serve with history fallback to `index.html`. Proxy `/portal` and `/portal/*` to the API host.

## Clerk

Official React/Vite path (checked 2026-09-22):

- https://clerk.com/docs/react/getting-started/quickstart
- https://clerk.com/docs/react/reference/components/clerk-provider

`App.tsx` mounts `ClerkProvider`, routed `<SignIn />` / `<SignUp />`, `UserButton`, and `useAuth`. Sign-in and sign-up `forceRedirectUrl` is `/` so query `redirect_url` cannot open-redirect. `GET /portal/me` sends `Authorization: Bearer` only (`credentials: 'omit'`) with a bounded abort. Tenant display uses the server `tenant_id`. Email, Clerk org, and localStorage are not tenant authority.

## Production CSP

`csp/production.csp` is the operator-reviewed production allowlist. `infra/oci/app/Caddyfile.app` applies it as a `Content-Security-Policy` header to the SPA `handle` response.

Checked 2026-09-22: https://clerk.com/docs/guides/secure/best-practices/csp-headers

Production choices:

- Exact FAPI host `https://clerk.altcontext.com` plus `'self'`
- Cloudflare challenge `https://challenges.cloudflare.com`
- Scoped Clerk protect origins `https://*.protect.clerk.com` and connect ports `https://*.protect.clerk.com:*`
- Images `https://img.clerk.com`
- Workers `'self' blob:`
- `style-src` `'unsafe-inline'` only because Clerk injects runtime CSS
- No `script-src 'unsafe-inline'`, `'unsafe-eval'`, or broad `https:` / `*`
- `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'self'`
- `form-action` restricted to `'self'` and the FAPI host
- No fake static nonce (strict-dynamic nonces must be per-request)

## Not in this slice

Claim/invitation, API keys, usage, and billing UI. Live Clerk/Polar rehearsal. Host Caddy edits.
