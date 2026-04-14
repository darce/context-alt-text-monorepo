#!/usr/bin/env bash
set +e

WORKSPACE_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
HOOK_PAYLOAD="$(cat)"

if ! SHOULD_RUN="$(
  HOOK_PAYLOAD="$HOOK_PAYLOAD" python3 - <<'PY'
import json
import os

payload_raw = os.environ.get("HOOK_PAYLOAD", "")
try:
    payload = json.loads(payload_raw) if payload_raw else {}
except json.JSONDecodeError:
    print("true")
    raise SystemExit(0)

tool_name = payload.get("tool_name") or payload.get("toolName") or ""
tool_input = payload.get("tool_input") or payload.get("toolInput") or {}

if "record_event" in tool_name:
    print("true")
elif "review_findings" in tool_name:
    operation = (tool_input.get("review") or {}).get("operation")
    print("true" if operation not in {"list", "get"} else "false")
elif "review_runs" in tool_name:
    operation = (tool_input.get("review") or {}).get("operation")
    print("true" if operation not in {"list", "coverage"} else "false")
else:
    print("false")
PY
)"; then
  SHOULD_RUN="true"
fi

if [ "$SHOULD_RUN" != "true" ]; then
  exit 0
fi

agent-handoff-mcp --workspace-root "$WORKSPACE_ROOT" task >/dev/null 2>&1 || true
agent-handoff-mcp --workspace-root "$WORKSPACE_ROOT" dashboard >/dev/null 2>&1 || true

exit 0
