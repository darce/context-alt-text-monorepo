# Output Contract v2 Specification

> Spec for `agent-handoff-mcp` output contract changes: tool surface consolidation, response envelope, and CURRENT_TASK.md render cleanup.

**Date:** 2026-04-02
**Status:** Draft
**Assessment:** `docs/assessments/agent-handoff-mcp-output-state-keeping-report.md`
**Package version target:** 0.2.0

---

## Motivation

The current tool surface (28 tools, ~2,500 tokens of catalog per session) and unbounded CURRENT_TASK.md rendering are the two largest contributors to context budget waste. Tool responses lack a common envelope, making agent parsing inconsistent. The profile split (core/extended) hides tools instead of removing them, creating a discovery problem.

This spec defines:
1. Bounded CURRENT_TASK.md rendering (ready to implement)
2. A common response envelope for all tools (ready to implement)
3. Richer mutation responses from compound tools (ready to implement)
4. A tool-surface consolidation target (12-18 tools, pending ADR — see OC-005)

**Constraints:** Greenfield. Breaking changes are free. Historic data can be normalized. No backward-compatibility shims.

---

## Spec Items

### OC-001: Remove "All Review Findings History" from CURRENT_TASK.md

**Trace:** F2
**Priority:** P0

The `_render_findings_section()` function renders a durable "## All Review Findings History" section that includes every finding (fixed, deferred, wontfix, open) across all tasks. `_collect_all_findings_history()` runs an unbounded `SELECT * FROM review_findings` with no status filter. At ~1,800 findings, this dominates CURRENT_TASK.md token cost and grows monotonically.

**Change:** Remove the "All Review Findings History" section from the default render. Remove `_collect_all_findings_history()` from `_build_current_task_render_state()`. Historical findings remain accessible via the existing `list_review_findings(status="all")` tool.

**Before** (`current_task_rendering.py:533-541`):
```python
# --- Durable all-status history ---
lines.extend(["", "## All Review Findings History"])
findings_history = state.get("findings_history_all", {})
if not findings_history:
    lines.append("- None")
else:
    for ref, ref_findings in findings_history.items():
        lines.extend(["", f"### {ref}"])
        lines.extend(_finding_line(f, show_status=True) for f in ref_findings)
```

**After:** Lines removed entirely. `_collect_all_findings_history()` deleted. `findings_history_all` key removed from render state.

**Done when:**
- `generate_current_task_md` output contains no "## All Review Findings History" heading
- `_collect_all_findings_history` function does not exist in `current_task_rendering.py`
- Existing tests updated or removed to match

---

### OC-002: Cap cross-task deferred findings in CURRENT_TASK.md

**Trace:** R-MISS-1, F2
**Priority:** P1

`_collect_all_deferred_findings()` returns all deferred/wontfix findings across all tasks with no limit. As findings accumulate, this section grows without bound.

**Change:** Add a `max_cross_task_findings: int = 5` parameter to `generate_current_task_md`. Apply this cap per task_ref group in both `_collect_all_open_findings()` and `_collect_all_deferred_findings()`. Open findings from the active task remain uncapped (they are the agent's immediate concern).

**After:**
```python
def _collect_all_open_findings(
    conn: sqlite3.Connection,
    active_task_ref: str | None = None,
    max_per_task: int = 5,
) -> dict[str, list[dict]]:
    # ... existing query ...
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        d = dict(row)
        ref = d["task_ref"]
        bucket = grouped.setdefault(ref, [])
        if len(bucket) < max_per_task:
            bucket.append(d)
    return grouped
```

Same pattern for `_collect_all_deferred_findings()`.

**Done when:**
- Cross-task finding sections contain at most `max_per_task` entries per task_ref
- `generate_current_task_md` accepts `max_cross_task_findings` parameter
- Default value is 5

---

### OC-003: Return decision row from `close_slice`

**Trace:** R-MISS-2
**Priority:** P1

`close_slice` calls `record_decision` internally (line 658), parses the result to check `ok`, then discards it. The success response returns only boolean flags, forcing callers to issue a follow-up `get_handoff_state` to confirm the decision ID and new revision.

**Change:** Include the decision row and the new task revision in the success response.

**Before** (`core.py:690-699`):
```python
return _json_response({
    "ok": True,
    "task_ref": resolved_task_ref,
    "decision_recorded": True,
    "state_updated": True,
    "state_error": None,
    "current_task_md_written": True,
})
```

**After:**
```python
return _json_response({
    "ok": True,
    "task_ref": resolved_task_ref,
    "decision_recorded": True,
    "state_updated": True,
    "state_error": None,
    "current_task_md_written": True,
    "decision": decision_result.get("decision"),
    "task_revision": state_result.get("active", {}).get("revision"),
})
```

`decision_result` is already parsed at line 666. `state_result` is already parsed at line 681. No new queries needed.

**Done when:**
- `close_slice` success response includes `decision` (full decision row dict) and `task_revision` (int)
- Callers can confirm decision ID and revision without a follow-up read

---

### OC-004: Common response envelope

**Trace:** F1, F5
**Priority:** P1

Tool responses currently have ad-hoc shapes. Every response includes `ok` but nothing else is guaranteed. Agents must know each tool's custom response structure.

**Change:** Every tool response must include these top-level keys:

```json
{
  "ok": true,
  "schema_version": 2,
  "tool": "record",
  "scope": {
    "task_ref": "E15-3",
    "entity": "finding"
  },
  "data": { },
  "mutation": null,
  "artifacts": [],
  "warnings": []
}
```

| Key | Type | Required | Notes |
|-----|------|----------|-------|
| `ok` | bool | yes | Existing field, unchanged |
| `schema_version` | int | yes | Always `2` for this spec |
| `tool` | string | yes | The tool name that produced this response |
| `scope.task_ref` | string\|null | yes | Resolved task reference |
| `scope.entity` | string\|null | on polymorphic tools | The entity family dispatched to |
| `data` | object | yes | Tool-specific payload (current response body moves here) |
| `mutation` | object\|null | on writes | Structured mutation metadata |
| `artifacts` | array | yes | Render artifacts produced (e.g., CURRENT_TASK.md writes) |
| `warnings` | array | yes | Existing field, promoted to envelope |

**Mutation shape** (present on write responses):

```json
{
  "mutation": {
    "entity": "finding",
    "operation": "update",
    "affected_ids": [412],
    "task_revision": 464
  }
}
```

**Artifact shape** (when a render artifact is produced):

```json
{
  "artifacts": [
    {
      "type": "current_task_md",
      "path": "CURRENT_TASK.md",
      "written": true
    }
  ]
}
```

**Implementation:** Add a `_envelope()` helper in a shared module. All `_json_response()` call sites wrap their current payload as the `data` field inside the envelope.

**Done when:**
- Every tool response contains `ok`, `schema_version`, `tool`, `scope`, `data`, `mutation`, `artifacts`, `warnings`
- `schema_version` is `2` on all responses
- Existing tests updated to assert envelope structure
- `_json_response()` replaced by or delegates to `_envelope()`

---

### OC-005: Consolidate tool surface with typed polymorphic dispatch

**Trace:** F6, report §Tool surface reduction
**Priority:** P0 (design); implementation blocked until ADR is approved
**Status:** Requires design ADR before implementation tasks are created

The current 28-tool surface costs ~2,500 tokens of MCP catalog per session. Many tools share identical dispatch patterns (record X, list X, update X) differentiated only by entity type. The `--tool-profile` mechanism (core/extended) hides tools instead of removing them — agents can't discover or use tools they can't see.

**Goal:** Reduce the tool count significantly while preserving typed MCP schemas that give agents field-level contract information in the tool catalog.

#### Design constraint (from PLAN-01 review)

The current package gets its schema affordances from strongly typed `Annotated` parameters in `api.py`. Any consolidation must preserve typed parameter schemas per entity family — not collapse them into an opaque `payload: dict`. Two viable approaches need evaluation in an ADR:

**Option A — Typed union models:** Each polymorphic tool accepts a discriminated union of Pydantic models, one per entity family. The MCP catalog exposes the full typed schema for each variant. Agents see field names, types, and constraints directly.

```python
class RecordDecisionPayload(BaseModel):
    entity: Literal["decision"]
    decision: str
    rationale: str | None = None
    changed_files: list[str] | None = None
    # ...

class RecordFindingPayload(BaseModel):
    entity: Literal["finding"]
    finding_id: str
    description: str
    file_path: str
    severity: Literal["high", "medium", "low"]
    # ...

RecordPayload = RecordDecisionPayload | RecordFindingPayload | ...

@mcp.tool()
def record(payload: RecordPayload, session: str, task_ref: str | None = None, ...) -> str:
    ...
```

**Option B — Grouped semantic tools:** Instead of 28 or 12, consolidate to ~16-18 tools by merging only tools with identical parameter shapes (e.g., `list_review_findings` + `list_next_actions` + `list_review_runs` share similar filter/pagination params). Keep tools with divergent schemas separate. This preserves full typing with less design risk.

#### Target tool mapping (preliminary — subject to ADR)

| # | New Tool | Absorbs | Dispatch | Entity/Scope Values |
|---|----------|---------|----------|-------------------|
| 1 | **`get_state`** | `get_handoff_state`, `load_session` | `view` | `task`, `session`, `dashboard` |
| 2 | **`list`** | `list_review_findings`, `list_next_actions`, `list_review_runs`, `get_review_coverage`, `audit_decision_ids` | `entity` | `finding`, `action`, `review_run`, `coverage`, `decision` |
| 3 | **`record`** | `record_decision`, `record_review_finding`, `batch_record_review_findings`, `report_blocker`, `record_test_result`, `record_review_run`, `record_artifact` | `entity` | `decision`, `finding`, `findings_batch`, `blocker`, `test`, `review_run`, `artifact` |
| 4 | **`update`** | `update_review_finding`, `update_next_actions`, `set_handoff_state`, `update_task_status` | `entity` | `finding`, `actions`, `state`, `task_status` |
| 5 | **`close_slice`** | *(stays)* | — | — |
| 6 | **`render`** | `generate_current_task_md` | — | — |
| 7 | **`check`** | `handoff_close_check` | — | — |
| 8 | **`search`** | `search_handoff`, `search_artifacts` | `scope` | `handoff`, `artifacts` |
| 9 | **`get_artifact`** | *(stays)* | — | — |
| 10 | **`purge`** | `purge_artifacts` | — | — |
| 11 | **`export`** | `export_handoff_state` | — | — |
| 12 | **`transfer`** | `import_handoff_state`, `archive_task_state` | `operation` | `import`, `archive` |

This mapping is preliminary. The ADR should evaluate whether the 28→12 target is achievable with typed schemas or whether a 28→16-18 target is more practical.

#### Profile removal

Delete the `--tool-profile` / `AGENT_HANDOFF_TOOL_PROFILE` config option. Delete the `profile` field from the tool registry entry. Delete the conditional registration logic at `api.py:1006-1008`. All tools are always registered. This is independent of the consolidation target count and can proceed immediately.

#### Token budget (estimated)

- Current: 28 tools x ~90 tokens = ~2,520 tokens
- Target (12 tools): 12 x ~120 tokens = ~1,440 tokens (~43% reduction)
- Target (16 tools): 16 x ~100 tokens = ~1,600 tokens (~37% reduction)

Exact savings depend on the ADR outcome.

#### ADR scope

The ADR must resolve:

1. Typed unions vs grouped semantic tools vs hybrid
2. Whether FastMCP supports discriminated union tool parameters in practice
3. Final tool count and mapping
4. How the MCP catalog renders union/variant schemas to agents

#### Consumer doc sync (from PLAN-04 review)

Implementation of OC-005 must include updating all downstream surfaces that enumerate the tool names:

- `docs/agentic/contracts/agent-handoff-mcp.md` — tool surface table, profile docs
- `packages/agent-handoff-mcp/README.md` — tool listing
- `docs/agentic/instructions.md` — any tool name references in agent startup protocol
- `CLAUDE.md` — if tool names appear in handoff protocol rules

These updates are part of the done criteria, not a deferred cleanup.

**Done when:**
- ADR approved with chosen consolidation approach
- MCP server exposes the agreed tool count (all tools always registered, no profile split)
- Every entity-specific handler is reachable through its polymorphic parent
- All tool parameters remain typed (no opaque `payload: dict`)
- Consumer-facing contract doc and README updated to match new tool names
- Existing test coverage migrated to new tool names
- Package version bumped to 0.2.0

---

### OC-006: Package and schema versioning

**Trace:** Versioning discussion (2026-04-02)
**Priority:** P1

The package version is static at `0.1.0`. API responses have no version field. The DB schema version (`HANDOFF_SCHEMA_VERSION = 2`) already works correctly.

**Change:**

Two independent version surfaces:

1. **Response `schema_version`:** Set to `2` by OC-004 when the response envelope lands. This is a Tier 2 deliverable — it ships with OC-004 regardless of OC-005 status.
2. **Package version (`pyproject.toml`):** Bump to `0.2.0` when OC-004 (response envelope) ships. The package version marks the output contract break, not the tool-surface consolidation. If OC-005 later changes the tool surface, bump to `0.3.0` at that time.
3. **DB schema version:** If any spec item requires schema changes, bump `HANDOFF_SCHEMA_VERSION` and add the migration to `_apply_handoff_migrations()`.

**Done when:**
- `pyproject.toml` version is `0.2.0` (ships with OC-004)
- `schema_version: 2` field present in all responses (per OC-004)
- `HANDOFF_SCHEMA_VERSION` bumped if schema changed

---

### OC-007: Default `export_handoff_state` to `include_markdown=false`

**Trace:** F1
**Priority:** P2

`export_handoff_state` defaults to `include_markdown=True`, embedding the full CURRENT_TASK.md markdown in the export JSON. This mixes canonical state with rendered artifacts.

**Change:** Flip default to `include_markdown=False`. Callers who need markdown in exports pass it explicitly.

**Before** (`import_export.py`):
```python
def export_handoff_state(
    ...,
    include_markdown: bool = True,
) -> str:
```

**After:**
```python
def export_handoff_state(
    ...,
    include_markdown: bool = False,
) -> str:
```

**Done when:**
- Default exports contain no `current_task_markdown` key unless `include_markdown=True` is passed
- Existing import logic handles missing `current_task_markdown` gracefully (it already does — the key is optional in the import path)

---

## Entity Payload Schemas

Reference schemas for each entity family in the polymorphic `record` and `update` tools. These are the required and optional fields for the `payload` dict.

### `record` payloads

#### `decision`
```json
{
  "decision": "string (required, stable identifier)",
  "rationale": "string | null",
  "changed_files": ["string"] | null,
  "input_tokens": "int | null",
  "output_tokens": "int | null",
  "total_tokens": "int | null"
}
```

#### `finding`
```json
{
  "finding_id": "string (required)",
  "description": "string (required)",
  "file_path": "string (required)",
  "severity": "'high' | 'medium' | 'low' (required)",
  "review_mode": "string | null",
  "details": {
    "fix": "string | null",
    "line_start": "int | null",
    "line_end": "int | null"
  } | null
}
```

#### `findings_batch`
```json
{
  "findings": [
    { "...same as finding payload..." }
  ]
}
```

#### `blocker`
```json
{
  "operation": "'add' | 'resolve' | 'reopen' (required)",
  "description": "string | null (required for add)",
  "blocker_id": "int | null (required for resolve/reopen)"
}
```

#### `test`
```json
{
  "command": "string (required)",
  "passed": "bool (required)",
  "result": "string | null",
  "exit_code": "int | null"
}
```

#### `review_run`
```json
{
  "review_run_id": "string (required)",
  "subject_path": "string (required)",
  "subject_kind": "'task_plan' | 'epic' | 'branch' | 'adr' | 'roadmap' | 'other'",
  "review_mode": "string",
  "verdict": "'pass' | 'pass_with_findings' | 'fail' | 'conditional_pass' | null",
  "verdict_decision": "string | null"
}
```

#### `artifact`
```json
{
  "source_kind": "string (required)",
  "source_label": "string (required)",
  "content": "string (required)",
  "content_type": "string (default: 'text/plain')",
  "summary": "string | null",
  "metadata": "object | null",
  "lane_id": "string | null",
  "app_root": "string | null"
}
```

### `update` payloads

#### `finding`
```json
{
  "status": "'open' | 'fixed' | 'deferred' | 'wontfix' (required)",
  "finding_id": "string | null",
  "finding_db_id": "int | null",
  "resolution_notes": "string | null",
  "reopen_reason": "string | null",
  "verified_commit_sha": "string | null",
  "verification_evidence": "string | null"
}
```

#### `actions`
```json
{
  "operation": "'add' | 'update' | 'complete' | 'skip' (required)",
  "action_id": "int | null",
  "action": "string | null",
  "priority": "int | null",
  "status": "'pending' | 'done' | 'skipped' | null"
}
```

#### `state`
```json
{
  "objective": "string | null",
  "focus": "string | null",
  "status": "'in_progress' | 'blocked' | 'review' | 'done'",
  "expected_revision": "int | null"
}
```

#### `task_status`
```json
{
  "status": "'in_progress' | 'blocked' | 'review' | 'done' (required)",
  "expected_revision": "int | null"
}
```

### `list` parameters

#### `finding`
Accepts: `status`, `severity`, `review_mode`, `finding_id`, `finding_db_id`, `limit`, `offset`, `detail`

#### `action`
Accepts: `task_ref`, `status`

#### `review_run`
Accepts: `task_ref`, `review_mode`, `limit`, `offset`

#### `coverage`
Accepts: `task_ref`

#### `decision`
Accepts: `task_ref`, `session`

---

## Implementation Tiers

### Tier 1 — Ready to implement (high certainty, code-verified, independent)

These items have concrete before/after code, verified symbols, and no design ambiguity. Implementation tasks can be created immediately.

Task plan: `packages/agent-handoff-mcp/docs/tasks/AHMCP-2-bounded-current-task-rendering-and-mutation-output-task-plan.md`

```
OC-001  Remove findings history from CURRENT_TASK.md     ~10 lines, independent
OC-002  Cap cross-task findings                           ~20 lines, independent
OC-003  Enrich close_slice response                       ~5 lines, independent
OC-007  Default exports to include_markdown=false         1 line, independent
```

OC-001 through OC-003 can be parallelized. No dependencies between them.

### Tier 2 — Ready to implement after Tier 1 (mechanical, touches many files)

Task plan: `packages/agent-handoff-mcp/docs/tasks/AHMCP-3-response-envelope-and-output-contract-v2-rollout-task-plan.md`

```
OC-004  Response envelope                                 Mechanical across all handlers
OC-006  Package version bump to 0.2.0                     Ships with OC-004
```

OC-004 should land after Tier 1 so the envelope doesn't need to be updated when Tier 1 changes handler return shapes. OC-006 (package version bump) ships with OC-004 — it marks the output contract break, not the tool consolidation.

### Tier 3 — Blocked on ADR (architectural bet, design unresolved)

Design task: `packages/agent-handoff-mcp/docs/tasks/AHMCP-4-typed-tool-surface-consolidation-adr-task-plan.md`

ADR: `docs/agentic/adrs/ADR-005-agent-handoff-mcp-typed-tool-surface-consolidation.md`

```
OC-005  Tool surface consolidation                        Requires ADR on typed dispatch model
```

OC-005 must not become an implementation task until the ADR resolves:
1. Typed unions vs grouped semantic tools vs hybrid
2. Whether FastMCP supports discriminated union parameters
3. Final tool count
4. Consumer doc sync scope

Create the ADR as a design task, not an implementation task.

## Spec-Review Gate

This spec was reviewed (PLAN-01 through PLAN-04) before implementation task creation. That review caught invented field names, broken validation commands, and an under-specified consolidation model. **This should be standard for contract and spec work.**

**Rule:** No implementation tasks may be created from a spec until:
1. The spec has been reviewed with findings recorded in MCP
2. All review findings are resolved (fixed, deferred with rationale, or wontfix)
3. Validation snippets have been verified against the current package (not guessed)

For Tier 3 / architectural items, the review gate applies to the ADR as well — the ADR must be reviewed before the implementation spec is written.

---

## Validation

Validation snippets are split by tier. Each snippet runs against the package state after its tier is implemented.

### Tier 1 validation (runs against pre-envelope response shapes)

```bash
# --- OC-001: No findings history in CURRENT_TASK.md ---
python -c "
import json, os
os.environ.setdefault('AGENT_HANDOFF_WORKSPACE_ROOT', '.')
from agent_handoff_mcp import generate_current_task_md, configure_runtime
from agent_handoff_mcp.config import RuntimeConfig
configure_runtime(RuntimeConfig.for_workspace('.'))
md_raw = generate_current_task_md(write_file=False)
parsed = json.loads(md_raw)
# Pre-envelope: top-level 'markdown'; post-envelope: nested under 'data'
content = parsed.get('data', {}).get('markdown', '') or parsed.get('markdown', '') or ''
assert '## All Review Findings History' not in content, 'History section still present'
print('OC-001 OK: no findings history section')
"

# --- OC-002: Cross-task findings capped ---
# Verified via CURRENT_TASK.md content inspection:
# each cross-task section should have <= max_cross_task_findings entries per task_ref

# --- OC-003: close_slice returns decision row ---
# Verified by calling close_slice and checking response keys:
# json.loads(result) must contain 'decision' (dict) and 'task_revision' (int)

```

### Tier 2 validation (runs after OC-004 response envelope lands)

```bash
# --- OC-004: Response envelope ---
python -c "
import json, os
os.environ.setdefault('AGENT_HANDOFF_WORKSPACE_ROOT', '.')
from agent_handoff_mcp import get_handoff_state, configure_runtime
from agent_handoff_mcp.config import RuntimeConfig
configure_runtime(RuntimeConfig.for_workspace('.'))
result = json.loads(get_handoff_state())
assert result.get('schema_version') == 2, f'Expected schema_version 2, got {result.get(\"schema_version\")}'
assert 'data' in result, 'Missing data key'
assert 'tool' in result, 'Missing tool key'
assert 'scope' in result, 'Missing scope key'
print('OC-004 OK: envelope present')
"

# --- OC-005: Tool count (target TBD per ADR) ---
# Deferred until ADR resolves final tool count

# --- OC-006: Package version ---
python -c "
import importlib.metadata
v = importlib.metadata.version('agent-handoff-mcp')
assert v == '0.2.0', f'Expected 0.2.0, got {v}'
print(f'OC-006 OK: version {v}')
"

# --- Full test suite ---
make test-handoff
```