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

## I. MCP pin source-of-truth: overlay manifest drift + generation cutover (coordinate with E17-15)

The workstate MCP runtime version (`mcp-workstate-handoff`,
`mcp-workstate-orchestrator`) is hand-fanned across ~14 consumer references
(`.mcp.json`, `.vscode/mcp.json`, `.codex/config.toml`, `Makefile`, CI, and
operational docs/doc-tests). This is a single-source-of-truth violation that
already produced live drift twice: `.github/copilot-instructions.md` lagged two
minor versions, and the 2026-06-04 bootstrap pin sync bumped the three live
harness configs to `0.12.3`/`0.6.0` while the Makefile canonical, CI workflow,
and all doc/doc-test references stayed at `0.12.1`/`0.5.2` (fixed in this
slice). Two halves, split by ownership:

1. **Consumer-side (done here):** added `scripts/check_mcp_pins.py` +
   `make check-mcp-pins` (wired into `check-all`). Canonical = the Makefile
   `MCP_*_PACKAGE` pins; every editable current-pin reference must match.
   Frozen records (`docs/adrs|specs|tasks/`) are exempt. This is the consumer
   "manifest check" that the E17-15 verification table calls for
   ([E17-15 task plan](../tasks/17.0/E17-15-agentic-plugin-distribution-task-plan.md)
   line ~74). It also emits ADVISORIES for the overlay `mcp_servers.yaml`, the
   `scripts/README.md` range mention, and the `CLAUDE.md` git+ssh tag refs.

2. **Upstream/downstream (NOT fixed here — out of bounds):**
   - The overlay `config/agent-workflows/mcp_servers.yaml` (symlink into
     `.workstate/remote/`, `source: shared` from `workstate-system`) is
     currently in lockstep (`0.12.3`/`0.6.0`) but only by hand. The bump
     belongs upstream in `workstate-system` / `agentic-protocol-monorepo`, not
     this checkout (Plugin Boundary Rule). **Ask:** keep the manifest pins in
     lockstep with the consumer live-config pins (ideally derive/check one from
     the other in the shared generator).
   - The plugin generator (`scripts/generate_agent_workflows.py`, also overlay)
     and the live-config↔plugin-manifest parity belong to E17-15's downstream
     implementation in `agentic-protocol-monorepo`. Per ADR-010 / E17-15 the
     live harness configs remain the pin source of truth and emitted plugin
     manifests *preserve* them — so the consumer fix is the parity guard above,
     **not** a second generator path in this repo. Do not build live-config
     generation locally; it would duplicate and invert E17-15's decided model.

## J. Linked git worktrees do not inherit the bootstrap overlay (out-of-box gap)

`workstate-bootstrap install` materializes the gitignored overlay
(`.workstate/`, `.claude-plugin/`, `Makefile.d`, `scripts/workstate`,
`scripts/hooks`, …) once in the primary worktree. **Linked git worktrees**
(`git worktree add`, and Claude Code's auto-worktrees under
`.claude/worktrees/<name>/`) share the same `.git` but NOT gitignored files, so
they start with the overlay entirely absent. Only tracked files survive — e.g.
`.claude/settings.json` keeps `enabledPlugins: workstate-system@…=true`, so the
plugin is *enabled but unresolvable* → zero skills load, and `make` workflow
targets fail (missing `Makefile.d`). Today each worktree must be repaired by
hand (this repo symlinked the four surfaces to the root's copy). This is the
"works out of the box" gap: it should be solved once in the package, not
re-patched per consumer per worktree.

**Ask (capability — `workstate-bootstrap`):** a worktree-aware materialization
path, e.g. `workstate-bootstrap adopt-worktree --target <wt>` (or making
`install`/`repair` detect a linked worktree). It should **symlink the shared +
generated surfaces to the primary worktree's already-materialized overlay**
rather than re-cloning the remote per worktree (`.task-state/` stays
per-worktree). The canonical surface list already lives in the ledger, so only
the package can do this without a consumer hardcoding overlay-internal paths.

**Ask (trigger):** git has no native post-worktree-add hook, and Claude Code
auto-worktrees are created by the harness (knows nothing of workstate), so the
robust catch-all is a **session-start self-heal** — this is exactly layer (3)
of the WS-PKG-DELIVERY-01 durable direction (`make context` /
`.claude/settings.json` SessionStart runs `workstate-bootstrap doctor` +
auto-repair). Make that doctor+repair worktree-aware and it fixes every entry
path (raw `git worktree add`, `make task-start`, Claude Code auto-worktree) the
same way. For the `make task-start` path specifically, the shared
`lifecycle.mk` can call the adopt step directly.

**Consumer-template note:** if the upstream chooses symlink materialization, the
consumer `.gitignore` must use slashless patterns (`/.workstate`,
`/.claude-plugin`) — a dir-only pattern (`.workstate/`) does NOT match a
symlink (git treats it as a file), so the symlink shows up untracked. The
`workstate-bootstrap` `.gitignore` template should ship the slashless form.

## K. Close-check gate validates recorded evidence but never RUNS verification commands

`handoff_close_check` / `integrity-check --kind close`
(`workstate_handoff_mcp/decisions.py`) enforces that `test_result` evidence
exists and is tied to the current HEAD SHA, but it never *executes*
lint/typecheck/test — it trusts the recorded evidence. A broken tree can
therefore merge if evidence was recorded green while the working tree is
actually red: E15-26's `DashboardPage.test.tsx` (25 tests crashing on an
unmocked `useSyncHealth`) merged to main and was only caught when the e15-28
integration ran `make check` (ref E15-28 decision 748). The consumer cannot
fix this — the gate lives in the external package (Plugin Boundary Rule), and
"run the checks" is repo-specific, so the capability must be config-driven, not
hardcoded upstream. **Ask:** add a generic capability for the close-check to
RUN one or more consumer-configured verification commands (fail-closed on
non-zero exit) before it passes — e.g. a runtime-config
`close_check.required_commands: ["make check-all"]` — so the gate verifies the
working tree rather than only trusting recorded evidence. **Consumer mitigation
(this repo, MAINT-TYPECHECK-GATE-20260613):** a local `make pre-merge`
(= `make check-all`) run by habit before the close-check. This does NOT close
the bypass — it is not enforced by the gate — and is intentionally not built as
a bespoke changed-surface detector, which would be off the demo critical path
(per the 2026-06-11 MVP strategy assessment) and would duplicate the real fix
that belongs here.

## Resolved during this migration (not an upstream ask)

- `workstate_orchestrator_mcp.orchestration.lane_prompt` raised
  `AttributeError: module 'importlib' has no attribute 'util'` on import under
  orchestrator 0.4.7; **fixed** by upgrading to 0.5.0.
