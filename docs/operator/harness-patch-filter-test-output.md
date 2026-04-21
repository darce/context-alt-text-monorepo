# Harness Operator Report — `filter-test-output.py` AttributeError + adjacent harness friction

**Date:** 2026-04-20
**Reporter:** Claude Code (MAINT-FILTER-HOOK-20260420)
**Severity:** Medium (hook crashes silently, downstream agent sees only a traceback in stderr; doesn't break tool execution but pollutes observability and confuses sibling agents)
**Status of monorepo fix:** Patched on `feature/maint-filter-hook-20260420`, regression-tested, ready to merge.

---

## 1. The actual bug (now fixed in this monorepo)

### File
`scripts/hooks/filter-test-output.py` (Claude Code PostToolUse hook, fires on every `Bash` tool call).

### Buggy lines (pre-patch, lines 270–279)
```python
command = (payload.get("tool_input") or {}).get("command", "")
if not is_test_command(command):
    print("{}")
    return

response = payload.get("tool_response") or {}
stdout = response.get("stdout", "")
if not stdout or len(stdout) < 30:
    print("{}")
    return
```

### Failure mode
`payload["tool_response"]` is **normally** a dict (`{stdout, stderr, exitCode}`), but some harness paths emit a bare **string** when the underlying Bash invocation itself failed (timeout, signal, process error). The pattern `payload.get("tool_response") or {}` only falls back to `{}` when the value is **falsy** — a non-empty string is truthy, so it falls through, and `response.get("stdout", "")` raises:

```
AttributeError: 'str' object has no attribute 'get'
```

The hook exits non-zero, Claude Code logs the traceback to stderr, and the test output is delivered uncondensed. No infinite loop, no data loss, but every failed Bash command in a configured worktree produces a noisy stack trace.

### Patch shape
Defensive `isinstance` guards on every untrusted payload field. Same guard applied symmetrically to `tool_input` and `command`:

```python
tool_input = payload.get("tool_input")
if not isinstance(tool_input, dict):
    print("{}")
    return
command = tool_input.get("command", "")
if not isinstance(command, str) or not is_test_command(command):
    print("{}")
    return

response = payload.get("tool_response")
if not isinstance(response, dict):
    print("{}")
    return
stdout = response.get("stdout") or ""
if not isinstance(stdout, str) or len(stdout) < 30:
    print("{}")
    return
```

### Regression coverage added
`scripts/hooks/test_filter_test_output.py::TestEdgeCases` now has:
- `test_string_tool_response_is_safely_ignored`
- `test_string_tool_input_is_safely_ignored`
- `test_non_string_command_is_safely_ignored`
- `test_null_stdout_is_safely_ignored`

---

## 2. Why the existing tests didn't catch it

`make_bash_payload(command, stdout, exit_code=0)` (lines 33–43) always constructs a well-typed dict for `tool_response`. The "edge case" suite covered malformed JSON on stdin and empty/short stdout, but never a **type-mismatched** field within a successfully parsed payload. The Claude Code hook contract documents the field shapes but doesn't promise they'll always be honored — defensive parsing is the caller's responsibility.

**Lesson for any harness emitting hook payloads:** if your harness ever sends a non-dict for `tool_response` or `tool_input`, every consumer hook in the wild is one truthy-fallback bug away from crashing. Either:
- Always emit the documented dict shape (preferred), or
- Add a `tool_response_kind` discriminator field so hooks can short-circuit early.

---

## 3. Adjacent harness friction observed (codex / VS Code Copilot Chat)

The user reported a stream of confused behavior from a sibling codex/VS Code agent run that interleaved with the Claude Code session. None of these are patchable from this monorepo — they live in the codex CLI / Copilot Chat harness — but the symptoms are useful for whoever owns that harness.

### 3.1 Sync wrapper swallowing pytest output

**Symptom:** Agent ran `pytest`, saw an empty or truncated capture, retried with different flags, eventually gave up and reported "tests didn't run."

**Suspected file shape (search the harness repo):**
- Anything matching `codex_test_wrapper.*`, `run_test.sh`, `pytest_wrapper.py`, `wrap_subprocess.*` in the codex harness install or a `.vscode/tasks.json` `command:` field.
- A wrapper that uses `subprocess.run(..., capture_output=True)` with no `bufsize=1` and a tight `timeout=` — long pytest sessions get killed mid-write and the captured stdout is empty.

**Fix shape:**
- Use `subprocess.Popen` with `stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, text=True` and stream line-by-line, OR
- Pipe through `unbuffer` / `script -q` / `stdbuf -oL -eL` so pytest doesn't switch to block-buffered mode when its stdout isn't a TTY.
- Drop `capture_output=True` in favor of explicit `stdout=PIPE` so partial output is preserved on timeout.

### 3.2 Persistent terminal scrollback hygiene

**Symptom:** Agent referred to test results from two invocations earlier as if they were current; reasoned about a fix based on output that no longer reflected the working tree.

**Suspected file shape:**
- VS Code Copilot Chat's "persistent terminal" feature: search the extension for `terminalIntegration`, `shellIntegration`, `getTerminalBuffer`, `readTerminalSelection`.
- The harness re-reads the entire scrollback on every turn instead of capturing the delta since the last command boundary.

**Fix shape:**
- After each command, anchor on the shell-integration command-end marker (VS Code emits `OSC 633 ; D` / `633;C` sequences) and only feed the agent the bytes between the most recent `C` and `D`.
- If shell integration isn't available, prepend `printf '\n--- CMD START %s ---\n' "$(date +%s%N)"` and slice on that sentinel.

### 3.3 Large-output capture pollution

**Symptom:** Agent's input got bloated with hundreds of `....` progress dots and `[ 47%]` lines, then started reasoning about pytest progress as if it were test failures.

**Suspected file shape:**
- The harness's "tool result" formatter — search for `formatToolResult`, `truncateToolOutput`, `MAX_TOOL_OUTPUT_BYTES`. If the truncation strategy is "head + tail" with no semantic awareness of test runners, the model sees noise.

**Fix shape:**
- Adopt the same `filter-test-output.py` pattern at the harness level: detect pytest/vitest/phpunit output and condense to a summary block before injecting into the prompt.
- Reference implementation: `scripts/hooks/filter-test-output.py` in this repo (parser dispatch + `format_summary`). It's ~300 lines, MIT-compatible, and covers the three runners we use.

### 3.4 Reasoning-text leakage into tool calls

**Symptom:** Tool-call arguments contained agent chain-of-thought ("Let me try with -x to stop on first failure...") instead of just the command string.

**Suspected file shape:**
- The harness's tool-call deserializer — search for `parseToolCall`, `extractToolArguments`, or wherever the harness splits the model's output into prose vs. structured tool calls.
- Likely cause: the model is producing a single text block that mixes reasoning and a fenced code block, and the harness greedily takes the whole block as the argument.

**Fix shape:**
- Require a structured tool-call envelope (anthropic-style `tool_use` blocks or function-call JSON) and reject free-text-with-embedded-code. If the model can only produce free text, parse with a strict regex anchored to a sentinel (`<<<COMMAND>>> ... <<<END>>>`).

---

## 4. Suggested rollout

1. Patch `filter-test-output.py` in any other repos that copied this hook (search for `_PYTEST_SUMMARY_RE` or `is_test_command` across operator-managed monorepos — this hook was copied verbatim from the agent-handoff-mcp examples folder).
2. Add the four `TestEdgeCases` regression tests to those copies.
3. For the codex/VS Code harness friction: open issues against the upstream codex CLI / Copilot Chat extension referencing sections 3.1–3.4. None of the four are reproducible from this monorepo alone — they need the harness operator's terminal/buffer/parser code to investigate.

---

## 5. Verification

```
$ cd /Users/daniel/Development/context-alt-text-monorepo-maint-filter-hook-20260420
$ python3 -m pytest scripts/hooks/test_filter_test_output.py -v
============================== 33 passed in 2.51s ==============================
```

The hook itself emitted a clean `[pytest] 33 passed (2.51s) -- all green` summary on this run, confirming the patched version is operational.
