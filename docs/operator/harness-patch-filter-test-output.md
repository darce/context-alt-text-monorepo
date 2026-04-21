# Harness Operator Report — `filter-test-output.py` AttributeError + adjacent harness friction

**Date:** 2026-04-20
**Reporter:** Claude Code, MCP task `MAINT-FILTER-HOOK-20260420`
**Severity:** Medium — hook crashes don't break tool execution but pollute observability and confuse sibling agents.

---

## 0. Scope split (read this first)

This document mixes two scopes. Treat them as separate work surfaces:

| § | Scope | Owning repo | Owning task | Status | Implementation-ready? |
|---|-------|-------------|-------------|--------|-----------------------|
| 1 | **In-repo bug fix** — defensive type check in `scripts/hooks/filter-test-output.py` | This monorepo (`context-alt-text-monorepo`) | `MAINT-FILTER-HOOK-20260420` | Patched on `feature/maint-filter-hook-20260420` @ `ac881abeeda6b513340a0ba88b897d4c0991fde5`. **`main` still ships the unsafe code.** | **Yes** — merge prerequisite documented in §1.4. |
| 3 | **Upstream harness backlog** — four observed friction symptoms in the codex CLI / VS Code Copilot Chat harness | Upstream (codex CLI, Copilot Chat extension — **not this monorepo**) | None — needs upstream issue per item | Hypotheses only. None are reproducible from this monorepo. | **No** — see §3 for each item's exit criteria; file as upstream issues before assigning to an implementor. |

If you are an implementor working in this monorepo, only §1 is yours.

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
sed -n '270,280p' scripts/hooks/filter-test-output.py
# expected on main:
#   command = (payload.get("tool_input") or {}).get("command", "")
#   ...
#   response = payload.get("tool_response") or {}
#   stdout = response.get("stdout", "")
```

The four regression tests in `TestEdgeCases` (string `tool_response`, string `tool_input`, non-string `command`, null `stdout`) **do not exist on `main`** — `test_filter_test_output.py` ends at line 329 with `test_empty_stdout`.

### 1.3 The bug

`payload["tool_response"]` is normally a dict (`{stdout, stderr, exitCode}`), but some harness paths emit a bare **string** when the underlying Bash invocation itself failed (timeout, signal, process error). The pattern `payload.get("tool_response") or {}` only falls back to `{}` when the value is **falsy** — a non-empty string is truthy, so it falls through, and `response.get("stdout", "")` raises:

```
AttributeError: 'str' object has no attribute 'get'
```

The hook exits non-zero, Claude Code logs the traceback to stderr, and the test output is delivered uncondensed. No infinite loop, no data loss — but every failed Bash command in a configured worktree produces a noisy stack trace.

### 1.4 Action — what an implementor must do

1. **Cherry-pick or merge** `feature/maint-filter-hook-20260420` (commit `ac881abeeda6b513340a0ba88b897d4c0991fde5`) into `main` via the standard pre-merge gate (`handoff_close_check(enforce=True)` against `MAINT-FILTER-HOOK-20260420`).
2. **Verify** the patched code on `main`:
   ```bash
   sed -n '270,290p' scripts/hooks/filter-test-output.py
   # expected post-merge: explicit isinstance() guards on tool_input,
   # tool_response, command, stdout.
   ```
3. **Run regression tests on `main` post-merge:**
   ```bash
   python3 -m pytest scripts/hooks/test_filter_test_output.py -v
   # expected: 33 passed (4 of which are the new TestEdgeCases entries).
   ```

No work is required outside cherry-picking and verifying — the patch and tests are already on the feature branch.

### 1.5 Patch shape (reference)

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

### 1.6 Completion proof

Recorded against `MAINT-FILTER-HOOK-20260420`:

- Decision `#2161` — `claude_fix_filter_test_output_typecheck` (rationale, changed_files, commit_sha pinned).
- Verification: `python3 -m pytest scripts/hooks/test_filter_test_output.py -v` → 33 passed in 2.51s on the feature branch.
- The patched hook itself emitted a clean `[pytest] 33 passed (2.51s) -- all green` summary on the verification run, confirming the fix is operational on the feature branch.

After cherry-picking, the implementor must record a `test_result` event against `MAINT-FILTER-HOOK-20260420` for the post-merge `main`-tip pytest run before closing the task.

---

## 2. Why the existing tests didn't catch the bug

`make_bash_payload(command, stdout, exit_code=0)` (lines 33–43) always constructed a well-typed dict for `tool_response`. The "edge case" suite covered malformed JSON on stdin and empty/short stdout but never a **type-mismatched** field within a successfully parsed payload. The Claude Code hook contract documents the field shapes but doesn't promise they'll always be honored — defensive parsing is the caller's responsibility.

This is captured as engineering rationale, not a separate work item. The four new `TestEdgeCases` entries on `feature/maint-filter-hook-20260420` close the gap; no further test work is needed in this monorepo.

---

## 3. Upstream backlog — codex / VS Code Copilot Chat harness

> **None of these are actionable inside this monorepo.** All four are hypotheses based on observed sibling-agent behavior; the suspected root causes live in the codex CLI install and the VS Code Copilot Chat extension. File each as a separate upstream issue against the owning repo before assigning to an implementor. Until reproducers exist, treat them as triage tickets, not implementation tickets.
>
> **Owning repo:** unknown — depends on which extension/CLI the operator runs. Candidates: `microsoft/vscode-copilot-chat`, the codex CLI distribution the operator installs. The operator should attach the correct repo when filing.
>
> **Confidence:** Hypothesis only. The "suspected file shape" sections below are search hints, not located code.

Each subsection follows the same structure: **observed symptom → suspected cause (hypothesis) → reproducer needed → exit criteria for the upstream issue.**

### 3.1 Sync wrapper swallowing pytest output

- **Observed symptom (this monorepo):** Sibling codex agent ran `pytest`, saw an empty or truncated capture, retried with different flags, eventually reported "tests didn't run."
- **Suspected cause (hypothesis):** A wrapper using `subprocess.run(..., capture_output=True, timeout=...)` with no line buffering. Long pytest sessions get killed mid-write and the captured stdout is empty.
- **Search hints for the upstream repo:** `codex_test_wrapper.*`, `run_test.sh`, `pytest_wrapper.py`, `wrap_subprocess.*`, `.vscode/tasks.json` `command:` fields.
- **Reproducer needed before this is implementation-ready:** A minimal harness invocation that runs a long-output command (`for i in $(seq 1 10000); do echo $i; done; sleep 5; echo done`) under the suspected wrapper and demonstrates that the captured output is empty or truncated when the wrapper times out.
- **Exit criteria for the upstream issue:** Either (a) the wrapper streams stdout line-by-line via `Popen(..., bufsize=1, text=True)` with `unbuffer` / `script -q` / `stdbuf -oL -eL` so partial output is preserved on timeout, or (b) the suspected wrapper is shown not to exist and the symptom is rerouted to a different layer.

### 3.2 Persistent terminal scrollback hygiene

- **Observed symptom (this monorepo):** Sibling agent referred to test results from two invocations earlier as if they were current; reasoned about a fix based on output that no longer reflected the working tree.
- **Suspected cause (hypothesis):** VS Code Copilot Chat's persistent-terminal feature re-reads the entire scrollback on every turn instead of capturing the delta since the last command boundary.
- **Search hints for the upstream repo:** `terminalIntegration`, `shellIntegration`, `getTerminalBuffer`, `readTerminalSelection` in the Copilot Chat extension source.
- **Reproducer needed before this is implementation-ready:** A two-turn agent transcript where turn 1 runs command `A`, turn 2 runs command `B`, and turn 2's tool-result payload contains text from `A` that should have been bounded out by command-end markers.
- **Exit criteria for the upstream issue:** The harness anchors on the shell-integration command-end marker (VS Code emits OSC 633 `;D` / `;C` sequences) and only feeds the agent the bytes between the most recent `C` and `D`. Fallback: prepend `printf '\n--- CMD START %s ---\n' "$(date +%s%N)"` and slice on that sentinel.

### 3.3 Large-output capture pollution

- **Observed symptom (this monorepo):** Sibling agent's input got bloated with hundreds of `....` progress dots and `[ 47%]` lines, then started reasoning about pytest progress as if it were test failures.
- **Suspected cause (hypothesis):** The harness's tool-result formatter uses a head+tail truncation strategy with no semantic awareness of test runners.
- **Search hints for the upstream repo:** `formatToolResult`, `truncateToolOutput`, `MAX_TOOL_OUTPUT_BYTES`.
- **Reproducer needed before this is implementation-ready:** A captured tool-result payload from a real pytest run that demonstrates the head+tail truncation produced semantically meaningless content (e.g. only progress dots, no failure summary).
- **Exit criteria for the upstream issue:** The harness adopts a runner-aware summarization step before injecting tool output into the prompt. Reference implementation already in this monorepo: `scripts/hooks/filter-test-output.py` (parser dispatch + `format_summary`, ~300 lines, MIT-compatible, covers pytest/vitest/phpunit). Whether to literally port that code or reimplement is the upstream owner's call.

### 3.4 Reasoning-text leakage into tool-call arguments

- **Observed symptom (this monorepo):** Tool-call arguments contained agent chain-of-thought ("Let me try with -x to stop on first failure...") instead of just the command string.
- **Suspected cause (hypothesis):** The harness's tool-call deserializer splits the model's output into prose vs. structured tool calls greedily, taking a free-text-with-embedded-code block as the entire argument.
- **Search hints for the upstream repo:** `parseToolCall`, `extractToolArguments`, the tool-call splitting layer.
- **Reproducer needed before this is implementation-ready:** A captured model output where reasoning text and a fenced code block coexist in a single block, plus the resulting tool-call argument that the harness extracted. Demonstrate the whole block was passed as the argument.
- **Exit criteria for the upstream issue:** The harness either (a) requires structured tool-call envelopes (Anthropic-style `tool_use` blocks or function-call JSON) and rejects free-text-with-embedded-code, or (b) parses with a strict regex anchored to a sentinel (`<<<COMMAND>>> ... <<<END>>>`).

---

## 4. Verification (in-repo §1 only)

```
$ cd /Users/daniel/Development/context-alt-text-monorepo-maint-filter-hook-20260420
$ python3 -m pytest scripts/hooks/test_filter_test_output.py -v
============================== 33 passed in 2.51s ==============================
```

The patched hook also emitted a clean `[pytest] 33 passed (2.51s) -- all green` summary on this run, confirming the patched version is operational on the feature branch. **This is not yet true on `main`** — see §1.4.

§3 has no in-repo verification. Each upstream issue must define its own reproducer before being assignable.
