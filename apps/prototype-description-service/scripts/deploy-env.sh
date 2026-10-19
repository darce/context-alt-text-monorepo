#!/usr/bin/env bash
# Install/update through the maintained source, digest, lease and recovery gates.
# First installation uses the same candidate admission as subsequent deployments.
set -euo pipefail
ENV="${1:?Usage: deploy-env.sh <env> [<ssh-target>]}"
case "$ENV" in
  dev | dev-fir | staging | prod | dev-auraface | staging-auraface | prod-auraface) ;;
  *)
    echo "ERROR: unknown deploy environment: $ENV" >&2
    exit 2
    ;;
esac
if [[ "$ENV" == prod || "$ENV" == prod-auraface ]]; then
  [[ "${CONFIRM:-}" == PROMOTE ]] || {
    echo 'ERROR: production installation requires CONFIRM=PROMOTE' >&2
    exit 2
  }
fi
if [[ -n "${2:-}" ]]; then
  target="$2"
  [[ "$target" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9_][A-Za-z0-9_.:-]*$ ]] || {
    echo 'ERROR: invalid SSH target (expected user@host)' >&2
    exit 2
  }
  export OCI_USER="${target%%@*}" OCI_HOST="${target#*@}"
fi
export OCI_HOST="${OCI_HOST:-129.213.40.111}" OCI_USER="${OCI_USER:-ubuntu}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
exec bash "$REPO_ROOT/scripts/deploy/recognition-service.sh" deploy "$ENV"
