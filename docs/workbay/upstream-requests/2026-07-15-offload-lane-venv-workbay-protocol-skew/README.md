# Upstream request — offload lane worktree `.venv` pins a stale `workbay_protocol` (missing `.version`); `offload_preflight` warns but there is no provisioning path

**Target repo:** `agentic-protocol-monorepo` / `darce/workbay` (`workbay-orchestrator-mcp` — offload lane env provisioning + `offload_preflight`).
**Consumer:** `context-alt-text-monorepo` (package-mode install, 8 GiB operator laptop).
**Affected releases (as observed):**
- Orchestrator runtime: `workbay_protocol==0.2.2` (from the uv-tool env `~/.local/share/uv/tools/mcp-workbay-orchestrator/` and pyenv-global 3.13.9) — **has** `workbay_protocol.version`.
- Linked worktree `.venv`: `workbay_protocol==0.2.0`, `mcp_workbay_handoff==0.2.0`, `mcp_workbay_orchestrator==0.2.0` — **lacks** `workbay_protocol.version`.

**Discovered while:** dispatching a `grok-cli` offload lane (VLM-6 eval-harness slice) from a linked worktree. `offload_preflight` passed backend/effort/model checks (`ok:true`) but warned the lane env was unready; there was no clean, documented way to reconcile it, so the slice was inlined.

## Summary

An offload lane runs in a **linked git worktree**, and `offload_preflight` validates the lane by importing `workbay_protocol.version` **with that worktree's `.venv` Python**. But the worktree `.venv` carries a **stale `workbay_protocol` (0.2.0)** that predates the `.version` submodule, while the orchestrator itself runs a newer build (0.2.2). The consumer has:

- **no root `pyproject.toml` / `uv.lock`** at the worktree (or repo) root — so `uv sync` fails outright (`No pyproject.toml found in current directory or any parent directory`);
- **no documented `make`/`wb` target** to reconcile a lane `.venv` to the orchestrator's pinned `workbay_protocol`;
- **only a warning, not a fail**, from `offload_preflight` — so the pass would proceed into a lane whose worker cannot import a module the worker runtime needs, converting a fixable pre-flight condition into a mid-pass failure that burns a dispatch cycle.

Net effect: on this host, grok offload was not shippable this session. Combined with host memory pressure (a **separate** defect already filed — see `2026-07-13-hostgov-remote-backend-cost-class`), the two made `/offload` unusable and the work was completed inline.

---

## Defect 1 — lane `.venv` `workbay_protocol` is never reconciled to the orchestrator's version

`offload_preflight` returned:

```
worktree env unready: lane .venv cannot import required workbay siblings
(workbay_protocol, workbay_protocol.version):
ModuleNotFoundError: No module named 'workbay_protocol.version'
— run `uv sync` in <worktree> before dispatch
```

But `uv sync` cannot run — there is no `pyproject.toml` at the worktree or repo root (this consumer is a package-mode install, not a uv workspace). The remediation the warning prescribes is inapplicable to the very install shape workbay ships to.

The three `workbay_protocol` copies observed on one machine:

| Location | version | `.version`? | used by |
|---|---|---|---|
| `~/.local/share/uv/tools/mcp-workbay-orchestrator/` | (tool pin) | — | orchestrator process |
| pyenv-global `3.13.9/site-packages` | 0.2.2 | yes | ambient `python3` |
| linked worktree `.venv` | 0.2.0 | **no** | **lane worker + preflight import check** |

Nothing in lane materialization (`manage_worktree_lane` / `materialize_offload_lane_manifest`) pins or upgrades the worktree `.venv`'s workbay siblings to match the orchestrator, so a worktree created (or `.venv`-seeded) at an older workbay release stays skewed indefinitely.

**Ask:**
- Have lane materialization (or `offload_preflight` in a `--repair`/auto mode) **reconcile the lane `.venv`'s `workbay_protocol` (+ `mcp_workbay_*`) to the orchestrator's own resolved versions**, using a mechanism that works for **package-mode installs with no root `pyproject.toml`** (e.g. `uv pip install --python <lane .venv> "workbay-protocol==<orchestrator version>"`, or point the lane worker at the orchestrator's env rather than the worktree `.venv`).
- Prefer **"worker uses the orchestrator's resolved env"** over per-worktree duplication if feasible — three divergent copies on one host is the root smell (single-source-of-truth).
- If a per-worktree `.venv` is required, document the exact reconcile command in the offload runbook and expose it as a `wb`/`make` one-shot (`wb offload-repair-env` or similar), since `uv sync` is not applicable.

## Defect 2 — preflight should **fail** (or offer `--repair`) on an unready lane env, not warn-and-continue

`offload_preflight` returns `ok:true` with the env-unready condition demoted to `warnings[]`. A `run_offload_pass` that follows would dispatch into a worker that cannot import a required module — the exact class of failure the Fail-Fast pre-flight exists to prevent (Release It! — fail before spend, not during).

**Ask:**
- Treat "lane `.venv` cannot import `workbay_protocol.version`" (or any required worker sibling) as a **hard pre-flight failure** by default (`ok:false` with the reconcile instruction), OR
- Add an `offload_preflight(..., repair=true)` (and/or a lane-materialization step) that provisions the lane env in place and re-verifies, so the operator gets a one-call fix instead of an unactionable warning.
- Whichever path: the remediation string must be **valid for the shipped install shape** — do not instruct `uv sync` when there is no `pyproject.toml`.

---

## Reproduction

1. Package-mode workbay install (no root `pyproject.toml`); orchestrator on `workbay_protocol>=0.2.2`.
2. A linked worktree whose `.venv` was seeded at an older workbay release (`workbay_protocol==0.2.0`).
3. `offload_preflight(agent="grok-cli", reasoning_effort="high", model="grok-4.5", token_budget=…, worktree_path=<worktree>)`.
4. Observe: `ok:true` **with** `warnings:[ "worktree env unready: lane .venv cannot import … workbay_protocol.version … run \`uv sync\` …" ]`.
5. `uv sync` in the worktree → `error: No pyproject.toml found`. No documented alternative.

## Workaround used

None viable within the session's risk budget: reconciling the workbay env in-worktree was declined because bootstrap/self-heal churn has previously deleted tracked files on this consumer (see `2026-06-05` bootstrap incident notes). The offload slice was **implemented inline** and the env gap recorded as a consumer-side error event for the harvest.

## Cross-references

- Memory-pressure / remote-API admission (a **distinct** offload blocker on the same host): `docs/workbay/upstream-requests/2026-07-13-hostgov-remote-backend-cost-class/`.
- Overlay/env materialization fragility on linked worktrees (Makefile.d, scripts/*, `.claude/hooks` symlink) rsynced from root this session — same class of "linked worktree not fully provisioned" gap; worth a unified lane-provisioning story.
