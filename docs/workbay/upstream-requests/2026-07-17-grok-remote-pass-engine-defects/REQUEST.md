# Upstream request — three grok-remote offload-pass engine defects observed in production use

**Target repo:** `darce/agentic-protocol-monorepo` (`mcp-workbay-orchestrator` — `orchestration/offload_pass.py`, `orchestration/adapters/remote_exec.py`, `scripts/remote_agent.sh`).
**Consumer:** `context-alt-text-monorepo` (package-mode install).
**Affected release:** `mcp-workbay-orchestrator==0.2.12`, `workbay==0.3.26`.
**Context:** FIR-2 orchestration, 2026-07-17 — five grok-remote passes on lane `fir-2-s2a` (OCI VM gate). Three slices landed successfully, so these are quality-of-signal defects, not launch blockers. Ordered by cost.

## Defect 1 — review cycle rebuilds the sandbox, silently destroying uncommitted execute work

Pass `fir-2-s3-pass-v1`: the execute turn fully implemented the slice (worker transcript shows 722 unit tests green) but hit the residual wall-clock cap at its single end-of-turn `git commit`. The pass then ran its smoke-review cycle, whose `remote_agent.sh` invocation **rebuilds the sandbox from the pushed branch** — wiping the dirty tree. Result: `outcome=error, commit_landed=false, checkpoint_commits=[]`, sandbox clean on inspection, an entire turn's work unrecoverable.

**Ask:** before any subsequent remote invocation for the same lane within a pass, preserve a dirty sandbox tree (e.g. `git diff > pre-rebuild.patch` kept next to the sandbox, or auto-commit a `wip:` checkpoint and surface it via `checkpoint_commits`). A turn cap on an implemented-but-uncommitted tree should degrade to `checkpoint`/salvageable, never silent loss. (Caller-side mitigation that worked: brief-mandated incremental commits — the v2 retry landed clean.)

## Defect 2 — grok's streamed multi-JSON stdout fails the review-stage handoff parse; every green pass reports `outcome=error`

All three successful passes (`fir-2-s2a-pass-v3`, `fir-2-s2b-pass-v1`, `fir-2-s3-pass-v2`) ended `outcome=error` / `failed_stage=review` / "review phase ended the pass without a clean handoff" **despite** `commit_landed=true` and green self-verify. Cause: grok-4.5 emits intermediate handoff-shaped JSON objects turn-by-turn; `.grok-result.json`'s `text` is a concatenation of several objects, the LAST of which is the schema-valid final report (`merge_ready`, findings, tests_run). The engine's parse evidently rejects the concatenation wholesale.

**Ask:** parse the final complete JSON object from the stream (or have the adapter strip intermediates before validation). The mandate "emit exactly one schema-valid JSON object" is not enforceable against grok's streaming behavior, and the current failure mode devalues the typed-outcome contract — the orchestrator must fall back to `commit_landed`/`failed_stage` discriminators plus manual `.grok-result.json` archaeology on every pass.

## Defect 3 — execute-stage sandbox-provisioning failure misreported as `self_verify_failed`

Pass `fir-2-s2a-pass-v1`: the consumer repo had no root `pyproject.toml`, so `remote_agent.sh`'s sandbox `uv sync` failed (uv rc=2 → script exit before grok launched; no systemd scope started). The pass reported `outcome=self_verify_failed, failed_stage=self_verify` with a pytest file-not-found tail — pointing diagnosis at the worker's tests instead of the transport. Expected: an execute-stage error naming the provisioning failure (`uv sync failed` tail). Caveat: the installed `remote_exec.py` on this host carried a local hot-patch (concurrent session), so please verify the rc→outcome mapping against pristine v0.2.12 before triaging.

Related: the root-`uv sync` requirement itself forces every consumer monorepo without a root Python project to commit a virtual `pyproject.toml` shim (done here @de149622, mirroring the agentic-protocol lanes fix) — consider making sandbox provisioning tolerate a missing root project (skip sync, or sync per-app from the brief's cwd).
