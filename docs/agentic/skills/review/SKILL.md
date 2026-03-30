# Review

Use this skill when the user asks to review code, a branch, a PR diff, a task plan, an epic, a roadmap, or an ADR.

## Trigger

Use this skill when the request matches any of:

- "review" + (implementation | code | changes | branch | PR | diff)
- "audit" + (branch | code)
- "propose improvements" or "flag gaps/bugs"
- "review" + (task plan | epic | roadmap | ADR | planning document)
- "flag issues/gaps/obsolete assumptions" on a `docs/` file
- "audit" + (plan | epic | roadmap)

## Goal

Produce a structured, MCP-recorded set of review findings with a verdict. Route automatically to the correct review guide based on the review target.

## Canonical Policy

- Use [../../instructions.md](../../instructions.md) for startup, handoff, and evidence-logging policy.
- Use [../../rules/development-workflow.md](../../rules/development-workflow.md) for slice and review-readiness rules.
- Use this skill only for review-mode detection, phase orchestration, and MCP recording discipline. The actual review checklist lives in the linked guides.

## Mode Detection

Determine review mode before starting. Do not ask the user — infer from context.

### Branch Review (`review_mode="branch"`)

**Detected when**: request mentions code, branch, PR, diff, implementation, or the target is source files under `apps/`, `packages/`, `scripts/`, or `mk/`.

**Guide**: load and follow [../../rules/branch-review-guide.md](../../rules/branch-review-guide.md).

**Scope**:

```bash
git diff --name-only <base>...HEAD
git diff --stat <base>...HEAD
```

If the user specifies a file subset, restrict to those files. Otherwise review the full branch diff.

**Finding ID prefix**: `H-<n>`, `M-<n>`, `L-<n>` (severity-based).

**Subject kind**: `branch`.

### Planning Review (`review_mode="planning"`)

**Detected when**: request mentions task plan, epic, roadmap, ADR, planning document, or the target is a file under `docs/tasks/`, `docs/epics/`, `docs/roadmaps/`, or `docs/agentic/contracts/`.

**Guide**: load and follow [../../rules/planning-review-guide.md](../../rules/planning-review-guide.md).

**Scope**: the specific document(s) named by the user, plus any prerequisite specs/contracts they depend on.

**Finding ID prefix**: `<TaskRef>-PLAN-<n>` (e.g., `E12-3-PLAN-01`).

**Subject kind**: `task_plan`, `epic`, `roadmap`, or `adr` as appropriate.

### Ambiguous targets

If the diff contains both code and planning docs, run **two separate review passes** — one branch review for code files, one planning review for doc files. Record findings under the appropriate `review_mode` for each pass.

## Phase 1 — Load Context

1. Confirm MCP is available. Call `get_handoff_state` to identify the active task.
2. Check for prior review runs on the same target: `list_review_runs(subject_path=<target>)`.
3. Check for open findings from prior reviews: `list_review_findings(status="open")`.
4. Load the appropriate review guide (branch or planning) and its checklist.

For branch reviews, also:

```bash
git log --oneline <base>...HEAD
git diff --stat <base>...HEAD
```

For planning reviews, also:
- Read the planning document under review.
- Read prerequisite contracts and specs it depends on.
- Read current implementation anchors where relevant.

## Phase 2 — Execute Review Checklist

Walk the full checklist from the loaded review guide. Do not skip sections.

**Branch review priority order** (from branch-review-guide):
1. Correctness and type safety
2. Architecture violations and regression guards
3. Dead code and complexity
4. Test coverage gaps
5. Contract/schema parity

**Planning review priority order** (from planning-review-guide):
1. Obsolete assumptions
2. Architecture/ownership mistakes
3. Greenfield-policy violations
4. Contradictory scope or checklist logic
5. Contract gaps
6. Unnecessary complexity

For branch reviews, apply the Bug-Finding Heuristics from the guide:
- Variable identity after normalization
- Cross-method contract bugs
- Envelope-wrapper sanity check
- Boundary value sweep
- Retry lifecycle traps
- IDE stale-file guard (re-verify with terminal after git ops)

## Phase 3 — Record Findings

**Hard rule**: do not present a finding in chat unless it is already recorded in MCP with a stable `finding_id`.

For each finding, determine severity:

| Branch Review | Planning Review |
|---|---|
| **HIGH**: incorrect behavior, data corruption, type unsafety | **HIGH**: plan cannot be implemented correctly as written |
| **MEDIUM**: architecture violations, maintenance burden | **MEDIUM**: implementable but likely regressions/churn |
| **LOW**: style, minor cleanup | **LOW**: wording drift, minor sequencing gaps |

### Recording

**Single finding** (fewer than 3):

```
record_review_finding(
  session="<session-id>",
  finding_id="<finding-id>",
  severity="high|medium|low",
  file_path="<monorepo-relative-path>",
  description="<one-paragraph with evidence>",
  task_ref="<task-ref>",
  review_mode="branch|planning",
  details={ "line_start": N, "line_end": N, "fix": "<suggested fix>" }
)
```

**Batch findings** (3 or more in one pass):

```
batch_record_review_findings(
  session="<session-id>",
  task_ref="<task-ref>",
  findings=[
    { finding_id, severity, file_path, description, review_mode, details },
    ...
  ]
)
```

The `details` object must be nested — never pass `line_start`, `line_end`, or `fix` as top-level parameters.

## Phase 4 — Record Verdict

1. Confirm finding counts: `list_review_findings(task_ref=<task-ref>, status="open")`.

2. Determine verdict:
   - `pass` — zero findings.
   - `pass_with_findings` — no HIGH findings; MEDIUM/LOW deferred with justification.
   - `conditional_pass` — HIGH findings exist but mitigations identified.
   - `fail` — HIGH findings that must be resolved before merge/implementation.

3. Record the verdict decision:

```
record_decision(
  session="<session-id>",
  decision="review_verdict_<review_mode>_<subject_slug>",
  rationale="<verdict>: <severity-count-summary>. <key-findings-summary>"
)
```

4. Record the review run:

```
record_review_run(
  review_run_id="<task-ref>-review-<n>",
  session="<session-id>",
  subject_path="<monorepo-relative-path>",
  subject_kind="<branch|task_plan|epic|roadmap|adr>",
  review_mode="<branch|planning>",
  verdict="<pass|pass_with_findings|conditional_pass|fail>",
  verdict_decision="<decision-slug-from-step-3>"
)
```

5. Regenerate task context: `generate_current_task_md(task_ref=<active-task-ref>)`.

## Phase 5 — Respond

Present findings grouped by severity (HIGH first), citing `finding_id` for each. Do not repeat the full description if already recorded — reference the ID.

For branch reviews with HIGH findings, suggest a fix order (Phase 1: must-fix, Phase 2: should-fix, Phase 3: optional).

End the response with:
- Verdict summary (pass/fail + severity counts)
- `Handoff updated: yes`

## Multi-Lens Escalation

If the review target crosses audit triggers (architecture transitions, multi-service state, persistence changes, broad UI surfaces), escalate to a multi-lens audit:

1. Run lenses sequentially: architecture/reliability, QA/state-matrix, contract/compliance.
2. Use lens-specific finding-ID prefixes: `ARCH-<n>`, `QA-<n>`, `CONTRACT-<n>`.
3. Set `review_mode="release_audit"` for all findings in this mode.
4. Record findings after each lens before proceeding to the next.

## Recovery

- If MCP is unavailable, stop the review and record a blocker. Do not produce findings outside MCP.
- If the diff is empty or the planning document is missing, report the issue and exit without findings.
- If findings from a prior review run are still open, acknowledge them and avoid duplicating. Reopen with `update_review_finding(status="open", reopen_reason=...)` if a prior finding recurs.
- If a finding has been reopened 2 or more times, include `verification_evidence` proving the issue persists.

## Convergence Criteria

- Every finding is recorded in MCP before being mentioned in chat.
- A `record_review_run` entry exists for this review pass.
- A `record_decision` entry exists with the verdict.
- `CURRENT_TASK.md` has been regenerated.
- Response includes `Handoff updated: yes`.
