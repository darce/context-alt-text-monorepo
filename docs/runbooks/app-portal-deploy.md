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

Canon v0.26.2: the shared lock serializes portal and recognition publication:
[GRPH-09 — Colour the conflict graph](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/graph-theory.md#grph-09)
(*Graph Theory with Applications*, ch. 8). Snapshot, journal, restore and recovery
are rehearsed before publication:
[RLSE-08 — Rollback written before ship](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#rlse-08)
(*Continuous Delivery*, ch. 10 and ch. 12). The exact source, prior P baseline and
bounded test receipts travel in the author report:
[GRPH-14 — Record provenance as a walkable lineage graph](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/graph-theory.md#grph-14)
(*Building Knowledge Graphs*, ch. 8; *Mental Models*, ch. 8).

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

- **STOP:** before materialization or deployment, `main` must contain
  `apps/prototype-description-service/scripts/manage_portal_invitations.py`
  from PORTALDEV-1, and the combined-main production service release to deploy
  must include that CLI. Follow the
  [Clerk production LAUNCH prerequisite](clerk-production-auth.md#production-launch-prerequisite-before-a3deployment):
  PORTALPROD-1 config mainmerge, then PORTALDEV-1 union/mainmerge, then launch
  from that combined main candidate. Before public frontend apply or signed-in
  smoke, the combined-main service release must be deployed and its invitation
  CLI verified in the running production API. A restart alone does not install code.
- The production value `prod = "1"` for `RECOGNITION_PORTAL_ENABLED` is
  committed in `config/env/manifest.d/30-portal-backend.toml`. The API mounts
  `/portal` only when this setting is `1`, `true`, `yes`, or `on`.
- The operator-supplied public live publishable key is committed as the
  `prod` value of `VITE_CLERK_PUBLISHABLE_KEY` in
  `config/env/manifest.d/60-app-portal.toml`; a production build now renders
  the live key. This key is public by design. Do not add a Clerk secret to the
  manifest.
- The VM's Clerk values are already harvested into
  `config/env/manifest.d/30-portal-backend.toml`. The remaining operator steps
  are: confirm the combined-main source/release prerequisite; check and
  materialize the production manifest; deploy the combined-main service with
  `make deploy-prod CONFIRM=PROMOTE` (which restarts and verifies `acx-prod`
  with the materialized environment); verify the
  deployed invitation CLI and API mounting; apply the frontend; then issue a
  matching, unexpired invitation and perform signed-in smoke. Follow the API
  activation sequence below. Resolve any reported runtime drift or missing
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

**STOP:** before the first materialization below, `main` must contain
`apps/prototype-description-service/scripts/manage_portal_invitations.py` from
PORTALDEV-1 and the combined-main production service release to deploy must
include it. Follow the
[Clerk production LAUNCH prerequisite](clerk-production-auth.md#production-launch-prerequisite-before-a3deployment).
Do not apply the public frontend or begin signed-in smoke until that release
has been deployed and the container CLI check below succeeds.

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

Next, from a clean, synced combined-main checkout on the operator workstation,
deploy the production service release including PORTALDEV-1's invitation CLI:

```bash
make deploy-prod CONFIRM=PROMOTE
```

This is the supported target in `mk/deploy.mk`; it invokes
`scripts/deploy/recognition-service.sh deploy prod`. Its
`preflight_env_manifest` runs `materialize_remote.sh prod svc-vm --check`
before building or promoting, and refuses runtime drift or missing host-only
secrets. Therefore check/materialize **before** service deployment: requiring
the new release to be deployed before materialization would block the deploy
on the very manifest change being activated. Do not bypass the manifest
preflight or any other deployment safety gate. The source/release prerequisite
precedes materialization; the deployed-code prerequisite precedes public launch.

The deploy target builds, ships, restarts `acx-prod` with the materialized
environment (including `RECOGNITION_PORTAL_ENABLED=1`), and verifies the service.
A restart alone does not install code. Continue only after this verified deploy
succeeds; the CLI check and the HTTP 401 probe below follow that verification.

On the VM, fail closed if the running production container cannot load the
invitation CLI. This checks deployed code without issuing an invitation:

```bash
(
  set -euo pipefail
  if ! (cd /opt/acx-backend/prod && docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_portal_invitations --help); then
    echo 'STOP: deployed production invitation CLI unavailable; do not apply frontend or begin signed-in smoke' >&2
    exit 1
  fi
)
```

Any directory, Compose, container, or CLI failure is a STOP; resolve the failed
service deployment and rerun this check before continuing. After frontend
apply, follow the [Clerk signed-in smoke check](clerk-production-auth.md#post-launch-signed-in-smoke-check):
the smoke account needs a matching, unexpired operator-issued portal invitation
for its verified primary email. Configuration materialization and process
restart cannot substitute for deploying the invitation CLI.

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
   Then recovers any interrupted activation: promotion phases restore snapshots,
   reapply Compose state, and reload Caddy; `snapshotting` only cleans planned
   partial snapshots, and `restored` only retries failed-set cleanup. Cleanup
   is synced before clearing the journal last. See the exact
   [recovery invocation](#recover-an-interrupted-frontend-activation) below.
   Recovery requires no replacement frontend build. Only after recovery does
   it validate `FRONTEND_DIST`, including its source-path guards; a deleted
   build directory or another unavailable or invalid build exits nonzero
   with the restored live state intact.
2. Stages a merged Caddyfile, a complete www tree, and an overlay with
   `__APP_WWW__` rendered to the selected `APP_WWW`. Existing `api.*`,
   `demo.altcontext.com`, `129-213-40-111.sslip.io`, and `dl.darce.xyz` stay.
3. Runs `caddy validate` on the staged Caddyfile (`--adapter caddyfile`).
4. On validate failure: live Caddyfile, www, and overlay are left untouched.
5. On success: durably journals all planned snapshot/marker paths at
   `phase=snapshotting` **before** writing the first snapshot or absence marker,
   then copies complete rollback state to
   `/opt/acx-backend/app/rollback/{Caddyfile,www,docker-compose.app.yml}.<ts>`.
   A previously absent frontend or overlay instead gets `absent-www.<ts>` or
   `absent-overlay.<ts>`, containing exactly `app-portal-absent-www-v1` or
   `app-portal-absent-overlay-v1` plus a newline. These markers are synced before
   activation and remain after success clears the journal. Numeric snapshots
   and markers from older applies are reclaimed only after a successful apply,
   retaining that apply's prestate set; nonnumeric operator files are untouched.
   A failed apply must not displace the last successful apply's prestate set.
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
8. Selects the effective generation with `edge_compose_args "$CADDY_COMPOSE"
   "$OVERLAY_DEST"`, then uses `EDGE_COMPOSE_ARGV` for recreation, readiness
   probes and reload. Absent staging/prod Aura networks are omitted by the
   helper; the installed overlay participates whenever present. Reload runs
   `exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile`.
   `APP_RELOAD_CMD` is the explicit override. The reviewed helper is atomically
   packaged at `${APP_ROOT}/shared-edge.sh` before clearing the journal, so
   later manual recovery does not require a checkout or retained `/tmp` files.
9. Verifies the promoted Caddyfile, frontend, and overlay, then runs the
   required `APP_HEALTH_CMD` against the live frontend and production API.
10. Any failure at write/move/copy/compose/reload/health restores all three
    rollback artifacts, recreates Caddy with the restored compose state, attempts a
    rollback reload, and **does not** print `applied:`. Successful failed-apply
    restore clears its journal and removes only its duplicate timestamp set,
    preserving the last successful apply's prestate set for manual back-out.
    Failed restore retains the journal and all snapshot/absence-marker inputs
    for retry; it does not reclaim rollback sets.

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
existing Caddy compose configuration before health checking. The commands below
load the helper packaged by that apply at `${APP_ROOT}/shared-edge.sh`.
For an older apply, use the four-file recovery transport below and export
`APP_SHARED_EDGE_LIB=/tmp/app-portal-recovery.shared-edge.sh` first. No VM
checkout is required. After a successful apply, confirm the mount is present:

```bash
(
  set -euo pipefail
  cd /opt/acx-backend
  helper="${APP_SHARED_EDGE_LIB:-/opt/acx-backend/app/shared-edge.sh}"
  if [ ! -f "$helper" ] || [ -L "$helper" ]; then
    echo 'STOP: reviewed shared-edge helper missing or unsafe' >&2
    exit 1
  fi
  source "$helper"
  trap 'edge_compose_cleanup' EXIT
  edge_compose_args docker-compose.caddy.yml /opt/acx-backend/app/docker-compose.app.yml
  edge_bounded_run docker compose "${EDGE_COMPOSE_ARGV[@]}" exec -T caddy \
    sh -c 'test -s /srv/app-portal/index.html && test -d /srv/app-portal/assets'
)
```

The mount exposes the chosen `APP_WWW` (default `/opt/acx-backend/app/www`) at
`/srv/app-portal` inside `caddy`. `docker-compose.caddy.yml` remains the
TLS/network owner. A custom `APP_WWW` is already baked into the published
overlay; do not compose the `__APP_WWW__` template.

Confirm Caddy's mounted Caddyfile matches the host configuration (same check
as `sync-demo.sh`). Both hashes must match before declaring the apply verified:

```bash
(
  set -euo pipefail
  cd /opt/acx-backend
  helper="${APP_SHARED_EDGE_LIB:-/opt/acx-backend/app/shared-edge.sh}"
  if [ ! -f "$helper" ] || [ -L "$helper" ]; then
    echo 'STOP: reviewed shared-edge helper missing or unsafe' >&2
    exit 1
  fi
  source "$helper"
  trap 'edge_compose_cleanup' EXIT
  edge_compose_args docker-compose.caddy.yml /opt/acx-backend/app/docker-compose.app.yml
  sha256sum /opt/acx-backend/Caddyfile
  edge_bounded_run docker compose "${EDGE_COMPOSE_ARGV[@]}" exec -T caddy \
    sha256sum /etc/caddy/Caddyfile
)
```

If the hashes differ, recreate Caddy to refresh its bind mount, wait for its
admin endpoint with the deployment script's bounded probe, then reload:

```bash
(
  set -euo pipefail
  cd /opt/acx-backend
  helper="${APP_SHARED_EDGE_LIB:-/opt/acx-backend/app/shared-edge.sh}"
  if [ ! -f "$helper" ] || [ -L "$helper" ]; then
    echo 'STOP: reviewed shared-edge helper missing or unsafe; refusing fix-forward' >&2
    exit 1
  fi
  source "$helper"
  # Refuse symlinked ancestors before opening the persistent lock.
  parent=/opt/acx-backend/app
  while [ "$parent" != / ]; do
    if [ ! -d "$parent" ] || [ -L "$parent" ]; then
      echo 'STOP: live parent missing or unsafe; refusing fix-forward' >&2
      exit 1
    fi
    parent="$(dirname -- "$parent")"
  done
  # Hold the same persistent inode through selection, recreation and reload.
  lock=/opt/acx-backend/app/activation.journal.lock
  if [ -L "$lock" ] || { [ -e "$lock" ] && [ ! -f "$lock" ]; }; then
    echo 'STOP: deployment lock path unsafe; refusing fix-forward' >&2
    exit 1
  fi
  exec 9>>"$lock"
  flock -w "${APP_DEPLOY_LOCK_WAIT:-30}" 9
  if [ -e /opt/acx-backend/app/activation.journal ] || [ -L /opt/acx-backend/app/activation.journal ]; then
    echo 'STOP: activation journal present; recover interrupted activation before fix-forward' >&2
    exit 1
  fi
  trap 'edge_compose_cleanup' EXIT
  edge_compose_args docker-compose.caddy.yml /opt/acx-backend/app/docker-compose.app.yml
  compose=(docker compose "${EDGE_COMPOSE_ARGV[@]}")
  if [ "${#EDGE_COMPOSE_ARGV[@]}" -eq 4 ] && [ "${EDGE_COMPOSE_ARGV[1]}" = docker-compose.caddy.yml ]; then
    # Unmarked legacy base with an overlay: exactly the helper-selected files.
    edge_bounded_run docker compose -f docker-compose.caddy.yml \
      -f /opt/acx-backend/app/docker-compose.app.yml up -d --force-recreate --no-deps caddy 9>&-
  else
    edge_bounded_run "${compose[@]}" up -d --force-recreate --no-deps caddy 9>&-
  fi
  ready=0
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if edge_bounded_run "${compose[@]}" exec -T caddy \
      wget -q -T 1 -O /dev/null http://127.0.0.1:2019/config/ 9>&-; then
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
  edge_bounded_run "${compose[@]}" exec -T caddy \
    caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile 9>&-
  sha256sum /opt/acx-backend/Caddyfile
  if [ "${EDGE_COMPOSE_ARGV[1]}" = docker-compose.caddy.yml ]; then
    edge_bounded_run docker compose -f docker-compose.caddy.yml exec -T caddy \
      sha256sum /etc/caddy/Caddyfile 9>&-
  else
    edge_bounded_run "${compose[@]}" exec -T caddy sha256sum /etc/caddy/Caddyfile 9>&-
  fi
  edge_bounded_run /usr/local/bin/app-portal-health-check 9>&-
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

**Protected hosts.** `app-portal.sh` refuses to claim any host that another stack
owns, using `EDGE_PROTECTED_HOSTS` from `scripts/deploy/lib/shared-edge.sh`:
`api.altcontext.com`, `staging.api.altcontext.com`, `dev.api.altcontext.com`,
`fir.dev.api.altcontext.com`, `demo.altcontext.com`, `129-213-40-111.sslip.io`,
`dl.darce.xyz`, and the three AuraFace hosts `auraface.dev.altcontext.com`,
`auraface.staging.api.altcontext.com`, and `auraface.api.altcontext.com`.
A managed portal block that names any of these hosts is refused as malformed.

**Shared deploy lock.** Apply takes `${APP_ROOT}/activation.journal.lock`, the same
inode the shared edge uses. The wait is `APP_DEPLOY_LOCK_WAIT` seconds (default
30; integers 0 through 3600). A busy lock refuses with no mutation. A short holder
process keeps the flock, and the script releases it on every exit path. The holder
also exits if the apply shell dies, so a crashed apply does not block later deploys
for longer than the owner's exit. Never truncate, unlink, or replace the lock file.
Recognition-side convergence adopts the same lock in its own change; this runbook
does not claim that behavior until that change lands.

The holder cap is 7200 seconds. The complete apply/recovery transaction gets
7080 seconds, with a watchdog that also exits on owner death. Before each
operation, the next operation's deadline plus kill grace must fit both the
transaction budget and the ownership expiry. Each filesystem mutation is
fenced, including journal transitions, snapshots, promotion, restoration,
cleanup and sync. Validation and health calls are checked again on return.
A dead, expired, unknown or insufficient hold exits 5 immediately and retains
any existing journal and staged files; it never attempts an unfenced rollback.
The next apply acquires its own hold, validates the pending journal's paths and
recovers it before checking for a replacement frontend build.

**Frozen D/P helper ABI (2026-10-17).** Source the reviewed helper; it changes
neither shell options nor caller traps. It requires Bash, coreutils/flock,
Python 3 for managed-block parsing, and Docker Compose/jq for resolved models.

```bash
handle=$(edge_lock_acquire "$APP_ROOT/activation.journal.lock" "$wait_seconds" "$hold_max_seconds" "$owner_pid_or_0")
edge_lock_check "$handle" "$remaining_operation_budget"
edge_effective_caddyfile "$repository_base" "$live_caddyfile" # stdout only
edge_compose_args "$base_compose" "$installed_portal_overlay" # EDGE_COMPOSE_ARGV array
edge_required_networks "$base_compose" "$installed_portal_overlay" # stdout: actual names
# Caller checks ownership before each mutation, including recovery/back-out.
edge_lock_release "$handle" "$cleanup_deadline"
```

The last two acquire arguments, the check budget and the release deadline are
optional. Capture the handle explicitly; the acquire is not an in-shell lock
side effect. Owner 0 permits separate remote calls to use the same handle. Keep
the persistent lock inode; do not delete or replace it. D ships the helper and
owns recognition callsites and back-out separately.

**Effective Compose generation.** The marked repository Caddy Compose base
opts into generation selection. The helper resolves the base plus the installed
portal overlay using the real `docker compose config --format json` producer,
then reads `docker network ls`. Only absent staging/prod Aura memberships are
omitted. Generic, FIR and dev Aura memberships stay external and unchanged;
no stores or networks are started or created. An unreadable inventory refuses.
The resulting private JSON model preserves resolved network names, bind paths,
volumes and project identity. Every Compose operation must use
`"${EDGE_COMPOSE_ARGV[@]}"`; raw base-only `up` still requires every listed
network. The array may select a generated model rather than the original file
pair. Selection remains stable in that shell until base/overlay bytes change.
Call `edge_compose_cleanup` after the last use to remove that shell's private
model; it changes no traps. App-portal does this on owned exit. Independent D
callers can use the frozen functions without changing their signatures.

The managed-block parser handles Unicode whitespace, schemes, ports, multiple
addresses, quotes and token-initial comments. It counts structural brace tokens,
not braces inside comments or strings, and refuses imports, environment
expansions, unquoted escapes/heredocs and other syntax whose ownership it cannot prove.
Accepted managed-block bytes, including an END marker without a newline, are
preserved. Caddy validation remains required before publication. The lexical
reference is the [Caddy v2 lexer](https://github.com/caddyserver/caddy/blob/v2.10.2/caddyconfig/caddyfile/lexer.go).

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

### Recover an interrupted frontend activation

A retained `/opt/acx-backend/app/activation.journal` blocks manual back-out.
Recovery must use the same reviewed deploy script and input paths as the
interrupted apply. If those files exist only on the operator workstation, copy
these four reviewed files from that release to the VM first (the `acx-backend`
SSH alias is the same existing VM used for deployment; no VM checkout is assumed):

```bash
scp scripts/deploy/app-portal.sh acx-backend:/tmp/app-portal-recovery.sh
scp scripts/deploy/lib/shared-edge.sh acx-backend:/tmp/app-portal-recovery.shared-edge.sh
scp infra/oci/app/Caddyfile.app acx-backend:/tmp/app-portal-recovery.Caddyfile.app
scp infra/oci/app/docker-compose.app.yml acx-backend:/tmp/app-portal-recovery.overlay.yml
```

The standalone script needs the shared-edge helper. It is not found beside
`/tmp/app-portal-recovery.sh`, so the recovery invocation names it with
`APP_SHARED_EDGE_LIB`. Recovery refuses if that file is missing or is a symlink.

In an operator shell on the VM, with the same filesystem and Docker permissions
as the original apply, run this exact recovery invocation. These are the default
apply bindings; substitute the original values if they were overridden, including
`APP_ROOT`, `APP_WWW`, `CADDYFILE`, `CADDY_COMPOSE`, `APP_UPSTREAM`, and the overlay
template. The installed live overlay remains `${APP_ROOT}/docker-compose.app.yml`.
`env -u FRONTEND_DIST` also removes a build path inherited from the operator shell:

```bash
env -u FRONTEND_DIST \
  APP_ROOT=/opt/acx-backend/app \
  APP_WWW=/opt/acx-backend/app/www \
  CADDYFILE=/opt/acx-backend/Caddyfile \
  CADDY_COMPOSE=/opt/acx-backend/docker-compose.caddy.yml \
  APP_UPSTREAM=prod-api:8000 \
  APP_SNIPPET=/tmp/app-portal-recovery.Caddyfile.app \
  APP_OVERLAY=/tmp/app-portal-recovery.overlay.yml \
  APP_SHARED_EDGE_LIB=/tmp/app-portal-recovery.shared-edge.sh \
  APP_HEALTH_CMD=/usr/local/bin/app-portal-health-check \
  bash /tmp/app-portal-recovery.sh --apply
```

The script acquires its bounded deployment lock, validates the Compose Caddyfile
bindings (base, installed overlay, and rendered template), and recovers the
journal **before** requiring a replacement build. Recovery restores/reloads live
state for `prepared`, `caddy_promoted`, `www_promoted`, or `overlay_promoted`.
For `snapshotting`, no live promotion has occurred: recovery removes only that
journal's planned partial snapshot/marker set without restoring live files.
For `restored`, restoration/reload is already durable and recovery retries only
failed-set cleanup. Cleanup is synced while the journal remains present and the
journal is cleared last; earlier successful rollback sets are preserved.

After successful recovery the command deliberately exits nonzero with
`ERROR: FRONTEND_DIST is required for --apply`, before staging or redeploying.
Do not blindly ignore a nonzero status: any other error is a STOP. Confirm the
output reports recovery followed by that exact missing-build refusal; check that
`activation.journal` is gone (neither an existing path nor a dangling symlink),
inspect the restored Caddyfile, frontend/absence, and overlay/absence against the
pre-activation state, and verify Caddy/API readiness and restored frontend
behavior as applicable. If the journal remains or restoration is unverified,
STOP and resolve recovery first. Only then run manual back-out below to restore
the last successful apply's prestate. Supplying `FRONTEND_DIST` would instead
recover and then redeploy, so it must remain unset for this recovery step.

### Frontend back-out

`/opt/acx-backend/app/rollback/Caddyfile.<ts>` plus `www.<ts>` and
`docker-compose.app.yml.<ts>` are the pre-activation copies. For each previously
missing artifact, a validated `absent-www.<ts>` or `absent-overlay.<ts>` replaces
its snapshot. Missing snapshots alone never prove prior absence. Automatic restore
runs on promote/compose/reload/health failure and reapplies the restored compose
state before the rollback reload. Successful failed-apply restore removes only
its duplicate timestamp set while the durable journal is at `phase=restored`,
syncs that cleanup, then clears the journal last, preserving the last successful
apply's prestate set. Thus a failed re-apply does not replace the
manual back-out target with copies of the still-live successful frontend.
Failed restore retains the journal and all snapshot/absence-marker inputs for
retry; use [interrupted activation recovery](#recover-an-interrupted-frontend-activation)
before attempting manual back-out. The manual block holds the same bounded
`activation.journal.lock` as deploy and refuses any retained journal, including a
dangling symlink, before selecting snapshots or mutating live/rollback state.
Candidate Compose resolution and network selection finish before any journal,
rollback-set, or live write. A pure preflight refusal needs no recovery.
After admission, the block publishes a durable version-2 journal and a separate
copy of the selected target set before the first live write. The original
successful sets remain intact. If snapshot copying fails, the native
`snapshotting` recovery cleans only the partial copy; rerun manual back-out.
If any live write, recreation, readiness probe, or reload fails, leave the
journal in place and use the exact interrupted activation recovery invocation
above with `FRONTEND_DIST` unset. Its native recovery finishes restoring this
back-out target and removes only the duplicate set; the expected missing-build
refusal then proves no replacement apply started. Verify the restored state
before retrying manual back-out. Do not delete or bypass the journal.
Overlay replacement is staged, synced, and renamed in the same directory, so an
interrupted copy cannot leave malformed live YAML blocking native recovery.
Its temporary file uses the native journal cleanup prefix.
On the VM, manual restore selects only
`Caddyfile.<digits>` names and sorts by the numeric filename suffix, never mtime
(`cp -a` preserves the live file's older mtime). It prints the chosen timestamp
and refuses missing, empty, incomplete, or contradictory marker/snapshot sets
before changing live files. Markers must be regular files without symlinks and
match the exact versioned contents written by deployment, including the newline.
The snapshot's `index.html` must be a non-empty regular file, not a symlink.
The live overlay must be a regular file or absent, never a symlink; its parent
must be an existing directory, not a symlink, even when the overlay is absent.
The commands below use the default paths; substitute the same paths used at
apply if they were overridden. Successful apply packages its reviewed helper at
`${APP_ROOT}/shared-edge.sh`. For an older apply without that package, copy the
four reviewed recovery artifacts above and set
`APP_SHARED_EDGE_LIB=/tmp/app-portal-recovery.shared-edge.sh` in this shell.
Both manual back-out and fix-forward refuse a missing or symlinked helper. Restore the Caddyfile back **in place**,
preserving its bind-mounted inode, and www/overlay from that same timestamp.
The executable branches below restore each snapshot or remove the newly added
artifact only when its absence marker is validated. They support a full snapshot,
first deployment with both artifacts absent, and either mixed prior state:

```bash
(
  set -euo pipefail
  umask 077
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
  # Same lock inode and bounded wait as app-portal.sh; never truncate the lock.
  lock=/opt/acx-backend/app/activation.journal.lock
  if [ -L "$lock" ] || { [ -e "$lock" ] && [ ! -f "$lock" ]; }; then
    echo 'STOP: deployment lock path unsafe; refusing restore' >&2
    exit 1
  fi
  lock_wait="${APP_DEPLOY_LOCK_WAIT:-30}"
  case "$lock_wait" in
    ''|*[!0-9]*) echo 'STOP: APP_DEPLOY_LOCK_WAIT must be a non-negative integer' >&2; exit 1 ;;
  esac
  if ! command -v flock >/dev/null 2>&1; then
    echo 'STOP: flock required for deployment lock; refusing restore' >&2
    exit 1
  fi
  if ! exec 9>>"$lock"; then
    echo 'STOP: cannot open deployment lock; refusing restore' >&2
    exit 1
  fi
  if ! flock -w "$lock_wait" 9; then
    echo "STOP: cannot acquire deployment lock within ${lock_wait}s; refusing restore" >&2
    exit 1
  fi
  if [ -e /opt/acx-backend/app/activation.journal ] || [ -L /opt/acx-backend/app/activation.journal ]; then
    echo 'STOP: activation journal present; recover interrupted activation before manual back-out' >&2
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
  helper="${APP_SHARED_EDGE_LIB:-/opt/acx-backend/app/shared-edge.sh}"
  if [ ! -f "$helper" ] || [ -L "$helper" ]; then
    echo 'STOP: reviewed shared-edge helper missing or unsafe; refusing restore' >&2
    exit 1
  fi
  source "$helper"
  trap 'edge_compose_cleanup' EXIT
  # Admit the rollback inputs, never the current live overlay. Keep this
  # generation (or the unchanged legacy snapshot argv) through the last reload.
  cd /opt/acx-backend
  edge_compose_args docker-compose.caddy.yml "$overlay_snapshot"
  compose=(docker compose "${EDGE_COMPOSE_ARGV[@]}")
  candidate_bind="$(edge_bounded_run "${compose[@]}" config --format json 9>&- | \
    jq -er '[.services.caddy.volumes[]? | select(.target == "/etc/caddy/Caddyfile")] |
      if length == 1 and .[0].type == "bind" then .[0].source | select(type == "string")
      else error("expected one Caddyfile bind mount") end')"
  if [ "$candidate_bind" != /opt/acx-backend/Caddyfile ]; then
    echo 'STOP: candidate Caddyfile bind source differs from live path; refusing restore' >&2
    exit 1
  fi

  # The actual app-portal.sh v2 recovery reader consumes this separate target
  # set. Never point it at the original successful set: recovery deletes its
  # own set after reload. Intent precedes even partial snapshot copies.
  rollback=/opt/acx-backend/app/rollback
  journal=/opt/acx-backend/app/activation.journal
  resume_ts="$(date +%s)"
  while :; do
    collision=0
    for prefix in Caddyfile www docker-compose.app.yml absent-www absent-overlay; do
      if [ -e "$rollback/$prefix.$resume_ts" ] || [ -L "$rollback/$prefix.$resume_ts" ]; then
        collision=1
      fi
    done
    [ "$collision" -eq 1 ] || break
    resume_ts=$((resume_ts + 1))
  done
  resume_caddy="$rollback/Caddyfile.$resume_ts"
  resume_www="$rollback/www.$resume_ts"
  resume_overlay="$rollback/docker-compose.app.yml.$resume_ts"
  journal_tmp="$(mktemp "$journal.new.XXXXXXXX")"
  overlay_stage=""
  trap 'edge_compose_cleanup; rm -f -- "$journal_tmp"; if [ -n "$overlay_stage" ]; then rm -f -- "$overlay_stage"; fi' EXIT
  backout_journal() {
    printf 'version=2\nphase=%s\ncaddyfile=%s\napp_www=%s\noverlay=%s\ncaddy_compose=%s\nrollback_caddy=%s\nrollback_www=%s\nrollback_overlay=%s\n' \
      "$1" /opt/acx-backend/Caddyfile /opt/acx-backend/app/www \
      /opt/acx-backend/app/docker-compose.app.yml /opt/acx-backend/docker-compose.caddy.yml \
      "$resume_caddy" "$resume_www" "$resume_overlay" >"$journal_tmp"
    edge_bounded_run sync "$journal_tmp"
    edge_bounded_run mv -f -- "$journal_tmp" "$journal"
    edge_bounded_run sync /opt/acx-backend/app
  }
  backout_journal snapshotting
  cp -a -- "$snapshot" "$resume_caddy"
  if [ "$restore_www" -eq 1 ]; then
    cp -a -- "$www_snapshot" "$resume_www"
  else
    cp -- "$www_absent" "$rollback/absent-www.$resume_ts"
    resume_www=-
  fi
  if [ "$restore_overlay" -eq 1 ]; then
    cp -a -- "$overlay_snapshot" "$resume_overlay"
  else
    cp -- "$overlay_absent" "$rollback/absent-overlay.$resume_ts"
    resume_overlay=-
  fi
  # Flush snapshot data and directory entries before publishing prepared.
  edge_bounded_run sync -f "$rollback"
  backout_journal prepared
  cp -- "$snapshot" /opt/acx-backend/Caddyfile
  edge_bounded_run sync /opt/acx-backend/Caddyfile
  backout_journal caddy_promoted
  rm -rf -- /opt/acx-backend/app/www
  if [ "$restore_www" -eq 1 ]; then
    cp -a -- "$www_snapshot" /opt/acx-backend/app/www
  fi
  edge_bounded_run sync -f /opt/acx-backend/app
  backout_journal www_promoted
  if [ "$restore_overlay" -eq 1 ]; then
    # Native recovery validates the installed overlay before restoration. A
    # partial copy must never put malformed YAML on that admission path.
    overlay_stage="$(mktemp "$journal.new.overlay.XXXXXXXX")"
    cp -- "$overlay_snapshot" "$overlay_stage"
    edge_bounded_run sync "$overlay_stage"
    edge_bounded_run mv -f -- "$overlay_stage" /opt/acx-backend/app/docker-compose.app.yml
    overlay_stage=""
  else
    rm -f -- /opt/acx-backend/app/docker-compose.app.yml
  fi
  edge_bounded_run sync -f /opt/acx-backend/app
  backout_journal overlay_promoted
  edge_bounded_run "${compose[@]}" up -d --force-recreate --no-deps caddy 9>&-
  ready=0
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if edge_bounded_run "${compose[@]}" exec -T caddy wget -q -T 1 -O /dev/null \
      http://127.0.0.1:2019/config/ 9>&-; then
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
  edge_bounded_run "${compose[@]}" exec -T caddy \
    caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile 9>&-
  # Durable completion precedes cleanup; the native restored phase can retry
  # a partial cleanup without reading already removed target copies.
  backout_journal restored
  for prefix in Caddyfile www docker-compose.app.yml absent-www absent-overlay; do
    rm -rf -- "$rollback/$prefix.$resume_ts"
  done
  edge_bounded_run sync "$rollback"
  rm -f -- "$journal"
  edge_bounded_run sync /opt/acx-backend/app
)
```

The block reapplies the prior compose overlay and reloads Caddy only after every
guard, the full restore, and bounded admin readiness polling succeed. The
candidate snapshot overlay participates in one selected generation used for
recreation, probing, and reload, including a legacy overlay's `name:` project.
Snapshot input paths remain available after live overlay restoration. A marked
base uses its private resolved generation; missing staging/prod Aura networks
never cause sibling stacks or networks to be created. The block attempts the
container-local admin probe up to ten times with a one-second request timeout
and at most nine one-second pauses. Exhaustion prints STOP and retains the
journal and target copies without reloading. A successful reload durably records
`restored`, syncs duplicate-set cleanup, then clears the journal last. Any
interruption during that cleanup resumes through the native `restored` phase.

If there was no prior overlay (first deployment), automatic rollback uses its
activation journal's recorded absence. Manual rollback uses the durable validated
absence markers even after a successful apply has cleared that journal. With both
markers it removes the newly installed overlay and frontend directory after all
guards pass, restores the Caddyfile in place, and uses the base compose file alone
as input to the helper for recreation, the same bounded readiness probe, and
reload in the block above. Optional network selection still applies.

Failed validation never replaces the live files, so rollback is only needed
after activation has started.

## Out of scope

- Live deploy from this sandbox, production remote-shell from the worker
- Clerk Dashboard changes, billing-provider catalog setup, or new OCI VM
- Recognition deploy callsites and live publication; P only supplies the helper ABI and Compose generation contract
