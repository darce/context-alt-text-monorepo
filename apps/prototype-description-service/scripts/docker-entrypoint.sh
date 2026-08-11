#!/bin/sh
# Shared boot chain for runtime and runtime-vlm (ORCH-LAUNCH-01-S1-BR-02 / RA-08).
# Order is load-bearing: migrate, sync schema, verify schema, then (vlm only)
# verify the pre-seeded model cache, then hand off to uvicorn as PID 1.
#
# Image variant is build-immutable at /app/.image-variant (not ENV alone —
# compose env_file can override ACX_IMAGE_VARIANT and fail open). String values
# must match ImageVariant in scripts/verify_vlm_cache.py (recognition | vlm).
set -eu
cd /app

IMAGE_VARIANT_FILE=/app/.image-variant
if [ ! -f "${IMAGE_VARIANT_FILE}" ]; then
	echo "FATAL: missing baked image variant at ${IMAGE_VARIANT_FILE}" >&2
	exit 1
fi
BAKED_IMAGE_VARIANT=$(tr -d '[:space:]' < "${IMAGE_VARIANT_FILE}")
case "${BAKED_IMAGE_VARIANT}" in
recognition|vlm) ;;
*)
	echo "FATAL: invalid baked image variant '${BAKED_IMAGE_VARIANT}'" >&2
	exit 1
	;;
esac
# Fail closed when env claim disagrees with the bake (env_file override).
if [ -n "${ACX_IMAGE_VARIANT:-}" ] && [ "${ACX_IMAGE_VARIANT}" != "${BAKED_IMAGE_VARIANT}" ]; then
	echo "FATAL: ACX_IMAGE_VARIANT=${ACX_IMAGE_VARIANT} disagrees with baked ${BAKED_IMAGE_VARIANT} at ${IMAGE_VARIANT_FILE}" >&2
	exit 1
fi
# Prefer bake; keep ACX_IMAGE_VARIANT in the gate so packaging polarity tests
# still see the env-shaped compare (RHS must be vlm, not recognition). The
# compare is no longer env-mutable fail-open: bake overwrote the env above.
ACX_IMAGE_VARIANT="${BAKED_IMAGE_VARIANT}"

# Pre-privilege-drop stacks may still mount a root:root acx_blobs named volume
# (Docker never re-chowns existing volumes). Fail closed with the one-shot
# repair path rather than 500ing every multipart upload under USER acx.
BLOB_ROOT="${RECOGNITION_BLOB_ROOT:-/var/lib/acx-blobs}"
if [ ! -d "${BLOB_ROOT}" ]; then
	echo "FATAL: blob root ${BLOB_ROOT} does not exist" >&2
	exit 1
fi
if [ ! -w "${BLOB_ROOT}" ]; then
	echo "FATAL: blob root ${BLOB_ROOT} is not writable by uid $(id -u) ($(id -un 2>/dev/null || echo unknown))." >&2
	echo "Existing named volumes created as root stay root:root; Docker never re-chowns them." >&2
	echo "Remediate once per stack (compose profile repair):" >&2
	echo "  docker compose -f docker-compose.env.yml --profile repair run --rm fix-blob-ownership" >&2
	exit 1
fi

alembic -c db/alembic.ini upgrade head
python -m scripts.sync_identity_schema
python -m scripts.verify_identity_schema
# VLM image only (bake-driven via ACX_IMAGE_VARIANT above). The Python gate
# self-skips non-LOCAL_CPU profiles; recognition must not grow a weight-mount
# boot dependency. Packaging polarity tests require RHS = "vlm" (not inverted).
if [ "${ACX_IMAGE_VARIANT:-recognition}" = "vlm" ]; then
	python -m scripts.verify_vlm_cache
fi
exec uvicorn api.main:app --host 0.0.0.0 --port 8000
