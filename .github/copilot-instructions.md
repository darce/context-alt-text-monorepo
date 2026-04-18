# Tool Selection — Mandatory Decision Tree

> This rule is enforced by `.github/hooks/terminal-guard.py`. Violations are blocked or flagged at the point of tool call.

**Run this decision tree EVERY time before calling `run_in_terminal`. No exceptions.**

Is the task one of these exact four categories?

- Running tests (`pytest`, `npm test`, `phpunit`, `vitest`, `playwright`)
- Running `make` targets
- `git commit` / `git push` / `git rebase` / `git cherry-pick` / `git worktree`
- `pyenv` commands

**YES** — Terminal is allowed. Prefer direct, focused test runs. Use `| tail -n 40` only when the command is noisy.

**TEST RUNS (MANDATORY):** Run the narrowest direct test command that proves the change. Do not use `tee`; it can freeze the integrated terminal in this workspace.

- Python: `cd <app-dir> && pyenv exec python -m pytest <path> -q`
- Vitest: `cd <app-dir> && npx vitest run <path>`
- PHP: `cd <app-dir> && vendor/bin/phpunit <path>`
- If a test run needs captured output, redirect once to `/tmp/<suite>.txt` with `> /tmp/<suite>.txt 2>&1`, then inspect it with `read_file`. Never `cat` the file in terminal.
- Background terminals lack pyenv; only use the foreground terminal for Python tests.
- Never hardcode user-local absolute filesystem paths such as `/Users/...` in commands, docs, or settings. Use environment variables such as `${env:HOME}`, `${workspaceFolder}`, `${PYENV_ROOT:-$HOME/.pyenv}`, and `${REPO_ROOT:-$PWD}` instead.
- For `packages/agent-handoff-mcp` and `packages/agent-orchestrator-mcp`, do not invoke IDE Python environment-configuration tools. Use the foreground terminal with `PYENV_VERSION=description-service`, `pyenv exec python`, or `${PYENV_ROOT:-$HOME/.pyenv}/versions/description-service/bin/python`. If the harness stalls at `Configuring a Python Environment` or `Preparing`, stop retrying and ask the user to run the terminal command directly.

**NO** — Stop. Use the native tool:

| Task                        | Native tool                        | NEVER use terminal                          |
| --------------------------- | ---------------------------------- | ------------------------------------------- |
| Read file contents          | `read_file`                        | `cat`, `sed -n`, `head`, `tail`             |
| Search / grep code          | `grep_search` or `search_subagent` | `grep -rn`, `rg`                            |
| List changed files or diffs | `get_changed_files`                | `git diff`, `git status`                    |
| Lint / type-check errors    | `get_errors`                       | `npm run lint`, `mypy`, `phpstan`, `eslint` |
| Explore multiple files      | `Explore` subagent                 | chained terminal reads                      |

Terminal output is **stale**. Native tools read live IDE state and never accumulate scrollback. When in doubt, use the native tool.

## Branch Isolation — Mandatory

Code files under `apps/` or `packages/` must not be edited on `main`.

- Enforced in the VS Code harness by `.github/hooks/guard-main-branch.py` via `.github/hooks/terminal-guard.json`
- Enforced in the Claude harness by `scripts/hooks/guard-main-branch.sh` via `.claude/settings.json`
- Allowed on `main`: only explicitly permitted operator docs, settings, Makefiles, and other non-planning config surfaces; planning docs require a task branch from the first edit

If you inherit dirty code changes on `main`, move them to a feature branch or stash them before starting new implementation work.

Before editing code, use one of these isolation tiers:

1. `git checkout -b feature/<task-id>-<slug>` for single-agent work
2. Worktree isolation for delegated subtasks
3. Lane orchestration for multi-agent parallel work

---

# Agent Cold-Start Orientation

On every session start, context switch, or worktree change:

1. Run `make context` to verify your shell is in the correct worktree on the correct branch.
2. Query MCP state: `get_handoff_state(sections="identity")` to learn the active task, target branch, and target worktree path.
3. If the active task has a `target_worktree_path`, `cd` to it before doing any work.
4. Check open findings: `review_findings(operation="list", status="open")`.

This protocol ensures you orient to the correct workspace state regardless of which agent set it up.

# MCP and Python API Fallback

`agent-handoff-mcp` is the primary state store for task state, decisions, findings, and review runs. `agent-orchestrator-mcp` extends it with lane management, worker control, and review dispatch. When MCP tool calls are available, use them directly. When they are unavailable (server not started, cold start, context switch), use the Python API as a fallback.

> **Canonical source:** [`docs/agentic/contracts/harness-protocol.yaml`](../docs/agentic/contracts/harness-protocol.yaml) `python_api_fallback.required_exports` is the authoritative list of package-root symbols every harness must keep importable. The example below is a practical subset used by VS Code/Copilot cold-start; the contract defines the minimum surface. If the two drift, fix the contract first, then re-sync both harness docs (CLAUDE.md and this file).

**Correct import pattern** — always import from the package root, never from submodules:

```python
from pathlib import Path
from agent_handoff_mcp import (
    RuntimeConfig,
    configure_runtime,
    get_handoff_state,
    search_handoff,
    record_event,
    review_findings,
    list_review_findings,
    get_verified_tests,
)

# Configure runtime FIRST — required before any read/write
configure_runtime(RuntimeConfig.for_repo(Path(".")))

# Then query state
state = get_handoff_state(sections="identity")
```

**Common mistakes to avoid:**

- `from agent_handoff_mcp.decisions import ...` — submodules are internal; use the top-level package
- `from agent_handoff_mcp.config import get_runtime_config` — `get_runtime_config` is re-exported from the package root
- `import sqlite3; conn.execute("SELECT ...")` — never query `handoff.db` directly; the schema is internal

**Running in monorepo without install:**

```bash
PYTHONPATH=packages/agent-handoff-mcp/src python3 -c "
from pathlib import Path
from agent_handoff_mcp import RuntimeConfig, configure_runtime, get_handoff_state
configure_runtime(RuntimeConfig.for_repo(Path('.')))
print(get_handoff_state(sections='identity'))
"
```

---

# Project Instructions

This is the `context-alt-text-monorepo`. Full agent instructions: `docs/agentic/instructions.md`.
Full role routing, testing guides, and domain rules are in `docs/agentic/rules/`.

Key conventions at a glance:

- PHP namespace `AltContext\`; prefix `acx_*` / `ACX_*`; REST namespace `acx/v1/`
- Design tokens `--acx-*` — no raw hex/px literals in CSS
- Greenfield project: no migrations, no backward-compat shims
- MCP handoff required before/after every coding slice (`agent-handoff-mcp`)
- `npm` for Node.js; `Composer` for PHP; `pyenv` for Python
