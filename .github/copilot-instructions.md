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
