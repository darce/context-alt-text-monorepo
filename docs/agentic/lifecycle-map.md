# Development Lifecycle Map

> Primary navigation surface. Planning stages (P) run on `main`. Implementation stages (I) run on a feature branch.
> Full detail: [planning-pipeline.md](rules/planning-pipeline.md) · [development-workflow.md](rules/development-workflow.md)

---

## Stage Map

| Step | Stage | Entry point | Skill | Key MCP tools | Exit gate |
|------|-------|-------------|-------|---------------|-----------|
| P1 | Scope | `make context` | `investigate` | `set_handoff_state` | Problem traced to code; task ref initialized |
| P2 | Assess | `make plan-analyze DOC=<path>` | `plan-analyze` | `review_findings(analysis)` | All findings cite `file:line`; priority ordered |
| P3 | Spec | `make plan-review DOC=<path>` | `planning-review` | `review_findings` + `review_runs(record)` | ≥1 review run recorded; 0 open findings |
| P3.5 | ADR _(conditional)_ | `make plan-review DOC=<path>` | `planning-review` | same | Alternatives documented; spec updated |
| P4 | Task plan | `make plan-analyze` → `make plan-review` | `planning-review` | same | Slices trace to spec; `target_branch` declared |
| I1 | Branch start | `make task-start TASK=<id> OBJECTIVE="..."` | `branch-lifecycle` | `set_handoff_state(target_branch)` | Plan on `main`; worktree + branch exist; `make context` clean |
| I2 | Slice: RED | `make slice-start` | `tdd` | `record_event(test_result, passed=false)` | Failing test recorded **before** any implementation edit |
| I3 | Slice: GREEN | _(edit files)_ | `incremental-implementation` | _(none until commit)_ | Tests pass; ≤100 new lines since last test run |
| I4 | Slice: COMMIT | `make slice-commit MSG="..."` | `branch-lifecycle` | `close_slice` → `generate_current_task_md` | `slice_complete` decision recorded; `CURRENT_TASK.md` regenerated |
| — | _(repeat I2–I4)_ | | | | |
| I5 | Review | `make review-run` | `branch-review` | `review_findings(batch_record)` + `review_runs(record)` + `record_event(decision)` | 0 open findings; verdict decision + review-run recorded |
| I6 | Gate | `make handoff-close-check` | `branch-lifecycle` | `handoff_close_check(enforce=True, current_commit_sha=HEAD)` | `ok=true`; all five pre-merge requirements met |
| I7 | Finish | `make task-finish TASK=<id>` | `branch-lifecycle` | `update_task_status(done)` + `archive_task_state` + `generate_current_task_md` | Task archived; branch deleted; root worktree on `main` |

---

## Make Target Reference

| Target | Stage | What it does |
|--------|-------|-------------|
| `make context` | All | Verify worktree + branch alignment against active MCP task |
| `make plan-analyze DOC=<path>` | P2, P4 | Agent-assisted: six detection passes against a planning artifact |
| `make plan-review DOC=<path>` | P3–P4 | Agent-assisted: planning-review skill loop against an artifact |
| `make task-start TASK=<id>` | I1 | Create feature branch + linked worktree + register MCP target in one shot |
| `make slice-start` | I2 | Record `test_result(passed=false)` as the TDD gate for the current slice |
| `make slice-commit MSG="..."` | I4 | `git commit` + `close_slice` + `generate_current_task_md` atomically |
| `make review-ready` | I4→I5 | Check review readiness; print NOT READY reasons |
| `make review-run` | I5 | Agent-assisted: branch-review skill; records findings + verdict |
| `make handoff-close-check` | I6 | `handoff_close_check(enforce=True, current_commit_sha=HEAD)` |
| `make task-finish TASK=<id>` | I7 | Merge teardown: worktree remove + branch delete + MCP archive |

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
| Task completion | `update_task_status(status="done")` then `archive_task_state` | In that order |
| Search history | `search_handoff(query=...)` | Find prior decisions/findings without reloading full state |

---

## ctx7 Entry Points

Use `context7` (load via `ToolSearch select:mcp__context7__*`) when implementation depends on upstream library behavior. Do **not** use for repo-local rules, contracts, or task plans.

| Trigger | Library ID hint |
|---------|----------------|
| FastMCP tool registration, discriminated union patterns | `fastmcp` |
| Pydantic v2 model validators, field coercion | `pydantic` |
| SQLAlchemy 2.x session / query patterns | `sqlalchemy` |
| React hooks, component lifecycle | `react` |
| Radix UI component API, accessibility props | `radix-ui` |
| WordPress REST API, hook system | `wordpress` |
| MCP SDK protocol, transport options | `modelcontextprotocol/python-sdk` |

Static fallback when ctx7 is unavailable: [docs/agentic/maps/tech-stack.md](maps/tech-stack.md).
