# Harness Terminal Stall Investigation

**Date:** 2026-05-11
**Task:** `MAINT-harness-terminal-stall-20260511`

## Community Signals

- `anthropics/claude-code#52933` reports that the Bash tool hangs and routes commands to background tasks in the VS Code Copilot harness. The report describes the problem as generic Bash-tool behavior, not a zsh-only regression.
- `anthropics/claude-code#57260` reports the same background-task symptom on macOS, again against the Bash tool rather than zsh specifically.
- `microsoft/vscode#315395` documents that local agent-host terminals now respect `terminal.integrated.agentHostProfile.<os>`, and that `bash`, `zsh`, `fish`, and `sh` all route through the same `bash` tool family. Only the executable `path` is honored today; profile `args` and `env` are ignored.

## Findings

- The public issue traffic does **not** confirm that zsh is the root cause. What it does confirm is that the VS Code Copilot or agent-host terminal path can hang independently of shell choice.
- zsh is still a plausible amplifier on macOS because its startup path often loads heavier shell customizations than `/bin/bash`, so forcing a simpler shell is a reasonable workspace-level mitigation.
- The public issue traffic does **not** prove that daisy-chained commands are the direct root cause either, but single focused commands are still the safer operating mode in this harness because they reduce terminal scrollback, simplify repros, and reduce ambiguity when a command is backgrounded or truncated.
- Follow-up repro on 2026-05-11 showed `cd "$HOME/Development/context-alt-text-monorepo-e15-22/apps/prototype-wp-alt-context" && npx vitest run js/admin/pages/workbench/__tests__/JobTimeline.test.tsx` can finish in about one second, print the shell prompt, and still leave the VS Code chat terminal tool waiting until timeout. Redirecting stdout/stderr and adding `--pool=forks` did not make raw `npx vitest run` reliable.
- Running the same target through `npm run test:agent -- js/admin/pages/workbench/__tests__/JobTimeline.test.tsx` returned control to chat and preserved the Vitest output. That wrapper intentionally masks the shell exit code, so agents must read the output summary rather than treating exit code `0` as proof of green tests.

## Repo-Local Fix

- Set `terminal.integrated.agentHostProfile.osx` to `{ "path": "/bin/bash" }` in workspace settings so the local agent host uses a minimal POSIX shell path on macOS.
- Set the WordPress plugin Vitest pool to `forks`; this reduces one observed completion problem for green runs but does not make raw `npx vitest run` reliable in VS Code chat.
- Add `npm run test:agent -- <path>` for VS Code chat test runs. It executes Vitest through an npm script wrapper and returns control even when the test is red; this is a chat-harness workaround, not a CI gate.
- Narrow `.github/hooks/terminal-guard.py` to block only raw `vitest run` / `npx vitest run` and allow every other terminal command through. Earlier allowlist/default-deny behavior blocked useful investigation commands without addressing the observed stall.
- Keep the guidance operational rather than magical: prefer one `make`, test, or git command per terminal invocation when practical. Avoid long `cd ... && ... && ...` chains when a focused command or a cwd-aware form can express the same action.

## Proposed Operator Guidance

- Prefer `/bin/bash` for the local VS Code agent host in this workspace.
- In VS Code agent chat, prefer `npm run test:agent -- <path>` over raw `npx vitest run <path>` and read the result text for pass/fail.
- Prefer a single focused terminal command per invocation.
- Treat chained commands as a readability and harness-debuggability risk, not as the proven root cause.
