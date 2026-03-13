# Monorepo Scripts

Cross-project scripts for the monorepo. App-specific scripts live under each app's own `scripts/` directory.

## Structure

```
scripts/
├── localwp-db.sh          # Connect to LocalWP MySQL (auto-discovers socket)
├── worktree-lane          # Worktree + MCP helper for orchestrator/worker lanes
└── mcp/
    ├── mcp-server.sh       # Agent Handoff MCP launch shim
    └── unified_server.py   # Legacy non-handoff/reference MCP implementation
```

## localwp-db.sh

Connect to the LocalWP MySQL database without needing to know the volatile socket path.

```bash
./scripts/localwp-db.sh                                 # Interactive shell
./scripts/localwp-db.sh -e "SHOW TABLES LIKE '%acx%'"   # Run a query
./scripts/localwp-db.sh -e "SELECT * FROM wp_acx_clusters"
```

Supports `LOCALWP_SOCKET`, `LOCALWP_DB_NAME`, `LOCALWP_DB_USER`, `LOCALWP_DB_PASS` env overrides.

## mcp/

The canonical MCP runtime for handoff state is now the packaged `agent-handoff-mcp` server under [`packages/agent-handoff-mcp/`](../packages/agent-handoff-mcp/). Clients should launch the installed `agent-handoff-mcp` binary directly. `mcp/mcp-server.sh` remains a local fallback shim for development and diagnostics.

`unified_server.py` is no longer the handoff runtime. It remains only as legacy/reference code for any future extraction of non-handoff repo-intel workflows.

## worktree-lane

Helper for the orchestrator/worker pattern described in [instructions.md](../docs/agentic/instructions.md).

Preferred entrypoint:

- use the root [Makefile](../Makefile) targets for normal lane orchestration
- drop to `scripts/worktree-lane` only when you need the lower-level helper directly

Recommended commands:

```bash
make lane-open TASK=phase-5-retention-export-and-audit-controls LANE=frontend
make lane-open TASK=phase-5-retention-export-and-audit-controls LANE=frontend ENTER_SHELL=1
make lane-status TASK=phase-5-retention-export-and-audit-controls LANE=frontend
make lane-handoff
make lane-report TASK=phase-5-retention-export-and-audit-controls LANE=frontend SESSION=phase5-frontend SUMMARY="Frontend slice ready" MERGE_READY=1
make lane-reset TASK=phase-5-retention-export-and-audit-controls LANE=frontend REF=feature/6.0.2-retention-export
make lane-commits TASK=phase-5-retention-export-and-audit-controls LANE=frontend
make lane-intake TASK=phase-5-retention-export-and-audit-controls LANE=frontend DRY_RUN=1
```

Notes:

- `make lane-open` cannot mutate the parent shell's working directory.
- `ENTER_SHELL=1` is the closest equivalent: it opens an interactive subshell rooted in the lane worktree after setup and briefing.
- `make lane-path ...` prints the exact worktree path if you prefer `cd "$(make lane-path ...)"`.
- `make lane-handoff` is the normal worker handoff path: it shows lane status and then submits a merge-ready report using inferred `TASK`, `LANE`, and default `SESSION`.
- `make lane-commits ...` shows the commits reachable from the lane branch that are not yet on the current orchestrator branch.
- `make lane-intake ...` prints those lane-only commits first, then cherry-picks them in order. Run it from the orchestrator root, not from a worker worktree.

It wraps:

- `git worktree add`
- shared-state `agent-handoff-mcp lane-upsert`
- lane self-query via `state`, `lane-list`, `lane-activity`
- merge-ready worker handback via `lane-report` and optional `lane-message`
- brief/report template rendering

Examples:

```bash
scripts/worktree-lane create \
  --orchestrator-root /path/to/context-alt-text-monorepo \
  --lane-id backend-http \
  --branch codex/phase5-backend-http \
  --title "Backend HTTP" \
  --objective "Implement retention router and schema updates."
```

```bash
scripts/worktree-lane brief \
  --orchestrator-root /path/to/context-alt-text-monorepo \
  --task-ref phase-5-retention-export-and-audit-controls \
  --lane-id backend-http \
  --branch codex/phase5-backend-http \
  --worktree-path /path/to/context-alt-text-monorepo-backend-http \
  --objective "Implement retention router and schema updates." \
  --owned-path apps/prototype-description-service/recognition/interface_adapters/http/** \
  --required-doc docs/agentic/instructions.md \
  --test-command "cd apps/prototype-description-service && pytest recognition/tests/api/test_retention_api.py"
```

```bash
scripts/worktree-lane status \
  --orchestrator-root /path/to/context-alt-text-monorepo \
  --lane-id backend-http \
  --worktree-path /path/to/context-alt-text-monorepo-backend-http
```

```bash
scripts/worktree-lane report \
  --orchestrator-root /path/to/context-alt-text-monorepo \
  --task-ref phase-5-retention-export-and-audit-controls \
  --lane-id backend-http \
  --session phase5-http \
  --summary "HTTP slice is ready for orchestrator review." \
  --worktree-path /path/to/context-alt-text-monorepo-backend-http \
  --test-command "cd apps/prototype-description-service && pytest recognition/tests/api/test_retention_api.py" \
  --merge-ready \
  --message "This lane is ready for branch review."
```
