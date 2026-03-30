# Tech Debt: ACE Metrics Signal Quality

## Background

`ace_metrics.py` aggregates several metrics into `get_metrics_summary`. A review of the implementation
identified four categories where the current metrics either measure the wrong thing, are scoped
incorrectly, or are operational hygiene gauges that have been grouped alongside developer-memory
metrics without distinction.

The issues below are non-blocking; `get_metrics_summary` continues to work. But they should be
addressed before any dashboard or retrospective tooling treats these signals as authoritative.

---

## Issue 1: `ctx7_adoption` uses regex over prose instead of turn-level telemetry

**Location:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_metrics.py`, line 917

**Problem:**
`_ctx7_adoption` queries the `decisions.rationale` column and applies `_CTX7_LIBRARY_ID_RE` to
detect ctx7 usage. This measures whether an agent happened to write a library ID into a decision
rationale string, not whether ctx7 was actually invoked during a turn.

- False negatives: a turn that fetched ctx7 docs but wrote a generic rationale produces zero signal.
- False positives: a rationale that quotes a library ID in a "decided not to use" comment would
  register as ctx7 adoption.
- The `reuse_ratio` derived value compounds the noise.

The task plan for ADPH-3 (`docs/tasks/12.0/accurate-token-and-context-metrics-task-plan.md`)
acknowledges this in both the Problem Statement and the Constraints:

> "ctx7 attribution is limited to coarse decision-text heuristics rather than turn-level telemetry."
> "ctx7 usage cannot be inferred from package internals alone; any turn-level ctx7 attribution must
> come from an explicit caller/runtime reporting protocol until direct instrumentation exists."

**Correct fix (from ADPH-3):**
Record an explicit attribution flag in the turn-metrics ledger at execution time. Until that ledger
exists, the metric should be labeled `estimated` or `heuristic_only` rather than presented alongside
exact counts.

**Interim mitigation:**
Attach a `measurement_source: "decision_prose_heuristic"` key to the `_ctx7_adoption` result dict
so callers know the value is inferred, not observed.

---

## Issue 2: `contract_co_change_signal` is a repo-governance metric, not a task-archaeology metric

**Location:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_metrics.py`, line 961

**Problem:**
`_contract_co_change_signal` runs `git log -n{commit_limit}` against `HEAD` and checks whether
recent commits that touched boundary prefixes also touched contract files. The `commit_limit`
defaults to 20.

This answers: "In the last 20 commits across the whole repo, did boundary changes co-travel with
contract updates?" It does not answer: "During this task, did the agent correctly maintain contract
parity with boundary changes?"

For task-level retrospectives the useful question is scoped to the task's commit range or the
task's handoff narrative of decisions, not the latest 20 repo commits. If another task landed
boundary-only changes in those 20 commits, the signal is polluted. Conversely, if the current
task's boundary changes fall outside the 20-commit window, they are invisible entirely.

**Correct fix:**
Either scope the git scan to the commits attributed to `task_ref` (using decision timestamps
cross-referenced against commit timestamps), or move this metric to a repo-level reports surface
and remove it from `get_metrics_summary` per-task output.

**Short-term mitigation:**
Document the `commit_limit` window explicitly in the metric output and add a
`scope: "recent_repo_commits"` key so consumers are not confused with per-task coverage.

---

## Issue 3: Operational hygiene metrics are mixed with developer-memory metrics

**Locations:**

| Metric | Location | Category |
|---|---|---|
| Raw FTS counts (`handoff_record_counts`, `artifact_chunks_fts_count`) | line 512 | Operational hygiene |
| `hot_state_size_bytes` | line 684 (inside `_handoff_memory`) | Operational hygiene |
| `stale_artifact_rate` | line 843 | Operational hygiene |
| `archive_rate` / `mean_interval_hours` | line 875 | Operational hygiene |

**Problem:**
These four metrics measure the health of the storage layer and tooling cadence, not whether an
agent retained or used relevant prior knowledge. That distinction matters because:

- Retrospective tooling that tries to correlate "did the agent have good context?" with "did the
  task converge quickly?" should not be confused by noise from "how fast does the team archive
  tasks" or "how large is the hot-state JSON blob".
- `hot_state_size_bytes` specifically conflates "agent had lots of context" with "agent had useful
  context" - a bloated state can indicate poor pruning, not strong memory.
- `archive_rate.mean_interval_hours` is only meaningful if archiving cadence is a process
  requirement, which it currently is not formally.

**Correct fix:**
Group metrics into explicit categories in the `get_metrics_summary` response envelope:

```python
{
  "developer_memory": { ... },
  "operational_hygiene": {
    "archive_rate": ...,
    "stale_artifact_rate": ...,
    "hot_state_size_bytes": ...,
    "fts_record_counts": ...,
  },
}
```

Consumers that only care about developer-memory signals can ignore `operational_hygiene` without
needing to know which individual keys to skip.

---

## Issue 4: `planning_drift` and ACE documentation counters measure adoption, not reality

**Locations:**

| Metric | Location |
|---|---|
| `planning_drift` | line 793 |
| ACE documentation counters (`total_helpful`, `total_harmful`, `rule_count`) | line 1043 |

**Problem:**

`planning_drift` computes `1 - (terminal_cursors / total_cursors)`. If plan cursors are not
consistently created for every slice (which they are not enforced to be), then a low `drift` value
can mean either "all slices completed cleanly" or "no plan cursors were ever created". Both
scenarios produce identical output. The metric only distinguishes real drift from zero-adoption once
cursor usage is a hard process invariant, not an optional practice.

The ACE documentation counters (`helpful` / `harmful` totals, `rule_count`) are derived from
`parse_strategy_bullets`, which scans instruction files for `[sr-NNN]` and `[rg-NNN]` annotations.
This counts how many rules are documented, not whether they were detected in recent findings, applied
to counter updates, or produced any behavioral change. Two repos with identical rule documentation
but completely different ACE process health would report the same counter values.

**Correct fix:**
- For `planning_drift`: add a `cursor_coverage_rate` field (cursors created per decision recorded)
  as a prerequisite signal; suppress or flag `drift` when `cursor_coverage_rate` is below a minimum
  threshold (e.g., 0.5), so low cursor adoption does not silently produce misleading drift scores.
- For ACE counters: pair documentation counts with the ACE process health states already planned in
  ADPH-3 (`defined` / `detecting` / `applied`). A `rule_count` value is only interpretable
  alongside a `process_health` field that shows whether those rules are actively detecting anything.

---

## Priority

These are non-blocking but should be addressed before ADPH-3 ships a production-facing metrics
dashboard. Issue 1 and Issue 4 (ctx7 and planning_drift) carry the highest risk of producing
misleading retrospectives. Issues 2 and 3 are primarily cosmetic/organizational but create
analysis debt if left unaddressed.

Suggested order: Issue 3 (grouping, low effort) > Issue 2 (document scope, low effort) >
Issue 4 (cursor coverage gate, medium effort) > Issue 1 (blocked on ADPH-3 turn-metrics ledger).
