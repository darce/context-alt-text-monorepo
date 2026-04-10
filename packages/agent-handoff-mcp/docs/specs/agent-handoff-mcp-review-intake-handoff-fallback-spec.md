# Review Intake Handoff Fallback Specification

> **Metadata**
>
> - **Date**: 2026-04-10
> - **Author**: GPT-5.4
> - **Status**: Draft
> - **Assessment**: `packages/agent-handoff-mcp/docs/assessments/agent-handoff-mcp-review-intake-tooling-proposal.md`
> - **Package version target**: `n/a`
>
> **Purpose:** This spec turns the 2026-04-10 review-intake assessment and ADR-007 into concrete, testable work. It closes the handoff-only cold-start gap without reintroducing packet duplication across `agent-handoff-mcp` and `agent-orchestrator-mcp`.
>
> **Pipeline position:** Assessment -> Spec -> [ADR] -> Task Plan -> Implementation.
>
> **Exit gate:** At least one planning review pass with findings recorded in MCP. All findings resolved. Validation snippets verified against the current package. No implementation tasks may be created until this gate is passed.

---
> Cold-start review already has a canonical compound packet on `agent-orchestrator-mcp`. The remaining gap is narrower: handoff-only callers still cannot search or list verified test rows directly, and the fallback sequence is implicit rather than documented. This spec makes those primitive reads explicit while preserving orchestrator ownership of compound review packets.

**Constraints:** ADR-007 is binding: compound review-summary ownership stays on `agent-orchestrator-mcp`; `agent-handoff-mcp` adds only ledger-native primitives and documentation. Greenfield policy applies; schema/bootstrap changes land in the baseline schema path, not in preservation-oriented migrations. No imports from `agent_orchestrator_mcp` may be added to `agent-handoff-mcp`.

---

## Spec Items

### RIF-001: Make verified test rows searchable through `search_handoff`

**Trace:** F2, F3
**Priority:** P0

`verified_tests` rows already exist as durable ledger records, but the current search surface cannot query them. That forces handoff-only reviewers to guess which direct reads to make after they discover a slice-complete decision. The search surface must treat verification evidence as a first-class searchable record type so the fallback flow can discover test evidence through the same FTS entry point as decisions, findings, blockers, and actions.

**Before** (`packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py::search_handoff`, `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py::HANDOFF_SCHEMA_SQL`):

```python
_VALID_RECORD_TYPES: frozenset[str] = frozenset({"decision", "finding", "blocker", "action"})

_RECORD_TYPE_FTS_MAP: dict[str, tuple[str, bool]] = {
    "decision": ("decisions_fts", False),
    "finding": ("findings_fts", True),
    "blocker": ("blockers_fts", True),
    "action": ("actions_fts", True),
}

_HANDOFF_REQUIRED_FTS_TABLES = frozenset({"decisions_fts", "findings_fts", "blockers_fts", "actions_fts"})
```

**After:**

```python
_VALID_RECORD_TYPES: frozenset[str] = frozenset(
    {"decision", "finding", "blocker", "action", "verified_test"}
)

_RECORD_TYPE_FTS_MAP: dict[str, tuple[str, bool]] = {
    "decision": ("decisions_fts", False),
    "finding": ("findings_fts", True),
    "blocker": ("blockers_fts", True),
    "action": ("actions_fts", True),
    "verified_test": ("verified_tests_fts", False),
}

_HANDOFF_REQUIRED_FTS_TABLES = frozenset(
    {"decisions_fts", "findings_fts", "blockers_fts", "actions_fts", "verified_tests_fts"}
)

CREATE VIRTUAL TABLE IF NOT EXISTS verified_tests_fts USING fts5(
    body,
    record_id UNINDEXED,
    task_ref UNINDEXED,
    lane_id UNINDEXED,
    tokenize = 'porter unicode61'
);
```

The indexed body must be `command || ' ' || COALESCE(result, '')`, and the table must receive the same insert/update/delete trigger coverage and backfill handling as the existing four FTS tables.

**Done when:**

- `search_handoff(..., record_types=["verified_test"])` returns a valid envelope instead of an invalid-record-type error.
- Schema bootstrap, FTS trigger registration, and FTS backfill all include `verified_tests_fts`.
- Search results can return `record_type: "verified_test"` rows with snippets derived from the verification command and result text.
- Regression tests cover both schema/bootstrap behavior and search behavior for `verified_test` rows.

---

### RIF-002: Add `get_verified_tests` as a handoff-native primitive read

**Trace:** F2, F3, ADR-007 rule 2
**Priority:** P0

Search alone is not enough for deterministic cold-start review. Once a caller has the relevant task ref and commit SHA, it still needs an exact, ordered ledger read that returns the matching verification rows without reconstructing them from packet text or raw SQL. `agent-handoff-mcp` must expose that read directly.

**Before** (`packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py::TOOL_DESCRIPTIONS`, `packages/agent-handoff-mcp/src/agent_handoff_mcp/decisions.py::record_test_result`):

```python
TOOL_DESCRIPTIONS: dict[str, str] = {
    ...
    "search_handoff": "Search decisions, findings, blockers, actions by keyword with BM25 ranking.",
}

def record_test_result(
    session: str,
    command: str,
    passed: bool,
    ...
) -> str:
    ...  # inserts into verified_tests
```

**After:**

```python
def get_verified_tests(
    task_ref: str | None = None,
    lane_id: str | None = None,
    branch: str | None = None,
    commit_sha: str | None = None,
    passed: bool | None = None,
    limit: int = 20,
) -> dict:
    """List verified_tests rows ordered by verified_at DESC, id DESC."""
```

The tool must return the canonical v2 envelope with `data.tests` as the row list and must support these filters:

- `task_ref` defaulting to the active task when omitted
- `lane_id` exact-match filter
- `branch` exact-match filter
- `commit_sha` exact-match filter
- `passed` optional pass/fail filter
- `limit` clamped to the existing read-surface safety range

Rows must expose the existing stored columns only: `id`, `task_ref`, `lane_id`, `command`, `passed`, `exit_code`, `result`, `session`, `agent`, `branch`, `commit_sha`, `verified_at`.

**Done when:**

- `get_verified_tests` is registered as a public MCP tool and documented in the handoff contract.
- The tool returns verified test rows ordered by `verified_at DESC, id DESC`.
- Filtering by `task_ref`, `lane_id`, `branch`, `commit_sha`, and `passed` is covered by tests.
- No handoff code reconstructs compound slice packets or imports orchestrator packet helpers to satisfy the read.

---

### RIF-003: Document the handoff-only fallback path without inventing a second packet

**Trace:** F3, F4, F5, ADR-007 rules 3-5
**Priority:** P1

The review guides already prefer the orchestrator packet. What is missing is the explicit degraded-path recipe for sessions where only `agent-handoff-mcp` is loaded. The contracts and guides must say that clearly, and they must do so without implying that handoff owns a second packet builder.

**Before** (`docs/agentic/contracts/agent-handoff-mcp.md`, `docs/agentic/rules/branch-review-guide.md`, `docs/agentic/rules/planning-review-guide.md`):

```md
Cross-task and review-summary tools (`switch_task`, `get_latest_slice_review_packet`,
`get_review_findings_summary`, `reconcile_review_findings`) are registered on
`agent-orchestrator-mcp`.

# branch/planning review guides
- prefer the latest-slice packet before diff archaeology
```

**After:**

```md
Preferred path when orchestrator is loaded:
1. `get_latest_slice_review_packet`
2. `get_review_findings_summary` or `review_findings(list)` as needed

Handoff-only fallback:
1. `load_session`
2. `search_handoff(query="slice_complete", record_types=["decision"], limit=1)`
3. `get_verified_tests(task_ref=..., commit_sha=...)`
4. `review_findings(operation="list", status="open")`
```

The documentation must explicitly say that this is a degraded multi-call fallback and that `agent-handoff-mcp` does **not** expose a parallel `get_review_packet`-style compound tool.

**Done when:**

- The handoff contract documents both the new `get_verified_tests` tool and the `verified_test` search record type.
- The branch and planning review guides include a `Handoff-only fallback` section that preserves packet-first guidance while documenting the deterministic fallback sequence.
- Assessment and ADR references point to the created spec and task plans rather than placeholder “to be created” language.
- No doc claims that handoff owns a second compound review packet.

---

## Entity / Payload Schemas

### `get_verified_tests` response row

```json
{
  "id": "integer",
  "task_ref": "string",
  "lane_id": "string | null",
  "command": "string",
  "passed": "boolean",
  "exit_code": "integer | null",
  "result": "string | null",
  "session": "string",
  "agent": "string | null",
  "branch": "string | null",
  "commit_sha": "string | null",
  "verified_at": "datetime string"
}
```

### `search_handoff` result for `verified_test`

```json
{
  "record_type": "verified_test",
  "record_id": "integer",
  "task_ref": "string",
  "lane_id": "string | null",
  "status": null,
  "snippet": "string"
}
```

---

## Implementation Tiers

### Tier 1 — Ready to implement

Task plan: `packages/agent-handoff-mcp/docs/tasks/AHMCP-8-verified-test-search-and-read-surfaces-task-plan.md`

```text
RIF-001  Make verified_tests searchable through search_handoff   schema + search + regression coverage
RIF-002  Add get_verified_tests primitive read                   new MCP read surface + contract coverage
```

Both items stay inside `agent-handoff-mcp` plus its owning contract doc. They can land in one package-local implementation task because they share the same ledger boundary and proof surface.

### Tier 2 — Ready after Tier 1

Task plan: `packages/agent-handoff-mcp/docs/tasks/AHMCP-9-review-intake-fallback-adoption-docs-task-plan.md`

```text
RIF-003  Document packet-first plus handoff-only fallback guidance   depends on shipped RIF-001/RIF-002 semantics
```

This tier depends on Tier 1 because the fallback docs must reference the real public tool shape, not speculative names.

### Tier 3 — Blocked on ADR

Design task: `none`
ADR: `docs/adrs/ADR-007-review-intake-handoff-fallback-boundary.md`

```text
none  ADR-007 resolved the only boundary question for this scope
```

No Tier 3 items remain for this spec.

---

## Spec-Review Gate

No implementation tasks may be created from this spec until:

1. The spec has been reviewed with findings recorded in MCP
2. All review findings are resolved (fixed, deferred with rationale, or wontfix)
3. Validation snippets have been verified against the current package (not guessed)

For Tier 3 / architectural items, the review gate applies to the ADR as well — the ADR must be reviewed before implementation tasks are created from it.

---

## Validation

### Tier 1 validation

```bash
# --- RIF-001 / RIF-002: searchable verified tests + primitive read ---
cd packages/agent-handoff-mcp && make test-handoff
cd packages/agent-handoff-mcp && make mypy-handoff
```

### Tier 2 validation

```bash
# --- RIF-003: contract and review-guide fallback docs ---
rg -n "get_verified_tests|verified_test|Handoff-only fallback" \
  docs/agentic/contracts/agent-handoff-mcp.md \
  docs/agentic/rules/branch-review-guide.md \
  docs/agentic/rules/planning-review-guide.md \
  packages/agent-handoff-mcp/docs/assessments/agent-handoff-mcp-review-intake-tooling-proposal.md \
  docs/adrs/ADR-007-review-intake-handoff-fallback-boundary.md
```