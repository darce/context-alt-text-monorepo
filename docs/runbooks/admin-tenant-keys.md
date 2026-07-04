# Runbook: Operator `/admin` console for tenant API-key lifecycle

> **Replaces** the manual `docker exec ... python -m scripts.manage_api_keys`
> ceremony for routine tenant + key work. The CLI remains a supported fallback
> (see `docs/workbay/contracts/security.md` § Operator CLI: Key Rotation
> Ceremony).

The `/admin` surface (E15-31) lets the single operator create tenants, mint and
revoke API keys, and view key status from a browser. Its admin authority is
**tailnet reachability AND a shared admin token** — neither alone is
sufficient:

- The public `api.altcontext.com/admin` returns **404 by design** (Caddy denies
  `/admin*` on the public vhost). It is reachable only over the tailnet.
- Every `/admin` route requires the shared `RECOGNITION_ADMIN_TOKEN`.

Host-level Tailscale enrollment for the VM is the canonical
`infra/oci/README.md` runbook (read-only reference — do not edit it here).

---

## (a) Enable `/admin` on the prod VM

1. In the prod env file (`/opt/acx-backend/prod/secrets/.env`), set:

   ```sh
   RECOGNITION_ADMIN_ENABLED=true
   # strong token, >=32 chars:  python -c "import secrets; print(secrets.token_urlsafe(32))"
   RECOGNITION_ADMIN_TOKEN=<paste-generated-token>
   RECOGNITION_ADMIN_TAILNET_BOUND=1
   ```

   Fail-closed: if `RECOGNITION_ADMIN_ENABLED=true` with an empty/`<32`-char
   token, or in production without `RECOGNITION_ADMIN_TAILNET_BOUND=1`, the
   service refuses to start (`validate_admin_config`).

2. Bring the stack up with the prod-only loopback overlay so the tailnet path
   can reach the api container (the shared `docker-compose.env.yml` does NOT
   publish the api host port; the overlay adds `127.0.0.1:8000:8000`):

   ```sh
   docker compose -f docker-compose.env.yml -f docker-compose.admin.yml up -d
   ```

   The checked-in prod deploy and compose-sync paths install this overlay and
   render it into `acx-prod.service`; ordinary deploys and systemd restarts
   therefore retain the loopback binding. If the unit predates this support,
   run `apps/prototype-description-service/scripts/deploy-env.sh prod` once to
   converge the compose files and unit before enabling `/admin`.

---

## (b) Reach `/admin` over the tailnet

Use **either** path. Both keep `/admin` off the public internet.

**Option 1 — `tailscale serve` (browse a MagicDNS URL):**

```sh
tailscale serve --bg --https=443 --set-path /admin http://127.0.0.1:8000/admin
```

Then browse the VM's MagicDNS URL, e.g. `https://<vm-name>.<tailnet>.ts.net/admin/`.

**Option 2 — `ssh -L` tunnel from your workstation (over the tailnet):**

```sh
ssh -L 8001:127.0.0.1:8000 <vm-over-tailnet>
```

Leave it open, then browse `http://localhost:8001/admin/`.

---

## (c) Authenticate

The console prompts for HTTP Basic auth in the browser:

- **Username**: any value (ignored).
- **Password**: the `RECOGNITION_ADMIN_TOKEN` from step (a).

(Programmatic callers send the `X-Admin-Token` header; it is mandatory for
JSON create/mint/revoke mutations.)

---

## (d) Create tenant → mint key → revoke

1. **Create tenant**: enter a tenant UUID + site URL and submit. Duplicate
   `site_url` → 409.
2. **Mint key**: on the tenant, mint a key. The **raw key is shown exactly
   once** — copy it immediately and store it in the operator secret vault. It
   is unrecoverable after this page (hash-only storage). Unknown tenant → 404.
3. **Revoke key**: use the revoke button on the key. Already-revoked → 200
   (idempotent; original `revoked_at` preserved).

Every create/mint/revoke writes an `audit_events` row atomically with the
mutation.

---

## (e) Public path is denied by design

`curl -so /dev/null -w "%{http_code}" https://api.altcontext.com/admin/` returns
**404**. This is intentional: the public vhost denies `/admin*`. If you can
reach the console publicly, the Caddy deny is misconfigured — stop and fix the
vhost before continuing.
