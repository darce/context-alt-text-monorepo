# Guard: Finding-Status Trailer Heuristic for `guard-task-plan-findings.py`

> **Metadata**
>
> - **Date**: 2026-04-16
> - **Author**: Claude Opus 4 (1M context)
> - **Project**: `agent-handoff-mcp`
> - **Status**: Tech-debt note (no implementation slice yet)
> - **Related rule**: [`CLAUDE.md` § Review Findings Placement](../../../../CLAUDE.md) · [`branch-review-guide.md` § Review Findings Placement](../../../../docs/agentic/rules/branch-review-guide.md#review-findings-placement-mandatory)
> - **Related hook**: `scripts/hooks/guard-task-plan-findings.py`
> - **Related lint target**: `make lint-task-plans` (drives `--scan-repo` mode)

## Problem

The committed rule is clear: *finding status lives in the handoff DB, not in task-plan markdown*. The hook currently blocks:

1. Three or more consecutive bullet lines that each open with a finding-style identifier (`- AOMCP-3-BR-04: ...`).
2. Any finding-style bullet that appears under a `Findings` section heading.

Both heuristics target the *paste a finding list* failure mode. Neither catches the subtler failure mode that prompted this entry: **single-bullet status-tracking trailers** inside otherwise-legitimate checklists. Examples that currently slip through:

```markdown
- [x] `make check-harness-sync` exits 0 with no drift (`E17-6-BR-09` closed)
- [x] `check_plan_analyze.py` filters by target document (`E17-6-BR-08`: fixed in MCP)
- [ ] Review-finding cleanup — resolve open BR-07, BR-08, BR-09
```

Each row embeds finding status in a markdown file, duplicating the DB, and drifts the instant a finding is reopened or re-classified. The rule text was strengthened to forbid these patterns, but the hook does not yet enforce them.

## Proposed Heuristic

Add a third, single-line detector that complements the existing two:

1. A **finding-status-trailer** regex fires on any line matching the following structure:
   - Task-prefixed or severity-shorthand finding ID (reuse `_FINDING_BULLET_RE`'s id pattern).
   - Followed, within a short window (≤ ~40 chars), by one of: `closed`, `fixed`, `open`, `deferred`, `wontfix`, `resolved`, `landed`, `addressed`, or a bracketed status word.

2. The detector runs on every line (bullet or narrative), not just bullet opens, so `(E17-6-BR-09 closed)` trips it whether it appears as a checklist trailer, a parenthetical in a paragraph, or a row in a table.

3. The detector shares the existing path filter (`/docs/tasks/`, `/docs/epics/`, `*task-plan*.md`, `*-plan.md`) — narrative docs outside task plans remain exempt.

Draft regex (subject to calibration against the existing false-positive corpus):

```python
_FINDING_STATUS_TRAILER_RE = re.compile(
    r"""
    (?P<id>
        (?:[A-Z]{1,5}\d*-\d+(?:-[A-Z]+)?-\d+)   # AOMCP-3-BR-04, E17-6-BR-09
        |
        (?:[HML]-\d+)                            # H-1, M-2, L-3
    )
    \s*
    (?:[:,\-\u2014]|\bis\b|\bwas\b)?\s*
    \(?(?P<status>closed|fixed|open|deferred|wontfix|resolved|landed|addressed)\b\)?
    """,
    re.IGNORECASE | re.VERBOSE,
)
```

## Calibration Plan

Before wiring into `make check-all`:

1. Run the regex against every tracked `.md` file the current hook would scan (same `--scan-repo` discovery). Classify every hit as true-positive (should block) or false-positive (should pass). Budget: review the full hit list; ship only if false-positive rate is **0** on committed docs.
2. Expected clean docs at the time of this write-up:
   - No surviving finding-status trailers in the active task plans under `docs/tasks/**`.
   - Historical snapshots under `docs/archive/**` are out of scope (not scanned by the existing path filter).
3. Known acceptable patterns the heuristic must NOT flag:
   - `"Incidental Fixes (flagged by E17-6-BR-06)"` — reference without a status word.
   - `"see AOMCP-3-BR-04 in handoff"` — reference, no status word.
   - `"handoff_close_check blocks merge until findings are closed"` — status word present but no adjacent finding ID.
4. Add a new test file under `scripts/hooks/test_guard_task_plan_findings.py` (or the existing one) with both positive and negative fixtures for the new heuristic.

## Mitigation While This Is Deferred

- The rule text in `CLAUDE.md` and `branch-review-guide.md` now explicitly forbids status-tracking trailers.
- `TASK_PLAN.template.md` carries a short inline reminder above the Consolidated Checklist.
- Agents reviewing task plans should read the rule before adding any checklist item that references a finding ID.

## Out of Scope

- Changing the existing `_detect_finding_runs` or `_detect_findings_under_heading` semantics.
- Scanning committed historical archives (`docs/archive/**`).
- Extending the guard to non-task-plan markdown (ADRs, epics already covered; narrative docs intentionally exempt).

## Ownership

Owner TBD — plan in `agent-handoff-mcp`'s tech-debt queue until an epic or task absorbs it. Track via a dedicated task_ref when pulled in (e.g. `AHMCP-<n>-task-plan-status-heuristic`).
