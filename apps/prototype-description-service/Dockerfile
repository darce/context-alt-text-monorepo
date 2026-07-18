# Multi-stage Dockerfile for prototype-description-service (ARM64, recognition-only)
# Build: docker build --platform linux/arm64 \
#          --build-arg GIT_COMMIT_SHA=$(git rev-parse HEAD) \
#          -t iad.ocir.io/idu2kqqe2jxy/acx-backend:latest .
# No VLM/torch — InsightFace + onnxruntime CPU only.
#
# Deps resolve from the checked-in uv.lock via `uv sync --frozen` (FIR4-BR-01).

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
# Stage 2: Runtime — slim image with only what's needed to run
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

# Install the app package itself (deps already present from frozen lock sync)
RUN pip install --no-cache-dir -e . --no-deps

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
