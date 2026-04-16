# Why does `agent-handoff-mcp` CLI persist alongside native MCP tools and the Python API?

> **Metadata**
>
> - **Date**: 2026-04-16
> - **Author**: Claude Opus 4 (1M context)
> - **Status**: Investigation / architectural note (no implementation slice)
> - **Trigger**: User question on the `branch-lifecycle` cycle after E17-6 merged: *"Why is the python CLI still used for `agent-handoff-mcp` instead of native tools? Is using CLI more economical from a token usage perspective?"*
> - **Scope**: monorepo root `/Users/daniel/Development/context-alt-text-monorepo`, HEAD `d221e98f`.

## TL;DR

1. The CLI is used in exactly **one** non-bootstrap call site in production code: the shell hook `scripts/hooks/guard-main-branch.sh` querying identity on main-branch edits.
2. The CLI, Python API, and native MCP tools are **three presentations of the same Python backend**. They are not competitors — they are chosen by *what runs them*: shell vs. Python interpreter vs. agent tool loop.
3. From a **token** perspective the question is moot where the CLI is used: the hook runs out-of-band in shell, its stdout is parsed and discarded, and **zero agent tokens** are spent. Converting that hook to a native MCP tool call would push the query into the agent's tool-use loop and **add** tokens per edit.
4. The CLI is not kept for token economy. It is kept because shell scripts cannot `import` Python, and the hook needs a one-shot, harness-neutral, Python-backed query. The equivalent path would be `python3 -c "from agent_handoff_mcp import …"` — same interpreter cost, marginally terser syntax, slightly different packaging.

## Call-site inventory

Three tiers, each chosen by execution environment:

### 1. CLI (shell-visible)

| File | Line | Command | Runs in | Agent tokens |
|---|---|---|---|---|
| `scripts/hooks/guard-main-branch.sh` | 73 | `agent-handoff-mcp --workspace-root "$REPO_ROOT" state --sections identity` | shell (PreToolUse hook) | **0** (hook output → stderr warn or silent allow) |
| `scripts/hooks/regenerate-task-views.sh` | 43 | `agent-handoff-mcp --workspace-root "$WORKSPACE_ROOT" write-dashboard` | shell (PostToolUse hook) | **0** (fire-and-forget; errors swallowed) |
| `.mcp.json` | — | `agent-handoff-mcp --workspace-root … serve-stdio` | MCP server bootstrap | **0** (the CLI *is* the MCP server) |

`.mcp.json` is not a "CLI call site" in the behavioural sense — it is how Claude Code and VS Code launch the MCP server subprocess that *provides* the native tools. Removing the CLI entry point would remove native MCP tools with it.

### 2. Python API (in-process)

Used wherever a Python interpreter is already the host:

- `scripts/_task_start_inline.py`, `scripts/_task_finish_inline.py` — `task-start.sh` / `task-finish.sh` shell out to Python once.
- `scripts/agentic/slice_commit.py` — `make slice-commit` entry point.
- `scripts/check_plan_analyze.py`, `scripts/check_harness_sync.py`, `scripts/task_plan_audit.py`, `scripts/worktree_audit.py` — audit/gate scripts wired into `make check-all`.
- `scripts/hooks/record-file-touch.py`, `scripts/hooks/guard-task-plan-findings.py`, `scripts/hooks/guard-rationale-size.py`, `scripts/hooks/ace-detect.py`, `scripts/hooks/slim-handoff-response.py`, `scripts/hooks/validate-mcp-dict-params.py` — hook scripts implemented in Python.
- `packages/agent-orchestrator-mcp/tests/*.py` — pytest suites that exercise handoff tables directly via the API.

Common shape: `configure_runtime(RuntimeConfig.for_repo(Path('.')))` then direct function calls.

### 3. Native MCP tools (`mcp__agent-handoff-mcp__*`)

Referenced by hook matchers and protocol docs; actually invoked by the agent's tool-use loop:

- `.claude/settings.json` and `.github/hooks/terminal-guard.json` — matchers that gate the PreToolUse / PostToolUse hooks listed above.
- `docs/agentic/contracts/harness-protocol.yaml` — canonical harness contract.
- `docs/agentic/maps/mcp-tool-routing.yaml` — `agent-handoff-mcp` is in the `always` group.

This is the only tier that costs **agent tokens** per call.

## Why three tiers — and why the split is not redundant

The CLI, Python API, and native MCP tools **share one backend** (`packages/agent-handoff-mcp/src/agent_handoff_mcp/`). The three tiers exist because invocation environments differ:

| Environment | What it can do | Why each tier is useful |
|---|---|---|
| Agent inside Claude Code / Copilot | call native MCP tools directly | fastest path for agent-driven reads/writes; slim-handoff-response hook trims the response |
| Python scripts (tests, Makefile targets, PostToolUse hooks) | `import agent_handoff_mcp` | zero IPC overhead; richer return shapes than the MCP schema exposes |
| Bash hooks, CI shell steps | invoke a binary on `$PATH` | harness-neutral; one-liner to query a JSON blob without writing a Python wrapper |

A pure two-tier model (Python API + native MCP tools) would force every shell surface to inline `python3 -c "from agent_handoff_mcp import …"` or add a Python wrapper. The CLI is the ergonomic shell-facing veneer on the same Python entry points.

## Token economics — the measurement

The user's question conflates two categories of cost:

**Wall time / CPU** — I measured both paths on the live repo:

```
$ /usr/bin/time agent-handoff-mcp --workspace-root "$(pwd)" state --sections identity
real 2.61  user 1.43  sys 0.27      (output: 189 bytes)

$ /usr/bin/time python3 -c "from pathlib import Path; \
    from agent_handoff_mcp import RuntimeConfig, configure_runtime, get_handoff_state; \
    configure_runtime(RuntimeConfig.for_repo(Path('.'))); \
    print(get_handoff_state(sections='identity'))"
real 2.59  user 1.41  sys 0.27      (output: 157 bytes)
```

Near-identical. Wall time is dominated by Python interpreter startup + `agent_handoff_mcp` package import, not by argparse. The CLI is not cheaper.

**Agent token context** — this is where the answer flips:

| Path | Token cost to the agent |
|---|---|
| Shell hook invokes CLI → stdout parsed by hook → stderr warn or silent allow | **0** |
| Shell hook invokes `python3 -c "from agent_handoff_mcp import …"` → same | **0** |
| Agent issues `mcp__agent-handoff-mcp__get_handoff_state(sections="identity")` directly | ~100–250 tokens (request + envelope + response, after slim-handoff-response trims it) |
| Agent issues `Bash("agent-handoff-mcp state …")` or `Bash("python3 -c …")` | ~200–400 tokens (Bash tool envelope + stdout capture) |

The CLI path in `guard-main-branch.sh` is **strictly more economical** than either agent-side path because *it is not an agent-side path*. The hook runs before the agent ever sees a tool result, and its output is consumed by the hook wrapper, not surfaced to the agent.

Moving that logic into a native MCP call would require:
1. teaching the hook to *emit* a recommendation to the agent, and
2. trusting the agent to issue the query *before every main-branch edit*.

Both are regressions: (1) shifts a guard rail from compile-time (hook) to runtime (agent choice); (2) spends tokens on every edit that the hook otherwise handles for free.

## Is the CLI "more economical from a token usage perspective"?

**Direct answer**: Yes, but not for the reason the question implies.

- The CLI is not chosen instead of native MCP tools as a token-saving optimization.
- It is used in a layer (shell hooks) where native MCP tools are **not available to the caller** (shell cannot hold an MCP session).
- In that layer, its token cost is zero — same as the Python API would be. Native MCP tools would cost non-zero tokens because they run inside the agent's tool-use loop.
- For agent-side work, the ordering is unchanged: **native MCP tools > Python API via Bash > CLI via Bash**. The CLI via Bash is the most expensive agent-side path per unit of work, not the cheapest.

## What (if anything) to change

The current layout is consistent with the harness-protocol contract and the cold-start rule ("MCP tool calls when available; fall back to the Python API on cold start or context switch"). Three follow-ups are worth noting:

1. **`guard-main-branch.sh` could be rewritten in Python** to reuse the in-process API and drop the CLI dependency. Benefit: fewer moving parts. Cost: none material. Not urgent; the CLI call is already cheap and bounded.
2. **`regenerate-task-views.sh` could migrate similarly**. Same tradeoff.
3. **The CLI must stay** regardless, because `.mcp.json` launches it as the MCP server. Removing the binary would remove native tools.

None of these are load-bearing. Filing as an observation, not an action.

## References

- `scripts/hooks/guard-main-branch.sh:73` — the one CLI hook query in production.
- `scripts/hooks/regenerate-task-views.sh:43` — dashboard regen fallback.
- `.mcp.json` — MCP server launch line.
- `docs/agentic/contracts/harness-protocol.yaml` — harness contract (cold-start, python_api_fallback).
- `docs/agentic/maps/mcp-tool-routing.yaml` — routing rules.
- `docs/agentic/rules/branch-review-guide.md` § Handoff-only Fallback — cold-start cascade.
- `CLAUDE.md` § Agent Startup Protocol step 2–3 — MCP-first, Python API fallback ordering.
