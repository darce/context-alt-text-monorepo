#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
INSIGHTFACE_SPEC="${INSIGHTFACE_SPEC:-insightface==0.7.3}"

if [[ $(uname -s) != "Darwin" || $(uname -m) != "arm64" ]]; then
  echo "[install_insightface_mac] Apple Silicon macOS not detected; skipping specialised build." >&2
  echo "[install_insightface_mac] Run '${PYTHON_BIN} -m pip install ${INSIGHTFACE_SPEC}' directly instead." >&2
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

echo "[install_insightface_mac] Using SDK at ${SDKROOT}" >&2

EXTRA_CFLAGS="-isysroot ${SDKROOT} -I${SDKROOT}/usr/include -I${SDKROOT}/usr/include/c++/v1"
EXTRA_CXXFLAGS="${EXTRA_CFLAGS} -stdlib=libc++"
EXTRA_LDFLAGS="-isysroot ${SDKROOT} -L${SDKROOT}/usr/lib"

env \
  SDKROOT="${SDKROOT}" \
  CFLAGS="${EXTRA_CFLAGS} ${CFLAGS:-}" \
  CXXFLAGS="${EXTRA_CXXFLAGS} ${CXXFLAGS:-}" \
  LDFLAGS="${EXTRA_LDFLAGS} ${LDFLAGS:-}" \
  "${PYTHON_BIN}" -m pip install --no-cache-dir "${INSIGHTFACE_SPEC}"

echo "[install_insightface_mac] insightface installation complete." >&2
