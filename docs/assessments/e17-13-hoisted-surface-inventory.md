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
| `darce/mcp-agent-handoff` | `v0.4.2` | pending `git ls-remote` capture | pending |
| `darce/mcp-agent-orchestrator` | `v0.1.3` | pending `git ls-remote` capture | pending |
| `darce/agentic-system` | `v0.2.1` | pending `git ls-remote` capture | pending |
| `darce/agentic-bootstrap` | `v0.2.0` | pending `git ls-remote` capture | pending |

`Resolved commit SHA` remains blank until the exact remote tag-to-commit mapping is captured from `git ls-remote --heads --tags` and copied into this table.

## Scratch Install Gate

| Target | Required command | Current status | Notes |
| --- | --- | --- | --- |
| `darce/agentic-bootstrap@v0.2.0` | `pip install "git+ssh://git@github.com/darce/agentic-bootstrap.git@v0.2.0"` | pending scratch install proof | Must pass before any deletion slice starts because bootstrap owns the shared overlay install path. |
| `darce/mcp-agent-handoff@v0.4.2` | `pip install "git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.4.2"` plus `agent-handoff-mcp --workspace-root . doctor` | pending scratch install proof | Confirms the monorepo can consume the external handoff CLI without local package-source fallback. |
| `darce/mcp-agent-orchestrator@v0.1.3` | `pip install "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.3"` plus `agent-orchestrator-mcp --workspace-root . --help` | pending scratch install proof | Confirms the monorepo can consume the external orchestrator CLI without local package-source fallback. |

No deletion slice may start while any Slice 1 prerequisite remains pending.

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

1. Capture the remote SHAs behind the selected tags with `git ls-remote --heads --tags` for all four repos.
2. Run scratch-install proof for `darce/agentic-bootstrap@v0.2.0`, `darce/mcp-agent-handoff@v0.4.2`, and `darce/mcp-agent-orchestrator@v0.1.3`.
3. Promote the resulting SHA evidence into the handoff decision and mark the Slice 1 checklist items complete.