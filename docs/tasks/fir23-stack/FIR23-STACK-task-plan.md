# FIR23-STACK. acx-dev-fir — isolated FIR/SFace benchmarking backend

**Task ref:** FIR23-STACK · **Branch:** feature/fir23-stack · **Status:** in_progress

## Objective

Stand up `acx-dev-fir`, a profile-pinned recognition backend running the `face_pipeline`
profile (SFace 128d, YuNet detector), isolated from the InsightFace `acx-dev` stack, so
InsightFace-vs-FIR curated clusters can be compared side-by-side in two Workbenches.

## Why isolated stacks (not a runtime toggle)

Canon **[EMB-01]** one embedding space per comparison · **[IDX-02]** mixed-space query is
meaningless. InsightFace `buffalo_l` = 512d, SFace = 128d; the DB `media_identities.embedding`
column is dimension-pinned by `PGVECTOR_DIM` and fail-closed by the three-way guard
(`face_pipeline_adapter.py:318-329` + `settings.py:321-333`). Two models = two DBs = two stacks.
Curated clusters are model-specific materialized outputs; a read-time toggle would force
wipe+rescan and invite silent mixed-space garbage. Supersedes the dropped per-request
`X-ACX-Face-Pipeline-Profile` header design (decision #2947).

## Verified anchors

- One parameterized compose `apps/prototype-description-service/docker-compose.env.yml`;
  per-env `.env` differentiates stacks; each stack owns its postgres container + volume + network.
- SFace model_id `opencv-sface@128d/l2/cosine` (`provenance.py:86-99`); needs
  `face_recognition_sface_2021dec.onnx` + `face_detection_yunet_2026may.onnx`, fetched +
  sha256-verified by `scripts/fetch_face_pipeline_models.py`. Not present on VM (only buffalo_l).
- Dimension root: `PGVECTOR_DIM` only (`db/settings.py:213-224`); `RECOGNITION_EMBEDDING_DIMENSION`
  deliberately ignored (`settings.py:63-64`). Profile ≠ dimension: must set BOTH
  `RECOGNITION_FACE_PIPELINE_PROFILE=face_pipeline` AND `PGVECTOR_DIM=128` or boot/health fails closed.
- Deploy driver `scripts/deploy/recognition-service.sh` hardcodes `dev|staging|prod` in 6 case
  blocks (`env_to_tag`/`env_to_unit`/`env_to_remote_dir`/`env_to_health_url`/`env_to_ready_url`/
  `compose_files_for`); also `sync-compose.sh:22`, `db-reset-remote.sh:66,73,81`. Makefile targets in `mk/deploy.mk`.
- Systemd unit per env from `systemd/acx-env.service.template`; dev/staging use
  `-f docker-compose.env.yml` (no admin overlay). VM stack dir `/opt/acx-backend/<env>/`.
- Caddy `/opt/acx-backend/Caddyfile`: `dev.api.altcontext.com { reverse_proxy dev-api:8000 }`.
  Network alias is `${ACX_ENV}-api`.

## Decisions (operator-confirmed 2026-07-23)

- Durable/scripted path via **remote grok flock** (not manual stand-up).
- Public DNS ingress `fir.api.altcontext.com` via Caddy (operator adds DNS A record).

## Slices

### Slice 1 — deploy-tooling `dev-fir` support (CODE · grok flock · gated)

- Add `dev-fir` arm to all 6 case blocks in `recognition-service.sh`: tag=`dev`, unit=`acx-dev-fir`,
  remote dir=`/opt/acx-backend/fir`, health/ready URLs=`https://fir.api.altcontext.com/...`,
  compose files=`-f docker-compose.env.yml`.
- Add `dev-fir` to `sync-compose.sh:22` and `db-reset-remote.sh` env allow-lists.
- Makefile `mk/deploy.mk`: `deploy-dev-fir`, `deploy-rollback-dev-fir`, `deploy-verify ENV=dev-fir`.
- New `apps/prototype-description-service/.env.fir.example` documenting `COMPOSE_PROJECT_NAME=acx-dev-fir`,
  `ACX_ENV=dev-fir`, `ACX_IMAGE_TAG=dev`, distinct `ACX_PGDATA_PATH`/`ACX_MODELS_PATH`, shared
  `ACX_NETWORK_NAME`, `RECOGNITION_FACE_PIPELINE_PROFILE=face_pipeline`, `PGVECTOR_DIM=128`.
- Caddy block for `fir.api.altcontext.com → dev-fir-api:8000` (add to Caddyfile / template).
- Tests: extend any shell/case-coverage tests to include `dev-fir`; guard that unknown env still fails closed.

### Slice 2 — VM provisioning + deploy (INFRA · operator + orchestrator)

- Create `/opt/acx-backend/fir/{.env,secrets}` (secrets vault-fed: POSTGRES_PASSWORD, RECOGNITION_ADMIN_TOKEN).
- `fetch_face_pipeline_models.py` → place SFace+YuNet ONNX into `fir-models` (or bake into image path).
- Operator adds DNS A record `fir.api.altcontext.com → VM`.
- `make deploy-dev-fir`; verify: container Up, boot migration runs at vector(128), three-way guard passes,
  `/health` green, `active_embedding_model_id()` == `opencv-sface@128d/l2/cosine`.

### Slice 3 — fir LocalWP wiring + benchmark (ORCHESTRATION)

- fir site (`/Volumes/Butter/WP/fir`, plugin symlinked): `wp plugin activate alt-context` (LocalWP shell).
- Set `acx_recognition_url=https://fir.api.altcontext.com`; mint fresh dev tenant key; configure.
- Scan the same image set on both stacks → compare curated clusters in the two Workbenches.

## Open threads

- Caddy network: fir stack must join Caddy's shared network (shared `ACX_NETWORK_NAME`, distinct `ACX_ENV`
  avoids `${ACX_ENV}-api` alias collision). Confirm Caddy reaches `dev-fir-api`.
- Where the container loads face_pipeline ONNX from (mounted `ACX_MODELS_PATH` vs image-baked) — Slice 2 resolves.
- Model disk: SFace 38.7MB + YuNet ~0.2MB into fir-models.
