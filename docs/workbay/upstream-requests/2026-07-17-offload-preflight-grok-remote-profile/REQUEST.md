# Upstream request — `offload_preflight` has no `grok-remote` profile row, so fully-remote dispatches false-refuse under grok-cli's gated `remote_api` cost class

**Target repo:** `darce/agentic-protocol-monorepo` (`mcp-workbay-orchestrator` — `orchestration/offload_profiles.py`, `orchestration/offload_preflight.py`).
**Consumer:** `context-alt-text-monorepo` (package-mode install).
**Affected release:** `mcp-workbay-orchestrator==0.2.12`, `workbay==0.3.26`.

## Summary

Plan 0132 (`wb-hostgov-remote-costclass-01`) landed the correct admission posture for fully off-box workers: `host_resources.COST_REMOTE` is never gated on local memory ("gating a remote lane on local RAM is a false positive"), `grok-remote`'s `BackendSpec` carries `cost_class=COST_REMOTE`, and `run_offload_pass` resolves it per-backend via `cost_class_for_backend(backend)`.

`offload_preflight` never got the matching row. `OFFLOAD_AGENT_PROFILES` contains only `grok-cli` and `codex-subagent`, so:

- `offload_preflight(agent="grok-remote", ...)` fails fast: `backend 'grok-remote' is not a supported /offload agent; supported: grok-cli, codex-subagent`.
- The practical workaround — preflight under `agent="grok-cli"`, then dispatch/run with `backend="grok-remote"` — evaluates the preflight admission facet under grok-cli's `COST_REMOTE_API` (gated) class. On a memory/disk-constrained laptop the preflight returns `admission_refused` (observed: `swap-volume free disk 6.7GiB below floor 8.0GiB` on an 8GB M1) for a dispatch whose agent execution **and** tests run entirely on the remote OCI VM.

The caller is then forced to choose between `admission_override=true` (etiquette-violating — the refusal is not a false positive *for the class preflight assumed*) and skipping/tolerating preflight's admission facet (what we did, after verifying the pass engine's own gate resolves `COST_REMOTE` → allow). Both undermine the Fail-Fast contract: the one surface designed to give a zero-spend verdict gives the wrong verdict for exactly the backend that exists to route around a busy local box.

## Ask

Add an `OFFLOAD_AGENT_PROFILES` row for `grok-remote`:

- same `grok-4.5` pin and grok-derived single-cycle bounds as `grok-cli` (remoteness is carried by the adapter/cost class, not the model policy);
- availability via the existing `_probe_grok_remote` (unset `WORKBAY_REMOTE_GATE_HOST` stays a typed fail-fast);
- preflight admission facet resolved with `cost_class_for_backend("grok-remote")` → `COST_REMOTE`, so a fully-remote dispatch preflights clean on a busy local box — matching what `run_offload_pass` already does at spawn time.

Secondary (docs): the `/offload` skill's "Explicit agent + effort" section lists only `grok-cli | codex-subagent`; if the profile row lands, list `grok-remote` there too so operators don't rediscover the preflight-under-grok-cli workaround.

## Reproduction

1. Local host under memory pressure such that `swap_volume_free_bytes < swap_volume_disk_floor_gib` (or any gated dimension failing).
2. `offload_preflight(worktree_path=<lane>, agent="grok-cli", model="grok-4.5", reasoning_effort="high", token_budget=150000)` → `ok:false, error_kind=admission_refused` (cost_class `remote_api`).
3. `run_offload_pass(lane_id=<lane>, backend="grok-remote", ...)` on the same host at the same instant → admitted (cost_class `remote`, ungated by design).

Observed 2026-07-17 dispatching FIR-2 S2a from `context-alt-text-monorepo` to the OCI VM remote gate (`WORKBAY_REMOTE_GATE_HOST` set, `remote_agent.sh doctor` green).
