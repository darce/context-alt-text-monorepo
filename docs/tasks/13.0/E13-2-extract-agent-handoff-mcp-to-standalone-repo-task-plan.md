# E13-2. Extract agent-handoff-mcp to Standalone Repository

> **Metadata**
>
> - **Date**: 2026-03-31
> - **Author**: Claude Opus 4.6
> - **Owning Epic**: [docs/epics/v0.3.1/agent-handoff-mcp-packaging-epic.md](../../epics/v0.3.1/agent-handoff-mcp-packaging-epic.md)
> - **Epic Short ID**: E13
> - **Review Coverage Target**: 2

---

## Objective

Extract `agent-handoff-mcp` from the monorepo into `darce/mcp-agent-handoff` on GitHub (private, git+ssh installable) so it can be adopted by other projects without pulling in monorepo structure, and rewire all monorepo consumers to depend on the extracted repo.

## Problem Statement

`agent-handoff-mcp` is already architecturally separated from orchestration after E12-9, but extraction is still blocked by monorepo-coupled tooling. The root Makefile still stitches the MCP stack together via `PYTHONPATH` source paths, CI workflows and IDE configs still launch repo-local entrypoints, and orchestrator-owned helper modules still carry hardcoded monorepo paths (`SCRIPT_DIR.parents[4]`, `docs/agentic/rules/`, `config/lane-orchestration/`, `packages/agent-handoff-mcp/src/`). The remaining work is therefore not to move orchestration back out of handoff, but to finish de-coupling the live consumers and the orchestrator-owned helpers that still assume this repository layout.

## Constraints

- `core.py` must remain pure handoff-state CRUD per `[rg-013]`.
- Orchestration modules must use late-binding imports per `[rg-014]`.
- Keep the extracted handoff package's runtime dependency surface minimal; the current package already depends on `fastmcp` and `tiktoken`, and no new extraction-only runtime dependency should be introduced without a concrete need.
- The extracted repo must have no reference to "context alt text", "alt-context", or "acx". It is an agent-agnostic handoff server.
- `shared-contracts` stays in the monorepo — it is application-domain, not MCP concern.
- `agent-orchestrator-mcp` stays in the monorepo for now; it will consume the extracted package via git+ssh.
- `codex-subagent-bridge` stays in the monorepo.
- No backward-compatibility shims (greenfield policy).
- `wp-testing-helpers` is a dead stub (README only, zero references) and should be deleted as part of cleanup.

## Workflow Principles

- Start from the post-E12-9 boundary that already exists in this repo: `agent-handoff-mcp` stays ledger-only and `agent-orchestrator-mcp` keeps ownership of slice-review, lane, daemon, and path-coupled orchestration helpers.
- Complete the remaining in-monorepo prep slices before extraction, so changes are testable against the existing suite.
- The extraction commit should be a clean snapshot, not a copy of monorepo git history.
- Consumer rewiring in the monorepo happens in a single coordinated commit after the extracted repo is pushed.

## Terminology

- **Core Handoff**: Portable modules (`core.py`, `config.py`, `runtime.py`, `enums.py`, `artifact_index.py`, `cli.py`, `api.py`) providing task-state CRUD, review findings, artifacts, search, export/import, and CURRENT_TASK.md generation.
- **Orchestration tier**: Generic multi-agent layer (daemons, adapters, lane exec) that now lives in `agent-orchestrator-mcp` and remains in this monorepo for now.
- **ACE**: Autonomous Coding Engine. Repo-specific playbook system. Stays in the monorepo; never ships in the extracted package.
- **Consumer rewiring**: Updating all monorepo references (Makefile, CI, IDE configs, pyproject.toml) to install from git+ssh instead of source paths.

## Current State Analysis

- E12-9 has already crossed the main package-boundary line: `agent-handoff-mcp` is ledger-only, has no `orchestration/` subpackage, and no longer exports orchestration helpers from its CLI, `api.py`, or `__init__.py`.
- `get_latest_slice_review_packet()` is now owned by `agent-orchestrator-mcp` (`lanes.py` and `api.py`), so this task must not move slice-review ownership back into handoff.
- `packages/agent-handoff-mcp/pyproject.toml` already reflects a ledger package shape with ordinary `test` and `dev` extras; there is no handoff-local orchestration extra to introduce.
- The remaining hardcoded monorepo path assumptions are orchestrator-owned: `lane_manifest.py` still derives `MANIFEST_DIR` from `SCRIPT_DIR.parents[4]`, `generate_lane_manifest.py` still derives its output root the same way, `review_ready.py` still hardcodes `packages/agent-handoff-mcp/src/` and contract/boundary prefixes, and runtime helpers in `agent_orchestrator_mcp/api.py` still assemble source-path `PYTHONPATH` values.
- Root Makefile and `mk/*.mk` still build local source-path `PYTHONPATH` values and launch repo-local scripts instead of relying on installed entrypoints.
- GitHub workflows and IDE configs still point at `packages/agent-handoff-mcp/**` paths for installs, launchers, or `PYTHONPATH` wiring.
- Package-local workflows and operator docs still assume neighboring source trees or repo-local installs, including `packages/agent-orchestrator-mcp/Makefile`, `docs/agentic/contracts/agent-handoff-mcp.md`, `docs/agentic/contracts/agent-orchestrator-mcp.md`, `docs/agentic/BOOTSTRAP.md`, and related playbooks.
- `packages/wp-testing-helpers/` is still a dead stub and can be removed during cleanup.

## Target Outcome

`darce/mcp-agent-handoff` is a private GitHub repo containing the portable `agent-handoff-mcp` package. It has its own CI, its own README (written for 3rd-party adopters), and zero references to this monorepo's structure. This monorepo installs it via `git+ssh://git@github.com/darce/mcp-agent-handoff.git` in pyproject.toml dependencies and Makefile targets. The monorepo's `packages/agent-handoff-mcp/` directory no longer exists.

## Context Loading

- Rules: `docs/agentic/rules/backend-python-guidelines.md`
- Contracts: `docs/agentic/contracts/` (verify no handoff-specific contracts break)
- Epic: `docs/epics/v0.3.1/agent-handoff-mcp-packaging-epic.md` (phases 1-5, code anchors, design decisions)
- Prior work: `docs/tasks/12.0/12.1/E12-9-orchestration-physical-separation-task-plan.md` (status of physical separation)
- Operator docs: `docs/agentic/BOOTSTRAP.md`, `docs/agentic/playbooks/`
- Tech debt: `docs/tech-debt/migrate-pip-to-uv.md` (installer preference)

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `agent-handoff-mcp` Python API | handoff core | `pyproject.toml` + `__init__.py` exports | Package location moves; import paths unchanged | No — greenfield policy | `pip install` from git+ssh, import test |
| `agent-orchestrator-mcp` dependency | orchestrator | plain `agent-handoff-mcp` dependency plus local source-path fallback in package/root Makefiles | `agent-handoff-mcp @ git+ssh://...` in pyproject.toml; installed-package runtime in Makefiles | No — same Python API | orchestrator test suite passes |
| Makefile / package-local `PYTHONPATH` | monorepo build | source paths in root and package-local Makefiles | installed package or explicit bootstrap install; remove handoff source-path coupling | No | `make check-mcp` passes |
| MCP server launch | IDE configs | source path to launcher script plus repo-local `PYTHONPATH` | installed entrypoint or installed launcher invocation with no monorepo source-path dependency | No | MCP server starts in VS Code / Claude Code |
| Operator contracts and playbooks | docs | repo-local package install / source-path launch instructions | standalone-repo install instructions plus extracted-package consumer guidance | No | bootstrap and contract docs match live runtime |

## Proposed Solution

Start from the already-separated E12-9 boundary. Keep `agent-handoff-mcp` ledger-only, fix the remaining monorepo-coupled helpers in `agent-orchestrator-mcp`, move live monorepo consumers off handoff source paths, then extract the clean ledger package snapshot to a new repo and rewire the monorepo to consume it via git+ssh. Any broader ACE or public-package follow-on remains deferred.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Orchestrator path seams | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/lane_manifest.py` | Accept `manifest_dir` parameter |
| Orchestrator path seams | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/generate_lane_manifest.py` | Stop deriving output root from monorepo-only `SCRIPT_DIR.parents[4]` |
| Orchestrator path seams | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/review_runner.py` | Accept `rules_dir` parameter |
| Orchestrator path seams | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/review_ready.py` | Accept `boundary_prefixes`, `contract_prefixes`, `contract_checklist_path` |
| Runtime wiring | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py` | Remove handoff source-path assumptions from runtime helpers |
| Package metadata | `packages/agent-orchestrator-mcp/pyproject.toml` | Pin `agent-handoff-mcp` to git+ssh after extraction |
| Package-local tooling | `packages/agent-orchestrator-mcp/Makefile` | Remove `../agent-handoff-mcp/src` fallback |
| New repo | `~/Development/mcp-agent-handoff/` | Clean package snapshot + CI + README |
| Makefile | `Makefile` (root) | Remove handoff from `MCP_PYTHONPATH`; use installed package |
| Makefile | `mk/lane-worker.mk` | Replace direct CLI path invocations |
| Makefile | `mk/handoff.mk` | Update `MCP_CMD` to use installed entrypoint |
| Makefile | `mk/orchestrator.mk` | Use installed package runtime assumptions where needed |
| CI | `.github/workflows/mcp-packages.yml` | Remove handoff job; extracted repo has its own CI |
| CI | `.github/workflows/handoff-integrity.yml` | Install from git+ssh instead of local path |
| IDE config | `.vscode/mcp.json` | Use installed entrypoint |
| IDE config | `.mcp.json` | Use installed entrypoint |
| IDE config | `.codex/config.toml` | Use installed entrypoint |
| MCP script | `scripts/mcp/mcp-server.sh` | Use installed entrypoint |
| Contracts and bootstrap | `docs/agentic/contracts/agent-handoff-mcp.md` | Remove repo-local source-path guidance; document extracted install |
| Contracts and bootstrap | `docs/agentic/contracts/agent-orchestrator-mcp.md` | Update source-path/install guidance for extracted handoff dependency |
| Contracts and bootstrap | `docs/agentic/BOOTSTRAP.md` | Update MCP install and launcher guidance |
| Playbooks | `docs/agentic/playbooks/**/*.md` | Remove live operator references to `packages/agent-handoff-mcp/src` |
| Package docs | `packages/agent-orchestrator-mcp/README.md` | Update dependency/install instructions |
| Lane config | `config/lane-orchestration/*.json` | Remove `packages/agent-handoff-mcp` owned paths |
| Cleanup | `packages/agent-handoff-mcp/` | Delete entire directory |
| Cleanup | `packages/wp-testing-helpers/` | Delete (dead stub) |
| Cleanup | `packages/Makefile` | Remove handoff forwarding targets |

## Related Files

| File | Note |
| --- | --- |
| `docs/tech-debt/migrate-pip-to-uv.md` | Consider using `uv` for installs in updated Makefile targets |
| `docs/tasks/12.0/12.1/E12-9-orchestration-physical-separation-task-plan.md` | Prior separation work; confirms handoff no longer re-exports orchestration |
| `docs/agentic/contracts/agent-handoff-mcp.md` | Live contract for ledger-only handoff surface |
| `docs/agentic/contracts/agent-orchestrator-mcp.md` | Live contract for slice-review and orchestration ownership |
| `docs/agentic/BOOTSTRAP.md` | Live operator install and MCP launch guidance |
| `README.md` | Update monorepo structure description |
| `CLAUDE.md` | Update allowed paths list (remove `packages/agent-handoff-mcp`) |

## Verification Strategy

- Deterministic tests:
  - `make test-handoff` (while the local package still exists, and again in the extracted repo)
  - `make test-orchestrator` (in monorepo, first against local package, then consuming from git+ssh)
  - `make check-mcp` (in monorepo)
- Runtime-parity checks:
  - `pip install "agent-handoff-mcp @ git+ssh://git@github.com/darce/mcp-agent-handoff.git"` in a clean venv starts the MCP server
- Contract/fixture verification:
  - `python -c "from agent_handoff_mcp import build_handoff_mcp; print('OK')"` after install from git
- Manual verification:
  - MCP server connects in VS Code via updated `.vscode/mcp.json`
  - Claude Code connects via updated `.mcp.json`
- Live-surface cleanup check:
  - `git grep 'packages/agent-handoff-mcp' -- Makefile mk .github/workflows .vscode .mcp.json .codex docs/agentic packages/agent-orchestrator-mcp README.md CLAUDE.md` returns zero hits after the final cleanup slice
  - Historical planning docs (`docs/tasks/`, `docs/epics/`, `docs/archive/`) and generated metadata are explicitly excluded from the live-surface grep proof

## Slice Delivery

### Slice 1: Parameterize Orchestrator-Owned Path Blockers

**Goal**: Remove the remaining monorepo-only path assumptions from `agent-orchestrator-mcp` without reopening the handoff/orchestrator boundary.

Changes:

- `lane_manifest.py`: accept `manifest_dir` parameter instead of deriving it from `SCRIPT_DIR.parents[4]`
- `generate_lane_manifest.py`: accept a configurable manifest/output root instead of assuming monorepo layout
- `review_runner.py`: accept `rules_dir` parameter instead of hardcoding `docs/agentic/rules`
- `review_ready.py`: accept `boundary_prefixes`, `contract_prefixes`, and `contract_checklist_path`
- `agent_orchestrator_mcp/api.py`: remove runtime helpers that require `packages/agent-handoff-mcp/src` source-path assembly when an installed package is the real target
- Add config plumbing where needed on the orchestrator side; do not move any orchestration symbol back into `agent-handoff-mcp`

Proof:

- Orchestrator modules instantiated with custom paths work correctly in tests
- `get_latest_slice_review_packet` remains owned by `agent-orchestrator-mcp`
- No new `agent_handoff_mcp/orchestration/` surface is introduced
- `make test-orchestrator` passes

### Slice 2: Remove Live Monorepo Source-Path Coupling

**Goal**: Make the current monorepo run against installed MCP packages and entrypoints instead of local handoff source paths.

Changes:

- Root `Makefile` and `mk/*.mk`: replace direct handoff source-path `PYTHONPATH` usage with installed package assumptions or one explicit bootstrap step
- `packages/agent-orchestrator-mcp/Makefile`: remove `../agent-handoff-mcp/src` fallback
- `.github/workflows/mcp-packages.yml` and `.github/workflows/handoff-integrity.yml`: stop treating local handoff paths as the steady-state consumer path
- `.vscode/mcp.json`, `.mcp.json`, `.codex/config.toml`, `scripts/mcp/mcp-server.sh`: launch installed entrypoints or installed launcher paths without local handoff source coupling

Proof:

- `make check-mcp` passes with installed entrypoints
- Live workflow/config surfaces no longer contain `packages/agent-handoff-mcp/src`
- `make test-orchestrator` passes against the new runtime wiring

### Slice 3: Create Extracted Repository Snapshot

**Goal**: Create `darce/mcp-agent-handoff` from the already ledger-only handoff package.

Changes:

- Create `/Users/daniel/Development/mcp-agent-handoff/` with a clean snapshot of `packages/agent-handoff-mcp/`
- Strip monorepo-specific references and rewrite README/install guidance for a 3rd-party audience
- Add `.github/workflows/ci.yml`, `.gitignore`, `LICENSE`, and package metadata needed for private git+ssh installs
- `gh repo create darce/mcp-agent-handoff --private --source . --push`

Proof:

- CI passes on GitHub
- `pip install "agent-handoff-mcp @ git+ssh://git@github.com/darce/mcp-agent-handoff.git"` succeeds in a clean venv
- `python -c "from agent_handoff_mcp import build_handoff_mcp; print('OK')"` succeeds against the extracted repo

### Slice 4: Rewire Monorepo Packages and Delete Local Handoff

**Goal**: Point the monorepo's package and runtime dependencies at the extracted repo, then remove the local handoff package tree.

Changes:

- `packages/agent-orchestrator-mcp/pyproject.toml`: add git+ssh dependency on extracted handoff repo
- Root/package-local Makefiles and CI targets: consume installed handoff package instead of the deleted local tree
- Delete `packages/agent-handoff-mcp/` and `packages/wp-testing-helpers/`
- Update `packages/Makefile`, root `README.md`, and `CLAUDE.md`

Proof:

- `make test-orchestrator` passes while consuming the extracted repo dependency
- `packages/agent-handoff-mcp/` no longer exists in the monorepo
- `make check-mcp` passes after the package removal

### Slice 5: Clean Live Docs and Operator Surfaces

**Goal**: Remove the remaining live runtime, contract, bootstrap, and playbook references to the old handoff source path and close with an explicit live-surface proof.

Changes:

- `docs/agentic/contracts/agent-handoff-mcp.md`, `docs/agentic/contracts/agent-orchestrator-mcp.md`, `docs/agentic/BOOTSTRAP.md`, relevant `docs/agentic/playbooks/**/*.md`, and package READMEs: remove live operator references to `packages/agent-handoff-mcp/src`
- Any remaining live runtime/config surfaces that still hardcode handoff source paths: update or remove them
- Define explicit grep carve-outs for historical planning docs, archived docs, and generated metadata so the final proof matches the real target surface

Proof:

- MCP server connects in VS Code and Claude Code using the updated live configs
- `git grep 'packages/agent-handoff-mcp' -- Makefile mk .github/workflows .vscode .mcp.json .codex docs/agentic packages/agent-orchestrator-mcp README.md CLAUDE.md` returns zero hits
- Historical planning docs (`docs/tasks/`, `docs/epics/`, `docs/archive/`) and generated metadata are the only allowed carve-outs

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded epic phases 1-5 and code anchors from owning epic
- [ ] Confirmed E12-9 separation status is current
- [ ] Verified no handoff-specific contracts in `docs/agentic/contracts/` will break

### Checklist: Slice 1

- [ ] `lane_manifest.py` accepts `manifest_dir`
- [ ] `generate_lane_manifest.py` no longer depends on `SCRIPT_DIR.parents[4]`
- [ ] `review_runner.py` accepts `rules_dir`
- [ ] `review_ready.py` accepts `boundary_prefixes`, `contract_prefixes`, and `contract_checklist_path`
- [ ] Orchestrator runtime helpers stop assembling handoff source-path `PYTHONPATH` values as the target runtime model
- [ ] `get_latest_slice_review_packet` remains orchestrator-owned
- [ ] `make test-orchestrator` passes

### Checklist: Slice 2

- [ ] Root Makefile uses installed package/runtime assumptions, not `packages/agent-handoff-mcp/src`
- [ ] `mk/*.mk` use installed entrypoints or an explicit bootstrap step
- [ ] `packages/agent-orchestrator-mcp/Makefile` no longer falls back to `../agent-handoff-mcp/src`
- [ ] CI workflows updated
- [ ] IDE configs updated (`.vscode/mcp.json`, `.mcp.json`, `.codex/config.toml`)
- [ ] `scripts/mcp/mcp-server.sh` updated
- [ ] `make check-mcp` passes

### Checklist: Slice 3

- [ ] `darce/mcp-agent-handoff` created as private repo
- [ ] No monorepo-specific references in extracted code
- [ ] CI workflow passes (lint, type-check, test)
- [ ] README written for 3rd-party audience
- [ ] `pip install` from git+ssh starts MCP server

### Checklist: Slice 4

- [ ] `agent-orchestrator-mcp/pyproject.toml` depends on git+ssh URL
- [ ] `packages/agent-handoff-mcp/` deleted
- [ ] `packages/wp-testing-helpers/` deleted
- [ ] `packages/Makefile` updated
- [ ] `README.md` and `CLAUDE.md` updated
- [ ] `make test-orchestrator` passes
- [ ] `make check-mcp` passes

### Checklist: Slice 5

- [ ] `docs/agentic/contracts/agent-handoff-mcp.md` updated
- [ ] `docs/agentic/contracts/agent-orchestrator-mcp.md` updated
- [ ] `docs/agentic/BOOTSTRAP.md` updated
- [ ] Relevant `docs/agentic/playbooks/**/*.md` updated
- [ ] Package-local docs updated
- [ ] Live-surface grep is clean with documented historical/generated carve-outs

## Review Readiness

- [ ] No boundary-touching implementation left without matching contract evidence
- [ ] Handoff decision records each slice completion
- [ ] `CURRENT_TASK.md` regenerated after final slice

## Success Criteria

- [ ] `darce/mcp-agent-handoff` is a functional private GitHub repo with passing CI
- [ ] This monorepo installs and uses it via git+ssh with no source-path coupling
- [ ] `packages/agent-handoff-mcp/` no longer exists in the monorepo
- [ ] No live runtime/config/operator surface still depends on `packages/agent-handoff-mcp/src` (historical planning docs and generated metadata excluded)
- [ ] MCP server connects in all configured IDEs
