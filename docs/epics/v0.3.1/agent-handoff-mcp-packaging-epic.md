# E13. Agent Handoff MCP Extraction and Consumer Rewiring (v0.3.1)

> **Epic Short ID**: E13

## Objective

Extract `agent-handoff-mcp` into a standalone private repository that other projects can install via git+ssh, while keeping the already-separated `agent-orchestrator-mcp` in this monorepo and rewiring all live monorepo consumers away from local `packages/agent-handoff-mcp/src` coupling.

## Problem Statement

E12-9 already completed the key architectural split: `agent-handoff-mcp` is now a ledger-only package and `agent-orchestrator-mcp` owns slice-review, lane management, daemon lifecycle, and other orchestration surfaces. The remaining extraction blockers are operational rather than structural.

Today, the monorepo still assumes a checked-out local handoff package in several places:

- root and package-local Makefiles build `PYTHONPATH` from `packages/agent-handoff-mcp/src`
- CI workflows and IDE MCP configs still install or launch from repo-local handoff paths
- orchestrator-owned helper modules still hardcode monorepo layout assumptions such as `SCRIPT_DIR.parents[4]`, `docs/agentic/rules/`, `config/lane-orchestration/`, and `packages/agent-handoff-mcp/src/`
- operator-facing contracts, bootstrap docs, and playbooks still describe repo-local source-path launches as the live operating model

That means `agent-handoff-mcp` is logically portable but not yet operationally extractable. The epic is therefore no longer about splitting orchestration out of handoff; it is about finishing path de-coupling, creating the standalone handoff repo snapshot, and rewiring the monorepo to consume the extracted package cleanly.

## UX Vision

After this epic:

- `darce/mcp-agent-handoff` exists as a private standalone repo with CI and a third-party-facing README
- this monorepo consumes `agent-handoff-mcp` via git+ssh rather than through local source-tree assumptions
- `agent-orchestrator-mcp` remains monorepo-local for now, but its shipped helpers no longer depend on hardcoded monorepo paths that block handoff extraction
- MCP clients in VS Code and Claude Code still connect successfully using the updated runtime wiring

Future work such as extracting ACE-specific behavior, publishing packages publicly, or decoupling orchestrator further can build on this rebaselined boundary instead of redoing E12-9.

## Constraints

- The existing `[rg-013]` and `[rg-014]` guardrails remain load-bearing: `core.py` stays pure CRUD; orchestration uses late-binding imports where required.
- The extracted handoff package should keep a minimal runtime dependency surface. The current package already depends on `fastmcp` and `tiktoken`; extraction should not add new runtime dependencies without a concrete need.
- No breaking changes to the shipped handoff Python API beyond package location. Existing imports from `agent_handoff_mcp` should continue to work after installation from git+ssh.
- `agent-orchestrator-mcp` stays in this monorepo for now and will consume the extracted handoff package as a dependency.
- `shared-contracts` stays in the monorepo; it is application-domain, not MCP-package scope.
- `codex-subagent-bridge` stays in the monorepo.
- Greenfield packaging policy applies; no backward-compat shims for repo-local paths that are being retired.
- The extracted repo must have no reference to "context alt text", "alt-context", or `acx`.
- `packages/wp-testing-helpers/` is a dead stub and should be removed during cleanup.

## Terminology

- **Core Handoff**: The extracted `agent-handoff-mcp` ledger package: task state, review findings, artifacts, export/import, search, and CURRENT_TASK.md generation.
- **Orchestrator**: The monorepo-local `agent-orchestrator-mcp` package: daemons, workers, lane management, slice-review packets, review-summary helpers, and related runtime tooling.
- **Consumer rewiring**: Updating Makefiles, CI, IDE configs, docs, and package metadata so the monorepo uses the extracted handoff package rather than local `packages/agent-handoff-mcp/src` paths.
- **Live surfaces**: Runtime, config, contract, bootstrap, playbook, and package-local workflow files that operators actively use. Historical planning docs and generated metadata are not part of the live-surface cleanup proof.

## Current State

### Already True After E12-9

- `agent-handoff-mcp` is ledger-only and no longer contains `orchestration/` or `lanes.py`.
- `agent-handoff-mcp/cli.py`, `agent-handoff-mcp/api.py`, and `agent-handoff-mcp/__init__.py` no longer expose orchestration helpers.
- `get_latest_slice_review_packet` is owned by `agent-orchestrator-mcp`, not handoff.
- `agent-orchestrator-mcp` owns local copies of orchestration modules, lane CRUD, plan cursors, and the cross-task review packet surface.
- Package-local Makefiles and standalone-first README workflows already exist for the MCP packages.

### Remaining Extraction Blockers

- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/lane_manifest.py` still derives manifest roots from `SCRIPT_DIR.parents[4]`.
- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/generate_lane_manifest.py` still derives output roots from monorepo assumptions.
- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/review_ready.py` still hardcodes boundary and contract prefixes including `packages/agent-handoff-mcp/src/`.
- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py` still assembles source-path `PYTHONPATH` values for runtime helpers.
- The root [Makefile](../../../Makefile) and `mk/*.mk` modules still use local handoff source paths as part of the MCP runtime model.
- `.vscode/mcp.json`, `.mcp.json`, `.codex/config.toml`, and `.github/workflows/*.yml` still point to local handoff package paths.
- Package-local workflows and live docs still describe repo-local handoff installs and source-path launches.

## Target Architecture

The target state is a two-package runtime split plus one extracted repo:

```text
darce/mcp-agent-handoff (private repo)
  agent-handoff-mcp package
  ledger-only MCP surface
  CI + README for third-party adopters

context-alt-text-monorepo
  agent-orchestrator-mcp package remains local
  consumes agent-handoff-mcp via git+ssh dependency
  no live runtime/config/doc surface depends on packages/agent-handoff-mcp/src

repo-local only
  lane manifests under config/lane-orchestration/
  operational docs/playbooks
  codex-subagent-bridge
  any future ACE-specific follow-on work
```

Key architecture rules:

- `agent-handoff-mcp` stays ledger-only; do not move orchestration symbols back into it.
- `agent-orchestrator-mcp` keeps ownership of slice-review, daemon, lane, and review-summary helpers.
- Remaining path seams are parameterized or localized on the orchestrator side before extraction.
- Live consumer surfaces are rewired before the local handoff package is deleted.

## Design Decisions

| Decision                                               | Rationale                                                                                                                                                                                    |
| ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Treat E12-9 as completed prerequisite work             | The repo has already crossed the major package boundary; redoing that work in E13 would reopen finished separation slices.                                                                   |
| Extract handoff first; keep orchestrator local         | Handoff is already the portable ledger boundary. Orchestrator still carries repo-local workflow assumptions and is not the immediate extraction target.                                      |
| Fix path seams on orchestrator-owned helpers           | The remaining hardcoded layout assumptions live on the orchestrator side, so the cleanup should happen where that ownership now resides.                                                     |
| Rewire live consumers explicitly                       | Makefiles, CI, IDE configs, package-local workflows, contracts, bootstrap docs, and playbooks all participate in the runtime model; leaving any of them stale breaks extraction in practice. |
| Use a live-surface grep proof with explicit carve-outs | Historical planning docs will continue to mention the old local path. The proof should target the operator-facing/runtime surfaces that must actually be clean.                              |

## Data and Contract Model

- **Canonical state**: `handoff.db` and `mcp-artifacts.db` remain the shared SQLite data stores for handoff and orchestrator packages.
- **Handoff package API**: import paths stay `agent_handoff_mcp.*`; the change is package source location and install source, not module naming.
- **Orchestrator package API**: continues to own `get_latest_slice_review_packet`, lane management, daemon lifecycle, review-summary helpers, and turn metrics.
- **Runtime wiring**: MCP launch/config surfaces should move from repo-local source-path assembly to installed package entrypoints or explicit installed launcher paths.
- **Docs and operator contracts**: must describe the extracted handoff package as the live install target once rewiring lands.

## Phased Delivery

### Phase 1: Parameterize Orchestrator-Owned Path Blockers -- not-started

> **Status**: not-started
> **Task plans**: [E13-2 Slice 1](../../tasks/13.0/E13-2-extract-agent-handoff-mcp-to-standalone-repo-task-plan.md)

**Goal**: Remove the remaining monorepo-only path assumptions from `agent-orchestrator-mcp` without reopening the handoff/orchestrator boundary.

Deliverables:

- parameterize `lane_manifest.py` with `manifest_dir`
- parameterize `generate_lane_manifest.py` output roots
- parameterize `review_runner.py` with `rules_dir`
- parameterize `review_ready.py` with boundary prefixes, contract prefixes, and contract checklist path
- remove runtime helper assumptions in `agent_orchestrator_mcp/api.py` that require `packages/agent-handoff-mcp/src` source-path assembly

Exit criteria:

- orchestrator path-sensitive helpers work with explicit custom paths in tests
- `get_latest_slice_review_packet` remains owned by `agent-orchestrator-mcp`
- no new `agent_handoff_mcp/orchestration/` surface is introduced
- `make test-orchestrator` passes

### Phase 2: Remove Live Monorepo Source-Path Coupling -- not-started

> **Status**: not-started
> **Task plans**: [E13-2 Slice 2](../../tasks/13.0/E13-2-extract-agent-handoff-mcp-to-standalone-repo-task-plan.md)

**Goal**: Make the monorepo run against installed MCP packages and entrypoints instead of local handoff source paths.

Deliverables:

- update root and package-local Makefiles
- remove `../agent-handoff-mcp/src` fallback from `packages/agent-orchestrator-mcp/Makefile`
- update CI workflows, MCP launch configs, and runtime scripts
- validate that live workflow and config surfaces no longer depend on `packages/agent-handoff-mcp/src`

Exit criteria:

- `make check-mcp` passes with the updated runtime model
- live workflow/config surfaces no longer contain handoff source-path coupling
- `make test-orchestrator` passes against the new runtime wiring

### Phase 3: Create Extracted Repository Snapshot -- not-started

> **Status**: not-started
> **Task plans**: [E13-2 Slice 3](../../tasks/13.0/E13-2-extract-agent-handoff-mcp-to-standalone-repo-task-plan.md)

**Goal**: Create `darce/mcp-agent-handoff` from the already ledger-only handoff package.

Deliverables:

- create a clean package snapshot outside the monorepo
- strip monorepo-specific references from the extracted repo
- add CI, README, license, and package metadata for private git+ssh installs
- push the private repo

Exit criteria:

- extracted repo CI passes
- clean-venv `pip install` from git+ssh succeeds
- import smoke test against the extracted package succeeds

### Phase 4: Rewire Monorepo Packages and Delete Local Handoff -- not-started

> **Status**: not-started
> **Task plans**: [E13-2 Slice 4](../../tasks/13.0/E13-2-extract-agent-handoff-mcp-to-standalone-repo-task-plan.md)

**Goal**: Point monorepo package/runtime dependencies at the extracted repo, then remove the local handoff package tree.

Deliverables:

- update `packages/agent-orchestrator-mcp/pyproject.toml` to the git+ssh dependency
- consume installed handoff package in Makefiles and CI
- delete `packages/agent-handoff-mcp/` and `packages/wp-testing-helpers/`
- update monorepo-level package references such as `packages/Makefile`, `README.md`, and `CLAUDE.md`

Exit criteria:

- `make test-orchestrator` passes against the extracted dependency
- `packages/agent-handoff-mcp/` is gone from the monorepo
- `make check-mcp` passes after removal

### Phase 5: Clean Live Docs and Operator Surfaces -- not-started

> **Status**: not-started
> **Task plans**: [E13-2 Slice 5](../../tasks/13.0/E13-2-extract-agent-handoff-mcp-to-standalone-repo-task-plan.md)

**Goal**: Remove remaining live runtime, contract, bootstrap, and playbook references to the old handoff source path and close with an explicit live-surface proof.

Deliverables:

- update contracts, bootstrap docs, playbooks, and package READMEs
- remove any remaining live runtime/config surfaces that hardcode handoff source paths
- document the historical/generated carve-outs for the final grep proof

Exit criteria:

- MCP clients connect successfully using the updated configs
- live-surface grep proof is clean with only documented carve-outs remaining

## Deferred Follow-On Work

These items are no longer part of E13's extraction-critical path and should be scoped separately if still desired:

- extracting ACE-specific metrics/reflection behavior from orchestrator-owned code
- further decoupling or publishing `agent-orchestrator-mcp`
- PyPI readiness and public distribution work
- plugin or hook systems for custom MCP extensions

## External Dependencies

| Dependency                                              | Owner    | Status                            | Blocks                        |
| ------------------------------------------------------- | -------- | --------------------------------- | ----------------------------- |
| GitHub private repo `darce/mcp-agent-handoff`           | @daniel  | Not started                       | Phase 3 snapshot push         |
| git+ssh consumer access from monorepo environments      | Internal | Not started                       | Phase 4 rewiring              |
| `fastmcp` and current handoff runtime deps (`tiktoken`) | External | Available                         | Extracted package runtime     |
| `codex-subagent-bridge` package                         | Internal | Available, remains monorepo-local | Optional runtime integrations |

## Code Anchors

| Layer                      | File                                                                                                 | Note                                                                                 |
| -------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Ledger package             | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`                                            | Ledger-only MCP surface; no orchestration exports                                    |
| Ledger package             | `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py`                                       | Public handoff exports stay package-stable across extraction                         |
| Orchestrator review packet | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py`                                  | Owns `get_latest_slice_review_packet` and still contains runtime source-path helpers |
| Orchestrator path seam     | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/lane_manifest.py`          | Still derives `MANIFEST_DIR` from monorepo-root assumptions                          |
| Orchestrator path seam     | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/generate_lane_manifest.py` | Still derives manifest output root from monorepo-root assumptions                    |
| Orchestrator path seam     | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/review_ready.py`           | Still hardcodes handoff source-path boundary prefixes and contract paths             |
| Orchestrator runtime       | `packages/agent-orchestrator-mcp/Makefile`                                                           | Still falls back to `../agent-handoff-mcp/src`                                       |
| Root runtime wiring        | `Makefile`                                                                                           | Still assembles `MCP_PYTHONPATH` from local package source trees                     |
| MCP bootstrap docs         | `docs/agentic/BOOTSTRAP.md`                                                                          | Still documents repo-local launcher/source-path setup                                |
| Handoff contract           | `docs/agentic/contracts/agent-handoff-mcp.md`                                                        | Live handoff install/launch guidance must match extracted reality                    |
| Orchestrator contract      | `docs/agentic/contracts/agent-orchestrator-mcp.md`                                                   | Live orchestrator install/launch guidance must match extracted handoff dependency    |
| IDE runtime                | `.vscode/mcp.json`, `.mcp.json`, `.codex/config.toml`                                                | Still point at repo-local handoff paths                                              |
| CI runtime                 | `.github/workflows/mcp-packages.yml`, `.github/workflows/handoff-integrity.yml`                      | Still consume local handoff package paths                                            |

---

## Consolidated Checklist

### Context and Ownership

- [ ] Confirm E12-9 separation status is still current before implementation
- [ ] Verify handoff/orchestrator contract surfaces against current docs and code
- [ ] Treat live-surface cleanup separately from historical planning-doc references

### Phase 1

- [ ] Parameterize `lane_manifest.py` manifest roots
- [ ] Parameterize `generate_lane_manifest.py` output roots
- [ ] Parameterize `review_runner.py` rules dir
- [ ] Parameterize `review_ready.py` boundary/contract/checklist paths
- [ ] Remove orchestrator runtime helper dependence on handoff source-path assembly
- [ ] `make test-orchestrator` passes

### Phase 2

- [ ] Root Makefile no longer depends on `packages/agent-handoff-mcp/src`
- [ ] `mk/*.mk` no longer require handoff source-path runtime wiring
- [ ] `packages/agent-orchestrator-mcp/Makefile` no longer falls back to `../agent-handoff-mcp/src`
- [ ] CI workflows updated
- [ ] IDE configs updated
- [ ] `scripts/mcp/mcp-server.sh` updated
- [ ] `make check-mcp` passes

### Phase 3

- [ ] `darce/mcp-agent-handoff` private repo created
- [ ] extracted repo CI passes
- [ ] README written for third-party adopters
- [ ] git+ssh install smoke test passes

### Phase 4

- [ ] `packages/agent-orchestrator-mcp/pyproject.toml` points to git+ssh handoff dependency
- [ ] `packages/agent-handoff-mcp/` deleted from the monorepo
- [ ] `packages/wp-testing-helpers/` deleted
- [ ] `packages/Makefile`, `README.md`, and `CLAUDE.md` updated
- [ ] `make test-orchestrator` passes
- [ ] `make check-mcp` passes

### Phase 5

- [ ] `docs/agentic/contracts/agent-handoff-mcp.md` updated
- [ ] `docs/agentic/contracts/agent-orchestrator-mcp.md` updated
- [ ] `docs/agentic/BOOTSTRAP.md` updated
- [ ] relevant `docs/agentic/playbooks/**/*.md` updated
- [ ] package-local docs updated
- [ ] live-surface grep proof is clean with documented carve-outs

## Success Criteria

- [ ] `darce/mcp-agent-handoff` is a functional private repo with passing CI
- [ ] this monorepo consumes it via git+ssh with no live source-path coupling
- [ ] `packages/agent-handoff-mcp/` no longer exists in the monorepo
- [ ] no live runtime/config/operator surface still depends on `packages/agent-handoff-mcp/src`
- [ ] MCP server connects in all configured IDEs
