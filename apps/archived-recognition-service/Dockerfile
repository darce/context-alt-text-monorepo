# syntax=docker/dockerfile:1
FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04 as base
#FROM nvidia/cuda:13.0.2-cudnn-devel-ubuntu24.04 as base

# Set environment variables for non-interactive apt-get
ENV DEBIAN_FRONTEND=noninteractive
ENV HOME="/data"
ENV CUDA_HOME=/usr/local/cuda
ENV PATH="${CUDA_HOME}/bin:${PATH}"
ENV LD_LIBRARY_PATH="${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}"
ENV ENABLE_REQUEST_TIMING=true

# Enable performance optimizations for HuggingFace Spaces
ENV HUGGINGFACE_SPACE=true
ENV ENV_MODE=production

# Model preloading configuration
# 
# Available modes:
#   1. SKIP_MODEL_PRELOAD=true - Skip all preloading (fastest build, slowest startup)
#   2. PRELOAD_FILES_ONLY=true - Download files only (medium build, medium startup)  
#   3. PRELOAD_CPU_WARMUP=true - Full CPU warmup (slower build, fastest startup)
#
# Memory requirements:
#   - Files only: ~2-4GB during build
#   - CPU warmup: ~8-12GB during build (auto-fallback if insufficient)
#
# Current settings: Skip all preloading, use Git LFS for YOLO, runtime download for Phi-3
ENV SKIP_MODEL_PRELOAD=true
ENV PRELOAD_CPU_WARMUP=false
ENV PRELOAD_FILES_ONLY=false

ENV CACHE_BASE=/data/cache
ENV CACHE_DIR=${CACHE_BASE}  \
    HOST=0.0.0.0  \
    PORT=7860

# Build-time environment variables for Huggingface cache
ENV HF_HOME=${CACHE_BASE}/huggingface_cache \
    TRANSFORMERS_CACHE=${CACHE_BASE}/huggingface_cache \
    HF_HUB_CACHE=${CACHE_BASE}/huggingface_cache \
    TORCH_HOME=${CACHE_BASE}/torch \
    YOLO_CONFIG_DIR=${CACHE_BASE}/yolo \
    MPLCONFIGDIR=${CACHE_BASE}/matplotlib \
    INSIGHTFACE_CACHE_DIR=${CACHE_BASE}/insightface \
    INSIGHTFACE_HOME=${CACHE_BASE}/insightface

# Update apt and install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    cmake \
    git \
    libgl1-mesa-glx \
    libsm6 \
    libxext6 \
    libfontconfig1 \
    libxrender1 \
    libglib2.0-0 \
    ffmpeg \
    wget \
    bc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    # Create a 'python' symlink to python3
    && ln -sf /usr/bin/python3 /usr/bin/python

# Set working directory
WORKDIR /code
ENV PYTHONPATH=/code

# Dependencies stage - optimize for Docker layer caching
FROM base as dependencies

# Copy only requirements files first for better caching
COPY requirements_main.txt requirements_remote_main.txt ./

# Install core packages, PyTorch, main dependencies, and onnxruntime in one layer
RUN pip install packaging && \
    pip install torch==2.7.1+cu128 \
        torchvision==0.22.1+cu128 \
        --extra-index-url https://download.pytorch.org/whl/cu128 && \
    pip install -r requirements_main.txt onnxruntime-gpu

# Create python symlink
RUN ln -sf /usr/bin/python3 /usr/bin/python

# Application stage - this rebuilds frequently, keep it lightweight
FROM dependencies as application

# Copy application code (changes frequently, so put it late)
COPY app.py ./
COPY shared/ shared/
COPY recognition_core/ recognition_core/
COPY analysis/ analysis/
COPY roster/ roster/
COPY api/ api/

# Create application data directories (don't copy existing data/ from repo)
RUN mkdir -p /code/data/media \
    && mkdir -p /code/data/backups \
    && mkdir -p /code/data/debug/face_crops

# Set permissions for Hugging Face Space container
RUN chmod -R a+r /code/shared/infrastructure \
    && chmod -R a+r /code/recognition_core \
    && chmod -R a+r /code/analysis \
    && chmod -R a+r /code/roster \
    && chmod -R a+r /code/api \
    && chmod -R a+r /code/shared/config \
    && chmod -R a+r /code/shared/utils

# Ensure data directory and model directories are writable
RUN chmod -R a+rwx /code/data \
    && chmod -R a+rwx /code/shared/infrastructure/models

# Production stage - optimize for size and performance
FROM application as production

# Fix cache directory permissions (needed for Hugging Face Spaces)
RUN chmod -R a+rwx ${HF_HOME} || true

# Expose the port
EXPOSE ${PORT}

# Log container start and launch timestamps, then start the app
ENTRYPOINT sh -c "echo '🚀 Container started at: $(date)'; echo '📅 Launching Entity Identifier API at: $(date)'; exec uvicorn app:app --host \${HOST:-0.0.0.0} --port \${PORT:-7860} --log-level info"
