# Tech Debt: Migrate Deprecated-Alias Test Call Sites

## Background

E12-5 (MCP Server Split and Tool Consolidation) removed six tools from the `agent-handoff-mcp` MCP surface by consolidating them into their successors:

| Removed alias | Successor |
| --- | --- |
| `get_artifact_source` | `get_artifact(source_id=...)` |
| `get_artifact_terms` | `get_artifact(..., include_terms=True)` |
| `list_artifact_sources` | `search_artifacts()` with no queries |
| `get_review_finding` | `list_review_findings(finding_id=...)` |
| `reopen_review_finding` | `update_review_finding(status="open", reopen_reason=...)` |
| `get_handoff_dashboard` | `get_handoff_state(view="dashboard")` |

The Python alias functions remain in `core.py` (not MCP-exposed) because test code calls them directly. Until these tests are migrated, the aliases cannot be deleted.

## Scope

~30 call sites across two test files:

| File | Aliases used |
| --- | --- |
| `packages/agent-handoff-mcp/tests/test_artifact_tools.py` | `get_artifact_source` (~8 sites), `list_artifact_sources` (~6 sites), `get_artifact_terms` (~4 sites) |
| `packages/agent-handoff-mcp/tests/test_handoff_state.py` | `get_review_finding` (~2 sites), `reopen_review_finding` (~1 site), `get_handoff_dashboard` (~1 site) |

## Work

For each call site, replace with the successor API:

```python
# Before
handoff_core.get_artifact_source(source_id=x)
# After
handoff_core.get_artifact(source_id=x)

# Before
handoff_core.get_artifact_terms(source_id=x, top_n=5)
# After
handoff_core.get_artifact(source_id=x, include_terms=True, top_n_terms=5)

# Before
handoff_core.list_artifact_sources(task_ref="t")
# After — result shape changes: ok=True, mode="sources", sources=[...]
result = _parse(handoff_core.search_artifacts(task_ref="t"))
assert result["mode"] == "sources"
rows = result["sources"]

# Before
mcp_server.get_review_finding(finding_db_id=x)
# After
result = _parse(mcp_server.list_review_findings(finding_db_id=x))
finding = result["findings"][0]   # reshape from single-finding to list envelope

# Before
mcp_server.reopen_review_finding(reason="...", finding_id="H-1")
# After
mcp_server.update_review_finding(status="open", reopen_reason="...", finding_id="H-1")

# Before
mcp_server.get_handoff_dashboard(include_archived=True)
# After
mcp_server.get_handoff_state(view="dashboard")
```

After migration: delete `get_artifact_source`, `get_artifact_terms`, `reopen_review_finding`, `get_review_finding`, and `get_handoff_dashboard` from `core.py` and their re-exports from `api.py` and `__init__.py`. `list_artifact_sources` may also be removed unless `scripts/mcp/unified_server.py` is still active.

## Notes

- `list_artifact_sources` response envelope changed in E12-5: it now returns `{"ok": true, "mode": "sources", "sources": [...]}` instead of a bare list. Test assertions must be updated accordingly.
- `get_review_finding` returned `{"ok": true, "finding": {...}}` (single-item envelope); `list_review_findings(finding_id=...)` returns `{"ok": true, "findings": [...]}`. Tests that unpack `result["finding"]` need updating to `result["findings"][0]`.
- `scripts/mcp/unified_server.py` is a self-contained legacy file that defines its own copies of these functions. It does not import from the package and is unaffected by alias deletion in `core.py`.

## Acceptance Criteria

- [x] All ~30 call sites in `test_artifact_tools.py` and `test_handoff_state.py` use successor APIs.
- [x] `get_artifact_source`, `get_artifact_terms`, `reopen_review_finding`, `get_review_finding`, `get_handoff_dashboard` deleted from `core.py`.
- [x] Corresponding re-exports removed from `api.py` and `__init__.py`.
- [x] `python -m pytest packages/agent-handoff-mcp/tests/ -q` passes (800 tests).
