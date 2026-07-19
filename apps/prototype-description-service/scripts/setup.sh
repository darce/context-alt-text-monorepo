#!/usr/bin/env bash
# Unified setup script for prototype-description-service.
# Handles platform-specific dependencies (macOS Apple Silicon vs Linux).
#
# Usage:
#   ./scripts/setup.sh            # Core + face_pipeline model fetch
#   ./scripts/setup.sh --no-face  # Core only (skip model fetch)
#   ./scripts/setup.sh --bench    # Also install insightface ([bench] extra)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
UV_BIN="${UV_BIN:-uv}"
PROJECT_VENV_PYTHON="${PROJECT_ROOT}/.venv/bin/python"

# Parse arguments
INSTALL_FACE=1
INSTALL_BENCH=0
for arg in "$@"; do
  case $arg in
    --no-face)
      INSTALL_FACE=0
      ;;
    --bench)
      INSTALL_BENCH=1
      ;;
  esac
done

echo "[setup] Syncing locked core dependencies via uv.lock..."
cd "${PROJECT_ROOT}"
VIRTUAL_ENV= "${UV_BIN}" sync --locked --extra dev

if [[ "${INSTALL_BENCH}" -eq 1 ]]; then
  echo "[setup] Installing insightface via [bench] extra (FIR-5 bake-off / incumbent)..."
  if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
    PYTHON_BIN="${PROJECT_VENV_PYTHON}" "${SCRIPT_DIR}/install_insightface_mac.sh" --bench
  else
    VIRTUAL_ENV= "${UV_BIN}" sync --locked --extra dev --extra bench
  fi
fi

if [[ "${INSTALL_FACE}" -eq 1 ]]; then
  echo "[setup] Fetching face_pipeline ONNX models (YuNet + SFace)..."
  PYTHON_BIN="${PROJECT_VENV_PYTHON}" "${SCRIPT_DIR}/install_insightface_mac.sh"
else
  echo "[setup] Skipping face_pipeline model fetch (--no-face specified)"
fi

echo ""
echo "✓ Setup complete!"
echo ""
echo "Next steps:"
echo "  make serve   # Start development server"
echo "  make check   # Run linting, type checking, and tests"
echo "  # Dark face_pipeline profile: set RECOGNITION_FACE_PIPELINE_PROFILE=face_pipeline"
echo "  #   + PGVECTOR_DIM=128 (fresh DB; sole embedding-dimension root)."
echo "  # Incumbent / bake-off: ./scripts/setup.sh --bench"
