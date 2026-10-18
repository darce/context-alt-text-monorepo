<!-- lint-dashboard-txt: allow -->
# Why does `DASHBOARD.md` keep appearing when the correct file is `DASHBOARD.txt`?

> **Metadata**
>
> - **Date**: 2026-04-16
> - **Author**: Claude Opus 4 (1M context)
> - **Status**: Investigation (diagnosis only; fix proposed, not applied)
> - **Trigger**: User asked *"why is @DASHBOARD.md still being rendered when the correct file must be @DASHBOARD.txt — does the mcp binary need to be updated or perhaps a hook is missing or incorrect guidance?"*
> - **Scope**: monorepo root `/Users/daniel/Development/context-alt-text-monorepo`, HEAD `d221e98f`.

## TL;DR

The MCP binary is **correct**: every production code path writes `DASHBOARD.txt` (default set in `packages/agent-handoff-mcp/src/agent_handoff_mcp/config.py:105`). No hook writes `DASHBOARD.md`.

The symptom is **stale guidance** — a post-AHMCP-23 cleanup that never completed. Twelve active-surface docs, the Makefile docstring, one production Python docstring, and the public API name `generate_dashboard_md` all still say "DASHBOARD.md". Agents that generate dashboard copies by reading the docs emit the wrong filename; operators that `cat DASHBOARD.md` find either a stale pre-AHMCP-23 artifact or nothing.

Not a hook bug. Not a binary bug. Incomplete rename rollout.

## Symptoms collected

1. **Initial session git status** showed `?? DASHBOARD.md` as an untracked file in the repo root. After subsequent `make task-finish` + `generate_dashboard_md()` calls in this session, the `.md` file was gone and only `DASHBOARD.txt` remained:

   ```
   -rw-r--r-- 1 daniel staff 23933 Apr 16 16:26 DASHBOARD.txt
   ```

2. **Git history** shows `DASHBOARD.md` was tracked and then deleted in commit `dfe58be0` (2026-04-11) as part of the AHMCP-23 observatory dashboard split. A surviving `DASHBOARD.md` in the working tree is therefore a stale artifact from before that commit OR a later manual regeneration by a caller that hard-coded the `.md` suffix.

3. **Production code**: every writer targets `.txt`.
   ```
   packages/agent-handoff-mcp/src/agent_handoff_mcp/config.py:105
       else resolved_workspace_root / "DASHBOARD.txt"
   ```
   `generate_dashboard_md(write_file=True)` writes to `cfg.dashboard_path`, which defaults to the line above unless `AGENT_HANDOFF_DASHBOARD_PATH` is set (it is not set in `.mcp.json` or the shell env).

4. **Hooks do not write dashboards directly.** No `PreToolUse` / `PostToolUse` hook in `.claude/settings.json` or `.github/hooks/terminal-guard.json` touches the dashboard file; `regenerate-task-views.sh` delegates to the CLI's `write-dashboard` subcommand, which funnels through `config.py:105`.

## Hypotheses, tested

### H1 (refuted): The binary writes `.md` by default.

Refuted. `config.py:105` is `DASHBOARD.txt`. A single dry-run confirms:

```
$ agent-handoff-mcp --workspace-root "$(pwd)" write-dashboard
# produces DASHBOARD.txt, 23K bytes
```

### H2 (refuted): A hook forces `.md`.

Refuted. `grep -rn DASHBOARD .claude/settings.json .github/hooks/terminal-guard.json scripts/hooks` returns zero hook matches.

### H3 (refuted): An env override (`AGENT_HANDOFF_DASHBOARD_PATH`) redirects to `.md`.

Refuted. `.mcp.json` env block only sets `AGENT_HANDOFF_ENFORCE_BRANCH=1`. No shell env override.

### H4 (refuted): A hard-coded literal `"DASHBOARD.md"` write path in production code.

Refuted. `grep -rnE '"DASHBOARD\.md"' packages scripts --include="*.py" --include="*.sh"` returns zero production hits. The only `.md` literals are in **tests** (intentional per-test fixture paths) and in one production **docstring** (`packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/dashboard_extension.py:1-4`) that narrates the extension concept.

### H5 (confirmed): Guidance refers to `DASHBOARD.md` and agents/operators act on the stale guidance.

Confirmed. Eighteen files in active surfaces reference `DASHBOARD.md`:

| File | Nature of reference |
|---|---|
| `CLAUDE.md` | — none remaining (verified clean post-E17-6) |
| `Makefile:581` | target comment "Generate DASHBOARD.md — the human-scoped observatory view" |
| `.claude/commands/handoff-lifecycle.md` | slash-command help text |
| `.claude/skills/branch-lifecycle/SKILL.md` | skill body references DASHBOARD.md |
| `.claude/skills/handoff-lifecycle/SKILL.md` | same |
| `config/agent-workflows/portable_commands.json` | workflow manifest body text |
| `docs/agentic/contracts/agent-handoff-mcp.md` | the CONTRACT — lines 9, 32, 34, 80, 88, 125, 428, 566, 568, 570 |
| `docs/agentic/instructions.md` | lines 107, 216, 347, 348, 369 |
| `docs/agentic/lifecycle-map.md` | line 45 — lifecycle summary row |
| `docs/agentic/playbooks/host-adapters/worktree-codex-playbook.md` | lines 80, 342, 924 |
| `docs/agentic/playbooks/worktree-orchestration-playbook.md` | line 79 |
| `docs/agentic/rules/development-workflow.md` | lines 215, 252, 548, 563 |
| `docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md` | epic narrative |
| `docs/tasks/17.0/E17-3-core-workflow-skills-task-plan.md` | archived plan (may be historical) |
| `docs/tasks/17.0/E17-5-dashboard-redesign-task-plan.md` | archived plan (AHMCP-25 work) |
| `packages/agent-handoff-mcp/docs/tasks/AHMCP-23-observatory-dashboard-split-task-plan.md` | archived plan |
| `packages/agent-handoff-mcp/docs/tasks/AHMCP-25-dashboard-current-task-split-task-plan.md` | archived plan |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/dashboard_extension.py:1-4` | production docstring |
| `.task-state/exports/handoff-AHMCP-31.json` | snapshot export (frozen in time — leave it) |

Eighty individual `DASHBOARD.md` grep hits across those files (excluding tests, archives, `__pycache__`, `node_modules`, `.venv`).

Additionally, the public API name is a misnomer:

```python
def generate_dashboard_md(write_file: bool = True) -> dict:
    """Generate DASHBOARD.txt from the live handoff DB. ..."""
```

The `_md` suffix in the function name predates the AHMCP-23 switch. The first line of the docstring already says "DASHBOARD.txt", but every agent that reads the function *name* will assume the output filename ends in `.md`.

## Root cause

Incomplete rollout of AHMCP-23 ("observatory dashboard split", commit `dfe58be0`, 2026-04-11). The rename moved the on-disk artifact from `DASHBOARD.md` to `DASHBOARD.txt` and deleted the tracked `.md` copy, but:

- Contract docs, playbooks, Makefile comments, skill files, and epic narratives kept the old name.
- The public API function name (`generate_dashboard_md`) kept the old suffix.
- Archived task plans (AHMCP-23, AHMCP-25, E17-5) describe the pre-split world.
- No lint target catches drift between documented filenames and `config.py:105`.

Agents (including earlier sessions that spawned the `?? DASHBOARD.md` untracked file at session start) operate on whichever surface they read first. Some end up emitting a `DASHBOARD.md` alongside the authoritative `DASHBOARD.txt`; others `cat DASHBOARD.md` and get an empty read or a stale copy.

This matches the **config drift / regression** pattern in `branch-review-guide.md`: the contract was changed in one place but not mirrored consistently across the surfaces that drive future behaviour.

## Recommended fix (scope = docs + 1 docstring + 1 Makefile comment)

Do **not** touch the binary. It is correct.

1. **Rename all active-surface references** from `DASHBOARD.md` → `DASHBOARD.txt`:
   - `Makefile:581` target comment.
   - `docs/agentic/contracts/agent-handoff-mcp.md` (contract is load-bearing; update with care).
   - `docs/agentic/instructions.md`, `lifecycle-map.md`, `rules/development-workflow.md`.
   - `docs/agentic/playbooks/*.md`.
   - `.claude/skills/{branch-lifecycle,handoff-lifecycle}/SKILL.md`.
   - `.claude/commands/handoff-lifecycle.md`.
   - `config/agent-workflows/portable_commands.json` — plus regenerate adapters via `make generate-agent-workflows`.
   - `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/dashboard_extension.py` docstring.
2. **Leave archived task plans alone** (AHMCP-23, AHMCP-25, E17-5). They describe history; rewriting them would rewrite the record.
3. **Leave tests alone.** Test fixtures use `DASHBOARD.md` by design — they construct a `RuntimeConfig` with an explicit `dashboard_path`, which is the supported override path.
4. **Do NOT rename the public function** `generate_dashboard_md`. That is an API break affecting every script that imports it. Instead, update its docstring's first line to state the output filename prominently. Consider a follow-up to add an alias `generate_dashboard` in a future minor version.
5. **Add a lint check**: `make check-docs-dashboard-name` (or fold into `lint-task-plans`) — `grep -rn DASHBOARD.md` across tracked non-archive markdown and fail CI if any hit is found. This is the regression guard that would have caught the original incomplete rename.
6. **Delete stray `DASHBOARD.md`** from the working tree if it reappears. A `.gitignore` entry for `DASHBOARD.md` would stop it from showing up as an untracked file and would keep future accidental writers from getting promoted into a commit.

## Answer to the posed questions

| Sub-question | Answer |
|---|---|
| Does the MCP binary need to be updated? | **No.** It writes `DASHBOARD.txt` correctly. |
| Is a hook missing or incorrect? | **No.** No hook touches the dashboard file directly. |
| Is guidance incorrect? | **Yes.** Eighteen active-surface files still say `DASHBOARD.md`. Agents and operators acting on the stale guidance are the source of every "`DASHBOARD.md` appeared" report. |

The fix is a mechanical rename + one regression-guarding lint step. No behavior change required in the handoff server.

## References

- `packages/agent-handoff-mcp/src/agent_handoff_mcp/config.py:102-105` — dashboard_path default.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/dashboard_rendering.py:510-582` — `generate_dashboard_md()` implementation.
- Commit `dfe58be0` (2026-04-11) — AHMCP-23 rename landing.
- `docs/agentic/contracts/agent-handoff-mcp.md` — contract (load-bearing, highest-priority to update).
