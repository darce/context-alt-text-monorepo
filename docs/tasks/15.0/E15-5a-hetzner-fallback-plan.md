# E15-5a Hetzner CX22 Fallback Plan

> **Status**: see `DASHBOARD.txt` and `review_findings(operation="list", task_ref="E15-5A")` (MCP is the source of truth; planning-review fix commit `1a66402e` recorded in [the run log](./E15-5a-oci-hygiene-run-log.md#planning-review-outcome)).
> **Parent**: [E15-5a OCI Operational Hygiene](./E15-5a-oci-operational-hygiene-task-plan.md) Slice 3
> **Scope**: planning artifact only. This plan does not execute the migration; it documents the migration so an operator can execute it under pressure.
> **Living-doc rule**: re-verify this plan whenever `apps/prototype-description-service/.env.prod.example`, `apps/prototype-description-service/docker-compose.env.yml`, or `apps/prototype-description-service/Caddyfile` change materially.

---

## Trigger Conditions

Execute this fallback when **any one** of the following holds:

1. **Two consecutive OCI capacity failures on reboot** -- the Always Free A1.Flex instance fails to come back up after a stop/start cycle and `retry-apply.sh` shows `Out of host capacity` across all three Ashburn ADs for >2h. Capacity failures during normal `terraform apply` provisioning (i.e. not affecting a running instance) do *not* trigger fallback.
2. **A 24h backend outage** with root cause confined to OCI infrastructure (host network, region-wide event, security incident requiring instance destruction).
3. **A documented OCI billing event** that pushes the project off Always Free (e.g. the A1.Flex tier is revoked or the project exceeds Always Free entitlements) where the projected steady-state monthly cost on OCI exceeds the CX22 monthly cost by >2x.
4. **A demo-blocking ARM compatibility regression** discovered in the image stack that cannot be patched within the same business day.

Trigger conditions are evaluated by the operator; there is no automation that flips the switch. Cross-reference the `$10` budget alert from [Slice 1](./E15-5a-oci-operational-hygiene-task-plan.md#slice-1----oci-budget-alerts) as the cost-side signal.

---

## Migration Scope

This plan migrates the **prod** environment only. Staging and dev remain on OCI until prod is stable on Hetzner; they migrate later under a separate task if Hetzner becomes the new permanent home.

| Component                | OCI today                                       | Hetzner target                                              |
|--------------------------|--------------------------------------------------|--------------------------------------------------------------|
| Compute                  | A1.Flex (arm64, Always Free)                     | CX22 (x86, ~EUR 4.51/mo at time of writing)                  |
| OS                       | Ubuntu 22.04 LTS                                 | Ubuntu 22.04 LTS                                             |
| Container runtime        | Docker + compose (per-env units via systemd)     | Identical -- reuse [docker-compose.env.yml](../../../apps/prototype-description-service/docker-compose.env.yml) |
| Reverse proxy            | Caddy 2 ([Caddyfile](../../../apps/prototype-description-service/Caddyfile)) -- **not** in `docker-compose.env.yml`; runs as a separate container attached to `${ACX_NETWORK_NAME}` (`acx-prod-net`) so it can reach the `prod-api` service alias | Same Caddy, same Caddyfile (Let's Encrypt re-issues on first request); Caddy must join `acx-prod-net` to route to `prod-api:8000` |
| Container registry       | `iad.ocir.io/idu2kqqe2jxy/acx-backend`           | Same (pull works cross-cloud; auth token portable)            |
| Image architecture       | `linux/arm64` built natively on the A1.Flex VM   | **`linux/amd64`** -- requires rebuild via `docker buildx`     |
| Persistent state         | `/opt/acx-backend/data/prod-pgdata` (Postgres)   | Same path layout on CX22 local disk                          |
| Unified cache mount      | `/opt/acx-backend/data/prod-models` mounted to `/data/cache` in api+worker (HuggingFace, InsightFace, transformers, matplotlib caches all live under this single host directory per `ACX_MODELS_PATH`) | Re-populated on first container start (not migrated)         |
| Object/blob state        | `acx_blobs` named volume                          | Migrated via `docker volume` export/import or `rsync`        |
| DNS                      | `api.altcontext.com` A record -> OCI public IP   | Same A record -> Hetzner public IP                           |

**Out of scope for first migration**: staging + dev envs, OCIR migration (the registry stays on OCI; only the compute moves).

---

## Sizing Analysis (CX22 Baseline)

### Baseline Hypothesis

The CX22 (2 vCPU, 4 GB RAM, 40 GB disk, 20 TB traffic at time of writing) is the smallest Hetzner CX shape that can sustain the current prod stack (api + worker + postgres + caddy). Hypothesis is grounded in the per-process memory footprint observed locally; the live OCI sample below is what validates or rejects it.

### Required Sampling Evidence (operator captures into the run log)

Capture a representative 15-minute window during typical operator usage (workbench browsing + at least one scan job) and record in [E15-5a-oci-hygiene-run-log.md](./E15-5a-oci-hygiene-run-log.md#memory-sampling-evidence-capture):

```bash
# REPLACE before running: <tailnet> -> your tailnet name (e.g. tail1a44b8); confirm with `tailscale status`.
# From the workstation, over the tailnet:
ssh ubuntu@acx-backend.<tailnet>.ts.net '
  echo "=== free -m ===" && free -m
  echo "=== docker stats snapshot ===" && \
    sudo docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}"
  echo "=== top per-process ===" && top -bn1 -o %MEM | head -25
'
```

Run the snapshot every minute for 15 minutes (`for i in $(seq 1 15); do <cmd>; sleep 60; done`) and tee to a file. Peak combined RSS across `acx-prod-api-1`, `acx-prod-worker-1`, and `acx-prod-postgres-1` is the load-bearing number.

### Escalation Rules

Escalate from CX22 to **CX32** (4 vCPU, 8 GB RAM, ~EUR 8.21/mo) if **any** of the following are true after the 15-minute sample:

1. Peak combined RSS (api + worker + postgres) >= **3 GB** during the sample window. CX22 has 4 GB total; leaving <1 GB for OS + caddy + headroom is unsafe for a live demo.
2. Peak CPU sustained at 100% on both vCPUs for >2 consecutive minutes during a scan job. CX32 doubles vCPU count and is the next safe step.
3. The amd64 parity check (below) requires a runtime workaround (e.g. larger buildx cache, additional system packages) that pushes memory usage above the threshold.

Escalation beyond CX32 (to CX42/CX52) is not contemplated by this plan; if the workload requires it, this fallback has lost its "drop-in equivalent" property and a fresh sizing pass is required.

### amd64 Parity Check (definition)

The parity check is the gating decision between "rebuild on x86 and ship" and "block on architecture-specific fix". It runs once, locally or on a throwaway CX22, before DNS cutover.

> Run the build from `apps/prototype-description-service/` (where the `Dockerfile` lives) so the build context resolves correctly.

| Step | Pass criterion |
|------|----------------|
| `cd apps/prototype-description-service && docker buildx build --platform linux/amd64 --build-arg GIT_COMMIT_SHA=$(git rev-parse HEAD) -t iad.ocir.io/idu2kqqe2jxy/acx-backend:fallback-amd64 --push .` | Build completes with exit 0 and the image is pushed to OCIR; no architecture-specific patches required to `Dockerfile`, `pyproject.toml`, or system package list. `--push` is required so the Hetzner host can `docker pull` it during Migration Steps below. |
| `docker compose -f docker-compose.env.yml up -d` against the rebuilt image on the x86 host (override `ACX_IMAGE_TAG=fallback-amd64` for the parity boot) | The 3 services in `docker-compose.env.yml` (postgres, api, worker) boot; only `postgres` declares a compose `healthcheck` (it reaches `healthy` within ~60s, which gates api/worker startup via `depends_on: service_healthy`). api/worker have no compose healthcheck, so do not gate api readiness on compose `healthy` status — gate it on the `/health` + `/ready` endpoint smoke rows below (~120s for api). Caddy is not in this compose; it comes from the separate `docker-compose.caddy.yml`. |
| `curl https://<test-host>/health` and `/recognition/health` | Returns the same JSON shape and the `commit_sha` field matches `GIT_COMMIT_SHA` build-arg passed above. |
| `curl https://<test-host>/ready` | Returns 200 with `{status, checks: [...], timestamp}` where top-level `status` is `ok`/`degraded` (unhealthy flips to 503) and the `checks[]` array carries `database`, `breaker`, and `model_cache` entries (each `{name, status, detail}` with `status` one of `ok`/`degraded`/`unhealthy`). There are no top-level `database`/`models` keys. The InsightFace cache must download cleanly on amd64 so the `model_cache` check reports `ok`. |

Any failure on these steps **forces** either CX32 review or an explicit architecture-fix follow-up task before DNS cutover.

### Image Promotion

The parity-check build above pushes `:fallback-amd64`. The Hetzner production stack pulls `:latest` (per `ACX_IMAGE_TAG=latest` in the migrated env file). Promote the verified amd64 image to `:latest` before cutover so Hetzner's `docker compose pull` resolves to the verified artifact, not the stale arm64 `:latest`:

```bash
# REPLACE before running: <operator-email> -> the OCI user that owns the OCIR auth token.
docker login iad.ocir.io -u "idu2kqqe2jxy/<operator-email>"

# Tag the verified amd64 image as :latest and push.
docker buildx imagetools create \
  -t iad.ocir.io/idu2kqqe2jxy/acx-backend:latest \
  iad.ocir.io/idu2kqqe2jxy/acx-backend:fallback-amd64
```

`buildx imagetools create` re-points the registry tag without re-uploading layers and works on the existing single-arch amd64 manifest (no local pull required). Confirm the promotion landed:

```bash
docker buildx imagetools inspect iad.ocir.io/idu2kqqe2jxy/acx-backend:latest \
  | grep -E "Platform|MediaType" | head
# Expect: Platform: linux/amd64
```

Note: the OCI host's `:latest` (arm64) is no longer accessible from Hetzner once `:latest` is re-pointed at amd64. Rollback to OCI (per the Rollback section) is unaffected because the OCI host already holds the running arm64 container; it does not re-pull on rollback.

---

## Postgres Data Migration

### Backup Baseline

The operator verifies whether a daily `pg_dump` cron is currently running on the OCI VM and records the result in [the run log § Postgres Backup Baseline Check](./E15-5a-oci-hygiene-run-log.md#postgres-backup-baseline-check).

**Lookup sequence** (run in order; first hit wins; record the outcome from each step):

```bash
# REPLACE before running: <tailnet> -> your tailnet name.
ssh ubuntu@acx-backend.<tailnet>.ts.net '
  echo "=== crontab (root) ===" && sudo crontab -l 2>/dev/null | grep -i "pg_dump\|postgres\|backup" || echo "(no matching root crontab entry)"
  echo "=== crontab (ubuntu) ===" && crontab -l 2>/dev/null | grep -i "pg_dump\|postgres\|backup" || echo "(no matching user crontab entry)"
  echo "=== /etc/cron.d ===" && sudo grep -RIl "pg_dump\|postgres\|backup" /etc/cron.d /etc/cron.daily /etc/cron.hourly 2>/dev/null || echo "(no matching files)"
  echo "=== systemd timers ===" && systemctl list-timers --all 2>/dev/null | grep -i "pg\|postgres\|backup" || echo "(no matching timers)"
  echo "=== docker backup sidecar ===" && sudo docker ps -a --format "table {{.Names}}\t{{.Image}}" | grep -i "backup\|dump\|barman\|pgbackrest" || echo "(no backup container)"
  echo "=== local dump artifacts ===" && sudo ls -lah /var/backups/postgres /opt/acx-backend/backups 2>/dev/null || echo "(no standard backup dirs)"
'
```

- If **any step shows a recurring `pg_dump` schedule**, record the schedule + output path in the run log. The fallback uses the most recent nightly dump as the migration starting point and runs a fresh `pg_dump` immediately before cutover to capture the final delta.
- If **all steps show no backup mechanism**, the fallback requires a one-off `pg_dump` as a prerequisite step and opens a separate follow-up to automate ongoing backups. The follow-up is not in scope for this plan; capture the follow-up task ref in the run log.

### Migration Steps

> **Fresh-PGDATA restore ordering.** `docker-compose.env.yml` mounts `./db/docker-prod-init` into the postgres container's `/docker-entrypoint-initdb.d` (read-only), and Postgres runs those scripts **only once, on an empty PGDATA**. The Hetzner `docker compose up -d postgres` below (step 4) initializes a fresh PGDATA, so `001-extensions.sql` runs first and creates the `vector`/`uuid-ossp`/`citext`/`pgcrypto` extensions **before** the `pg_restore` lands the dump -- the ordering is correct and the dumped schema's `vector` columns restore cleanly. This only holds if `db/docker-prod-init/` is actually present on the Hetzner host next to the compose file: `deploy-env.sh` ships it (`scp -r .../db/docker-prod-init -> /opt/acx-backend/<env>/db/`), but the manual bring-up in step 4 does not. If you bring postgres up manually without that directory, the fresh init creates no extensions and `pg_restore` fails on the first `vector`-typed column -- `scp` `apps/prototype-description-service/db/docker-prod-init` to `/opt/acx-backend/prod/db/` before step 4.

```bash
# REPLACE before running: <tailnet> -> your tailnet name; <hetzner-ip> -> Hetzner public IP.
# 1. On OCI VM: capture final dump just before cutover.
#    The container path /var/lib/postgresql/data is bind-mounted from the host
#    path ${ACX_PGDATA_PATH} = /opt/acx-backend/data/prod-pgdata (see
#    apps/prototype-description-service/docker-compose.env.yml). pg_dump writes
#    INSIDE the container; ls/scp on the host MUST use the host path.
ssh ubuntu@acx-backend.<tailnet>.ts.net '
  sudo docker exec acx-prod-postgres-1 \
    pg_dump -U acx_app -d alt_context_service -Fc \
    --file=/var/lib/postgresql/data/prod-cutover-$(date -u +%Y%m%dT%H%M%SZ).dump
  sudo ls -lh /opt/acx-backend/data/prod-pgdata/prod-cutover-*.dump
'

# 2. Workstation: pull the dump (host path on the OCI VM, not the container path).
scp ubuntu@acx-backend.<tailnet>.ts.net:/opt/acx-backend/data/prod-pgdata/prod-cutover-*.dump \
    ./prod-cutover.dump

# 3. Workstation: ship to Hetzner.
scp ./prod-cutover.dump root@<hetzner-ip>:/opt/acx-backend/data/prod-cutover.dump

# 4. On Hetzner: stop api+worker to prevent writes during restore.
ssh root@<hetzner-ip> '
  sudo systemctl stop acx-prod
  cd /opt/acx-backend/prod
  sudo docker compose -f docker-compose.env.yml up -d postgres
  # Wait for postgres healthy:
  until sudo docker exec acx-prod-postgres-1 pg_isready -U acx_app; do sleep 2; done

  # Restore.
  sudo docker exec -i acx-prod-postgres-1 \
    pg_restore -U acx_app -d alt_context_service --clean --if-exists \
    < /opt/acx-backend/data/prod-cutover.dump

  # Restart the full stack.
  sudo systemctl start acx-prod
'

# 5. Verify row counts match between OCI and Hetzner before flipping DNS.
ssh ubuntu@acx-backend.<tailnet>.ts.net 'sudo docker exec acx-prod-postgres-1 psql -U acx_app -d alt_context_service -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname;"' > /tmp/oci-counts.txt
ssh root@<hetzner-ip> 'sudo docker exec acx-prod-postgres-1 psql -U acx_app -d alt_context_service -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname;"' > /tmp/hetzner-counts.txt
diff /tmp/oci-counts.txt /tmp/hetzner-counts.txt
```

### Blob Volume

The `acx_blobs` named volume holds recognition blobs that are not in Postgres. Migrate via:

```bash
# REPLACE before running: <tailnet> -> your tailnet name; <hetzner-ip> -> Hetzner public IP.
# On OCI VM:
ssh ubuntu@acx-backend.<tailnet>.ts.net '
  sudo docker run --rm -v acx-prod_acx_blobs:/from -v /tmp:/to alpine \
    sh -c "cd /from && tar czf /to/acx_blobs.tar.gz ."
'
scp ubuntu@acx-backend.<tailnet>.ts.net:/tmp/acx_blobs.tar.gz ./acx_blobs.tar.gz
scp ./acx_blobs.tar.gz root@<hetzner-ip>:/tmp/

# On Hetzner (after `docker compose up postgres` has implicitly created the named volume):
ssh root@<hetzner-ip> '
  sudo docker run --rm -v acx-prod_acx_blobs:/to -v /tmp:/from alpine \
    sh -c "cd /to && tar xzf /from/acx_blobs.tar.gz"
'
```

The unified cache mount (`prod-models` -> `/data/cache`, which holds HuggingFace, InsightFace, transformers, and matplotlib caches per `apps/prototype-description-service/.env.prod.example`) is NOT migrated -- it re-downloads from Hugging Face / InsightFace on first container start. Add ~5 min to the cutover timing for the warm-up.

### Post-Cutover Backup Continuity

Migrating Postgres data once does not re-establish the standing backup mechanism on Hetzner. Cutover MUST NOT complete without one of the following:

1. **Mirror the OCI cron on Hetzner** (preferred when the OCI baseline check found a working schedule). Reuse the same pg_dump invocation from the OCI VM (output path `/var/backups/postgres/<env>-<date>.dump`) and install it as a root crontab entry on the Hetzner host. Validate the next scheduled run produces a dump before declaring cutover stable.
2. **Provision a one-off cron during cutover** (when the OCI baseline check found no schedule). Add a daily `@daily root sudo docker exec acx-prod-postgres-1 pg_dump -U acx_app -d alt_context_service -Fc --file=/var/lib/postgresql/data/auto-$(date -u +%%Y%%m%%dT%%H%%M%%SZ).dump` entry on the Hetzner host as part of the cutover, and open the same automation follow-up task referenced in the Backup Baseline section above. Note: cron requires `%` to be doubled to `%%` inside crontab entries.

Off-host retention (Hetzner Storage Box, S3-compatible, or operator workstation pull) is out of scope for this plan but should be tracked in the same follow-up. Cutover is not "complete" until the next scheduled dump produces a fresh artifact on Hetzner.

---

## Env, Secrets, and Config Migration

### Files to Copy Verbatim

The full surface lives in [`apps/prototype-description-service/.env.prod.example`](../../../apps/prototype-description-service/.env.prod.example). The actual prod values live in `/opt/acx-backend/prod/secrets/.env` on the OCI VM. Migrate as a unit:

```bash
# REPLACE before running: <tailnet> -> your tailnet name; <hetzner-ip> -> Hetzner public IP.
ssh ubuntu@acx-backend.<tailnet>.ts.net 'sudo cat /opt/acx-backend/prod/secrets/.env' > prod.env.tmp
# Move to Hetzner via password manager or short-lived scp; do NOT commit.
scp prod.env.tmp root@<hetzner-ip>:/opt/acx-backend/prod/secrets/.env
ssh root@<hetzner-ip> '
  sudo chown root:root /opt/acx-backend/prod/secrets/.env
  sudo chmod 600 /opt/acx-backend/prod/secrets/.env
  sudo ln -sf /opt/acx-backend/prod/secrets/.env /opt/acx-backend/prod/.env
'
shred -u prod.env.tmp
```

### Per-Variable Migration Notes

| Variable                          | Migration action |
|-----------------------------------|------------------|
| `COMPOSE_PROJECT_NAME=acx-prod`   | Unchanged.       |
| `ACX_ENV=prod`                    | Unchanged.       |
| `RECOGNITION_RUNTIME_MODE=production` | **Required, unchanged.** `api/main.py` refuses to start if `RECOGNITION_RUNTIME_MODE=production` **and** `RECOGNITION_ALLOWED_API_KEYS` is non-empty (the dev-keys-in-prod guard). Verify the value survived the `.env` copy and that `RECOGNITION_ALLOWED_API_KEYS` is empty before `docker compose up`; provision real keys via `apps/prototype-description-service/scripts/manage_api_keys.py` post-boot. |
| `ACX_IMAGE_TAG=latest`            | Unchanged once the amd64 `:latest` is pushed (see [§ Image Promotion](#image-promotion) above).      |
| `ACX_PGDATA_PATH=/opt/acx-backend/data/prod-pgdata` | Same path; ensure directory exists on Hetzner before `docker compose up`. |
| `ACX_MODELS_PATH=/opt/acx-backend/data/prod-models` | Same path; ensure directory exists; cache repopulates on first run. |
| `ACX_NETWORK_NAME=acx-prod-net`   | Unchanged.       |
| `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` | Unchanged; the `pg_restore` above expects these to match. |
| `POSTGRES_DSN`/`POSTGRES_SYNC_DSN`| Unchanged (container-internal `postgres:5432`). |
| `RECOGNITION_AUTH_ENABLED=true`   | Unchanged.       |
| `RECOGNITION_ALLOWED_API_KEYS`    | MUST remain empty (the prod startup guard refuses to boot otherwise). **WordPress plugin auth continuity is preserved by the Postgres dump**: real API keys live in the `api_keys` table and migrate via `pg_restore` above. No key rotation is required during cutover. Run `apps/prototype-description-service/scripts/manage_api_keys.py list` post-boot only to confirm the expected keys are present; rotate via `apps/prototype-description-service/scripts/manage_api_keys.py revoke`/`create` only if a leak is suspected. |
| `RECOGNITION_ALLOWED_ORIGINS`     | Unchanged (commented out in `.env.prod.example`; uncomment + set only if the WP host is on a different origin from the API).       |
| `TENANT_ID`                       | Unchanged (single-tenant prod). |
| Cache dirs (`CACHE_BASE`, `HF_HOME`, etc.) | Unchanged (container-internal). |

### Caddyfile

`apps/prototype-description-service/Caddyfile` is identical on both hosts; the only deploy artifact needed at `/opt/acx-backend/Caddyfile`. Let's Encrypt re-issues the cert on first request once DNS points at Hetzner.

Caddy is **not** declared in `docker-compose.env.yml`; it runs from the sibling compose file `apps/prototype-description-service/docker-compose.caddy.yml`, managed by the `acx-caddy.service` systemd unit (`apps/prototype-description-service/systemd/acx-caddy.service`). The Caddy container must join `${ACX_NETWORK_NAME}` (`acx-prod-net`) to reach the `prod-api` service alias; the compose file already wires that. Confirm Caddy is on the network before flipping DNS or the proxy returns connection refused.

#### Bring-Up On Hetzner

> **Precondition (hard, not optional).** `docker-compose.caddy.yml` declares **three** networks as `external: true` -- `acx-prod-net`, `acx-staging-net`, and `acx-dev-net`. On a prod-only Hetzner host only `acx-prod-net` exists (created by the prod env stack); the staging/dev networks do not. `docker compose -f docker-compose.caddy.yml up` (and `deploy-env.sh prod`, and the `acx-caddy.service` ExecStart) will hard-fail at network-attach time with `network acx-staging-net declared as external, but could not be found` and Caddy will never start. This is a startup failure distinct from the soft Caddyfile-route 502 covered below. Resolve it with **one** of:
> - **Pre-create the two empty external networks** on the prod-only host before starting Caddy (the step below does this; both `acx-prod` env up and the caddy compose then attach cleanly), OR
> - **Ship a pruned `docker-compose.caddy.yml`** that declares only `acx-prod-net` (drop the `acx-staging-net`/`acx-dev-net` entries from both the service `networks:` list and the top-level `networks:` block). This pairs with the same staging/dev prune the Caddyfile-route guard recommends at the end of this section.

```bash
# REPLACE before running: <hetzner-ip> -> Hetzner public IP.
# Mirror the OCI install: ship Caddyfile + compose + systemd unit, then start.
scp apps/prototype-description-service/Caddyfile root@<hetzner-ip>:/opt/acx-backend/Caddyfile
scp apps/prototype-description-service/docker-compose.caddy.yml root@<hetzner-ip>:/opt/acx-backend/docker-compose.caddy.yml
scp apps/prototype-description-service/systemd/acx-caddy.service root@<hetzner-ip>:/tmp/acx-caddy.service
ssh root@<hetzner-ip> '
  # PRECONDITION: create the two external networks the caddy compose requires
  # but the prod-only stack never creates. Idempotent: `docker network create`
  # of an existing network errors, so guard each with inspect. Skip this only
  # if you shipped a pruned caddy compose that declares only acx-prod-net.
  for net in acx-staging-net acx-dev-net; do
    sudo docker network inspect "$net" >/dev/null 2>&1 || sudo docker network create "$net"
  done
  sudo cp /tmp/acx-caddy.service /etc/systemd/system/acx-caddy.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now acx-caddy.service
  sudo systemctl status --no-pager acx-caddy.service | head -20
'
```

Or equivalently invoke `apps/prototype-description-service/scripts/deploy-env.sh prod root@<hetzner-ip>` -- that script already pushes `docker-compose.caddy.yml`, `Caddyfile`, and `acx-caddy.service` as part of an env deploy. **The same external-network precondition above applies to this path too**: run the `acx-staging-net`/`acx-dev-net` create loop (or ship a pruned caddy compose) before `deploy-env.sh` starts the caddy unit, or its `acx-caddy.service` start will fail identically. See [§ Time-to-Cutover One-Time Install](#estimated-time-to-cutover) below for the parent install row.

The Let's Encrypt staging-CA guard in the next subsection applies on first Caddy start.

The Caddyfile also defines `staging.api.altcontext.com` and `dev.api.altcontext.com` routes targeting `staging-api`/`dev-api` aliases. **Prod-only Hetzner migration leaves those two routes pointing at services that do not exist on the Hetzner host** -- they will 502 until staging/dev migrate or until those Caddyfile blocks are removed/commented for the prod-only host. Either prune those blocks from the deployed `/opt/acx-backend/Caddyfile` during the cutover, or keep staging/dev resolving to the OCI IPs via separate A records.

#### Let's Encrypt Rate-Limit Guard

Let's Encrypt's production CA enforces a 5-duplicate-certs-per-week limit on `api.altcontext.com`. A bouncing cutover (Hetzner boots, fails, rollback to OCI, retry) can exhaust that limit and lock issuance for days. Mitigation:

1. **First boot on Hetzner uses the LE staging CA.** Inject `acme_ca https://acme-staging-v02.api.letsencrypt.org/directory` into the global Caddyfile options block during the test boot (before DNS cutover). The staging CA has no per-week duplicate limit and issues untrusted certs that still prove the issuance path works.
2. **Flip to production CA only after the host has booted cleanly twice in a row.** Remove the `acme_ca` line, restart Caddy, then proceed to DNS cutover.
3. **If rollback is needed mid-cutover**, the OCI host still owns the production cert; no new prod issuance happens until Hetzner is retried. Document the rollback in the run log so the next attempt re-uses the staging-then-prod sequence.

### OCIR Authentication

The image registry stays on OCI. Cache OCIR auth on the new Hetzner host once:

```bash
# REPLACE before running: <hetzner-ip> -> Hetzner public IP; <operator-email> -> the OCI user that owns the auth token.
ssh root@<hetzner-ip> 'docker login iad.ocir.io -u "idu2kqqe2jxy/<operator-email>"'
# Token from OCI console -> User Settings -> Auth Tokens (or reuse the existing token).
```

### Tailscale (optional, recommended)

Install Tailscale on the Hetzner host using the same pattern documented in [`infra/oci/README.md` § Tailscale](../../../infra/oci/README.md#tailscale-recommended-for-dynamic-ip-workstations).

**Auth-key lifecycle** (do not reuse the OCI host's auth key):

1. In the Tailscale admin console, generate a **reusable, non-ephemeral** auth key scoped to the Hetzner host. Reusable is required because the Hetzner host may be re-imaged during cutover testing; ephemeral would deauthorize the node on each restart.
2. Use hostname `acx-backend-hetzner` so the OCI MagicDNS name (`acx-backend`) does not collide while both hosts run in parallel during cutover.
3. **Revoke the auth key once the Hetzner host has successfully joined the tailnet** (Tailscale admin console -> Settings -> Keys). The key only needs to exist for the duration of `tailscale up`; leaving it valid is the same as leaving a long-lived deploy credential.
4. After cutover, the operator may rename `acx-backend-hetzner` to `acx-backend` in the Tailscale admin console if the OCI host is decommissioned.

---

## DNS Cutover

Single A record change: `api.altcontext.com` -> `<hetzner-public-ip>`.

| Step | Command / action | Timing |
|------|------------------|--------|
| Pre-cutover: confirm Hetzner stack passes `/health`, `/ready`, `/recognition/health` on its own hostname | `curl https://<hetzner-test-host>/health` | T-0:00 |
| Drop DNS TTL ahead of cutover (do this 24h+ in advance if possible) | Registrar admin -> `api.altcontext.com` TTL -> 60s | T-24:00h |
| Final OCI dump + restore on Hetzner (see Postgres section) | per scripts above | T-0:30 to T-0:00 |
| Flip A record at registrar | Registrar admin -> `api.altcontext.com` A -> `<hetzner-ip>` | T-0:00 |
| Wait for DNS convergence | `dig +short api.altcontext.com @1.1.1.1` returns Hetzner IP from multiple resolvers | T-0:00 to T-0:05 |
| Force Caddy cert issuance | First HTTPS request will trigger Let's Encrypt (`curl -v https://api.altcontext.com/health`) | T-0:05 |
| Plugin smoke from at least one WP install pointing at `api.altcontext.com` | Trigger a person clustering / recognition request via the workbench | T-0:10 |
| Restore DNS TTL to nominal once stable for 1h | TTL -> 3600s | T+1:00 |

### Rollback

If the Hetzner stack fails post-cutover, flip the A record back to the OCI IP. The OCI stack stays running through cutover (it is the source of truth for the dump until row counts match). Rollback recovers within the new TTL window (60s if the pre-cutover TTL drop was done).

---

## Estimated Time-to-Cutover

| Phase | Estimate | Notes |
|-------|----------|-------|
| amd64 parity check (one-time, can be done now) | 30-60 min | Local rebuild + boot + smoke. |
| Hetzner CX22 provisioning | 5 min | Includes initial SSH + docker install. |
| One-time install (docker, OCIR login, Tailscale, directory layout, per-env + caddy systemd units) | 30 min | Two-step install. Step (a) mirrors `infra/oci/cloud-init.yaml`: docker engine + buildx + compose plugin, `/opt/acx-backend/{secrets,logs,data}` layout, UFW (allow 22/443), fail2ban. Step (b) installs the per-env `acx-prod.service` unit and `acx-caddy.service` -- these are NOT in cloud-init; they are rendered from `apps/prototype-description-service/systemd/acx-env.service.template` and `apps/prototype-description-service/systemd/acx-caddy.service` by `apps/prototype-description-service/scripts/deploy-env.sh`. Override the script's default SSH target: `apps/prototype-description-service/scripts/deploy-env.sh prod root@<hetzner-ip>` (the script defaults to `ubuntu@<oci-ip>`). Do it ahead of trigger. |
| Postgres dump + transfer + restore | 10-20 min | Depends on DB size; today << 1 GB. |
| Blob volume tar + transfer + untar | 5-15 min | Depends on blob volume size. |
| InsightFace model cache repopulation | ~5 min | First-request hit; can be pre-warmed via a synthetic scan after the stack starts. |
| DNS cutover + cert issuance + plugin smoke | 15 min | Conditional on the pre-cutover TTL drop. |
| **Total under-pressure** | **~75-120 min** | Assumes the amd64 image is already built and pushed. |
| **Total without prep** | **~3-4 h** | If the amd64 image and one-time install have not been done ahead of time. |

The recommended posture is to keep an amd64 `:fallback-amd64` image pre-built and pushed to OCIR at all times, and to provision the Hetzner one-time install during quiet hours so the trigger-driven phase is only DNS + data + smoke.

---

## Open Threads (handled outside this plan)

1. **Backup automation follow-up** -- if Slice 3's first checklist item finds no daily `pg_dump` cron, the operator opens a separate task (referenced from the run log) to add one. That follow-up benefits both OCI and Hetzner targets.
2. **Staging/dev migration** -- this plan deliberately covers prod only. If Hetzner becomes the permanent home, a follow-up plan migrates the remaining envs and decommissions OCI.
3. **OCIR replacement** -- the registry stays on OCI in the first migration. If OCI is being abandoned entirely, the same image can be mirrored to GitHub Container Registry or Hetzner's container registry, but that decision is out of scope here.
4. **Multi-region failover** -- the plan is single-region (Hetzner Nuremberg or Ashburn equivalent). Multi-region is a separate epic.

---

## Review Bar

This plan exits Slice 3 only when:

- [ ] It passes `/planning-review` against the current `apps/prototype-description-service/.env.prod.example`, `apps/prototype-description-service/docker-compose.env.yml`, and `apps/prototype-description-service/Caddyfile` (planning-review fix commit recorded in the run log; live finding status via `review_findings(operation="list", task_ref="E15-5A")`).
- [ ] Zero open planning findings remain on the E15-5a task ref.
- [ ] The Slice 3 checklist items in [the parent task plan](./E15-5a-oci-operational-hygiene-task-plan.md#checklist-for-slice-3-hetzner-fallback-plan-cx22-baseline-sizing-analysis-required) are all ticked.
