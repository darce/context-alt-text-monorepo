# Implementation Plan: Agent-Agnostic Handoff State via MCP + SQLite

> **Metadata**
>
> - **Task Ref**: `LEGACY-12-0-AGENT-HANDOFF-STATE-MCP`

> Historical note: this document captures the original handoff-state plan that started in `scripts/mcp/unified_server.py`. The shipped implementation was later packaged into `agent-handoff-mcp`; use `docs/agentic/BOOTSTRAP.md`, `docs/agentic/contracts/agent-handoff-mcp.md`, and `packages/agent-handoff-mcp/src/` as the authoritative description of the final server surface and file layout.

## Problem Statement

`CURRENT_TASK.md` is used inconsistently across agent sessions, causing redundant context reads, token-heavy handoffs, and stale state.
The project needs a structured, low-token, agent-agnostic handoff mechanism that works across multiple coding agents without coupling to one vendor runtime.

## Workflow Principles

- SQLite is the canonical handoff state store; markdown is a generated view.
- MCP is the access layer so any MCP-capable agent can read/write state.
- Reads default to compact summaries to minimize token use.
- Writes are append-first for history (`decisions`, `verified_tests`) and status-based for workflow items (`blockers`, `next_actions`).
- Multi-agent safety requires provenance and optimistic concurrency, not silent last-write-wins.

## Terminology

- **Active task**: The current focal work item represented by `task_ref` (for example, `4.12.0`).
- **Singleton state row**: A single-row `handoff_state` table (`id=1`) for active task metadata.
- **Provenance**: Writer identity fields (`agent`, `branch`, `commit_sha`) captured with each mutation.
- **Revision**: Monotonic integer in `handoff_state` used for optimistic locking.

## Current State Analysis

- `/CURRENT_TASK.md` is comprehensive but expensive to read repeatedly.
- Session logs and checklist edits are manual and can drift from real execution state.
- At plan inception, `scripts/mcp/unified_server.py` was the handoff entry point and the intended insertion point for the first implementation pass. The final shipped work was later packaged into `agent-handoff-mcp`.
- No structured store currently exists for blocker lifecycle, test verification history, or next-action prioritization.

## Proposed Solution

Add a lightweight SQLite-backed handoff subsystem exposed via six MCP tools in `scripts/mcp/unified_server.py`:

1. `set_handoff_state`
2. `get_handoff_state`
3. `record_decision`
4. `update_next_actions`
5. `record_test_result`
6. `report_blocker`

Persist state in `/.task-state/handoff.db`.
Keep the database local by default (`.gitignore`), and generate `/CURRENT_TASK.md` from structured state for human review.
At plan inception, the custom MCP server tool count was 10 and the initial target was 16 tools. The shipped implementation was later packaged as `agent-handoff-mcp` and now exposes 27 tools; see `docs/agentic/BOOTSTRAP.md` for the current inventory.
Editor-native tools (for example, `find_definition`, `search_code`, `read_file`) remain outside this count and should be documented separately.

## Schema (v1)

```sql
-- Singleton active-task state
CREATE TABLE IF NOT EXISTS handoff_state (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    task_ref      TEXT NOT NULL,
    objective     TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'in_progress'
                  CHECK (status IN ('in_progress', 'blocked', 'review', 'done')),
    revision      INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_by    TEXT,
    updated_branch TEXT,
    updated_commit_sha TEXT
);

-- Append-only decisions
CREATE TABLE IF NOT EXISTS decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_ref      TEXT NOT NULL,
    session       TEXT NOT NULL,
    decision      TEXT NOT NULL,
    rationale     TEXT,
    agent         TEXT,
    branch        TEXT,
    commit_sha    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Blockers with lifecycle state
CREATE TABLE IF NOT EXISTS blockers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_ref      TEXT NOT NULL,
    description   TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open', 'resolved')),
    agent         TEXT,
    branch        TEXT,
    commit_sha    TEXT,
    resolved_at   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (
        (status = 'open' AND resolved_at IS NULL)
        OR (status = 'resolved' AND resolved_at IS NOT NULL)
    )
);

-- Action queue for short-horizon execution
CREATE TABLE IF NOT EXISTS next_actions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_ref      TEXT NOT NULL,
    action        TEXT NOT NULL,
    priority      INTEGER NOT NULL DEFAULT 100,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'done', 'skipped')),
    agent         TEXT,
    branch        TEXT,
    commit_sha    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Verified test command history
CREATE TABLE IF NOT EXISTS verified_tests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_ref      TEXT NOT NULL,
    command       TEXT NOT NULL,
    passed        INTEGER NOT NULL CHECK (passed IN (0, 1)),
    exit_code     INTEGER,
    result        TEXT,
    session       TEXT NOT NULL,
    agent         TEXT,
    branch        TEXT,
    commit_sha    TEXT,
    verified_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_decisions_task_created
    ON decisions(task_ref, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_blockers_task_status
    ON blockers(task_ref, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_actions_task_status_priority
    ON next_actions(task_ref, status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_tests_task_verified
    ON verified_tests(task_ref, verified_at DESC);
```

## Tool Contract (MCP)

For write tools, `task_ref` is optional: if omitted, the tool defaults to the current `handoff_state.task_ref`. Callers may override explicitly when backfilling another task.

### `set_handoff_state`

- True cold-start-safe upsert for singleton row (`id=1`) for `task_ref`, `objective`, `status`.
- Accept `expected_revision` and fail with conflict if stale on update path.
- Increment `revision` on updates; first insert initializes `revision=0`.

### `get_handoff_state`

- Default compact response:
  - active task metadata
  - open blockers (`top_n_blockers=5`)
  - pending actions (`top_n_actions=5`, priority order)
  - latest decisions (`top_n_decisions=3`)
  - latest verified tests (`top_n_tests=3`)
- Allow optional overrides for each top-N value.
- Include optional `verbose=true` mode for full lists.

### `record_decision`

- Insert append-only decision with rationale and provenance.

### `update_next_actions`

- Support add/update/complete/skip operations.
- Ensure `updated_at` changes on mutation.

### `record_test_result`

- Insert command + `passed` + optional `result` summary + optional `exit_code`.
- `exit_code` is best-effort metadata and not required for callers.

### `report_blocker`

- Add blocker, resolve blocker, or reopen blocker.
- Automatically set/clear `resolved_at` to satisfy table constraints.

## Generated `CURRENT_TASK.md`

- Add a generator path in MCP to render markdown from sqlite state.
- Keep file human-readable and deterministic.
- Add top banner: `DO NOT EDIT: generated from .task-state/handoff.db`.
- Trigger mode: keep an explicit render path for deterministic regeneration. The shipped package also regenerates `CURRENT_TASK.md` on selected write paths so task state stays synchronized without requiring a separate manual render after every mutation.
- Section order:
  1. Objective
  2. Active status
  3. Open blockers
  4. Pending next actions
  5. Recent decisions
  6. Latest verified tests

## Patterns to Follow

### SQLite safety defaults

```python
conn = sqlite3.connect(db_path)
conn.execute("PRAGMA journal_mode=WAL;")
conn.execute("PRAGMA busy_timeout=5000;")
```

### Cold-start-safe upsert with revision guard

```sql
INSERT INTO handoff_state (id, task_ref, objective, status, revision, updated_at, updated_by, updated_branch, updated_commit_sha)
VALUES (1, ?, ?, ?, 0, datetime('now'), ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET
  task_ref = excluded.task_ref,
  objective = excluded.objective,
  status = excluded.status,
  revision = handoff_state.revision + 1,
  updated_at = datetime('now'),
  updated_by = excluded.updated_by,
  updated_branch = excluded.updated_branch,
  updated_commit_sha = excluded.updated_commit_sha
WHERE handoff_state.revision = ?;
```

### Compact read shape

```json
{
  "limits": {"blockers": 5, "actions": 5, "decisions": 3, "tests": 3},
  "active": {"task_ref": "4.12.0", "status": "in_progress", "revision": 17},
  "blockers_open": [{"id": 3, "description": "..."}],
  "actions_pending": [{"id": 11, "priority": 0, "action": "..."}],
  "decisions_recent": [{"id": 42, "decision": "..."}],
  "tests_recent": [{"id": 8, "command": "pytest ...", "passed": 1, "exit_code": 0}]
}
```

## Functions to Change

| File | Line | Change |
| --- | --- | --- |
| `/scripts/mcp/unified_server.py` | 1 | Add sqlite initialization, schema bootstrap, and 6 MCP handoff tools. |
| `/scripts/mcp/mcp-server.sh` | 1 | Confirm environment exposes writable path for `.task-state/` (no behavior change expected). |
| `/.gitignore` | 1 | Ignore `.task-state/` and any temporary exports. |
| `/docs/agentic/BOOTSTRAP.md` | 1 | Update MCP inventory from 10 to 16 custom tools, document new handoff tools and state file location, and list editor-native tools (`find_definition`, `search_code`, etc.) separately. |
| `/docs/agentic/instructions.md` | 1 | Update workflow guidance: use MCP handoff tools as source of truth; `CURRENT_TASK.md` is generated. |

## Related Files

| File | Note |
| --- | --- |
| `/.vscode/mcp.json` | Existing server wiring; no server registration changes expected. |
| `/CURRENT_TASK.md` | Becomes generated output from sqlite state. |
| `/docs/agentic/templates/CURRENT_TASK.template.md` | Keep for fallback/manual mode; mark as secondary path. |

## Token Budget and ROI (Verified)

Assumption: `~1 token ~= 4 bytes` for planning-level estimates.

Measured file sizes (`wc -c`):

- `CURRENT_TASK.md`: 32,296 bytes (`~8,074` tokens)
- `docs/agentic/instructions.md`: 14,818 bytes (`~3,705` tokens)
- `docs/agentic/BOOTSTRAP.md`: 4,583 bytes (`~1,146` tokens)
- Context map range:
  - `docs/agentic/maps/backend.md`: 5,298 bytes (`~1,325` tokens)
  - `docs/agentic/maps/frontend.md`: 4,147 bytes (`~1,037` tokens)
  - `docs/agentic/maps/php-plugin.md`: 3,454 bytes (`~864` tokens)
  - `docs/agentic/maps/integration.md`: 4,167 bytes (`~1,042` tokens)

Verified per-session estimate:

- **Current handoff-only** (read `CURRENT_TASK.md` at start + re-read before editing at end):
  - `~16,148` tokens/session.
- **Proposed handoff-only** (`get_handoff_state` compact + structured writes):
  - `~550-950` tokens/session (response size + write payloads).
- **Handoff-only savings**:
  - `~15,200` tokens/session (`~94-97%` reduction).

Including unchanged context reads (`instructions.md` + one map + optional `BOOTSTRAP.md`):

- **Current total**: `~20,700-22,300` tokens/session.
- **Proposed total**: `~5,100-7,100` tokens/session.
- **Total savings**: `~67-75%` per session.

At 12 sessions/day (3 agents x 4 sessions):

- **Current handoff-only/day**: `~193,776` tokens.
- **Proposed handoff-only/day**: `~6,600-11,400` tokens.
- **Daily handoff savings**: `~182,000-187,000` tokens/day.

Note: `~250,000` daily savings is achievable only under stricter assumptions (for example, counting additional non-handoff rereads as handoff overhead). Under the measured baseline above, the conservative verified range is `~182k-187k` daily tokens saved.

## Risks and Mitigations

- **Risk**: Divergence between generated markdown and sqlite state.
  - **Mitigation**: Generate markdown from DB only; never reverse-sync from markdown.
- **Risk**: Parallel agent writes conflict.
  - **Mitigation**: optimistic locking on singleton row + append-only event tables.
- **Risk**: Tool misuse yields verbose payloads.
  - **Mitigation**: compact defaults and explicit pagination limits.
- **Risk**: Local-only DB not shared between developers.
  - **Mitigation**: document scope clearly; add optional export/import JSON flow in future phase.

---

# Consolidated Checklist

## Completed

- [x] Evaluated schema direction and selected SQLite + MCP as agent-agnostic baseline.
- [x] Defined required hardening for multi-agent safety (`task_ref`, provenance, revision locking, constrained statuses).

## Phase 0: Scaffolding

- [x] Add sqlite bootstrap helpers in the initial `unified_server.py` prototype path; final implementation later moved to the packaged `agent-handoff-mcp` modules.
- [x] Add typed request/response contracts for each new MCP handoff tool.
- [x] Implemented full tool behavior directly (stubs superseded).
- [x] Add `.task-state/` to `.gitignore`.
- [x] Add documented defaults for compact read limits (`5/5/3/3`) and optional `task_ref` auto-default behavior.

## Phase 1: Schema and Storage Layer

- [x] Implement schema creation for all 5 tables + indexes.
- [x] Implement singleton upsert for `handoff_state` with revision conflict detection.
- [x] Implement CRUD helpers for blockers/actions and append helpers for decisions/tests.
- [x] Ensure all write paths capture provenance fields when provided.

## Phase 2: MCP Tool Implementation

- [x] Implement `set_handoff_state` with cold-start-safe upsert plus revision guard.
- [x] Implement `get_handoff_state` compact mode with top-N limits.
- [x] Implement `record_decision` append path.
- [x] Implement `update_next_actions` add/update/status transitions.
- [x] Implement `record_test_result` with required `passed`, optional `exit_code`, and summary.
- [x] Implement `report_blocker` add/resolve/reopen behaviors.

## Phase 3: Generated Markdown View

- [x] Implement markdown renderer from DB state to `CURRENT_TASK.md`.
- [x] Keep an explicit render trigger available for deterministic regeneration.
- [x] Regenerate `CURRENT_TASK.md` automatically on selected write paths in the shipped package so the generated view stays synchronized with task-state mutations.
- [x] Add deterministic ordering and `DO NOT EDIT` header.
- [x] Ensure generated output mirrors compact MCP state categories.

## Phase 4: Verification and Documentation

- [x] Add tests for schema bootstrap idempotency.
- [x] Add tests for revision conflict behavior.
- [x] Add tests for blocker/action status constraints.
- [x] Add tests for compact response token discipline (top-N behavior).
- [x] Update `docs/agentic/BOOTSTRAP.md` with usage examples and the current packaged handoff-server tool count (27 tools).
- [x] Update `docs/agentic/instructions.md` workflow guidance.

## Stretch Goals

- [x] Add `export_handoff_state` and `import_handoff_state` tools for optional cross-machine sharing.
- [x] Add `archive_task_state(task_ref)` to support multiple concurrent task histories.
- [x] Add optional read-only dashboard query for quick terminal inspection.

## Success Criteria

- [x] Agents can hand off state without editing markdown manually.
- [x] `get_handoff_state` returns sufficient context in a compact payload.
- [x] Parallel writes to `handoff_state` cannot silently overwrite each other.
- [x] `CURRENT_TASK.md` is reproducible from sqlite state and remains human-reviewable.
- [x] Existing MCP tools remain functional with no regressions.
