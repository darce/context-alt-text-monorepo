# Upstream request — `codex-subagent` offload backend unavailable in bootstrap/package-mode installs

**Target repo:** `agentic-protocol-monorepo` / `darce/workbay` (`mcp-workbay-orchestrator` + `workbay-bootstrap`).
**Consumer:** `context-alt-text-monorepo` (package-mode install; orchestrator runs as a uv-tool console).
**Affected release:** `mcp-workbay-orchestrator==0.2.1` (installed via `workbay-bootstrap install`, alongside `workbay-v0.3.8`).

## Problem

`/offload --agent codex-subagent …` cannot run out of the box. The orchestrator MCP server reports the codex offload backend as unavailable:

```
list_available_backends(probe=true) →
  codex-subagent:
    is_available: false
    availability_state: "declared_not_installed"
    availability_detail: "Bridge module 'workbay_codex_bridge' is not importable in this
      runtime. Install the optional host package (mcp-workbay-orchestrator[bridge]) or
      launch the server from a venv that provides it."
```

The `structured-turn` in-process backend composes `codex-subagent` downstream, so it is transitively unavailable for real turns too. `grok-cli` is the only reasoning-effort junior backend left up.

Because the `/offload` skill is **fail-fast with no backend fallback**, and `codex-cli` is explicitly disallowed for offload (no single-cycle wall-clock bound), **codex offload is fully blocked** — there is no supported degrade path.

## Root cause chain

1. `mcp-workbay-orchestrator==0.2.1` declares the codex bridge as an **optional extra**, not a base dep:
   `Provides-Extra: bridge` → `Requires-Dist: workbay-codex-bridge<0.3.0,>=0.2.0; extra == 'bridge'`.
2. `workbay-bootstrap install` installs the orchestrator as a uv tool (`uv tool list` → `mcp-workbay-orchestrator v0.2.1`) **without the `[bridge]` extra**. The tool venv at `~/.local/share/uv/tools/mcp-workbay-orchestrator` therefore has no `workbay_codex_bridge` module (`importlib.util.find_spec('workbay_codex_bridge')` → `None`).
3. `scripts/hooks/mcp_launch.py` execs that bootstrap-installed uv-tool console (`mcp-workbay-orchestrator … serve-stdio`) — the fast path that deliberately skips per-session `uv run`. So the server always launches from the extra-less tool venv; there is no launch-time opportunity to inject the bridge.
4. The probe's remediation string (`mcp-workbay-orchestrator[bridge]`) is not actionable in a bootstrap/package-mode consumer: there is no documented, bootstrap-integrated way to add the extra to the existing tool install, and a bare `uv tool install "mcp-workbay-orchestrator[bridge]"` re-resolves the base dist and still depends on `workbay-codex-bridge` being reachable from the consumer's configured index.

Net: a bootstrap-managed consumer that follows the documented setup ends up with a codex offload backend that is permanently `declared_not_installed`.

## Current consumer workaround

None viable in-session. The running MCP server can't pick up a newly-installed module without a reconnect/restart (session-level), and `/offload`'s no-fallback contract forbids silently routing to `grok-cli` or `codex-cli`. Consumer is blocked on this request.

## Ask

Make `codex-subagent` available out of the box for bootstrap/package-mode consumers. Any one of:

- **(preferred)** `workbay-bootstrap install` installs the orchestrator **with the `bridge` extra** by default (or behind a documented `--with-bridge` / config flag), so the uv-tool venv carries `workbay_codex_bridge`. Promote the extra into base deps if the bridge is meant to be the default offload path.
- OR provide a **supported, bootstrap-integrated command** to add the extra to the existing tool install (e.g. `workbay doctor --fix-offload-bridge` that runs `uv tool install --reinstall --with workbay-codex-bridge mcp-workbay-orchestrator` against the pinned version + index), and surface it in the probe `availability_detail` instead of the non-actionable `mcp-workbay-orchestrator[bridge]` string.
- OR, if the bridge is intentionally optional, make `offload_preflight` / `list_available_backends` return a **precise, copy-pasteable remediation** (exact command + explicit note that an MCP reconnect is required afterward) rather than a generic install hint, so the failure is self-service.

Please also confirm which offload backend is the intended default for package-mode consumers (codex-subagent vs grok-cli); the docs/skill assume codex-subagent is available while bootstrap installs it absent.

## Acceptance

On a fresh bootstrap/package-mode consumer, immediately after `workbay-bootstrap install` (no manual venv surgery) and an MCP (re)connect:

```
# orchestrator MCP:
list_available_backends(probe=true)   # codex-subagent.is_available == true
offload_preflight(agent="codex-subagent", token_budget=…, worktree_path=…)   # passes
```

---

## Appendix — orchestrator/worker daemon token-cost model (consumer question)

Recorded here because the consumer asked whether re-enabling orchestration would again skyrocket token spend (the reason daemons were turned off). Evidence from `workbay_orchestrator_mcp/orchestration/` (v0.2.1):

**The token skyrocket is the *continuous polling daemons*, not orchestration per se.** The shipped one-shot startup warning (`daemon_startup.py::emit_daemon_startup_warning`) states verbatim:

- orchestrator daemon: `~10-15 MCP queries/cycle`
- worker daemon: `~3-5 MCP queries/cycle` + "spawn `lane_prompt.py --check` subprocesses per poll"
- both: *"This may consume significant agent tokens over long runs. Rework candidate: see `packages/mcp-workbay-orchestrator/docs/reworks/event-driven-daemon-design-note.md`"*

The continuous loops (`orchestrator_daemon.py::_run_loop`, `worker_daemon.py` `while True`) run these query cycles every `poll_interval` seconds **indefinitely** until a stall threshold trips — this is the historical burn.

**A bounded, active-only path already exists and is exactly what `/offload` uses:** it never starts the continuous `manage_orchestrator` daemon. It calls `manage_worker(action="start", single_pass=true, token_budget=N)`, which:

- runs **one** actionable cycle then returns (`worker_daemon.py`: every poll branch does `if single_pass: return …` — no `time.sleep(poll_interval)` re-loop), and
- is capped by a `token_budget` circuit breaker (`_run_worker_cycles`: `if cumulative_tokens > token_budget → _handle_token_budget_exceeded(); return`), which open-circuits and preserves the worktree diff on exceed.

So token consumption **can** be scoped to active orchestration only — use the `single_pass` offload worker and do **not** start `manage_orchestrator(operation="start")`. The residual cost is the coordinator's own status polling (bounded MCP reads on a slow cadence). The upstream `event-driven-daemon-design-note.md` rework (pull/event-driven instead of fixed-interval poll) would further cut the continuous-daemon cost if that mode is ever needed.
