# GPUOPS-1 gate review — adversarial slice review of `feature/gpuops-1`

READ-ONLY. Commit nothing. **Never start or stop a real GPU. No OCI calls. No ssh to acx-backend.** The A10 is STOPPED and only the operator may change that.
Finding-id range reserved for this reviewer: `GPUOPS-1-GR-01..30`. Do not reuse any other id.

## Subject

`feature/gpuops-1` at the merge head you are given. It gives an operator a button that starts and stops a $2/hr A10, and gives an automated controller the authority to reap it. The landed lanes:
- `gpuops-1-lifecycle` / `-r1-intent-reader` — `infra/oci/gpu_lifecycle/`: intent reader, controller semantics, additive `gpu-state.json` fields.
- `gpuops-1-installer` / `-r3-installer-fencing` — `scripts/deploy/gpu-lifecycle-install.sh`, `infra/oci/cloud-init.yaml`: `--intent-dir`, the `acx-gpu-intent.path` unit, installer as single reaper owner.
- `gpuops-1-service-api` / `-php` / `-spa` / `-naming-*` — FastAPI `/scene/gpu/*`, the WordPress `acx/v1/recognition/gpu/*` pass-through, the Settings Burst GPU card.
- `gpuops-1-fix-process` — task plan and lane-common process fixes.
- `gpuops-1-fix-intent` — durable intent, monotonic authority, deferred-stop trace, decision log, runbook guard.

## What this component claims

That an operator's start/stop intent is honoured exactly once, cannot be forged or replayed, survives a reboot, and that every automated decision to spend or stop spending money leaves a record a human can reconstruct.

## Your lenses

1. **Fencing at the point of use** ([RES-10] fencing tokens). A monotonic sequence that only the store enforces is not a fence. Trace the authority from the HTTP POST through the intent file to the reaper's decision and name every place a stale or lower-sequence intent could still win. Specifically: a backwards clock correction, a replayed nonce, two writers racing the same env directory, an intent file written by a process that then dies before fsync.
2. **Durability symmetry** ([RES-17] write-ahead of intent before in-place mutation). The intent authorises a durable external mutation — a running A10 and a durable lease at `/var/lib/acx-gpu/running-since.json`. Is the authorising record now as durable as what it authorises, on every path? What survives a backend reboot, and what silently reverts to `auto`? A `start` that reverts to `auto` means the GPU gets reaped mid-demo with `last_transition_reason='idle'`.
3. **The dropped instruction** ([FLOW-08] declare a late-event policy). A `stop` deferred behind work in flight must be re-armed or explicitly dropped with a trace. Find the path where it is neither. Check the interaction between the deferral and the TTL, and between the deferral and a subsequent `start`.
4. **Reconstructability** ([HAI-06] audit trail as design fuel). Can a reader answer "who started the A10 at 03:00, and did the controller honour it" from the decision log alone, after a reboot and after the next POST overwrites the intent? Is the log append-only in practice, or truncated/rotated by something in the deployment?
5. **Mutual exclusion.** Two lifecycle units, a `.path` unit, and a timer. Is `flock` on `/var/lib/acx-gpu/lifecycle.lock` taken on every path that can issue a START or STOP? Name any that bypasses it. The cloud-init idle reaper was removed this round — verify nothing else re-introduces a second reaper owner.
6. **Trust boundary** ([SEC-01] validate at every trust boundary). `requested_by` comes from WordPress `user_login`; the PHP layer is a verbatim pass-through per [rg-015]. Can a caller forge `requested_by`, an `expires_at`, or a sequence? Is the demo tenant's `403 gpu_control_forbidden` enforced at the service, not just hidden in the UI ([rg-003] primary controls and their guards must not depend on UI state)?
7. **Bounded waits** ([RES-02]). Readiness probes, OCI polls, the 10s PHP timeout, the intent lock timeout. Name any unbounded one.
8. **Enum completeness** ([REF-29]). `IntentAction`, `IntentStatus`, `LastTransitionReason`, the exposed status payload. An unknown value must not read as a neighbouring one, and the UI must not render a state the contract cannot produce.
9. **Guard tests that pin syntax instead of contract.** This branch has already produced two of these (`START_INTERVAL` in the warmstart guard, and the three-variable shell-default regex in the runbook guard). Look for more: a test that would break on a cosmetic rewrite of the artefact it guards is a false guard ([rg-005] validate against the real artefact).

## Canon

`~/Development/heuristics-canon-research` — 1213 rules across 11 lexicons; `INDEX.md` maps id → lexicon anchor; `distilled/engineering`, `distilled/security`, `distilled/epistemics` carry the reasoning cards. Cite real ids only; verify each in `INDEX.md` before you use it. Load-bearing here: [RES-10] fencing tokens · [RES-17] write-ahead of intent before in-place mutation · [RES-02] timeout on every blocking call · [RES-01]/[API-02] retry without idempotency · [FLOW-08] declare a late-event policy · [SEC-01] validate at every trust boundary · [REF-29] enum completeness · [HAI-06] audit trail as design fuel · [OBS-05] expose everything, externalize policy. Repo guards: [rg-015] boundary adapters never invent contract metadata · [rg-005] contract parity against the real artefact · [rg-010] cross-check a surprising finding with a terminal command first — several paths here are gitignored in the sandbox mirror and will look absent when they are not.

## Output

Findings via `review_findings` (`batch_record` when ≥3) on `task_ref=GPUOPS-1`, each with `file_path`, `line_start`/`line_end`, a concrete `fix`, and the canon id in the description. If no MCP write path exists in the sandbox, print a fenced JSON block titled `FINDINGS` with the same fields.
One line: `VERDICT: pass | pass_with_findings | conditional_pass | fail` plus a one-sentence reason.

A finding needs evidence, a line range, and a fix a junior agent could apply from the text alone. No finding without a concrete failing input or a named unfenced path.
