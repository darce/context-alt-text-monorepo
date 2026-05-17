# E15-5a Hetzner CX22 Fallback Plan

> **Status**: draft -- pending `/planning-review`
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
| Reverse proxy            | Caddy 2 ([Caddyfile](../../../apps/prototype-description-service/Caddyfile)) | Same Caddy, same Caddyfile (Let's Encrypt re-issues on first request) |
| Container registry       | `iad.ocir.io/idu2kqqe2jxy/acx-backend`           | Same (pull works cross-cloud; auth token portable)            |
| Image architecture       | `linux/arm64` built natively on the A1.Flex VM   | **`linux/amd64`** -- requires rebuild via `docker buildx`     |
| Persistent state         | `/opt/acx-backend/data/prod-pgdata` (Postgres)   | Same path layout on CX22 local disk                          |
| Model cache              | `/opt/acx-backend/data/prod-models`              | Re-populated on first container start (not migrated)         |
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

| Step | Pass criterion |
|------|----------------|
| `docker buildx build --platform linux/amd64 --build-arg GIT_COMMIT_SHA=$(git rev-parse HEAD) -t iad.ocir.io/idu2kqqe2jxy/acx-backend:fallback-amd64 .` | Build completes with exit 0; no architecture-specific patches required to `Dockerfile`, `pyproject.toml`, or system package list. |
| `docker compose -f docker-compose.env.yml up -d` against the rebuilt image on the x86 host | All four services (postgres, api, worker, caddy if attached) reach `healthy` within the same timeout as the OCI gate (~60s for postgres, ~120s for api). |
| `curl https://<test-host>/health` and `/recognition/health` | Returns the same JSON shape and the `commit_sha` field matches `GIT_COMMIT_SHA` build-arg passed above. |
| `curl https://<test-host>/ready` | Returns 200 with `database: up` and `models: loaded`. The InsightFace cache must download cleanly on amd64. |

Any failure on these steps **forces** either CX32 review or an explicit architecture-fix follow-up task before DNS cutover.

---

## Postgres Data Migration

### Backup Baseline

Per the parent task plan's Slice 3 first checklist item: the operator verifies whether a daily `pg_dump` cron is currently running on the OCI VM and records the result in the run log.

- If **yes**, the fallback uses the most recent nightly dump as the migration starting point and runs a fresh `pg_dump` immediately before cutover to capture the final delta.
- If **no**, the fallback requires a one-off `pg_dump` as a prerequisite step and opens a separate follow-up to automate ongoing backups. The follow-up is not in scope for this plan; capture the follow-up task ref in the run log.

### Migration Steps

```bash
# 1. On OCI VM: capture final dump just before cutover.
ssh ubuntu@acx-backend.<tailnet>.ts.net '
  sudo docker exec acx-prod-postgres-1 \
    pg_dump -U acx_app -d alt_context_service -Fc \
    --file=/var/lib/postgresql/data/prod-cutover-$(date -u +%Y%m%dT%H%M%SZ).dump
  ls -lh /var/lib/postgresql/data/prod-cutover-*.dump
'

# 2. Workstation: pull the dump.
scp ubuntu@acx-backend.<tailnet>.ts.net:/var/lib/postgresql/data/prod-cutover-*.dump \
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

The InsightFace model cache (`prod-models`) is NOT migrated -- it re-downloads from Hugging Face on first container start. Add ~5 min to the cutover timing for the warm-up.

---

## Env, Secrets, and Config Migration

### Files to Copy Verbatim

The full surface lives in [`apps/prototype-description-service/.env.prod.example`](../../../apps/prototype-description-service/.env.prod.example). The actual prod values live in `/opt/acx-backend/prod/secrets/.env` on the OCI VM. Migrate as a unit:

```bash
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
| `ACX_IMAGE_TAG=latest`            | Unchanged once the amd64 `:latest` is pushed (see Image Promotion).      |
| `ACX_PGDATA_PATH=/opt/acx-backend/data/prod-pgdata` | Same path; ensure directory exists on Hetzner before `docker compose up`. |
| `ACX_MODELS_PATH=/opt/acx-backend/data/prod-models` | Same path; ensure directory exists; cache repopulates on first run. |
| `ACX_NETWORK_NAME=acx-prod-net`   | Unchanged.       |
| `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` | Unchanged; the `pg_restore` above expects these to match. |
| `POSTGRES_DSN`/`POSTGRES_SYNC_DSN`| Unchanged (container-internal `postgres:5432`). |
| `RECOGNITION_AUTH_ENABLED=true`   | Unchanged.       |
| `RECOGNITION_ALLOWED_API_KEYS`    | MUST remain empty; the prod startup guard refuses to boot otherwise. Provision real keys via `scripts/manage_api_keys.py` (same flow as OCI). |
| `RECOGNITION_ALLOWED_ORIGINS`     | Unchanged.       |
| `TENANT_ID`                       | Unchanged (single-tenant prod). |
| Cache dirs (`CACHE_BASE`, `HF_HOME`, etc.) | Unchanged (container-internal). |

### Caddyfile

`apps/prototype-description-service/Caddyfile` is identical on both hosts; the only deploy artifact needed at `/opt/acx-backend/Caddyfile`. Let's Encrypt re-issues the cert on first request once DNS points at Hetzner.

### OCIR Authentication

The image registry stays on OCI. Cache OCIR auth on the new Hetzner host once:

```bash
ssh root@<hetzner-ip> 'docker login iad.ocir.io -u "idu2kqqe2jxy/<operator-email>"'
# Token from OCI console -> User Settings -> Auth Tokens (or reuse the existing token).
```

### Tailscale (optional, recommended)

Install Tailscale on the Hetzner host using the same pattern documented in [`infra/oci/README.md` § Tailscale](../../../infra/oci/README.md#tailscale-recommended-for-dynamic-ip-workstations). Use a fresh auth key with hostname `acx-backend-hetzner` so the OCI MagicDNS name doesn't collide while both hosts run in parallel during cutover. After cutover, the operator can rename `acx-backend` if desired.

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
| One-time install (docker, OCIR login, Tailscale, directory layout) | 30 min | Mirrors the OCI cloud-init script; do it ahead of trigger. |
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

- [ ] It passes `/planning-review` against the current `apps/prototype-description-service/.env.prod.example`, `apps/prototype-description-service/docker-compose.env.yml`, and `apps/prototype-description-service/Caddyfile` (review-run id recorded in the run log).
- [ ] Zero open planning findings remain on the E15-5a task ref.
- [ ] The Slice 3 checklist items in [the parent task plan](./E15-5a-oci-operational-hygiene-task-plan.md#checklist-for-slice-3-hetzner-fallback-plan-cx22-baseline-sizing-analysis-required) are all ticked.
