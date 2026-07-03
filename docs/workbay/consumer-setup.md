# Consumer Setup

Use this guide when you want another private Daniel-owned repository to consume the hoisted workbay system without copying files by hand.

## Prerequisites

- macOS or Linux with `git`, `python3`, and `uv`
- Access to the private `darce/*` GitHub repositories over SSH
- A clean consumer repository root where the overlay should live

## Install

Install the `workbay` front-door tool from the pinned git ref (no PyPI), then materialize the overlay into the current repo. Bundle every package surface with `--with` so the single `uv tool` install resolves the whole stack from one ref:

```bash
REF=workbay-v0.3.6
R="git+https://github.com/darce/workbay.git@$REF"
uv tool install --no-sources \
  --with "$R#subdirectory=packages/workbay-protocol" \
  --with "$R#subdirectory=packages/mcp-workbay-handoff" \
  --with "$R#subdirectory=packages/mcp-workbay-orchestrator" \
  --with "$R#subdirectory=packages/workbay-bootstrap" \
  --with "$R#subdirectory=packages/workbay-system" \
  --from "$R#subdirectory=packages/workbay" \
  workbay
workbay install --target . --remote-ref "$REF"
```

`workbay` lands on `PATH` via `uv tool`, so invoke it directly — do not shell out to `./.venv/bin/workbay-bootstrap`. The install runs in package mode: it materializes the overlay from package data (no `.workbay/remote/` clone, no symlinks), writes `.workbay-bootstrap.json`, registers the two MCP servers via the `mcp_launch.py` shim, and wires `core.hooksPath`.
Keep the overlay ref pinned to the reviewed workbay tag (`workbay-v0.3.6`) until a newer release set is explicitly promoted.

After install, run one sanity check from the consumer root:

```bash
workbay doctor --target .
```

## State Paths

Default handoff state lives under the consumer repo, not the source monorepo:

- `workspace_root`: the consumer repository root
- default state directory: `.task-state`
- default database: `.task-state/handoff.db`
- default exports directory: `.task-state/exports`
- default dashboard: `DASHBOARD.txt`
- optional explicit current-task export: `CURRENT_TASK.json`

The supported path override surface is:

- `AGENT_HANDOFF_WORKSPACE_ROOT`
- `AGENT_HANDOFF_STATE_DIR`
- `AGENT_HANDOFF_DASHBOARD_PATH`
- `AGENT_HANDOFF_CURRENT_TASK_PATH`
- `AGENT_HANDOFF_EXPORTS_DIR`

`CURRENT_TASK.json` is task-scoped and on-demand. An explicit render or helper may write it, but do not assume it exists or is current.

If you set explicit relative paths, they resolve from `AGENT_HANDOFF_WORKSPACE_ROOT`, not from the process cwd.

## Update Workflow

Re-run the pinned `uv tool install` to upgrade the front-door tool and every bundled package surface, then `workbay update` to re-materialize the overlay:

```bash
REF=workbay-v0.3.6
R="git+https://github.com/darce/workbay.git@$REF"
uv tool install --no-sources \
  --with "$R#subdirectory=packages/workbay-protocol" \
  --with "$R#subdirectory=packages/mcp-workbay-handoff" \
  --with "$R#subdirectory=packages/mcp-workbay-orchestrator" \
  --with "$R#subdirectory=packages/workbay-bootstrap" \
  --with "$R#subdirectory=packages/workbay-system" \
  --from "$R#subdirectory=packages/workbay" \
  workbay
workbay update --target . --remote-ref "$REF"
```

Keep both the install ref and the overlay `--remote-ref` pinned to the same reviewed release set. When a newer release set is approved, bump `REF` and the `--remote-ref` together.

`workbay update --target . --remote-ref "$REF"` re-materializes the overlay from the requested ref's package data and refreshes `.workbay-bootstrap.json` with the new pinned ref.

## Doctor and Repair

Use `workbay doctor --target .` when the overlay looks wrong but you want diagnosis first:

```bash
workbay doctor --target .
```

Doctor should verify:

- the materialized overlay surfaces are present and current against the pinned ref
- `.workbay-bootstrap.json` records the expected pinned ref
- `core.hooksPath` still points at `scripts/hooks/git`
- the runtime can discover `AGENT_HANDOFF_WORKSPACE_ROOT` and `.task-state/handoff.db`

Use `workbay repair --target .` when the overlay is missing, corrupt, or drifted:

```bash
workbay repair --target .
```

Repair re-materializes the overlay from package data and re-wires the local MCP config and `core.hooksPath` to match the pinned ref.

## Git Hooks

The consumer overlay must include both harness hook trees:

- `.github/hooks/`
- `scripts/hooks/`
- `scripts/hooks/git`

Bootstrap wiring sets `core.hooksPath` to `scripts/hooks/git` so client-side hooks such as `post-checkout`, `post-merge`, `post-rewrite`, and `pre-push` run from the overlaid hook subtree.

In `context-alt-text-monorepo`, these hook and prompt payloads are
bootstrap-managed local/generated surfaces, not product source. Keep
`.github/hooks/`, `.github/prompts/`, `scripts/hooks/`, `scripts/workbay/`,
and `Makefile.d/` ignored here; fixes to reusable workflow behavior belong in
the downstream workbay/agentic-protocol source and should flow back through a
pinned `workbay update`. The tracked files in this repo should stay
limited to the install ledger, client config pins, docs/tests that lock those
pins, and the small Makefile shim needed to invoke the shared fragments.

You can verify the wiring directly:

```bash
git config core.hooksPath
```

Expected value:

```text
scripts/hooks/git
```

## Daemons

Daemons are opt-in. Leave them off unless you explicitly want the long-running orchestrator and worker loops.

Enable them through your local overlay contract:

```yaml
orchestrator:
  daemons:
    enabled: true
```

The controlling key is `orchestrator.daemons.enabled`. When disabled, daemon start paths should fail fast with an actionable message. When enabled, expect a startup warning that names poll intervals, query pressure, and token-cost implications.

## Plugin Overrides

Consumers that locally patch plugin-distributed components (skills, prompts) keep those patches under a plugin overrides tree, by convention `workbay-overrides/<plugin>/` (this repo: `workbay-overrides/workbay-system`). Each plugin directory carries:

- `overrides.yaml` — which components are overridden and in what mode.
- `overrides.lock.json` — provenance ledger: `base_remote_sha` plus, per component, the `base_path` of the materialized upstream copy and its `upstream_digest`.
- the materialized upstream base copy next to the local override, e.g. `skills/branch-review/SKILL.base.md` beside the patched `skills/branch-review/SKILL.md`.

Digest convention: `upstream_digest` is the whole-file sha256 of the materialized upstream base copy (`SKILL.base.md`), not of the generated base surface under `.workbay/generated/` — the generator injects harness-specific sections (e.g. Global Instructions), so its hash legitimately differs. `make check-overrides-digest` (wired into `make check-all`) validates every lock entry against the materialized base copy, so digest drift fails CI instead of surfacing on the next manual bootstrap update.

The `.workbay-bootstrap.json` manifest names this tree via the optional `plugin_overrides_path` field. The field is a forward-compat hook for the APD-07 durable-recipe-overrides release: workbay-bootstrap v0.1.22 does not read it, so it stays inert until the consumer updates to an APD-07-capable bootstrap. See `docs/workbay/contracts/overlay-manifest.yaml` for the contract entry.

## Troubleshooting

`AmbiguousWorkspaceContextError`

This means the repo has more than one active task candidate for the current workspace context. Resolve it by selecting the intended task explicitly before continuing, or archive stale active rows so the workspace resolves to one task again.

`ConsumerRootResolutionError`

This means the runtime could not infer a git-backed consumer root and you did not provide explicit path overrides. Set `AGENT_HANDOFF_WORKSPACE_ROOT` and, when needed, one or more of `AGENT_HANDOFF_STATE_DIR`, `AGENT_HANDOFF_DASHBOARD_PATH`, `AGENT_HANDOFF_CURRENT_TASK_PATH`, or `AGENT_HANDOFF_EXPORTS_DIR`.

Broken or drifted overlay

Run `workbay doctor --target .` first. If the overlay is broken or drifted, use `workbay repair --target .` instead of manually editing the materialized surfaces.

Wrong MCP launcher path

Consumer configs must call the installed console scripts directly. They should not reference monorepo-local helpers such as `scripts/mcp/mcp-server.sh`.

## Tenancy

Tenancy is by database file, not by shared-schema partitioning.

Each consumer repository keeps its own `.task-state/handoff.db`. Do not point multiple unrelated repos at one shared database unless you intentionally want them to share task state, findings, and dashboard outputs.

## Platform Support

The MVP target is Unix-like environments only: macOS and Linux.

The overlay relies on git-hook path wiring. Windows support is deferred until there is an explicit follow-on slice to define the expected hook behavior there.

## Lessons Learned (E17-10-followon, 2026-04-22)

### What worked

- Bootstrap install was clean for all three real consumers (`hoist-mvp-consumer`, `darce.github.io`, `altcontext-marketing-monorepo`): `agentic-bootstrap install --target .` wrote the overlay manifest, symlinked `.claude/skills`, and dropped 12+ hooks under `scripts/hooks/` on first run.
- Per-consumer DB isolation held: each consumer's `.task-state/handoff.db` only sees its own task_refs; cross-consumer probe via `get_handoff_state(task_ref=...)` showed zero foreign-ref leakage across three distinct DB files.
- The doc-lock test (`scripts/test_consumer_setup_doc.py`) caught both pin-bumps (handoff v0.4.1→v0.4.2 and orchestrator v0.1.2→v0.1.3) before they landed silently.

### What needed manual intervention

- The orchestrator's `pyproject.toml` pins `workbay-handoff-mcp` by exact git URL (`@v0.4.1`). Publishing handoff `v0.4.2` without bumping that URL pin caused pip resolution conflicts when consumers installed all three packages explicitly. Resolution: published `mcp-agent-orchestrator@v0.1.3` with the URL bumped to `@v0.4.2`, then re-pinned the consumer-setup doc to `@v0.1.3`.
- `agentic-bootstrap` resolved via `PATH` after `source .venv/bin/activate` matched a global `agentic-bootstrap` install instead of the venv binary on consumers where global script shims sat ahead of the venv on `PATH`. Workaround: always invoke via the explicit `./.venv/bin/agentic-bootstrap` path. Doc and bootstrap install instructions should prefer the explicit-path form.
- `agentic-bootstrap` v0.2.0 has no `--version` flag (only subcommands `install | status | doctor | update | repair`). Use `pip show agentic-bootstrap` for version reporting until a `--version` flag is added.
- `agentic-bootstrap doctor --target <empty-dir>` correctly exits 1 with `missing_manifest: .agentic-overlay.json`. Doctor is meant to flag drift, not to be used as a pre-install smoke. Only call `doctor` after `install`.

### Follow-on tasks opened

- `MAINT-orchestrator-pyproject-pin-policy` — decide whether orchestrator should pin handoff via URL (current) vs version-only constraint (e.g. `mcp-agent-handoff>=0.6.0,<0.7`) so cleanup tags don't force orchestrator retags.
- `MAINT-bootstrap-cli-version-flag` — add a `--version` flag to `agentic-bootstrap` so external smoke checks can verify the installed CLI without `pip show`.
- `MAINT-consumer-setup-explicit-venv-path` — update `consumer-setup.md` install snippets to prefer `./.venv/bin/agentic-bootstrap` over `agentic-bootstrap` to avoid global-PATH shadowing.
