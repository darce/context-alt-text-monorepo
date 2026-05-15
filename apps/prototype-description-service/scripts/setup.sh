#!/usr/bin/env bash
# Unified setup script for prototype-description-service.
# Handles platform-specific dependencies (macOS Apple Silicon vs Linux).
#
# Usage:
#   ./scripts/setup.sh           # Install all dependencies including face detection
#   ./scripts/setup.sh --no-face # Skip face detection dependencies

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
UV_BIN="${UV_BIN:-uv}"
PROJECT_VENV_PYTHON="${PROJECT_ROOT}/.venv/bin/python"

# Parse arguments
INSTALL_FACE=1
for arg in "$@"; do
  case $arg in
    --no-face)
      INSTALL_FACE=0
      shift
      ;;
  esac
done

echo "[setup] Syncing locked core dependencies via uv.lock..."
cd "${PROJECT_ROOT}"
VIRTUAL_ENV= "${UV_BIN}" sync --locked --extra dev

if [[ "${INSTALL_FACE}" -eq 1 ]]; then
  echo "[setup] Installing face detection dependencies..."
  
  if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
    echo "[setup] Detected macOS Apple Silicon - using specialized install script..."
    PYTHON_BIN="${PROJECT_VENV_PYTHON}" "${SCRIPT_DIR}/install_insightface_mac.sh"
  else
    echo "[setup] Syncing locked InsightFace dependencies..."
    VIRTUAL_ENV= "${UV_BIN}" sync --locked --extra dev --extra face
  fi
else
  echo "[setup] Skipping face detection dependencies (--no-face specified)"
fi

echo ""
echo "✓ Setup complete!"
echo ""
echo "Next steps:"
echo "  make serve   # Start development server"
echo "  make check   # Run linting, type checking, and tests"
