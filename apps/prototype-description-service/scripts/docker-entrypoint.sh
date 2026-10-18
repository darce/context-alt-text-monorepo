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

# PID-1 signal handling (REV-r08112960-A-13): the kernel ignores unhandled
# SIGTERM on PID 1, so docker stop during the pre-uvicorn window would wait for
# the stop timeout then SIGKILL mid-migrate. Install a handler and run long
# steps under &+wait so TERM can interrupt the chain.
_boot_child=""
_on_term() {
	if [ -n "${_boot_child}" ]; then
		kill -TERM "${_boot_child}" 2>/dev/null || true
		wait "${_boot_child}" 2>/dev/null || true
	fi
	echo "FATAL: SIGTERM during boot chain; aborting before uvicorn" >&2
	exit 143
}
trap '_on_term' TERM INT

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
# Prefer bake; export so child steps (and any ENV-stripped runtime) see the
# authoritative variant even if image ENV ACX_IMAGE_VARIANT is absent.
export ACX_IMAGE_VARIANT="${BAKED_IMAGE_VARIANT}"

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

# Long steps: background + wait so the TERM trap can kill them (A-13).
# Line prefixes stay as the bare command so packaging gates that key on
# alembic / python module lines still match.
alembic -c db/alembic.ini upgrade head &
_boot_child=$!
wait "${_boot_child}" || exit $?
_boot_child=""

python -m scripts.sync_identity_schema &
_boot_child=$!
wait "${_boot_child}" || exit $?
_boot_child=""

python -m scripts.verify_identity_schema &
_boot_child=$!
wait "${_boot_child}" || exit $?
_boot_child=""

# VLM image only (bake-driven via ACX_IMAGE_VARIANT above). The Python gate
# self-skips non-LOCAL_CPU profiles; recognition must not grow a weight-mount
# boot dependency. Packaging polarity tests require RHS = "vlm" (not inverted).
#
# Host bind of ACX_MODELS_PATH masks image-layer chown of /data/cache
# (REV-r08112960-A-08). When the mount exists but is unreadable by uid 10001,
# fail closed with an ownership hint instead of a bare library PermissionError.
# Missing path is left to verify_vlm_cache (seed/manifest errors).
if [ "${ACX_IMAGE_VARIANT:-recognition}" = "vlm" ] \
	&& [ -e /data/cache ] && [ ! -r /data/cache ]; then
	echo "FATAL: /data/cache exists but is not readable by uid $(id -u) ($(id -un 2>/dev/null || echo unknown))." >&2
	echo "Host ACX_MODELS_PATH bind-mount ownership wins over the image layer." >&2
	echo "Make the seeded cache readable by uid 10001, e.g.:" >&2
	echo "  sudo chown -R 10001:10001 \"\${ACX_MODELS_PATH}\"   # or: chmod -R a+rX \"\${ACX_MODELS_PATH}\"" >&2
	exit 1
fi
if [ "${ACX_IMAGE_VARIANT:-recognition}" = "vlm" ]; then
	python -m scripts.verify_vlm_cache &
	_boot_child=$!
	wait "${_boot_child}" || exit $?
	_boot_child=""
fi
# Clear boot trap before permanent handoff; uvicorn becomes PID 1 under exec.
trap - TERM INT
exec uvicorn api.main:app --host 0.0.0.0 --port 8000
