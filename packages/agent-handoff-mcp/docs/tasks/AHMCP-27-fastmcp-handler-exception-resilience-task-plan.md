# AHMCP-27. FastMCP Handler Exception Resilience

> **Metadata**:
>
> - **Date**: 2026-04-12
> - **Author**: Claude Opus 4.6 (retroactive)
> - **Project**: agent-handoff-mcp
> - **Task ID**: AHMCP-27
> - **Target Branch**: `feature/ahmcp-27`

---

## Objective

Wrap all FastMCP tool handlers with an exception-catching envelope so tool-level errors (e.g., `ValueError: No active task`) return structured `ok: false` response envelopes instead of propagating unhandled exceptions that crash or destabilize the MCP server process.

## Problem Statement

When a tool handler raises an exception — most commonly `ValueError: No active task in handoff_state` when `review_findings` or other task-scoped tools are called before any task is initialized — the exception propagates through FastMCP's transport layer. Depending on the transport and client, this can crash the server process, return an unstructured error string, or leave the client in an ambiguous state where it cannot distinguish "tool failed" from "server died." The server must stay alive after any single tool failure so subsequent calls succeed.

## Constraints

- Must preserve handler signatures so FastMCP's Pydantic-based schema generation continues to work.
- Must use the existing `_envelope(ok=False, ...)` format so error responses are structurally identical to success responses.
- Must not catch `SystemExit` or `KeyboardInterrupt` (only `Exception` subclasses).
- The wrapper applies to all tools uniformly at the registration site; no per-tool opt-out.

## Current State Analysis

- All tool handlers already return `dict` envelopes via `_envelope()` / `_json_response()` on the success path.
- The registration loop in `build_handoff_mcp()` previously called `mcp.add_tool(entry.handler)` directly — no exception boundary existed between handler code and FastMCP transport.
- A prior wrapper (`_make_dict_wrapper`) was removed in AHMCP-10 after handlers were migrated from `-> str` to `-> dict`; the comment at the registration site still references it.

## Proposed Solution

Insert a `_wrap_fastmcp_handler` function at the registration site that:

1. Captures the original handler's `inspect.signature` before wrapping.
2. Wraps the handler with `functools.wraps` + a `try/except Exception` that returns `_envelope(ok=False, tool=entry.name, data={"error": str(exc), "exception_type": type(exc).__name__})`.
3. Validates the return type is `dict`; returns an error envelope if not.
4. Reattaches the original signature (with `return_annotation=dict`) so FastMCP sees the correct parameter schema.

## Verification Strategy

- Deterministic tests:
  - `cd packages/agent-handoff-mcp && make test-handoff` — 496 tests pass
- Specific test:
  - `test_stdio_review_findings_no_active_task_returns_error_envelope_and_keeps_server_alive` — proves error envelope is returned AND server stays alive for follow-up calls

## Slice Delivery

### Slice 1: Exception-to-Envelope Wrapper and Integration Test

**Goal**: All tool handlers wrapped; server survives tool-level exceptions.

Changes:

- `api.py`: Add `_wrap_fastmcp_handler` function; change `mcp.add_tool(entry.handler)` to `mcp.add_tool(_wrap_fastmcp_handler(entry))`
- `test_stdio.py`: Add end-to-end stdio test that calls `review_findings` with no active task, asserts `ok=False` envelope, then calls `get_handoff_state` to prove server liveness

Proof:

- `make test-handoff` — 496 passed
- New test specifically validates error envelope format and server liveness

## Handoff Reference

- MCP task ref: `AHMCP-27`
- Review verdict: decision #1614 (`cla_branch_review_AHMCP-27_resilience_wrapper`)
- Branch review findings: AHMCP-27-BR-01 (pragma:no-cover), AHMCP-27-BR-02 (missing scope in error envelope), AHMCP-27-BR-03 (stale comment)

---

## Consolidated Checklist

### Checklist for Slice 1: Exception-to-Envelope Wrapper

- [x] `_wrap_fastmcp_handler` added to `api.py`
- [x] Registration loop calls `_wrap_fastmcp_handler(entry)` instead of `entry.handler`
- [x] Handler signature preserved via `inspect.signature` + `functools.wraps`
- [x] Exception path returns `_envelope(ok=False)` with error and exception_type
- [x] Non-dict return path returns `_envelope(ok=False)` with InvalidToolResultError
- [x] stdio integration test proves error envelope + server liveness
- [x] `make test-handoff` — 496 passed

## Success Criteria

- [x] Calling any tool that raises an exception returns a structured `ok: false` envelope
- [x] The MCP server process stays alive after any tool-level exception
- [x] All 496 existing tests continue to pass
