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
`/billing/return` are frontend paths; billing webhooks stay on the API
host, not the app host.

## Env ownership (do not put secrets in these files)

| Surface | Owner | Names |
| --- | --- | --- |
| This deploy script | app-host lane | `APP_HOSTNAME`, `APP_UPSTREAM`, `APP_ROOT`, `APP_WWW`, `CADDY_COMPOSE`, `APP_FRONTEND_ROOT`, `CADDYFILE`, `FRONTEND_DIST`, `APP_APPROVED_ROOTS`, `APP_RELOAD_CMD`, `APP_HEALTH_CMD`, `APP_PORTAL_ENV_ROOT` |
| Prod API process | `svc-vm` manifest target, including `30-portal-backend.toml` | Clerk runtime settings and production portal enablement are committed in the manifest; materialize `/opt/acx-backend/prod/.env` (mode 0600) and restart the prod API before frontend apply |
| Frontend build | `app-portal-build` public-build manifest target | public `VITE_CLERK_PUBLISHABLE_KEY` and `VITE_CLERK_FAPI`; use the live publishable key variant in production |

`infra/oci/app/env.example` lists the deploy names only. Clerk secret keys and
billing credentials never belong in the snippet, overlay, this runbook's
commands, or apply stdout. The `configure_clerk_production.py` command is a
read-only manifest validator; use the manifest targets as the production
source of truth.

## Before production launch

- The production value `prod = "1"` for `RECOGNITION_PORTAL_ENABLED` is
  committed in `config/env/manifest.d/30-portal-backend.toml`. The API mounts
  `/portal` only when this setting is `1`, `true`, `yes`, or `on`.
- The operator-supplied public live publishable key is committed as the
  `prod` value of `VITE_CLERK_PUBLISHABLE_KEY` in
  `config/env/manifest.d/60-app-portal.toml`; a production build now renders
  the live key. This key is public by design. Do not add a Clerk secret to the
  manifest.
- The VM's Clerk values are already harvested into
  `config/env/manifest.d/30-portal-backend.toml`. Materialization and restart
  are the remaining operator steps; follow the API activation sequence below
  before frontend apply. Resolve any reported runtime drift or missing
  host-only secrets before applying. There is no interim VM writer.

## Default dry-run

From the repo, on the VM filesystem (worker must not open a remote shell):

```bash
scripts/deploy/app-portal.sh
# or
scripts/deploy/app-portal.sh --dry-run
```

Prints the plan, lists live Caddy hosts, and exits 0 without writing. Unsafe
path/upstream/hostname values are still refused **before** any render, copy,
`rm`, or `mv`. If `CADDY_COMPOSE` is not installed yet, dry-run prints the plan
and reports its absence. `--apply` requires a regular Compose file before lock
creation, interrupted recovery, or staging.

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

## Build and apply

The committed React/Vite portal source lives in `apps/app-portal/`. Render its
production public build environment after completing the
[launch checklist](#before-production-launch), install the locked dependencies, and
build the SPA from the repository root:

```bash
make env-render ENV=prod TARGET=app-portal-build
python3 apps/prototype-description-service/scripts/configure_clerk_production.py
npm ci --prefix apps/app-portal
npm --prefix apps/app-portal run build
```

The manifest writes `apps/app-portal/.env.production.local`; it contains only
public build values. `VITE_CLERK_PUBLISHABLE_KEY` is public and must be the
live production key variant. Never put a Clerk secret in the browser build.
The build output is `apps/app-portal/dist/`. `--apply` checks the production
manifest and confirms that reachable JavaScript modules contain the same live
key and FAPI before staging; missing, test, mismatched, or decoy unreferenced
values fail before activation. `APP_PORTAL_ENV_ROOT` can select a manifest
root other than the repository's `config/env` when a deployment uses a
separately checked-out manifest.

### Activate the production API before frontend apply

The portal router enablement and Clerk verifier settings are already committed
in the `svc-vm` environment manifest. From the repository root on the operator
workstation, check the production target first; resolve any runtime drift or
missing host-only secrets before continuing:

```bash
make env-materialize ENV=prod TARGET=svc-vm
```

Still on the operator workstation, materialize the committed production settings:

```bash
make env-materialize ENV=prod TARGET=svc-vm APPLY=1 CONFIRM=prod
```

On the VM, restart the shared prod API so it mounts `/portal` with
`RECOGNITION_PORTAL_ENABLED=1` before frontend health runs:

```bash
sudo systemctl restart acx-prod
```

Confirm an unauthenticated `/portal/me` request returns HTTP **401**, not 404,
before running frontend apply. Use the API host for the first deployment,
when the app vhost may not yet exist:

```bash
(
  if code="$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' https://api.altcontext.com/portal/me)"; then
    if [ "$code" = 401 ]; then
      echo 'portal API mounted (401)'
    else
      echo "STOP: expected 401, got ${code:-none}; do not apply frontend" >&2
      exit 1
    fi
  else
    echo "STOP: portal API probe failed (${code:-none}); do not apply frontend" >&2
    exit 1
  fi
)
```

### Install the checker and apply the frontend

The checked-in `scripts/deploy/app-portal.sh` also provides the health-check
implementation when installed under the name `app-portal-health-check`. Install
that versioned script as a regular executable on the VM:

```bash
sudo install -m 0755 scripts/deploy/app-portal.sh /usr/local/bin/app-portal-health-check
```

It returns zero only when all three probes pass: the live frontend at
`https://app.altcontext.com/` and the production API readiness endpoint at
`https://api.altcontext.com/ready` return successful HTTP responses, and the
unauthenticated `https://app.altcontext.com/portal/me` returns HTTP **401**.
It returns nonzero if any check fails.
The deploy script passes the selected `APP_HOSTNAME` to the checker; hostname
overrides probe that frontend instead. Standalone checks default to
`app.altcontext.com` unless `APP_HOSTNAME` is set.

```bash
FRONTEND_DIST=apps/app-portal/dist \
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

1. Validates paths and `APP_UPSTREAM`. Before staging or
   interrupted recovery changes, resolves Compose configuration as JSON and
   uses `jq` to require the Caddy service's `/etc/caddy/Caddyfile` bind source
   to equal the absolute `CADDYFILE`. Checks the base-only configuration,
   any installed overlay, and the rendered replacement overlay. A mismatch
   names both paths and leaves staging, the journal, and live files untouched.
   Then recovers any interrupted activation by restoring its snapshots,
   reapplying its Compose state, reloading Caddy, and clearing the journal.
   Recovery requires no replacement frontend build. Only after recovery does
   it validate `FRONTEND_DIST`, including its source-path guards; a deleted
   build directory or another unavailable or invalid build exits nonzero
   with the restored live state intact.
2. Stages a merged Caddyfile, a complete www tree, and an overlay with
   `__APP_WWW__` rendered to the selected `APP_WWW`. Existing `api.*`,
   `demo.altcontext.com`, `129-213-40-111.sslip.io`, and `dl.darce.xyz` stay.
3. Runs `caddy validate` on the staged Caddyfile (`--adapter caddyfile`).
4. On validate failure: live Caddyfile, www, and overlay are left untouched.
5. On success: copies complete rollback state to
   `/opt/acx-backend/app/rollback/{Caddyfile,www,docker-compose.app.yml}.<ts>`.
   A previously absent frontend or overlay instead gets `absent-www.<ts>` or
   `absent-overlay.<ts>`, containing exactly `app-portal-absent-www-v1` or
   `app-portal-absent-overlay-v1` plus a newline. These markers are synced before
   activation and remain after success clears the journal. Numeric snapshots
   and markers from older applies are reclaimed, retaining the current set;
   nonnumeric operator files are untouched.
6. Promotes under an ERR/INT/TERM trap:
   - Caddyfile: write a complete sibling, then `cat` into the live inode
     (same bind-mount inode rule as `sync-demo.sh` / GUIDEDEPLOY-1-BR-04).
   - www: atomic rename of the staged directory onto `APP_WWW`.
   - overlay: atomic rename onto `${APP_ROOT}/docker-compose.app.yml`.
7. Applies the base Caddy compose file (default
   `${APP_ROOT%/*}/docker-compose.caddy.yml`) with the rendered overlay using
   `docker compose ... up -d --force-recreate --no-deps caddy`. This recreates
   only Caddy after the directory swap so its bind mount serves the new
   `APP_WWW` at `/srv/app-portal`, even when Compose configuration is unchanged.
   Caddy briefly restarts before frontend health runs. After each recreation,
   including rollback and interrupted recovery, the script probes the container
   admin endpoint up to 10 times (one-second request timeout and one-second
   pauses) before reload. Exhaustion fails activation into rollback; if rollback
   also fails, the journal is retained for retry.
8. Defaults to reloading Caddy in the composed service with
   `docker compose -f "$CADDY_COMPOSE"` and adds `-f "$OVERLAY_DEST"` when the
   overlay exists, then runs `exec -T caddy caddy reload --config
   /etc/caddy/Caddyfile --adapter caddyfile`. First-deploy rollback uses only
   the base compose file. `APP_RELOAD_CMD` is the explicit override.
9. Verifies the promoted Caddyfile, frontend, and overlay, then runs the
   required `APP_HEALTH_CMD` against the live frontend and production API.
10. Any failure at write/move/copy/compose/reload/health restores all three
    rollback artifacts, recreates Caddy with the restored compose state, attempts a
    rollback reload, and **does not** print `applied:`.

Interrupted recovery also recreates Caddy after restoring the frontend snapshot,
including interruptions before overlay promotion, to refresh the directory mount.

Interrupted-activation journals record `CADDY_COMPOSE` alongside the artifact
paths. Recovery refuses a changed path before restoring files or invoking
Compose; rerun with the original deployment paths. Version 1 journals lack this
path and are refused rather than recovered against an unverified Compose project.

Protected hostnames (`api.altcontext.com` and the other live vhosts) cannot be
used as `APP_HOSTNAME`. The shared repo file
`apps/prototype-description-service/Caddyfile` is refused as `CADDYFILE`.

`--apply` requires Docker Compose, `jq`, and the configured `CADDY_COMPOSE` file to
apply the overlay and reload the Caddy service. `APP_RELOAD_CMD` can explicitly
override the reload command. `CADDY_COMPOSE` must be outside staging, rollback,
`APP_WWW`, `APP_WWW.prev`, and the activation destinations (Caddyfile, overlay,
journal, and lock); conflicting paths are refused before mutation. A reload
failure during activation restores the rollback artifacts and prevents the
`applied:` message.

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

Confirm Caddy's mounted Caddyfile matches the host configuration (same check
as `sync-demo.sh`). Both hashes must match before declaring the apply verified:

```bash
sha256sum /opt/acx-backend/Caddyfile
docker compose -f docker-compose.caddy.yml exec -T caddy \
  sha256sum /etc/caddy/Caddyfile
```

If the hashes differ, recreate Caddy to refresh its bind mount, wait for its
admin endpoint with the deployment script's bounded probe, then reload:

```bash
(
  set -euo pipefail
  docker compose -f docker-compose.caddy.yml \
    -f /opt/acx-backend/app/docker-compose.app.yml up -d --force-recreate --no-deps caddy
  ready=0
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if docker compose -f docker-compose.caddy.yml \
      -f /opt/acx-backend/app/docker-compose.app.yml exec -T caddy \
      wget -q -T 1 -O /dev/null http://127.0.0.1:2019/config/; then
      ready=1
      break
    fi
    if [ "$attempt" -lt 10 ]; then
      sleep 1
    fi
  done
  if [ "$ready" -ne 1 ]; then
    echo 'STOP: Caddy admin endpoint not ready after 10 attempts; refusing reload/verification; follow frontend back-out' >&2
    exit 1
  fi
  docker compose -f docker-compose.caddy.yml \
    -f /opt/acx-backend/app/docker-compose.app.yml exec -T caddy \
    caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
  sha256sum /opt/acx-backend/Caddyfile
  docker compose -f docker-compose.caddy.yml exec -T caddy \
    sha256sum /etc/caddy/Caddyfile
  /usr/local/bin/app-portal-health-check
)
```

The subshell stops on recreation/reload failure or readiness exhaustion, before
hash/health verification. The probe uses container-local BusyBox `wget`, a
one-second request timeout, and at most nine one-second pauses between ten
attempts. On exhaustion, follow frontend back-out. Recheck both hashes and
health after recovery. If the hashes still differ or
health fails, follow the [frontend back-out](#frontend-back-out) below before
declaring the apply verified.

Verify all three live probes with the installed checker; backend settings were
materialized and the API restarted before frontend apply:

```bash
/usr/local/bin/app-portal-health-check
```

Billing webhooks stay on the API host, not the app host.

## Shared-edge maintenance

DNS: operator A-record `app.altcontext.com` → `129.213.40.111`. Caddy issues
the cert once that name resolves here.

**Re-apply after a shared-edge promote.** `sync-demo.sh` and recognition deploy
ship the git `Caddyfile` wholesale to `/opt/acx-backend/Caddyfile`. That would
drop this vhost. Re-run `scripts/deploy/app-portal.sh --apply` after those
promotes until a later shared-Caddyfile owner absorbs the snippet (not this
lane; [GRPH-09]).

## Rollback

### Backend back-out

The portal flag mounts both `/portal` and the billing webhooks router in the
shared prod API; missing Clerk verifier settings can prevent API startup.
To back out backend enablement, change the production value of
`RECOGNITION_PORTAL_ENABLED` to `prod = "0"` in
`config/env/manifest.d/30-portal-backend.toml` through the normal reviewed merge.
The manifest is the only writer: there is no interim VM writer, and a hand edit
of `/opt/acx-backend/prod/.env` is reverted as drift at the next materialize.
From the repository root on the operator workstation, check the merged target
and resolve drift or missing host-only secrets:

```bash
make env-materialize ENV=prod TARGET=svc-vm
```

Still on the operator workstation, materialize the disabled flag:

```bash
make env-materialize ENV=prod TARGET=svc-vm APPLY=1 CONFIRM=prod
```

On the VM, restart the shared prod API:

```bash
sudo systemctl restart acx-prod
```

Confirm API readiness recovers and `/portal/me` returns 404 with the router
disabled. Roll the frontend back using the [frontend back-out](#frontend-back-out)
sequence below; the frontend checker expects 401 and will fail while the
backend portal is disabled.

### Frontend back-out

`/opt/acx-backend/app/rollback/Caddyfile.<ts>` plus `www.<ts>` and
`docker-compose.app.yml.<ts>` are the pre-activation copies. For each previously
missing artifact, a validated `absent-www.<ts>` or `absent-overlay.<ts>` replaces
its snapshot. Missing snapshots alone never prove prior absence. Automatic restore
runs on promote/compose/reload/health failure and reapplies the restored compose
state before the rollback reload. On the VM, manual restore selects only
`Caddyfile.<digits>` names and sorts by the numeric filename suffix, never mtime
(`cp -a` preserves the live file's older mtime). It prints the chosen timestamp
and refuses missing, empty, incomplete, or contradictory marker/snapshot sets
before changing live files. Markers must be regular files without symlinks and
match the exact versioned contents written by deployment, including the newline.
The snapshot's `index.html` must be a non-empty regular file, not a symlink.
The live overlay must be a regular file or absent, never a symlink; its parent
must be an existing directory, not a symlink, even when the overlay is absent.
The commands below use the default paths; substitute the same paths used at
apply if they were overridden. Restore the Caddyfile back **in place**,
preserving its bind-mounted inode, and www/overlay from that same timestamp.
The executable branches below restore each snapshot or remove the newly added
artifact only when its absence marker is validated. They support a full snapshot,
first deployment with both artifacts absent, and either mixed prior state:

```bash
(
  set -euo pipefail
  # Reject symlinked parents for every source and destination before any mutation.
  parent=/opt/acx-backend/app/rollback
  while [ "$parent" != / ]; do
    if [ ! -d "$parent" ] || [ -L "$parent" ]; then
      echo 'STOP: rollback/live parent missing or unsafe; refusing restore' >&2
      exit 1
    fi
    parent="$(dirname -- "$parent")"
  done
  if [ ! -d /opt/acx-backend/app/rollback ] || [ -L /opt/acx-backend/app/rollback ]; then
    echo 'STOP: rollback directory missing or unsafe; refusing restore' >&2
    exit 1
  fi
  ts="$(find /opt/acx-backend/app/rollback -maxdepth 1 -type f \
    -name 'Caddyfile.*' -printf '%f\n' -o \
    ! -type f -name 'Caddyfile.*' -printf '%f\n' \
    | sed -n 's/^Caddyfile\.\([0-9][0-9]*\)$/\1/p' \
    | sort -nr | sed -n '1p')"
  if [ -z "$ts" ]; then
    echo 'STOP: no numeric Caddyfile rollback snapshot; refusing restore' >&2
    exit 1
  fi
  echo "Selected rollback timestamp: $ts"
  snapshot="/opt/acx-backend/app/rollback/Caddyfile.$ts"
  www_snapshot="/opt/acx-backend/app/rollback/www.$ts"
  overlay_snapshot="/opt/acx-backend/app/rollback/docker-compose.app.yml.$ts"
  www_absent="/opt/acx-backend/app/rollback/absent-www.$ts"
  overlay_absent="/opt/acx-backend/app/rollback/absent-overlay.$ts"
  if [ ! -f "$snapshot" ] || [ ! -s "$snapshot" ] || [ -L "$snapshot" ]; then
    echo 'STOP: no non-empty regular Caddyfile rollback snapshot; refusing restore' >&2
    exit 1
  fi
  restore_www=1
  if [ -e "$www_absent" ] || [ -L "$www_absent" ]; then
    if [ ! -f "$www_absent" ] || [ -L "$www_absent" ] \
      || ! cmp -s -- "$www_absent" <(printf 'app-portal-absent-www-v1\n') \
      || [ -e "$www_snapshot" ] || [ -L "$www_snapshot" ]; then
      echo "STOP: invalid or contradictory frontend absence marker at $ts; refusing restore" >&2
      exit 1
    fi
    restore_www=0
  elif [ ! -d "$www_snapshot" ] || [ -L "$www_snapshot" ] \
    || [ ! -f "$www_snapshot/index.html" ] || [ ! -s "$www_snapshot/index.html" ] \
    || [ -L "$www_snapshot/index.html" ]; then
    echo "STOP: incomplete rollback snapshot at $ts; refusing restore" >&2
    exit 1
  fi
  restore_overlay=1
  if [ -e "$overlay_absent" ] || [ -L "$overlay_absent" ]; then
    if [ ! -f "$overlay_absent" ] || [ -L "$overlay_absent" ] \
      || ! cmp -s -- "$overlay_absent" <(printf 'app-portal-absent-overlay-v1\n') \
      || [ -e "$overlay_snapshot" ] || [ -L "$overlay_snapshot" ]; then
      echo "STOP: invalid or contradictory overlay absence marker at $ts; refusing restore" >&2
      exit 1
    fi
    restore_overlay=0
  elif [ ! -f "$overlay_snapshot" ] || [ ! -s "$overlay_snapshot" ] || [ -L "$overlay_snapshot" ]; then
    echo "STOP: incomplete rollback snapshot at $ts; refusing restore" >&2
    exit 1
  fi
  if [ ! -f /opt/acx-backend/Caddyfile ] || [ -L /opt/acx-backend/Caddyfile ]; then
    echo 'STOP: live Caddyfile must be an existing regular file; refusing restore' >&2
    exit 1
  fi
  if [ ! -d /opt/acx-backend/app ] || [ -L /opt/acx-backend/app ]; then
    echo 'STOP: live overlay parent must be an existing directory without symlinks; refusing restore' >&2
    exit 1
  fi
  if [ -L /opt/acx-backend/app/docker-compose.app.yml ] \
    || { [ -e /opt/acx-backend/app/docker-compose.app.yml ] \
      && [ ! -f /opt/acx-backend/app/docker-compose.app.yml ]; }; then
    echo 'STOP: live overlay must be a regular file or absent without symlinks; refusing restore' >&2
    exit 1
  fi
  if [ -L /opt/acx-backend/app/www ] \
    || { [ -e /opt/acx-backend/app/www ] && [ ! -d /opt/acx-backend/app/www ]; }; then
    echo 'STOP: live frontend must be a directory or absent without symlinks; refusing restore' >&2
    exit 1
  fi
  cp -- "$snapshot" /opt/acx-backend/Caddyfile
  rm -rf -- /opt/acx-backend/app/www
  if [ "$restore_www" -eq 1 ]; then
    cp -a -- "$www_snapshot" /opt/acx-backend/app/www
  fi
  if [ "$restore_overlay" -eq 1 ]; then
    cp -- "$overlay_snapshot" /opt/acx-backend/app/docker-compose.app.yml
  else
    rm -f -- /opt/acx-backend/app/docker-compose.app.yml
  fi
  cd /opt/acx-backend
  compose=(docker compose -f docker-compose.caddy.yml)
  if [ "$restore_overlay" -eq 1 ]; then
    compose+=(-f /opt/acx-backend/app/docker-compose.app.yml)
    docker compose -f docker-compose.caddy.yml \
      -f /opt/acx-backend/app/docker-compose.app.yml up -d --force-recreate --no-deps caddy
  else
    docker compose -f docker-compose.caddy.yml up -d --force-recreate --no-deps caddy
  fi
  ready=0
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if "${compose[@]}" exec -T caddy wget -q -T 1 -O /dev/null \
      http://127.0.0.1:2019/config/; then
      ready=1
      break
    fi
    if [ "$attempt" -lt 10 ]; then
      sleep 1
    fi
  done
  if [ "$ready" -ne 1 ]; then
    echo 'STOP: Caddy admin endpoint not ready after 10 attempts; restored files retained; refusing reload; investigate Caddy startup before retry' >&2
    exit 1
  fi
  if [ "$restore_overlay" -eq 1 ]; then
    docker compose -f docker-compose.caddy.yml \
      -f /opt/acx-backend/app/docker-compose.app.yml exec -T caddy \
      caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
  else
    docker compose -f docker-compose.caddy.yml exec -T caddy \
      caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
  fi
)
```

The block reapplies the prior compose overlay and reloads Caddy only after every
guard, the full restore, and bounded admin readiness polling succeed. With a prior
overlay, it uses both compose files for recreation, probing, and reload. As in
fix-forward, it attempts the container-local admin probe up to ten times with a
one-second request timeout and at most nine one-second pauses. Exhaustion prints
STOP and leaves the restored files in place without reloading Caddy; investigate
Caddy startup before retrying, and do not declare recovery verified.

If there was no prior overlay (first deployment), automatic rollback uses its
activation journal's recorded absence. Manual rollback uses the durable validated
absence markers even after a successful apply has cleared that journal. With both
markers it removes the newly installed overlay and frontend directory after all
guards pass, restores the Caddyfile in place, and uses the base compose file alone
for recreation, the same bounded readiness probe, and reload in the block above.

Failed validation never replaces the live files, so rollback is only needed
after activation has started.

## Out of scope

- Live deploy from this sandbox, production remote-shell from the worker
- Clerk Dashboard changes, billing-provider catalog setup, or new OCI VM
- Editing `apps/prototype-description-service/Caddyfile` or `docker-compose.caddy.yml`
