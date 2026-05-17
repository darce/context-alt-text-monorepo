# Agent Skill Workflow Friction Assessment

> **Date**: 2026-05-15
> **Author**: GitHub Copilot
> **Scope**: Branch-review, planning-review, handoff-lifecycle, branch-lifecycle skills, and Make/MCP glue used by E15-22/E17-15 workflows
> **Status**: Draft

This assessment reviews the friction exposed by E15-22 implementation, branch review, close-check, merge, and the follow-on E17-15 assessment work. The user concern was that there has been "lots of friction due to ambiguity & incomplete workflows." The main conclusion is that the skills describe the intended durable workflow, but several Make targets and recovery paths still act as instruction printers, optional wrappers, or environment-sensitive helpers. Agents can therefore believe a workflow step completed when only guidance was printed, a review was scoped to the wrong worktree, or generated handoff state was refreshed by the wrong Python package version.

**Related docs:**

- [../../agentic/templates/ASSESSMENT.template.md](../../agentic/templates/ASSESSMENT.template.md)
- [../../../.claude/skills/branch-review/SKILL.md](../../../.claude/skills/branch-review/SKILL.md)
- [../../../.claude/skills/planning-review/SKILL.md](../../../.claude/skills/planning-review/SKILL.md)
- [../../../.claude/skills/handoff-lifecycle/SKILL.md](../../../.claude/skills/handoff-lifecycle/SKILL.md)
- [../../../.claude/skills/branch-lifecycle/SKILL.md](../../../.claude/skills/branch-lifecycle/SKILL.md)

## Evidence Base

This report combines current code review with the session transcript, recent git history, and handoff records. Observed process evidence included repeated `plan-analyze`/`plan-review` loops that printed expected outputs without creating the required planning rows; an initial `review-run` against root/main docs instead of the E15-22 worktree; review output that claimed MCP findings existed before readback showed no rows; `CURRENT_TASK.json` refresh attempts split across Python environments; and post-rebase review/close evidence that had to be rebuilt at the final E15-22 HEAD.

The most important handoff evidence was the E15-22 branch-review run history: earlier branch-mode review rows were recorded against stale SHAs or `main` actor context, while the final valid pass was review run `564` at `e6a7c141ee1792c3e26d87c9124658b1f9351734`. Recent git history shows the merged runtime fix commit `e6a7c141 fix(workbench): repair face thumbnails and stale job polling`, preceded by proof-bundle and branch-review cleanup commits.

## Executive Summary

The current skills have strong intent, especially around branch isolation, durable MCP findings, and close-check discipline. The friction came from a mismatch between that intent and the executable surfaces that agents naturally reach for. Several targets named like workflow commands do not perform the workflow; they print what a human or agent should do next. That is workable only when the skill makes the target's non-durable nature unmistakable and requires a readback receipt before progress can continue.

The highest-risk gap is review scope. The branch-review skill now says that `make review-run` is local/lane working-tree review, but the Make target still accepts any `WORKTREE_PATH` without proving it is the active task's `target_worktree_path`. In practice, a shell that drifted back to the root worktree reviewed unrelated main-worktree docs and produced plausible-looking findings. The skill needs an executable scope lock and post-run evidence checks, not just written caution.

The second high-risk gap is generated handoff state. Current docs correctly demote `CURRENT_TASK.json` to an optional generated export, yet lifecycle gates still consult it and the repository uses multiple Python environments to render it. During E15-22, review-ready stayed blocked until the export was regenerated through the same `description-service` environment that the Make target used. That failure mode is hard for agents to infer from the current skills.

The next step should be a spec for skill/workflow hardening under E17-15 or a sibling process-hardening spec. The spec should treat skills, Make targets, and MCP write receipts as one contract: every command must clearly declare whether it prints instructions, performs durable writes, or verifies existing durable state.

## Findings

### F1. Some workflow targets print instructions while their skills imply durable completion

The planning-review skill says it "applies the planning-review checklist, records findings in MCP, refreshes `DASHBOARD.txt`, and closes with a planning-mode review run plus verdict decision" at `.claude/skills/planning-review/SKILL.md:22`. Its core process requires prior review history, finding writes, a verdict decision, a review run, and dashboard refresh at `.claude/skills/planning-review/SKILL.md:55-62`.

The Make targets with the same user-facing names do less. `plan-analyze` only prints an agent-assisted target and an "Expected output" line at `mk/handoff.mk:75-91`; it does not create the `plan-analyze` review marker that `plan-review` later requires. `plan-review` checks for a prior analyze finding through `scripts/check_plan_analyze.py` and then prints expected output at `mk/handoff.mk:93-120`. The checker itself returns `MISSING` unless it finds an existing review finding with a `plan-analyze-` session and matching file path at `scripts/check_plan_analyze.py:53-91`.

Current examples:

- `mk/handoff.mk:75-91` - `plan-analyze` is a guidance printer, even though its output says MCP planning findings and a review-run marker are expected.
- `scripts/check_plan_analyze.py:53-91` - `plan-review` depends on a durable `plan-analyze-` finding that `make plan-analyze` does not itself write.
- `.claude/skills/planning-review/SKILL.md:55-62` - the skill requires durable planning-review writes, but the Make wrapper does not execute them.

**Impact:** Agents can loop through `make plan-analyze && make plan-review`, see authoritative-looking output, and still have no MCP evidence. This turns a workflow gate into a manual memory exercise.

### F2. Branch-review scope is described, but not executable-locked

The branch-review skill now names the distinction clearly: `make review-run` is for lane/local working-tree review, while committed feature-branch diff review must use a slice packet or direct `git diff main...HEAD` scope at `.claude/skills/branch-review/SKILL.md:57`. It also requires honest scope labeling at `.claude/skills/branch-review/SKILL.md:98`.

The executable target still accepts a caller-provided `WORKTREE_PATH` and forwards it to `review_runner run` at `mk/handoff.mk:244-258`. It does not verify that the path matches the handoff task's registered `target_worktree_path`, that the branch matches the task's `target_branch`, or that the changed-file set belongs to the task before invoking the reviewer. The top-level Makefile has enough context to know the worktree and orchestrator roots (`Makefile:23-40`) and resolves task context (`Makefile:50-51`), but `review-run` does not enforce that relationship.

Current examples:

- `.claude/skills/branch-review/SKILL.md:57` - the skill depends on the agent choosing the correct review scope.
- `mk/handoff.mk:244-258` - the target accepts `WORKTREE_PATH` but does not cross-check it against the task's MCP identity before review.
- `Makefile:23-40` - the repo already computes `WORKTREE_ROOT_REAL`, `ORCHESTRATOR_ROOT`, MCP runtime, and current-task path, so an executable scope check is feasible.

**Impact:** A single cwd mistake can create plausible review output for the wrong diff. In E15-22 that happened: an early review pass inspected unrelated root/main docs before the run was discarded and rerun with an explicit linked-worktree path.

### F3. Review output is not always tied to readback-verified MCP receipts

The branch-review skill requires every finding to be recorded, a verdict decision to be written, a branch-mode review run to exist, and the final response to print row IDs at `.claude/skills/branch-review/SKILL.md:61-99`. That is the right contract.

The executable path still leaves too much room for non-durable review output. `make review-run` only passes `--record-findings` when `RECORD_FINDINGS=1` is set at `mk/handoff.mk:255-257`, and the target itself does not perform a post-run `review_findings(list)` / `review_runs(list)` receipt check. The fallback `handoff_review_run.py` records a review run and renders dashboard/current-task state at `scripts/handoff_review_run.py:133-151`, but it is specifically a review-run helper, not a full finding persistence/readback contract.

Current examples:

- `.claude/skills/branch-review/SKILL.md:61-99` - durable findings, verdict, review run, and row-ID receipt are required by policy.
- `mk/handoff.mk:255-257` - finding persistence is optional and flag-driven in the review-run wrapper.
- `scripts/handoff_review_run.py:133-151` - the review-run fallback records a run and renders state, but does not validate finding rows.

**Impact:** Review text can say findings were recorded while MCP state does not contain open rows. In E15-22 the agent had to manually batch-record findings after readback showed no open finding rows.

### F4. `CURRENT_TASK.json` is demoted in docs but still blocks lifecycle gates

The handoff lifecycle skill says generated task views are outputs, not logs, and reserves `render_handoff(kind='current_task')` for on-demand task snapshots at `.claude/skills/handoff-lifecycle/SKILL.md:54`. It also warns not to hand-edit `CURRENT_TASK.json` at `.claude/skills/handoff-lifecycle/SKILL.md:66` and says stale generated views should be regenerated at `.claude/skills/handoff-lifecycle/SKILL.md:83`.

Other surfaces correctly reinforce the demotion: `CLAUDE.md:48` says `CURRENT_TASK.json` is optional and should not be assumed current, and `scripts/test_current_task_demotion_surfaces.py:25-32` tests that wording. At the same time, `review-ready` takes `--orchestrator-root`, `--worktree-root`, and `--task-ref` at `mk/handoff.mk:165-178` but still reports `CURRENT_TASK sync` as a gate condition. The root Makefile hard-wires `MCP_PYENV_VERSION ?= description-service` and the root current-task path at `Makefile:32-40`. The Copilot instructions also tell agents to use `PYENV_VERSION=description-service` for MCP runtime flows at `.github/copilot-instructions.md:13`.

Current examples:

- `CLAUDE.md:48` - `CURRENT_TASK.json` is optional and must not be assumed current.
- `mk/handoff.mk:165-178` - `review-ready` is an executable lifecycle gate that still checks current-task sync.
- `Makefile:32-40` - the Make gate uses the `description-service` Python environment and root current-task path.
- `.github/copilot-instructions.md:13` - agents are told to use `PYENV_VERSION=description-service` for MCP runtime flows, but ad hoc `pyenv exec python` can load a different installed handoff package.

**Impact:** Agents can regenerate a valid-looking export with one Python environment and still fail `review-ready` because the gate compares against another environment's renderer. E15-22 lost substantial time diagnosing this environment/version split before `review-ready` passed.

### F5. Rebase and rewrite events do not have a first-class evidence-refresh workflow

The branch-lifecycle skill requires `make review-ready`, review, `make handoff-close-check`, merge, and `make task-finish` in order at `.claude/skills/branch-lifecycle/SKILL.md:59-64`. It also says close-check failures must be resolved and rerun at `.claude/skills/branch-lifecycle/SKILL.md:84-85`.

The repository has a best-effort post-commit hook to refresh active-task SHA provenance: `scripts/hooks/_post_commit_refresh_sha.py:1-11` states the motivation, and `scripts/hooks/_post_commit_refresh_sha.py:64-75` stamps HEAD through `set_handoff_state`. The post-rewrite hook, however, only drains stdin and runs the main-worktree dirty scanner at `scripts/hooks/git/post-rewrite:1-16`. There is no corresponding rebase/amend workflow step that invalidates stale review runs, re-records tests at the new SHA, or explains the exact order for rebuilding close-check evidence.

Current examples:

- `.claude/skills/branch-lifecycle/SKILL.md:59-64` - final lifecycle order is clear, but not rebase-specific.
- `scripts/hooks/_post_commit_refresh_sha.py:1-11` - post-commit SHA refresh exists because agents forget to do it manually.
- `scripts/hooks/git/post-rewrite:1-16` - post-rebase/amend does not refresh handoff SHA or mark review/test evidence stale.

**Impact:** After E15-22 was rebased, previously plausible review-ready, review, and close-check artifacts were tied to older SHAs and had to be rebuilt. The skill did not provide a short "after rebase, redo these evidence writes" checklist.

### F6. Test-validation instructions do not prevent invalid dependency borrowing strongly enough

The Copilot test instructions say PHP tests should run as `cd <app-dir> && vendor/bin/phpunit <path>` at `.github/copilot-instructions.md:6-10`. The plugin Makefile has a stronger local dependency path: `_php-deps` installs missing Composer dev tools in the app worktree at `apps/prototype-wp-alt-context/Makefile:63-71`, and `php-test` depends on `_php-deps` at `apps/prototype-wp-alt-context/Makefile:78-79`.

During E15-22, a missing linked-worktree vendor led to attempts to borrow PHPUnit from the root checkout, which loaded root checkout classes and produced misleading failures. The repo already warns that PHP runtime autoload parity must match tests at `CLAUDE.md:230`, but the workflow instructions did not force the Make target path first.

Current examples:

- `.github/copilot-instructions.md:6-10` - direct PHP command guidance names `vendor/bin/phpunit`, but not the app Make target that installs local dependencies first.
- `apps/prototype-wp-alt-context/Makefile:63-79` - `_php-deps` and `php-test` already encode the app-local Composer dependency flow.
- `CLAUDE.md:230` - runtime autoload parity is recognized as a regression guard.

**Impact:** Agents can create invalid test evidence by running a sibling checkout's PHPUnit binary. That wastes time and can mask the real issue, as happened before the local Composer install and real PHP proof were completed.

## Recommendations

### 1. Split every workflow surface into `guide`, `verify`, and `write` modes

**Traces:** F1, F3
**Priority:** P0

Make targets should not share names with durable workflow steps unless they perform those steps. For planning review, either rename instruction printers (`plan-analyze-guide`, `plan-review-guide`) or implement durable write modes that create the expected review rows. The spec should require every workflow target to state whether it printed guidance, verified existing durable state, or wrote MCP rows, and it should print row IDs for write mode.

### 2. Add executable scope locks before branch review

**Traces:** F2, F3
**Priority:** P0

`make review-run` should preflight the requested `WORKTREE_PATH` against the task's `target_worktree_path`, `target_branch`, base ref, and changed-file set. If the target is being used for branch-diff fallback review, it should say so and persist that scope in the review run. Wrong-worktree review should fail before model review begins.

### 3. Require post-write readback receipts for all review workflows

**Traces:** F3
**Priority:** P0

After `review_findings(batch_record)`, `record_event`, and `review_runs(record)`, the wrapper or skill should read back the rows it just created and expose the row IDs in one receipt block. A review response should not be allowed to say "recorded" based only on model text or terminal JSON. This can be implemented as a shared receipt helper for branch-review, planning-review, and handoff-review-run.

### 4. Unify current-task rendering under the same runtime used by gates

**Traces:** F4
**Priority:** P1

The handoff lifecycle should specify the gate-compatible rendering command, including Python environment, workspace root, and whether the export is workspace-summary or task-scoped. Better, `review-ready` should render or compare state internally through the same codepath instead of asking agents to repair `CURRENT_TASK.json` manually.

### 5. Add a post-rewrite evidence refresh checklist and helper

**Traces:** F5
**Priority:** P1

Branch-lifecycle should include an "after rebase/amend" checkpoint: refresh task SHA, rerun narrow tests if necessary, re-record current-HEAD test evidence, rerun review-ready, record a fresh branch review run, and rerun close-check. The existing post-commit SHA refresh shows this class of automation is already justified; post-rewrite needs equivalent workflow support.

### 6. Prefer app-local Make test gates over raw dependency binaries

**Traces:** F6
**Priority:** P1

Testing instructions should route PHP validation through `make php-test` or `make check-php` from the app directory when the worktree may lack dependencies. Direct `vendor/bin/phpunit` is still fine for narrow reruns after local vendor is known good, but the skill should explicitly reject sibling-checkout binaries as invalid evidence.

## Code-Verified Critique

### What the assessment gets right

The strongest claims are about mismatched durable workflow semantics. The code shows instruction-printer Make targets for plan analysis and review (`mk/handoff.mk:75-120`), optional finding persistence in branch review (`mk/handoff.mk:255-257`), and explicit policy requiring durable row receipts (`.claude/skills/branch-review/SKILL.md:61-99`, `.claude/skills/planning-review/SKILL.md:55-62`). The `CURRENT_TASK.json` mismatch is also well supported because docs demote it (`CLAUDE.md:48`) while review-ready still gates on current-task sync (`mk/handoff.mk:165-178`).

### Where the assessment overstates the problem

The skills have improved during the same history being assessed. For example, branch-review now has an explicit step 0 for task scope and an `Ambiguous active task` recovery note at `.claude/skills/branch-review/SKILL.md:51-56`. The assessment should therefore not say the skills ignore ambiguity entirely. The narrower claim is that the executable wrappers and recovery paths do not yet enforce or automate the now-documented intent.

Likewise, the repo already contains good PHP dependency plumbing in `apps/prototype-wp-alt-context/Makefile:63-79`. The issue is not that the repository cannot do app-local PHP validation; it is that the skill/test instructions did not route agents there before direct binary invocation failed.

### Recommendations the assessment is missing

R-MISS-1: Add workflow-level tests that simulate wrong-worktree `review-run`, missing plan-analyze marker, stale `CURRENT_TASK.json`, and post-rebase stale evidence. The repository already has targeted process tests such as `scripts/test_current_task_demotion_surfaces.py:25-58`; the spec should extend that style to the failure modes named here.

R-MISS-2: Make subagent review results durable only through a coordinator receipt. The branch-review skill should treat subagent output as advisory until the coordinator records MCP findings or a verdict. This is not a separate finding because the current code has no obvious subagent integration surface to cite, but it should be included in the spec if review-parallel orchestration is in scope.

## Priority Ordering

| Priority | Change | Impact | Effort | Trace |
|----------|--------|--------|--------|-------|
| **P0** | Split workflow targets into guide/verify/write semantics | Eliminates false completion from instruction-printer targets | Medium | F1, F3 |
| **P0** | Scope-lock `make review-run` to task worktree/branch | Prevents wrong-diff reviews and stale branch findings | Medium | F2 |
| **P0** | Add post-write readback receipts | Makes MCP durability visible and auditable | Low-medium | F3 |
| **P1** | Gate-compatible current-task rendering | Removes environment/version ambiguity from review-ready | Medium | F4 |
| **P1** | Post-rebase evidence refresh helper | Prevents stale SHA review/close artifacts | Medium | F5 |
| **P1** | App-local validation routing | Prevents borrowed dependency runners and invalid proof | Low | F6 |

## Deferred or Rejected Directions

- Do not require every assessment to include transcript citations. The template's code-reference gate is still the right baseline; session transcripts and handoff rows should support, not replace, current code citations.
- Do not make `CURRENT_TASK.json` authoritative again. The better direction is for gates to render or compare their own state through one runtime path.
- Do not solve this by adding more prose-only warnings to skills. The recurring failures happened where executable surfaces left room for interpretation.

## Suggested Spec Direction

Write a spec for agent workflow hardening, either as part of E17-15's plugin/skill distribution work or as a sibling spec under `docs/specs/agentic-skill-workflow-contract-spec.md`. The spec should define a small contract for every workflow command: inputs, task-scope resolution, side effects, readback receipts, expected row IDs, stale-state recovery, and failure modes. It should cover branch-review, planning-review, handoff-lifecycle, branch-lifecycle, and test-validation routing.

The spec should stay out of detailed product code. Its acceptance tests should be harness/process tests around `mk/handoff.mk`, skill docs, and lightweight Python wrappers.

## Next Step

- [x] Spec recommended (target path: `docs/specs/agentic-skill-workflow-contract-spec.md`) - flag ADR-gated items for current-task export semantics and MCP package/runtime distribution if they overlap E17-15 plugin distribution.
- [ ] No spec needed; handle as direct implementation or doc sync.

## References

- E15-22 final review run: `review_run id 564`, `branch-review-E15-22-e6a7c141`, verdict `pass`, commit `e6a7c141ee1792c3e26d87c9124658b1f9351734`.
- E15-22 earlier friction examples: review runs `553` and `554` recorded with `branch=main` for a working-tree feature review; review run `559` recorded `pass_with_findings` for uncommitted implementation; later rows `562`, `563`, and `564` show re-recording at newer SHAs.
- Recent git history anchor: `e6a7c141 fix(workbench): repair face thumbnails and stale job polling`.
- Local session transcript evidence: repeated `make plan-analyze` / `make plan-review` loops, wrong-root `make review-run`, manual finding persistence, `CURRENT_TASK.json` renderer mismatch, and borrowed PHPUnit attempts during E15-22.
