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

The canonical MCP runtime for handoff state is now the packaged `agent-handoff-mcp` server under [`packages/agent-handoff-mcp/`](../packages/agent-handoff-mcp/). Repo-owned orchestration tools prefer the checked-out package source so local branch fixes take effect immediately; an installed `agent-handoff-mcp` binary is the fallback outside repo-managed flows. `mcp/mcp-server.sh` remains a local fallback shim for development and diagnostics.

`unified_server.py` is no longer the handoff runtime. It remains only as legacy/reference code for any future extraction of non-handoff repo-intel workflows.

## worktree-lane

Helper for the orchestrator/worker pattern described in [instructions.md](../docs/agentic/instructions.md).

Preferred entrypoint:

- use the root [Makefile](../Makefile) targets for normal lane orchestration
- drop to `scripts/worktree-lane` only when you need the lower-level helper directly

App-level Makefiles (`apps/prototype-description-service/Makefile`, `apps/prototype-wp-alt-context/Makefile`) use a `lane-%:` pattern rule that auto-forwards any `lane-*` target to the root Makefile. New lane targets added to root are available in app directories immediately with no app Makefile changes.

Task-aware lane orchestration is driven by checked-in manifests under `config/lane-orchestration/<task-ref>.json`. Add a manifest there when a new task needs reusable lane automation; the root `Makefile` and dispatch helpers read from that manifest instead of from task-specific hardcoded tables.

Recommended commands:

```bash
make lane-open TASK=phase-5-retention-export-and-audit-controls LANE=frontend
make lane-open TASK=phase-5-retention-export-and-audit-controls LANE=frontend ENTER_SHELL=0
make lane-status TASK=phase-5-retention-export-and-audit-controls LANE=frontend
make lane-inbox TASK=phase-5-retention-export-and-audit-controls LANE=frontend
make lane-prompt TASK=phase-5-retention-export-and-audit-controls LANE=frontend
make lane-run TASK=phase-5-retention-export-and-audit-controls LANE=frontend
make lane-dispatch TASK=phase-5-retention-export-and-audit-controls LANE=frontend MESSAGE="Add the remaining Phase 6 retention Vitest coverage."
make handoff-inbox TASK=phase-5-retention-export-and-audit-controls
make handoff-dispatch TASK=phase-5-retention-export-and-audit-controls
make review-dispatch TASK=phase-5-retention-export-and-audit-controls
make lane-commit
make lane-handoff
make lane-refresh TASK=phase-5-retention-export-and-audit-controls LANE=frontend
make lane-clean TASK=phase-5-retention-export-and-audit-controls LANE=frontend
make lane-report TASK=phase-5-retention-export-and-audit-controls LANE=frontend SESSION=phase5-frontend SUMMARY="Frontend slice ready" MERGE_READY=1
make lane-reset TASK=phase-5-retention-export-and-audit-controls LANE=frontend REF=feature/6.0.2-retention-export
make lane-commits TASK=phase-5-retention-export-and-audit-controls LANE=frontend
make lane-intake TASK=phase-5-retention-export-and-audit-controls LANE=frontend DRY_RUN=1
```

Notes:

- `make lane-open` cannot mutate the parent shell's working directory.
- It now polls the initial lane inbox as part of setup so the worker sees open orchestrator dispatches immediately.
- It refuses to reuse an existing lane worktree if that checkout is on the wrong branch, which protects against misdirected commits.
- By default it opens an interactive subshell rooted in the lane worktree after setup and briefing.
- Set `ENTER_SHELL=0` if you want setup only and prefer to `cd` manually afterward.
- `make lane-path ...` prints the exact worktree path if you prefer `cd "$(make lane-path ...)"`.
- `make lane-inbox` is the worker polling command. It shows open orchestrator-to-worker lane messages, the latest worker report, recent lane activity, and git status.
- `make lane-prompt` turns the current lane inbox into a concise worker prompt. This is the most reliable handoff bridge from MCP state into a fresh agent run.
- `make lane-check` runs the lane's configured verification commands and records each result into MCP, so `lane-activity` carries a durable test trail instead of terminal-only output.
- `make lane-run` launches the selected execution backend in the lane worktree using that generated prompt, requires a structured final handoff payload, and then auto-submits either `lane-handoff` or a blocked `lane-report` based on the result. `BACKEND=codex-cli` uses `codex exec`; `BACKEND=codex-subagent` routes through the Codex app-server bridge. It is better than trying to push text into an already-running interactive session.
- Lanes may declare manifest-driven preflight gates. For example, `backend-domain` now checks local Postgres/env readiness before any subagent turn and will auto-submit `needs_guidance` if the DB capability is unavailable.
- `make handoff-inbox` is the orchestrator polling command. It shows open worker-to-orchestrator lane messages and the latest merge-ready or blocked worker reports across lanes.
- `make lane-dispatch ... MESSAGE="..."` is the orchestrator assignment command. It records a lane message in MCP and regenerates `CURRENT_TASK.md`.
- `make handoff-dispatch` is the orchestrator handoff-fanout command. Run reviews or update handoff state from the orchestrator root, then route unassigned open review findings, blockers, and next actions to the correct lane so workers see them in `make lane-inbox`.
- `make review-dispatch` remains available as a backward-compatible alias for `make handoff-dispatch`.
- `make lane-commit` stages the lane-owned paths and creates a default commit whose message begins with the lane name, for example `frontend: update retention admin UI`.
- `make lane-handoff` is the normal worker handoff path: it verifies scope, commits lane-owned changes, shows lane status, and then submits a merge-ready report using inferred `TASK`, `LANE`, and default `SESSION`.
- Merge-ready and blocked worker reports now auto-open a `worker_to_orchestrator` lane message, so the orchestrator can pick them up through `make handoff-inbox` without requiring an extra manual `MESSAGE=...` step.
- `lane-report` keeps merge-ready handoffs commit-based, but blocked guidance reports can be submitted without lane commits when a sandbox or environment issue prevented code changes. Dirty worktrees are still rejected unless explicitly allowed.
- `make lane-report ... STATUS=blocked MESSAGE="..."` remains available as a manual escape hatch, but `make lane-run` should normally infer and submit that blocked handoff automatically from the worker's structured final result.
- `make lane-refresh` refreshes a worker lane from the orchestrator branch. It auto-stashes dirty lane state before the refresh and auto-pops the stash afterward; if the pop conflicts, the stash is preserved and a warning is printed. Resets or rebases depending on whether the lane already has unique commits. Workflow tooling is expected to arrive through committed orchestrator branch state, not by copying live root files into the lane.
- If root workflow tooling is locally dirty, `make lane-refresh` refuses to run until those orchestrator changes are committed. That keeps worker branches clean.
- `make lane-clean` removes legacy copied tooling drift from a lane without touching lane-owned product files.
- `make lane-commits ...` shows the commits reachable from the lane branch that are not yet on the current orchestrator branch.
- `make lane-intake ...` prints the latest merge-ready worker report, stages the intake in a scratch worktree, runs lane-local verification there, and only fast-forwards the orchestrator branch if the scratch intake succeeds. Run it from the orchestrator root, not from a worker worktree.
- If `lane-intake` hits a conflict, root stays untouched. Refresh the lane and resolve the conflict there instead of hand-editing the orchestrator branch.

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
  --task-ref phase-5-retention-export-and-audit-controls \
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
