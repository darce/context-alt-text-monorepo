# Tool Selection — Mandatory Decision Tree

> This rule is enforced by `.github/hooks/terminal-guard.py`. Violations are blocked or flagged at the point of tool call.

**Run this decision tree EVERY time before calling `run_in_terminal`. No exceptions.**

Is the task one of these exact four categories?

- Running tests (`pytest`, `npm test`, `phpunit`, `vitest`, `playwright`)
- Running `make` targets
- `git commit` / `git push` / `git rebase` / `git cherry-pick` / `git worktree`
- `pyenv` commands

**YES** — Terminal is allowed. Pipe output: `| tail -n 40`. Never redirect with `>` AND `2>&1` in the same command.

**NO** — Stop. Use the native tool:

| Task | Native tool | NEVER use terminal |
|------|-----------|--------------------|
| Read file contents | `read_file` | `cat`, `sed -n`, `head`, `tail` |
| Search / grep code | `grep_search` or `search_subagent` | `grep -rn`, `rg` |
| List changed files or diffs | `get_changed_files` | `git diff`, `git status` |
| Lint / type-check errors | `get_errors` | `npm run lint`, `mypy`, `phpstan`, `eslint` |
| Explore multiple files | `Explore` subagent | chained terminal reads |

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
