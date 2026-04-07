# Token-Efficient Usage

`agent-handoff-mcp` now emits compact v2 envelopes by default, but callers still control a large share of total token cost. Use the smallest read surface that answers the current question.

## Principles

- Treat `data` as the canonical payload block. Do not depend on mirrored top-level fields.
- Use full-detail reads for session-start hot state and review work.
- Use scoped reads for polling, health checks, and targeted lookups.
- Prefer additive shaping parameters over post-processing large payloads client-side.

## Recommended Read Patterns

### Routine task checks

When the caller only needs to know which task is active, use the identity-only view:

```python
get_handoff_state(sections="identity")
```

This keeps the response to the active-task identity plus limits, instead of fetching decisions, findings, blockers, and tests.

### Session-start hot state

For a fresh task load, keep the default full-detail `load_session()` or `get_handoff_state()` behavior unless the caller explicitly needs a lighter view:

```python
load_session(task_ref="AHMCP-7")
```

If the caller can tolerate truncated rationale and finding text, opt in explicitly:

```python
load_session(task_ref="AHMCP-7", detail="summary")
```

`detail="summary"` is an opt-in size reduction, not the package default.

### Focused handoff reads

Ask for only the sections you need:

```python
get_handoff_state(
    task_ref="AHMCP-7",
    sections="tests_recent,decisions_recent",
    detail="summary",
    top_n_tests=3,
    top_n_decisions=2,
)
```

Useful section patterns:

- `identity`
- `tests_recent`
- `decisions_recent`
- `findings_open`
- `blockers_open`
- `actions_pending`

### Findings and search queries

Use `detail="summary"` and `limit=` for inspection flows, and project only the fields you need where supported:

```python
review_findings(
    review={
        "operation": "list",
        "task_ref": "AHMCP-7",
        "status": "open",
        "detail": "summary",
        "limit": 20,
    }
)

search_handoff(
    queries="projection",
    record_types="decision,finding",
    detail="summary",
    limit=10,
    fields="record_type,task_ref,title,snippet",
)
```

### Artifacts

When browsing indexed artifacts, request summary mode or a field projection instead of full chunk content:

```python
artifacts(
    artifact={
        "operation": "search",
        "task_ref": "AHMCP-7",
        "detail": "summary",
        "fields": "source_id,source_label,title,snippet",
    }
)
```

## Anti-Patterns

- Calling `get_handoff_state()` with no shaping parameters in a tight polling loop.
- Using `load_session(detail="full")` for a single-field liveness check.
- Reading top-level mirrored fields instead of `data`, which prevents future envelope simplification.
- Fetching hundreds of findings/actions/decisions and trimming them client-side when `top_n_*`, `limit`, `sections`, `detail`, or `fields` could do it server-side.

## Caller Checklist

- Use `sections="identity"` for routine state checks.
- Use `detail="summary"` when truncation is acceptable.
- Cap `top_n_*` and `limit=` aggressively for UI/polling paths.
- Use `fields=` for `search_handoff`, `review_findings`, and artifact reads when only a subset is needed.
- Reserve full-detail session loads for human review, task start, and close-check workflows.
