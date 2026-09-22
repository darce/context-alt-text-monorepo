# App portal host — app.altcontext.com on the existing OCI VM

Prepare the public customer hostname on **the current edge**, host
`129.213.40.111` (`acx-backend`). This lane does **not** provision a new
machine, does **not** edit the shared git `Caddyfile`, and does **not** deploy
live from a sandbox worker.

Bounded artifacts:

- `infra/oci/app/Caddyfile.app` — public vhost snippet
- `infra/oci/app/docker-compose.app.yml` — static-root overlay
- `infra/oci/app/env.example` — deploy input names only
- `scripts/deploy/app-portal.sh` — dry-run by default; `--apply` on the VM

Canon: [GRPH-09] keep this vhost off the shared Caddyfile so demo/API owners
do not collide; [RES-02] fail closed on missing builds and failed `caddy
validate`; [RES-01]/[RES-05] no remote-shell retries from this script.

## What the vhost exposes

HTTPS `app.altcontext.com` (Caddy ACME, same edge as `api.altcontext.com`):

| Path | Behaviour |
| --- | --- |
| `/portal` and `/portal/*` | `reverse_proxy` to `prod-api:8000` (compose alias on `acx-prod-net`) |
| `/` static SPA | `root * /srv/app-portal` + `try_files {path} /index.html` |
| `/admin`, `/admin/*` | `404` (same public denial as the API vhosts) |
| `/recognition`, `/roster`, `/scene`, `/billing/webhooks`, `/health`, `/ready`, `/metrics`, `/docs`, `/x` | `404` — those surfaces stay on `api.altcontext.com` |

SPA routes such as `/billing/return` are frontend paths, not the Polar webhook.

## Env ownership (do not put secrets in these files)

| Surface | Owner | Names |
| --- | --- | --- |
| This deploy script | app-host lane | `APP_HOSTNAME`, `APP_UPSTREAM`, `APP_ROOT`, `APP_WWW`, `APP_FRONTEND_ROOT`, `CADDYFILE`, `FRONTEND_DIST` |
| Prod API process | backend/portal composition | `RECOGNITION_PORTAL_ENABLED=1` and Clerk/Polar keys in `/opt/acx-backend/prod/.env` (mode 0600) |
| Frontend build | later `apps/app-portal` build | `VITE_CLERK_PUBLISHABLE_KEY`, `VITE_CLERK_FAPI` baked by `configure_clerk_production.py` |

`infra/oci/app/env.example` lists the deploy names only. Clerk secret keys and
Polar tokens never belong in the snippet, overlay, or this runbook's commands.

## Default dry-run

From the repo, on the VM filesystem (worker must not open a remote shell):

```bash
scripts/deploy/app-portal.sh
# or
scripts/deploy/app-portal.sh --dry-run
```

Prints the plan, lists live Caddy hosts, and exits 0 without writing. Unsafe
path/upstream/hostname values are still refused.

## Apply (only with a real frontend build)

There is no committed `apps/app-portal` in this tree. Do **not** generate a
placeholder `index.html`. `--apply` refuses a missing dist, empty `index.html`,
or empty `assets/`.

```bash
FRONTEND_DIST=/absolute/path/to/real/dist \
APP_UPSTREAM=prod-api:8000 \
CADDYFILE=/opt/acx-backend/Caddyfile \
scripts/deploy/app-portal.sh --apply
```

`--apply` then:

1. Validates `FRONTEND_DIST` and `APP_UPSTREAM`.
2. Stages a merged Caddyfile that **keeps** `api.*`, `demo.altcontext.com`,
   `129-213-40-111.sslip.io`, and `dl.darce.xyz`.
3. Runs `caddy validate` on the staged file (`--adapter caddyfile`).
4. On validate failure: live `/opt/acx-backend/Caddyfile` is left untouched
   (active config intact).
5. On success: copies live config to `/opt/acx-backend/app/rollback/Caddyfile.<ts>`,
   writes the staged file **in place** (`cat > Caddyfile`, same inode rule as
   `sync-demo.sh`), and flips `/opt/acx-backend/app/www` from a staging dir.

Protected hostnames (`api.altcontext.com` and the other live vhosts) cannot be
used as `APP_HOSTNAME`. Path traversal (`..`) and shell metacharacters are
refused. The shared repo file
`apps/prototype-description-service/Caddyfile` is refused as `CADDYFILE`.

## Later integration (mounts + edge reload)

`--apply` does not recreate the Caddy container. After a successful apply:

1. Overlay the static mount onto the existing compose file (do not replace it):

   ```bash
   cd /opt/acx-backend
   docker compose -f docker-compose.caddy.yml \
     -f /opt/acx-backend/app/docker-compose.app.yml up -d
   ```

   That bind-mounts `/opt/acx-backend/app/www` → `/srv/app-portal` inside
   `caddy`. `docker-compose.caddy.yml` remains the TLS/network owner.

2. Reload or recreate Caddy so it sees both the merged Caddyfile inode and the
   new volume. Prefer `docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile` when the inode already matches; recreate when
   the mount hash diverges (same check as `sync-demo.sh`).

3. Enable the portal router in `/opt/acx-backend/prod/.env`:
   `RECOGNITION_PORTAL_ENABLED=1`, plus the Clerk issuer/JWKS/audience/authorized
   parties already documented in `docs/runbooks/clerk-production-auth.md`. Restart
   the prod API unit after those env changes. Polar webhook URL stays on
   `https://api.altcontext.com/billing/webhooks/polar`, not the app host.

4. DNS: operator A-record `app.altcontext.com` → `129.213.40.111`. Caddy issues
   the cert once that name resolves here.

5. **Re-apply after a shared-edge promote.** `sync-demo.sh` and recognition
   deploy ship the git `Caddyfile` wholesale to `/opt/acx-backend/Caddyfile`.
   That would drop this vhost. Re-run `scripts/deploy/app-portal.sh --apply`
   after those promotes until a later shared-Caddyfile owner absorbs the snippet
   (not this lane; [GRPH-09]).

## Rollback

`/opt/acx-backend/app/rollback/Caddyfile.<ts>` is the pre-activation copy.
Restore by writing it back **in place** (`cat rollback > Caddyfile`), then
reload Caddy. Failed validation never replaces the live file, so rollback is
only needed after a successful activation.

## Out of scope

- Live deploy from this sandbox, production remote-shell from the worker
- Inventing a frontend, Clerk Dashboard clicks, Polar catalog, or new OCI VM
- Editing `apps/prototype-description-service/Caddyfile` or `docker-compose.caddy.yml`
