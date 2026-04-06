#!/usr/bin/env bash
# PreToolUse hook: blocks code-file edits on the main branch.
#
# Receives tool invocation as JSON on stdin (Claude Code hook protocol).
# Exit 0 = allow, Exit 2 = block (stderr shown to agent as reason).
#
# Policy: docs, configs, and planning artifacts may be edited on main.
#         Code files under apps/ and packages/ require a feature branch.

set -euo pipefail

INPUT=$(cat)

# Extract file_path from the hook payload.
FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('file_path', ''))
except Exception:
    print('')
" 2>/dev/null || echo "")

# No file path means this isn't a file-edit invocation — allow.
if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Determine current branch.
BRANCH=$(git branch --show-current 2>/dev/null || echo "")

if [ "$BRANCH" != "main" ] && [ "$BRANCH" != "master" ]; then
  exit 0
fi

# Convert absolute path to repo-relative.
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
if [ -n "$REPO_ROOT" ] && [[ "$FILE_PATH" == "$REPO_ROOT"/* ]]; then
  REL_PATH="${FILE_PATH#"$REPO_ROOT"/}"
else
  REL_PATH="$FILE_PATH"
fi

# Block code files under apps/ or packages/ on main.
# Allow: docs, configs, Makefiles, markdown, templates, settings, etc.
if [[ "$REL_PATH" =~ \.(py|ts|tsx|js|jsx|php|sql|sh|css|scss)$ ]] && [[ "$REL_PATH" =~ ^(apps/|packages/) ]]; then
  cat >&2 <<EOF
BLOCKED: Code file edits are not allowed on the main branch.

  Branch: $BRANCH
  File:   $REL_PATH

Create a feature branch first:
  git checkout -b feature/<task-id>-<slug>

Or use worktree isolation for agent work:
  Use the Agent tool with isolation: "worktree"

See: docs/agentic/rules/development-workflow.md § Branch Isolation Protocol
EOF
  exit 2
fi

exit 0
