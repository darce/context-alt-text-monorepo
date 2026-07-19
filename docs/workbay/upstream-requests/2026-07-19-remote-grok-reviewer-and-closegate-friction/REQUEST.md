# Upstream request — remote-grok reviewer not autonomously provisionable, + close-gate orchestration friction

**Target repo:** `darce/agentic-protocol-monorepo` (WorkBay orchestrator + handoff mechanism; skills `review-parallel`, `branch-lifecycle`).
**Consumer:** `context-alt-text-monorepo` (package-mode install).
**Observed release:** `mcp-workbay-handoff==0.2.0`, `mcp-workbay-orchestrator==0.2.0` (as seen from the repo's default `python3`; the `workbay` wrapper version was not resolvable via `importlib.metadata` in that env).
**Session:** VECVLM-1 close-gate → merge (`fb8f3d22`) + VLM-6 sub-track split, 2026-07-19. Orchestrated with `ultracode` (Workflow-based adversarial review). Items below are the friction points that are WorkBay's to fix, ranked by impact.

---

## Item 1 (primary) — the remote-grok *reviewer* cannot be brought up autonomously

### Summary

Repo policy mandates a remote-grok voice in reviews: *"remote grok for /offload (dispatch HIGH effort); /review-parallel at every milestone includes a remote reviewer subagent"* and the session directive was *"dispatch remote grok high effort whenever it makes sense."* The canonical path (per repo memory) is to drive the `grok` CLI **on the OCI gate VM** (`ubuntu@acx-backend`) — `grok -m grok-4.5 --effort high --output-format json` — grounded by rsync, with handoff writes via the Python-API fallback.

This session could **not** use that reviewer voice:

- `acx-backend` is reachable (SSH OK), but `command -v grok` → **`GROK_ABSENT`**. The CLI is simply not installed on the gate VM.
- Bringing it up is **interactive**: `grok` auth is a device-flow/browser step that a headless coding agent cannot complete mid-turn. There is no documented non-interactive install + token-provisioning path, and no persisted credential the VM can reuse across sessions.

Net effect: the "always include a remote reviewer" mandate silently degrades to a Claude-only review whenever the CLI is not already up — with no signal to the agent that the reviewer is missing until it SSHes in and probes. The VECVLM-1 gate ran a 3-lexicon Claude adversarial pass (still strong: graph-theory clean, 4 findings fixed), but the remote voice was absent.

This is distinct from the existing grok requests, which all assume the CLI is **already installed and authed** and target downstream surfaces:
- `2026-07-01-grok-cli-execution-backend` — orchestrator BackendAdapter (dispatch lane work).
- `2026-07-17-offload-preflight-grok-remote-profile` — preflight admission profile.
- `2026-07-17-grok-remote-pass-engine-defects` — pass-engine defects.
- `2026-07-13-hostgov-remote-backend-cost-class` — cost class.

None address **provisioning** (install + persistent auth) of the remote-grok *reviewer* on the gate host.

### Ask

1. A documented, non-interactive **provisioning recipe** for `grok` on the gate VM: install + a headless/device-flow auth that yields a **persisted token** the VM reuses across sessions (so a coding agent never needs an interactive browser step at review time). Ideally wrapped as a `make remote-grok-provision` (idempotent; no-op if already authed) analogous to the existing remote-gate setup.
2. A **preflight/doctor probe** that reports remote-reviewer availability up front — e.g. `remote_reviewer: {available: true|false, host, reason, provision_cmd}` — so `/review-parallel` can state "remote reviewer: unavailable (grok not installed on acx-backend; run `make remote-grok-provision`)" instead of the agent discovering it by hand.
3. Make the remote-grok reviewer a **turnkey lens** in the `review-parallel` skill: when available, it is added as an independent adversarial subagent automatically; when not, the skill emits the actionable provisioning hint rather than silently dropping the voice.

### Reproduction

```
ssh -o BatchMode=yes acx-backend 'command -v grok >/dev/null && echo GROK_PRESENT || echo GROK_ABSENT'
# → GROK_ABSENT  (2026-07-19)
```
There is no repo-provided command to remediate this without an interactive auth step.

---

## Item 2 — worktree overlay gap: lifecycle `make` targets absent in linked worktrees

### Summary

The enforced pre-merge gate is `make handoff-close-check` (`$(LIFECYCLE) handoff-close-check`). Run from the task's **linked worktree** (`context-alt-text-monorepo-vecvlm-1`), it fails:

```
make: *** No rule to make target `handoff-close-check'.  Stop.
```

The `Makefile.d/*.mk` lifecycle overlay is not materialized in linked worktrees, so the very target the pre-merge protocol tells agents to run from the worktree does not exist there. The workaround was to call the Python API directly (`from workbay_handoff_mcp import handoff_close_check; handoff_close_check(task_ref=..., enforce=True, current_commit_sha=...)`) — which works, but is not something most agents will know, and it bypasses the `$(LIFECYCLE)` argument plumbing.

This is another concrete symptom of the overlay-materialization fragility already filed in `2026-06-28-refactoring-lens-and-overlay-mechanism` and `2026-07-08-overlay-surface-config-reconciliation-gaps` — recorded here with the specific target (`handoff-close-check`) and the exact close-gate context in which it bites.

### Ask

Either (a) worktree bootstrap materializes the `Makefile.d`/lifecycle overlay so `make handoff-close-check` / `make close-check` / `make context` resolve in linked worktrees, or (b) the lifecycle targets are made self-contained / resolvable from the worktree (delegating to the root Makefile), so the pre-merge protocol's own instructions run as written from the worktree. If neither, the pre-merge docs should name the Python-API fallback explicitly for worktree contexts.

---

## Item 3 — finding-resolve guard: inconsistent rejection across identical calls

### Summary

`review_findings(operation="update", status="fixed", ...)` is intercepted by `scripts/hooks/guard-review-finding-resolve.py`, which correctly redirects to the commit-backed resolver (`operation="resolve"`). Good design. But in a single batch of **four identically-shaped** update calls (one per finding, differing only in `finding_id`):

- 3 were rejected by the **PreToolUse hook** ("Use the commit-backed finding resolver instead of update(status=fixed)…").
- 1 (`VECVLM-1-ENG-02`) passed the hook and was rejected instead by the **server contract** ("resolution_notes is required when fixing a finding from a newer descendant commit", with a populated `commit_guard`).

Same operation, same shape, two different rejection paths in one batch — the guard did not fire uniformly. The `resolve` op then worked cleanly for all four (`fixed: 4, still_open: 0`).

### Ask

- Make the `update(status=fixed)` → `resolve` guard fire **uniformly** across a batch (pre-validate all items so the caller gets one consistent redirect, not a mix of hook + server errors).
- Surface `operation="resolve"` as the **canonical close path** in the `review_findings` tool description / write-contract examples — currently the resolver is discoverable only by tripping the guard.

---

## Item 4 — orphan task rows: actions/decisions accepted with no live `handoff_state` row

### Summary

VECVLM-1 arrived at this session with pending **next-actions**, **decisions**, and priorities recorded by a prior session — but `get_handoff_state(task_ref="VECVLM-1")` returned `active: null`, and the task was absent from `make tasks` / `list_handoff_rows`. i.e. child-table rows (actions, decisions) existed for a `task_ref` that had **no live `handoff_state` parent row**. This silently blocked `close_slice` / `handoff_close_check` until a row was created via `set_handoff_state` — a non-obvious recovery step. A prior session had been able to write actions against the ref without ever creating the parent row.

### Ask

- On `next_actions(add)` / `record_event` targeting a `task_ref` with no live `handoff_state` row, either **warn** ("no active handoff_state for <ref>; create one with set_handoff_state before close") or **auto-create a minimal stub** so the close-gate is reachable.
- Surface **orphan task_refs** (child rows with no parent `handoff_state`) on the dashboard / in `doctor`, so they are not invisible to `make tasks`.

---

## Notes

- Item 1 is the one flagged by the operator and the highest-leverage: it is the difference between the "always include a remote reviewer" mandate holding vs. silently degrading.
- Items 2–4 are lower severity (all had working in-session workarounds) but each cost a diagnostic round-trip during an otherwise clean close-gate.
