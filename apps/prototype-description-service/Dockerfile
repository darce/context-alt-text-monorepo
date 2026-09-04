# Multi-stage Dockerfile for prototype-description-service (ARM64)
#
# Default target `runtime`: recognition-only image.
#   InsightFace + onnxruntime CPU; torch-free (no VLM extras).
# Optional target `runtime-vlm`: recognition + VLM/torch (Florence-2 path).
#   Installs locked `--extra bench --extra vlm` so ACX_DESCRIPTION_ADAPTER can
#   leave the seeded placeholder once weights are provisioned.
#
# STAGE ORDER IS LOAD-BEARING: BuildKit builds the *last* stage when `--target`
# is omitted, and no build path in this repo passes `--target`
# (scripts/deploy/recognition-service.sh, .github/workflows/deploy-recognition.yml,
# infra/oci/README.md). `runtime` must therefore stay the final stage in this
# file or every default build silently ships torch to production
# (ORCH-LAUNCH-01-S1-BR-01). recognition/tests/deploy/test_dockerfile_stage_topology.py
# enforces this.
#
# Stage order: uv -> builder -> builder-vlm -> runtime-base -> runtime-vlm -> runtime
# (ORCH-LAUNCH-01-S1-BR-02 / RA-08: shared runtime-base + single entrypoint).
#
# Build recognition (default — production torch-free image):
#   docker build --platform linux/arm64 \
#     --build-arg GIT_COMMIT_SHA=$(git rev-parse HEAD) \
#     -t iad.ocir.io/idu2kqqe2jxy/acx-backend:latest .
# Build VLM-capable (explicit target; distinct repository — not a :vlm tag on
# acx-backend). scripts/deploy/recognition-service.sh maps ACX_BUILD_TARGET=runtime-vlm
# → IMAGE_NAME-vlm (default acx-backend-vlm):
#   docker build --platform linux/arm64 --target runtime-vlm \
#     --build-arg GIT_COMMIT_SHA=$(git rev-parse HEAD) \
#     -t iad.ocir.io/idu2kqqe2jxy/acx-backend-vlm:latest .
#
# Deps resolve from the checked-in uv.lock via `uv sync --locked` (FIR4-BR-01 /
# ORCH-LAUNCH-01-S1-RB-07): --locked asserts uv.lock still matches pyproject.toml.
# VLM model weights are NOT downloaded at container start (see runtime-vlm).

# Build-time provenance. Operators pass the current repo HEAD via
# `--build-arg GIT_COMMIT_SHA=$(git rev-parse HEAD)`; see infra/oci/README.md.
# The value is propagated through the runtime stage as APP_GIT_COMMIT_SHA so
# api/main.py can surface it on /health and /version (E15-3a-BR-03).
ARG GIT_COMMIT_SHA=unknown

# Pin uv for reproducible multi-arch builds (ghcr.io/astral-sh/uv is multi-arch).
# Bump deliberately when refreshing the service lock with a newer uv.
ARG UV_VERSION=0.11.21
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---------------------------------------------------------------------------
# Stage 1: Builder — compile native dependencies (InsightFace, onnxruntime)
# Default recognition path: runtime+[bench] only. Torch-free.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

COPY --from=uv /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    pkg-config \
    libopenblas-dev \
    liblapack-dev \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Lock is the system of record for runtime+[bench] image deps (FIR4-BR-01).
COPY pyproject.toml uv.lock ./

# Install exact locked runtime+[bench] deps into a relocatable venv.
# insightface remains installed through FIR-4: the production dark default still
# uses the incumbent path (FIR-6 removes it). face_pipeline ONNX models are NOT
# baked into the image here (operator fetch/verify for dark envs).
# --no-install-project: app package is installed --no-deps in the runtime stage.
# --locked: fail the build if uv.lock is out of date with pyproject.toml
# (ORCH-LAUNCH-01-S1-RB-07; --frozen would skip that check).
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1
RUN uv venv /opt/venv \
    && uv sync --locked --no-dev --extra bench --no-install-project

ENV PATH="/opt/venv/bin:$PATH"

# ---------------------------------------------------------------------------
# Stage 1b: Builder VLM — runtime+[bench]+[vlm] on top of builder (RA-08 / BR-02)
# Inherits apt, WORKDIR, lock COPY, UV_* env, and the existing venv; only the
# sync extras differ so the two builders cannot drift.
# ---------------------------------------------------------------------------
FROM builder AS builder-vlm

# Same lock, same bench extra, plus vlm (torch/transformers/…). --locked asserts
# uv.lock still matches pyproject.toml (ORCH-LAUNCH-01-S1-RB-07).
RUN uv sync --locked --no-dev --extra bench --extra vlm --no-install-project

# ---------------------------------------------------------------------------
# Stage 2: Runtime base — shared layers for recognition and VLM images (BR-02)
# Holds everything both runtime stages share so COPY/ENV/boot cannot drift.
# Not a deploy target; children are runtime-vlm and runtime.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime-base

# Runtime libs needed by OpenCV, InsightFace, and onnxruntime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopenblas0 \
    liblapack3 \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root identity + writable scratch paths only (ORCH-LAUNCH-01-S1-RB-03).
# DEVIATION from the reviewer's suggested `chown -R acx:acx /app /opt/venv`:
# leave /app and /opt/venv root:root (world-readable/executable) so the
# unprivileged runtime user cannot rewrite application code or the virtualenv —
# chowning them to acx would hand that persistence target straight back.
#
# Paths (what is actually true at runtime):
#   /data/cache — compose bind-mounts host weights here :ro. Image mkdir+chown
#     is only a seed for unmounted `docker run`; host ownership wins on the bind.
#   /var/lib/acx-blobs — named volume for multipart uploads; image seed+chown
#     so *fresh* volumes inherit acx ownership. Docker never re-chowns an
#     existing named volume created under root — operators must run the
#     compose `fix-blob-ownership` repair profile once on upgraded stacks
#     (see docker-compose.env.yml). Entrypoint fails closed if unwritable.
#   /var/log/acx — file logs for USER acx (api.logging_config). Not under /app:
#     /app stays root:root and import-time mkdir of /app/logs would kill boot.
#   /var/cache/acx/hf_modules — private HF trust_remote_code module scratch.
#     Compose mounts a per-container noexec tmpfs here; image seed for bare runs.
#     HF_MODULES_CACHE MUST be set as ENV (transformers reads it at import time).
#
# The gid is pinned as deliberately as the uid (WBUX6-MRG-01). `groupadd -r acx`
# without `-g` lets the base image hand out whatever system gid is free —
# observed `uid=10001(acx) gid=999(acx)` on python:3.12-slim. The GPU host
# provisions the describe-load publish directory `root:10001 0775`
# (scripts/deploy/gpu-lifecycle-install.sh), which grants write access through
# the *group*, so a drifting gid makes the container match neither owner nor
# group: it falls through to `other` (r-x) and the describe-load publish fails
# with EACCES. Owning the directory as 10001:10001 instead would also work but
# would hand the container chmod/chown/rename rights over the host's directory;
# group-write with a pinned gid is the least-privilege half of that pair.
RUN groupadd -r -g 10001 acx && useradd -r -g acx -u 10001 acx \
    && mkdir -p /data/cache /var/lib/acx-blobs /var/cache/acx/hf_modules /var/log/acx \
    && chown acx:acx /data/cache /var/lib/acx-blobs /var/cache/acx/hf_modules /var/log/acx
ENV HF_MODULES_CACHE=/var/cache/acx/hf_modules

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Rebind the top-level ARG inside this stage so ENV can consume it.
# Without this, GIT_COMMIT_SHA is out of scope in the runtime image.
ARG GIT_COMMIT_SHA=unknown
ENV APP_GIT_COMMIT_SHA=${GIT_COMMIT_SHA}

WORKDIR /app

# Copy application code (shared by both runtime images)
COPY api/ api/
COPY db/ db/
COPY recognition/ recognition/
COPY roster/ roster/
COPY scene/ scene/
COPY shared/ shared/
COPY scripts/ scripts/
COPY pyproject.toml .

# Weight/cache env: /data/cache is the host bind (compose :ro). Module cache is
# HF_MODULES_CACHE above — not under HF_HOME — so trust_remote_code never tries
# to makedirs on the read-only weight mount.
# TRANSFORMERS_CACHE intentionally omitted (ORCH-LAUNCH-01-S1-BR-04): deprecated
# since transformers 4.36 in favour of HF_HOME/HF_HUB_CACHE (locked 4.48.3).
# Do not declare VOLUME here — see runtime-vlm comment, ORCH-LAUNCH-01-S1-RA-10.
ENV CACHE_BASE=/data/cache
ENV HF_HOME=/data/cache/huggingface_cache
ENV HF_HUB_CACHE=/data/cache/huggingface_cache
ENV INSIGHTFACE_CACHE_DIR=/data/cache/insightface
ENV INSIGHTFACE_HOME=/data/cache/insightface

EXPOSE 8000

# Single boot chain for both images (ORCH-LAUNCH-01-S1-BR-02 / RA-08).
# POSTGRES_SYNC_DSN is used by Alembic (via db/migrations/env.py).
# Full boot chain lives in scripts/docker-entrypoint.sh; CMD is deliberately bare.
CMD ["/app/scripts/docker-entrypoint.sh"]

# ---------------------------------------------------------------------------
# Stage 2a: Runtime VLM — recognition path + torch/transformers (OPTIONAL)
# Build with: docker build --target runtime-vlm ...
# Deliberately NOT the last stage — see the stage-order note in the header.
#
# Model-weight cache strategy (mount, not bake):
#   VLM weights (Florence-2 / HF hub) are served from a host bind mount at
#   /data/cache:ro (immutable weights; trust_remote_code must not write there).
#   Operators seed HF_HOME outside this offline image
#   (`python -m scripts.seed_vlm_cache`, see infra/oci/README.md § VLM weight cache).
#   Module scratch is HF_MODULES_CACHE=/var/cache/acx/hf_modules (private tmpfs
#   in compose — not the weight mount). Boot fail-closed is scripts.verify_vlm_cache
#   (manifest + trust_remote_code *.py set match) on the entrypoint VLM path.
#   HF_HUB_OFFLINE=1 / TRANSFORMERS_OFFLINE=1 are a second line of defense.
# ---------------------------------------------------------------------------
FROM runtime-base AS runtime-vlm

COPY --from=builder-vlm /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Build-immutable identity: /app/.image-variant is the source of truth for
# /health + /version + entrypoint (must match ImageVariant.VLM — sr-007).
# ENV alone is not safe: compose env_file can override image ENV and fail open.
ENV ACX_IMAGE_VARIANT=vlm
RUN printf 'vlm\n' > /app/.image-variant && chmod 0444 /app/.image-variant

# Install the app package into /opt/venv without resolving build/runtime deps.
# --no-deps: runtime deps come only from the locked uv.lock sync above.
# --no-build-isolation: PEP 517 must not pull setuptools/etc. from the network
# outside the lock (FINALB-05 / DEP-01/02). Use the venv interpreter explicitly.
RUN --mount=type=bind,from=uv,source=/uv,target=/usr/local/bin/uv \
    uv pip install --python /opt/venv/bin/python --no-cache-dir -e . --no-deps --no-build-isolation

# Offline runtime: cannot self-seed; network fetch blocked if gate is bypassed.
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1

# /data/cache is a :ro host bind supplied by compose/deploy (ORCH-LAUNCH-01-S1-RA-10).
# No VOLUME instruction: an anonymous volume here would leak unreclaimable disk
# on every `docker run` without an explicit mount (including boot-smoke).

# Drop root for the serving process (SEC-13). Writable under USER acx:
# /var/lib/acx-blobs (named volume) + /var/cache/acx/hf_modules (tmpfs).
# /data/cache is read-only weights; /app and /opt/venv stay root:root.
USER acx

# ---------------------------------------------------------------------------
# Stage 2b: Runtime — slim image with only what's needed to run (recognition)
# DEFAULT final stage: torch-free. MUST remain the last stage in this file.
# ---------------------------------------------------------------------------
FROM runtime-base AS runtime

# Copy the virtualenv from the builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Build-immutable identity (must match ImageVariant.RECOGNITION). See runtime-vlm.
ENV ACX_IMAGE_VARIANT=recognition
RUN printf 'recognition\n' > /app/.image-variant && chmod 0444 /app/.image-variant

# Install the app package into /opt/venv without resolving build/runtime deps.
# --no-deps: runtime deps come only from the locked uv.lock sync above.
# --no-build-isolation: PEP 517 must not pull setuptools/etc. from the network
# outside the lock (FINALB-05 / DEP-01/02). Use the venv interpreter explicitly.
RUN --mount=type=bind,from=uv,source=/uv,target=/usr/local/bin/uv \
    uv pip install --python /opt/venv/bin/python --no-cache-dir -e . --no-deps --no-build-isolation

# Drop root for the recognition serving process too (SEC-13 / wave3).
# WHY same model as runtime-vlm: boot chain (alembic → schema sync → uvicorn)
# needs Postgres plus writes under /var/lib/acx-blobs (and hf_modules scratch
# if ever used). Weights on /data/cache stay :ro. PYTHONDONTWRITEBYTECODE=1
# avoids __pycache__ under /app. Do not re-introduce USER root here.
USER acx
