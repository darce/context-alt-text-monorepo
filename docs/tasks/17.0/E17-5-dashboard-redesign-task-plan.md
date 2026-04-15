# E17-5. Dashboard Redesign — Plain ASCII, Epic-Scoped Tests, Optional ANSI Colour

- **Date**: 2026-04-14
- **Author**: Claude Sonnet 4.6
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-5`
- **Review Coverage Target**: 1

---

## Objective

Redesign `DASHBOARD` (currently `DASHBOARD.md`) as a pure terminal text file: strip all markdown conventions (code fences, `.md` extension), scope the TEST STATUS section to the active epic only (currently lists every task across all history), add hook parity so dashboard refresh is harness-independent, surface workflow-integrity anomalies as a derived section rather than overloading task status, and add an optional ANSI colour layer (low-priority stretch goal).

## Problem Statement

Five concrete defects confirmed in the live dashboard:

1. **`.md` extension implies markdown**: editors, GitHub, and MCP docs treat it as markdown. The file is intentionally not markdown — it uses `====` / `----` underlines and plain ASCII alignment. The extension contradicts the format.

2. **Code fences in ALL TASKS section**: `current_task_rendering._render_dashboard_section` wraps the ASCII task table with triple-backtick fences (lines 570, 575, 588). This renders correctly in a markdown viewer but produces raw fence syntax in a terminal `cat` or IDE plain-text view.

3. **TEST STATUS lists all historical tasks**: `_collect_task_test_status` queries `verified_tests` with no filter, returning 30+ rows spanning all historical tasks across epics. Agents and operators only need test coverage visibility for the current epic (e.g., E17-*, AHMCP-*). Cross-epic historical records are noise at daily operation time.

4. **Dashboard refresh is harness-dependent**: `.claude/settings.json` runs `scripts/hooks/regenerate-task-views.sh` after state-changing MCP writes, but `.github/hooks/terminal-guard.json` has no equivalent PostToolUse hook. In VS Code/Copilot sessions, MCP state can change without an automatic dashboard refresh, so `DASHBOARD` is not guaranteed current across harnesses.

5. **Active-task findings are buried below TEST STATUS**: the renderer emits `TEST STATUS` before `OPEN FINDINGS`, so urgent active-task findings or workflow-integrity anomalies are pushed below a large block of historical test rows. The data exists, but operators have to scroll past low-priority noise to find the reason a task needs attention.

## Constraints

- No change to `CURRENT_TASK.md` — that file is machine-readable for agent handoffs and intentionally uses markdown. Scope is `DASHBOARD` only.
- `RuntimeConfig.dashboard_path` default changes from `workspace_root / "DASHBOARD.md"` to `workspace_root / "DASHBOARD"`. Callers that set `dashboard_path` explicitly are unaffected. Callers using the default must regenerate; the old `DASHBOARD.md` is not auto-deleted.
- ANSI colour must be completely suppressible — `NO_COLOR=1` env var (standard convention) disables it unconditionally. No ANSI escape codes in non-tty writes (file output, CI).
- `_render_dashboard_section` is shared between `CURRENT_TASK.md` and `DASHBOARD` rendering paths. The code-fence removal must not break the `CURRENT_TASK.md` path. Verify with grep before editing.
- Workflow-integrity data must stay derived from handoff state plus live git state. Do not overload persisted task progress status with git-cleanup metadata.

## Current State Analysis

- `config.py:105`: default `dashboard_path = workspace_root / "DASHBOARD.md"`
- `current_task_rendering.py:570,575,588`: three backtick fence lines in `_render_dashboard_section`
- `dashboard_rendering._collect_task_test_status`: queries `verified_tests` with no `task_ref` filter — returns all historical rows
- `dashboard_rendering._collect_epic_decisions`: already uses `_infer_epic_ref(active_task_ref)` to scope decisions — same pattern needed for test status
- `_render_dashboard_md` currently emits `TEST STATUS` before `OPEN FINDINGS`, which hides urgent active-task issues below a long historical section
- `.claude/settings.json` already runs `scripts/hooks/regenerate-task-views.sh` after state-changing MCP writes; `.github/hooks/terminal-guard.json` does not
- `.gitignore:92`: `DASHBOARD.md` — must change to `DASHBOARD`
- `CLAUDE.md`: two plain-text references to `DASHBOARD.md` in MCP fallback and handoff protocol sections
- `api.py`: docstring strings referencing `DASHBOARD.md` in tool descriptions and `close_slice` / `generate_dashboard_md` signatures
- `_render_dashboard_md` signature in `dashboard_rendering.py`: accepts `task_test_status: dict[str, dict] | None` — already structured; caller in `generate_dashboard_md` must pass filtered dict

## Target Outcome

- `DASHBOARD` (no extension) written by default; terminal `cat DASHBOARD` produces clean plain-text
- ALL TASKS table renders without backtick fences — column alignment intact
- TEST STATUS shows only tasks whose `task_ref` matches the current epic prefix (same `_infer_epic_ref` logic used by RECENT DECISIONS)
- Dashboard regeneration is harness-independent: either both Claude and VS Code/Copilot run the refresh hook, or refresh moves into the MCP write path
- A derived `WORKFLOW INTEGRITY` section renders only when branch/worktree anomalies exist, keyed to `target_branch` plus live git state
- Active-task findings and workflow-integrity alerts render before `TEST STATUS`
- ANSI colour (stretch): status values, finding severity labels, test icons colourised when `sys.stdout.isatty()` and `NO_COLOR` unset

## Files and Surfaces to Change

| Surface | File | Change |
|---|---|---|
| Config default | `src/agent_handoff_mcp/config.py` | Default `dashboard_path` from `DASHBOARD.md` → `DASHBOARD` |
| Code fence removal | `src/agent_handoff_mcp/current_task_rendering.py` | Remove backtick lines at 570, 575, 588 from `_render_dashboard_section` |
| Hook parity | `.github/hooks/terminal-guard.json` or MCP write path | Add VS Code/Copilot dashboard-refresh parity or move refresh into write path |
| Test status filter | `src/agent_handoff_mcp/dashboard_rendering.py` | `_collect_task_test_status(conn, epic_ref)` — filter by epic prefix when provided |
| Workflow integrity section | `src/agent_handoff_mcp/dashboard_rendering.py` | Add derived `WORKFLOW INTEGRITY` section based on `target_branch` plus live git state; render only on anomalies |
| Section order | `src/agent_handoff_mcp/dashboard_rendering.py` | Render active-task findings and integrity alerts before `TEST STATUS` |
| ANSI palette (stretch) | `src/agent_handoff_mcp/dashboard_rendering.py` | `_AnsiPalette` dataclass; `_ansi_enabled()` gate; apply to render functions |
| gitignore | `.gitignore` | Line 92: `DASHBOARD.md` → `DASHBOARD` |
| Docs refs | `CLAUDE.md` | Two occurrences of `DASHBOARD.md` → `DASHBOARD` |
| API docstrings | `src/agent_handoff_mcp/api.py` | Occurrences of `DASHBOARD.md` in tool descriptions and docstrings |
| Tests | `tests/test_dashboard_rendering.py` | Verify no fences, epic-scoped test status, ANSI gate |

## Proposed Solution

### Slice 1: Plain-text Format and File Extension

**Goal**: Remove all markdown conventions from the dashboard file and rename the default output path.

Changes:

- `config.py`: change `workspace_root / "DASHBOARD.md"` → `workspace_root / "DASHBOARD"` in the `else` branch of `for_workspace()`.
- `current_task_rendering.py:570,575,588`: delete the three `"```"` string literals from `_render_dashboard_section`. Verify the function is not called on the `CURRENT_TASK.md` render path (it is not — the CURRENT_TASK path calls `_render_current_task_md`, a separate function).
- `.gitignore:92`: `DASHBOARD.md` → `DASHBOARD`.
- `CLAUDE.md`: update two references.
- `api.py`: update docstring occurrences.

Proof:

- `cat DASHBOARD` after regeneration shows no backtick lines
- `ls DASHBOARD.md` → not found; `ls DASHBOARD` → exists
- `make test-handoff` — `test_generate_dashboard_md_writes_file` passes (update assertion to check `DASHBOARD`, not `DASHBOARD.md`)
- `test_generate_dashboard_md_uses_runtime_dashboard_path` passes unchanged (uses explicit path)

### Slice 2: Epic-Scoped Test Results

**Goal**: TEST STATUS shows only tasks from the active epic; cross-epic historical rows are hidden.

Changes:

- `dashboard_rendering._collect_task_test_status(conn, epic_ref: str | None = None)`: when `epic_ref` is set, filter the `verified_tests` query to `WHERE task_ref = ? OR task_ref LIKE ?` using `(epic_ref, f"{epic_ref}-%")` — identical to the `_collect_epic_decisions` filter pattern. When `epic_ref` is `None`, behaviour is unchanged (full history).
- `dashboard_rendering.generate_dashboard_md`: pass `epic_ref` (already collected via `_collect_epic_decisions`) into `_collect_task_test_status`.
- `_render_test_status_section`: no change to rendering — only the input dict changes size.

Proof:

- `get_handoff_state` with active task `E17-4`: `TEST STATUS` shows only `E17-*`, `E17-4-PLAN`, `MAINT-*` tasks (tasks within the E17 family), not `AHMCP-*` or `4.13.3` historical entries
- `make test-handoff` — new test `test_task_test_status_filtered_to_epic`: creates verified_tests rows for two epics; asserts only the matching epic's rows appear in the rendered section

### Slice 3: Refresh Parity and Integrity Alerts

**Goal**: Dashboard freshness is harness-independent, and urgent workflow anomalies render above historical test noise.

Changes:

- Add VS Code/Copilot parity for dashboard regeneration via `.github/hooks/terminal-guard.json`, or move dashboard refresh into the MCP write path so state-changing writes regenerate `DASHBOARD` regardless of harness.
- Add a derived `WORKFLOW INTEGRITY` section in `dashboard_rendering.py` keyed to active/archived snapshot `target_branch` plus live git state. Render only anomalous states such as orphan branch, missing branch, undeleted merged branch, or worktree drift.
- Reorder `_render_dashboard_md` so active-task `OPEN FINDINGS` and `WORKFLOW INTEGRITY` render before `TEST STATUS`.

Proof:

- A state-changing MCP write from either Claude or VS Code/Copilot updates `DASHBOARD` without a manual regeneration step.
- With an active task that has open findings, those findings appear above `TEST STATUS`.
- With no integrity anomalies, `WORKFLOW INTEGRITY` is omitted entirely.

### Slice 4 (Stretch): ANSI Colour

**Goal**: Optional terminal colour on status values, severity labels, and test icons.

Not a priority. Implement after Slices 1–2 are merged and only if terminal use warrants it.

Changes (when prioritised):

- `_ansi_enabled() -> bool`: returns `True` when `sys.stdout.isatty()` and `os.environ.get("NO_COLOR", "") == ""`. File writes always get `False` (pass `to_file=True` flag).
- `_AnsiPalette`: thin dataclass — `green`, `yellow`, `red`, `cyan`, `reset` as class attrs holding escape strings or empty strings depending on `_ansi_enabled()`.
- Apply palette to: status column in `_render_all_tasks_section` (green=done, cyan=in_progress, yellow=blocked, red=review), severity labels in `_render_open_findings_section`, icons in `_render_test_status_section` and `_render_needs_attention_section`.
- Tests: `NO_COLOR=1` in subprocess env → assert no `\x1b` in output.

## Verification Strategy

- Deterministic:
  - `make test-handoff` — all existing tests pass after code-fence removal
  - New test: `test_dashboard_no_fences` — rendered string contains no `` ``` ``
  - New test: `test_task_test_status_filtered_to_epic` — only epic-matching rows returned
  - New test: `test_dashboard_refresh_hook_parity` or equivalent write-path regression proving harness-independent refresh
  - New test: `test_workflow_integrity_section_only_on_anomalies` — integrity section omitted on clean state and present on anomaly
  - Updated test: `test_generate_dashboard_md_writes_file` — asserts filename `DASHBOARD`, not `DASHBOARD.md`
- Runtime:
  - `python -c "from agent_handoff_mcp import generate_dashboard_md; generate_dashboard_md()"` in monorepo root → `DASHBOARD` created, no `DASHBOARD.md` written
  - `cat DASHBOARD | grep '\`\`\`'` → empty (no fences)
  - Active task `E17-4` → TEST STATUS shows only `E17` family tasks

## Lane Decomposition

Single-lane work on `feature/e17-5`. Slices 1 and 2 are independent of each other and can be committed in either order. Slice 3 follows after the text-format changes are stable. Slice 4 (ANSI) remains stretch work.

---

## Consolidated Checklist

### Context and Ownership

- [ ] Read `_render_dashboard_section` in `current_task_rendering.py` to confirm fence lines are dashboard-only (not shared with CURRENT_TASK path)
- [ ] Confirm `_infer_epic_ref` handles all active task_ref formats in use (E17-N, AHMCP-N, MAINT-*)

### Checklist for Slice 1: Plain-text Format and File Extension

- [ ] `config.py` default changed from `DASHBOARD.md` to `DASHBOARD`
- [ ] Three backtick lines removed from `current_task_rendering._render_dashboard_section`
- [ ] `.gitignore` updated: `DASHBOARD.md` → `DASHBOARD`
- [ ] `CLAUDE.md` two references updated
- [ ] `api.py` docstring references updated
- [ ] `test_generate_dashboard_md_writes_file` updated to assert `DASHBOARD`
- [ ] Proof: `cat DASHBOARD` shows no fence lines; `ls DASHBOARD.md` → not found

### Checklist for Slice 2: Epic-Scoped Test Results

- [ ] `_collect_task_test_status` accepts `epic_ref` parameter; filters query when set
- [ ] `generate_dashboard_md` passes `epic_ref` from `_collect_epic_decisions` result
- [ ] New test `test_task_test_status_filtered_to_epic` passes
- [ ] Proof: active E17-4 task → TEST STATUS shows ≤10 E17-family rows, not 30+ cross-epic rows

### Checklist for Slice 3: Refresh Parity and Integrity Alerts

- [ ] VS Code/Copilot dashboard refresh parity added, or refresh moved into MCP write path
- [ ] Derived `WORKFLOW INTEGRITY` section renders only on anomalies
- [ ] Active-task findings and integrity alerts render before `TEST STATUS`
- [ ] Tests cover hook parity or write-path parity and anomaly-only integrity rendering

### Checklist for Slice 4: ANSI Colour (Stretch)

- [ ] `_ansi_enabled()` returns False when `NO_COLOR=1` or writing to file
- [ ] Palette applied to status, severity, test icons
- [ ] Test: `NO_COLOR=1` subprocess → no `\x1b` codes in output

## Review Readiness

- [ ] `make test-handoff` green after each slice
- [ ] No change to `CURRENT_TASK.md` rendering (not in scope)
- [ ] No change to `RuntimeConfig` fields — only the default value changes

## Success Criteria

- [ ] `DASHBOARD` (no extension) is written by default; no `DASHBOARD.md` created
- [ ] ALL TASKS section renders without any backtick fences in plain-text output
- [ ] TEST STATUS section shows only tasks whose task_ref matches the active epic prefix
- [ ] Dashboard refresh is harness-independent after state-changing MCP writes
- [ ] Workflow-integrity anomalies surface in a dedicated derived section without changing task progress status
- [ ] Active-task findings or integrity alerts appear before `TEST STATUS`
- [ ] `make test-handoff` passes with new tests for fence absence and epic scoping
