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
| This deploy script | app-host lane | `APP_HOSTNAME`, `APP_UPSTREAM`, `APP_ROOT`, `APP_WWW`, `APP_FRONTEND_ROOT`, `CADDYFILE`, `FRONTEND_DIST`, `APP_APPROVED_ROOTS`, `APP_RELOAD_CMD`, `APP_HEALTH_CMD` |
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

```bash
FRONTEND_DIST=/absolute/path/to/real/dist \
APP_UPSTREAM=prod-api:8000 \
CADDYFILE=/opt/acx-backend/Caddyfile \
scripts/deploy/app-portal.sh --apply
```

`--apply` is **not** staging-only. It mutates host files, then reloads and
health-checks under a trap. It does **not** run live VM `docker compose` from a
sandbox; tests inject fake `caddy` / `APP_RELOAD_CMD` / `APP_HEALTH_CMD`.

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
7. Reload (`APP_RELOAD_CMD` or `caddy reload --config "$CADDYFILE"`).
8. Health (`APP_HEALTH_CMD` or local artifact checks: hostname in Caddyfile,
   `APP_WWW/index.html`, overlay contains `APP_WWW`).
9. Any failure at write/move/copy/reload/health restores the three rollback
   artifacts, attempts a rollback reload, and **does not** print `applied:`.

Protected hostnames (`api.altcontext.com` and the other live vhosts) cannot be
used as `APP_HOSTNAME`. The shared repo file
`apps/prototype-description-service/Caddyfile` is refused as `CADDYFILE`.

If reload is skipped because neither `caddy` nor `APP_RELOAD_CMD` is present,
stdout says so and does **not** claim the edge process picked up the new
inode. Host files may still be activated; follow the operator sequence below.

## Later integration (mounts + edge reload)

`--apply` does not recreate the Caddy container. After a successful apply:

1. Overlay the **rendered** static mount (not the repo template) onto the
   existing compose file (do not replace it):

   ```bash
   cd /opt/acx-backend
   docker compose -f docker-compose.caddy.yml \
     -f /opt/acx-backend/app/docker-compose.app.yml up -d
   ```

   That bind-mounts the chosen `APP_WWW` (default `/opt/acx-backend/app/www`)
   → `/srv/app-portal` inside `caddy`. `docker-compose.caddy.yml` remains the
   TLS/network owner. A custom `APP_WWW` is already baked into the published
   overlay; do not compose the `__APP_WWW__` template.

2. Reload or recreate Caddy so it sees both the merged Caddyfile inode and the
   new volume. Prefer `docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile` when the inode already matches; recreate when
   the mount hash diverges (same check as `sync-demo.sh`). Compare:

   ```bash
   sha256sum /opt/acx-backend/Caddyfile
   docker compose -f docker-compose.caddy.yml exec -T caddy \
     sha256sum /etc/caddy/Caddyfile
   ```

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

`/opt/acx-backend/app/rollback/Caddyfile.<ts>` plus `www.<ts>` and
`docker-compose.app.yml.<ts>` are the pre-activation copies. Automatic restore
runs on promote/reload/health failure. Manual restore: write the Caddyfile back
**in place** (`cat rollback > Caddyfile`), restore www/overlay, then reload
Caddy. Failed validation never replaces the live files, so rollback is only
needed after activation has started.

## Out of scope

- Live deploy from this sandbox, production remote-shell from the worker
- Inventing a frontend, Clerk Dashboard clicks, Polar catalog, or new OCI VM
- Editing `apps/prototype-description-service/Caddyfile` or `docker-compose.caddy.yml`
