# MCP and Tooling Automation

## Objective

Move the highest-value process rules out of agent memory and into discoverable skills, automated Make targets, and structured MCP surfaces so agents spend less time rediscovering safe procedures and reviewers can trust tooling to enforce co-change and evidence gates.

## Problem Statement

Phases 1-3 codified the process rules; agents now know what to do if they load the right docs. But the rules still rely on agent recall rather than tooling enforcement:

- Daemon lifecycle procedures (safe start, signal stop, stale-lock recovery, pause/resume) are implemented in four code files (`api.py`, `orchestrator_daemon.py`, `worker_daemon.py`, `worker_daemon_ctl.py`) but no skill encodes the safe interaction patterns. Agents rediscover them through code archaeology.
- No rescue-lane protocol exists. Recovery from lane regressions is ad hoc; the cherry-pick, contract-diff, and MCP-decision workflow is undocumented.
- `make lane-intake` updates lane state after a successful intake, and that MCP write currently regenerates `CURRENT_TASK.md` indirectly. The workflow does not make that guarantee explicit or regression-test it, so the sync behavior is easy to break silently during future refactors.
- `make lane-intake` has no post-intake cross-lane regression gate; a clean lane intake can still break a previously-merged lane's tests.
- ~50 MCP tools exist with comprehensive functionality, but no classification distinguishes which are stateful actions, which are read-only queries, and which should be prompt templates. Agents cannot tell from the tool list what is safe to retry, what mutates state, and what is informational.
- Skill files do not consistently declare triggers, owned outputs, safety constraints, retry/recovery rules, or convergence criteria. They are advisory prose rather than structured execution patterns.
- The repo-local `subfeature-committer` skill surface is missing from the current skill inventory even though it is the most natural companion to `commit2git` for small finished slices.
- The `agent-handoff-mcp` contract doc does not always stay synchronized with the operator README after tool surface changes.
- Policy text is duplicated across skills, instructions.md, and README surfaces, creating drift risk.

## Constraints

- Skills are documentation; they encode patterns from existing working code, not new runtime features. No new MCP tool endpoints are required for Slices 1-2.
- Lane-intake changes (Slice 2) must not break existing `make lane-intake` workflows that rely on `SKIP_TESTS=1` or `DRY_RUN=1`.
- MCP surface classification (Slice 3) is an audit and documentation exercise; it does not require refactoring the existing tool registration in `api.py`.
- Review-readiness automation (Slice 4) should reuse existing MCP queries (`get_handoff_state`, `list_review_findings`, `get_review_findings_summary`, `handoff_close_check`) rather than adding new MCP endpoints.
- Selective-memory surfaces (Slice 5) should prefer composition of existing tools over new database schema.
- If Slice 2 introduces manifest-driven post-intake checks, it must update the real manifest readers (`lane_manifest.py`, `lane_config.py`) in the same slice rather than assuming JSON keys will be available automatically.

## Workflow Principles

- Skills encode patterns from working code; do not speculate about procedures that have not been validated in production.
- Tooling gates should fail loudly with actionable output, not silently pass.
- MCP surface classification informs how agents call tools (idempotent reads vs. state-mutating writes) but does not change runtime behavior.
- Policy deduplication removes the copy, not the canonical source. Rules own policy; skills route to rules.

## Terminology

- **Skill**: A `SKILL.md` file under `docs/agentic/skills/` that encodes a bounded execution pattern with triggers, steps, safety constraints, and convergence criteria.
- **MCP surface class**: Whether a tool is a stateful action (creates/mutates records), a read-only query (safe to retry, no side effects), or a prompt/template surface (generates text from state).
- **Post-intake gate**: A verification step that runs automatically after `make lane-intake` succeeds, before the orchestrator branch is considered clean.
- **Review-readiness check**: A scripted summary of whether a branch meets the pre-review evidence requirements (open findings, contract co-change, test evidence, docs drift).
- **Subfeature committer**: A repo-local skill for committing one already-isolated completed slice when `commit2git` would be unnecessarily broad.

## Current State Analysis

- 3 repo-local skills exist (`commit2git`, `worktree-orchestrator`, `worktree-worker`); the commit-oriented `subfeature-committer` surface is still absent/empty, and none of the existing skills have structured trigger/recovery/convergence sections.
- No `daemon-lifecycle` or `rescue-lane` skill exists.
- `mk/lane-maintenance.mk` `lane-intake` target (L213-284) validates scope and runs lane tests, then fast-forwards the orchestrator branch. It relies on the downstream `lane-upsert` MCP write to keep `CURRENT_TASK.md` current, but that coupling is implicit and unverified. No cross-lane post-intake gate exists.
- `api.py` registers ~50 MCP tools via `FastMCP`. The contract doc (`docs/agentic/contracts/agent-handoff-mcp.md`) describes them categorically but does not classify each by read/write/template semantics.
- `instructions.md` selective-memory guidance (hot/warm/cold state tiers) is defined in prose but has no tooling counterpart that enforces or automates the tiering.
- `ctx7` entry criteria are documented in `instructions.md` but no repo helper caches resolved library IDs or suggests queries.

## Target Outcome

After this task:

1. Agents can invoke a `daemon-lifecycle` skill for safe daemon interaction without reading four source files.
2. Agents can invoke a `rescue-lane` skill for structured lane recovery without improvising cherry-pick workflows.
3. `make lane-intake` explicitly preserves its existing `CURRENT_TASK.md` sync behavior and runs a cross-lane post-intake gate, so the orchestrator branch is never left in a stale or silently-regressed state.
4. Every MCP tool has a documented surface class (action/query/generator) so agents know what is safe to retry and what mutates state.
5. Skills follow a consistent structure with explicit triggers, constraints, recovery, and convergence criteria.
6. A scripted review-readiness check summarizes branch evidence status before review.
7. Policy text lives in one canonical location; skills and READMEs reference rather than duplicate.

## Context Loading

- Rules: `docs/agentic/rules/branch-review-guide.md`, `docs/agentic/rules/development-workflow.md`
- Contracts: `docs/agentic/contracts/agent-handoff-mcp.md`
- Epic: `docs/epics/v0.3.0/agentic-development-process-hardening-epic.md` (Phase 4 deliverables and checklist)
- Handoff/MCP state: task ref `agentic-development-process-hardening-epic`; review Phase 4 checklist items
- Skills: existing skills under `docs/agentic/skills/` for format reference
- Code: `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` (tool registrations), `orchestrator_daemon.py`, `worker_daemon.py`, `worker_daemon_ctl.py` (daemon patterns)
- Makefile: `mk/lane-maintenance.mk` (lane-intake target), `mk/lane-lifecycle.mk` (lane targets)
- Manifest/runtime config: `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_manifest.py`, `lane_config.py`

## Contract and Boundary Impact

| Boundary                         | Owner           | Current Contract                                                                                                                                                                               | Expected Change                                                                                                                     | Compatibility Needed?                           | Verification                                                                                        |
| -------------------------------- | --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `agent-handoff-mcp` tool surface | agentic-tooling | `docs/agentic/contracts/agent-handoff-mcp.md`                                                                                                                                                  | Add surface-class annotations to tool catalog                                                                                       | No; documentation only                          | Contract doc updated in same slice                                                                  |
| `make lane-intake`               | orchestration   | `mk/lane-maintenance.mk` + `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_manifest.py` + `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_config.py` | Preserve current `CURRENT_TASK.md` sync path, add post-intake gate, and add manifest/config support if checks are lane-configurable | Yes; `SKIP_TESTS` and `DRY_RUN` must still work | Existing lane-intake behavior preserved; manifest-backed checks resolve through real config readers |

## Proposed Solution

Five slices delivered in dependency order:

1. **Skills first**: create `daemon-lifecycle`, `rescue-lane`, and `subfeature-committer` skills from existing code patterns; retrofit structured sections onto existing skills.
2. **Lane-intake fixes**: preserve the existing `CURRENT_TASK.md` sync path explicitly and add a post-intake `check-all` gate to `mk/lane-maintenance.mk`, including manifest/config support if the checks are lane-configurable.
3. **MCP classification**: audit all ~50 tools, classify each as action/query/generator, document a troubleshooting ladder, and update the contract doc.
4. **Review-readiness command**: add a scripted `make review-ready` target that checks open findings, contract co-change, test evidence, and docs drift.
5. **Documentation sync and deduplication**: synchronize contract and README, reduce policy duplication across skills, and add ctx7 caching guidance.

## Files and Surfaces to Change

| Surface  | File                                                                              | Change                                                                                       |
| -------- | --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| skill    | `docs/agentic/skills/daemon-lifecycle/SKILL.md`                                   | Create; encode safe-start, signal-stop, stale-lock-recovery, pause/resume, lane-health-check |
| skill    | `docs/agentic/skills/rescue-lane/SKILL.md`                                        | Create; encode cherry-pick rescue, contract diff, MCP decision, regeneration                 |
| skill    | `docs/agentic/skills/subfeature-committer/SKILL.md`                               | Create; encode single-slice commit flow for already-isolated completed work                  |
| skill    | `docs/agentic/skills/worktree-orchestrator/SKILL.md`                              | Add structured trigger/recovery/convergence sections                                         |
| skill    | `docs/agentic/skills/worktree-worker/SKILL.md`                                    | Add structured trigger/recovery/convergence sections                                         |
| skill    | `docs/agentic/skills/commit2git/SKILL.md`                                         | Add structured trigger/recovery/convergence sections                                         |
| tooling  | `mk/lane-maintenance.mk`                                                          | Preserve verified `CURRENT_TASK.md` sync behavior and add `check-all` gate to `lane-intake`  |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_manifest.py` | Add manifest support for post-intake checks if Slice 2 uses lane-configurable commands       |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_config.py`   | Expose post-intake check settings to Make helpers if Slice 2 uses lane-configurable commands |
| contract | `docs/agentic/contracts/agent-handoff-mcp.md`                                     | Add per-tool surface-class catalog (action/query/generator), MCP troubleshooting ladder      |
| docs     | `packages/agent-handoff-mcp/README.md`                                            | Synchronize with contract doc after classification changes                                   |
| rules    | `docs/agentic/rules/development-workflow.md`                                      | Add review-readiness check reference                                                         |
| tooling  | `Makefile` or `mk/`                                                               | Add `review-ready` target                                                                    |
| docs     | `docs/agentic/instructions.md`                                                    | Add ctx7 caching guidance; remove any policy text that duplicates rules                      |

## Related Files

| File                                                                              | Note                                                                                            |
| --------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`                         | Source of truth for all MCP tool registrations; ~50 tools                                       |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestrator_daemon.py`         | Safe-start, lock, pause/resume, health-check patterns for daemon-lifecycle skill                |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/worker_daemon.py`               | Worker daemon patterns: poll, preflight, handoff, observability                                 |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/worker_daemon_ctl.py`           | Control commands: start, stop, resume, status, event history                                    |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_manifest.py` | Validates and normalizes lane manifest fields; must change if Slice 2 adds `post_intake_checks` |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_config.py`   | Emits manifest-derived values to Make helpers; must change if Slice 2 adds `post_intake_checks` |
| `mk/lane-lifecycle.mk`                                                            | Lane lifecycle targets that may need coordination with lane-intake changes                      |
| `config/lane-orchestration/`                                                      | Lane manifest files; relevant for rescue-lane skill context                                     |

## Verification Strategy

- Deterministic tests:
  - Existing `make lane-intake DRY_RUN=1` still works after Slice 2 changes
  - `make review-ready` runs and produces structured output (Slice 4)
- Contract/fixture verification:
  - `docs/agentic/contracts/agent-handoff-mcp.md` surface-class catalog matches actual `api.py` registrations
  - Every skill file contains required structural sections (trigger, constraints, recovery, convergence)
  - If Slice 2 adds `post_intake_checks`, manifest/config readers parse and surface the new field correctly
- Manual verification:
  - Daemon-lifecycle skill steps match actual daemon management commands
  - Rescue-lane skill steps execute end-to-end on a test branch

## Slice Delivery

### Slice 1: Daemon Lifecycle and Rescue Lane Skills

**Goal**: Create the missing high-value repo-native skills and retrofit structured execution sections onto all existing skills.

Changes:

- Create `docs/agentic/skills/daemon-lifecycle/SKILL.md`:
  - **Trigger**: agent needs to start, stop, pause, resume, or troubleshoot an orchestrator or worker daemon
  - **Steps**: safe-start (check stale lock, PID liveness, log tailing); signal-stop (SIGTERM, wait, SIGKILL escalation); stale-lock recovery (stale PID detection, lock removal, restart); pause/resume (sentinel file creation/removal); lane-health-check (exhaustion streak, scope violations, token burn)
  - **Safety constraints**: never `kill -9` without first attempting SIGTERM; always verify lock is stale before removal; do not auto-restart unhealthy lanes (exhaustion_streak >= 2)
  - **Recovery**: if daemon fails to start, check lock, log, and port; if stop hangs, escalate to SIGKILL after timeout
  - **Convergence**: daemon running and accepting cycles; or daemon cleanly stopped and lock removed
  - Source patterns from: `OrchestratorLock` / `WorkerLock`, `daemon_pause` / `daemon_resume` / `daemon_status`, `daemon_start` / `daemon_stop` in `worker_daemon_ctl.py`, `_check_lane_health` in `orchestrator_daemon.py`

- Create `docs/agentic/skills/rescue-lane/SKILL.md`:
  - **Trigger**: lane regression detected (failing tests, scope violations, or merge conflict) that cannot be resolved by normal lane-check
  - **Steps**: (a) identify last known-good commit on the lane branch; (b) create rescue branch `codex/rescue-<lane>-<timestamp>` from that commit; (c) cherry-pick fix commits; (d) diff contract surfaces between rescue branch and broken lane; (e) run lane test pack plus targeted regression test; (f) update MCP state with a rescue decision record; (g) regenerate `CURRENT_TASK.md`
  - **Safety constraints**: never force-push the broken lane; always create a new rescue branch; run full lane test pack before declaring rescue complete
  - **Recovery**: if cherry-pick conflicts, record blocker and escalate to orchestrator
  - **Convergence**: rescue branch passes all lane tests; MCP decision records the rescue; broken lane status updated

- Create `docs/agentic/skills/subfeature-committer/SKILL.md`:
  - **Trigger**: one completed slice is already isolated in the working tree and needs a single intentional commit without the broader grouping pass of `commit2git`
  - **Steps**: inspect diff, confirm the slice boundary, stage only the finished slice, verify staged story, commit with a precise subject, and confirm the remaining worktree state
  - **Safety constraints**: do not sweep unrelated files into the commit; do not use it when the branch clearly contains multiple finished slices that require grouping
  - **Recovery**: if the slice is interleaved with unrelated hunks, stop and switch to `commit2git` or hunk-splitting
  - **Convergence**: exactly one coherent finished slice is committed and the remaining working tree is intentionally left for the next slice

- Retrofit existing skills (`commit2git`, `worktree-orchestrator`, `worktree-worker`) with structured sections: **Trigger**, **Safety constraints**, **Recovery**, **Convergence criteria**; keep existing content, add the missing structural sections

Proof:

- All 6 skill files exist under `docs/agentic/skills/`
- Each contains: trigger, steps/checklist, safety constraints, recovery, convergence criteria
- Daemon-lifecycle steps reference real function names from the codebase
- Rescue-lane steps reference real git and MCP commands
- Subfeature-committer cleanly differentiates itself from `commit2git`

### Slice 2: Lane Intake Automation

**Goal**: Make `make lane-intake` leave the orchestrator branch in a fully verified and documented state by preserving the existing `CURRENT_TASK.md` sync behavior explicitly and adding a cross-lane check-all gate.

Changes:

- Make the `CURRENT_TASK.md` sync path explicit:
  - Preserve the current regeneration behavior that already flows through the successful `lane-upsert` MCP write
  - Add proof in tests or dry-run/behavior checks that a successful intake still leaves `CURRENT_TASK.md` current
  - Guard the behavior so `DRY_RUN=1` still avoids side effects

- Add a post-intake `check-all` gate:
  - After the fast-forward merge (and before declaring success), run a configurable set of cross-lane verification commands
  - If the commands are lane-configurable, add a lane manifest field such as `post_intake_checks` and wire it through `lane_manifest.py` and `lane_config.py`; otherwise explicitly scope a fixed default command path
  - If any check fails, print the failure but do NOT roll back the merge (the merge is already committed); instead, emit a warning and record a blocker via MCP
  - Allow skipping with `SKIP_POST_INTAKE=1` for cases where cross-lane tests are known to be temporarily broken

Proof:

- `make lane-intake` with a real or mock lane still leaves `CURRENT_TASK.md` current after success
- `make lane-intake DRY_RUN=1` does NOT regenerate or run post-intake checks
- `make lane-intake SKIP_TESTS=1` still works as before
- If `post_intake_checks` is manifest-backed, lane manifest/config helpers parse and expose it correctly
- Post-intake check failure emits a warning but does not roll back the merge

### Slice 3: MCP Surface Classification and Troubleshooting

**Goal**: Classify every MCP tool by surface class so agents know what is safe to retry, what mutates state, and what generates output; add a troubleshooting ladder for common MCP failures.

Changes:

- Audit all ~50 tools in `api.py` and classify each as:
  - **action**: creates or mutates state (e.g., `set_handoff_state`, `record_decision`, `record_review_finding`, `switch_task`, `worker_start`, `orchestrator_start`)
  - **query**: read-only, safe to retry, no side effects (e.g., `get_handoff_state`, `list_review_findings`, `get_review_findings_summary`, `search_handoff`, `list_worktree_lanes`)
  - **generator**: produces derived output from state (e.g., `generate_current_task_md`, `export_handoff_state`, `get_handoff_dashboard`, `handoff_close_check`)

- Add a per-tool surface-class catalog to `docs/agentic/contracts/agent-handoff-mcp.md` as a table: tool name, surface class, idempotent (yes/no), notes

- Add an MCP troubleshooting ladder section to the contract doc:
  - **Startup failure**: binary not found, wrong workspace-root, state-dir missing
  - **Capability discovery failure**: tool not registered, version mismatch, transport misconfiguration
  - **Runtime execution failure**: write conflict (expected_revision mismatch), FTS5 error, database locked
  - **Evidence-write failure**: finding/decision not persisted, CURRENT_TASK.md not regenerated

- Synchronize `packages/agent-handoff-mcp/README.md` with any structural changes to the contract doc

Proof:

- Contract doc contains a complete tool catalog with surface class for every registered tool
- Troubleshooting ladder covers all four failure layers with inspection commands
- README and contract doc are synchronized (no contradictions)

### Slice 4: Review Readiness Command

**Goal**: Add a scripted `make review-ready` target that summarizes whether a branch meets pre-review evidence requirements, so agents and operators can check readiness before requesting review.

Changes:

- Create a `review-ready` Make target (in `Makefile` or a new `mk/review-gates.mk`):
  - Query MCP for open review findings (`get_review_findings_summary`); report count
  - Query MCP for open blockers; report count
  - Check whether any boundary-touching files changed without matching contract/doc updates (using `git diff --name-only` against known contract paths)
  - Check whether `CURRENT_TASK.md` is stale (compare MCP revision against generated file)
  - Check whether any test evidence is recorded (`record_test_result` entries exist)
  - Output a structured summary: READY / NOT READY with itemized reasons

- Add a reference to the review-readiness check in `docs/agentic/rules/development-workflow.md`

- Ensure the target works from both orchestrator root and worker worktrees (using `--state-dir` and `--workspace-root` resolution)

Proof:

- `make review-ready` runs against current branch and produces structured output
- A branch with open HIGH findings reports NOT READY
- A clean branch with no open findings and test evidence reports READY

### Slice 5: Documentation Sync and Policy Deduplication

**Goal**: Synchronize contract and operator docs, reduce policy duplication across skills and instructions, and add ctx7 caching guidance.

Changes:

- Deduplicate policy text across skills and `instructions.md`:
  - Identify passages in skill files that restate rules from `instructions.md` or `rules/`
  - Replace with concise cross-references: "See [rules/development-workflow.md](../../rules/development-workflow.md) for the full protocol"
  - Keep only skill-specific behavioral guidance in skill files

- Synchronize `packages/agent-handoff-mcp/README.md` with `docs/agentic/contracts/agent-handoff-mcp.md`:
  - Ensure CLI examples, transport configuration, and capability descriptions match
  - Add a note in README pointing to the contract doc as the canonical reference

- Add ctx7 caching guidance to `docs/agentic/instructions.md`:
  - When a `ctx7` lookup resolves a library ID that will be reused, record the library ID and the specific query in the handoff decision
  - Future sessions referencing the same dependency should check handoff for a cached library ID before issuing a new `ctx7` resolve

- Update epic Phase 4 checklist items to checked

Proof:

- No skill file contains more than one paragraph of policy text that duplicates a rule or instruction
- README and contract doc do not contradict each other on CLI args, transport, or tool behavior
- `instructions.md` ctx7 section references caching guidance
- Epic Phase 4 checklist fully checked

---

# Consolidated Checklist

## Context and Ownership

- [x] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [x] Confirmed whether external dependency context requires `ctx7`.
- [x] Reviewed epic Phase 4 deliverables and checklist for completeness.

## Slice 1: Daemon Lifecycle and Rescue Lane Skills

- [x] Created `docs/agentic/skills/daemon-lifecycle/SKILL.md` with trigger, steps, safety, recovery, convergence.
- [x] Created `docs/agentic/skills/rescue-lane/SKILL.md` with trigger, steps, safety, recovery, convergence.
- [x] Created `docs/agentic/skills/subfeature-committer/SKILL.md` with trigger, steps, safety, recovery, convergence.
- [x] Retrofitted `commit2git/SKILL.md` with structured sections.
- [x] Retrofitted `worktree-orchestrator/SKILL.md` with structured sections.
- [x] Retrofitted `worktree-worker/SKILL.md` with structured sections.
- [x] All 6 skill files reference real function/command names from the codebase.
- [x] Handoff decision recorded for Slice 1.

## Slice 2: Lane Intake Automation

- [x] Preserved and verified `CURRENT_TASK.md` sync on the `make lane-intake` success path.
- [x] Added post-intake `check-all` gate with configurable commands.
- [x] `DRY_RUN=1` skips regeneration and post-intake checks.
- [x] `SKIP_TESTS=1` still works as before.
- [x] `SKIP_POST_INTAKE=1` skips post-intake cross-lane checks.
- [x] If configurable checks are manifest-backed, `lane_manifest.py` and `lane_config.py` support the new field.
- [x] Post-intake check failure emits warning but does not roll back merge.
- [x] Handoff decision recorded for Slice 2.

## Slice 3: MCP Surface Classification and Troubleshooting

- [x] Audited all tools in `api.py`; classified each as action/query/generator.
- [x] Added per-tool surface-class catalog table to contract doc.
- [x] Added MCP troubleshooting ladder (startup, discovery, runtime, evidence-write).
- [x] Synchronized README with contract doc.
- [x] Handoff decision recorded for Slice 3.

## Slice 4: Review Readiness Command

- [x] Created `make review-ready` target.
- [x] Checks: open findings, open blockers, contract co-change, stale CURRENT_TASK.md, test evidence.
- [x] Outputs structured READY / NOT READY summary.
- [x] Works from orchestrator root and worker worktrees.
- [x] Referenced in `development-workflow.md`.
- [x] Handoff decision recorded for Slice 4.

## Slice 5: Documentation Sync and Policy Deduplication

- [x] Deduplicated policy text across skills (replaced with cross-references).
- [x] Synchronized README and contract doc.
- [x] Added ctx7 caching guidance to `instructions.md`.
- [x] Updated epic Phase 4 checklist items to checked.
- [x] Handoff decision recorded for Slice 5.

## Review Readiness

- [x] No boundary-touching implementation is left without matching contract/doc/fixture evidence.
- [x] All new skills follow the structured skill template with trigger, safety, recovery, convergence.
- [x] Handoff decision records the change, verification, and any contract implications.

## Success Criteria

- [x] Agents can invoke `daemon-lifecycle` and `rescue-lane` skills from cold start without reading source code.
- [x] Agents can invoke `subfeature-committer` for a single isolated slice without misusing `commit2git`.
- [x] `make lane-intake` leaves `CURRENT_TASK.md` current and runs cross-lane verification.
- [x] Every MCP tool has a documented surface class (action/query/generator) in the contract doc.
- [x] `make review-ready` produces a structured pre-review evidence summary.
- [x] Policy text exists in exactly one canonical location; skills cross-reference rather than duplicate.
