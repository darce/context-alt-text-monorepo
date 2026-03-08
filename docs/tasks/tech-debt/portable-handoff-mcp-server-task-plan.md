# Portable Agent Handoff MCP Server

## Problem Statement

The current MCP setup is centered on [`scripts/mcp/unified_server.py`](/Users/daniel/Development/context-alt-text-monorepo/scripts/mcp/unified_server.py), which mixes handoff state, repo-intel helpers, and client-specific launch assumptions into one server. The project needs a properly packaged, portable MCP server whose sole job is agent handoff, plus a decomposition plan for the remaining non-handoff tools so they can become separate MCP servers later without dragging handoff state along with them.

## Workflow Principles

- Handoff state is the product; repo-intel helpers are separate concerns and must not remain coupled to it.
- MCP standardizes protocol, not client registration; packaging must assume multiple harness-specific adapters.
- Workspace state belongs to the workspace, not inside the installed server package directory.
- SQLite remains the canonical handoff store; markdown remains a generated view.
- This task is greenfield for packaging and naming; no backward-compatibility layer or data migration is required.
- Future MCP servers should start as narrow stubs with stable tool contracts, not another "unified" monolith.

## Terminology

- **Handoff server**: The MCP server exposing only task-state, review-finding, archive/export, and close-check tools.
- **Workspace state**: Mutable per-repo or per-worktree data such as `handoff.db` and generated `CURRENT_TASK.md`.
- **Client adapter**: Harness-specific registration/config that launches the same MCP server in VS Code, Codex, Claude, Gemini, or other MCP-capable hosts.
- **Tool family**: A logical grouping of tools, for example `handoff_*`, `wordpress_*`, `react_*`, or `docs_*`.
- **Portable packaging**: A distribution model that does not depend on `.vscode/mcp.json`, `pyenv`, Homebrew paths, or repo-local shell wrappers to function.

## Current State Analysis

- [`scripts/mcp/unified_server.py`](/Users/daniel/Development/context-alt-text-monorepo/scripts/mcp/unified_server.py) already contains the handoff SQL schema and task-state logic that should be reused as implementation input, even though packaging can start fresh.
- The same file also contains non-handoff helpers for WordPress lookup, React lookup, and docs/contracts/maps access, which makes the server name, packaging, and responsibility boundary unclear.
- [`scripts/mcp/mcp-server.sh`](/Users/daniel/Development/context-alt-text-monorepo/scripts/mcp/mcp-server.sh) and [`.vscode/mcp.json`](/Users/daniel/Development/context-alt-text-monorepo/.vscode/mcp.json) are VS Code oriented launch adapters, not a portable installation story.
- The current runtime assumes local shell execution details such as `bash`, `pyenv`, sourced `.env`, and macOS/Homebrew-style PATH setup.
- The handoff database is currently modeled as workspace state under [`.task-state/handoff.db`](/Users/daniel/Development/context-alt-text-monorepo/.task-state/handoff.db), which is the correct ownership model for task history tied to a repo/worktree.
- MCP itself does not define where mutable server state lives. That decision is application-specific and should follow the ownership boundary of the data.
- Generic file search/read tools already exist in most harnesses, so docs/contracts/maps helpers should only survive as future MCP stubs if they provide curated domain lookup that generic tools do not.
- The current fallback workflow also depends on the large CLI surface in `unified_server.py`; a handoff-only package cannot drop that path unless the task explicitly replaces it with an equivalent CLI.

## Proposed Solution

Extract the handoff functionality into a dedicated, installable MCP package at `packages/agent-handoff-mcp/` with a stable generic name, explicit transport entrypoints, explicit CLI subcommands, and workspace-scoped state configuration. Reuse the existing SQLite schema and handoff tool logic as the starting implementation model, but do not preserve old environment variable names, old server registration names, or previous handoff database contents.

At the same time, inventory the non-handoff helpers in `unified_server.py` and split them into future-oriented modules with stubbed MCP server entrypoints for:

1. WordPress helpers
2. React/frontend helpers
3. Docs/contracts/maps helpers, only where they provide curated value beyond native agent tools

The outcome should be:

- one portable handoff MCP server package
- one workspace-state convention for `handoff.db`
- one set of client adapters/generated launch manifests
- one explicit classification of all remaining non-handoff tools before any future stubs are created

## Current Tool Inventory

The current `unified_server.py` exposes 29 tools. The task should classify them before creating any non-handoff follow-up servers.

| Tool | Family | Preliminary Disposition |
| --- | --- | --- |
| `set_handoff_state` | handoff | move to handoff package |
| `get_handoff_state` | handoff | move to handoff package |
| `record_decision` | handoff | move to handoff package |
| `update_next_actions` | handoff | move to handoff package |
| `record_test_result` | handoff | move to handoff package |
| `report_blocker` | handoff | move to handoff package |
| `record_review_finding` | handoff | move to handoff package |
| `update_review_finding` | handoff | move to handoff package |
| `reopen_review_finding` | handoff | move to handoff package |
| `list_review_findings` | handoff | move to handoff package |
| `get_review_finding` | handoff | move to handoff package |
| `get_review_findings_summary` | handoff | move to handoff package |
| `reconcile_review_findings` | handoff | move to handoff package |
| `handoff_close_check` | handoff | move to handoff package |
| `generate_current_task_md` | handoff | move to handoff package |
| `export_handoff_state` | handoff | move to handoff package |
| `import_handoff_state` | handoff | move to handoff package |
| `archive_task_state` | handoff | move to handoff package |
| `get_handoff_dashboard` | handoff | move to handoff package |
| `get_context_map` | docs | classify in Phase 3 |
| `get_api_contract` | docs | classify in Phase 3 |
| `get_instructions` | docs | classify in Phase 3 |
| `trace_api_endpoint` | cross-boundary repo intel | classify in Phase 3 |
| `find_react_component` | react | classify in Phase 3 |
| `find_react_hook` | react | classify in Phase 3 |
| `list_frontend_tests` | react | classify in Phase 3 |
| `find_wp_action` | wordpress/php | classify in Phase 3 |
| `find_wp_rest_route` | wordpress/php | classify in Phase 3 |
| `find_php_class` | wordpress/php | classify in Phase 3 |

## Patterns to Follow

### Workspace-Scoped State, Not Package-Scoped State

```python
from pathlib import Path
import os


def resolve_workspace_root(cli_workspace_root: str | None) -> Path:
    if cli_workspace_root:
        return Path(cli_workspace_root).expanduser().resolve()

    env_workspace_root = os.environ.get("AGENT_HANDOFF_WORKSPACE_ROOT")
    if env_workspace_root:
        return Path(env_workspace_root).expanduser().resolve()

    raise RuntimeError("AGENT_HANDOFF_WORKSPACE_ROOT must be set or passed via --workspace-root")


def resolve_workspace_state_dir(cli_state_dir: str | None, cli_workspace_root: str | None) -> Path:
    if cli_state_dir:
        return Path(cli_state_dir).expanduser().resolve()

    env_state_dir = os.environ.get("AGENT_HANDOFF_STATE_DIR")
    if env_state_dir:
        return Path(env_state_dir).expanduser().resolve()

    return resolve_workspace_root(cli_workspace_root) / ".task-state"


def resolve_handoff_db_path(cli_state_dir: str | None, cli_workspace_root: str | None) -> Path:
    return resolve_workspace_state_dir(cli_state_dir, cli_workspace_root) / "handoff.db"
```

### Portable MCP Entrypoint With CLI Fallback

```python
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "serve-stdio",
            "serve-http",
            "doctor",
            "state",
            "dashboard",
            "set",
            "decision",
            "action",
            "blocker",
            "test",
            "review-list",
            "review-summary",
            "handoff-close-check",
        ],
    )
    parser.add_argument("--workspace-root")
    parser.add_argument("--state-dir")
    args = parser.parse_args()

    config = RuntimeConfig.from_args(args)

    if args.command == "serve-stdio":
        build_handoff_mcp(config).run(transport="stdio")
    elif args.command == "serve-http":
        build_handoff_mcp(config).run(transport="streamable-http")
    elif args.command == "state":
        print(run_state_cli(config, args))
    else:
        run_cli_command(config, args)
```

### Client Adapters Are Generated, Not Canonical

```json
{
  "name": "agent-handoff",
  "command": "agent-handoff-mcp",
  "args": ["serve-stdio", "--workspace-root", "/path/to/repo"],
  "env": {
    "AGENT_HANDOFF_WORKSPACE_ROOT": "/path/to/repo"
  }
}
```

## Functions to Change

| File | Line | Change |
| --- | --- | --- |
| `packages/agent-handoff-mcp/` | new | Create the installable handoff-only package with runtime config, MCP bootstrap, and CLI entrypoints. |
| [`/Users/daniel/Development/context-alt-text-monorepo/scripts/mcp/unified_server.py`](/Users/daniel/Development/context-alt-text-monorepo/scripts/mcp/unified_server.py) | 1 | Extract handoff schema, migrations, runtime config, and MCP tool registration into a dedicated handoff package; leave only transitional compatibility or remove unified bootstrap entirely. |
| [`/Users/daniel/Development/context-alt-text-monorepo/scripts/mcp/mcp-server.sh`](/Users/daniel/Development/context-alt-text-monorepo/scripts/mcp/mcp-server.sh) | 1 | Replace repo-specific launcher assumptions with a compatibility shim that invokes the packaged handoff server or generated adapter. |
| [`/Users/daniel/Development/context-alt-text-monorepo/.vscode/mcp.json`](/Users/daniel/Development/context-alt-text-monorepo/.vscode/mcp.json) | 1 | Point VS Code at the packaged handoff server adapter instead of the unified repo script. |
| [`/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/BOOTSTRAP.md`](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/BOOTSTRAP.md) | 1 | Replace unified-server setup guidance with handoff-server packaging, registration, and state-location guidance. |
| [`/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/instructions.md`](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/instructions.md) | 1 | Update MCP fallback and handoff guidance to refer to the dedicated handoff server and its canonical state location. |
| `/Users/daniel/Development/context-alt-text-monorepo/CLAUDE.md` | 152 | Update MCP handoff contract text and any server-name or tool-prefix assumptions. |
| `/Users/daniel/Development/context-alt-text-monorepo/GEMINI.md` | 152 | Update MCP handoff contract text and any server-name or tool-prefix assumptions. |
| [`/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/tests/unit/test_mcp_handoff_state.py`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/tests/unit/test_mcp_handoff_state.py) | 1 | Retarget the handoff tests to the extracted package/module boundaries and add packaging/runtime config coverage. |

## Related Files

| File | Note |
| --- | --- |
| [`/Users/daniel/Development/context-alt-text-monorepo/docs/tasks/tech-debt/agent-handoff-state-mcp-implementation-plan.md`](/Users/daniel/Development/context-alt-text-monorepo/docs/tasks/tech-debt/agent-handoff-state-mcp-implementation-plan.md) | Original implementation plan whose schema and tool behavior should be preserved rather than redesigned. |
| [`/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/templates/CURRENT_TASK.template.md`](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/templates/CURRENT_TASK.template.md) | Fallback markdown template; generated-task behavior still needs to align with this shape. |
| [`/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/contracts/`](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/contracts/) | Docs/contracts/maps helpers should only become future MCP servers if they add curated lookup value beyond generic tooling. |
| [`/Users/daniel/Development/context-alt-text-monorepo/scripts/README.md`](/Users/daniel/Development/context-alt-text-monorepo/scripts/README.md) | Needs updated MCP server inventory and launch guidance after decomposition. |
| `/Users/daniel/Development/context-alt-text-monorepo/CLAUDE.md` | Current fallback instructions and tool-prefix assumptions are part of the rename/update surface. |
| `/Users/daniel/Development/context-alt-text-monorepo/GEMINI.md` | Current fallback instructions and tool-prefix assumptions are part of the rename/update surface. |

---

# Consolidated Checklist

## Completed

- [x] A working handoff schema, SQLite migrations, and handoff tool logic already exist inside the unified server.
- [x] Workspace-local state convention already exists via `.task-state/handoff.db`.
- [x] VS Code-specific MCP launch wiring already exists and can serve as one client adapter.

## Phase 0: Scaffolding

- [ ] Choose `packages/agent-handoff-mcp/` as the canonical package location.
- [ ] Create a dedicated package/module layout for the handoff MCP server separate from `unified_server.py`.
- [ ] Add runtime config objects for workspace root, state dir, DB path, and generated markdown path.
- [ ] Add packaged entrypoints for `serve-stdio`, `doctor`, and the handoff CLI fallback commands.
- [ ] Update API/tool contract docs in `docs/agentic/contracts/` if any handoff tool names or request shapes change.
- [ ] Verify scaffolds compile and import cleanly in tests without going through VS Code-specific launch paths.

## Phase 1: Portable Handoff Packaging

- [ ] Extract only handoff-related schema/bootstrap/logic from `unified_server.py` into the dedicated handoff package.
- [ ] Reuse the existing handoff SQL schema and tool behavior as the baseline implementation, but do not migrate old persisted handoff state.
- [ ] Replace shell- and pyenv-specific bootstrap assumptions with package/runtime configuration that works across harnesses.
- [ ] Use fresh generic naming for package, server, and env vars with no compatibility aliases required.
- [ ] Support workspace-root and state-dir overrides so the same server can run per repo or per worktree.
- [ ] Keep the handoff DB in workspace state (`.task-state/` by default), not inside the installed server package directory.
- [ ] Rewrite handoff tests to inject runtime config rather than monkeypatching module-level globals.

## Phase 2: Client Portability

- [ ] Define one canonical packaged server name and display name for the handoff server.
- [ ] Generate or document thin client adapters for VS Code, Codex, Claude, Gemini, and other MCP-capable harnesses.
- [ ] Add a `doctor` command that validates runtime dependencies, writable state path, stdio startup, and CLI fallback startup.
- [ ] Document the rename/update surface for client registration names and instruction-file tool prefixes.
- [ ] Add a stdio smoke test to prove the server can be discovered outside VS Code-specific config.

## Phase 3: Decompose Non-Handoff Tool Families

- [ ] Inventory every non-handoff tool currently exposed by `unified_server.py`.
- [ ] Classify each non-handoff tool as `future_server`, `drop`, or `keep_only_if_curated_value`.
- [ ] Decide whether the non-handoff follow-up shape is one `repo-intel` companion server or multiple narrower servers.
- [ ] Create WordPress-helper MCP stubs only for tools that still provide value beyond native grep/read/definition tools.
- [ ] Create React-helper MCP stubs only for tools that still provide value beyond native grep/read/definition tools.
- [ ] Create docs/contracts/maps MCP stubs only if they provide curated canonical lookup that generic agent tooling does not already cover.
- [ ] Remove or quarantine non-handoff tool registration from the portable handoff server.

## Phase 4: Tests and Migration Safety

- [ ] Add unit coverage for runtime path resolution and default DB placement.
- [ ] Add regression tests proving the extracted handoff server preserves the intended handoff SQL schema behavior and task semantics from a fresh database.
- [ ] Add transport-level smoke tests for `serve-stdio`.
- [ ] Add CLI smoke tests for fallback commands such as `state`, `review-list`, and `handoff-close-check`.
- [ ] Add compatibility coverage for the VS Code adapter and one non-VS-Code adapter path.
- [ ] Verify existing handoff state tests pass after extraction.

## Stretch Goals

- [ ] Publish the handoff server as a versioned internal package or binary so clients do not need repo-local shell wrappers.
- [ ] Add `serve-http` once there is a real consumer for remote/shared transport.
- [ ] Split future MCP servers into separate packages (`wordpress`, `react`, `docs`, or one `repo-intel` companion) once their contracts are validated.
- [ ] Add a manifest generator that emits client-specific registration snippets from one source of truth.

## Success Criteria

- [ ] A single-purpose handoff MCP server can be launched without relying on `.vscode/mcp.json` or `mcp-server.sh`, and exposes both MCP and CLI fallback entrypoints.
- [ ] Handoff state remains workspace-scoped, with `handoff.db` stored under `.task-state/` by default rather than inside the server package directory.
- [ ] VS Code, Codex, Claude, and Gemini can each register the same handoff server through client-specific adapters without changing server code.
- [ ] Non-handoff functionality is no longer bundled into the handoff server and instead has an explicit inventory and documented next-step classification.
- [ ] The new handoff package starts cleanly from an empty database without requiring legacy handoff-state migration.
