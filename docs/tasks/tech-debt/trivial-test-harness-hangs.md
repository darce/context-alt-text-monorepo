# Tech Debt: Trivial test harness hangs

## Problem

Focused, low-cost test commands can hang or return unusable output when run through the coding-agent harness, even when the same command completes normally in a direct terminal session.

Recent example:

- `npx vitest run js/admin/hooks/__tests__/useWorkbenchMedia.test.tsx` passed in under one second when run manually.
- The same style of focused Vitest invocation produced an empty redirected output file or a canceled/indeterminate harness run when triggered through the agent terminal flow.

This creates two concrete problems:

- verification becomes unreliable for narrow slices that should be cheap to prove;
- the agent is pushed toward user-supplied manual evidence instead of first-party harness evidence.

## Why this matters

- It slows routine validation for small frontend and PHP slices.
- It increases ambiguity about whether a failure is in the code, the test runner, or the harness.
- It makes tool-selection policy harder to follow because the recommended direct test path is not consistently trustworthy.

## Desired outcome

Establish a deterministic agent-side test execution path for trivial suites so focused runs either:

- complete with reliable captured output; or
- fail with a clear harness-level error that distinguishes transport issues from test failures.

## Candidate directions

- Audit the agent terminal capture path for redirected `vitest` output and foreground process completion semantics.
- Add a documented fallback wrapper for trivial suites that preserves exit code and output without hanging the harness.
- Define a repo-level verification convention for cases where harness output is known to be unreliable, including how evidence should be captured and recorded.

## Exit criteria

- Reproduce the hang with a minimal focused test command.
- Identify whether the failure is caused by terminal capture, shell state, redirection, or the harness integration.
- Document one reliable validation command pattern for narrow suites and update agent instructions if needed.

## Consolidated Triage Checklist (2026-04-30)

**Disposition:** Still needs investigation; keep open.
**Evaluation basis:** Current test-run policy and current frontend verification surfaces.

- [ ] Reproduce the focused Vitest hang with a minimal command under the agent terminal flow.
- [ ] Compare foreground terminal output, redirected output, and any harness cancellation/timeout behavior.
- [ ] Identify whether the failure is caused by terminal capture, shell state, redirection, Vitest process behavior, or harness integration.
- [ ] Document a reliable narrow-suite command pattern in the agent instructions or testing guide.
- [ ] Archive only after the root cause and fallback convention are documented.