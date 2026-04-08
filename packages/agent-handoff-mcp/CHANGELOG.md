# Changelog

All notable changes to `agent-handoff-mcp` are recorded here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file is the canonical migration notice for in-monorepo agents and
external consumers. When you see a new entry, read the **Migration** block
in that entry before relying on previously cached field shapes.

## [0.4.0] — 2026-04-07

### Added

- **Oversize-response advisory warning.** The response envelope built by
  `_envelope()` now appends an `oversize_response: ~<bytes> bytes (~<tokens>
  tokens) ...` warning to `payload["warnings"]` whenever the serialised
  payload exceeds `RESPONSE_OVERSIZE_WARN_BYTES` (default 20,000 bytes,
  ~5,000 tokens). The warning is purely advisory — the response is still
  returned in full so callers are not silently truncated — but it names the
  bounded-read levers callers should adopt for the next call:

  - `sections="identity"` for routine identity-only checks (returns just
    `active` + `limits`).
  - `sections="<comma-separated>"` to fetch only the sections you need.
  - `detail="summary"` to truncate long-form rationale, fix, and verification
    fields to 200 chars.
  - Lower `top_n_blockers`, `top_n_actions`, `top_n_decisions`, `top_n_tests`,
    `top_n_findings` to reduce row counts.
  - `fields=...` (where supported) to project specific columns.

  This is exposed via the new `RESPONSE_OVERSIZE_WARN_BYTES` constant in
  `shared_primitives.py`. Callers that already use bounded-read parameters
  will never see the warning. The threshold is tunable but should remain a
  soft cap — hard truncation belongs at the caller's discretion, not the
  envelope's.

  Motivated by AHMCP-14: a routine `get_handoff_state(top_n_decisions=10,
  detail="full")` call against AOMCP-3 returned ~17.6k tokens because
  slice-complete decision rationales dominate the payload, and AHMCP-7 /
  AHMCP-10 wire-format optimizations only attack the wrapper, not the
  rationale text itself. The warning is the cheapest possible nudge toward
  the documented narrowing levers.

### Migration — what callers must do

- **Nothing required.** This is an additive change. Existing callers will
  start seeing an extra warning entry on oversize responses; the response
  body is unchanged.
- If you were already filtering `payload["warnings"]` for `context_drift:`
  prefixes, add `oversize_response:` to your filter list to surface the new
  advisory.
- Treat the advisory as a soft signal: **the next call** should be narrowed,
  not the current one. Do not retry the same call expecting different output.

### Companion enforcement (outside the package)

This release also introduces an out-of-package PreToolUse hook —
`scripts/hooks/guard-task-plan-findings.py` in the monorepo root — that
rejects any Edit/Write attempting to paste a review-finding list into a
task plan, epic, or planning document. The hook is wired into both
`.claude/settings.json` and `.github/hooks/terminal-guard.json`, runs in
`make check-all` via `make lint-task-plans`, and exposes a `--scan-staged`
mode for opt-in `git pre-commit` integration (the monorepo does not ship
a checked-in `.git/hooks/pre-commit`; teams that want commit-time
enforcement should wire it themselves via `core.hooksPath` or a tool like
`pre-commit`). Review findings live in `agent-handoff-mcp` and are
recorded with `review_findings(review={"operation":"record"|"batch_record",
...})`; pasting them inline duplicates the source of truth and escapes the
pre-merge gate.

## [0.3.0] — 2026-04-08

### Changed (BREAKING — wire format)

- **MCP tool responses are now native JSON objects, not JSON strings.**
  Every handoff-mcp tool handler is annotated `-> dict` and returns a real
  Python dict via `_envelope()` / `_json_response()`. FastMCP serialises
  the dict exactly once on the wire instead of running a
  `json.dumps -> structured_content={"result": "<escaped JSON>"} -> json.loads`
  round trip.

  **Old wire payload (≤0.2.x):**
  ```json
  {"structured_content": {"result": "{\"ok\": true, \"schema_version\": 2, \"data\": {...}}"}}
  ```

  **New wire payload (≥0.3.0):**
  ```json
  {"structured_content": {"ok": true, "schema_version": 2, "data": {...}}}
  ```

  The envelope **fields** (`ok`, `schema_version`, `tool`, `scope`, `data`,
  `mutation`, `artifacts`, `warnings`, `task_ref`) are unchanged. The
  envelope `schema_version` stays at `2` because the field set and contract
  have not moved — only the wire format went from JSON-string-inside-JSON
  to native nested object.

  Per-call wire savings range from ~9.5% on large structured payloads to
  ~24% on small ones, depending on how many `"` and `\n` characters the
  legacy form had to escape.

### Migration — what callers must do

- **Use the canonical access pattern** (this was always documented in the
  README and `docs/guides/token-efficient-usage.md`, but is now mandatory):
  ```python
  result = mcp_tool.call(...)        # in-process or via FastMCP client
  active = result["data"]["active"]  # canonical
  # NOT result["active"] — the legacy top-level mirror was removed in 0.3.0
  # and never returns
  ```
- **Stop wrapping handler results in `json.loads(...)`.** Pre-0.3.0 callers
  did `parsed = json.loads(handoff_tool(...))`. Post-0.3.0 the call
  returns a dict directly:
  ```python
  result = handoff_tool(...)         # already a dict
  if not result.get("ok"):
      ...
  ```
  In-monorepo callers under `agent-orchestrator-mcp` and `scripts/` were
  updated in lockstep with this release. The four private `_json_load`
  helpers in `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/`
  now accept either `str` or `dict` so caller sites need not change.
- **External tools that read `result.content[0].text` and then
  `json.loads()` the inner string** must instead read
  `result.structured_content` directly. The `text` field still exists for
  backward compatibility with MCP clients that only consume the text
  channel, but the canonical payload is now in `structured_content`.
- **Tests** that build a flat-access dict via a local helper like
  `_parse_response(raw)` should accept both `str` (CLI stdout capture)
  and `dict` (in-process handler call) input. Eight in-tree test files
  use the smart pattern; copy the same idiom for new tests:
  ```python
  def _parse(raw: str | dict) -> dict:
      result = raw if isinstance(raw, dict) else json.loads(raw)
      ...
  ```

### Removed

- The `_make_dict_wrapper` shim in `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`
  is gone. Earlier versions wrapped string-returning handlers at FastMCP
  registration time to convince it the result was a dict; the wrapper is no
  longer needed because handlers return dicts natively.
- The `_flatten_v2` helper in `core.py` is gone. Compound tools
  (`load_session`, `close_slice`) now read inner-tool results from the
  canonical `result["data"][...]` path directly with no merge step.
- The legacy top-level mirror introduced by AHMCP-3 (where every `data`
  field was duplicated at the envelope root) was removed by AHMCP-7
  Slice 2; AHMCP-10 finishes the cleanup by deleting all the bridging
  shims that depended on it.

### History notice

This release closes out the deferred half of AHMCP-7 ("Response Envelope
Token Optimization"). AHMCP-7 documented Slice 3 ("Dict Return at MCP
Boundary") as complete in late March, but the work landed as a
backward-compat shim (`_make_dict_wrapper`) instead of a real dict-return
end to end. AHMCP-10 (this release) removes the shim and flips every
handler to its honest return type. There is no deprecation window: agents
running against `agent-handoff-mcp ≥0.3.0` see the new wire format
immediately, and any consumer that hardcodes the legacy
`structured_content.result` shape will break on first call. The
in-monorepo orchestrator package, scripts, and tests were all migrated in
the same commit (`406dbae3` followed by an amend that includes this
changelog entry and the `_runtime_pythonpath` annotation revert from
branch-review finding `AHMCP-10-BR-01`).

## [0.2.0] — 2026-03-09

Initial published release. v2 envelope, discriminated tool surface
(AHMCP-6), SQLite-backed handoff state store, FastMCP stdio transport.
