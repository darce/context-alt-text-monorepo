#!/usr/bin/env bash
# Sync topology for the currently receipted release. No mutable-tag compose up.
# First installations use recognition-service.sh deploy <env> instead.
# Usage: ENV=prod-auraface CONFIRM=PROD scripts/deploy/sync-compose.sh
set -euo pipefail
ENV="${ENV:?ENV must be set}"
case "$ENV" in
  dev | dev-fir | staging | prod | dev-auraface | staging-auraface | prod-auraface) ;;
  *)
    echo "ERROR: unknown ENV: $ENV" >&2
    exit 2
    ;;
esac
if [[ "$ENV" == prod || "$ENV" == prod-auraface ]]; then
  [[ "${CONFIRM:-}" == PROD ]] || {
    echo 'ERROR: production compose sync requires CONFIRM=PROD' >&2
    exit 2
  }
fi
# Alternate SOURCE files bypass the pinned source contract. Use a reviewed ref.
if [[ -n "${SOURCE:-}" || -n "${ADMIN_SOURCE:-}" ]]; then
  echo 'ERROR: custom compose sources are refused; use GIT_REF=<reviewed-commit>' >&2
  exit 2
fi
export CONFIRM=PROMOTE
export OCI_HOST="${OCI_HOST:-129.213.40.111}" OCI_USER="${OCI_USER:-ubuntu}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec bash "$SCRIPT_DIR/recognition-service.sh" sync-runtime "$ENV"
