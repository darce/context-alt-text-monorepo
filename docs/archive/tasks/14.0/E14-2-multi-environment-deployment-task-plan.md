# E14-2. Multi-Environment Deployment (dev / staging / prod)

> **Metadata**
>
> - **Date**: 2026-04-01
> - **Author**: Claude Opus 4.6
> - **Owning Epic**: [docs/epics/v0.3.1/self-hosting-epic.md](../../epics/v0.3.1/self-hosting-epic.md)
> - **Epic Short ID**: E14
> - **Review Coverage Target**: 2

---

## Objective

Run three isolated environments (dev, staging, prod) on the single OCI VM, each with its own Postgres, API, worker, secrets, and subdomain. Enable a promotion workflow where images flow dev → staging → prod with verification gates at each step.

## Problem Statement

E14-1 deployed a single production stack. There is no way to test changes on the VM without risking the production service. Developers must either test locally (which hides ARM/container/network differences) or push directly to production. A staging environment that mirrors production and a dev environment that can be broken freely are both missing.

## Constraints

- Single VM: `VM.Standard.A1.Flex` with 4 OCPUs and 24 GB RAM. All three environments share this hardware.
- Resource budget: each full stack (postgres + api + worker) uses ~1.1 GB RAM. Three stacks = ~3.3 GB. Well within the 24 GB limit.
- Single Caddy instance routes all three subdomains. Each environment's API runs on the Docker internal network; no host ports except 80/443.
- Secrets must be isolated per environment — dev credentials must not grant access to prod data.
- The systemd unit from cloud-init (`acx-backend.service`) currently starts a single compose stack from `/opt/acx-backend`. This task replaces it with per-environment units.
- Plugin boundary rule: cloud-init and Terraform core (VCN, instance, security lists) must not be modified for this task. Only the Caddyfile, compose files, systemd overrides, and deployment scripts change.
- Port 80 and 443 are already open in the OCI security list and iptables (from E14-1 domain setup).

## Workflow Principles

- Each environment is a fully isolated compose project with its own Postgres, its own data volumes, and its own secrets. No shared databases.
- Image tags drive promotion: `:dev` is the bleeding edge, `:staging` is a promoted candidate, `:latest` is the verified production image.
- Promotion is an explicit tag-and-pull, not an automatic pipeline. The operator decides when to promote.
- Dev can be broken at any time without affecting staging or prod.
- Staging must pass health checks before its image is promoted to prod.

## Terminology

- **Environment**: An isolated compose project (postgres + api + worker) with its own subdomain, secrets, and data volumes.
- **Promotion**: Retagging a Docker image from one environment's tag to the next (`:dev` → `:staging` → `:latest`) and pulling it on the VM.
- **Compose project**: A Docker Compose stack with a unique `COMPOSE_PROJECT_NAME`, giving it isolated containers and networks.

## Current State Analysis

- Single production stack runs at `/opt/acx-backend` with `docker-compose.prod.yml`.
- `acx-backend.service` systemd unit starts this single stack.
- E14-1 deployed with IP-only access (`https://129.213.40.111/health`). Domain-based routing (`api.altcontext.com`) was added post-E14-1 as a follow-on but E14-1 docs and the ops README still reference IP-based verification.
- Caddy now serves `api.altcontext.com` with Let's Encrypt TLS (configured after E14-1 completion).
- DNS A records for `api`, `staging.api`, and `dev.api` subdomains all point to `129.213.40.111` (propagated and verified).
- OCIR has one image tag: `iad.ocir.io/idu2kqqe2jxy/acx-backend:latest`.
- No dev or staging infrastructure exists on the VM.
- Ports 80 and 443 are open in both OCI security list and iptables.
- **Prerequisite**: E14-1 ops docs (`infra/oci/README.md`) should be updated to reflect domain-based access as part of Slice 1 migration.

## Target Outcome

Three subdomains, each backed by an isolated stack on the same VM:

| Environment | Subdomain                    | Image Tag  | Can Break?        |
| ----------- | ---------------------------- | ---------- | ----------------- |
| dev         | `dev.api.altcontext.com`     | `:dev`     | Yes               |
| staging     | `staging.api.altcontext.com` | `:staging` | No (mirrors prod) |
| prod        | `api.altcontext.com`         | `:latest`  | No                |

Operator promotes images via:

```bash
# Promote dev to staging
docker tag iad.ocir.io/idu2kqqe2jxy/acx-backend:dev iad.ocir.io/idu2kqqe2jxy/acx-backend:staging
docker push iad.ocir.io/idu2kqqe2jxy/acx-backend:staging
ssh ubuntu@129.213.40.111 'cd /opt/acx-backend/staging && docker compose pull && sudo systemctl restart acx-staging'

# Promote staging to prod (after e2e verification)
docker tag iad.ocir.io/idu2kqqe2jxy/acx-backend:staging iad.ocir.io/idu2kqqe2jxy/acx-backend:latest
docker push iad.ocir.io/idu2kqqe2jxy/acx-backend:latest
ssh ubuntu@129.213.40.111 'cd /opt/acx-backend/prod && docker compose pull && sudo systemctl restart acx-prod'
```

## Context Loading

- Epic: `docs/epics/v0.3.1/self-hosting-epic.md`
- Prior task: `docs/tasks/14.0/E14-1-deploy-description-service-to-oci-task-plan.md`
- Infra: `infra/oci/cloud-init.yaml` (systemd unit reference, directory layout)
- Compose: `apps/prototype-description-service/docker-compose.prod.yml`
- Caddy: `apps/prototype-description-service/Caddyfile`
- Ops: `infra/oci/README.md` (deployment workflow)

## Contract and Boundary Impact

| Boundary         | Owner   | Current Contract            | Expected Change                              | Compatibility Needed? | Verification                    |
| ---------------- | ------- | --------------------------- | -------------------------------------------- | --------------------- | ------------------------------- |
| FastAPI HTTP API | backend | `api/main.py` router mounts | None; same API across all envs               | N/A                   | Health check per subdomain      |
| Caddy routing    | infra   | `Caddyfile`                 | Three subdomain blocks instead of one        | No                    | All three subdomains return 200 |
| Systemd services | infra   | `acx-backend.service`       | Replaced by `acx-{prod,staging,dev}.service` | No                    | `systemctl status` per env      |
| OCIR image tags  | infra   | `:latest` only              | Add `:dev` and `:staging`                    | No                    | All three tags pullable         |

## Proposed Solution

Each environment gets its own compose project that declares a named external network (`acx-prod-net`, `acx-staging-net`, `acx-dev-net`). Within each project, the API service is aliased as `api` on its own network. A standalone Caddy compose project joins all three external networks and routes each subdomain to the correct backend via the network-scoped hostname (`api` resolved on the target network).

**Network and service-discovery design:**

```
Caddy container
  ├── joins acx-prod-net    → reverse_proxy api:8000  (resolves to prod api)
  ├── joins acx-staging-net → reverse_proxy api:8000  (resolves to staging api)
  └── joins acx-dev-net     → reverse_proxy api:8000  (resolves to dev api)
```

Each environment compose declares:

```yaml
networks:
  backend:
    name: acx-${ACX_ENV}-net # e.g. acx-prod-net
    driver: bridge
```

The Caddy compose joins all three as external networks and uses Caddy's `network` upstream directive to route per-subdomain:

```
api.altcontext.com {
    reverse_proxy api:8000 {
        transport http {
            # Caddy resolves 'api' on acx-prod-net
        }
    }
}
```

This avoids unique container names or host port conflicts. Each `api` service name is scoped to its own network.

## Files and Surfaces to Change

| Surface              | File                                                          | Change                                                                                         |
| -------------------- | ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Caddy config         | `apps/prototype-description-service/Caddyfile`                | Three subdomain blocks with network-scoped upstreams                                           |
| Env compose template | `apps/prototype-description-service/docker-compose.env.yml`   | **New**; parameterized compose with `${ACX_ENV}`, named external network, env-specific volumes |
| Caddy compose        | `apps/prototype-description-service/docker-compose.caddy.yml` | **New**; standalone Caddy joining `acx-{prod,staging,dev}-net` external networks               |
| Env template         | `apps/prototype-description-service/.env.prod.example`        | Extend with `ACX_ENV`, `ACX_IMAGE_TAG`, `ACX_DATA_PREFIX` documentation                        |
| Systemd units        | `apps/prototype-description-service/systemd/acx-prod.service` | **New**; repo-managed unit template for prod (staging/dev derived from same template)          |
| Deploy script        | `apps/prototype-description-service/scripts/deploy-env.sh`    | **New**; installs compose, env, systemd unit for a given environment on the VM                 |
| Ops docs             | `infra/oci/README.md`                                         | Update with multi-env layout, promotion workflow, domain-based health checks                   |

## Related Files

| File                                                         | Note                                                                             |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| `infra/oci/cloud-init.yaml`                                  | Defines original `acx-backend.service`; not modified but overridden by new units |
| `apps/prototype-description-service/docker-compose.prod.yml` | Current single-env compose; replaced by parameterized template                   |
| `apps/prototype-description-service/.env.prod.example`       | Extended with per-env variable documentation                                     |

## Verification Strategy

- Deterministic tests:
  - `docker compose -f docker-compose.env.yml config` validates for each env
  - `docker compose -f docker-compose.caddy.yml config` validates Caddy routing
- Runtime-parity checks:
  - `curl https://api.altcontext.com/health` returns 200
  - `curl https://staging.api.altcontext.com/health` returns 200
  - `curl https://dev.api.altcontext.com/health` returns 200
  - Each environment has its own Postgres with independent data
- Promotion checks:
  - Tag `:dev` → `:staging`, pull on VM, staging health returns 200
  - Tag `:staging` → `:latest`, pull on VM, prod health returns 200
- Isolation checks:
  - Stop dev stack; staging and prod continue serving
  - Dev Postgres data is independent of prod Postgres data

## Slice Delivery

### Slice 1: VM directory scaffold and per-environment secrets

**Goal**: Create the three-environment directory structure on the VM with isolated secrets. Requires a brief maintenance window (~2 min) to stop, relocate, and restart the production stack.

Changes:

- Stop `acx-backend.service` (maintenance window begins)
- Create `/opt/acx-backend/{prod,staging,dev}/` directories, each with `secrets/.env` and `.env` symlink
- Migrate existing production compose, Caddyfile, db-init, and secrets from `/opt/acx-backend/` root into `/opt/acx-backend/prod/`
- Move existing pgdata to `/opt/acx-backend/data/prod-pgdata/`
- Create staging and dev secrets with separate Postgres credentials and API keys
- Restart prod via new systemd unit (maintenance window ends)
- Update `infra/oci/README.md` health checks from IP-based to domain-based

Proof:

- `ls /opt/acx-backend/{prod,staging,dev}/secrets/.env` all exist with different credentials
- Existing prod data preserved after migration

### Slice 2: Parameterized compose template and Caddy routing

**Goal**: A single compose template that works for any environment via `.env` variables, plus a Caddy config routing all three subdomains.

Changes:

- `docker-compose.env.yml`: parameterized with `${ACX_ENV}`, `${ACX_IMAGE_TAG}`, `${ACX_DATA_PREFIX}` for volume paths and container names
- `docker-compose.caddy.yml`: standalone Caddy connecting to all three compose networks
- `Caddyfile`: three subdomain blocks routing to env-specific API containers
- Per-env `.env` files set `COMPOSE_PROJECT_NAME=acx-${env}`, `ACX_IMAGE_TAG`, and data paths

Proof:

- `docker compose -f docker-compose.env.yml config` validates with each env's `.env`
- `docker compose -f docker-compose.caddy.yml config` validates

### Slice 3: Systemd units and DNS

**Goal**: Three systemd units and DNS records so each environment auto-starts on boot.

Changes:

- Create `acx-prod.service`, `acx-staging.service`, `acx-dev.service` systemd units
- Disable old `acx-backend.service`
- DNS: add `staging.api` and `dev.api` A records pointing to `129.213.40.111`

Proof:

- `sudo systemctl start acx-prod acx-staging acx-dev` starts all three stacks
- All three subdomains return 200 with Let's Encrypt TLS
- `sudo reboot` recovers all three environments

### Slice 4: Image tagging and promotion workflow

**Goal**: Push tagged images and document the promotion workflow.

Changes:

- Push `:dev` and `:staging` tags to OCIR
- Document promotion commands in `infra/oci/README.md`
- Test full promotion cycle: build → push `:dev` → promote to `:staging` → promote to `:latest`

Proof:

- All three tags exist in OCIR
- Promotion from `:dev` to `:staging` updates the staging environment
- Promotion from `:staging` to `:latest` updates the prod environment
- Each environment serves its expected image version

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded E14-1 deployment state and ops docs
- [x] Verified VM is reachable and current prod stack is healthy
- [x] Confirmed DNS for `staging.api` and `dev.api` subdomains

### Checklist: Slice 1

- [x] Three env directories created on VM
- [x] Existing prod stack migrated from root to `prod/`
- [x] Per-env secrets created with unique credentials
- [x] Existing pgdata preserved after migration
- [x] Production health check passes after migration

### Checklist: Slice 2

- [x] Parameterized compose validates for all three envs
- [x] Caddy compose validates with three-network routing
- [x] Caddyfile has three subdomain blocks
- [x] No hardcoded paths or image tags in compose template

### Checklist: Slice 3

- [x] Three systemd units created and enabled
- [x] Old `acx-backend.service` disabled
- [x] DNS records propagated for all three subdomains
- [x] All three subdomains return 200 with valid TLS
- [x] VM reboot recovers all three environments

### Checklist: Slice 4

- [x] Three image tags exist in OCIR
- [x] Promotion from dev to staging verified (2026-04-02)
- [x] Promotion from staging to prod verified (2026-04-02)
- [x] README updated with promotion workflow

## Review Readiness

- [x] No secrets committed to repo
- [x] Production migration completed within a controlled maintenance window (brief downtime expected during prod stack relocation and systemd switchover; no zero-downtime guarantee for this migration)
- [x] Handoff decision records each slice
- [x] `CURRENT_TASK.md` regenerated after final slice

## Success Criteria

- [x] `https://api.altcontext.com/health` returns 200
- [x] `https://staging.api.altcontext.com/health` returns 200
- [x] `https://dev.api.altcontext.com/health` returns 200
- [x] Each environment has independent Postgres data
- [x] Stopping one environment does not affect the others (verified: stop dev, prod+staging 200)
- [x] Image promotion workflow works end-to-end (dev→staging→prod verified 2026-04-02)
- [x] VM reboot auto-recovers all three environments
