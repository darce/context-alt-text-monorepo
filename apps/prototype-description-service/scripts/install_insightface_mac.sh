#!/usr/bin/env bash
# Face-pipeline era local model provisioning (FIR-4 S5).
#
# Default: fetch + hash-verify YuNet/SFace ONNX into face_pipeline/models/
# (core deps only — insightface is NOT required for the face_pipeline profile).
#
# --bench: install InsightFace for FIR-5 bake-off legs / incumbent dark-default
# local work. On macOS Apple Silicon this uses SDK-aware compile flags; elsewhere
# prefer `uv sync --locked --extra bench`.
#
# Historical note: this script previously only installed insightface. The old
# install path is preserved under --bench so bake-off knowledge stays reachable.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_PROJECT_PYTHON="${PROJECT_ROOT}/.venv/bin/python"
if [[ -x "${DEFAULT_PROJECT_PYTHON}" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-${DEFAULT_PROJECT_PYTHON}}"
else
  PYTHON_BIN="${PYTHON_BIN:-python}"
fi

INSTALL_BENCH=0
for arg in "$@"; do
  case $arg in
    --bench)
      INSTALL_BENCH=1
      ;;
    -h|--help)
      cat <<'EOF'
Usage: install_insightface_mac.sh [--bench]

  (default)  Fetch/verify face_pipeline ONNX models via
             scripts/fetch_face_pipeline_models.py
  --bench    Install insightface (FIR-5 bake-off / incumbent local).
             On macOS arm64 uses SDK-aware build flags; otherwise prints
             the uv sync --extra bench command.
EOF
      exit 0
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Default: face_pipeline models (no insightface)
# ---------------------------------------------------------------------------
if [[ "${INSTALL_BENCH}" -eq 0 ]]; then
  echo "[face-pipeline] Fetching YuNet + SFace models (hash-verified)..." >&2
  echo "[face-pipeline] insightface / [bench] is only needed for FIR-5 bake-off" >&2
  echo "[face-pipeline] legs or local incumbent profile work — re-run with --bench." >&2
  cd "${PROJECT_ROOT}"
  if command -v uv >/dev/null 2>&1; then
    uv run python "${SCRIPT_DIR}/fetch_face_pipeline_models.py"
  else
    "${PYTHON_BIN}" "${SCRIPT_DIR}/fetch_face_pipeline_models.py"
  fi
  echo "[face-pipeline] Models ready. Verify later with:" >&2
  echo "  uv run python scripts/fetch_face_pipeline_models.py --verify-only" >&2
  exit 0
fi

# ---------------------------------------------------------------------------
# --bench: InsightFace install (FIR-5 bake-off / incumbent local)
# ---------------------------------------------------------------------------
# Extract the full insightface spec from pyproject.toml, keeping the upper
# bound (e.g. "insightface>=0.7.3,<1.0.0"): uv.lock and the deployed service
# pin 0.7.x, so stripping it would install an unvetted 1.x build.
INSIGHTFACE_SPEC="${INSIGHTFACE_SPEC:-$(grep -o '"insightface[^"]*"' "${PROJECT_ROOT}/pyproject.toml" | head -1 | tr -d '"')}"

if [[ $(uname -s) != "Darwin" || $(uname -m) != "arm64" ]]; then
  echo "[install-insightface] Apple Silicon macOS not detected; skipping specialized build." >&2
  echo "[install-insightface] Run 'uv sync --locked --extra dev --extra bench' directly instead." >&2
  exit 0
fi

if ! command -v xcode-select >/dev/null 2>&1; then
  echo "Command Line Tools are required. Install them via 'xcode-select --install'." >&2
  exit 1
fi

if ! xcode-select -p >/dev/null 2>&1; then
  echo "xcode-select did not return a developer directory. Reinstall CLT with 'xcode-select --install'." >&2
  exit 1
fi

SDKROOT="$(xcrun --sdk macosx --show-sdk-path 2>/dev/null || true)"
if [[ -z "${SDKROOT}" || ! -d "${SDKROOT}" ]]; then
  echo "Unable to resolve the macOS SDK path. Ensure Command Line Tools are installed." >&2
  exit 1
fi

echo "[install-insightface] Using SDK at ${SDKROOT}" >&2

EXTRA_CFLAGS="-isysroot ${SDKROOT} -I${SDKROOT}/usr/include -I${SDKROOT}/usr/include/c++/v1"
EXTRA_CXXFLAGS="${EXTRA_CFLAGS} -stdlib=libc++"
EXTRA_LDFLAGS="-isysroot ${SDKROOT} -L${SDKROOT}/usr/lib"

# uv-managed venvs ship without pip; route through `uv pip` against the
# project python in that case so the install lands in the same environment.
if "${PYTHON_BIN}" -m pip --version >/dev/null 2>&1; then
  INSTALL_CMD=("${PYTHON_BIN}" -m pip install --no-cache-dir "${INSIGHTFACE_SPEC}")
elif command -v uv >/dev/null 2>&1; then
  INSTALL_CMD=(uv pip install --python "${PYTHON_BIN}" --no-cache "${INSIGHTFACE_SPEC}")
else
  echo "Neither pip (in ${PYTHON_BIN}) nor uv is available; cannot install InsightFace." >&2
  exit 1
fi

echo "[install-insightface] Installing ${INSIGHTFACE_SPEC} with SDK flags..." >&2
env \
  SDKROOT="${SDKROOT}" \
  CFLAGS="${EXTRA_CFLAGS} ${CFLAGS:-}" \
  CXXFLAGS="${EXTRA_CXXFLAGS} ${CXXFLAGS:-}" \
  LDFLAGS="${EXTRA_LDFLAGS} ${LDFLAGS:-}" \
  "${INSTALL_CMD[@]}"

echo "[install-insightface] InsightFace installation complete." >&2
echo "[install-insightface] Prefer locking via: uv sync --locked --extra bench" >&2
