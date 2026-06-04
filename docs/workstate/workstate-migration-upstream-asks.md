# Workstate migration — upstream asks (canonical package gaps)

> Recorded during `MAINT-workstate-migration-20260530` (follow-up completing the
> deferred lifecycle-wrapper-tooling cutover from legacy `agentic-*` to
> `workstate`). These are gaps in the **consumed** canonical packages
> (`mcp-workstate-handoff`, `mcp-workstate-orchestrator`,
> `workstate-bootstrap`/`workstate-system`) that this repo cannot fix from its
> own checkout (Plugin Boundary Rule). They are tracked here so the canonical
> repo can absorb them; this consumer was repointed to the nearest available
> surface and the residual gaps documented rather than reimplemented locally.

## A. `maint-start` / `maint-archive-stale` have no canonical lifecycle equivalent

The canonical `Makefile.d/lifecycle.mk` + `scripts/workstate/lifecycle` CLI has
`task-start` (MODE=here creates a branch in the current repo) but no path to
**register a `MAINT-*` row against the repo root with no feature branch / no
linked worktree**, nor a stale-MAINT garbage-collector. This repo's
`make maint-start` (scripts/maint-start.sh + scripts/_maint_start_inline.py) and
`make maint-archive-stale` (scripts/maint_archive_stale.py) were kept and
repointed to `workstate_handoff_mcp` because the CLAUDE.md startup protocol
requires them. **Ask:** canonical lifecycle should absorb a `maint-start` /
`maint-archive-stale` (or `task-start --no-branch` + `tasks-gc`) surface.

## B. Handoff CLI dropped the lane-data verbs (now MCP-tool-only)

`mcp-workstate-handoff` 0.12.0 dropped these CLI subcommands that the lane
workflow depends on: `lane-upsert`, `lane-message`, `lane-message-list`,
`lane-message-update`, `lane-report`, `lane-report-list`. They now exist only as
orchestrator **MCP tools** (`manage_worktree_lane`, `lane_communication`,
`worker_reports`). `make` / bash cannot invoke MCP tools, so these consumer
targets execute dropped verbs and fail at runtime:
`make lane-dispatch` (mk/lane-lifecycle.mk), `make lane-inbox`,
`make lane-intake` (mk/lane-maintenance.mk), and `scripts/worktree-lane`
upsert/report/message operations. The orchestrator CLI's `dispatch` subcommand
is a partial replacement for `lane-upsert` only. **Ask:** either expose the
lane-data verbs on the `mcp-workstate-orchestrator` CLI, or reimplement the lane
workflow against the MCP tools upstream in `workstate-system`.

## C. Handoff CLI redesigned verbs (consumer recipes left at old flag-shapes)

These verbs were redesigned, not dropped — direct equivalents exist with
different invocation shapes: `test` → `event` (event_kind=test_result),
`blocker` → `event` (event_kind=blocker), `artifact-search` → `artifacts`,
`handoff-close-check` → `integrity-check --kind close`. The consumer lane
recipes (mk/lane-worker.mk `lane-check`; mk/lane-maintenance.mk `lane-intake`)
were left calling the old shapes pending an upstream decision on whether the
lane workflow is reworked in `workstate-system` rather than this consumer.

## D. Canonical `lifecycle.mk` `tasks-gc` target calls a non-existent subcommand

`Makefile.d/lifecycle.mk` defines `tasks-gc: @mcp-workstate-handoff tasks-gc`,
but `tasks-gc` is not a `mcp-workstate-handoff` subcommand (the gc path is
`archive --operation gc` / a `tasks` operation). **Ask:** fix the canonical
fragment.

## E. Canonical `check-agent-workflows` drops the codex router-block check

Canonical `Makefile.d/workflows.mk` `check-agent-workflows` runs the generator
`--check` + facade + settings-pin checks but not `--check-codex-router-blocks`.
This consumer keeps a repo-local `check-codex-command-router` target and added it
to `check-all` to preserve coverage. **Ask:** canonical `check-agent-workflows`
should include the codex router-block validation (the generator already supports
the flag).

## F. Bootstrap hoist gap — workflow generator scripts deleted but not symlinked

The migration install (commit `1fcac802`) deleted `scripts/generate_agent_workflows.py`,
`scripts/check_workflow_facade.py`, and `scripts/validate_claude_settings_pin.py`
from the consumer root but did not symlink them back, leaving canonical
`Makefile.d/workflows.mk` (which resolves the generator relative to the consumer
root) broken. Fixed locally by symlinking the three scripts into `scripts/` →
`.workstate/remote/packages/workstate-system/scripts/`. **Ask:**
`workstate-bootstrap` should hoist these shared scripts (and track them in
`.workstate-bootstrap.json` `surfaces`) like the `Makefile.d/*.mk` and
`scripts/hooks` symlinks it already manages. This consumer now carries those
local symlinks and ledger entries to keep the branch mergeable; the upstream ask
is to make future installs materialize them without consumer-side repair.

## G. Shared Git hooks should resolve guards relative to the hook directory

`scripts/hooks` is an ignored symlink to the canonical `workstate-system`
surface. Its `git/post-checkout` hook resolves guard helpers through
`GUARD_DIR`, but `git/pre-push`, `git/post-merge`, `git/post-rewrite`,
`git/post-commit`, and `git/pre-commit` still resolve helpers via
`$REPO_ROOT/scripts/hooks/...`. That misses in nested source or hoisted
consumer layouts where the git root is not the shared hook source. **Ask:**
update the canonical `workstate-system/scripts/hooks/git/*` hooks to use the
same `HOOK_DIR` / `GUARD_DIR` pattern as `post-checkout`.

## H. Bootstrap Stop-hook adapter should not require absolute consumer paths

`workstate-bootstrap==0.7.3 doctor --target .` reports
`hook_adapter_drift: .claude/settings.json` when this repo keeps the managed
Claude Stop hook portable as
`python3 "$CLAUDE_PROJECT_DIR/scripts/hooks/compact-session.py"`. Running repair
would rewrite the checked-in hook adapter to an absolute consumer-root command
such as `/Users/.../scripts/hooks/compact-session.py`, which conflicts with this
repo's no-user-local-path policy and makes the committed settings non-portable.
**Ask:** change the canonical compact-session adapter declaration to use an
environment-relative or workspace-relative command, and teach doctor/repair to
accept that portable form.

## Resolved during this migration (not an upstream ask)

- `workstate_orchestrator_mcp.orchestration.lane_prompt` raised
  `AttributeError: module 'importlib' has no attribute 'util'` on import under
  orchestrator 0.4.7; **fixed** by upgrading to 0.5.0.
