# Upstream request — `doctor` reports 15 false `hook_command_unresolved` errors and prescribes the remedy that destroys the fix

**Filed:** 2026-08-04
**Consumer:** `context-alt-text-monorepo`
**Versions:** `workbay` 0.3.31, `workbay-bootstrap` 0.3.22, `workbay-system` 0.3.21,
`mcp-workbay-handoff` 0.2.16, `mcp-workbay-orchestrator` 0.2.16, `workbay-protocol` 0.2.3
**Sibling requests:** `2026-07-29-codex-hook-cwd-anchor-and-worktree-blindness` (why the
consumer patch exists at all), `2026-08-04-clean-install-silent-surface-revert-and-unrecoverable-states`
(why it has to be re-applied after every install)
**Severity:** medium — no runtime breakage, but the diagnostic is wrong on every run and its
stated remedy reverts a security-relevant guard fix

---

## Symptom

`workbay doctor --target .` emits **15** errors of this shape, one per command in
`.codex/hooks.json`:

```
hook_command_unresolved: .codex/hooks.json — command 'sh -c \'root="$(git rev-parse
--show-toplevel 2>/dev/null || echo .)"; exec python3 "$root/scripts/hooks/_run_guard.py"
"$root/.github/hooks/guard-main-branch.py"\' sh' names 'root="$(git rev-parse
--show-toplevel 2>/dev/null || echo .)"; exec python3 "$root/scripts/hooks/_run_guard.py"
"$root/.github/hooks/guard-main-branch.py"' which does not resolve from the target
(checked /Users/daniel/Development/context-alt-text-monorepo/root="$(git rev-parse
--show-toplevel 2>/dev/null || echo .)"; exec python3 ".../guard-main-branch.py")
; the harness will errno-2 this hook. Regenerate the config or restore the script.
```

Every one is false. All 16 scripts referenced across `.codex/hooks.json` and
`.claude/settings.json` exist on disk:

```
$ for f in scripts/hooks/_run_guard.py .github/hooks/guard-main-branch.py \
           .github/hooks/guard-worktree-drift.py scripts/hooks/guard-bash-main-branch.py \
           ... ; do [ -f "$f" ] && echo "OK   $f" || echo "MISS $f"; done
OK   scripts/hooks/_run_guard.py
OK   .github/hooks/guard-main-branch.py
OK   .github/hooks/guard-worktree-drift.py
...
(16 OK, 0 MISS)
```

The hooks also *run*. This is a reporting defect, not a runtime one.

## Mechanism

The resolver takes the hook's `command` string and picks the token it believes is the
script path, then joins it onto the target root and stats it. It appears to look for the
first token after the interpreter rather than parsing the command as shell words.

Given `sh -c '<script>' sh`, it takes the entire quoted `<script>` body — newlines,
`$(...)`, semicolons and all — as one path component. The `checked` path in the error
message shows this directly: the target root with a whole shell program concatenated onto
it.

The fix is to parse with `shlex.split()` and, when `argv[0]` is a shell (`sh`, `bash`,
`zsh`) with `-c`, either resolve paths *inside* the script body or decline to judge it.
Declining is fine — an unparseable command is not evidence of a missing file.

## Why this one bites harder than an ordinary false positive

**The prescribed remedy destroys the thing the patch fixes.** "Regenerate the config"
rewrites `.codex/hooks.json` back to the bare relative form:

```sh
python3 scripts/hooks/_run_guard.py .github/hooks/guard-main-branch.py
```

which is exactly the form that does not resolve from a linked worktree — the defect filed
in `2026-07-29-codex-hook-cwd-anchor-and-worktree-blindness`. The `sh -c` wrapper exists
*because* of that request. So the loop is:

1. Consumer patches the hooks to anchor on `git rev-parse --show-toplevel`.
2. `doctor` cannot parse the patch, calls all 15 commands unresolved, and says regenerate.
3. Regenerating reverts the anchor, silently disabling the main-branch and worktree-drift
   guards from every linked worktree.
4. `doctor` now reports clean.

An operator following the tool's own advice ends in the *less* safe state with a greener
report. Combined with the sibling finding that a reinstall reverts the patch anyway and
`doctor` then reports no drift, there is no configuration in which `doctor` tells the truth
about this file.

**And it drowns the real findings.** The same run surfaces one genuine warning
(`orphan_hook_config: .claude/settings.hooks.json`) and one genuine note
(`unharvested_agent_errors: 469 rows, top class compaction_failed`). Both sit underneath 15
identical false errors, each ~450 characters.

## Canon

Graded against `heuristics-canon` v0.19.0; rule text quoted verbatim.

- **OBS-04** (`engineering.md:463`) — trigger: *log statement at ERROR level for business
  noise*. **"ERROR means operator action**: false positives train operators to ignore real
  alarms." Check: *"Would on-call need to act on this at 3 a.m.?"* Fifteen errors per run,
  none actionable, sitting on top of two that are.
- **PERC-07** (`interaction-ux.md:97`) — **"Don't habituate alarms**: reserve strong
  attention-getting methods for rare, critical, irreversible events and suppress the
  routine, or users learn to dismiss the one that matters." `doctor`'s error channel is now
  routine noise for this consumer.
- **AGT-10** (`engineering.md:80`) — **"Degrade loudly"**, whose reception-side twin OBS-04
  names directly: *"an alarm that demands no action makes the loud channel lie in the reader
  instead of the emitter."* That is precisely the state here.
- **WEB-02** (`security.md:104`) / **DATA-12** — **"Never shell-interpolate untrusted
  input**: use argv APIs or refuse shell." The inverse discipline applies to *reading* a
  command too: a shell command line is not a path and must not be treated as one by string
  concatenation.

## Asks, in priority order

1. **Parse before judging.** Use `shlex.split()`. If `argv[0]` is a shell with `-c`, do not
   emit `hook_command_unresolved` for the script body — either resolve inside it or skip.
2. **Never prescribe a remedy that reverts a consumer patch.** If a hook command is
   unparseable, say so ("could not parse; not checked") rather than asserting the harness
   will errno-2 and telling the operator to regenerate. Assert breakage only when a path was
   actually resolved and actually missing.
3. **Generate the anchored form.** The root cause is that consumers must hand-patch at all.
   Emitting a repo-root-anchored command from the generator closes this request and
   `2026-07-29` together, and removes the surface that `2026-08-04-clean-install-silent-surface-revert`
   keeps reverting.
4. **Cap repeated identical findings.** Fifteen ~450-char errors differing only in script
   name should collapse to one finding with a count and a list.

## Reproduction

```sh
# in a consumer whose .codex/hooks.json commands are wrapped as:
#   sh -c 'root="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"; \
#          exec python3 "$root/scripts/hooks/_run_guard.py" "$root/<guard>"' sh
workbay doctor --target .
# => 15 x hook_command_unresolved, while every referenced script exists
```
