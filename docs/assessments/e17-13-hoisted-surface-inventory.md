# E17-13 Hoisted Surface Inventory

## Objective

Lock the Slice 1 prerequisites for hoisted-surface cleanup before any deletion work starts: choose the external refs the monorepo intends to consume, classify every `packages/*` directory by ownership, define the proof commands that block deletion, and make an explicit generator ownership decision.

## Selected External Refs

| Repo | Selected ref | Why this ref | Verification gate |
| --- | --- | --- | --- |
| `darce/mcp-agent-handoff` | `v0.4.2` | Latest cleanup tag after the `v0.4.1` reconciliation that fixed `run_doctor` at commit `18f681ca`. | `git ls-remote --heads --tags git@github.com:darce/mcp-agent-handoff.git`; `pip install "git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.4.2"`; `agent-handoff-mcp --workspace-root . doctor` |
| `darce/mcp-agent-orchestrator` | `v0.1.3` | Latest published compat tag that advances the handoff URL pin to `mcp-agent-handoff@v0.4.2`. | `git ls-remote --heads --tags git@github.com:darce/mcp-agent-orchestrator.git`; `pip install "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.3"`; `agent-orchestrator-mcp --workspace-root . --help` |
| `darce/agentic-system` | `v0.2.1` | Slice 4 cleanup tag after the `v0.2.0` contract-split release. Consumers do not `pip install` this repo directly; bootstrap clones it into the overlay. | `git ls-remote --heads --tags git@github.com:darce/agentic-system.git`; `agentic-bootstrap install --target <scratch-consumer>`; inspect `.agentic-overlay.json` for the resolved clone ref |
| `darce/agentic-bootstrap` | `v0.2.0` | Published bootstrap CLI tag. The default branch may be README-only, so the tag install is the real gate. | `git ls-remote --heads --tags git@github.com:darce/agentic-bootstrap.git`; `pip install "git+ssh://git@github.com/darce/agentic-bootstrap.git@v0.2.0"`; `agentic-bootstrap install --target <scratch-consumer>`; `agentic-bootstrap doctor` |

The `git ls-remote --heads --tags` steps remain the authoritative remote-SHA capture for this slice. This assessment records the selected tags first so the rest of Slice 1 can proceed against concrete refs instead of `main`.

## Remote Ref Evidence

| Repo | Selected tag | Resolved commit SHA | Capture status |
| --- | --- | --- | --- |
| `darce/mcp-agent-handoff` | `v0.4.2` | `0f7f62e9cf9f030dd4871115066bd6da17801068` | captured 2026-04-23 |
| `darce/mcp-agent-orchestrator` | `v0.1.3` | `11cf321a4e9671f01f8d02b5bf3790042656c162` | captured 2026-04-23 |
| `darce/agentic-system` | `v0.2.1` | `2a03e136bf3359485d4305c7562162bd45fa30df` | captured 2026-04-23 |
| `darce/agentic-bootstrap` | `v0.2.0` | `d5f43300a8eeca81cc8c2c44e429e67b4fb5062f` | captured 2026-04-23 |

The recorded SHAs are the peeled tag commits from `git ls-remote --tags <repo> refs/tags/<tag> refs/tags/<tag>^{}` so downstream slices compare runtime behavior against the actual tagged commit, not the annotated-tag object id.

## Scratch Install Gate

| Target | Required command | Current status | Notes |
| --- | --- | --- | --- |
| `darce/agentic-bootstrap@v0.2.0` | `pip install "git+ssh://git@github.com/darce/agentic-bootstrap.git@v0.2.0"` | install + smoke passed on 2026-04-23 | scratch venv: `/tmp/e17-13-proof.nHQuBj/venv`; bootstrap install target: `/tmp/e17-13-proof.nHQuBj/consumer`; `agentic-bootstrap install --target .` succeeded; `agentic-bootstrap doctor --target .` succeeded after correcting the CLI invocation to include the required `--target`; install output reported `installed agentic-system overlay: git@github.com:darce/agentic-system.git@ac7a77c4e29cd0f16a6945510445330f8d448caf -> .`, which does not match the selected `v0.2.1` commit and must be adjudicated before deletion work starts. |
| `darce/mcp-agent-handoff@v0.4.2` | `pip install "git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.4.2"` plus `agent-handoff-mcp --workspace-root . doctor` | install + smoke passed on 2026-04-23 | scratch venv: `/tmp/e17-13-proof.nHQuBj/venv`; doctor exited 0; the doctor JSON reported `workspace_root` as `/Users/daniel/Development/context-alt-text-monorepo` instead of the feature worktree path, so the external CLI currently reaches a root-worktree state path even when invoked from `feature/e17-13`. |
| `darce/mcp-agent-orchestrator@v0.1.3` | `pip install "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.3"` plus `agent-orchestrator-mcp --workspace-root . --help` | install + smoke passed on 2026-04-23 | scratch venv: `/tmp/e17-13-proof.nHQuBj/venv`; `--help` exited 0 and printed the expected command set (`serve`, `doctor`, `orchestrator-start`, `dispatch`, `metrics`, ...). |

No deletion slice may start while any Slice 1 prerequisite remains pending.
The scratch proof removed the `pending` state, but it surfaced two mismatches that still block deletion: bootstrap `v0.2.0` installed `agentic-system` at `ac7a77c4e29cd0f16a6945510445330f8d448caf` instead of the selected `v0.2.1` commit `2a03e136bf3359485d4305c7562162bd45fa30df`, and `agent-handoff-mcp --workspace-root . doctor` resolved the root monorepo path instead of the feature worktree path.

## Package Classification

| Path | Classification | Current decision |
| --- | --- | --- |
| `packages/agent-handoff-mcp/` | `external-owned duplicate` | Delete only after Slice 2 proves the installed `darce/mcp-agent-handoff@v0.4.2` path satisfies doctor/runtime expectations without local source fallback. |
| `packages/agent-orchestrator-mcp/` | `external-owned duplicate` | Delete only after Slice 2 proves the installed `darce/mcp-agent-orchestrator@v0.1.3` path satisfies CLI/import expectations without local source fallback. |
| `packages/codex-subagent-bridge/` | `monorepo-local package` | Not part of the hoisted family. Keep in monorepo unless a separate task explicitly externalizes it. |
| `packages/shared-contracts/` | `monorepo-local package` | Holds alt-context product contracts and schemas. Keep in monorepo; do not treat as an MCP duplicate. |
| `config/agent-workflows/` | `bootstrap-managed shared surface input` | Shared workflow definitions should come from `darce/agentic-system` through bootstrap/overlay, with monorepo-local overrides retained only where needed. |
| `scripts/generate_agent_workflows.py` | `monorepo-local package` | Keep as a repo-local generator driver until Slice 4 proves that bootstrap-supplied shared definitions fully cover the monorepo workflow generation path. |

## Deletion Gate Matrix

| Local path | Replacement ref | Proof commands that must pass before deletion | Blocked until |
| --- | --- | --- | --- |
| `packages/agent-handoff-mcp/` | `darce/mcp-agent-handoff@v0.4.2` | `git ls-remote --heads --tags git@github.com:darce/mcp-agent-handoff.git`; `pip install "git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.4.2"`; `agent-handoff-mcp --workspace-root . doctor` | External install runs and monorepo handoff smoke no longer needs `packages/agent-handoff-mcp/` on `PYTHONPATH`. |
| `packages/agent-orchestrator-mcp/` | `darce/mcp-agent-orchestrator@v0.1.3` | `git ls-remote --heads --tags git@github.com:darce/mcp-agent-orchestrator.git`; `pip install "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.3"`; `agent-orchestrator-mcp --workspace-root . --help` | External install runs and monorepo orchestrator smoke no longer needs `packages/agent-orchestrator-mcp/` on `PYTHONPATH`. |
| Shared overlay roots (`.claude/`, `.github/hooks/`, `scripts/hooks/`, `.github/prompts/`, `.claude/commands/`, `config/agent-workflows/`) | `darce/agentic-system@v0.2.1` via `darce/agentic-bootstrap@v0.2.0` | `git ls-remote --heads --tags git@github.com:darce/agentic-system.git`; `git ls-remote --heads --tags git@github.com:darce/agentic-bootstrap.git`; `agentic-bootstrap install --target <scratch-consumer>`; `agentic-bootstrap doctor` | Bootstrap overlay resolves the shared surface cleanly and validators pass against the overlay-managed files. |

## Generator Ownership Decision

Retain in monorepo as a local driver: `scripts/generate_agent_workflows.py` should remain the monorepo-owned generator entrypoint for now.

Reasoning:

- The script writes repo-specific generated outputs and Makefile-triggered workflow artifacts that are consumed inside this monorepo.
- The shared workflow definitions should come from `darce/agentic-system`, but the generator remains the adapter that turns those external workflow definitions into local generated outputs.
- Slice 4 can revisit this if bootstrap proves generator parity, but Slice 1 should not leave ownership ambiguous.

## Next Verification Pass

1. Reconcile why `darce/agentic-bootstrap@v0.2.0` installs `agentic-system` at `ac7a77c4e29cd0f16a6945510445330f8d448caf` instead of the selected `v0.2.1` commit `2a03e136bf3359485d4305c7562162bd45fa30df`.
2. Reconcile why `agent-handoff-mcp --workspace-root . doctor` reports the root monorepo path when run from the feature worktree with the external package install.
3. Promote the resulting evidence and mismatch disposition into handoff before marking Slice 1 complete.