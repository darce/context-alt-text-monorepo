# E17-13. Hoisted Surface Cleanup and External Repo Consumption

- **Date**: 2026-04-23 10:16 EDT
- **Author**: Codex
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-13`
- **Review Coverage Target**: 2
- **Source Scope**: [docs/scopes/e17-10-hoisted-surface-cleanup-scope.md](../../scopes/e17-10-hoisted-surface-cleanup-scope.md)
- **Superseded Scope Path**: `docs/scopes/e17-10-external-mcp-cleanup-scope.md` was renamed during scope review because the work covers the full hoisted family, not only MCP repos.
- **Hard Prerequisites**: E17-10 follow-on publication/validation work has completed enough that the external refs this task consumes are reachable and installable. Before any deletion slice starts, this task must verify all four external repos over SSH and confirm `darce/agentic-bootstrap@v0.2.0` installs successfully even if the remote default branch is README-only; recovery/republish work is only triggered if the tag install fails.

---

## Objective

Make this monorepo consume the hoisted external repos as the canonical implementation boundary, then remove duplicated root-repo surfaces incrementally once external functionality is confirmed. This task intentionally happens before E17-10 MVP closure so publication/validation work and monorepo cleanup remain separate review units.

## Intake

- **Scope one-pager**: [docs/scopes/e17-10-hoisted-surface-cleanup-scope.md](../../scopes/e17-10-hoisted-surface-cleanup-scope.md)
- **Key Q&A decisions**: The user confirmed the MVP is both external consumption and root-repo cleanup; all root-repo surfaces that belong in external repos are in scope; all three completion signals from the scope are required; deletion is allowed only after external functionality is confirmed.
- **Not-Doing**: no premature deletion, no audit-only final outcome, no consumer-repo cleanup except bounded validation, no retagging/republishing unless the cleanup uncovers a missing upstream capability, and no deletion of alt-context-specific contracts.

## Problem Statement

E17-10 hoisted the shared agentic system into four external repos, but this monorepo still carries duplicated implementation and shared-surface copies. That split creates ambiguous ownership: some configs and docs point at external repos, while package source, tests, hooks, skills, contracts, and compatibility shims still live in root. Until the monorepo is converted into a consumer of the external refs, MVP validation and post-MVP cleanup are coupled together and future work can accidentally modify the wrong source of truth.

## Constraints

- **Externalize first, then delete.** No root-repo surface may be removed until the external replacement is installed/cloned from the exact ref and has proven equivalent behavior.
- **Four-repo family.** The canonical external repos are `darce/mcp-agent-handoff`, `darce/mcp-agent-orchestrator`, `darce/agentic-system`, and `darce/agentic-bootstrap`. Only the first two carry the `mcp-` prefix because only they ship MCP servers.
- **Bootstrap gate.** First test-install `darce/agentic-bootstrap@v0.2.0`; only if that immutable tag is missing or not installable does the first slice recover or republish bootstrap before any slice depends on it.
- **Contract split preserved.** Agentic-only contracts move to or are consumed from `darce/agentic-system`; alt-context-specific contracts remain in this monorepo.
- **Branch isolation.** Monorepo edits happen on `feature/e17-13`; external repo repairs, if required, happen in their own isolated external-repo worktrees and are referenced by immutable SHAs/tags before monorepo deletion proceeds.
- **No raw DB access.** Handoff verification uses `agent-handoff-mcp` CLI/API surfaces, not direct `sqlite3`, except for schema debugging outside this task.
- **No compatibility shim in greenfield paths.** Temporary wrappers may exist only to reduce migration risk and must have an explicit removal condition.

## Workflow Principles

- Delete by ownership boundary, not by directory size.
- Every slice must produce behavior plus proof; inventory-only work is allowed only in the prerequisite slice.
- Prefer pinned external refs for deterministic cleanup. Tracking `main` is acceptable only for a temporary smoke and must not be the final documented consumption path.
- Archived historical docs may retain old paths when clearly archived; live workflow docs, configs, tests, and rules must not.

## Terminology

- **Hoisted family**: the four external repos under `darce/` that own MCP packages, shared agentic surfaces, and bootstrap installation.
- **Root duplicate**: a monorepo file or directory whose canonical owner is now one of the hoisted external repos.
- **Monorepo-local override**: a root file intentionally retained because it is specific to this project and not shared upstream.
- **Deletion gate**: the external install/clone plus monorepo proof required before removing a root duplicate.

## Current State Analysis

- `packages/agent-handoff-mcp/` and `packages/agent-orchestrator-mcp/` still contain package source, tests, docs, and package-local Makefiles in the monorepo, even though external repos with `mcp-` prefixes are reachable.
- `packages/codex-subagent-bridge/` is not part of the E17-10 hoisted family and remains a monorepo-local package unless Slice 1 records a separate ownership decision.
- `packages/shared-contracts/` contains alt-context/product contracts and remains monorepo-local unless Slice 1 identifies a specific shared-surface subset that belongs in `darce/agentic-system`.
- `scripts/mcp/mcp-server.sh` remains a monorepo-local compatibility shim and is still referenced by local adapter smoke tests.
- `.claude/skills/`, `.github/hooks/`, `scripts/hooks/`, `.github/prompts/`, `.claude/commands/`, `config/agent-workflows/`, and agentic-only contracts are duplicated shared surfaces that should ultimately be consumed from `darce/agentic-system`, except for explicit monorepo-local overrides.
- `docs/agentic/contracts/` mixes agentic-only contracts with alt-context-specific contracts; cleanup must preserve that split.
- Live rules and docs still reference monorepo package paths, including constitution guards such as `rg-013` and `rg-014`.
- Follow-on scope review reported that `darce/agentic-bootstrap` default branch may be README-only, while tags such as `v0.1.0` and `v0.2.0` may still contain package content. Bootstrap publishability is therefore checked by installing the selected tag first, not by treating default-branch contents as authoritative.

## Target Outcome

The monorepo becomes a consumer of the hoisted family. MCP runtime/config/test flows install and invoke the external `mcp-*` packages; shared skills/hooks/prompts/commands/workflows and agentic-only contracts come through the `agentic-bootstrap` / `agentic-system` overlay; root duplicates are deleted or intentionally retained as monorepo-local overrides with documented ownership.

## Context Loading

- Rules: [docs/agentic/instructions.md](../../agentic/instructions.md), [docs/agentic/rules/development-workflow.md](../../agentic/rules/development-workflow.md), [docs/agentic/rules/planning-review-guide.md](../../agentic/rules/planning-review-guide.md)
- Constitution: [docs/agentic/constitution.md](../../agentic/constitution.md)
- Scope: [docs/scopes/e17-10-hoisted-surface-cleanup-scope.md](../../scopes/e17-10-hoisted-surface-cleanup-scope.md)
- Source plans: [E17-10-hoist-agentic-system-mvp-task-plan.md](./E17-10-hoist-agentic-system-mvp-task-plan.md), [E17-10-followon-publish-and-validate-task-plan.md](./E17-10-followon-publish-and-validate-task-plan.md)
- Contracts: `docs/agentic/contracts/harness-protocol.yaml`, `docs/agentic/contracts/agent-handoff-mcp.md`, `docs/agentic/contracts/agent-orchestrator-mcp.md`, `docs/agentic/contracts/overlay-manifest.yaml`
- Handoff/MCP state: task ref `E17-13`; review findings under `MAINT-e17-10-scope-review-20260423` were fixed before plan drafting.
- External docs via `ctx7` only if: bootstrap or packaging behavior depends on an upstream library/API whose current behavior is unknown.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Handoff MCP package | `darce/mcp-agent-handoff` | duplicated local source plus external repo | monorepo consumes external package; local duplicate removed | yes, CLI/API behavior must stay stable | external pip install, CLI smoke, monorepo handoff smoke |
| Orchestrator MCP package | `darce/mcp-agent-orchestrator` | duplicated local source plus external repo | monorepo consumes external package; local duplicate removed | yes, lane/review/orchestrator flows must stay stable | external pip install, orchestrator CLI smoke, lane/review dry-run |
| Shared agentic surface | `darce/agentic-system` | root copies under `.claude/`, `.github/`, `scripts/hooks/`, docs/contracts | monorepo consumes overlay; shared duplicates removed | yes, local overrides and alt-context contracts retained | `agentic-bootstrap install/update`, overlay manifest checks, validators |
| Bootstrap CLI | `darce/agentic-bootstrap` | expected package may not match current remote | consume publishable bootstrap package/ref | yes, install/update/doctor/repair must work | scratch venv pip install, CLI help/status/doctor |
| Harness configs | root `.mcp.json`, `.vscode/mcp.json`, `.codex/config.toml` | invoke installed console scripts but may still rely on local tests/source | remove local source coupling and stale shim refs | yes, harness startup must continue | config smoke plus doc-lock tests |
| Live rules/docs | `docs/agentic/**`, `CLAUDE.md` | package-path references in rules and instructions | references move to external boundary or validated consumer path | yes, rule intent preserved | grep audit and planning review |
| Contract split | `docs/agentic/contracts/` + `darce/agentic-system` | mixed agentic and alt-context contracts in root | agentic-only contracts externalized; alt-context contracts retained | yes, validators must resolve correct surface | contract inventory and `check-harness-sync` |

## Proposed Solution

Use a gated, incremental cleanup. Slice 1 verifies and, if needed, repairs the external consumption prerequisites. Slice 2 cuts MCP package runtime/test/config paths over to external installs without deleting source. Slice 3 deletes duplicated MCP package sources after the cutover proves stable. Slice 4 makes the monorepo consume the shared agentic overlay via bootstrap. Slice 5 deletes duplicated shared surfaces while preserving local overrides and alt-context contracts. Slice 6 reconciles rules/docs, removes the TODO, and runs final no-local-coupling audits.

## Files and Surfaces to Change

| Surface | File / Path | Change |
| --- | --- | --- |
| New task plan | `docs/tasks/17.0/E17-13-hoisted-surface-cleanup-task-plan.md` | this plan |
| Inventory proof | `docs/assessments/e17-13-hoisted-surface-inventory.md` | current-state inventory, external refs, deletion gates |
| Package duplicates | `packages/agent-handoff-mcp/`, `packages/agent-orchestrator-mcp/` | remove after external install cutover proves equivalent behavior |
| Other monorepo packages | `packages/codex-subagent-bridge/`, `packages/shared-contracts/` | classify as monorepo-local or explicitly deferred in Slice 1; do not delete as MCP duplicates |
| MCP shim | `scripts/mcp/mcp-server.sh` | remove or justify as transitional; update tests first |
| Harness configs | `.mcp.json`, `.vscode/mcp.json`, `.codex/config.toml` | ensure external package invocation only; no local source fallback |
| CI/workflow config | `.github/workflows/**`, `Makefile`, `mk/**`, `packages/Makefile` | remove local package-source assumptions and obsolete package targets |
| Shared workflow generator | `scripts/generate_agent_workflows.py`, `Makefile` targets `generate-agent-workflows` / `check-agent-workflows` | decide whether generator ownership moves to `darce/agentic-system` or remains a monorepo-local driver over external definitions |
| Shared surfaces | `.claude/skills/`, `.github/hooks/`, `scripts/hooks/`, `.github/prompts/`, `.claude/commands/`, `config/agent-workflows/` | consume from `darce/agentic-system`; retain only monorepo-local overrides |
| Contracts | `docs/agentic/contracts/` | remove local duplication for agentic-only contracts; retain alt-context-specific contracts |
| Rules/docs | `docs/agentic/**`, `CLAUDE.md`, `.github/copilot-instructions.md`, relevant task docs | update ownership and package-path references |
| Consumer setup docs/tests | `docs/agentic/consumer-setup.md`, `scripts/test_consumer_setup_doc.py` | keep pins and instructions aligned with external consumption |

## Related Files

| File | Note |
| --- | --- |
| `docs/scopes/e17-10-hoisted-surface-cleanup-scope.md` | source scope and deletion policy |
| `docs/tasks/17.0/E17-10-followon-publish-and-validate-task-plan.md` | publication/validation evidence this cleanup builds on |
| `scripts/README.md` | current `mcp-server.sh` boundary note |
| `scripts/overlay_resolver.py` | shared/local overlay resolution used by validators |
| `scripts/check_skills.py` | must work against overlay-resolved shared/local skill surface |
| `scripts/check_harness_sync.py` | must work after contract and hook surface externalization |
| `scripts/test_consumer_setup_doc.py` | doc-lock for consumer install URLs |
| `scripts/test_shared_agentic_surface_doc.py` | guards canonical external repo names |
| `packages/agent-handoff-mcp/tests/test_adapters.py` | currently references `scripts/mcp/mcp-server.sh` |
| `packages/agent-handoff-mcp/tests/conftest.py`, `packages/agent-orchestrator-mcp/tests/conftest.py` | package-local pytest guards that must be replaced by external-install verification before package deletion |
| `packages/codex-subagent-bridge/`, `packages/shared-contracts/` | non-hoisted-family package dirs that Slice 1 must classify explicitly |
| `scripts/generate_agent_workflows.py` | generator for workflow adapters; ownership must be decided with shared-surface migration |
| `docs/agentic/constitution.md` | source of `rg-013`, `rg-014`, and rule migration |

## Verification Strategy

- Deterministic tests:
  - `python3 -m pytest scripts/test_consumer_setup_doc.py scripts/test_shared_agentic_surface_doc.py -q`
  - `python3 -m pytest scripts/test_check_skills.py scripts/test_check_harness_sync.py scripts/test_lint_hoisted_paths.py -q`
- Runtime-parity / environment checks:
  - `git ls-remote --heads --tags git@github.com:darce/mcp-agent-handoff.git`
  - `git ls-remote --heads --tags git@github.com:darce/mcp-agent-orchestrator.git`
  - `git ls-remote --heads --tags git@github.com:darce/agentic-system.git`
  - `git ls-remote --heads --tags git@github.com:darce/agentic-bootstrap.git`
  - scratch venv `pip install` of the two MCP packages and bootstrap from pinned external refs
  - `agent-handoff-mcp --workspace-root . doctor`
  - `agent-orchestrator-mcp --workspace-root . --help` or equivalent import/CLI smoke
  - `agentic-bootstrap install --target <scratch-monorepo-consumer>` followed by `agentic-bootstrap doctor`
- Contract/fixture verification:
  - overlay manifest lists shared/local ownership after bootstrap install
  - contract inventory confirms agentic-only contracts are externalized and alt-context contracts remain local
  - grep audit confirms no live runtime/test/config path references deleted local package dirs
  - archived-reference audit treats only `docs/archive/**`, `docs/tasks/**` for completed historical task plans, `packages/*/docs/tasks/**`, `packages/*/docs/epics/**`, `packages/*/docs/assessments/**`, and explicit `HISTORICAL-REFERENCE:` marker comments as exempt
- Manual verification:
  - inspect `DASHBOARD.txt` / `CURRENT_TASK.json` regeneration after external package cutover
  - verify root worktree remains on `main` and cleanup work happens only in the feature worktree

## Slice Delivery

### Slice 1: External Ref and Bootstrap Prerequisite Gate

**Goal**: prove the external repo family is reachable, publishable, and suitable for monorepo consumption before any local deletion begins.

Changes:

- Create `docs/assessments/e17-13-hoisted-surface-inventory.md` with the exact refs/tags/SHAs selected for all four external repos.
- Verify `darce/agentic-bootstrap@v0.2.0` contains a package install surface by installing from that tag first. If the tag install fails, recover or republish bootstrap in the external repo before continuing.
- Inventory every `packages/*` directory and classify each as external-owned, monorepo-local override, archived-only reference, explicitly deferred, or transitional wrapper.
- Record the first deletion-gate matrix: replacement ref, proof command, local paths blocked from deletion until proof passes.
- Decide generator ownership for `scripts/generate_agent_workflows.py` and `make generate-agent-workflows` / `make check-agent-workflows`: either external-owned by `darce/agentic-system`, or retained as a monorepo-local driver over external workflow definitions.

Proof:

- `git ls-remote` succeeds for all four repos and the selected refs are recorded in the assessment.
- Scratch venv `pip install "git+ssh://git@github.com/darce/agentic-bootstrap.git@v0.2.0"` succeeds, or the slice records a blocker and no deletion slices run.
- Inventory assessment lists all candidate surfaces and owner classification.
- Inventory assessment explicitly classifies `packages/codex-subagent-bridge/`, `packages/shared-contracts/`, and `scripts/generate_agent_workflows.py`.

### Slice 2: External MCP Runtime Cutover

**Goal**: make monorepo runtime/config/test flows use the external `mcp-*` packages without deleting local source yet.

Changes:

- Update live configs, Makefiles, CI, and smoke tests so handoff/orchestrator runtime paths invoke installed external packages from pinned refs.
- Replace `scripts/mcp/mcp-server.sh` test dependencies with installed-console-script smoke coverage, or record why the shim remains transitional.
- Add/adjust smoke tests that prove the installed external package surfaces satisfy monorepo runtime expectations.
- Replace the package-local pytest guard model (`packages/*/tests/conftest.py` plus `make test-handoff` / `make test-orchestrator`) with an external-install verification convention: no editable installs from this monorepo, pinned `pip install` from external refs in scratch venvs, and explicit CLI/import smoke checks.
- Keep local `packages/agent-{handoff,orchestrator}-mcp/` present but ignored by the new runtime proof.

Proof:

- Scratch venv installs `darce/mcp-agent-handoff` and `darce/mcp-agent-orchestrator` from pinned refs.
- Handoff doctor and orchestrator CLI/import smoke run without `PYTHONPATH=packages/...` or editable local installs.
- Grep audit shows live configs/tests no longer rely on `scripts/mcp/mcp-server.sh` or local package source for runtime startup.
- `CLAUDE.md` and package-test instructions describe the new external-install verification convention before the old conftest guards are removed.

### Slice 3: Remove Duplicated MCP Package Sources

**Goal**: delete local MCP package source directories after Slice 2 proves external package consumption.

Changes:

- Remove `packages/agent-handoff-mcp/` and `packages/agent-orchestrator-mcp/` from the monorepo.
- Remove package-local Makefile targets, CI paths, and tests that only validate the duplicated local source.
- Apply only deletion-blocking rule/doc edits in this slice: `rg-013`, `rg-014`, and the package-test invocation rule must stop pointing at deleted package paths and must name the external package boundary. The broader guidance/doc sweep remains Slice 6.
- Remove `scripts/mcp/mcp-server.sh` if Slice 2 replaced its remaining usage; otherwise keep it with a documented transitional owner and follow-up removal condition.

Proof:

- `rg 'packages/agent-(handoff|orchestrator)-mcp|scripts/mcp/mcp-server.sh'` returns only hits under the archived-reference allow-list or lines marked `HISTORICAL-REFERENCE:` / documented transitional wrappers.
- External package runtime smoke from Slice 2 still passes after the local package dirs are absent.
- `python3 -m pytest scripts/test_consumer_setup_doc.py scripts/test_shared_agentic_surface_doc.py -q` passes.

### Slice 4: Monorepo Shared-Surface Overlay Cutover

**Goal**: make this monorepo consume shared skills/hooks/prompts/commands/workflows and agentic-only contracts from `darce/agentic-system` through bootstrap/overlay.

Changes:

- Run or adapt `agentic-bootstrap install/update` for the monorepo as a consumer, using a pinned `darce/agentic-system` ref.
- Preserve monorepo-local overrides in a clearly named local layer.
- Update overlay manifest handling and validators so root checks resolve effective shared/local surfaces correctly.
- Confirm hooks and generated workflow adapters still run from the overlay-resolved paths.
- Implement the generator ownership decision from Slice 1: either consume `scripts/generate_agent_workflows.py` from `darce/agentic-system`, or retain it locally as a driver that reads external workflow definitions and writes only monorepo-local generated outputs.

Proof:

- `agentic-bootstrap doctor` passes for the monorepo target or a documented scratch target that mirrors monorepo paths.
- `python3 -m pytest scripts/test_check_skills.py scripts/test_check_harness_sync.py scripts/test_lint_hoisted_paths.py -q` passes against the overlay-resolved surface.
- Overlay manifest shows shared surface refs and local override counts.

### Slice 5: Remove Duplicated Shared Agentic Surfaces

**Goal**: remove root duplicates for shared surfaces while preserving monorepo-local overrides and alt-context-specific contracts.

Changes:

- Delete shared `.claude/skills/`, `.github/hooks/`, `scripts/hooks/`, `.github/prompts/`, `.claude/commands/`, and `config/agent-workflows/` files that are now supplied by `darce/agentic-system`.
- Retain or relocate monorepo-local overrides under the overlay's local layer.
- Remove local duplication for agentic-only contracts; retain alt-context-specific contracts in this monorepo.
- Update docs and validators to describe the resulting root ownership model.

Proof:

- Contract inventory confirms agentic-only contracts resolve from external shared surface and alt-context-specific contracts remain local.
- Overlay validators pass.
- Grep audit shows no live config/test/doc instructs manual copying from the old root shared surface.

### Slice 6: Final Rule, TODO, and No-Local-Coupling Audit

**Goal**: close the cleanup by removing stale TODOs and proving no live monorepo path still depends on deleted duplicates.

Changes:

- Replace `TODO(E17-10-POST-MVP-CLEANUP)` with a completed-reference note pointing to this task and the final ownership model.
- Perform the full live-guidance sweep across `docs/agentic/instructions.md`, `docs/agentic/rules/development-workflow.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, and relevant task docs so live guidance names external repos and overlay ownership accurately. Do not repeat Slice 3's minimal package-deletion rule edits except to normalize wording.
- Record final handoff decisions and test results for the cleanup.

Proof:

- No live-path grep hits remain for deleted package dirs or deleted shared-surface roots, excluding only the archived-reference allow-list or `HISTORICAL-REFERENCE:` marker comments.
- All deterministic tests in the verification bundle pass.
- `handoff_close_check(task_ref="E17-13", enforce=True, require_fresh_tests=True, current_commit_sha=<HEAD>)` passes before merge.

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `mcp-cutover` | `packages/agent-handoff-mcp/**`, `packages/agent-orchestrator-mcp/**`, `scripts/mcp/**`, `.mcp.json`, `.vscode/mcp.json`, `.codex/config.toml`, `.github/workflows/**`, `mk/**`, `Makefile`, narrow package-deletion rule edits in `docs/agentic/constitution.md` and `CLAUDE.md` | Slice 1 refs complete | external MCP install smoke, handoff doctor, orchestrator smoke |
| `agentic-overlay` | `.claude/**`, `.github/hooks/**`, `.github/prompts/**`, `scripts/hooks/**`, `.claude/commands/**`, `config/agent-workflows/**`, `docs/agentic/contracts/**`, `scripts/generate_agent_workflows.py` if Slice 1 classifies it as shared-surface-owned | Slice 1 bootstrap consumable | `test_check_skills`, `test_check_harness_sync`, `test_lint_hoisted_paths` |
| `docs-rules` | `docs/agentic/instructions.md`, `docs/agentic/rules/**`, `docs/agentic/constitution.md` after Slice 3's narrow edits, `docs/agentic/generated/**`, `CLAUDE.md`, `.github/copilot-instructions.md`, `docs/tasks/17.0/**`, `scripts/README.md`; explicitly excludes `docs/agentic/contracts/**` | Slices 2-5 ownership decisions | grep audit, doc-lock tests |

### Merge Order

1. `mcp-cutover` Slice 2 before MCP source deletion.
2. `mcp-cutover` Slice 3 after Slice 2 proof.
3. `agentic-overlay` Slice 4 before shared-surface deletion.
4. `agentic-overlay` Slice 5 after Slice 4 proof.
5. `docs-rules` Slice 6 last, after final ownership is known; Slice 3 may make only the narrow deletion-blocking rule edits declared above.

### Manifest

```bash
make lane-manifest-init TASK=E17-13 LANE_IDS='mcp-cutover agentic-overlay docs-rules' TASK_PLAN=docs/tasks/17.0/E17-13-hoisted-surface-cleanup-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools with declared lane ownership and verification boundaries.
- **Shell fallback**: Use linked worktrees and root lane helpers while preserving the same ownership and evidence requirements.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, scope note, E17-10 source plans, and handoff state before editing.
- [ ] Confirmed whether external dependency context requires `ctx7`.
- [ ] Recorded boundary ownership and compatibility expectations for all four external repos.

### Checklist for Slice 1: External Ref and Bootstrap Prerequisite Gate

- [x] Verified all four external repos are reachable over SSH.
- [x] Confirmed selected refs/tags/SHAs for `mcp-agent-handoff`, `mcp-agent-orchestrator`, `agentic-system`, and `agentic-bootstrap`.
- [x] Test-installed `agentic-bootstrap@v0.2.0` first; only triggered recovery/republish if the tag install failed.
- [x] Wrote `docs/assessments/e17-13-hoisted-surface-inventory.md` with owner classification and deletion gates.
- [x] Classified every `packages/*` directory, including `codex-subagent-bridge` and `shared-contracts`.
- [x] Decided ownership of `scripts/generate_agent_workflows.py` and the `generate-agent-workflows` / `check-agent-workflows` targets.
- [x] Recorded verification evidence in handoff.

Handoff provenance discipline for remaining slices:

- For Slice 2+ handoff writes, capture `git rev-parse HEAD` from the feature worktree and pass that SHA as `actor.commit_sha`.
- Do not rely on the root worktree's ambient HEAD.

### Checklist for Slice 2: External MCP Runtime Cutover

- [x] Updated runtime/config/test flows to use installed external MCP packages from pinned refs.
- [x] Removed or replaced live dependence on `scripts/mcp/mcp-server.sh` for MCP startup tests.
- [x] Added installed-package smoke coverage for handoff and orchestrator.
- [x] Replaced package-local conftest/Makefile guard guidance with external-install verification guidance.
- [x] Proved no live runtime flow uses local package source.
- [x] Recorded verification evidence in handoff.

### Checklist for Slice 3: Remove Duplicated MCP Package Sources

- [x] Removed duplicated local MCP package dirs only after Slice 2 proof.
- [x] Removed obsolete local package CI/Makefile/test paths.
- [x] Migrated only deletion-blocking package rule references (`rg-013`, `rg-014`, package-test invocation guidance) away from package-local paths.
- [x] Removed or explicitly justified `scripts/mcp/mcp-server.sh`.
- [x] Re-ran external MCP smoke and no-local-coupling grep audit.

### Checklist for Slice 4: Monorepo Shared-Surface Overlay Cutover

- [ ] Installed or updated the monorepo shared surface from `darce/agentic-system` through bootstrap/overlay.
- [ ] Preserved monorepo-local overrides in the local layer.
- [ ] Verified overlay manifest, skills, hooks, commands, prompts, workflows, and contracts resolve as expected.
- [ ] Implemented the Slice 1 generator ownership decision.
- [ ] Ran overlay validators and lint.
- [ ] Recorded verification evidence in handoff.

### Checklist for Slice 5: Remove Duplicated Shared Agentic Surfaces

- [ ] Deleted shared root duplicates supplied by `darce/agentic-system`.
- [ ] Retained or relocated monorepo-local overrides.
- [ ] Removed local duplication for agentic-only contracts.
- [ ] Retained alt-context-specific contracts.
- [ ] Verified validators and contract inventory after deletion.

### Checklist for Slice 6: Final Rule, TODO, and No-Local-Coupling Audit

- [ ] Removed or replaced `TODO(E17-10-POST-MVP-CLEANUP)`.
- [ ] Updated live instructions, rules, contracts, and harness docs to the final ownership model.
- [ ] Ran final grep audit with the concrete archived-reference allow-list and `HISTORICAL-REFERENCE:` marker convention.
- [ ] Ran deterministic verification bundle.
- [ ] Recorded final slice-complete decision and fresh test evidence.

## Review Readiness

- [ ] No boundary-touching implementation is left without matching contract/doc/fixture evidence.
- [ ] Runtime-parity checks are included for every deletion gate.
- [ ] Handoff decision records the change, verification, and contract implications for each slice.
- [ ] External repo refs consumed by the monorepo are immutable or explicitly recorded.
- [ ] Open findings for `E17-13` are zero before merge.

## Stretch Goals

- [ ] Add a single `make check-hoisted-surface-cleanup` target that runs the final no-local-coupling audit and selected smoke checks.
- [ ] Generate a machine-readable ownership manifest for retained monorepo-local overrides.
- [ ] Add a dashboard section that reports external hoisted-family refs consumed by the monorepo.

## Success Criteria

- [ ] Monorepo runtime/config/test paths resolve against the external repos wherever those repos are the intended canonical home.
- [ ] Duplicated MCP package sources are removed from the monorepo after external MCP functionality is confirmed.
- [ ] Shared agentic root duplicates are removed or converted into explicit local overrides after overlay functionality is confirmed.
- [ ] Agentic-only contracts are consumed from `darce/agentic-system`; alt-context-specific contracts remain in this monorepo.
- [ ] No root-repo scripts remain that are only compatibility shims for extracted MCP behavior unless explicitly justified with a removal condition.
- [ ] `TODO(E17-10-POST-MVP-CLEANUP)` is replaced by final ownership documentation.
- [ ] `handoff_close_check(task_ref="E17-13", enforce=True, require_fresh_tests=True, current_commit_sha=<HEAD>)` passes before merge.
