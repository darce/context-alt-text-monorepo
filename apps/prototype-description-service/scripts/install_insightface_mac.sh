#!/usr/bin/env bash
# Install InsightFace on macOS Apple Silicon with correct SDK paths.
# onnxruntime is installed via pyproject.toml dependencies.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"

# Extract insightface version from pyproject.toml (e.g., "insightface>=0.7.3,<1.0.0" -> "insightface>=0.7.3")
INSIGHTFACE_SPEC="${INSIGHTFACE_SPEC:-$(grep -o '"insightface[^"]*"' "${PROJECT_ROOT}/pyproject.toml" | head -1 | tr -d '"' | sed 's/,<.*//')}"

if [[ $(uname -s) != "Darwin" || $(uname -m) != "arm64" ]]; then
  echo "[install-insightface] Apple Silicon macOS not detected; skipping specialized build." >&2
  echo "[install-insightface] Run '${PYTHON_BIN} -m pip install ${INSIGHTFACE_SPEC}' directly instead." >&2
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

echo "[install-insightface] Installing ${INSIGHTFACE_SPEC} with SDK flags..." >&2
env \
  SDKROOT="${SDKROOT}" \
  CFLAGS="${EXTRA_CFLAGS} ${CFLAGS:-}" \
  CXXFLAGS="${EXTRA_CXXFLAGS} ${CXXFLAGS:-}" \
  LDFLAGS="${EXTRA_LDFLAGS} ${LDFLAGS:-}" \
  "${PYTHON_BIN}" -m pip install --no-cache-dir "${INSIGHTFACE_SPEC}"

echo "[install-insightface] InsightFace installation complete." >&2
