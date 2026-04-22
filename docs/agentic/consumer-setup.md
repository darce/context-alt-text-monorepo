# Consumer Setup

Use this guide when you want another private Daniel-owned repository to consume the hoisted agentic system without copying files by hand.

## Prerequisites

- macOS or Linux with `git`, `python3`, and `pyenv`
- Access to the private `darce/*` GitHub repositories over SSH
- A project-local virtual environment or other Python 3.11+ environment on your PATH
- A clean consumer repository root where the overlay should live

## Install

Install the three package surfaces from their standalone repositories, then materialize the shared overlay into the current repo:

```bash
pip install "git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.4.2"
pip install "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.3"
pip install "git+ssh://git@github.com/darce/agentic-bootstrap.git@v0.2.0"

agentic-bootstrap install --target .
```

The install flow clones the shared agentic surface into `.agentic/remote/`, creates the overlay symlinks, writes `.agentic-overlay.json`, and wires the local MCP config files.

After install, run one sanity check from the consumer root:

```bash
agentic-bootstrap doctor
```

## State Paths

Default handoff state lives under the consumer repo, not the source monorepo:

- `workspace_root`: the consumer repository root
- default state directory: `.task-state`
- default database: `.task-state/handoff.db`
- default exports directory: `.task-state/exports`
- default dashboard: `DASHBOARD.txt`
- default current-task snapshot: `CURRENT_TASK.json`

The supported path override surface is:

- `AGENT_HANDOFF_WORKSPACE_ROOT`
- `AGENT_HANDOFF_STATE_DIR`
- `AGENT_HANDOFF_DASHBOARD_PATH`
- `AGENT_HANDOFF_CURRENT_TASK_PATH`
- `AGENT_HANDOFF_EXPORTS_DIR`

If you set explicit relative paths, they resolve from `AGENT_HANDOFF_WORKSPACE_ROOT`, not from the process cwd.

## Update Workflow

Use the package manager for MCP package upgrades and `agentic-bootstrap update` for the overlay clone:

```bash
pip install --upgrade "git+ssh://git@github.com/darce/mcp-agent-handoff.git"
pip install --upgrade "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git"
pip install --upgrade "git+ssh://git@github.com/darce/agentic-bootstrap.git"

agentic-bootstrap update
```

Keep the install step pinned to a reviewed tag. The upgrade step intentionally omits a tag so pip can resolve the latest published release for each package.

`agentic-bootstrap update` fetches the shared clone, checks out the requested ref, re-validates symlinks, and refreshes `.agentic-overlay.json` with the new remote SHA.

## Doctor and Repair

Use `agentic-bootstrap doctor` when the overlay looks wrong but you want diagnosis first:

```bash
agentic-bootstrap doctor
```

Doctor should verify:

- the clone exists at `.agentic/remote/`
- overlay symlinks resolve cleanly
- `core.hooksPath` still points at `scripts/hooks/git`
- the runtime can discover `AGENT_HANDOFF_WORKSPACE_ROOT` and `.task-state/handoff.db`

Use `agentic-bootstrap repair` when the overlay is missing, corrupt, or drifted:

```bash
agentic-bootstrap repair
```

If the shared clone contains uncommitted files, repair must stop and name the dirty files unless you pass the explicit dirty-worktree override supported by the tool.

## Git Hooks

The consumer overlay must include both harness hook trees:

- `.github/hooks/`
- `scripts/hooks/`
- `scripts/hooks/git`

Bootstrap wiring sets `core.hooksPath` to `scripts/hooks/git` so client-side hooks such as `post-checkout`, `post-merge`, `post-rewrite`, and `pre-push` run from the overlaid hook subtree.

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

## Troubleshooting

`AmbiguousWorkspaceContextError`

This means the repo has more than one active task candidate for the current workspace context. Resolve it by selecting the intended task explicitly before continuing, or archive stale active rows so the workspace resolves to one task again.

`ConsumerRootResolutionError`

This means the runtime could not infer a git-backed consumer root and you did not provide explicit path overrides. Set `AGENT_HANDOFF_WORKSPACE_ROOT` and, when needed, one or more of `AGENT_HANDOFF_STATE_DIR`, `AGENT_HANDOFF_DASHBOARD_PATH`, `AGENT_HANDOFF_CURRENT_TASK_PATH`, or `AGENT_HANDOFF_EXPORTS_DIR`.

Broken overlay symlinks

Run `agentic-bootstrap doctor` first. If the clone or symlinks are broken, use `agentic-bootstrap repair` instead of manually recreating links.

Wrong MCP launcher path

Consumer configs must call the installed console scripts directly. They should not reference monorepo-local helpers such as `scripts/mcp/mcp-server.sh`.

## Tenancy

Tenancy is by database file, not by shared-schema partitioning.

Each consumer repository keeps its own `.task-state/handoff.db`. Do not point multiple unrelated repos at one shared database unless you intentionally want them to share task state, findings, and dashboard outputs.

## Platform Support

The MVP target is Unix-like environments only: macOS and Linux.

The overlay relies on symlinks and git-hook path wiring. Windows support is deferred until there is an explicit follow-on slice to define the expected symlink and hook behavior there.

## Lessons Learned (E17-10-followon, 2026-04-22)

### What worked

- Bootstrap install was clean for all three real consumers (`hoist-mvp-consumer`, `darce.github.io`, `altcontext-marketing-monorepo`): `agentic-bootstrap install --target .` wrote the overlay manifest, symlinked `.claude/skills`, and dropped 12+ hooks under `scripts/hooks/` on first run.
- Per-consumer DB isolation held: each consumer's `.task-state/handoff.db` only sees its own task_refs; cross-consumer probe via `get_handoff_state(task_ref=...)` showed zero foreign-ref leakage across three distinct DB files.
- The doc-lock test (`scripts/test_consumer_setup_doc.py`) caught both pin-bumps (handoff v0.4.1→v0.4.2 and orchestrator v0.1.2→v0.1.3) before they landed silently.

### What needed manual intervention

- The orchestrator's `pyproject.toml` pins `agent-handoff-mcp` by exact git URL (`@v0.4.1`). Publishing handoff `v0.4.2` without bumping that URL pin caused pip resolution conflicts when consumers installed all three packages explicitly. Resolution: published `mcp-agent-orchestrator@v0.1.3` with the URL bumped to `@v0.4.2`, then re-pinned the consumer-setup doc to `@v0.1.3`.
- `agentic-bootstrap` resolved via `PATH` after `source .venv/bin/activate` matched the pyenv shim (`~/.pyenv/versions/3.13.9/bin/agentic-bootstrap`) instead of the venv binary on consumers where pyenv shims sit ahead of the venv on `PATH`. Workaround: always invoke via the explicit `./.venv/bin/agentic-bootstrap` path. Doc and bootstrap install instructions should prefer the explicit-path form.
- `agentic-bootstrap` v0.2.0 has no `--version` flag (only subcommands `install | status | doctor | update | repair`). Use `pip show agentic-bootstrap` for version reporting until a `--version` flag is added.
- `agentic-bootstrap doctor --target <empty-dir>` correctly exits 1 with `missing_manifest: .agentic-overlay.json`. Doctor is meant to flag drift, not to be used as a pre-install smoke. Only call `doctor` after `install`.

### Follow-on tasks opened

- `MAINT-orchestrator-pyproject-pin-policy` — decide whether orchestrator should pin handoff via URL (current) vs version-only constraint (e.g. `agent-handoff-mcp>=0.4.1,<0.5`) so cleanup tags don't force orchestrator retags.
- `MAINT-bootstrap-cli-version-flag` — add a `--version` flag to `agentic-bootstrap` so external smoke checks can verify the installed CLI without `pip show`.
- `MAINT-consumer-setup-explicit-venv-path` — update `consumer-setup.md` install snippets to prefer `./.venv/bin/agentic-bootstrap` over `agentic-bootstrap` to avoid pyenv-shim shadowing.
