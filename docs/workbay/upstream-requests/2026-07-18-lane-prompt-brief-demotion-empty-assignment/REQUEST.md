# Upstream request: lane_prompt demotes dispatch briefs — remote workers receive an empty Assignment and no-op

- **Date**: 2026-07-18
- **Package**: `mcp-workbay-orchestrator` (installed 0.x via uv tool; source `agentic-protocol-monorepo/packages/mcp-workbay-orchestrator`)
- **Severity**: high — silently converts every findings-fix dispatch into a zero-commit `error` pass
- **Extends**: `2026-07-17-grok-remote-pass-engine-defects` (defect 3, execute-failure misattribution)

## Symptom

Five consecutive `run_offload_pass` invocations on lane `fir-2-s2a` (backend `grok-remote`, dispatches
`fir-2-revfix-r0717cc62-v1..v4`, 2026-07-18 00:04–02:06 UTC) returned
`outcome=error / failed_stage=review / commit_landed=false` with the task's open findings echoed in the
payload and main-agent output of ≤22 tokens. The same lane had landed implementation commits successfully
90 minutes earlier (S4 passes, 23:39/23:45 UTC). VM was healthy throughout (18.4 GB MemAvailable, zero
`grok-lane-*` scopes, `remote_agent.sh doctor` green) — environment hypotheses refuted by operator-run
diagnostics.

## Root cause (source-confirmed)

`orchestration/lane_prompt.py`:

1. `_brief_messages` routes every message whose subject starts with `brief:` into the **Dependency
   Briefs** section, rendered by `PromptFormatter.brief_message` as a whitespace-collapsed one-liner.
2. The **Assignment Inbox** section builds only from non-brief messages plus **lane-scoped** actions,
   findings, and blockers. Findings merged under a coordinator task (`/review-parallel` merge writes
   `lane_id=null`) never appear.
3. Net effect for a review-fix dispatch: the worker prompt (observed 4,396 chars,
   `section_sizes.assignment = 0` in `worker-<lane>.status.json`) contains no assignment. grok
   legitimately files `needs_guidance`; `remote_agent.sh` exits 4 (no commit).

Compounding defects:

4. `orchestration/offload_pass.py:1582` maps the resulting nonzero handoff to
   `outcome=error / failed_stage=review` and discards the `BackendResult.summary` the
   `RemoteExecAdapter` carefully typed (the defect-3 misattribution already filed; this is its most
   damaging trigger).
5. `adapters/remote_exec.py` fetches `--result-out` into a `tempfile.TemporaryDirectory` that is
   deleted on return, so grok's own explanation is unrecoverable locally; the VM-side copy is
   permission-gated under `/home/gate/grok-sandbox`.
6. The prompt's `latest_report` slot replays whatever stale lane report exists (here a 2026-07-16
   "transport missing" failure), further steering workers toward declining.

## Controlled experiment (proof)

Dispatch v5 changed exactly one variable: the identical instructions were recorded as a **non-brief**
lane message (subject `assignment: implement revfix v5 (4 commit groups)`) with a one-line `brief:dispatch`
pointer. Result: `commit_landed=true`, implementation commit `fab6b427` (17 files, +411/−68), unit suite
721→732 green, all 10 findings closed. Same engine, same lane, same VM, minutes apart.

## Requested upstream changes

1. **Render the open dispatch brief as the Assignment** (or a dedicated first-class "Dispatch" section)
   with body intact — never a collapsed one-liner in Dependency Briefs. A dispatch brief is the work
   order, not context.
2. **Surface worker explanations on failure**: when a pass ends without a clean handoff, carry
   `BackendResult.summary`/`blockers` (and ideally the tail of `--result-out`) into the pass result
   instead of the bare `review phase ended the pass without a clean handoff`.
3. **Persist `--result-out`/`--debug-out`** under `.task-state/` (bounded size) instead of a
   TemporaryDirectory so zero-commit passes are diagnosable postmortem.
4. **Scope or age-out `latest_report`** in the prompt: a days-old failure report should not be replayed
   into every subsequent turn.
5. Consider including coordinator-level (`lane_id=null`) open findings for the lane's task in the
   Assignment when a fix-dispatch is active, or at minimum documenting the lane-scoping rule.

## Workaround in production here

Record instructions as a non-brief `assignment: …` message plus a pointer dispatch (see FIR-2 decision
`claude_fir2_pass_engine_brief_demotion_root_cause`, 2026-07-18). Verdict-bearing review passes
additionally route their verdict through `git commit --allow-empty -m "HARM-VERDICT: …"` so the text
survives the handoff parse defect.
