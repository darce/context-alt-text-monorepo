# Portal dev end-to-end runbook

## 1. Scope

This runbook covers the dev rung of the launch ladder: sign in to the local
portal with Clerk's development instance, claim an invitation, create an API
key, configure a local WordPress site, and describe an image through the dev
API. Production follows [Clerk production authentication](clerk-production-auth.md)
and [portal deployment](app-portal-deploy.md).

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

Use a repository checkout of `main`. From the workstation repository root,
deploy the dev API:

```bash
make deploy-dev
```

From the workstation repository root, check the dev backend environment against
the manifest:

```bash
make env-materialize ENV=dev TARGET=svc-vm
```

After reviewing the check and resolving any reported drift, apply it from the
workstation repository root:

```bash
APPLY=1 make env-materialize ENV=dev TARGET=svc-vm
```

For `svc-vm` in `dev`, the manifest must enable the portal with
`RECOGNITION_PORTAL_ENABLED=1`, set `ACX_CLERK_ISSUER` to
`https://saved-frog-4170.clerk.accounts.dev` and
`ACX_CLERK_JWKS_URL` to
`https://saved-frog-4170.clerk.accounts.dev/.well-known/jwks.json`, and set
`ACX_CLERK_AUDIENCE=altcontext-portal`.
Set `ACX_CLERK_AUTHORIZED_PARTIES`, `APP_PUBLIC_ORIGIN`, and
`APP_ALLOWED_ORIGINS` to exactly `http://localhost:5173`.

On the dev VM, restart the API after deployment and environment application:

```bash
sudo systemctl restart acx-dev
```

From the workstation, probe the dev endpoint:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://dev.api.altcontext.com/portal/me
```

An unauthenticated `401` means `/portal` is mounted. A `404` means it is not;
recheck `RECOGNITION_PORTAL_ENABLED` in the dev manifest, apply the environment,
and restart `acx-dev` again.

## 4. Invitation

In one VM shell, create the invitation for the same address used to sign in to
Clerk. The invitation is single-use and expires after 72 hours. Begin in the
API directory:

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

To revoke one, first select its ID from the list. In the same VM shell, read
that ID:

```bash
read -r -p 'Invitation ID to revoke: ' invitation_id
```

Then revoke that ID from the same VM shell and directory:

```bash
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_portal_invitations --env dev revoke --invitation-id "$invitation_id"
```

## 5. Portal

From the workstation repository root, render the local portal's public Clerk
settings:

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
- **403 while claiming:** confirm the signed-in primary email is verified and
  `email_verified` is a boolean claim, then confirm the invitation has not
  already been claimed and is still active.
- **503 from `/portal`:** inspect the API logs for the identity-store failure;
  this is a backend identity-store issue, not a Clerk sign-in failure.
- **Description remains queued:** follow the lifecycle checks in
  [GPU demo environment flip](gpu-demo-env-flip.md), including the pending-load
  snapshot, `acx-gpu-start.timer`, worker readiness, and durable-run status.

## 8. Rollback (RLSE-08)

Revoke the API key in the portal. Revoke any unused invitations using the list
and revoke commands in section 4. In local WordPress **Settings > Alt Context**,
restore the settings that were in place before this run.

To disable the dev portal, restore the pre-launch dev values in
`config/env/manifest.d/30-portal-backend.toml`. From the workstation repository
root, check the dev environment:

```bash
make env-materialize ENV=dev TARGET=svc-vm
```

After reviewing the check, apply the restored values from the workstation
repository root:

```bash
APPLY=1 make env-materialize ENV=dev TARGET=svc-vm
```

Finally, restart the service on the dev VM:

```bash
sudo systemctl restart acx-dev
```
