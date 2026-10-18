# Tool Selection

VS Code hook loading is pinned in `.vscode/settings.json`: Copilot loads the single dispatcher hook in `.vscode/copilot-hooks.json` and does not load the Claude Code `.claude/settings*.json` hook files. This prevents Claude-only guards from appearing as extra VS Code hook approvals.

The dispatcher routes to the targeted Workbay guards only when the current tool call needs them: worktree drift, main-branch edits, task-plan findings placement, MCP payload shape, and compact test-output summaries. Use normal judgment and prefer native VS Code tools when they give fresher state.

**TEST RUNS:** Run the narrowest direct test command that proves the change. Do not use `tee`; it can freeze the integrated terminal in this workspace.

- Python: `cd <app-dir> && VIRTUAL_ENV= uv run --locked --extra dev python -m pytest <path> -q`
- Vitest in VS Code agent chat: `cd <app-dir> && npm run test:agent -- <path>`; inspect the output for failures because this wrapper intentionally returns control to chat even for RED tests. Use normal `npm run test -- <path>` only outside the agent chat workflow when the shell can safely propagate failing exit codes.
- PHP: `cd <app-dir> && vendor/bin/phpunit <path>`
- If a test run needs captured output, redirect once to `/tmp/<suite>.txt` with `> /tmp/<suite>.txt 2>&1`, then inspect it with `read_file`. Never `cat` the file in terminal.
- Use the foreground terminal for Python tests so the app's uv-managed environment is the one being exercised.
- Never hardcode user-local absolute filesystem paths such as `/Users/...` in commands, docs, or settings. Use environment variables such as `${env:HOME}`, `${workspaceFolder}`, and `${REPO_ROOT:-$PWD}` instead.
- For external MCP package verification and runtime flows, do not invoke IDE Python environment-configuration tools. Use the foreground terminal with `uvx --from "mcp-workbay-handoff==0.2.0" python3`, `uvx --from "mcp-workbay-orchestrator==0.2.0" python3`, or a scratch-venv binary such as `/tmp/<env>/bin/python`. If the harness stalls at `Configuring a Python Environment` or `Preparing`, stop retrying and ask the user to run the terminal command directly.

Prefer native tools when they fit. These rows are agent-conduct conventions enforced by review and judgment, not by the narrow raw-Vitest terminal hook:

| Task                        | Prefer                            | Avoid in routine VS Code use                |
| --------------------------- | --------------------------------- | ------------------------------------------- |
| Read file contents          | `read_file`                       | `cat`, `sed -n`, `head`, `tail`             |
| Search / grep code          | `grep_search` or `Explore`        | `grep -rn`, `rg`                            |
| List changed files or diffs | `get_changed_files`               | `git diff`, `git status`                    |
| Lint / type-check errors    | `get_errors`                      | `npm run lint`, `mypy`, `phpstan`, `eslint` |
| Explore multiple files      | `Explore` subagent                | chained terminal reads                      |

Terminal output is **stale**. Native tools read live IDE state and never accumulate scrollback. When in doubt, use the native tool.

## Branch Isolation — Mandatory

Code files under `apps/` or `packages/` must not be edited on `main`.

- Enforced in the VS Code harness by `.github/hooks/guard-main-branch.py` via `.vscode/copilot-hooks.json`
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

0. **Identify the task first.** Before `make context` or any MCP read that resolves the active task by cwd, decide which task owns this scope:
   - Existing feature-branch task → proceed to step 1 from inside the task's `target_worktree_path`.
   - Ad-hoc / new work on `main` (e.g. `/branch-review`, audits, patches) → run `set_handoff_state(task_ref="MAINT-<slug>-<YYYYMMDD>", objective="...", status="in_progress")` FIRST, then pass `task_ref` explicitly to subsequent reads. Do not rely on cwd-based resolution on `main` — two or more active main-branch tasks trigger `Ambiguous active task` errors.
   - `Ambiguous active task. Known task_refs: ...` on startup means step 0 was skipped: create/select the task_ref and pass it explicitly, or archive stale MAINT-* rows.
1. Run `make context` to verify your shell is in the correct worktree on the correct branch.
2. Query MCP state: `get_handoff_state(sections="identity")` to learn the active task, target branch, and target worktree path.
3. If the active task has a `target_worktree_path`, `cd` to it before doing any work.
4. Check open findings: `review_findings(operation="list", status="open")`.

This protocol ensures you orient to the correct workspace state regardless of which agent set it up.

# MCP and Python API Fallback

`workbay-handoff-mcp` is the primary state store for task state, decisions, findings, and review runs. `workbay-orchestrator-mcp` extends it with lane management, worker control, and review dispatch. When MCP tool calls are available, use them directly. When they are unavailable (server not started, cold start, context switch), use the Python API as a fallback.

For Python-API fallback writes (`record_event`, `review_findings`, `set_handoff_state`, `update_task_status`, `close_slice`), always run them from the owning worktree with an explicit `cd <target_worktree_path> && ...` prefix and pass `task_ref='<task-ref>'` in the write call. The provenance guard rejects fallback writes that omit the explicit worktree `cd` or the explicit task ref because the Bash tool path otherwise cannot validate branch/SHA attribution before the write lands.

> **Canonical source:** [`docs/workbay/contracts/harness-protocol.yaml`](../docs/workbay/contracts/harness-protocol.yaml) `python_api_fallback.required_exports` is the authoritative list of package-root symbols every harness must keep importable. The example below is a practical subset used by VS Code/Copilot cold-start; the contract defines the minimum surface. If the two drift, fix the contract first, then re-sync both harness docs (CLAUDE.md and this file).

**Correct import pattern** — always import from the package root, never from submodules:

```python
from pathlib import Path
from workbay_handoff_mcp import (
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

- `from workbay_handoff_mcp.decisions import ...` — submodules are internal; use the top-level package
- `from workbay_handoff_mcp.config import get_runtime_config` — `get_runtime_config` is re-exported from the package root
- `import sqlite3; conn.execute("SELECT ...")` — never query `handoff.db` directly; the schema is internal

**Running against the installed MCP package:**

```bash
uvx --from "mcp-workbay-handoff==0.2.0" python3 -c "
from pathlib import Path
from workbay_handoff_mcp import RuntimeConfig, configure_runtime, get_handoff_state
configure_runtime(RuntimeConfig.for_repo(Path('.')))
print(get_handoff_state(sections='identity'))
"
```

This fallback resolves the standalone `workbay-handoff-mcp` package through `uvx` without depending on an IDE-managed interpreter. Use a scratch venv instead when you need a persistent installed environment.

When the missing surface is specifically review-run writes, prefer the repo-local wrapper over ad-hoc snippets: `make handoff-review-run TASK_REF=<task-ref> MODE=<branch|planning|release_audit> SUBJECT=<path-or-.> SUBJECT_KIND=<task_plan|epic|branch|adr|roadmap|other> VERDICT=<pass|pass_with_findings|fail|conditional_pass> DECISION=<decision-id> SESSION=<session> RUN_ID=<run-id>`. The target records the review run through the Python API fallback and refreshes `DASHBOARD.txt` plus `CURRENT_TASK.json`.

---

# Project Instructions

This is the `context-alt-text-monorepo`. Full agent instructions: `docs/workbay/instructions.md`.
Full role routing, testing guides, and domain rules are in `docs/workbay/rules/`.

Key conventions at a glance:

- PHP namespace `AltContext\`; prefix `acx_*` / `ACX_*`; REST namespace `acx/v1/`
- Design tokens `--acx-*` — no raw hex/px literals in CSS
- Greenfield project: no migrations, no backward-compat shims
- MCP handoff required before/after every coding slice (`workbay-handoff-mcp`)
- `npm` for Node.js; `Composer` for PHP; `uv` for the backend Python app and `uvx` or scratch venvs for MCP/package verification
