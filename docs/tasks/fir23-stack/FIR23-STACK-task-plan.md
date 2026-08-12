# FIR23-STACK. acx-dev-fir — isolated FIR/SFace benchmarking backend

**Task ref:** FIR23-STACK · **Branch:** feature/fir23-stack · **Status:** in_progress

> Rev 2 — incorporates planning-review fixes for findings FIR23-STACK-BR-01..08.

## Objective

Stand up `acx-dev-fir`, a profile-pinned recognition backend running the `face_pipeline`
profile (SFace 128d, YuNet detector), fully isolated from the InsightFace `acx-dev` stack, so
InsightFace-vs-FIR curated clusters can be compared side-by-side in two Workbenches.

## Why isolated stacks (not a runtime toggle)

Canon **[EMB-01]** one embedding space per comparison · **[IDX-02]** mixed-space query is
meaningless. InsightFace `buffalo_l` = 512d, SFace = 128d; the DB `media_identities.embedding`
column is dimension-pinned by `PGVECTOR_DIM`, fail-closed by the **three-way guard**
`assert_three_way_embedding_dimensions` (`face_pipeline_adapter.py:318-329`; the two-way
pgvector-pair guard is separately `settings.py:321-333`). Two models = two DBs = two stacks.
Supersedes the dropped per-request header design (decision #2947).

## Verified anchors

- One parameterized compose `apps/prototype-description-service/docker-compose.env.yml`; per-env
  `.env`; **each stack owns its own postgres container, volume, AND network** (per-stack external
  nets on the VM: `acx-dev-net`, `acx-prod-net`, `acx-staging-net`, `acx-demo-net`).
- **OpenCV runtime version is part of the provenance pin, not an implementation detail** <span>(QA v8 re-gate, 2026-07-28)</span>. An SFace embedding computed under OpenCV 4.x is not comparable to one computed under 5.x — CVUP-1 moves the stack — so the `cv2` major version must be recorded alongside the ONNX sha256 on every run row, and two runs that differ only in `cv2` version must **not** compare. This lane is on QA v8's critical path precisely because it is what makes the FIRTRAIN-05 re-run **under 5.x** possible as a recorded artifact; without the version pin the artifact cannot prove which stack produced it.
- **Provision a candidate-detector lane alongside the 512d/128d embedder split.** The current design is an embedder-dimension split only. QA v8 leaves the detector-vs-embedder question **undecided** — which leg wins is not known — so building only the embedder lane presupposes the answer.
- SFace model_id `opencv-sface@128d/l2/cosine` (`provenance.py:86-99`). ONNX fetched + sha256-verified by
  `scripts/fetch_face_pipeline_models.py`. **Not baked into the `dev` image** (Dockerfile:44-45; `*.onnx`
  gitignored; remote-build rsync excludes `face_pipeline/models/*.onnx`).
- Dimension root: `PGVECTOR_DIM` only (`db/settings.py:212-224`, default "512"); `RECOGNITION_EMBEDDING_DIMENSION`
  ignored (`settings.py:60-68`). Must set BOTH `RECOGNITION_FACE_PIPELINE_PROFILE=face_pipeline` AND `PGVECTOR_DIM=128`.
- **Runtime ONNX load path** = `settings.face_pipeline.resolved_models_dir` = env
  `RECOGNITION_FACE_PIPELINE_MODELS_DIR`, else package `DEFAULT_MODELS_DIR`
  (`settings.py:52-57,222-224`; `runtime_factory.py:73`; `health.py:393`). The compose mount
  `${ACX_MODELS_PATH}:/data/cache` does NOT overlay the package dir — so the env var MUST point at the mount.
- Deploy driver `recognition-service.sh` env-mapping case blocks: `env_to_tag`, `env_to_unit`,
  `env_to_remote_dir`, `env_to_health_url`, `env_to_ready_url`, `env_to_compose_files`.
  Also `do_status()` iterates `for env in dev dev-fir staging prod`. `sync-compose.sh:22` allow-list.
  `db-reset-remote.sh:66-83` arms hardcode PG_CONTAINER/API_CONTAINER/PG_USER/PG_DB/HEALTH_URL per env.
- Systemd unit from `systemd/acx-env.service.template`; `WorkingDirectory=/opt/acx-backend/{{ENV}}`,
  `ExecStart=docker compose {{COMPOSE_FILES}} up`. `converge_runtime` ships compose to `env_to_remote_dir`.
  **WorkingDirectory basename must equal ENV** → remote dir MUST be
  `/opt/acx-backend/dev-fir` (NOT `/opt/acx-backend/fir`).
- **Edge ownership:** the deploy driver owns edge convergence. `converge_runtime` ships the shared
  Caddyfile + `docker-compose.caddy.yml` checksum-gated, verifies caddy's network membership of
  `acx-dev-fir-net`, and **refuses to mutate the edge unless `ACX_EDGE_APPLY=1`** (fail-closed; it
  prints the lever). Caddy multi-homed via `/opt/acx-backend/docker-compose.caddy.yml` (networks:
  per-stack, `external: true`). Caddyfile vhost: `fir.dev.api.altcontext.com { reverse_proxy dev-fir-api:8000 }`
  (alongside existing `dev.api.altcontext.com { reverse_proxy dev-api:8000 }`).
- `dev` tier secrets: `/opt/acx-backend/dev/.env` uses **inline plaintext** `POSTGRES_DSN`,
  `RECOGNITION_AUTH_ENABLED=false`, **no vault** (only prod/staging use `oci_vault`).
- VM disk: `/` 193G, 72G avail (ample).

## Canonical stack identity (single source of truth)

- `ACX_ENV=dev-fir` · `COMPOSE_PROJECT_NAME=acx-dev-fir` · `ACX_IMAGE_TAG=dev`
- containers: `acx-dev-fir-postgres-1`, `acx-dev-fir-api-1`, `acx-dev-fir-worker-1` · api alias `dev-fir-api`
- network: `acx-dev-fir-net` (OWN network, `external`) · remote dir `/opt/acx-backend/dev-fir`
- data: `ACX_PGDATA_PATH=/opt/acx-backend/data/dev-fir-pgdata`, `ACX_MODELS_PATH=/opt/acx-backend/data/dev-fir-models`
- POSTGRES_USER=`acx_dev_fir` POSTGRES_DB=`alt_context_dev_fir`
- `RECOGNITION_FACE_PIPELINE_PROFILE=face_pipeline` · `PGVECTOR_DIM=128` · `RECOGNITION_AUTH_ENABLED=false`
- `RECOGNITION_FACE_PIPELINE_MODELS_DIR=/data/cache/face_pipeline` (under the mounted `ACX_MODELS_PATH`)
- ingress: `fir.dev.api.altcontext.com → dev-fir-api:8000`

## Decisions (operator-confirmed 2026-07-23)

- Durable/scripted path via **remote grok flock**. Public DNS ingress via Caddy (operator adds A record).

## Slices

### Slice 1 — deploy-tooling `dev-fir` support (CODE · grok flock · gated)

- `recognition-service.sh`: add `dev-fir)` arm to all 6 env-mapping case blocks — tag=`dev`,
  unit=`acx-dev-fir`, **remote dir=`/opt/acx-backend/dev-fir`** (BR-04), health/ready=`https://fir.dev.api.altcontext.com/health|/ready`,
  compose files=`-f docker-compose.env.yml`. Add `dev-fir` to `do_status()` loop (BR-08).
- `sync-compose.sh:22`: add `dev-fir` to allow-list.
- `db-reset-remote.sh`: add `dev-fir)` arm with PG_CONTAINER=`acx-dev-fir-postgres-1`,
  API_CONTAINER=`acx-dev-fir-api-1`, PG_USER=`acx_dev_fir`, PG_DB=`alt_context_dev_fir`,
  HEALTH_URL=`https://fir.dev.api.altcontext.com/health` (BR-06).
- `mk/deploy.mk`: `deploy-dev-fir` (`.PHONY`; `deploy-verify ENV=dev-fir` already generic).
  `deploy-rollback-dev-fir` **refuses**: dev-fir shares the `:dev` image tag with `acx-dev`, so a
  FIR-only rollback is impossible — use `deploy-rollback-dev` (affects both).
- New `apps/prototype-description-service/.env.fir.example` = the "Canonical stack identity" above, incl.
  **`RECOGNITION_FACE_PIPELINE_MODELS_DIR=/data/cache/face_pipeline`** (BR-01) and inline dev-style secrets,
  auth disabled, **no vault, no tenant key** (BR-05).
- Tests: extend shell/case coverage to include `dev-fir`; unknown env still fails closed.

### Slice 2 — VM provisioning + deploy (INFRA · operator + orchestrator)

Ordered (gates matter):
1. Create `/opt/acx-backend/dev-fir/.env` from `.env.fir.example` (inline secrets, fir DB password).
2. Ensure models land where `RECOGNITION_FACE_PIPELINE_MODELS_DIR=/data/cache/face_pipeline` reads them
   (BR-01): `fetch_face_pipeline_models.py --dest /opt/acx-backend/data/dev-fir-models/face_pipeline`
   is **mandatory** — `preflight_remote_face_pipeline_models` / boot smoke only verify/probe
   existing weights; neither provisions them.
3. **Operator adds DNS A/CNAME record `fir.dev.api.altcontext.com → VM`; CONFIRM it resolves** (BR-07)
   BEFORE public health verify.
4. **First dev-fir deploy:** run `make deploy-dev-fir` with `ACX_EDGE_APPLY=1` so `converge_runtime`
   creates/attaches `acx-dev-fir-net`, ships Caddyfile + `docker-compose.caddy.yml`, and applies edge
   mutation (vhost + network membership). Without the lever the driver fail-closes and prints it.
   Fallback only if the net must be pre-created by hand: `docker network create --label com.docker.compose.network=backend --label com.docker.compose.project=acx-dev-fir acx-dev-fir-net`
   (compose refuses adopting an unlabeled pre-existing net; the deploy driver auto-creates it in
   boot smoke + converge, so this is rarely needed).
5. Verify: container Up, boot migration at `vector(128)`, three-way guard passes,
   `active_embedding_model_id()==opencv-sface@128d/l2/cosine`, **local** `/health` green.
6. Verify public `https://fir.dev.api.altcontext.com/health` green + TLS issued.

### Slice 3 — fir LocalWP wiring + benchmark (ORCHESTRATION)

- fir site (`/Volumes/Butter/WP/fir`, plugin symlinked): `wp plugin activate alt-context` (LocalWP shell).
- Set `acx_recognition_url=https://fir.dev.api.altcontext.com`; **auth disabled ⇒ no tenant key** (mirror dev) (BR-05).
- Scan the SAME image set on both stacks → compare curated clusters in the two Workbenches.

## Open threads

- Edge ownership: deploy driver (`converge_runtime`) owns Caddy/net convergence gated by `ACX_EDGE_APPLY=1`;
  DNS A/CNAME for `fir.dev.api.altcontext.com` remains operator-manual.
- Model disk: SFace 38.7MB + YuNet ~0.2MB into dev-fir-models.
- `do_status` cosmetic addition (BR-08) optional but included.
