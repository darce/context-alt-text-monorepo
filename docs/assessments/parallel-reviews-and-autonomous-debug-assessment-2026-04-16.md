# Parallel Branch Reviews & Autonomous Bug-Fix Loop — Harness Readiness Assessment

> **Metadata**
>
> - **Date**: 2026-04-16
> - **Task ref**: `MAINT-PARALLEL-AUTONOMOUS-ASSESSMENT`
> - **HEAD SHA**: `5f3bb5ca8efff855f3486aaafe2d908f30d3864b`
> - **Trigger**: User's Claude Code Insights report flagged two "On the Horizon" workflows — *Parallel Agents for Branch Reviews* and *Autonomous Bug Fix With Test Validation* — against a working style that already uses 112 Agent tool calls, multi-vendor harnesses, and an MCP-logged review loop.
> - **User constraint**: avoid vendor lock-in; distribute implementation and review across agents from different harnesses; build on the existing `agent-handoff-mcp` + `agent-orchestrator-mcp` surface rather than replacing it.
> - **Scope**: monorepo root; reads current MCP tool surface, skills in `.claude/skills/`, hooks in `scripts/hooks/` + `.claude/settings.json`, portable manifest in `config/agent-workflows/`.

## TL;DR

1. **The harness is already 70% of the way there.** `agent-orchestrator-mcp` has worktree lanes, worker daemons, a backend registry spanning `codex-cli`, `codex-subagent`, `copilot-host`, `claude-code`, and `local-model-openai`, and `agent-handoff-mcp` already carries lane/agent/model provenance on every finding and test-result write. Cross-vendor portability is real, not aspirational.
2. **Parallel branch reviews** need three modest additions: a coordinator skill, a lane-scoped findings index, and an aggregation MCP op. No new daemon, no new backend abstraction. An orchestrator fan-out pattern already exists for *implementation* lanes — the missing piece is a dedicated *review* fan-out that each lane reviews the same diff from different vendor backends and then a merger agent dedupes.
3. **Autonomous bug-fix loop** is the smaller gap. `handoff_close_check(require_fresh_tests=True)` is already the convergence criterion. The missing piece is the loop driver itself — a skill + optional hook that runs tests, inspects failures, records a finding, calls `investigate`, applies a fix, re-runs, updates the finding to `fixed`, and either closes or escalates after N cycles. No new MCP tools required; this is a skill-layer composition.
4. **The risk is not missing primitives. It is un-enforced convergence.** Today the review loop and fix loop are driven by skill prose that humans read. Turning them autonomous means making `handoff_close_check` and finding-status transitions the actual loop condition — so an agent *cannot* exit early with open findings or stale tests regardless of which vendor's CLI is running it.

## 1.1 Truth vs fiction on parallel-agent context

**Fiction.** "Parallel agents in Claude Code share the same context window." They do not. Claude Code's Agent tool spawns subagents with **fully isolated** contexts — each has its own window and bills independently against the API. There is no shared transcript between parent and child.

**Truth.** The parent conversation only sees the subagent's **returned summary**, not the full transcript. That is the real economic lever: the parent's main thread is protected from bloat and prompt-cache churn, so a coordinator can run many subagents in sequence or parallel without its own context degrading. Each subagent still pays for its own window.

**Practical consequence.** "Parallel" here is not free; it is *cheaper than serial* because each subagent's prompt is scoped tightly to a single review diff or a single fix iteration, not to the whole epic. It is *far cheaper than a worker daemon* because there is no polling loop re-hydrating handoff state every 30 seconds. Worker daemons (`dispatch_lane_work(start_worker=True)`) re-read `get_handoff_state(top_n_*=500)` every cycle and dispatch a fresh backend prompt, costing ~10–30K tokens/cycle × hours of runtime. Three parallel Agent-tool reviewers cost roughly the sum of their individual review prompts, on the order of 50–150K tokens total.

**Vendor-agnosticism caveat.** The Agent tool itself is a **Claude Code harness primitive**, not a portable cross-vendor API. What IS cross-vendor is the *pattern* — ephemeral isolated subagents writing to a shared MCP ledger. Every harness implements it with its own primitive (Codex: `codex exec` subprocess; Copilot: `run_structured_turn` via `copilot-host`). See §2.6.

See §2.6 for the full fan-out taxonomy.

## 1. What the usage report actually asks for

From `~/.claude/usage-data/report.html` (section `#section-horizon`):

> **Autonomous Bug Fix With Test Validation** — "With 51 bug fixes and 48 buggy-code friction events, you're spending enormous cycles on iterative debugging. Claude can autonomously run tests, diagnose failures, implement fixes, and re-run until green… Use Claude Code's headless mode or the Agent tool to spawn a sub-agent that loops: run tests, read failures, edit code, repeat until passing."

> **Parallel Agents for Branch Reviews** — "You already use 112 Agent tool calls and structured handoff reviews — but reviews happen sequentially. Multiple sub-agents can review different branches or epics in parallel, each logging findings via MCP, then a coordinator agent synthesizes a unified report with cross-branch conflict detection."

Two distinct workflows, both leaning on the same two primitives: **structured MCP write provenance** and **headless fan-out**. Both are already present in this repo; what's missing is the glue skill/command that turns them into a single-prompt workflow.

## 2. Current surface inventory

### 2.1 `agent-orchestrator-mcp` — parallel-execution primitives

| Tool | Shape | Parallel readiness |
|---|---|---|
| `manage_worktree_lane` | upsert/close/list lane rows with `lane_id`, `worktree_path`, `branch`, `model`, `backend`, `reasoning_effort` | **Ready** — lane is the unit of parallelism; each carries backend + model metadata for cross-vendor attribution. |
| `dispatch_lane_work` | update dispatch params; optional `start_worker=True` spawns worker daemon subprocess | **Ready** — fire-and-forget spawn already exists. |
| `manage_worker` / `manage_orchestrator` | start/stop/status lifecycle for daemons; `worker.start_all` respects manifest merge order | **Ready for implementation lanes**; not yet used for review-only lanes. |
| `lane_communication` | bidirectional orchestrator↔worker messages (`kind: message | brief`, `direction`) | **Ready** — this is the channel a coordinator would use to feed review briefs to lane reviewers and collect verdicts. |
| `worker_reports` | per-lane terminal reports (`summary`, `changed_files`, `merge_ready`, `test_commands`) | **Ready** — this is already how workers hand back results to orchestrator; reviewers can reuse it. |
| `reconcile_review_findings` | compare open findings against current files, mark stale | **One-way** — removes stale; does not merge cross-lane duplicates on content similarity. |
| `get_latest_slice_review_packet` | fetch latest review packet for task (optionally lane/review-kind scoped) | **Ready** — consumer-side aggregation exists. |
| `run_structured_turn` | synchronous JSON-schema-constrained turn against a bridge backend | **Blocking** — ThreadPoolExecutor + timeout; can't pipeline N turns in one MCP call, but can be called N times concurrently by a coordinator. |
| `list_available_backends` | enumerate registered backends | **Five backends wired**: `codex-cli`, `codex-subagent`, `copilot-host`, `claude-code`, `local-model-openai`. |
| `turn_metrics`, `get_metrics_summary` | per-turn + aggregate telemetry (tokens, phase duration, backend) | **Ready for observability**; no live feedback loop yet. |

### 2.2 `agent-handoff-mcp` — review + test lifecycle

| Capability | Primitive | Gap |
|---|---|---|
| Multi-reviewer findings on same `task_ref` | `review_findings.record`/`batch_record` with `actor={agent, model, model_label, lane_id}`; SQLite WAL handles concurrent writes | No `idx_review_findings_lane_status` → O(N) scan to fetch one lane's findings; no merger op for content-similar findings across lanes. |
| Fix-loop convergence | `handoff_close_check(enforce=True, require_fresh_tests=True, current_commit_sha=…)` → returns blocker list if any finding open, no fresh test_result on HEAD, or no slice-complete decision | **Already the right gate**; just needs a loop driver that treats it as the loop condition. |
| Test-to-finding linkage | `record_event(event_kind="test_result")` stores `(task_ref, lane_id, branch, commit_sha, passed, …)` | No `finding_id` FK on `verified_tests` — a finding does not auto-close when a follow-on test passes; agent must explicitly `review_findings.update(status="fixed", verified_commit_sha=…)`. |
| Cross-vendor invocation | stdio MCP (`agent-handoff-mcp serve-stdio`) + package-root Python API (`from agent_handoff_mcp import …`) + CLI (`agent-handoff-mcp …`) | Three equivalent presentations of the same backend. Codex, Copilot, Claude Code all reach the same ledger. |
| Provenance for attribution | Every write carries `actor` (agent, model, model_label, lane_id, branch, commit_sha) — SHA validated against live git | Coordinator can distinguish "Opus 4.7 reviewer in lane review-a" from "Codex GPT-5 reviewer in lane review-b" from the same row. |

### 2.3 Skills layer

Relevant skills already in place (`.claude/skills/`):

- **`worktree-orchestrator`** — split task across lanes, create worktrees, dispatch briefs, enforce ownership, coordinate merges. *Already parallel-capable for implementation.*
- **`worktree-worker`** — execute a delegated slice inside a lane; stay in owned paths; hand back merge-ready report.
- **`branch-review`** — per-branch or per-lane review pass; writes findings via `review_findings.batch_record`; records a `review_run` verdict. *Single-threaded per invocation; nothing prevents N concurrent invocations against the same `task_ref`.*
- **`investigate`** — root-cause debugging skill with MCP recording discipline. *This is the per-iteration body of an autonomous fix-loop.*
- **`tdd`** — RED-first gate; records failing `test_result` before any edit. *This is the pre-condition of an autonomous fix-loop.*
- **`incremental-implementation`** — vertical-slice implementation with `plan_cursor(require_clean_slice=true)` gating. *This is the post-condition.*

The composition primitive for autonomous fix-loop — `tdd` → `investigate` → `incremental-implementation` → re-run tests → `handoff_close_check` — already exists as four skills. It just isn't wrapped in a loop.

### 2.4 Hooks layer (`.claude/settings.json` + `scripts/hooks/`)

| Hook | Matcher | Effect | Parallel/autonomous relevance |
|---|---|---|---|
| `guard-main-branch` | PreToolUse on Edit/Write | Block code edits on `main` | Would also block an autonomous agent from skipping branch isolation. |
| `guard-task-plan-findings` | PreToolUse on Edit/Write to task plans | Block pasting finding lists into markdown | Keeps findings canonical in MCP for multi-reviewer aggregation. |
| `record-file-touch` | PostToolUse on Edit/Write | Persist changed files to MCP audit trail | Gives a coordinator a "what changed in lane X" query for free. |
| `regenerate-task-views` | PostToolUse on MCP writes | Auto-regen `DASHBOARD.txt` | Coordinator's read-only view stays fresh. |
| `slim-handoff-response` | PostToolUse on `get_handoff_state` | Trim oversized reads | Parallel coordinators reading state don't bloat context. |
| **Missing** | PostToolUse on test-result event | Would trigger next fix-loop iteration | No hook today; fix-loop is manual. |
| **Missing** | PostToolUse on review verdict | Would trigger coordinator merge op | No hook today; aggregation is manual. |

### 2.5 Portable commands (`config/agent-workflows/portable_commands.json`)

Eight managed ids today: `scope`, `branch-lifecycle`, `branch-review`, `handoff-lifecycle`, `incremental-implementation`, `plan-analyze`, `planning-review`, `tdd`. Generator (`scripts/generate_agent_workflows.py`) produces Claude (`.claude/commands/*.md`) and Copilot (`.github/prompts/*.prompt.md`) adapters from one manifest; Codex routes via CLAUDE.md instructions directly. **This is the vendor-portability layer** — the thing that lets a Codex agent run `/branch-review` the same way a Claude agent does.

### 2.6 Fan-out mechanisms and their token profiles

Three mechanisms exist for multi-agent work in this harness. They are not interchangeable, and the cost gap between them is one-to-two orders of magnitude.

| Mechanism | Per-unit cost | Context lifetime | Best for |
|---|---|---|---|
| **Host subagent primitive** (Claude Code Agent tool; Codex `codex exec`; Copilot bridge) | ~7–20K tokens per subagent | single-pass, ephemeral | bounded parallel reviews; bounded fix iterations driven from the main thread |
| **Worker daemon** (`dispatch_lane_work(start_worker=True)`) | ~10–30K tokens per cycle × 30s poll × duration | long-running subprocess | multi-turn implementation lanes running hours/overnight against Codex / Claude-Code / local backends |
| **Synchronous bridge turn** (`run_structured_turn`) | one prompt + one completion against a bridge backend | single blocking call | small JSON-schema-constrained queries to a specific backend from a coordinator script |

**Evidence.** Worker-daemon cycle cost is dominated by `get_handoff_state(sections='findings_open,blockers_open,actions_pending', top_n_*=500)` at `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/handoff_read_shapes.py:15-22`, plus a fresh backend prompt each cycle (`worker_daemon.py:867-880`). Poll interval default is 30s (`worker_daemon.py:817`). Orchestrator daemon is metadata-only and makes no LLM calls (`orchestrator_daemon.py:898-1083, 1254`) — it is not a token cost centre.

**Vendor-agnosticism nuance.** The Claude Code Agent tool is a **host-specific primitive**. It is not portable to Codex or Copilot. What IS portable is the pattern it implements: *parent spawns N ephemeral subagents → each writes findings to `agent-handoff-mcp` via stdio-MCP / Python-API / CLI → parent synthesizes*. Each harness has its own implementation:

| Harness | Ephemeral-subagent primitive | Cross-vendor cost delta |
|---|---|---|
| Claude Code | Agent tool (in-process, isolated) | baseline |
| Codex CLI | `codex exec` subprocess (short-lived, no daemon) | + subprocess spawn overhead (~1–2s, negligible tokens) |
| Copilot | `run_structured_turn` via `copilot-host` bridge | + bridge round-trip (already wired) |
| Plain API (Anthropic / OpenAI-compatible) | direct API call with per-call prompt isolation | + custom coordinator code |

A coordinator skill must therefore declare the **pattern**, not the **primitive**. It must detect the host and choose the matching implementation. The Agent tool is the cheapest and most ergonomic path when running under Claude Code; the other paths preserve cross-vendor portability at modest per-invocation overhead.

**Worker daemons remain correct** for genuinely long-horizon implementation lanes — a backend that needs to chew on a feature slice for an hour, with periodic MCP state re-reads to pick up cross-lane blockers. Do not default to them for reviews or for fix-loops; the poll overhead dominates the actual work.

**Glossary.** In the remainder of this document:

- *Subagent* = ephemeral isolated-context agent, spawned via the host's subagent primitive (above).
- *Worker daemon* = long-running subprocess that polls handoff state on a cycle and dispatches backend turns.
- *Orchestrator* = coordinator process or skill; may be a daemon (current implementation for implementation lanes) or a main-thread skill (new recommendation for parallel reviews).
- *Lane* = the unit of parallelism in the orchestrator model; carries `lane_id`, `backend`, `model`.

## 3. Gap analysis per target workflow

### 3.1 Parallel Agents for Branch Reviews

**What exists today:**

- An orchestrator daemon that can spawn N worker subprocesses with different backends.
- Per-lane provenance on every finding write.
- `batch_record` + WAL give you atomic concurrent writes.
- A review skill any agent can invoke.
- Cross-vendor adapters in the backend registry.

**What's missing to make a user prompt `/review-parallel TASK=<t>` actually run:**

1. **A coordinator skill (`parallel-branch-review` or similar) that spawns ephemeral subagents via the host primitive (§2.6) — not worker daemons.** Takes `task_ref`, a list of reviewer personas (e.g. `[{backend: claude-code, model: opus-4.7}, {backend: codex-cli, model: gpt-5.4}, {backend: copilot-host}]`), detects the host, and spawns N **ephemeral subagents** accordingly: Agent tool when running under Claude Code; `codex exec` subprocess when under Codex; `run_structured_turn` via `copilot-host` when under Copilot. Each subagent reviews a bounded diff, writes findings via stdio-MCP, returns a verdict summary. Coordinator then reads from `review_runs` + `review_findings` and records a synthesized coordinator `review_run`. `dispatch_lane_work(start_worker=True)` remains available as an **escape hatch** for reviews that must survive past the parent session, but it is not the default.
2. **A findings merger op.** `review_findings` already dedupes on `finding_id`; it does not merge two findings that describe the same bug with different IDs. A new MCP op `review_findings.merge(primary_id, duplicate_ids[])` would close duplicates with a `resolution_notes` pointer and let the coordinator actually produce "unified cross-branch report" rather than "concatenated N-reviewer dump." Low-risk: additive, no schema migration needed.
3. **A lane-scoped index.** `idx_review_findings_lane_status` on `(task_ref, lane_id, status)`. One migration, one line. Makes coordinator reads O(log n) per lane instead of O(n).
4. **A `/review-parallel` portable command.** Add to `portable_commands.json`; generator writes adapters for both Claude and Copilot. Codex routes via CLAUDE.md. One manifest entry.

**Estimated effort**: one slice (~½ day). One skill file, one MCP op, one index migration, one portable-command entry, wire-up tests.

**What to not build**: a new daemon. For ephemeral reviews, don't use the *existing* daemon either — default to the host subagent primitive. Reserve `dispatch_lane_work(start_worker=True)` for implementation lanes that genuinely outlive a single coordinator session.

### 3.2 Autonomous Bug Fix With Test Validation

**What exists today:**

- `tdd` skill records RED test_result before any code edit.
- `investigate` skill enforces root-cause discipline with MCP recording before fix.
- `incremental-implementation` skill produces the fix.
- `handoff_close_check(require_fresh_tests=True, current_commit_sha=…)` is the exact convergence condition: no open findings, no pending actions, fresh passing test on current HEAD.
- `review_findings.update(status="fixed", verified_commit_sha=…, verification_evidence=…)` is how a fix is attested.
- `record_event(event_kind="test_result", …)` already SHA-validates against git and stores passed/failed with full actor attribution.

**What's missing to make a user prompt `/auto-fix TASK=<t> TEST_CMD=<cmd>` actually run:**

1. **A loop driver skill (`auto-fix-loop` or similar) that runs in the main thread with bounded reads.** Composes existing skills. Critically, the loop reads handoff state with **identity-only** shaping between iterations (per CLAUDE.md §Bounded Handoff Reads, lines 161-173) and only widens the read when a test fails:
   ```
   # Baseline state read — identity only, ~50-200 tokens
   while not handoff_close_check(enforce=True, require_fresh_tests=True).ok:
       run TEST_CMD → record test_result
       if passed: record_event(decision="auto_fix_converged"); break
       # Widen the read only on failure:
       get_handoff_state(sections="findings_open", detail="summary", top_n_findings=5)
       record finding from first failure
       /investigate that finding
       apply minimal fix
       /tdd slice (add regression test if not already present)
       retry (bounded: max N cycles, e.g. 5)
   if N exhausted: record_event(event_kind="blocker") and escalate
   ```
2. **Optional: a PostToolUse hook on `record_event` with `event_kind=test_result, passed=false`** that re-enters the loop skill. This would make the loop continue autonomously without the agent having to remember to re-invoke it. Opt-in via env var so it doesn't fire during normal TDD work.
3. **Optional: `verified_tests.finding_id` nullable FK.** Would let an agent assert "test T validates fix of finding F"; `handoff_close_check` could auto-close findings whose linked test passed. Nice-to-have, not a blocker — the explicit `review_findings.update` path already works.
4. **A `/auto-fix` portable command.** Same generator pattern; cross-vendor for free.

**Cadence and prompt-cache economics.** Prefer **in-foreground iteration** — the loop runs in the main agent's thread, system prompt stays cache-warm across iterations, and per-iteration marginal cost is just the new turn. If the loop must run in the background via `ScheduleWakeup`, keep `delaySeconds<270` to stay inside the Anthropic 5-minute cache window, or accept a cache miss per tick and amortize it with `delaySeconds>=1200`. The trap is `delaySeconds=300` — worst of both worlds.

**Estimated effort**: one slice. One skill file composing four existing skills, one optional hook, one portable-command entry.

**What to not build**: a new "test runner" MCP tool. Tests run via the existing `TEST_CMD` env var convention (`make slice-start TEST_CMD=…`); result is recorded with the existing `record_event` path. **Do not run the fix-loop as a worker daemon.** Worker daemons re-hydrate `top_n_*=500` handoff state every 30s — five iterations as a daemon costs more tokens than fifty iterations from the main thread.

## 4. Cross-vendor implications

The user's "avoid vendor lock-in" constraint is already the design's backbone. Both proposed skills would preserve it if they:

1. **Write every step through MCP, not through Claude-specific memory.** Each fix-loop iteration records a `test_result` + optional `review_finding.update` + optional `decision`. A Codex agent resuming the same task after a Claude agent crashed reads the same state.
2. **Parameterize the pattern, not the primitive.** The `parallel-branch-review` coordinator should accept `reviewers=[{backend, model}]` AND detect the host harness to pick the right ephemeral-subagent primitive (Claude Code Agent tool / Codex `codex exec` / Copilot bridge; see §2.6). The `auto-fix-loop` is already backend-agnostic because it's pure MCP-ops + shell-tests executed from the main thread.
3. **Route through `portable_commands.json`.** Any new `/command` lives in the manifest, which is already generator-distributed to Claude and Copilot and readable by Codex.
4. **Stay inside contracts.** `docs/agentic/contracts/harness-protocol.yaml` declares `python_api_fallback.required_exports` — new MCP ops added for parallel reviews must also be exported at the package root so a Python-only harness can call them.

The one cross-vendor friction to watch: **`run_structured_turn` today is synchronous and bridge-only** (`codex-subagent`, `copilot-host`). A fully cross-vendor parallel review would either invoke N `codex` CLIs via subprocess (the `dispatch_lane_work(start_worker=True)` path — works today) or extend `run_structured_turn` to accept CLI-backend dispatch via the same ThreadPool. The subprocess path is the right first step; bridge-parity is a later polish.

## 5. What prior work already points here

- **E17-3** (Core Workflow Skills) — formalized skill anatomy and the PostToolUse dashboard-refresh hook. Both proposed skills would be drop-in under that anatomy.
- **E17-4** (Workflow Integrity) — already flagged "cascade cancellation" when agents batch `make context` + ToolSearch in parallel. A lesson for parallel-review design: the coordinator must not race the handoff bootstrap.
- **E17-6** (Phase 3 Retrofit) — 11 skills retrofitted for MCP-native invocation; `make check-skills` validator still to be built. An autonomous-loop skill should land behind that validator when it exists.
- **No prior ADR or epic covers parallel reviews or a self-healing loop** — this is net-new workflow territory, but built on thoroughly-tested primitives.

## 6. Recommended sequencing

One epic, two tasks, both small. Leave implementation slicing to the planning pipeline.

**Task A — "Parallel branch-review coordinator"**
- Skill: `.claude/skills/parallel-branch-review/SKILL.md` + portable command entry. Skill prescribes the **pattern** (ephemeral isolated subagents → MCP findings → coordinator synthesis) and delegates primitive selection to host detection (§2.6).
- MCP op: `review_findings.merge` (additive, no migration).
- Migration: `idx_review_findings_lane_status` (one-line).
- Contract test: a parallel-review dry-run with two fake backends in `packages/agent-orchestrator-mcp/tests/`.
- Docs: `docs/agentic/playbooks/parallel-branch-review-playbook.md`.

**Token envelope — Task A.** Per invocation with 3 reviewers + coordinator using Claude Code Agent tool: ~50–150K tokens total (each subagent: ~2–5K system prompt + ~3–10K review brief + ~5K diff context + ~5K reviewer turns; coordinator synthesis: ~10–20K). Codex `codex exec` subprocess reviewers add negligible tokens but ~1–2s spawn overhead each. Worst-case four large-diff reviewers: ~250K tokens. The equivalent run as worker daemons for one hour: ~3.6–10.8M tokens. Agent-tool/subagent path is one-to-two orders of magnitude cheaper for ephemeral review work. Evidence: `worker_daemon.py:867-880`, `handoff_read_shapes.py:15-22`.

**Task B — "Autonomous fix-test loop"**
- Skill: `.claude/skills/auto-fix-loop/SKILL.md` + portable command entry. Skill runs the loop **from the main thread** with bounded reads (§3.2 pseudocode), not as a worker daemon.
- Optional hook: `scripts/hooks/autofix-on-test-fail.py` (PostToolUse on test_result events; env-var-gated).
- Optional migration: nullable `verified_tests.finding_id` FK.
- Contract test: a seeded failing test + known fix; assert the loop converges and `handoff_close_check` passes.
- Docs: `docs/agentic/playbooks/autonomous-fix-loop-playbook.md`.

**Token envelope — Task B.** Per iteration from the main thread with bounded reads (`sections='identity'` between iterations; full `findings_open` only on failure): ~5–15K tokens. Typical convergence in 3–5 iterations: ~25–75K tokens total. Worst case with deep test output + `investigate` skill reads: ~150K tokens. In-foreground iteration keeps the prompt cache warm and amortizes the system prompt; scheduled wakeups should use `delaySeconds<270` (cache-warm) or `delaySeconds>=1200` (one clean cache miss). Running the same loop as a worker daemon inflates the cost to ~10–30K tokens per 30s cycle — five iterations as a daemon can cost more than fifty in-foreground iterations.

**Sequencing note.** Task A's "turns review throughput into a multiplier" claim now has a ~100K-token cost per invocation under the Agent-tool/subagent pattern — well-bounded. Task B's "collapses 51 × N iterations" payoff is real *only if* the loop uses bounded reads from the main thread; if implemented as a daemon it regresses to the same cost pattern it's trying to replace.

Either task is independently valuable.

## 7. What not to do

1. **Do not build a new orchestration daemon.** The existing one already fans out subprocesses with per-lane backend metadata.
2. **Do not default to worker daemons for ephemeral work.** Worker daemons are the right tool for multi-turn implementation lanes running for hours. For bounded single-pass reviews and for main-thread fix loops, use the host's subagent primitive (§2.6). The poll overhead (10–30K tokens per 30s cycle) dominates the actual work for anything shorter than an implementation lane.
3. **Do not bypass `handoff_close_check` to make the auto-loop "go faster."** It is the convergence condition and the pre-merge gate. Make it the loop condition; don't circumvent it.
4. **Do not hardcode a backend OR a host primitive in the new skills.** Every new skill must accept backend + model as parameters AND detect the host harness so a Codex agent running `/auto-fix` works identically to a Claude Code agent. The Claude Code Agent tool is a *host-specific* optimization; the cross-vendor pattern lives above it.
5. **Do not add review-finding display logic to task plans.** The `guard-task-plan-findings` hook already blocks this, and it matters even more once findings come from N parallel reviewers.
6. **Do not skip the portable manifest.** Any new slash command lives in `portable_commands.json` first; adapters are generated.

## 8. Open questions

- Should the parallel-review coordinator compute a *unanimous* verdict (all reviewers approve) or a *quorum* verdict (k-of-n)? Both are trivial to implement; the policy choice belongs in the skill prose, not the MCP schema.
- How should the auto-fix loop handle the case where the "fix" makes a *different* test fail? Probably: open a new finding for the regression and keep looping. Bounded by cycle-count to prevent infinite flailing.
- Does the coordinator's synthesized review_run want its own `review_mode` label (e.g. `parallel`)? If so, extend the enum — additive.

These are skill-design questions, not harness gaps.

---

## Appendix: evidence trail

- `agent-orchestrator-mcp` tool inventory: sourced from `mcp__agent-orchestrator-mcp__*` tool schemas surfaced via ToolSearch + `packages/agent-orchestrator-mcp/src/`.
- `agent-handoff-mcp` schema claims: sourced from `packages/agent-handoff-mcp/src/agent_handoff_mcp/` and tool schemas; concurrent-write behaviour from SQLite WAL defaults.
- Backend registry contents: `list_available_backends` surface + `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/adapters/`.
- Skills surface: `.claude/skills/` directory; trigger/process claims from each `SKILL.md`.
- Hooks: `.claude/settings.json` + `scripts/hooks/`.
- Portable commands: `config/agent-workflows/portable_commands.json` + `scripts/generate_agent_workflows.py`.
- Usage report quotes: `~/.claude/usage-data/report.html` lines 832–841.
