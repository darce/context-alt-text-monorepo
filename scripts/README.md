# Monorepo Scripts

Cross-project scripts for the monorepo. App-specific scripts live under each app's own `scripts/` directory.

## Structure

```text
scripts/
├── localwp-runtime.sh     # Resolve LocalWP socket/php paths without hard-coded hashes
├── localwp-wp.sh          # Run WP-CLI with LocalWP-aware php/socket resolution
├── localwp-gate-status.sh # Print LocalWP E15-3a gate status as JSON
├── localwp-db.sh          # Connect to LocalWP MySQL (auto-discovers socket)
├── worktree-lane          # Worktree + MCP helper for orchestrator/worker lanes
└── mcp/
    └── unified_server.py   # Legacy non-handoff/reference MCP implementation (deprecated)
```

The orchestration helpers in this repo now execute the installed `mcp-workbay-orchestrator`
package directly, including `python -m workbay_orchestrator_mcp.orchestration.lane_config`
for lane/task manifest resolution.

## check_published_head_sha.py

Every committed eval run-record and report under `docs/` and `benchmarks/`
must stamp a `head_sha` that exists in this repository. Harvest/rebase
rewrites have previously left orphan SHAs in published artifacts.

```bash
python3 scripts/check_published_head_sha.py
```

The script walks tracked `docs/**` and `benchmarks/**` JSON/Markdown files,
collects each published `head_sha`, and runs
`git rev-parse --verify <sha>^{commit}` on each. Exit 0 if every stamp
resolves; exit 1 if any SHA is missing. Wired into `make lint-scripts`.

## Test Placement Policy

Root-level doc-lock tests stay in `scripts/` when they validate monorepo-wide
operator surfaces rather than one app. Examples include
`test_consumer_setup_doc.py`, `test_current_task_demotion_surfaces.py`,
and `test_rg014_external_package_scope.py`.
These tests cover shared setup guides, harness contracts, constitution rules,
MCP launcher behavior, or cross-repo naming policy, so moving them into an app
test tree would hide their ownership.

App-owned script tests should live with the app when the script and all of its
runtime assumptions are app-local. The description service keeps script CLI
tests under `apps/prototype-description-service/recognition/tests/scripts/`;
WordPress plugin-only helpers should follow the plugin's test tree instead of
adding new root-level tests.

Hook tests belong beside their hooks in `scripts/hooks/test_*.py`.

Task-ephemeral guards: these should not remain as live root tests after the
task is closed; either generalize the assertion into a durable doc/tooling
contract or remove the guard once it only protects a historical task plan or
run log.

## localwp-runtime.sh

Resolve LocalWP runtime paths dynamically instead of relying on the hashed
`~/Library/Application Support/Local/run/<hash>/...` directory directly.

```bash
./scripts/localwp-runtime.sh socket
./scripts/localwp-runtime.sh php-bin
```

Supports `LOCALWP_SOCKET` and `LOCALWP_PHP_BIN` env overrides.

## localwp-wp.sh

Run WP-CLI against LocalWP without hard-coding the volatile MySQL socket path or
depending on the shell's default PHP.

```bash
./scripts/localwp-wp.sh --path="$HOME/Development/wp-context-alt-text/app/public" option get siteurl
./scripts/localwp-wp.sh --path="$HOME/Development/wp-context-alt-text/app/public" plugin status alt-context
./scripts/localwp-wp.sh --print-plan
```

Behavior:

- prefers `wp-nightly` when available for PHP 8.5+ compatibility
- otherwise runs stable `wp` under `php@8.4` when present
- otherwise falls back to the default PHP resolved by `localwp-runtime.sh`
- injects the discovered LocalWP MySQL socket via `mysqli.default_socket`
- mutes WP-CLI's bundled-phar deprecation noise at the source via
  `error_reporting` (warnings/notices/errors stay visible)

Supports `LOCALWP_WP_BIN`, `LOCALWP_WP_NIGHTLY_BIN`, `LOCALWP_WP_PHP84_BIN`,
`LOCALWP_WP_DISABLE_PHP84`, `LOCALWP_WP_DISABLE_NIGHTLY`,
`LOCALWP_WP_ERROR_REPORTING`, `LOCALWP_SOCKET`, and `LOCALWP_PHP_BIN` env
overrides. Set `LOCALWP_WP_ERROR_REPORTING=E_ALL` to surface deprecations when
debugging plugin code. Deprecation muting is bootstrap-scoped — a command that
boots WordPress with `WP_DEBUG=true` re-enables `E_DEPRECATED`.

Running `wp` directly (bypassing this wrapper) does not get the mute; use the
wrapper, or pass `WP_CLI_PHP_ARGS="-d error_reporting='E_ALL & ~E_DEPRECATED & ~E_USER_DEPRECATED'"`.

## localwp-gate-status.sh

Summarize the LocalWP gate state for `E15-3a` in one JSON payload:

```bash
./scripts/localwp-gate-status.sh --wp-path "$HOME/Development/wp-context-alt-text/app/public"
```

Output includes:

- `site_url`
- `tenant_uuid`
- plugin `status` and `version`
- plugin Settings payload (`url_source`, `key_source`, masked last4)
- effective key fingerprint (12-char SHA-256 prefix, never raw)
- current `/settings/test` probe response

Supports `LOCALWP_GATE_WP_WRAPPER` if you need to point the helper at an
alternate LocalWP WP-CLI wrapper during tests or debugging.

## localwp-db.sh

Connect to the LocalWP MySQL database without needing to know the volatile socket path.

```bash
./scripts/localwp-db.sh                                 # Interactive shell
./scripts/localwp-db.sh -e "SHOW TABLES LIKE '%acx%'"   # Run a query
./scripts/localwp-db.sh -e "SELECT * FROM wp_acx_clusters"
```

Supports `LOCALWP_SOCKET`, `LOCALWP_DB_NAME`, `LOCALWP_DB_USER`, `LOCALWP_DB_PASS`, and `LOCALWP_MYSQL_BIN` env overrides.

## mcp/

Contains the remaining legacy/reference file:

VS Code now calls the installed console scripts directly via `.vscode/mcp.json`.

- **`unified_server.py`** -- legacy/reference implementation of the non-handoff repo-intel MCP workflow. It is no longer the handoff runtime and intentionally returns deprecation errors for all handoff tool calls. Retained only as a reference for any future non-handoff MCP extraction.

`unified_server.py` is no longer the handoff runtime. It remains only as legacy/reference code for any future extraction of non-handoff repo-intel workflows.

## worktree-lane

Helper for the orchestrator/worker pattern described in [instructions.md](../docs/workbay/instructions.md).

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
- `make lane-run` launches the selected execution backend in the lane worktree using that generated prompt, requires a structured final handoff payload, and then auto-submits either `lane-handoff` or a blocked `lane-report` based on the result. `BACKEND=codex-cli` uses `codex exec`; `BACKEND=codex-subagent` routes through the Codex app-server bridge. Orchestrator-started `codex-subagent` workers can now inherit, explicitly set, or auto-tune reasoning effort per lane cycle.
- Lanes may declare manifest-driven preflight gates. For example, `backend-domain` now checks local Postgres/env readiness before any subagent turn and will auto-submit `needs_guidance` if the DB capability is unavailable.
- `make handoff-inbox` is the orchestrator polling command. It shows open worker-to-orchestrator lane messages and the latest merge-ready or blocked worker reports across lanes.
- `make lane-dispatch ... MESSAGE="..."` is the orchestrator assignment command. It records a lane message in MCP and regenerates `CURRENT_TASK.json`.
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
- shared-state `mcp-workbay-handoff lane-upsert` (note: lane-* verbs are dropped from mcp-workbay-handoff>=0.12.0; see upstream findings)
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
  --required-doc docs/workbay/instructions.md \
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
