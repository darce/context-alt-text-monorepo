# Development Lifecycle Map

> Primary navigation surface. Planning stages (P) and implementation stages (I) both run on the task branch once an artifact will be written.
> Full detail: [planning-pipeline.md](rules/planning-pipeline.md) · [development-workflow.md](rules/development-workflow.md)

---

## Stage Map

> **Phase 2 note:** Rows P0, P2, P3, and P3.5 use the E17-3 skill-based entry points (`scope`, `plan-analyze`, `planning-review`) on the task branch once they emit artifacts. The full planning and branch review guides remain the canonical checklist/reference surfaces behind those entry points.

| Step | Stage | Entry point | Skill | Key MCP tools | Exit gate |
|------|-------|-------------|-------|---------------|-----------|
| P0 | Intake _(new features/epics only)_ | (in session) | `scope` _(E17-3)_ | `AskUserQuestion`, `record_event(decision)` | Q&A recorded in MCP; scope one-pager in `docs/scopes/`; Not-Doing list present |
| P1 | Scope | `make context` | `investigate` | `set_handoff_state` | Problem traced to code; task ref initialized |
| P2 | Assess | `make plan-analyze DOC=<path>` _(E17-3)_ | `plan-analyze` _(E17-3)_ | `review_findings(planning)` + `review_runs(record)` | All findings cite `file:line`; triage run recorded with `plan-analyze-*` session |
| P3 | Spec | `make plan-review DOC=<path>` _(E17-3)_ | `planning-review` _(E17-3)_ | `review_findings` + `review_runs(record)` | ≥1 review run recorded; 0 open findings |
| P3.5 | ADR _(conditional)_ | `make plan-review DOC=<path>` _(E17-3)_ | `planning-review` _(E17-3)_ | same | Alternatives documented; spec updated |
| P4 | Task plan | `make plan-analyze` → `make plan-review` _(E17-3)_ | `planning-review` _(E17-3)_ | same | Slices trace to spec; `target_branch` declared |
| I1 | Branch start | `make task-start TASK=<id> OBJECTIVE="..."` | `branch-lifecycle` | `set_handoff_state(target_branch)` | Worktree + branch exist before first planning artifact; `make context` clean |
| I2 | Slice: RED | `make slice-start` | `tdd` | `record_event(test_result, passed=false)` | Failing test recorded **before** any implementation edit |
| I3 | Slice: GREEN | _(edit files)_ | `incremental-implementation` | _(none until commit)_ | Tests pass; ≤100 new lines since last test run |
| I4 | Slice: COMMIT | `make slice-commit MSG="..."` | `branch-lifecycle` | `close_slice` → `render_handoff(kind='current_task')` | `slice_complete` decision recorded; `CURRENT_TASK.json` regenerated |
| — | _(repeat I2–I4)_ | | | | |
| I5 | Review | `make review-run` | `branch-review` | `review_findings(batch_record)` + `review_runs(record)` + `record_event(decision)` | 0 open findings; verdict decision + review-run recorded |
| I6 | Gate | `make handoff-close-check` | `branch-lifecycle` | `handoff_close_check(enforce=True, current_commit_sha=HEAD)` | `ok=true`; all five pre-merge requirements met |
| I7 | Finish | `make task-finish TASK=<id>` | `branch-lifecycle` | `update_task_status(done)` + `archive_task_state` + `render_handoff(kind='current_task')` + `render_handoff(kind='dashboard')`; `manage_worktree_lane(close)` when orchestrated lanes were opened | Task archived; both views regenerated; branch deleted; root worktree on `main` |

---

## Make Target Reference

| Target | Stage | What it does |
|--------|-------|-------------|
| `make context` | All | Verify worktree + branch alignment against active MCP task |
| `(scope skill — in session)` _(E17-3)_ | P0 | Ask 3–5 questions before any planning output; record Q&A as MCP decisions |
| `make plan-analyze DOC=<path>` _(E17-3)_ | P2, P4 | Agent-assisted: six detection passes against a planning artifact |
| `make plan-review DOC=<path>` _(E17-3)_ | P3–P4 | Agent-assisted: planning-review skill loop against an artifact |
| `make task-start TASK=<id>` | I1 | Create feature branch + linked worktree + register MCP target in one shot |
| `make slice-start` | I2 | Record `test_result(passed=false)` as the TDD gate for the current slice |
| `make slice-commit MSG="..."` | I4 | `git commit` + `close_slice` + `render_handoff(kind='current_task')` atomically |
| `make review-ready` | I4→I5 | Check review readiness; print NOT READY reasons |
| `make review-run` | I5 | Agent-assisted: branch-review skill; records findings + verdict |
| `make handoff-close-check` | I6 | `handoff_close_check(enforce=True, current_commit_sha=HEAD)` |
| `make task-finish TASK=<id>` | I7 | `update_task_status(done)` + `archive_task_state` + regenerate `CURRENT_TASK.json` + `DASHBOARD.txt`; worktree remove + branch delete |

---

## MCP Tool Quick Reference

| Domain | Tool | When |
|--------|------|------|
| Session start | `load_session` | Combined `get_handoff_state` + open findings; use at every session start |
| Identity check | `get_handoff_state(sections="identity")` | Routine — returns `active` + `limits` only |
| Task init / update | `set_handoff_state` | New task or objective change |
| Decision | `record_event(event_kind="decision")` | After any meaningful decision; required before review or completion |
| Test gate | `record_event(event_kind="test_result", passed=false)` | Before writing implementation (TDD gate) |
| Test evidence | `record_event(event_kind="test_result", passed=true)` | After passing test run; pre-merge gate requires this |
| Blocker | `record_event(event_kind="blocker", operation="add")` | Immediately when blocked |
| Slice close | `close_slice` | Via `make slice-commit`; enforces required sections + atomic write |
| Findings (3+) | `review_findings(operation="batch_record")` | All findings from one review pass — one atomic write |
| Findings (1–2) | `review_findings(operation="record")` | Single finding |
| Finding resolution | `review_findings(operation="update", status="fixed"\|"deferred"\|"wontfix")` | After resolving a finding |
| Pre-merge gate | `handoff_close_check(enforce=True)` | Must pass before merge; never bypass with `enforce=False` |
| Task completion | `update_task_status(status="done")` then `archive_task_state` | In that order — **never archive while `in_progress`** |
| Search history | `search_handoff(query=...)` | Find prior decisions/findings without reloading full state |

**workbay-orchestrator-mcp** (load via `ToolSearch select:mcp__workbay-orchestrator-mcp__*`):

| Domain | Tool | When |
|--------|------|------|
| Lane registration | `manage_worktree_lane(action="open")` | At `make task-start`; registers the lane so worker daemons can be dispatched |
| Lane close | `manage_worktree_lane(action="close")` | Step 2 of invariant close sequence — **before** `archive_task_state` |
| Task switch | `switch_task` | Transitioning between tasks mid-session; verifies current task is `done` or `blocked` before switching |
| Plan cursor | `plan_cursor` | Track which plan item the current slice advances; `require_clean_slice` guard blocks upsert if open findings exist |
| Pre-review triage | `get_review_findings_summary` | Summary of existing findings before starting detection passes in `branch-review` skill |
| Finding repair | `reconcile_review_findings` | Dedup and repair finding state before detection passes when prior review runs exist |
| Worker output | `worker_reports` | Query worker lane results during orchestrated multi-lane execution |
