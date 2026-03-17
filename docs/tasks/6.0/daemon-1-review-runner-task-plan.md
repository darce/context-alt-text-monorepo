# Daemon 1: Self-Review Runner

## Problem Statement

Autonomous worker execution needs a machine-invocable review step that can evaluate lane-local code changes against the branch review rules before the worker records a final handoff. Today the repo has review guidance and MCP finding storage, but no standalone review runner that can execute Codex with a structured schema and feed those findings back into the workflow.

## Workflow Principles

- **Structured findings, not prose.** The runner returns a validated JSON object containing findings and summary data that daemons can consume directly.
- **Recorded before acted on.** When the runner is used by daemon or Makefile automation, its findings are recorded in MCP before they drive fix cycles or completion decisions. A local dry-run mode may skip MCP writes for debugging only.
- **Keep review separate from handoff.** Review output stays in `scripts/mcp/review_runner.py`; `scripts/mcp/lane_result.py` remains scoped to final worker handoff payloads.
- **Stack-aware prompts.** The runner auto-selects the relevant stack review guides from the lane diff so callers do not have to specify Python vs TypeScript vs PHP manually.
- **Standalone and importable.** The same module should work as a CLI entrypoint and as a library dependency for the worker daemon.

## Terminology

- **Review runner**: `scripts/mcp/review_runner.py`, the Codex wrapper for branch review.
- **Review result**: Structured JSON containing `findings`, `summary`, and optional metadata such as whether findings were recorded.
- **Review convergence**: Zero HIGH, zero MEDIUM, at most one LOW finding.
- **Recordable run**: A runner invocation that includes the task/session context needed to write findings into MCP.

## Current State Analysis

- `docs/agentic/rules/branch-review-guide.md` and the stack-specific review guides already define the checklist content the runner should embed.
- `make lane-run` already proves the `codex exec --output-schema` pattern, but it is an implementation-plus-handoff wrapper, not a review primitive.
- `scripts/mcp/lane_result.py` already owns the final worker handoff schema and should not absorb review findings.
- MCP already supports `review-record`, `review-update`, `review-list`, and `review-summary`, so the missing piece is a review producer rather than a new storage layer.
- No script currently wraps Codex review execution against a lane diff or exports a reusable `findings_converged()` helper.

## Proposed Solution

Add a new script, `scripts/mcp/review_runner.py`, with two primary responsibilities:

1. Build a review prompt from:
   - `branch-review-guide.md`
   - any relevant stack guides
   - lane-local changed files and diff stat
2. Execute `codex exec` with a dedicated review schema, validate the result, and optionally record the findings in MCP.

The runner should support:

- `schema`: print the review output schema
- `run`: execute the review and print structured JSON
- `run --record-findings`: write findings into MCP using the supplied `--task-ref` and `--session`
- `run --dry-run`: print the assembled prompt and skip Codex/MCP side effects

When invoked by the future worker daemon, `--record-findings` is mandatory. The daemon should not inspect or act on review results that have not been recorded.

## Patterns to Follow

### Review Output Schema

```python
REVIEW_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["findings", "summary"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["severity", "category", "file_path", "description"],
                "properties": {
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "category": {
                        "type": "string",
                        "enum": ["ANTIPATTERN", "DEAD_CODE", "COMPLEXITY", "GAP"],
                    },
                    "file_path": {"type": "string"},
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                    "description": {"type": "string", "minLength": 1},
                    "fix": {"type": "string"},
                },
            },
        },
        "summary": {"type": "string", "minLength": 1},
    },
}
```

### Recording Contract

```python
def run_review(..., record_findings: bool = False) -> dict[str, Any]:
    result = _codex_exec(...)
    validated = _validate_review_result(result)
    if record_findings:
        _record_findings(validated["findings"], task_ref=task_ref, session=session)
    return validated
```

### Convergence Check

```python
def findings_converged(findings: list[dict[str, Any]]) -> bool:
    high = sum(1 for f in findings if f.get("severity") == "high")
    medium = sum(1 for f in findings if f.get("severity") == "medium")
    low = sum(1 for f in findings if f.get("severity") == "low")
    return high == 0 and medium == 0 and low <= 1
```

## Functions to Change

| File                                | Change                                                                                             |
| ----------------------------------- | -------------------------------------------------------------------------------------------------- |
| `scripts/mcp/review_runner.py`      | New CLI/module for prompt building, Codex execution, result validation, and optional MCP recording |
| `mk/handoff.mk`                     | Add `review-run` target as a human/operator wrapper around `review_runner.py run`                  |
| `packages/agent-handoff-mcp/tests/` | Add tests for schema validation, prompt rendering, stack detection, and MCP recording behavior     |

## Related Files

| File                                             | Note                                                        |
| ------------------------------------------------ | ----------------------------------------------------------- |
| `docs/agentic/rules/branch-review-guide.md`      | Canonical review checklist                                  |
| `docs/agentic/rules/branch-review-python.md`     | Python lane review rules                                    |
| `docs/agentic/rules/branch-review-typescript.md` | TypeScript/React lane review rules                          |
| `docs/agentic/rules/branch-review-php.md`        | PHP lane review rules                                       |
| `scripts/mcp/lane_result.py`                     | Final handoff adapter only; not extended with review schema |

---

# Consolidated Checklist

## Phase 0: Scaffolding

- [x] Create `scripts/mcp/review_runner.py` with `schema` and `run` subcommands
- [x] Define `REVIEW_OUTPUT_SCHEMA`
- [x] Export `findings_converged()` as a module-level helper
- [x] Add `review-run` Makefile target and help text
- [x] Verify: `python3 scripts/mcp/review_runner.py schema` prints valid JSON

## Phase 1: Prompt Construction

- [x] Implement changed-file discovery from the lane worktree
- [x] Implement stack-guide auto-detection from file extensions
- [x] Implement prompt rendering with branch-review guide, stack guides, and diff stat
- [x] Test: mixed-language diffs select the expected guide set
- [x] Test: prompt rendering omits stack sections when no matching files exist

## Phase 2: Codex Execution and Validation

- [x] Implement `_codex_exec()` with temp schema/result files
- [x] Validate the returned JSON against the review schema
- [x] Support `--dry-run` for prompt inspection without Codex execution
- [x] Support `--worktree-path`, `--lane-id`, `--task-ref`, and `--session`
- [x] Test: invalid result payloads fail with a clear error

## Phase 3: MCP Recording

- [x] Implement `--record-findings`
- [x] Record each finding through MCP before returning control to daemon callers
- [x] Include enough metadata in the result for downstream convergence checks and audit logs
- [x] Test: `--record-findings` creates MCP findings with stable IDs and line references
- [x] Test: `--dry-run` does not write MCP state

## Success Criteria

- [x] `python3 scripts/mcp/review_runner.py schema` emits a schema consumable by `codex exec --output-schema`
- [x] `python3 scripts/mcp/review_runner.py run --worktree-path <lane> --lane-id <lane>` returns validated structured findings
- [x] Daemon callers can enable MCP recording and rely on recorded findings before starting a fix cycle
- [x] Review schema and logic remain separate from the final worker handoff schema in `lane_result.py`
