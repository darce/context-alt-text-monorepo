#!/bin/sh
# Shared boot chain for runtime and runtime-vlm (ORCH-LAUNCH-01-S1-BR-02 / RA-08).
# Order is load-bearing: migrate, sync schema, verify schema, then (vlm only)
# verify the pre-seeded model cache, then hand off to uvicorn as PID 1.
#
# ACX_IMAGE_VARIANT string values must match ImageVariant in
# scripts/verify_vlm_cache.py (recognition | vlm). Shell cannot import that
# module before the venv is on PATH; keep the comparison literals in lockstep.
set -eu
cd /app
alembic -c db/alembic.ini upgrade head
python -m scripts.sync_identity_schema
python -m scripts.verify_identity_schema
# VLM image only: recognition must not grow a VLM weight-mount boot dependency.
if [ "${ACX_IMAGE_VARIANT:-recognition}" = "vlm" ]; then
	python -m scripts.verify_vlm_cache
fi
exec uvicorn api.main:app --host 0.0.0.0 --port 8000
