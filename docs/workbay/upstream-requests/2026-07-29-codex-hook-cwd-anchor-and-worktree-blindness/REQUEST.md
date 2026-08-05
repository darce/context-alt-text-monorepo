# REQUEST: Codex hook surface — cwd-relative commands block sessions, worktrees are ignored, coherence check false-positives the fix

- **Date**: 2026-07-29
- **Consumer**: `context-alt-text-monorepo`
- **Component**: `workbay` hook renderer (`_guard_wrap.wrap_guard_command`), `workbay_bootstrap.coherence`, `scripts/hooks/_run_guard.py`, `scripts/hooks/coherence-self-check.py`
- **Severity**: high — a codex session launched with `--cd <subdir>` is hard-blocked on every Edit/Write/Bash/MCP-write
- **Local handoff task**: `MAINT-codex-hook-cwd-20260729` (findings BR-01…BR-07)

## Summary

Three defects on the same seam. The first is fully diagnosed and locally worked around
in rendered output; the workaround reverts on the next re-render, so the durable fix is
upstream.

## 1. Cwd-relative hook commands block, they do not fail open

`wrap_guard_command()` renders the wrapper path with "the SAME per-harness anchor the
command already uses (`$CLAUDE_PROJECT_DIR` for Claude, `${GROK_WORKSPACE_ROOT}` for
Grok, **relative for VS Code/Codex whose runners spawn hooks with cwd=workspace root**)".
`_run_guard.py`'s docstring states the same premise.

**The premise is false.** `codex exec --cd <subdir>` spawns hooks with
`cwd == <subdir>`, not the workspace root. Codex is routinely launched this way when a
review or fix pass is scoped to one app in a monorepo.

The failure is not graceful. `_run_guard.py` is designed to fail **open** when a
*handler* is missing (exit 0 + `hook_infra_failure` telemetry) — but the wrapper's *own*
path is resolved by the shell, before any of that logic can run. A missing wrapper is
`python3: can't open file …` → **exit 2 → BLOCK**.

Reproduced from `apps/prototype-wp-alt-context`:

```
python3: can't open file '/…/apps/prototype-wp-alt-context/scripts/hooks/_run_guard.py'
exit 2
PostToolUse Blocked
```

Observed live: a codex review arm could not write its report through the patch interface,
and every MCP write in the session was rejected.

**Requested fix.** For harnesses with no workspace-root env anchor, anchor at the git
toplevel instead of emitting a relative path. `.codex/config.toml`'s own MCP launchers
already use exactly this idiom, so it is established in the codebase:

```sh
sh -c 'root="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"; exec python3 "$root/scripts/hooks/_run_guard.py" "$root/<handler>"' sh
```

Pass the handler absolute too — `_resolve_handler()` honours `os.path.isabs`, and a
relative handler under the wrong cwd fails **open** (exit 0), silently skipping the guard.
That silent-skip is the quieter half of this bug: a hook that never runs looks identical
to a hook that passed.

Also correct the docstrings in `_guard_wrap.py` and `_run_guard.py` that assert
`cwd == workspace root` for Codex/VS Code. They are the reason the defect was designed in.

## 2. Codex ignores linked git worktrees

Codex loads `.codex/` from the **root** repo, not from the linked worktree it is pointed
at. Proven empirically: with the worktree's `.codex/hooks.json` moved aside, 16 hook lines
still fired, sourced from the root checkout.

Consequences for a worktree-per-task workflow:

- Fixing the rendered hook surface *on the feature branch* is inert. The fix only takes
  effect once merged to the branch the root worktree has checked out.
- Every guard a codex session runs is the `main` version. A branch that **adds** a guard
  gets no codex enforcement until merge — the harness is weakest exactly where new rules
  are being introduced.

**Requested fix.** Either resolve `.codex/` from the session's actual working root, or
document the limitation prominently so consumers stop rendering per-worktree codex configs
that cannot take effect. Rendering an inert config is worse than rendering none.

## 3. `coherence-self-check.py` false-positives the correct form — and tells agents to undo it

`_command_path_tokens()` `shlex.split`s the command and flags any token containing `/` as
a path. For the anchored `sh -c '<script>'` form the **entire inner script** is one token,
so every correctly-anchored command is reported dangling. This repo now emits that warning
into **every session's** `additionalContext` for all 14 codex hooks.

The advisory text is the actively harmful part:

> "run `make check-harness-coherence` (or `make doctor`) and **re-render/reinstall the hook
> surfaces**"

An agent that follows it re-renders the cwd-relative form and reverts the fix for §1. The
warning also claims "a missing handler is fail-open at runtime" — true for handlers, false
for the wrapper, which is what §1 is about.

**Requested fix.** Recurse into `-c` script arguments; strip `$(…)` command substitutions
and `VAR=` assignment tokens before classifying. Sketch:

```python
_SHELL_WORDS   = frozenset({"sh", "bash", "zsh", "dash"})
_CMD_SUBST_RE  = re.compile(r"\$\((?:[^()]|\([^()]*\))*\)")
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# in _command_path_tokens(command, depth=0):
#   command = _CMD_SUBST_RE.sub("", command)
#   on `<shell> -c <script>`: recurse into <script> at depth+1 (cap at 2)
#   skip tokens matching _ASSIGNMENT_RE
#   existing _ENV_ANCHOR_RE strip already turns "$root/scripts/…" into a resolvable path
```

The same tokenizer lives in `workbay_bootstrap.coherence` behind
`make check-harness-coherence`, so fix both or share one implementation. Note the local
`make check-harness-coherence` target does not exist in this consumer and
`workbay_bootstrap` is not importable here, so the advisory names a command the reader
cannot run.

## 4. Harness guard parity gap (lower priority)

`.claude/settings.json` registers a `guard-review-finding-resolve.py` PreToolUse hook on
`review_findings` writes; the rendered codex surface had no equivalent. The same MCP write
was gated in one harness and ungated in the other, though both surfaces are meant to be
renderings of one contract. Added locally; the renderer should emit it for both.

## Local workaround applied (non-durable)

On `main`, under `MAINT-codex-hook-cwd-20260729`:

- `.codex/hooks.json` — all 14 commands rewritten to the git-toplevel-anchored form,
  handlers passed absolute; the missing `guard-review-finding-resolve.py` entry added.
- `.codex/config.toml` — `[features].codex_hooks` → `hooks` (the deprecated name emits a
  deprecation line into every session transcript, including offloaded review reports);
  `codebase-graph-mcp` launcher anchored to match its two already-anchored siblings.

Verified end-to-end, not asserted from the diff: `codex exec --cd <worktree>/apps/prototype-wp-alt-context`
now completes a file write with zero `_run_guard` errors, zero `PostToolUse Blocked`, and
zero deprecation output. The control run before the fix produced two blocks.

These are **rendered outputs**. `make generate-agent-workflows` or a `workbay update` will
regenerate them from the upstream transform and reintroduce §1. `scripts/hooks/coherence-self-check.py`
is a gitignored overlay file and is additionally blocked from local edit by the
main-branch guard, so §3 has no local workaround at all.

## Reproduction

```sh
# §1 — from any subdirectory of the workspace
cd apps/prototype-wp-alt-context
python3 scripts/hooks/_run_guard.py .github/hooks/guard-main-branch.py; echo "exit=$?"   # exit=2

# §2 — from a linked worktree, move .codex/hooks.json aside, then run any codex exec:
#      hook lines still fire, sourced from the root checkout

# §3
python3 scripts/hooks/coherence-self-check.py </dev/null    # every anchored command reported dangling
```
