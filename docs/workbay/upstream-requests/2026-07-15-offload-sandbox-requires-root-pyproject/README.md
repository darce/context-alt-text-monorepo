# Upstream request — offload pass: sandbox provisioning requires a root `pyproject.toml` (workaround is destructive), and the model pin is not authoritative (Composer contaminates the pass)

**Target repo:** `agentic-protocol-monorepo` / `darce/workbay` (`workbay-orchestrator-mcp` — offload sandbox provisioning, model pinning, `offload_preflight`).
**Consumer:** `context-alt-text-monorepo` (polyglot monorepo: PHP plugin + Python services; **no root `pyproject.toml` by design** — every Python package owns its own under `apps/*` and `packages/*`).
**Affected releases (as observed):** orchestrator uv-tool env `mcp-workbay-orchestrator` with `workbay_protocol==0.2.2`.

**Discovered while:** dispatching `grok-cli` offload lanes for VLM-6 (eval-harness slices) from a linked worktree, across two sessions on 2026-07-15.

## Summary

The offload pass provisions its sandbox by `uv sync`-ing a **depth-1 clone** of the
consumer worktree. When the repo root has no `pyproject.toml`, that sync fails
(`No pyproject.toml found in current directory or any parent directory`) and the pass
dies during provisioning — `failed_stage=execute`, before the brief is ever read, burning
a dispatch cycle.

There is no supported opt-out: `WORKBAY_GROK_SANDBOX_PROVISION=0` is refused by the
consumer harness's permission classifier (disabling sandbox provisioning is not a
sanctioned action). So the only path is to **commit a throwaway virtual-root
`pyproject.toml` onto the feature branch**.

That workaround is worse than it looks — see Defect 2. It is merge scaffolding that must
be manually removed before merge, **and it silently arms a destructive `uv sync` in the
consumer's own worktree**, recreating the exact lane-`.venv` defect filed separately in
[`2026-07-15-offload-lane-venv-workbay-protocol-skew`](../2026-07-15-offload-lane-venv-workbay-protocol-skew/README.md).

**Provenance note (what was observed by whom):** the provisioning failure itself was
observed in the **UXP-1 lane** (earlier session, recorded in operator notes as the verified
recipe). In the VLM-6 session the pass never reached the execute stage — it was refused at
host-memory admission both times — so this request does **not** claim a first-hand
reproduction of the sync failure. **Defect 2 is first-hand and new**, measured in this
session against the real worktree.

---

## Defect 1 — provisioning assumes a Python-rooted repo

`uv sync` is run at the clone root unconditionally. A polyglot monorepo legitimately has no
root `pyproject.toml`: here the Python packages are `apps/prototype-description-service`
and `packages/*`, each with its own. Nothing at the root is installable, and nothing should
be.

The failure also arrives late (`failed_stage=execute`), after admission and clone, rather
than at preflight where it is cheap and actionable.

**Ask (any one of):**
1. **Tolerate a rootless repo** — skip `uv sync` when the clone root has no `pyproject.toml`, and log the skip. The worker may not need a root env at all; here it does not.
2. **Make the provisioning target configurable** — a lane-level `provision_dir` (and/or `provision_cmd`) so the consumer can point provisioning at the package that actually owns the dependencies, e.g. `apps/prototype-description-service`.
3. **Detect it in `offload_preflight`** — checking for a root `pyproject.toml` is a stat call. Failing fast there (with the remedy named) turns a burned dispatch cycle into an actionable pre-flight message. Same spirit as Defect 2 of the sibling request ("preflight should fail, not warn-and-continue").

## Defect 2 — the prescribed shim is destructive in the consumer's worktree (first-hand)

The workaround is a virtual root:

```toml
[project]
name = "<repo>-root"
version = "0.0.0"
requires-python = ">=3.12"

[tool.uv]
package = false
```

This makes `uv sync` succeed **in the sandbox's fresh clone** (no `.venv` to prune). But the
same file is now committed on the branch and present in the consumer's **real** worktree,
where a `.venv` does exist — the lane's. Because the root declares **no dependencies**,
`uv sync` there resolves to an empty set and prunes the environment:

```
$ uv sync --dry-run          # in the worktree, with the shim committed
Would use project environment at: .venv
Resolved 1 package in 39ms
Would create lockfile at: uv.lock
Would uninstall 83 packages
 - aiofile==3.11.1
 - annotated-types==0.7.0
 ...
```

**83 packages**, including the `workbay-protocol` install that the offload lane requires.
So the mandated workaround for Defect 1 re-arms the stale/missing-`workbay_protocol` lane
defect filed in the sibling request: one `uv sync` at the root and the lane is broken again,
with no warning. A consumer following the documented recipe has a loaded footgun committed
to their branch.

It is also **merge scaffolding** — a file that must be manually dropped before merge to
`main`, with nothing enforcing that. If it leaks, `main` carries a root `pyproject.toml`
that prunes any root `.venv` on sync.

**Ask:**
- Fixing Defect 1 removes the need for the shim entirely — that is the preferred resolution.
- If a shim genuinely must remain the recipe, **document the prune hazard loudly** and consider having the tooling generate it *inside the sandbox clone only* (never in the consumer's tracked tree), which would fix both problems at once and require nothing of the consumer.

## Defect 3 — the model pin is not authoritative: Composer (`grok-build`) authors items anyway and quarantines the pass (first-hand)

**Composer should not be pinnable, selectable, or reachable as a fallback for an offload
pass at all.** A pass dispatched with an explicit model pin must run on that model, end to
end, or fail closed before doing any work.

Observed on the VLM-6 `vlm6-report-split` lane, dispatched with `WORKBAY_GROK_MODEL=grok-4.5`
and `dispatch_lane_work(..., model="grok-4.5")`:

```
outcome:       needs_guidance
commit_landed: true
failed_stage:  review
self_verify:   passed   (24 passed in 0.10s)

worker_reports(operation="list", lane_id="vlm6-report-split") -> report 60:
  summary:  "grok-build contamination detected in debug log"
  blockers: ["grok-build authored 2 AssistantItem(s) — contamination quarantine"]
  merge_ready: 0
```

So the pin was set at both the env and the dispatch call, and Composer still authored two
AssistantItems. `_grok_build_contamination_info` (`orchestration/worker_daemon.py:1366`)
correctly detected it, and the engine exposes a dedicated `composer_violation_quarantined`
outcome for exactly this — but detection after the fact is the wrong end of the problem.
The cost is a full dispatch cycle (211s wall, real tokens) producing a commit that is,
per the engine's own contract, **never merge-ready**:

> `api.py:211` — "needs_guidance means the worker submitted a blocked/unverified handoff — never merge-ready."

The consumer is then stuck with a landed, self-verified, code-reviewed commit that cannot be
attested. In this case the work was independently reviewed and verified sound (mutation-tested
guards, adversarial leak probing), so the only real loss was attestation — but that is luck,
not design: a contaminated pass could equally have landed something subtly wrong under a model
the operator never chose.

**Asks:**
1. **Make the pin authoritative.** If a model is pinned, Composer/`grok-build` must never author an item. Route nothing to it, ever, when a pin is present.
2. **Fail closed, early.** If the backend cannot honor the pin, refuse at dispatch/preflight (before the clone, before any turn) rather than discovering contamination at the review stage after a full pass has been paid for.
3. **Make the detection legible without archaeology.** The pass JSON reported only `needs_guidance` + a generic `error` string; the actual cause lived solely in the worker report row. Surface `composer_violation_quarantined` (the outcome that already exists for this) or put the contamination evidence in the pass result, so a caller reading the return value learns the truth without a second lookup.
4. **Document that the env pin is insufficient.** `WORKBAY_GROK_MODEL` currently reads as the remedy for "grok-cli silently runs composer-2.5-fast"; this session shows it does not hold. Until Ask 1 lands, say so.

---

## Reproduction

1. A repo with **no root `pyproject.toml`** (Python packages nested under `apps/*`).
2. `dispatch_lane_work(...)` then `run_offload_pass(...)` against a linked worktree lane.
3. Provisioning fails at `failed_stage=execute` with `No pyproject.toml found ...` (UXP-1 lane observation).
4. Add the virtual-root shim, commit it on the branch → the pass provisions.
5. In that same worktree, run `uv sync --dry-run` → **`Would uninstall 83 packages`** (first-hand, VLM-6, 2026-07-15).

For Defect 3:

1. `dispatch_lane_work(lane_id=..., model="grok-4.5", reasoning_effort="high", ...)` with `WORKBAY_GROK_MODEL=grok-4.5` exported.
2. `run_offload_pass(..., model="grok-4.5", timeout_seconds=1800, turn_timeout_seconds=900)`.
3. Pass returns `needs_guidance` / `commit_landed:true` / `failed_stage:review`, `self_verify.passed:true`.
4. `worker_reports(operation="list", lane_id=<lane>, task_ref=<ref>)` → `blockers: ["grok-build authored 2 AssistantItem(s) — contamination quarantine"]`, `merge_ready: 0` (first-hand, VLM-6, 2026-07-15).

## Workaround used

Committed the virtual-root shim on `feature/vlm-6`, marked `[DROP BEFORE MERGE]` in both the
filename banner and the commit subject, and documented the `uv sync` prune hazard in the file
itself so the next reader does not run it. This is scaffolding, not a fix.

## Cross-references

- [`2026-07-15-offload-lane-venv-workbay-protocol-skew`](../2026-07-15-offload-lane-venv-workbay-protocol-skew/README.md) — sibling defect; Defect 2 here **re-arms** it. The two should probably be fixed together.
- [`2026-07-13-hostgov-remote-backend-cost-class`](../2026-07-13-hostgov-remote-backend-cost-class/README.md) — the host-memory admission defect that blocked these same VLM-6 dispatches before they reached provisioning.
