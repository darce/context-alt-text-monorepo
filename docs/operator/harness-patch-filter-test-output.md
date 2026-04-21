<<<<<<< HEAD
# Harness Operator Report — repo-local VS Code harness stutter mitigation (`filter-test-output.py` crash + context-efficiency hooks)

**Date:** 2026-04-20
**Reporter:** Claude Code, MCP task `MAINT-FILTER-HOOK-20260420`
**Severity:** Medium — the repo cannot fix VS Code host-side UI stalls directly, but it can remove two local amplifiers of harness stutter: noisy Bash/test output and oversized handoff reads.

---

## 0. Scope split (read this first)

This document mixes three scopes. Treat them as separate work surfaces:

| § | Scope | Owning repo | Owning task | Status | Implementation-ready? |
|---|-------|-------------|-------------|--------|-----------------------|
| 1 | **In-repo bug fix** — defensive type check in `scripts/hooks/filter-test-output.py` | This monorepo (`context-alt-text-monorepo`) | `MAINT-FILTER-HOOK-20260420` | Patched on `feature/maint-filter-hook-20260420` @ `ac881abeeda6b513340a0ba88b897d4c0991fde5`. **`main` still ships the unsafe code.** | **Yes** — merge prerequisite documented in §1.4. |
| 2 | **In-repo mitigation path** — use the existing VS Code PostToolUse hooks to cut context bloat from test output and handoff reads | This monorepo (`context-alt-text-monorepo`) | `MAINT-FILTER-HOOK-20260420` for the crash fix; follow-on tuning can stay in maintenance scope | Partially shipped on `main`: `.github/hooks/terminal-guard.json` already wires `filter-test-output.py` for `Bash` and `slim-handoff-response.py` for `get_handoff_state` / `load_session` / `render_handoff`. The `filter-test-output.py` crash fix is the missing stabilization step. | **Yes** — actionable now; see §2. |
| 4 | **Upstream harness backlog** — four observed friction symptoms in the codex CLI / VS Code Copilot Chat harness | Upstream (codex CLI, Copilot Chat extension — **not this monorepo**) | None — needs upstream issue per item | Hypotheses only. None are reproducible from this monorepo. | **No** — see §4 for each item's exit criteria; file as upstream issues before assigning to an implementor. |

If you are an implementor working in this monorepo and your goal is to make the VS Code harness materially more usable today, §§1-2 are yours. Do not wait on §4 before shipping the repo-local mitigations.

---

## 1. In-repo work item — defensive type-check in `filter-test-output.py`

### 1.1 Identifiers

- **Owning task:** `MAINT-FILTER-HOOK-20260420`
- **Owning branch:** `feature/maint-filter-hook-20260420`
- **Tip commit at time of writing:** `ac881abeeda6b513340a0ba88b897d4c0991fde5`
- **Target merge branch:** `main`
- **Files in scope:** `scripts/hooks/filter-test-output.py`, `scripts/hooks/test_filter_test_output.py`

### 1.2 Current state of `main`

`main` (`94a1836b` at time of writing) **still contains the unsafe code**. Verify before acting:

```bash
cd "${REPO_ROOT:-$PWD}" && sed -n '270,280p' scripts/hooks/filter-test-output.py
# expected on main:
#   command = (payload.get("tool_input") or {}).get("command", "")
#   ...
#   response = payload.get("tool_response") or {}
#   stdout = response.get("stdout", "")
```

The four regression tests in `TestEdgeCases` (string `tool_response`, string `tool_input`, non-string `command`, null `stdout`) **do not exist on `main`** — `test_filter_test_output.py` ends at line 329 with `test_empty_stdout`.

Separately, `main` already wires the two relevant VS Code/Copilot PostToolUse hooks in `.github/hooks/terminal-guard.json`:

- `python3 scripts/hooks/filter-test-output.py` after every `Bash` tool call
- `python3 scripts/hooks/slim-handoff-response.py` after `get_handoff_state`, `load_session`, and `render_handoff`

That means this repo already has a local mechanism to reduce context bloat during tool calling and context acquisition. The missing piece on `main` is the `filter-test-output.py` crash fix, which currently causes the noisy stderr traceback exactly when a Bash call fails.

### 1.3 The bug

`payload["tool_response"]` is normally a dict (`{stdout, stderr, exitCode}`), but some harness paths emit a bare **string** when the underlying Bash invocation itself failed (timeout, signal, process error). The pattern `payload.get("tool_response") or {}` only falls back to `{}` when the value is **falsy** — a non-empty string is truthy, so it falls through, and `response.get("stdout", "")` raises:
=======
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
>>>>>>> ac881abe (fix(hooks): defensive type-check in filter-test-output for non-dict tool_response)

```
AttributeError: 'str' object has no attribute 'get'
```

<<<<<<< HEAD
The hook exits non-zero, Claude Code logs the traceback to stderr, and the test output is delivered uncondensed. No infinite loop, no data loss — but every failed Bash command in a configured worktree produces a noisy stack trace.

### 1.4 Action — what an implementor must do

1. **Cherry-pick or merge** `feature/maint-filter-hook-20260420` (commit `ac881abeeda6b513340a0ba88b897d4c0991fde5`) into `main` via the standard pre-merge gate (`handoff_close_check(enforce=True)` against `MAINT-FILTER-HOOK-20260420`).
2. **Verify** the patched code on `main`:
   ```bash
    cd "${REPO_ROOT:-$PWD}" && sed -n '270,290p' scripts/hooks/filter-test-output.py
   # expected post-merge: explicit isinstance() guards on tool_input,
   # tool_response, command, stdout.
   ```
3. **Run regression tests on `main` post-merge:**
   ```bash
    cd "${REPO_ROOT:-$PWD}" && pyenv exec python -m pytest scripts/hooks/test_filter_test_output.py -v
   # expected: 33 passed (4 of which are the new TestEdgeCases entries).
   ```

No work is required outside cherry-picking and verifying — the patch and tests are already on the feature branch.

### 1.5 Patch shape (reference)
=======
The hook exits non-zero, Claude Code logs the traceback to stderr, and the test output is delivered uncondensed. No infinite loop, no data loss, but every failed Bash command in a configured worktree produces a noisy stack trace.

### Patch shape
Defensive `isinstance` guards on every untrusted payload field. Same guard applied symmetrically to `tool_input` and `command`:
>>>>>>> ac881abe (fix(hooks): defensive type-check in filter-test-output for non-dict tool_response)

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

<<<<<<< HEAD
### 1.6 Completion proof

Recorded against `MAINT-FILTER-HOOK-20260420`:

- Decision `#2161` — `claude_fix_filter_test_output_typecheck` (rationale, changed_files, commit_sha pinned).
- Verification: `cd "${REPO_ROOT:-$PWD}" && pyenv exec python -m pytest scripts/hooks/test_filter_test_output.py -v` → 33 passed in 2.51s on the feature branch.
- The patched hook itself emitted a clean `[pytest] 33 passed (2.51s) -- all green` summary on the verification run, confirming the fix is operational on the feature branch.

After cherry-picking, the implementor must record a `test_result` event against `MAINT-FILTER-HOOK-20260420` for the post-merge `main`-tip pytest run before closing the task.

---

## 2. Repo-local path to reduce VS Code harness stutter now

If the primary goal is to reduce the current VS Code/Copilot harness stutter in this monorepo, ship the repo-local mitigation path in this order:

1. **Stabilize `filter-test-output.py` on `main`.** The hook already runs after every `Bash` tool call in the VS Code hook surface. When it crashes on a string `tool_response`, the model gets the raw failing command output plus a traceback instead of the compact test summary. Fixing the type check does not solve host-side UI latency, but it does remove a local source of noisy tool-call turns.
2. **Keep `slim-handoff-response.py` active for state reads.** `main` already runs it after `get_handoff_state`, `load_session`, and `render_handoff`, which are the repo-local context-acquisition paths most likely to balloon token usage. That hook does not shrink the current payload in place; it steers the *next* call toward bounded reads (`sections="identity"`, `detail="summary"`, lower `top_n_*`).
3. **Treat bounded reads as part of the fix, not optional advice.** Once the operator sees the oversize-response advisory, the next state read should be narrowed immediately. Repeating full `load_session` / `get_handoff_state` calls in VS Code defeats the mitigation and recreates the stutter symptom even if the hooks are healthy.

This repo-local path is the fastest lever available because it requires no VS Code extension changes and is already wired into `.github/hooks/terminal-guard.json`. If these mitigations are in place and the harness still stutters badly, *then* escalate to the upstream backlog in §4.

### 2.1 Success criteria for the repo-local mitigation path

- Failed or timed-out Bash/test commands no longer produce `AttributeError: 'str' object has no attribute 'get'` from `filter-test-output.py`.
- Green and red test runs continue to inject a compact summary via `hookSpecificOutput.additionalContext` instead of forcing the model to reason from raw progress noise alone.
- Oversized handoff reads trigger the `slim-handoff-response.py` advisory, and subsequent reads use bounded parameters instead of repeating full-history payloads.
- Operators understand that this repo can reduce prompt/context pressure, but cannot by itself fix host-side rendering or tool-call deserialization bugs in the VS Code extension.

## 3. Why the existing tests didn't catch the bug

`make_bash_payload(command, stdout, exit_code=0)` (lines 33–43) always constructed a well-typed dict for `tool_response`. The "edge case" suite covered malformed JSON on stdin and empty/short stdout but never a **type-mismatched** field within a successfully parsed payload. The Claude Code hook contract documents the field shapes but doesn't promise they'll always be honored — defensive parsing is the caller's responsibility.

This is captured as engineering rationale, not a separate work item. The four new `TestEdgeCases` entries on `feature/maint-filter-hook-20260420` close the gap; no further test work is needed in this monorepo.

---

## 4. Upstream backlog — codex / VS Code Copilot Chat harness

> **None of these are actionable inside this monorepo.** All four are hypotheses based on observed sibling-agent behavior; the suspected root causes live in the codex CLI install and the VS Code Copilot Chat extension. File each as a separate upstream issue against the owning repo before assigning to an implementor. Until reproducers exist, treat them as triage tickets, not implementation tickets.
>
> **Priority rule:** ship §§1-2 first. The upstream items matter only after the repo-local mitigation path is healthy and the harness remains materially unusable.
>
> **Owning repo:** unknown — depends on which extension/CLI the operator runs. Candidates: `microsoft/vscode-copilot-chat`, the codex CLI distribution the operator installs. The operator should attach the correct repo when filing.
>
> **Confidence:** Hypothesis only. The "suspected file shape" sections below are search hints, not located code.

Each subsection follows the same structure: **observed symptom → suspected cause (hypothesis) → reproducer needed → exit criteria for the upstream issue.**

### 4.1 Sync wrapper swallowing pytest output

- **Observed symptom (this monorepo):** Sibling codex agent ran `pytest`, saw an empty or truncated capture, retried with different flags, eventually reported "tests didn't run."
- **Suspected cause (hypothesis):** A wrapper using `subprocess.run(..., capture_output=True, timeout=...)` with no line buffering. Long pytest sessions get killed mid-write and the captured stdout is empty.
- **Search hints for the upstream repo:** `codex_test_wrapper.*`, `run_test.sh`, `pytest_wrapper.py`, `wrap_subprocess.*`, `.vscode/tasks.json` `command:` fields.
- **Reproducer needed before this is implementation-ready:** A minimal harness invocation that runs a long-output command (`for i in $(seq 1 10000); do echo $i; done; sleep 5; echo done`) under the suspected wrapper and demonstrates that the captured output is empty or truncated when the wrapper times out.
- **Exit criteria for the upstream issue:** Either (a) the wrapper streams stdout line-by-line via `Popen(..., bufsize=1, text=True)` with `unbuffer` / `script -q` / `stdbuf -oL -eL` so partial output is preserved on timeout, or (b) the suspected wrapper is shown not to exist and the symptom is rerouted to a different layer.

### 4.2 Persistent terminal scrollback hygiene

- **Observed symptom (this monorepo):** Sibling agent referred to test results from two invocations earlier as if they were current; reasoned about a fix based on output that no longer reflected the working tree.
- **Suspected cause (hypothesis):** VS Code Copilot Chat's persistent-terminal feature re-reads the entire scrollback on every turn instead of capturing the delta since the last command boundary.
- **Search hints for the upstream repo:** `terminalIntegration`, `shellIntegration`, `getTerminalBuffer`, `readTerminalSelection` in the Copilot Chat extension source.
- **Reproducer needed before this is implementation-ready:** A two-turn agent transcript where turn 1 runs command `A`, turn 2 runs command `B`, and turn 2's tool-result payload contains text from `A` that should have been bounded out by command-end markers.
- **Exit criteria for the upstream issue:** The harness anchors on the shell-integration command-end marker (VS Code emits OSC 633 `;D` / `;C` sequences) and only feeds the agent the bytes between the most recent `C` and `D`. Fallback: prepend `printf '\n--- CMD START %s ---\n' "$(date +%s%N)"` and slice on that sentinel.

### 4.3 Large-output capture pollution

- **Observed symptom (this monorepo):** Sibling agent's input got bloated with hundreds of `....` progress dots and `[ 47%]` lines, then started reasoning about pytest progress as if it were test failures.
- **Suspected cause (hypothesis):** The harness's tool-result formatter uses a head+tail truncation strategy with no semantic awareness of test runners.
- **Search hints for the upstream repo:** `formatToolResult`, `truncateToolOutput`, `MAX_TOOL_OUTPUT_BYTES`.
- **Reproducer needed before this is implementation-ready:** A captured tool-result payload from a real pytest run that demonstrates the head+tail truncation produced semantically meaningless content (e.g. only progress dots, no failure summary).
- **Exit criteria for the upstream issue:** The harness adopts a runner-aware summarization step before injecting tool output into the prompt. Reference implementation already in this monorepo: `scripts/hooks/filter-test-output.py` (parser dispatch + `format_summary`, ~300 lines, MIT-compatible, covers pytest/vitest/phpunit). Whether to literally port that code or reimplement is the upstream owner's call.

### 4.4 Reasoning-text leakage into tool-call arguments

- **Observed symptom (this monorepo):** Tool-call arguments contained agent chain-of-thought ("Let me try with -x to stop on first failure...") instead of just the command string.
- **Suspected cause (hypothesis):** The harness's tool-call deserializer splits the model's output into prose vs. structured tool calls greedily, taking a free-text-with-embedded-code block as the entire argument.
- **Search hints for the upstream repo:** `parseToolCall`, `extractToolArguments`, the tool-call splitting layer.
- **Reproducer needed before this is implementation-ready:** A captured model output where reasoning text and a fenced code block coexist in a single block, plus the resulting tool-call argument that the harness extracted. Demonstrate the whole block was passed as the argument.
- **Exit criteria for the upstream issue:** The harness either (a) requires structured tool-call envelopes (Anthropic-style `tool_use` blocks or function-call JSON) and rejects free-text-with-embedded-code, or (b) parses with a strict regex anchored to a sentinel (`<<<COMMAND>>> ... <<<END>>>`).

---

## 5. Verification (in-repo §§1-2 only)

```
$ cd "${REPO_ROOT:-$PWD}"
$ pyenv exec python -m pytest scripts/hooks/test_filter_test_output.py -v
============================== 33 passed in 2.51s ==============================
```

The patched hook also emitted a clean `[pytest] 33 passed (2.51s) -- all green` summary on this run, confirming the patched version is operational on the feature branch. **This is not yet true on `main`** — see §1.4.

For the broader VS Code harness-stutter goal, the repo-local verification surface is:

- `filter-test-output.py` no longer crashes on malformed Bash payload shapes
- `.github/hooks/terminal-guard.json` still wires `filter-test-output.py` and `slim-handoff-response.py` on the VS Code surface
- operators use bounded read levers after the slim-response advisory fires

§4 has no in-repo verification. Each upstream issue must define its own reproducer before being assignable.
=======
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
>>>>>>> ac881abe (fix(hooks): defensive type-check in filter-test-output for non-dict tool_response)
