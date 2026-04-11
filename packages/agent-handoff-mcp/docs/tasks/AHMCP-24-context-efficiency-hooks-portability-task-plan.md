# Task Plan

> **Metadata**
>
> - **Date**: 2026-04-11
> - **Author**: GPT-5.4
> - **Project**: agent-handoff-mcp
> - **Task ID**: AHMCP-24
> - **Target Branch**: `feature/ahmcp-24`

---

## AHMCP-24. Context Efficiency Hooks Portability

## Objective

Ensure the context-efficiency guardrails work across Claude, VS Code, and Codex surfaces. Current findings showed the implementation depended on legacy matcher names and a Claude-only mental model. The Bash test-output summarizer must register in Codex correctly, and the MCP-oriented safeguards must remain effective even where Codex cannot intercept MCP tools directly.

## Problem Statement

The initial slice added three hook scripts:

1. `guard-rationale-size.py`
2. `slim-handoff-response.py`
3. `filter-test-output.py`

Branch review found three portability gaps:

- VS Code hook matchers still referenced legacy `mcp__agent-handoff-mcp__...` names instead of the current `mcp_altcontext-mc_...` names.
- Codex had no hook registration at all; Codex hook support also uses `.codex/hooks.json`, not `.codex/config.toml` matcher entries.
- Tests only validated the scripts in isolation, so broken harness wiring could ship unnoticed.

Codex adds an important constraint: its current hook runtime only matches `Bash` for `PreToolUse` and `PostToolUse`. It cannot intercept MCP calls such as `record_event`, `close_slice`, `get_handoff_state`, or `load_session`. That means MCP-only guardrails must live in the backend, not only in host-adapter hook config.

## Constraints

- Do not guess undocumented Codex config shapes. Use the documented `.codex/hooks.json` surface.
- Keep the Bash output summarizer as a hook where the host supports it.
- Move MCP-critical protections into shared handoff code so Codex gets the same safety guarantees.
- Preserve backward compatibility for legacy matcher names while preferring current `altcontext` names.

## Proposed Solution

### Slice 1: Fix harness registration

- Update `.claude/settings.json` matchers to include current `mcp_altcontext-mc_*` names.
- Update `.github/hooks/terminal-guard.json` matchers the same way.
- Enable Codex hooks via `[features] codex_hooks = true` in `.codex/config.toml`.
- Register Bash post-tool summarization in `.codex/hooks.json`.

### Slice 2: Make MCP protections portable

- Enforce rationale hard limits in shared handoff validation, not only in Claude and VS Code hooks.
- Surface soft rationale warnings from the backend so `record_event` and `close_slice` stay informative across all harnesses.
- Lower the shared oversize-response advisory threshold to align with the hook threshold so Codex gets the same bounded-read guidance when MCP responses grow too large.

### Slice 3: Add config-aware regression tests

- Add tests that read `.claude/settings.json`, `.github/hooks/terminal-guard.json`, `.codex/config.toml`, and `.codex/hooks.json`.
- Add backend tests for verbose-rationale warnings and oversize-rationale rejection.
- Add a `close_slice` regression proving warnings survive the compound tool path.

## Verification Strategy

- `pyenv exec python -m pytest scripts/hooks/test_guard_rationale_size.py scripts/hooks/test_slim_handoff_response.py scripts/hooks/test_filter_test_output.py scripts/hooks/test_harness_hook_configs.py -q`
- `cd packages/agent-handoff-mcp && make test-handoff`

## Consolidated Checklist

### Slice 1: Harness registration

- [x] Claude matcher config updated for current `altcontext` tool names
- [x] VS Code matcher config updated for current `altcontext` tool names
- [x] Codex hooks enabled in `.codex/config.toml`
- [x] Codex Bash post-tool hook registered in `.codex/hooks.json`

### Slice 2: Portable backend safeguards

- [x] Decision rationale hard limits enforced in shared validation
- [x] Soft rationale warnings emitted from backend responses
- [x] `close_slice` preserves nested decision warnings
- [x] Shared oversize-response advisory threshold aligned with hook guidance

### Slice 3: Regression proof

- [x] Harness config tests added
- [x] Backend rationale warning test added
- [x] Backend oversize-rationale rejection test added
- [x] `close_slice` warning propagation test added
- [x] Focused validation commands passed

## Slice Completion Summary

- Slice 1 complete: host-adapter registrations now cover Claude, VS Code, and Codex’s documented hook surface.
- Slice 2 complete: MCP-specific protections no longer depend on host-adapter interception support.
- Slice 3 complete: regression tests now fail when config wiring drifts or backend portability regresses.
