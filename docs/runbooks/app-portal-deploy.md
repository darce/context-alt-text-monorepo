# App portal host — app.altcontext.com on the existing OCI VM

Prepare the public customer hostname on **the current edge**, host
`129.213.40.111` (`acx-backend`). This lane does **not** provision a new
machine, does **not** edit the shared git `Caddyfile`, and does **not** deploy
live from a sandbox worker.

Bounded artifacts:

- `infra/oci/app/Caddyfile.app` — public vhost snippet
- `infra/oci/app/docker-compose.app.yml` — static-root overlay template (`__APP_WWW__`)
- `infra/oci/app/env.example` — deploy input names only
- `scripts/deploy/app-portal.sh` — dry-run by default; `--apply` on the VM

Canon: [GRPH-09] keep this vhost off the shared Caddyfile so demo/API owners
do not collide; exact `path /portal /portal/*` (not `/portal*`) so `/portalfoo`
is not proxied; [GRPH-31] render the overlay to the chosen `APP_WWW`;
[RES-02] fail closed on missing builds, failed `caddy validate`, and any
promote/reload/health failure with rollback; [RES-01]/[RES-05] no remote-shell
retries, and reject `/`, symlink components, and paths outside
`APP_APPROVED_ROOTS` before any write.

## What the vhost exposes

HTTPS `app.altcontext.com` (Caddy ACME, same edge as `api.altcontext.com`):

| Path | Behaviour |
| --- | --- |
| `/portal` plus `/portal/*` | named matcher `@portal path /portal /portal/*`; `reverse_proxy` to `prod-api:8000` |
| `/` static SPA | `root * /srv/app-portal` + `try_files {path} /index.html` |
| `/admin`, `/admin/*` | `404` (same public denial as the API vhosts) |
| `/recognition`, `/roster`, `/scene`, `/billing/webhooks`, `/health`, `/ready`, `/metrics`, `/docs`, `/x` | `404` — those surfaces stay on `api.altcontext.com` |

`/portalfoo` and `/portal-admin` are **not** API paths. SPA routes such as
`/billing/return` are frontend paths, not the Polar webhook.

## Env ownership (do not put secrets in these files)

| Surface | Owner | Names |
| --- | --- | --- |
| This deploy script | app-host lane | `APP_HOSTNAME`, `APP_UPSTREAM`, `APP_ROOT`, `APP_WWW`, `CADDY_COMPOSE`, `APP_FRONTEND_ROOT`, `CADDYFILE`, `FRONTEND_DIST`, `APP_APPROVED_ROOTS`, `APP_RELOAD_CMD`, `APP_HEALTH_CMD` |
| Prod API process | backend/portal composition | `RECOGNITION_PORTAL_ENABLED=1` and Clerk/Polar keys in `/opt/acx-backend/prod/.env` (mode 0600) |
| Frontend build | later `apps/app-portal` build | `VITE_CLERK_PUBLISHABLE_KEY`, `VITE_CLERK_FAPI` baked by `configure_clerk_production.py` |

`infra/oci/app/env.example` lists the deploy names only. Clerk secret keys and
Polar tokens never belong in the snippet, overlay, this runbook's commands, or
apply stdout.

## Default dry-run

From the repo, on the VM filesystem (worker must not open a remote shell):

```bash
scripts/deploy/app-portal.sh
# or
scripts/deploy/app-portal.sh --dry-run
```

Prints the plan, lists live Caddy hosts, and exits 0 without writing. Unsafe
path/upstream/hostname values are still refused **before** any render, copy,
`rm`, or `mv`.

## Path and symlink safety

Destinations (`CADDYFILE`, `APP_ROOT`, `APP_WWW`) must be strict children of
`APP_APPROVED_ROOTS` (default `/opt/acx-backend`). The script rejects:

- filesystem root `/`
- symlink components (including a symlink `CADDYFILE`)
- path traversal (`..`) and empty components (`//`)
- file-vs-directory mismatches (Caddyfile must be a regular file; www/root dirs)
- `APP_FRONTEND_ROOT` other than `/srv/app-portal` (prevents `file_server` on `/`)
- `APP_WWW` equal to `APP_ROOT` or inside `rollback/` / `staging/`

`FRONTEND_DIST`, the snippet, and the overlay template are sources: regular
file/directory, no symlink components, never `/`. They are not required to
live under `APP_APPROVED_ROOTS`.

## Apply (only with a real frontend build)

There is no committed `apps/app-portal` in this tree. Do **not** generate a
placeholder `index.html`. `--apply` refuses a missing dist, empty `index.html`,
or empty `assets/`.

The checked-in `scripts/deploy/app-portal.sh` also provides the health-check
implementation when installed under the name `app-portal-health-check`. Install
that versioned script as a regular executable on the VM:

```bash
sudo install -m 0755 scripts/deploy/app-portal.sh /usr/local/bin/app-portal-health-check
```

It returns zero only when both the live frontend at
`https://app.altcontext.com/` and the production API readiness endpoint at
`https://api.altcontext.com/ready` return successful HTTP responses. It returns
nonzero if either check fails.
The deploy script passes the selected `APP_HOSTNAME` to the checker; hostname
overrides probe that frontend instead. Standalone checks default to
`app.altcontext.com` unless `APP_HOSTNAME` is set.

```bash
FRONTEND_DIST=/absolute/path/to/real/dist \
APP_UPSTREAM=prod-api:8000 \
CADDYFILE=/opt/acx-backend/Caddyfile \
APP_HEALTH_CMD=/usr/local/bin/app-portal-health-check \
scripts/deploy/app-portal.sh --apply
```

`--apply` mutates host files, applies the rendered compose overlay on the VM,
then reloads and health-checks under a trap. It does not access the live VM from
a sandbox; tests inject fake `docker` and Caddy validators plus health/reload
overrides.

`--apply` then:

1. Validates paths, `FRONTEND_DIST`, and `APP_UPSTREAM`.
2. Stages a merged Caddyfile, a complete www tree, and an overlay with
   `__APP_WWW__` rendered to the selected `APP_WWW`. Existing `api.*`,
   `demo.altcontext.com`, `129-213-40-111.sslip.io`, and `dl.darce.xyz` stay.
3. Runs `caddy validate` on the staged Caddyfile (`--adapter caddyfile`).
4. On validate failure: live Caddyfile, www, and overlay are left untouched.
5. On success: copies complete rollback state to
   `/opt/acx-backend/app/rollback/{Caddyfile,www,docker-compose.app.yml}.<ts>`.
6. Promotes under an ERR/INT/TERM trap:
   - Caddyfile: write a complete sibling, then `cat` into the live inode
     (same bind-mount inode rule as `sync-demo.sh` / GUIDEDEPLOY-1-BR-04).
   - www: atomic rename of the staged directory onto `APP_WWW`.
   - overlay: atomic rename onto `${APP_ROOT}/docker-compose.app.yml`.
7. Applies the base Caddy compose file (default
   `${APP_ROOT%/*}/docker-compose.caddy.yml`) with the rendered overlay using
   `docker compose ... up -d`. This attaches `APP_WWW` at `/srv/app-portal`
   before frontend health runs.
8. Defaults to reloading Caddy in the composed service with
   `docker compose -f "$CADDY_COMPOSE"` and adds `-f "$OVERLAY_DEST"` when the
   overlay exists, then runs `exec -T caddy caddy reload --config
   /etc/caddy/Caddyfile --adapter caddyfile`. First-deploy rollback uses only
   the base compose file. `APP_RELOAD_CMD` is the explicit override.
9. Verifies the promoted Caddyfile, frontend, and overlay, then runs the
   required `APP_HEALTH_CMD` against the live frontend and production API.
10. Any failure at write/move/copy/compose/reload/health restores all three
    rollback artifacts, reapplies the restored compose state, attempts a
    rollback reload, and **does not** print `applied:`.

Interrupted-activation journals record `CADDY_COMPOSE` alongside the artifact
paths. Recovery refuses a changed path before restoring files or invoking
Compose; rerun with the original deployment paths. Version 1 journals lack this
path and are refused rather than recovered against an unverified Compose project.

Protected hostnames (`api.altcontext.com` and the other live vhosts) cannot be
used as `APP_HOSTNAME`. The shared repo file
`apps/prototype-description-service/Caddyfile` is refused as `CADDYFILE`.

`--apply` requires Docker Compose and the configured `CADDY_COMPOSE` file to
apply the overlay and reload the Caddy service. `APP_RELOAD_CMD` can explicitly
override the reload command. A reload failure during activation restores the
rollback artifacts and prevents the `applied:` message.

## After apply (verify edge + API configuration)

`--apply` applies the **rendered** static mount (not the repo template) to the
existing Caddy compose configuration before health checking. After a successful
apply, confirm the mount is present:

```bash
cd /opt/acx-backend
docker compose -f docker-compose.caddy.yml \
  -f /opt/acx-backend/app/docker-compose.app.yml exec -T caddy \
  sh -c 'test -s /srv/app-portal/index.html && test -d /srv/app-portal/assets'
```

The mount exposes the chosen `APP_WWW` (default `/opt/acx-backend/app/www`) at
`/srv/app-portal` inside `caddy`. `docker-compose.caddy.yml` remains the
TLS/network owner. A custom `APP_WWW` is already baked into the published
overlay; do not compose the `__APP_WWW__` template.

Reload or recreate Caddy if its mounted Caddyfile does not match the host
configuration. Use `docker compose -f /opt/acx-backend/docker-compose.caddy.yml
-f /opt/acx-backend/app/docker-compose.app.yml exec -T caddy caddy reload
--config /etc/caddy/Caddyfile --adapter caddyfile` when the inode already
matches; recreate when the mount hash diverges (same check as `sync-demo.sh`).
Compare:

```bash
sha256sum /opt/acx-backend/Caddyfile
docker compose -f docker-compose.caddy.yml exec -T caddy \
  sha256sum /etc/caddy/Caddyfile
```

Enable the portal router in `/opt/acx-backend/prod/.env`:
`RECOGNITION_PORTAL_ENABLED=1`, plus the Clerk issuer/JWKS/audience/authorized
parties already documented in `docs/runbooks/clerk-production-auth.md`. Restart
the prod API unit after those env changes. Polar webhook URL stays on
`https://api.altcontext.com/billing/webhooks/polar`, not the app host.

DNS: operator A-record `app.altcontext.com` → `129.213.40.111`. Caddy issues
the cert once that name resolves here.

**Re-apply after a shared-edge promote.** `sync-demo.sh` and recognition deploy
ship the git `Caddyfile` wholesale to `/opt/acx-backend/Caddyfile`. That would
drop this vhost. Re-run `scripts/deploy/app-portal.sh --apply` after those
promotes until a later shared-Caddyfile owner absorbs the snippet (not this
lane; [GRPH-09]).

## Rollback

`/opt/acx-backend/app/rollback/Caddyfile.<ts>` plus `www.<ts>` and
`docker-compose.app.yml.<ts>` are the pre-activation copies. Automatic restore
runs on promote/compose/reload/health failure and reapplies the restored compose
state before the rollback reload. Manual restore: write the Caddyfile back
**in place** (`cat rollback > Caddyfile`), restore www/overlay, then reapply
the prior compose overlay and reload Caddy. Use these commands only when a prior
overlay snapshot was restored:

```bash
cd /opt/acx-backend
docker compose -f docker-compose.caddy.yml \
  -f /opt/acx-backend/app/docker-compose.app.yml up -d
docker compose -f docker-compose.caddy.yml \
  -f /opt/acx-backend/app/docker-compose.app.yml exec -T caddy \
  caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

If there was no prior overlay (first deployment), remove the newly installed
`/opt/acx-backend/app/docker-compose.app.yml` and frontend directory instead of
restoring absent snapshots. After restoring the Caddyfile in place, use the base
compose file alone:

```bash
cd /opt/acx-backend
docker compose -f docker-compose.caddy.yml up -d
docker compose -f docker-compose.caddy.yml exec -T caddy \
  caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Failed validation never replaces the live files, so rollback is only needed
after activation has started.

## Out of scope

- Live deploy from this sandbox, production remote-shell from the worker
- Inventing a frontend, Clerk Dashboard clicks, Polar catalog, or new OCI VM
- Editing `apps/prototype-description-service/Caddyfile` or `docker-compose.caddy.yml`
