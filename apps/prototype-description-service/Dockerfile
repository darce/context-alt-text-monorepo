# Multi-stage Dockerfile for prototype-description-service (ARM64)
#
# Default target `runtime`: recognition-only image.
#   InsightFace + onnxruntime CPU; torch-free (no VLM extras).
# Optional target `runtime-vlm`: recognition + VLM/torch (Florence-2 path).
#   Installs locked `--extra bench --extra vlm` so ACX_DESCRIPTION_ADAPTER can
#   leave the seeded placeholder once weights are provisioned.
#
# Build recognition (default — production torch-free image):
#   docker build --platform linux/arm64 \
#     --build-arg GIT_COMMIT_SHA=$(git rev-parse HEAD) \
#     -t iad.ocir.io/idu2kqqe2jxy/acx-backend:latest .
# Build VLM-capable (explicit target; does not change the default image):
#   docker build --platform linux/arm64 --target runtime-vlm \
#     --build-arg GIT_COMMIT_SHA=$(git rev-parse HEAD) \
#     -t iad.ocir.io/idu2kqqe2jxy/acx-backend:vlm .
#
# Deps resolve from the checked-in uv.lock via `uv sync --frozen` (FIR4-BR-01).
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
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1
RUN uv venv /opt/venv \
    && uv sync --frozen --no-dev --extra bench --no-install-project

ENV PATH="/opt/venv/bin:$PATH"

# ---------------------------------------------------------------------------
# Stage 1b: Builder VLM — runtime+[bench]+[vlm] from the same frozen lock
# Separate stage so the default builder/runtime dependency set is unchanged.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder-vlm

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

COPY pyproject.toml uv.lock ./

# Same lock, same bench extra, plus vlm (torch/transformers/…). Both extras
# resolve only through `uv sync --frozen` — no unlocked pip dep install.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1
RUN uv venv /opt/venv \
    && uv sync --frozen --no-dev --extra bench --extra vlm --no-install-project

ENV PATH="/opt/venv/bin:$PATH"

# ---------------------------------------------------------------------------
# Stage 2: Runtime — slim image with only what's needed to run (recognition)
# Default final stage: torch-free.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Runtime libs needed by OpenCV, InsightFace, and onnxruntime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopenblas0 \
    liblapack3 \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy the virtualenv from the builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Rebind the top-level ARG inside this stage so ENV can consume it.
# Without this, GIT_COMMIT_SHA is out of scope in the runtime image.
ARG GIT_COMMIT_SHA=unknown
ENV APP_GIT_COMMIT_SHA=${GIT_COMMIT_SHA}

WORKDIR /app

# Copy application code
COPY api/ api/
COPY db/ db/
COPY recognition/ recognition/
COPY roster/ roster/
COPY scene/ scene/
COPY shared/ shared/
COPY scripts/ scripts/
COPY pyproject.toml .

# Install the app package into /opt/venv without resolving build/runtime deps.
# --no-deps: runtime deps come only from the frozen uv.lock sync above.
# --no-build-isolation: PEP 517 must not pull setuptools/etc. from the network
# outside the lock (FINALB-05 / DEP-01/02). Use the venv interpreter explicitly.
RUN /opt/venv/bin/pip install --no-cache-dir -e . --no-deps --no-build-isolation

# Default cache directory inside the container (mapped to a volume)
ENV CACHE_BASE=/data/cache
ENV HF_HOME=/data/cache/huggingface_cache
ENV HF_HUB_CACHE=/data/cache/huggingface_cache
ENV INSIGHTFACE_CACHE_DIR=/data/cache/insightface
ENV INSIGHTFACE_HOME=/data/cache/insightface

EXPOSE 8000

# Entrypoint: run Alembic migrations, verify the schema footprint, then start uvicorn.
# The POSTGRES_SYNC_DSN env var is used by Alembic (via db/migrations/env.py).
CMD ["sh", "-c", "cd /app && alembic -c db/alembic.ini upgrade head && python -m scripts.sync_identity_schema && python -m scripts.verify_identity_schema && uvicorn api.main:app --host 0.0.0.0 --port 8000"]

# ---------------------------------------------------------------------------
# Stage 2b: Runtime VLM — recognition path + torch/transformers (optional)
# Build with: docker build --target runtime-vlm ...
#
# Model-weight cache strategy (mount, not bake):
#   VLM weights (Florence-2 / HF hub) are served from a persistent volume at
#   /data/cache. Operators pre-populate HF_HOME before production start.
#   HF_HUB_OFFLINE=1 fails closed if weights are missing — no HuggingFace
#   download on the production boot path.
#   Tradeoff: larger operator ops surface (seed the volume once) vs smaller
#   image than baking multi-GB weights into a layer; boot stays network-free.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime-vlm

RUN apt-get update && apt-get install -y --no-install-recommends \
    libopenblas0 \
    liblapack3 \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder-vlm /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ARG GIT_COMMIT_SHA=unknown
ENV APP_GIT_COMMIT_SHA=${GIT_COMMIT_SHA}

WORKDIR /app

COPY api/ api/
COPY db/ db/
COPY recognition/ recognition/
COPY roster/ roster/
COPY scene/ scene/
COPY shared/ shared/
COPY scripts/ scripts/
COPY pyproject.toml .

RUN /opt/venv/bin/pip install --no-cache-dir -e . --no-deps --no-build-isolation

# Persistent cache volume for HF / InsightFace weights (pre-seeded by operators).
ENV CACHE_BASE=/data/cache
ENV HF_HOME=/data/cache/huggingface_cache
ENV HF_HUB_CACHE=/data/cache/huggingface_cache
ENV TRANSFORMERS_CACHE=/data/cache/huggingface_cache
ENV INSIGHTFACE_CACHE_DIR=/data/cache/insightface
ENV INSIGHTFACE_HOME=/data/cache/insightface
# Fail closed on missing weights — production must not fetch at start.
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1
VOLUME ["/data/cache"]

EXPOSE 8000

CMD ["sh", "-c", "cd /app && alembic -c db/alembic.ini upgrade head && python -m scripts.sync_identity_schema && python -m scripts.verify_identity_schema && uvicorn api.main:app --host 0.0.0.0 --port 8000"]
