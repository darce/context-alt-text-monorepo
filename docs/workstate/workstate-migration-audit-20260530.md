# Workstate migration — hooks & skills audit (Stage 4 gate)

Task: `MAINT-workstate-migration-20260530`. Branch `feature/maint-workstate-migration-20260530`.
Canonical compared at `agentic-protocol-monorepo` v0.1.20 (`packages/workstate-system`).
Consumer overlay was pinned to stale `remote_sha e057c18`.

## Skills

| Consumer `.claude/skills/*` | Canonical equiv | Repo-specific content? | Disposition |
|---|---|---|---|
| auto-fix, branch-lifecycle, branch-review, handoff-lifecycle, incremental-implementation, plan-analyze, planning-review, review-parallel, scope, tdd | yes (all) | **none** (frontmatter byte-identical, no WP/PHP/alt-text refs) | **adopt canonical**, delete vendored copy + `.codex/skills` symlinks |

**Newly delivered by canonical (12, currently missing here):** `investigate`, `refactor`,
`spec`, `security-audit`, `review`, `commit2git`, `daemon-lifecycle`, `document-sync`,
`rescue-lane`, `subfeature-committer`, `worktree-orchestrator`, `worktree-worker`.
→ **adopt all** (this is what delivers `/investigate`). No `replace` overrides needed (no
repo-specific skill content exists).

**Obsolete vendored tooling → delete:** `scripts/generate_agent_workflows.py`,
`config/agent-workflows/portable_commands.json`, vendored `.claude/skills/*`, `.codex/skills`
symlinks. Canonical ships skills via the generated plugin tree, not these.

## Hooks (`scripts/hooks/` + `.github/hooks/`)

- **~30 files marked MODIFIED vs canonical = stale drift** (old pin), not intentional
  repo-specifics — they are workstate harness hooks, not alt-text-app hooks. → **adopt canonical**
  by letting the symlinked shared surface win. (IDENTICAL files trivially adopt too.)
- **Canonical-only (consumer missing) → gained on adopt:** `_active_task_context.py`,
  `_protocol.py`, `advise-worktree-cd.py`, `check_branch_naming.py`, `compact-session.py`,
  `terminal-guard.py`, plus ~12 newer tests.
- **Consumer-only (not in canonical):**
  - `scripts/hooks/guard-handoff-provenance.py` (+ `test_guard_handoff_provenance.py`) — wired in
    `.claude/settings.json` + `.codex/hooks.json`. **No canonical equivalent.** → DECISION A.
  - `.github/hooks/test_terminal_guard.py` — **dangling/broken** (imports the moved
    `terminal-guard.py`). Canonical ships its own `test_terminal_guard.py` under `scripts/hooks`.
    → **delete** (obsolete).

## Delivery model confirmed
- Bootstrap symlinks `scripts/hooks` + `.github/hooks` (+ Makefile.d, docs/workstate, scripts/workstate)
  from the pinned canonical clone — **whole-directory**, no per-file hook override.
- Canonical wires PreToolUse/PostToolUse guards via `.github/hooks/terminal-guard.json` (VS Code/
  Codex manifest) using the **new `mcp__workstate-handoff-mcp__*` matchers**, and *does* wire
  `terminal-guard.py` on Bash.
- `.claude/settings.json` is **consumer-owned** (bootstrap only optionally writes a stop-hook) →
  its matchers must be hand-updated to the new MCP tool names in Stage 6.

## Consequence for the two consumer-only hooks
Because hooks are a whole-directory symlink (no per-file override), keeping
`guard-handoff-provenance.py` requires freezing the entire `scripts/hooks` dir as `source: local`
(forfeits all canonical hook updates). The clean path drops it. → DECISION A.
`terminal-guard.py` is reintroduced+wired by canonical; the consumer had been retiring it. → DECISION B.
