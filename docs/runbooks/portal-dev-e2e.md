# Portal dev end-to-end runbook

## 1. Scope

The dev rung covers Clerk sign-in, invitation claim, API key creation, and
image description through the dev API from local WordPress. Production follows
[Clerk production authentication](clerk-production-auth.md) and
[portal deployment](app-portal-deploy.md).

## 2. Clerk development instance

In the Clerk Dashboard, select the existing **Development** instance
`saved-frog-4170.clerk.accounts.dev`. No DNS setup is needed. Enable email-code
sign-in. Under **Sessions > Customize session token**, set the template to
exactly:

```json
{
  "aud": "altcontext-portal",
  "email": "{{user.primary_email_address}}",
  "email_verified": "{{user.email_verified}}"
}
```

The publishable key is public and is rendered for the local portal. This flow
never needs a Clerk secret key.

## 3. Dev API

Use a clean, updated checkout of `main`. From the workstation repository root,
check the dev backend environment against the manifest before deploying:

```bash
make env-materialize ENV=dev TARGET=svc-vm
```

On the first rollout, GNU Make exits 2 when the materializer exits 1 for drift.
Expected drift requires exactly seven `missing` lines for the keys below and
`materialize_remote.sh: drift found (remote check exit 1)` (Make reports `Error 1`).
An already configured environment checks clean (Make exit 0). Stop on any other
drift (`missing`, `stale`, `unmanaged`, `differs`, or `mode`) or transport/config/check error before applying or deploying.
The seven `svc-vm` dev values must be:

- `RECOGNITION_PORTAL_ENABLED=1`
- `ACX_CLERK_ISSUER=https://saved-frog-4170.clerk.accounts.dev`
- `ACX_CLERK_JWKS_URL=https://saved-frog-4170.clerk.accounts.dev/.well-known/jwks.json`
- `ACX_CLERK_AUDIENCE=altcontext-portal`
- `ACX_CLERK_AUTHORIZED_PARTIES`, `APP_PUBLIC_ORIGIN`, and `APP_ALLOWED_ORIGINS`:
  exactly `http://localhost:5173`.

After reviewing those seven additions (or a clean check), apply from the workstation root:

```bash
APPLY=1 make env-materialize ENV=dev TARGET=svc-vm
```

Only after APPLY succeeds, deploy from that same workstation checkout:

```bash
make deploy-dev
```

Deploy checks for zero drift, restarts and verifies `acx-dev`; a separate VM restart is optional.

From the workstation, probe the dev endpoint:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://dev.api.altcontext.com/portal/me
```

An unauthenticated `401` means `/portal` is mounted. For `404`, recheck the dev
manifest, repeat the reviewed apply from the workstation, and restart `acx-dev` on the dev VM.

## 4. Invitation

On the dev VM, create a single-use invitation for the Clerk sign-in address
(expires in 72 hours). Begin in the API directory:

```bash
cd /opt/acx-backend/dev
```

Run the CLI inside the API container, with `--env dev` matching the container's
`ACX_ENV`:

```bash
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_portal_invitations --env dev create --email you@example.com --ttl-hours 72
```

On success, the raw invitation token appears once in a line named
`invitation_token`. Copy it directly into the local portal's **Invitation
token** field; do not put its value in notes or this runbook. To inspect
invitations, in the same VM shell and directory run:

```bash
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_portal_invitations --env dev list --include-inactive
```

To revoke one, select its ID from the list and read it in the same VM shell:

```bash
read -r -p 'Invitation ID to revoke: ' invitation_id
```

Then revoke that ID from the same VM shell and directory:

```bash
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_portal_invitations --env dev revoke --invitation-id "$invitation_id"
```

## 5. Portal

From the workstation repository root, render the local portal's public Clerk settings:

```bash
make env-render ENV=local TARGET=app-portal-local
```

Install portal dependencies from the workstation repository root:

```bash
npm --prefix apps/app-portal ci
```

Start Vite from the workstation repository root, routing `/portal` calls to
the dev API:

```bash
PORTAL_API_PROXY_TARGET=https://dev.api.altcontext.com npm --prefix apps/app-portal run dev
```

In the browser, open `http://localhost:5173`, sign in with the invited email
using the email code, paste the invitation into **Invitation token**, and
claim it. Create an API key and copy it directly to the local WordPress
settings; it is shown only once.

## 6. WordPress

Before testing, the GPU endpoint key must already be minted and installed on
the GPU host and in the dev environment. Follow
[GPU endpoint key minting](gpu-key-mint.md) for that prerequisite.

In the local WordPress site, open **Settings > Alt Context**. Set Recognition
URL to `https://dev.api.altcontext.com` and enter the API key created in the
portal. Save the settings to pair the tenant, then describe one image. The
first request can wait while the GPU starts: dev uses
`ACX_DESCRIPTION_ADAPTER=gpu_qwen30b` and the private GPU endpoint. The backend
lifecycle starts a stopped instance when work is queued and stops it when idle.

## 7. Troubleshooting by status

- **401 from `/portal`:** check the session template's `aud` and the token's
  `azp` against `ACX_CLERK_AUTHORIZED_PARTIES`, which must be exactly
  `http://localhost:5173`. Clerk supplies `azp` from the portal origin.
- **403 while claiming:** `email_unverified` requires a verified primary email
  and boolean `email_verified`; `csrf_origin_denied` requires the browser's
  `Origin` to match `APP_ALLOWED_ORIGINS` exactly: `http://localhost:5173`.
  `not_admitted` means the invited address differs from the Clerk primary email,
  or the token is expired, revoked, or unknown. `tenant_header_forbidden` means
  the request attempted to select a tenant.
- **409 while claiming:** `invitation_consumed` or `identity_already_bound`;
  inspect the invitation and existing identity binding before retrying.
- **422 while claiming:** `invalid_claim_request`; correct the claim payload.
- **503 from `/portal`:** inspect the API logs for the identity-store failure;
  this is a backend identity-store issue, not a Clerk sign-in failure.
- **Description remains queued:** follow the lifecycle checks in
  [GPU demo environment flip](gpu-demo-env-flip.md), including the pending-load
  snapshot, `acx-gpu-start.timer`, worker readiness, and durable-run status.

## 8. Rollback (RLSE-08)

Revoke the API key in the portal. Revoke any unused invitations using the list and revoke commands in section 4. In local WordPress **Settings > Alt Context**, restore the settings that were in place before this run.

To disable the dev portal durably (RLSE-19), from clean, updated `main` at the workstation repository root run `make task-start TASK=PORTALDEV-2 OBJECTIVE="Disable dev portal" MODE=worktree`. This creates maintenance branch `feature/portaldev-2` and its linked worktree; the invoking shell stays on `main`. Before editing, run `cd ../context-alt-text-monorepo-portaldev-2` and confirm `git branch --show-current` reports `feature/portaldev-2`. If that task ref is already in use, choose an unused digit-bearing ref with the same command and enter its reported `worktree_path`, confirming its corresponding feature branch.
Remove only the seven `dev` entries from the `values` maps in `config/env/manifest.d/30-portal-backend.toml`; preserve all local and existing or subsequently merged production settings.
In `scripts/env/tests/test_portal_backend_vars.py`, replace DEV-only expectations (`expected_dev`, DEV render assertions, and the enable-flag values check) with assertions that all seven DEV manifest values and rendered assignments are absent (portal disabled). Preserve all local/prod assertions, including any added since rollout; in the enable-flag values check remove only the `dev` entry from its expected map.
From that branch's workstation repository root, regenerate the example digests and pass both gates before committing all four files:
```bash
make env-examples &&
make env-check &&
LC_ALL=C uv run --no-project --with pytest python -m pytest scripts/env/tests -q &&
git add config/env/manifest.d/30-portal-backend.toml scripts/env/tests/test_portal_backend_vars.py apps/prototype-description-service/.env.example apps/prototype-description-service/.env.prod.example &&
git diff --cached --check && git commit -m "fix(portal): disable dev portal"
```

Obtain review and merge the complete change set to `main` before materializing. From clean, updated `main` at the workstation repository root, check:
```bash
make env-materialize ENV=dev TARGET=svc-vm
```
Expect seven `stale` lines; stop on other drift or failures. Review, then apply from the same workstation checkout:
```bash
APPLY=1 make env-materialize ENV=dev TARGET=svc-vm
```

After APPLY succeeds, restart the service on the dev VM:
```bash
sudo systemctl restart acx-dev
```

Keep later materializations and deployments on updated `main`: an older manifest can re-enable the portal on APPLY, or fail deploy's drift preflight.
