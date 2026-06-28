# Workstate migration — upstream asks (canonical package gaps)

> Recorded during `MAINT-workstate-migration-20260530` (follow-up completing the
> deferred lifecycle-wrapper-tooling cutover from legacy `agentic-*` to
> `workstate`). These are gaps in the **consumed** canonical packages
> (`mcp-workbay-handoff`, `mcp-workbay-orchestrator`,
> `workbay-bootstrap`/`workbay-system`) that this repo cannot fix from its
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
repointed to `workbay_handoff_mcp` because the CLAUDE.md startup protocol
requires them. **Ask:** canonical lifecycle should absorb a `maint-start` /
`maint-archive-stale` (or `task-start --no-branch` + `tasks-gc`) surface.

## B. Handoff CLI dropped the lane-data verbs (now MCP-tool-only)

`mcp-workbay-handoff` 0.12.0 dropped these CLI subcommands that the lane
workflow depends on: `lane-upsert`, `lane-message`, `lane-message-list`,
`lane-message-update`, `lane-report`, `lane-report-list`. They now exist only as
orchestrator **MCP tools** (`manage_worktree_lane`, `lane_communication`,
`worker_reports`). `make` / bash cannot invoke MCP tools, so these consumer
targets execute dropped verbs and fail at runtime:
`make lane-dispatch` (mk/lane-lifecycle.mk), `make lane-inbox`,
`make lane-intake` (mk/lane-maintenance.mk), and `scripts/worktree-lane`
upsert/report/message operations. The orchestrator CLI's `dispatch` subcommand
is a partial replacement for `lane-upsert` only. **Ask:** either expose the
lane-data verbs on the `mcp-workbay-orchestrator` CLI, or reimplement the lane
workflow against the MCP tools upstream in `workbay-system`.

## C. Handoff CLI redesigned verbs (consumer recipes left at old flag-shapes)

These verbs were redesigned, not dropped — direct equivalents exist with
different invocation shapes: `test` → `event` (event_kind=test_result),
`blocker` → `event` (event_kind=blocker), `artifact-search` → `artifacts`,
`handoff-close-check` → `integrity-check --kind close`. The consumer lane
recipes (mk/lane-worker.mk `lane-check`; mk/lane-maintenance.mk `lane-intake`)
were left calling the old shapes pending an upstream decision on whether the
lane workflow is reworked in `workbay-system` rather than this consumer.

## D. Canonical `lifecycle.mk` `tasks-gc` target calls a non-existent subcommand

`Makefile.d/lifecycle.mk` defines `tasks-gc: @mcp-workbay-handoff tasks-gc`,
but `tasks-gc` is not a `mcp-workbay-handoff` subcommand (the gc path is
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
`.workbay/remote/packages/workbay-system/scripts/`. **Ask:**
`workbay-bootstrap` should hoist these shared scripts (and track them in
`.workbay-bootstrap.json` `surfaces`) like the `Makefile.d/*.mk` and
`scripts/hooks` symlinks it already manages. This consumer now carries those
local symlinks and ledger entries to keep the branch mergeable; the upstream ask
is to make future installs materialize them without consumer-side repair.

## G. Shared Git hooks should resolve guards relative to the hook directory

`scripts/hooks` is an ignored symlink to the canonical `workbay-system`
surface. Its `git/post-checkout` hook resolves guard helpers through
`GUARD_DIR`, but `git/pre-push`, `git/post-merge`, `git/post-rewrite`,
`git/post-commit`, and `git/pre-commit` still resolve helpers via
`$REPO_ROOT/scripts/hooks/...`. That misses in nested source or hoisted
consumer layouts where the git root is not the shared hook source. **Ask:**
update the canonical `workbay-system/scripts/hooks/git/*` hooks to use the
same `HOOK_DIR` / `GUARD_DIR` pattern as `post-checkout`.

## H. Bootstrap Stop-hook adapter should not require absolute consumer paths

`workbay-bootstrap==0.7.3 doctor --target .` reports
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

The workstate MCP runtime version (`mcp-workbay-handoff`,
`mcp-workbay-orchestrator`) is hand-fanned across ~14 consumer references
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
     `.workbay/remote/`, `source: shared` from `workbay-system`) is
     currently in lockstep (`0.12.3`/`0.6.0`) but only by hand. The bump
     belongs upstream in `workbay-system` / `agentic-protocol-monorepo`, not
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

`workbay-bootstrap install` materializes the gitignored overlay
(`.workbay/`, `.claude-plugin/`, `Makefile.d`, `scripts/workstate`,
`scripts/hooks`, …) once in the primary worktree. **Linked git worktrees**
(`git worktree add`, and Claude Code's auto-worktrees under
`.claude/worktrees/<name>/`) share the same `.git` but NOT gitignored files, so
they start with the overlay entirely absent. Only tracked files survive — e.g.
`.claude/settings.json` keeps `enabledPlugins: workbay-system@…=true`, so the
plugin is *enabled but unresolvable* → zero skills load, and `make` workflow
targets fail (missing `Makefile.d`). Today each worktree must be repaired by
hand (this repo symlinked the four surfaces to the root's copy). This is the
"works out of the box" gap: it should be solved once in the package, not
re-patched per consumer per worktree.

**Ask (capability — `workbay-bootstrap`):** a worktree-aware materialization
path, e.g. `workbay-bootstrap adopt-worktree --target <wt>` (or making
`install`/`repair` detect a linked worktree). It should **symlink the shared +
generated surfaces to the primary worktree's already-materialized overlay**
rather than re-cloning the remote per worktree (`.task-state/` stays
per-worktree). The canonical surface list already lives in the ledger, so only
the package can do this without a consumer hardcoding overlay-internal paths.

**Ask (trigger):** git has no native post-worktree-add hook, and Claude Code
auto-worktrees are created by the harness (knows nothing of workstate), so the
robust catch-all is a **session-start self-heal** — this is exactly layer (3)
of the WS-PKG-DELIVERY-01 durable direction (`make context` /
`.claude/settings.json` SessionStart runs `workbay-bootstrap doctor` +
auto-repair). Make that doctor+repair worktree-aware and it fixes every entry
path (raw `git worktree add`, `make task-start`, Claude Code auto-worktree) the
same way. For the `make task-start` path specifically, the shared
`lifecycle.mk` can call the adopt step directly.

**Consumer-template note:** if the upstream chooses symlink materialization, the
consumer `.gitignore` must use slashless patterns (`/.workstate`,
`/.claude-plugin`) — a dir-only pattern (`.workbay/`) does NOT match a
symlink (git treats it as a file), so the symlink shows up untracked. The
`workbay-bootstrap` `.gitignore` template should ship the slashless form.

## K. Close-check gate validates recorded evidence but never RUNS verification commands

`handoff_close_check` / `integrity-check --kind close`
(`workbay_handoff_mcp/decisions.py`) enforces that `test_result` evidence
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

## L. compact-session.py Stop hook not re-wired post-workbay migration

The `compact-session.py` hook script and the Stop hook wiring in `.claude/settings.json`
were both left in a broken state after the workbay rename (2026-06-27):

1. **Package name not updated** — the hook imported `workstate_handoff_mcp` (old name)
   throughout; after the rename the package is `workbay_handoff_mcp`. The consumer had
   to manually `sed` all 18 occurrences. The canonical hook script in `workbay-system`
   should be updated to use the new package name and the bootstrap install/repair cycle
   should verify the package is importable before declaring success.

2. **Stop hook not wired** — `.claude/settings.json` / `settings.hooks.json` had no
   `Stop` entry after the bootstrap re-materialize; the hook script existed on disk but
   was never called. The consumer had to add the Stop entry manually. **Ask:**
   `workbay-bootstrap install` / `repair` should include the `compact-session.py` Stop
   hook entry in the managed `.claude/settings.json` surface alongside the existing
   `SessionStart` and `PreToolUse`/`PostToolUse` entries — and should idempotently
   re-add it on `repair` if absent.

3. **Harness-protocol permitted_main_surfaces gap** — `.claude/settings.json` and
   `.claude/settings.hooks.json` were not listed as `permitted_main_surfaces` in
   `docs/workbay/contracts/harness-protocol.yaml`, which caused the main-branch guard
   (BR-21) to block edits to operator config under a valid MAINT-* task whenever
   unrelated code files were dirty. Fixed locally by adding these two patterns to the
   contract. **Ask:** the canonical `harness-protocol.yaml` template in `workbay-system`
   (or `workbay-bootstrap`) should ship these patterns pre-populated so consumer installs
   don't hit this block on first operator-config edit.

4. **reinject-context.py also has stale workstate_handoff_mcp imports** — the
   `reinject-context.py` hook (SessionStart surface) imports `workstate_handoff_mcp`
   (12 occurrences) and uses `WORKSTATE_REINJECT_*` env var names. The consumer
   manually sed-patched `reinject-context.py` for the package name; the env var
   names in both the hook and the tunables table in `harness-protocol.yaml` should
   be audited for the rename. **Ask:** same fix as item 1 above, applied to the
   reinject hook and its documented tunables.

5. **reinject-context.py not wired in SessionStart** — same gap as item 2 for the
   Stop hook. The contract notes the reinject hook is "opt-in, manifest-declared in
   `portable_commands.json` hooks[]", but bootstrap should wire it alongside
   `compact-session.py` in `.claude/settings.json` `SessionStart` — these two hooks
   are the read/write pair of the compaction system and neither is useful without
   the other.

**Consumer mitigation (this repo, 2026-06-27):** replaced all `workstate_handoff_mcp`
imports with `workbay_handoff_mcp` in local copies of `compact-session.py` and
`reinject-context.py`; added `Stop` hook entry; added `.claude/settings.json` and
`.claude/settings.hooks.json` to `permitted_main_surfaces` in the harness contract.
The `reinject-context.py` SessionStart wiring was deferred pending operator confirmation
(see §M gap 2).

## M. 50k-token compaction + semantic reinjection — architecture implemented, 3 deployment gaps

**Design intent (confirmed).** The compaction system is designed to:

- Fire after every **50 000 new tokens** since the last compaction (Stop hook gate;
  `DEFAULT_MIN_NEW_TOKENS = 50_000` in `workbay_handoff_mcp.compaction`).
- At compaction, **embed the new-turn anchor text** into a vector stored in
  `session_compactions.anchor_vector` via `embed_compaction_anchor_on_write()`.
- At the next SessionStart, **reinject semantically-ranked concepts** from prior
  compactions via `reinject-context.py` + `build_semantic_reinjection_packet()`, with
  `ReinjectionConfig` controlling top-K (default 8), min score (0.35), MMR weight
  (0.7), and snippet budget (1 500 chars).

**All architecture is present in `mcp-workbay-handoff`.** None of it is active because
of three deployment gaps:

### Gap 1 — Bootstrap does not provision the ONNX model artifacts at install time

The embedding provider is correctly designed as a **local ONNX model** (no external API
calls during sessions). `EmbeddingProvider.from_env()` reads four env vars that point to
provisioned file paths:

```
WORKBAY_HANDOFF_EMBEDDING_MODEL=<path-to-onnx-model>
WORKBAY_HANDOFF_EMBEDDING_TOKENIZER=<path-to-tokenizer>
WORKBAY_HANDOFF_EMBEDDING_MODEL_SHA256=<hex-digest>
WORKBAY_HANDOFF_EMBEDDING_TOKENIZER_SHA256=<hex-digest>
```

The design is correct; what is missing is the **bootstrap provisioning step**. Currently
`workbay-bootstrap install` / `repair` does not download the model artifacts or write
these env vars into any harness config surface, so `EmbeddingProvider.from_env()`
always returns `None` and embeddings silently degrade. **Ask:**

1. `workbay-bootstrap install` should, by default, download a pinned ONNX embedding
   model (small, license-clear; e.g. a MiniLM-L6-v2 ONNX export), verify SHA256
   against the pinned digest, and write the four `WORKBAY_HANDOFF_EMBEDDING_*` env
   vars into a harness-owned config surface (e.g. a `.workbay/embedding.env` file
   sourced by the hook launcher, or injected into `.claude/settings.json` `env:`).

2. Provide an explicit **opt-out** flag — `workbay-bootstrap install --no-embeddings`
   or an env var `WORKBAY_HANDOFF_EMBEDDINGS_DISABLED=1` — so operators who cannot or
   do not want the download can skip it. The feature must default to **active** (download
   + wire on first install) but remain fully optional.

3. `workbay-bootstrap repair` should detect when the artifacts are absent or SHA256
   mismatch and re-download, matching the same idempotent repair logic used for other
   managed surfaces.

4. The degrade path when the model is absent (provider=None → non-semantic reinjection,
   no error) is correct and must be preserved.

### Gap 2 — SessionStart reinject hook not wired by bootstrap

`reinject-context.py` exists on disk but no `SessionStart` entry exists in
`.claude/settings.json` after bootstrap install. Same root cause as §L item 5.
**Ask:** `workbay-bootstrap install` / `repair` should wire the reinject hook in
`SessionStart` alongside the Stop hook for `compact-session.py`.

### Gap 3 — Semantic mode disabled by default; no documented activation path

Even with the hook wired and a provider configured, semantic reinjection is gated on
`WORKSTATE_REINJECT_SEMANTIC=1` (or `WORKBAY_REINJECT_SEMANTIC=1` after the rename —
**the env var name itself may need migration**). No bootstrap step sets this and no
install-time prompt asks about it. **Ask:** once the API provider path exists (Gap 1),
set semantic mode on by default when a provider is resolvable; or emit a one-time
post-install advisory naming the env var to enable it.

### Clarification needed — 50k trigger is session-end gated, not mid-session interval

The current Stop hook fires **once** at session end and then checks if 50k+ new tokens
have accumulated. This is a threshold gate, not a periodic mid-session trigger. If the
intent is to compact at 50k-token intervals **within** a session (e.g. every time
context grows by 50k, compact and reinject), that requires a `UserPromptSubmit` or
`PreToolUse` hook that counts running token usage and triggers `compact_session()`
mid-turn. **Ask:** clarify whether the 50k gate is intended as session-end-only (current
behaviour) or as a continuous within-session interval trigger, and implement the
mid-session path if the latter is intended.

## Resolved during this migration (not an upstream ask)

- `workbay_orchestrator_mcp.orchestration.lane_prompt` raised
  `AttributeError: module 'importlib' has no attribute 'util'` on import under
  orchestrator 0.4.7; **fixed** by upgrading to 0.5.0.

## Hand-completion status — `MAINT-workbay-migration-cleanup-20260628`

Completed by hand (this branch, no installer run): `docs/workstate/**`→`docs/workbay/**`
rename staged; override source renamed `workstate-overrides/`→`workbay-overrides/workbay-system/`;
install ledger `.workstate-bootstrap.json`→`.workbay-bootstrap.json`; 11 vestigial generic
`docs/workbay/skills/*` duplicates removed (real skills load from the generated plugin tree);
stale prose/identifier `workstate`→`workbay` renames; `.gitignore` re-ignores the legacy
`.workstate/` clone + drops the stale `WORKSTATE_BOOTSTRAP` marker; `Makefile`
`WORKSTATE_BOOTSTRAP LIFECYCLE INCLUDE` sentinel → `WORKBAY_BOOTSTRAP`; two migration-broken
doc-lock tests reconciled (`test_curation_refresh_status_docs.py` path; obsolete
`test_shared_agentic_surface_doc.py` retired — its section was removed upstream).

**Installer-gated remainder (deferred — requires `workbay-bootstrap install`, intentionally not run):**

- The overlay is still mounted on the legacy clone: `scripts/hooks`, `.github/hooks`,
  `Makefile.d`, `scripts/workstate` are symlinks into `.workstate/remote/...workstate-system...`,
  and `.workbay/remote` does not exist (package-mode install left the symlinks un-repointed).
  Until the installer repoints them, `.workstate/` (≈200 MB) cannot be physically removed and
  `scripts/overlay_resolver.py` (`_CLONE_SUBDIR = (".workstate","remote")`) must keep resolving
  there. The `.workstate/`-path references in `overlay_resolver.py`, `check_harness_sync.py`,
  `generate_agent_workflows.py`, `apply_cursor_skills_only_surface.py`, and the
  `scripts/workstate`/`workstate_system/payload` mentions in `consumer-setup.md` are therefore
  **keep-until-cutover**, not stale misses — renaming them by hand would point at nonexistent paths.
- `scripts/hooks/guard-main-branch.sh` still invokes `mcp-workstate-handoff` and reads
  `WORKSTATE_SKIP_ACTIVE_TASK_PROBE`; that file is overlay-symlinked (upstream-owned), so the
  durable fix lands when the installer re-materializes the hook subtree against the workbay package.
- `workbay-overrides/workbay-system/skills/branch-review/SKILL.{md,base.md}` retain
  `docs/workstate/...` links; `SKILL.base.md` is digest-locked (`overrides.lock.json`
  `upstream_digest`) as a verbatim upstream-base mirror, so it follows on the next upstream re-sync.
- `packages/codex-subagent-bridge` still depends on the published `mcp-workstate-*` /
  `workstate-protocol` artifacts (`uv.lock`) — a dependency bump + `uv lock` regeneration, tracked
  as its own task.
- Generic `docs/workbay/templates/*` (8 byte-identical to upstream, 6 drifted) remain tracked;
  offloading them to the overlay needs an overlay delivery path (installer), unlike the
  contracts/rules offload already completed.

## Refactoring-lens enforcement gaps (workbay code-gen / review skills)

Audited 2026-06-28 (MAINT-workbay-migration-cleanup): do the shipped code-gen/review skills
apply + enforce the distilled engineering literature so junior agents produce well-factored
code (less downstream refactoring)? **Partially — and the enforcement that works is repo-local,
not shipped.**

- **Upstream `refactor` skill exists but is not materialized here.** Canonical
  `.../payload/skills/refactor/body.md` carries the full Fowler/Beck smell catalog +
  characterization-tests-before-move, but it is absent from this repo's
  `.workbay/generated/plugins/workbay-system/effective/claude/skills/` and is cross-referenced
  by **zero** impl/review skills. A junior reaches it only by explicitly typing "refactor". **Ask:**
  (a) confirm why `refactor` is filtered out of the consumer Claude tree and re-enable it; (b) add
  a "See Also → refactor" link + a Red-Flag re-entry ("diff is growing a second responsibility →
  stop, run refactor") to `incremental-implementation` and `branch-review`.

- **The enforced lens is an untracked, local-only file.** `docs/workbay/rules/engineering-heuristics.md`
  (the 8-book trigger→rule lexicon that `branch-review-guide.md` + `planning-review-guide.md`
  wire in) is **not tracked, gitignored under `/docs/workbay/rules`, and not in the upstream
  payload** — it vanishes on a fresh clone / CI / overlay re-materialization, silently reverting
  review to the design-thin upstream guide (canonical `branch-review-guide` has only partial Fowler
  smells, no resilience/latency/idempotency lens). **Ask:** promote `engineering-heuristics.md` and
  the guide checklist extensions into the workbay-system payload (or move them to a tracked,
  clearly repo-owned path) so the lens survives regeneration. Interim repo guard: a `make check-*`
  assertion that the guides still reference `engineering-heuristics.md`.

- **Generation skills nudge cadence/NFR but not smell-avoidance.** Effective `tdd` /
  `incremental-implementation` / `scope` carry repo-overlaid design/scale/NFR cues (good), but none
  makes smell-*avoidance* (Large Class / Long Function / Data Clumps / Primitive Obsession /
  cohesion / SoC "and"-test) a **produce-first** gate — that shaping is only caught at review.
  **Repo-fixable (mode:patch):** add a 3-4 line "produce-first shape" cue to the
  `incremental-implementation` effective patch (cohesion/SoC "and"-test, ≤~400-line / ≤3-nesting
  budgets, Extract-on-second-responsibility, strategy-map-over-enum-switch) → `engineering-heuristics.md`.

- **`plan-analyze` triage is design-blind.** Its 7 passes (duplication / ambiguity / underspec /
  constitution / coverage / terminology / impl-grounding) have no complexity / coupling / cohesion /
  failure-mode pass, so a plan that bakes in a god-class or unbounded-result design passes triage
  untouched. **Repo-fixable (mode:patch):** add an 8th "design-quality & failure-mode grounding"
  pass mirroring the wiring already in `planning-review-guide.md`.

- **`review-parallel` guarantees no rubric of its own** — reviewers apply the factoring/design lens
  only if `reviewer_prompt_template` routes them to `branch-review-guide` + `engineering-heuristics`.
  Ensure that prompt cites them explicitly.
