# MCP Token Optimization Assessment

**Date:** 2025-07-16
**Scope:** agent-handoff-mcp response formatting, token consumption, alternatives evaluation

---

## 1. JSON Formatting Issue ("formatting characters instead of dicts")

### Root Cause (Resolved)

FastMCP's `function_parsing.py` detects `-> str` return types and wraps them
with `x-fastmcp-wrap-result: True`. At runtime, `tool.py` wraps the value as
`structured_content={"result": "<escaped JSON>"}`, so clients receive escaped
JSON inside a string field instead of native dict objects.

### Current Fix

`_make_dict_wrapper()` in `api.py:1477-1530` intercepts every registered tool
handler. It:

1. Parses the handler's JSON string return into a Python dict via `json.loads()`
2. Replaces the `__signature__` return annotation with `dict`
3. Sets `__annotations__["return"] = dict` (the type object, not the string `"dict"`)
4. Deletes `__wrapped__` so `inspect.signature()` doesn't follow the chain back

All 17 registered tools go through this wrapper (applied at `api.py:1567-1574`).

### Residual Risk: PEP 563 Annotation Mismatch

The wrapper sets `"return": dict` as the type object. If `from __future__
import annotations` is ever added (PEP 563), all annotations become strings at
parse time. FastMCP's `get_type_hints()` would see `"dict"` (string) vs `dict`
(type object), potentially causing a misbatch. Current files do NOT use PEP 563,
so this is a theoretical risk but worth noting for future maintainers.

### Verdict

The double-serialization problem is **solved** by `_make_dict_wrapper`. No action
needed unless the escaped-string symptom recurs; if it does, check whether a new
tool registration bypasses the wrapper loop.

---

## 2. Response Size and Token Consumption

### Envelope Duplication (~50% overhead)

`_envelope()` in `shared_primitives.py:203-233` builds every response with a
nested `data` block AND mirrors all data fields at the top level:

```python
payload["data"] = dict(data)   # canonical v2 shape
payload.update(dict(data))     # backward-compat mirror
```

For a response with 10 data fields, this doubles the payload. The backward-compat
comment says "legacy `result['foo']` access" but no caller outside the test suite
uses the top-level path anymore; agents use `result["data"]["foo"]`.

**Recommendation:** Bump `schema_version` to 3 and stop mirroring. Gate behind a
per-call `schema_version=3` parameter or a server config flag. Estimated savings:
30-50% of all response bytes.

### Response Size by Tool

| Tool | Default Size | With Optimization Params | Savings |
|------|-------------|-------------------------|---------|
| `get_handoff_state` (full) | 15-50 KB | `sections="identity"`: ~1 KB | 95%+ |
| `load_session` | 35-60 KB | `detail="summary"`: ~5 KB | 85%+ |
| `search_handoff` | 100-300 tokens | Already lightweight | N/A |
| `review_findings(list)` | 2-10 KB | `fields=`, `detail=`: ~1 KB | 50-80% |
| `review_findings(batch_record)` | Lightweight (IDs only) | N/A | N/A |

### Existing Optimization Parameters (Underused)

These parameters already exist but callers rarely use them:

- **`sections=`** on `get_handoff_state` / `load_session` ; filters to specific
  sections (identity, events, findings, archives). Using `sections="identity"`
  drops a full state fetch from ~30 KB to ~1 KB.
- **`detail="summary"|"full"`** on multiple tools; summary mode strips verbose
  fields like full event bodies and git provenance.
- **`fields=`** on `search_handoff` and `review_findings`; controls which
  columns are returned per row.
- **`top_n_events=`** and `top_n_findings=`** on `get_handoff_state`; limits the
  number of events/findings included (default is often "all").
- **`limit=`** on `search_handoff` and `review_findings(list)`.

### Wasteful Fields in Default Responses

- **Timestamps:** Every event row includes `created_at`, `updated_at`; adds
  ~500+ bytes for a typical task.
- **Reopen metadata:** `reopen_count`, `was_reopened`, `reopen_reason` on every
  finding; these are almost never meaningful.
- **Git provenance:** `sha`, `branch`, `author_tag` repeated per event row when
  the whole task typically lives on one branch.

### Actionable Recommendations

1. **Agents should use `sections="identity"` for routine state checks** instead
   of fetching the entire state. Reserve full fetches for review passes and
   task-start hot-state loads. `load_session` at session start should stay at
   the full-detail default unless the caller explicitly opts in to a lighter
   mode (see item 2).
2. **`detail="summary"` is an explicit opt-in, not a new default.** The live
   contract (`docs/agentic/contracts/agent-handoff-mcp.md`) preserves the
   pre-parameterization full-payload behavior for `load_session`; changing the
   default is a breaking contract change governed by `AHMCP-1` (additive,
   compatibility-managed parameterization with stable defaults). Callers that
   need smaller payloads should pass `detail="summary"` explicitly.
3. **Summary-mode field shaping (reopen metadata, git provenance)** is owned by
   [`AHMCP-1`](../../agent-handoff-mcp/docs/tasks/AHMCP-1-parameterize-handoff-mcp-read-surfaces-task-plan.md).
   Track implementation and any default-change decisions there.
4. **Envelope token optimization (legacy mirroring, compact serialization)** is
   owned by
   [`AHMCP-7`](../../agent-handoff-mcp/docs/tasks/AHMCP-7-response-envelope-token-optimization-task-plan.md),
   which explicitly excludes orchestrator-side edits. Track implementation there.
5. **Usage guidance belongs in `agent-handoff-mcp` package documentation.**
   Add a "Token-efficient usage" section to the package README or a dedicated
   `packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md`.
   `docs/agentic/instructions.md` and repo-level copilot instruction files
   should reference that package-owned guidance rather than owning the
   parameter patterns themselves.

---

## 3. Alternative Evaluation

### MemPalace (`milla-jovovich/mempalace`)

14k-star MCP memory server (v3.0.0, April 2026). Stores verbatim conversations
in ChromaDB with a hierarchical "palace" structure (wings/halls/rooms/closets/
drawers). 19 MCP tools, local-only, 96.6% LongMemEval R@5. Also has a knowledge
graph (SQLite), specialist agent diaries, and AAAK compression (experimental,
lossy, currently regresses recall).

**Assessment: not a replacement; potentially complementary.**

MemPalace is a *recall system* for long-term conversation memory ("what did we
decide about auth 3 months ago?"). It has no concept of:
- Active task state or lifecycle (in_progress/done/archived)
- Structured decision/event recording with actor attribution
- Review findings with status workflow (open -> fixed/deferred/wontfix)
- Pre-merge gate enforcement (`handoff_close_check`)
- Dashboard generation (CURRENT_TASK.md)
- Slice-complete checkpoints

It could add value as a **long-term memory layer alongside** agent-handoff-mcp;
e.g., mining archived decisions for cross-session recall of past architectural
choices. But it solves a fundamentally different problem (retrieval of past
conversations vs real-time workflow state management).

**Caveats:** very new (launched days ago), authors acknowledged overstated claims
in a public correction (AAAK compression, benchmark framing), shell injection
bugs recently patched in hooks. Worth monitoring but not production-ready for
adoption today.

### Generic MCP Memory Servers (GitHub `topics/mcp-memory`)

Seven repos were evaluated:

| Project | Focus | Fit |
|---------|-------|-----|
| enhanced-mcp-memory | General key-value memory | No task/decision tracking |
| memlord | Conversation memory | No structured handoff |
| tensory | Tensor-based embeddings | Wrong domain entirely |
| mcp-handoff-server | Generic agent handoff | No review findings, no orchestration |
| Yggdrasil | Knowledge graph | Over-engineered for our needs |
| Muninn | RAG memory | No task lifecycle |
| mcp-memory-service | Semantic search memory | No structured events/decisions |

**None** provide:
- Structured task lifecycle (in_progress -> done -> archived)
- Decision/event recording with actor attribution
- Review findings with status workflow (open -> fixed/deferred/wontfix)
- Slice-complete checkpoints
- CURRENT_TASK.md dashboard generation
- Handoff close checks with enforcement

### Official MCP Memory Server

The reference `@modelcontextprotocol/server-memory` provides a knowledge-graph
memory system. It stores entities and relations but has no concept of task state,
review findings, or pre-merge gates; it is designed for persistent *knowledge*,
not *workflow state*.

### Pure Bash Alternative

A bash-only approach (flat files + jq) could replace the SQLite backend for
simple read/write operations. However:

- **Lost:** ACID transactions, concurrent access safety, structured queries,
  revision tracking, atomic batch operations
- **Lost:** `search_handoff` full-text search across decisions
- **Lost:** `handoff_close_check` enforcement logic
- **Gained:** Zero Python dependency for CLI-only workflows

This would be a significant regression in capability for marginal simplicity gains.

### Verdict

**Keep agent-handoff-mcp.** It is a mature, domain-specific package with features
no alternative provides. The token consumption problem is a caller-side
optimization issue (not using available parameters) combined with a server-side
envelope duplication that can be fixed with a schema_version bump.

---

## 4. Priority Action Items

| Priority | Action | Effort | Impact |
|----------|--------|--------|--------|
| **P1** | Document preferred param patterns in package-owned `agent-handoff-mcp` docs | Low | High; immediate token savings |
| **P2** | Remove envelope duplication (schema_version=3) | Medium | 30-50% payload reduction |
| **P3** | Adopt `detail="summary"` explicitly in caller paths that can tolerate truncation | Low | High on targeted session/read paths without changing server defaults |
| **P4** | Strip reopen/git fields from summary mode | Low | ~500 bytes per response |
| **P5** | Monitor PEP 563 annotation risk in wrapper | None (document only) | Prevents future regression |

---

## 5. Summary

The JSON formatting issue is already solved by `_make_dict_wrapper`. Token waste
comes from two sources: (1) callers not using existing optimization parameters, and
(2) the `_envelope()` backward-compat mirror doubling every payload. Both are
fixable without architectural changes. No viable alternative exists that covers the
domain-specific handoff workflow this project requires.
