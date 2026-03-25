# Tool Selection — Mandatory Decision Tree

> This rule is enforced by `.github/hooks/terminal-guard.py`. Violations are blocked or flagged at the point of tool call.

**Run this decision tree EVERY time before calling `run_in_terminal`. No exceptions.**

Is the task one of these exact four categories?

- Running tests (`pytest`, `npm test`, `phpunit`, `vitest`, `playwright`)
- Running `make` targets
- `git commit` / `git push` / `git rebase` / `git cherry-pick` / `git worktree`
- `pyenv` commands

**YES** — Terminal is allowed. Pipe output: `| tail -n 40`. Never redirect with `>` AND `2>&1` in the same command.

**TEST RUNS (MANDATORY):** Always use `tee /tmp/<suite>.txt` then `read_file`. Never rely on terminal output alone:

- Python: `cd <app-dir> && pyenv exec python -m pytest <path> -q 2>&1 | tee /tmp/pytest_<suite>.txt`
- Vitest: `cd <app-dir> && npx vitest run <path> 2>&1 | tee /tmp/vitest_<suite>.txt`
- PHP: `cd <app-dir> && vendor/bin/phpunit <path> 2>&1 | tee /tmp/phpunit_<suite>.txt`
- Then: `read_file("/tmp/pytest_<suite>.txt")`. Never `cat` in terminal.
- Background terminals lack pyenv; only use the foreground terminal for Python tests.

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
