# Task Plan

> **Metadata**
>
> - **Date**: 2026-03-30
> - **Author**: Claude
> - **Folded from**:
>   - [E12-7-epic-operator-overview-task-plan.md](E12-7-epic-operator-overview-task-plan.md) — epic-scope overview surface
>   - [../9.0/orchestration-tui-monitoring-task-plan.md](../9.0/orchestration-tui-monitoring-task-plan.md) — original TUI monitoring (outdated)
>   - [../../deferred-features/agentic-process-hardening-post-v0.3.0.md](../../deferred-features/agentic-process-hardening-post-v0.3.0.md) — TUI follow-on deferred item
> - **Reference**: [pi-mono/coding-agent](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent) — retained-mode chat TUI with multi-agent visibility

---

> **Status**: Investigation complete. Ready for planning review and prioritization.

---

# Orchestrator Chat TUI

## Objective

Build a terminal UI that shows multi-agent orchestration as a live chat feed — streaming agent turns, tool calls, findings, and lane state changes — so operators can observe and interact with the full orchestration lifecycle from a single surface. Subsumes E12-7 (epic overview) and replaces the outdated 9.0 TUI monitoring plan.

## Problem Statement

The existing `dashboard_tui.py` and `dashboard_live.py` provide a **status table** — lane health, tokens, PID, cycle count — but no visibility into **what agents are doing**. Operators cannot see:

- Agent conversation turns as they stream
- Tool call arguments and results as they execute
- Cross-lane message routing (worker→orchestrator, orchestrator→worker)
- Decision rationale and findings as they're recorded
- When and why a worker stalls, loops, or escalates

The pi-mono coding-agent demonstrates that a scrollback-preserving chat TUI with tool call visibility and token telemetry is both buildable and practically valuable. The existing dashboard is useful as a **health summary pane** but insufficient as the primary operator interface.

## What Already Exists

The investigation found significantly more infrastructure than the 9.0 plan assumed:

| Surface | Location | Status |
| --- | --- | --- |
| Textual dashboard app | `packages/agent-orchestrator-mcp/.../dashboard_tui.py` (351 L) | Working — status table only |
| Rich live dashboard | `packages/agent-orchestrator-mcp/.../dashboard_live.py` (386 L) | Working — polling, no streaming |
| Daemon control | `packages/agent-orchestrator-mcp/.../worker_daemon_ctl.py` (500+ L) | Working — start/stop/pause/resume |
| Worker status files | `.task-state/worker-{lane_id}.status.json` | Live — state, observability, tokens |
| JSONL event logs | `logs/worker-daemon/worker-{lane_id}.jsonl` | Structured — lifecycle events + telemetry |
| Orchestrator events | `logs/daemon/orchestrator.jsonl` | Structured — dispatch, intake, routing |
| Handoff SQLite | `.task-state/handoff.db` (17 tables, FTS indexes) | Full — decisions, findings, blockers, lane messages, turn metrics |
| MCP tools | `get_handoff_state`, `load_session`, `handoff_close_check` | Queryable — dashboard view, close readiness |
| Makefile targets | `make dashboard`, `make worker-daemon-tail`, `make daemon-status` | Operational |

**What the 9.0 plan got wrong**: Assumed 70–80% of the infrastructure needed to be built. The data layer, daemon lifecycle, event logging, and state persistence all exist. The actual gap is the **presentation layer** — a chat-style view of agent activity.

## Constraints

- Must use Python. The orchestration stack is Python; adding a TypeScript TUI (like pi-mono) would introduce a cross-language boundary for accessing SQLite, status files, and JSONL logs.
- Textual is the TUI framework (already in use for `dashboard_tui.py`). Rich is the fallback.
- `CURRENT_TASK.md` remains the single-task generated mirror. This TUI is orthogonal — it shows operational activity, not task state.
- The TUI must be a **read-mostly** surface. Operator actions route through existing `agent-handoff-mcp` / `agent-orchestrator-mcp` commands.
- Must remain local-only (filesystem access to `.task-state/`, `logs/`). Remote/websocket access is a stretch goal.

## Design Principles (from pi-mono)

Key patterns worth adopting from the pi-mono coding-agent:

1. **Scrollback-preserving rendering**: Append to the terminal scrollback rather than full-screen hijack. Native search, scroll, and copy-paste work. Pi-mono uses this exclusively; for us, offer it as the default mode with a Textual full-screen mode as opt-in.
2. **Chat-first layout**: Agent turns, tool calls, and results render as a sequential message stream. This is how developers expect terminal output to work.
3. **Event-driven updates**: Subscribe to events (file watches on JSONL, status file mtime) rather than fixed-interval polling. The existing 10-second poll in `dashboard_tui.py` is too slow for chat-style visibility.
4. **Lane cards as collapsible threads**: Each lane's activity is a conversation thread. Expand to see turns; collapse to see one-line status. Similar to pi-mono's linear message stream but multiplexed across lanes.
5. **Token/cost footer**: Always-visible telemetry bar showing cumulative tokens, model, context pressure, cost. Pi-mono's footer is a good reference.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Header: task-ref, epic, active lanes, clock    │
├─────────────────────────────────────────────────┤
│  Lane Tabs / Thread Selector                    │
│  [all] [lane-a ●] [lane-b ○] [lane-c ●]       │
├─────────────────────────────────────────────────┤
│                                                 │
│  Chat Feed (scrollable)                         │
│  ┌─────────────────────────────────────────┐    │
│  │ 14:23:01 [lane-a] ▶ exec cycle 3       │    │
│  │   Tool: read_file("src/foo.py")         │    │
│  │   Result: 42 lines                      │    │
│  │ 14:23:04 [lane-a] ▶ agent turn          │    │
│  │   "Updating the handler to use..."      │    │
│  │ 14:23:08 [lane-a] ▶ edit_file(...)      │    │
│  │ 14:23:12 [lane-b] ⚠ FINDING medium     │    │
│  │   Missing null check in parse_config    │    │
│  │ 14:23:15 [lane-a] ✓ review pass         │    │
│  └─────────────────────────────────────────┘    │
│                                                 │
├─────────────────────────────────────────────────┤
│  Status Bar: tokens=142k  model=opus  cost=$2.3 │
│  Findings: 2 open  Blockers: 0  Pressure: normal│
└─────────────────────────────────────────────────┘
```

### Data Flow

```
JSONL logs ──tail──► EventAggregator ──events──► ChatFeed renderer
                          │
status.json ──watch──►    │
                          │
handoff.db ──query──►     │──snapshots──► LaneHealth table
                          │
MCP tools ──on-demand──►  │──actions──► Operator commands
```

### Event Normalization

All data sources normalize into a unified `ChatEvent`:

```python
@dataclass
class ChatEvent:
    ts: datetime
    lane_id: str
    event_type: str          # turn, tool_call, tool_result, finding, decision, blocker, state_change
    summary: str             # one-line display text
    detail: str | None       # expandable content (tool args, finding description, agent text)
    severity: str | None     # for findings/blockers
    tokens: TokenUsage | None
```

Sources:
- **JSONL logs** → `turn`, `tool_call`, `state_change` events (real-time via `tail -f` or inotify)
- **handoff.db** → `finding`, `decision`, `blocker` events (polled on change, FTS-indexed)
- **status.json** → `state_change` events (mtime-watched)
- **lane_messages** → `message` events (DB poll, direction-tagged)

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| core | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/chat_tui/` | New package: event aggregator, chat feed, lane threads |
| core | `.../chat_tui/__init__.py` | Package init, public API |
| core | `.../chat_tui/events.py` | JSONL tailer, status watcher, event normalization |
| core | `.../chat_tui/aggregator.py` | Merge events from all sources, maintain per-lane snapshots |
| core | `.../chat_tui/app.py` | Textual app: chat feed, lane tabs, status bar, action bindings |
| core | `.../chat_tui/scrollback.py` | Rich-based scrollback-preserving mode (non-fullscreen) |
| integration | `.../dashboard_tui.py` | Import lane health table from here into chat TUI as a pane |
| build | `mk/orchestrator.mk` | Add `make chat-tui` target |
| docs | `docs/agentic/playbooks/worktree-codex-playbook.md` | Reference the chat TUI for operator monitoring |
| tests | `.../chat_tui/tests/` | Event parsing, aggregation, rendering tests |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/dashboard_tui.py` | Existing status-table TUI; becomes a sub-pane |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/dashboard_live.py` | Data-layer helpers (`_mcp_worker_status`, `_summarize`) to reuse |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/worker_daemon_ctl.py` | Daemon control functions for action rail |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/orchestrator_daemon.py` | Source of orchestrator JSONL events |
| `.task-state/handoff.db` | SQLite state: decisions, findings, blockers, lane messages, turn metrics |
| `logs/worker-daemon/worker-*.jsonl` | Per-lane structured event stream |
| `logs/daemon/orchestrator.jsonl` | Orchestrator lifecycle events |
| `docs/tasks/tech-debt/agent-handoff-mcp-tool-surface-context-budget.md` | MCP tool profile guidance for TUI queries |

## What This Plan Supersedes

### From E12-7 (Epic Operator Overview)

E12-7 proposed a **generated Markdown file** (`CURRENT_EPIC.md`) with ASCII flow diagrams for epic-level scanning. That approach is subsumed:

- **Epic/multi-task view** → the chat TUI's lane tabs + health summary provide the same information with live updates instead of a static generated file
- **ASCII flow/tracks** → deferred; the chat feed naturally shows task progression through event ordering
- **Active-task marker** → the lane tab indicators (`●` active, `○` idle) serve this purpose
- **Findings/blockers visibility** → first-class in the chat feed, not a generated table

If a static epic overview file is still wanted for code-review diffs, it can be a separate `--export-markdown` flag on the chat TUI.

### From 9.0 TUI Monitoring

The 9.0 plan assumed building from scratch. This plan acknowledges the existing infrastructure and scopes work to the actual gap: chat-style event presentation. Specific items folded:

- **Event aggregation** (9.0 Phase 1) → `chat_tui/events.py` and `chat_tui/aggregator.py`
- **TUI surface** (9.0 Phase 2) → `chat_tui/app.py` with Textual
- **Operator actions** (9.0 Phase 3) → Action rail routing through existing daemon control
- **Observability** (9.0 Phase 4) → Token/model telemetry in status bar
- **Stale detection** (9.0 throughout) → Derived lane state from lock/PID/event (logic already in `dashboard_live.py`)

### From Deferred Features

The deferred-features doc gates TUI work on Phase 4/5 process-tooling stability. The MCP tool surface, review-readiness patterns, and handoff semantics are now stable (E12-1 through E12-6 complete). The prerequisite is met.

## Verification Strategy

- Deterministic tests:
  - `PYENV_VERSION=description-service pytest packages/agent-orchestrator-mcp/tests/ -x -q`
  - `PYENV_VERSION=description-service pytest packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/chat_tui/tests/ -x -q`
- Event parsing:
  - Feed real JSONL fixture files through the event normalizer; assert correct `ChatEvent` output
  - Feed status.json snapshots; assert state-change events
- Aggregation:
  - Multi-source merge ordering (events from different sources arrive out-of-order)
  - Lane filtering (show only selected lane's events)
- Rendering:
  - Textual app snapshot tests (if Textual supports them)
  - Scrollback mode output string assertions
- Integration:
  - `make chat-tui TASK=<ref>` starts without error against a real `.task-state/`
  - Existing `make dashboard` still works unchanged

## Slice Delivery

### Slice 1: Event Layer

**Goal**: Normalize all existing data sources into `ChatEvent` objects.

Changes:
- Define `ChatEvent` dataclass and event types
- JSONL log tailer (worker + orchestrator) with file-watch or mtime-based detection
- Status file watcher for state transitions
- Handoff DB poller for new findings, decisions, blockers, lane messages
- Merge/sort events by timestamp across sources

Proof:
- Pytest covers parsing real JSONL fixtures into `ChatEvent` sequences
- Multi-source merge produces correctly ordered event streams
- Missing/empty log files degrade gracefully (no crash, empty feed)

### Slice 2: Scrollback Chat Mode

**Goal**: Render events as a scrollback-preserving Rich output (no fullscreen).

Changes:
- Rich-based renderer that prints chat events to stdout with ANSI styling
- Lane-colored prefixes, severity icons, token summaries
- `--follow` mode that tails new events (like `tail -f` but formatted)
- `--lane` filter flag
- Wire into `make chat-tui --mode scrollback`

Proof:
- Output is readable in plain terminals
- `--follow` picks up new events written to JSONL during the run
- Ctrl-C exits cleanly

### Slice 3: Textual Fullscreen App

**Goal**: Interactive fullscreen TUI with lane tabs, chat feed, and status bar.

Changes:
- Textual app with: header, lane tab bar, scrollable chat feed, status footer
- Lane tab selection filters the chat feed
- "All" tab shows interleaved events from all lanes
- Status bar shows cumulative tokens, model, pressure, open findings/blockers
- Embed existing `dashboard_tui.py` health table as a toggle pane (`h` key)
- Auto-refresh via file-watch events (not polling)

Proof:
- App starts and displays events from a real `.task-state/` directory
- Lane tab switching filters correctly
- Health table toggle works
- Events appear within seconds of JSONL writes

### Slice 4: Operator Actions + Polish

**Goal**: Add safe operator commands and ergonomic refinements.

Changes:
- Action bindings: refresh, redispatch lane, stop lane, pause/resume, open finding detail
- Confirmation guards on destructive actions (stop, redispatch)
- Expandable/collapsible event detail (tool args, finding descriptions)
- Compact summary row for "what should I look at next" (highest-severity open finding, most-stale lane)
- Optional `--export-markdown` for static epic overview output (covers E12-7 use case)

Proof:
- Actions route through existing `worker_daemon_ctl.py` functions
- Confirmation dialog appears before stop/redispatch
- Exported markdown is readable in plain text and code review diffs

---

# Consolidated Checklist

## Context and Ownership

- [ ] Confirmed existing infrastructure in `dashboard_tui.py`, `dashboard_live.py`, `worker_daemon_ctl.py`
- [ ] Confirmed JSONL event format from `logs/worker-daemon/` and `logs/daemon/`
- [ ] Confirmed handoff DB schema supports all query needs (findings, decisions, blockers, lane messages, turn metrics)
- [ ] Confirmed MCP tool budget guidance from `agent-handoff-mcp-tool-surface-context-budget.md`

## Slice 1: Event Layer

- [ ] `ChatEvent` dataclass defined with all event types
- [ ] JSONL log tailer handles worker and orchestrator logs
- [ ] Status file watcher detects state transitions
- [ ] Handoff DB poller picks up new findings/decisions/blockers/messages
- [ ] Multi-source merge sorts by timestamp
- [ ] Graceful degradation when data sources are missing
- [ ] Pytest covers parsing, merging, and edge cases

## Slice 2: Scrollback Chat Mode

- [ ] Rich renderer prints formatted chat events to stdout
- [ ] Lane-colored prefixes, severity icons, timestamps
- [ ] `--follow` mode tails new events
- [ ] `--lane` filter works
- [ ] `make chat-tui` target added to `mk/orchestrator.mk`
- [ ] Clean exit on Ctrl-C

## Slice 3: Textual Fullscreen App

- [ ] Textual app with header, lane tabs, chat feed, status footer
- [ ] Lane tab filtering works
- [ ] "All" tab shows interleaved events
- [ ] Status bar shows tokens, model, pressure, findings, blockers
- [ ] Health table toggle (`h` key) embeds existing dashboard data
- [ ] File-watch-based updates (not fixed-interval polling)
- [ ] App starts cleanly against a real `.task-state/` directory

## Slice 4: Operator Actions + Polish

- [ ] Refresh, redispatch, stop, pause/resume actions wired
- [ ] Confirmation guards on destructive actions
- [ ] Expandable/collapsible event detail
- [ ] "What to look at next" summary
- [ ] Optional `--export-markdown` for static overview (E12-7 use case)

## Review Readiness

- [ ] Existing `dashboard_tui.py` and `dashboard_live.py` still work unchanged
- [ ] No new dependencies beyond textual (already in use) and watchdog (optional, for file events)
- [ ] Tests cover event parsing, aggregation, and rendering
- [ ] Operator docs reference the chat TUI

## Stretch Goals

- [ ] Websocket bridge for remote monitoring
- [ ] Web dashboard backed by the same event aggregator
- [ ] Configurable alerting for `review_exhausted`, repeated blockers, abnormal token burn
- [ ] Compact track heatmap / sparkline summary for long epics
- [ ] Agent turn streaming (partial content visibility as agent writes)

## Success Criteria

- [ ] An operator can watch agent activity across lanes as a live chat feed without tailing raw JSONL
- [ ] Lane selection filters the feed; "all" shows interleaved activity
- [ ] Findings, blockers, and decisions appear in-line with execution events
- [ ] Token/model/pressure telemetry is always visible
- [ ] The TUI never becomes a source of truth — all state comes from JSONL logs, status files, and handoff DB
- [ ] The existing status-table dashboard remains available as a toggle pane
