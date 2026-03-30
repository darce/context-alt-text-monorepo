# Investigate

Use this skill for systematic root-cause debugging when a test failure, runtime error, or unexpected behavior needs diagnosis before a fix is attempted.

## Trigger

Use this skill when the request matches any of:

- "investigate", "debug", "diagnose", "root cause"
- "why is this failing", "what's causing", "trace this"
- A test failure or error message is presented and the cause is not immediately obvious
- A finding from a review has been reopened 2+ times (indicates symptom-level fixes)

Do **not** use this skill for:
- Known bugs with obvious fixes (just fix them directly).
- Review or audit work (use the `review` skill instead).

## Goal

Identify and verify the root cause of a defect before any fix is applied. Record the investigation as MCP findings and decisions so the diagnosis survives handoff.

## Canonical Policy

- Use [../../instructions.md](../../instructions.md) for startup, handoff, and evidence-logging policy.
- Use [../../rules/development-workflow.md](../../rules/development-workflow.md) for slice checklist and regression sweep conventions.
- Use [../../rules/branch-review-guide.md](../../rules/branch-review-guide.md) for Bug-Finding Heuristics (variable identity, cross-method contracts, boundary values, retry lifecycle, stale-file guard).
- Use this skill for investigation phasing and discipline only; broader process policy lives in the linked canonical docs.

## Iron Law

**No fixes without root cause.** Do not apply a fix, workaround, or suppression until the root cause is identified and recorded. Symptom-level patches create harder bugs later.

## Phase 1 — Collect Symptoms

Gather all available evidence before forming hypotheses.

1. **Error output**: exact error message, stack trace, assertion failure, or unexpected behavior description.
2. **Reproduction**: determine the minimal steps to reproduce. If the user provided steps, verify them. If not, construct them.
3. **Recency**: check recent changes that may have introduced the issue:

```bash
git log --oneline -20
git diff --stat HEAD~5..HEAD
```

4. **Prior findings**: query MCP for related findings:

```
search_handoff(queries=["<error-keyword>", "<module-name>"])
list_review_findings(status="open")
```

5. **Scope boundary**: identify the module, layer, and contract surface involved. Read the relevant context map (`docs/agentic/maps/`) to understand the component's boundaries.

Record the symptom summary as an MCP finding with severity `medium` and status `open`:

```
record_review_finding(
  session="<session-id>",
  finding_id="INVEST-<n>",
  severity="medium",
  file_path="<file-where-symptom-manifests>",
  description="Investigation opened: <symptom-summary>. Reproduction: <steps>.",
  review_mode="branch",
  details={ "line_start": N, "line_end": N }
)
```

## Phase 2 — Pattern Analysis

Match the symptom against known defect patterns. Check each that applies:

| Pattern | What to look for |
|---|---|
| **Race condition** | Concurrent access, missing locks, async operations without guards |
| **Stale state** | Cached values surviving across calls, missing invalidation |
| **Contract mismatch** | Caller assumptions diverging from callee guarantees (types, nullability, ordering) |
| **Boundary value** | Empty collections, zero/negative inputs, max-length strings, None/null propagation |
| **Integration seam** | Failures at module boundaries, serialization/deserialization mismatches |
| **Config drift** | Environment-dependent behavior, missing/stale config keys |
| **Regression** | A previously-fixed behavior has returned (check git log for prior fixes in the same area) |

Apply the Bug-Finding Heuristics from `branch-review-guide.md`:
- Variable identity after normalization
- Cross-method contract bugs
- Envelope-wrapper sanity check
- Retry lifecycle traps

## Phase 3 — Hypothesize and Test

Form a specific, testable hypothesis: "The root cause is X because Y, which would explain symptom Z."

### Testing a hypothesis

1. Add targeted inspection (print/log, breakpoint, assertion) at the suspected root cause location.
2. Run the reproduction scenario.
3. Evaluate: does the evidence confirm or refute the hypothesis?

### Three-strike rule

If three hypotheses fail in sequence:

1. Record what was tried and ruled out as an MCP decision:

```
record_decision(
  session="<session-id>",
  decision="investigate_escalation_<slug>",
  rationale="Three hypotheses tested and refuted: (1) ... (2) ... (3) ... Escalating for human review."
)
```

2. Report a blocker:

```
report_blocker(
  operation="add",
  description="Investigation stalled after 3 failed hypotheses. Ruled out: <list>. Remaining unknowns: <list>."
)
```

3. Stop and present the findings to the user. Do not guess further.

### Red flags — stop and reassess if you notice:

- Proposing a "quick fix for now" without tracing the data flow.
- A fix that doesn't explain how the symptom was produced.
- Cascading failures suggesting the wrong architectural layer is being investigated.
- Touching more than 5 files for what should be a localized fix.

## Phase 4 — Fix

Only enter this phase after the root cause is confirmed.

1. **Minimal diff**: fix the root cause, not the symptom. Fewest files, fewest lines.
2. **Regression test**: write a test that fails without the fix and passes with the fix.
3. **Full suite**: run the relevant test suite to confirm no regressions.

```bash
# For Python packages:
make test-handoff    # or test-orchestrator, as appropriate
# For PHP:
composer test
# For TypeScript:
npm test
```

4. If the fix touches a contract surface, verify contract parity per [../../contracts/](../../contracts/).

## Phase 5 — Record and Close

1. **Update the investigation finding** with the root cause and fix:

```
update_review_finding(
  finding_id="INVEST-<n>",
  status="fixed",
  resolution_notes="Root cause: <explanation>. Fix: <what-changed>. Regression test: <file:line>.",
  verified_commit_sha="<sha>",
  verification_evidence="<test-output-or-reproduction-proof>"
)
```

2. **Record the investigation decision** using the slice-complete template structure:

```
record_decision(
  session="<session-id>",
  decision="investigate_complete_<work-ref>_<slug>",
  rationale="## Changes\n<files + functions changed>\n\n## Verification\n<test results>\n\n## Schema / Contract Changes\n- none.\n\n## Open Threads\n<related items, follow-on work>"
)
```

3. **Regenerate task context**: `generate_current_task_md(task_ref=<active-task-ref>)`.

## Recovery

- If MCP is unavailable, record the investigation in a local scratch note and transfer to MCP when access returns. Do not skip recording.
- If the symptom cannot be reproduced, record that fact and close the finding as `wontfix` with `resolution_notes` explaining the reproduction attempts.
- If the fix requires changes outside the current lane or owned paths, record a cross-lane finding and escalate — do not cross ownership boundaries.
- If a prior investigation finding exists for the same symptom, reopen it with `update_review_finding(status="open", reopen_reason=...)` rather than creating a duplicate.

## Convergence Criteria

- Root cause is identified and recorded in MCP before any fix is applied.
- The fix is minimal and accompanied by a regression test.
- An `update_review_finding` call closes the investigation finding with evidence.
- A `record_decision` entry exists with the investigation outcome using slice-complete template structure.
- `CURRENT_TASK.md` has been regenerated.
- Response includes `Handoff updated: yes`.
