#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MCP_HANDOFF_PACKAGE="${MCP_HANDOFF_PACKAGE:-mcp-agent-handoff==0.11.2}"

if command -v uvx >/dev/null 2>&1; then
	exec uvx --from "${MCP_HANDOFF_PACKAGE}" python3 "${REPO_ROOT}/scripts/handoff_review_run.py" "$@"
fi

exec python3 "${REPO_ROOT}/scripts/handoff_review_run.py" "$@"