# ACE + ctx7 Documentation Evolution

## Problem Statement

Agent instruction files carry ~400 lines of generic library reference material (Radix UI patterns, Vitest hoisting rules, pytest-asyncio setup, React state anti-patterns) that agents load on every session. This inflates context pressure, requires manual maintenance when libraries update, and contradicts the existing ACE self-correction principles already stated in `instructions.md`. Adopting the ACE framework's Generator/Reflector/Curator model for documentation evolution; combined with ctx7 for on-demand library docs; can eliminate static library reference, reduce per-session token load, and make instruction documents self-improving.

## Workflow Principles

- **Project-specific rules stay in-repo; library reference delegates to ctx7.** No agent instruction file should teach upstream API behavior that ctx7 can serve on demand.
- **Every instruction paragraph must have earned its place.** ACE's Reflector/Curator cycle validates rules against real execution outcomes; rules that never trigger or duplicate tooling checks get pruned.
- **Incremental delta updates over full rewrites.** ACE's grow-and-refine principle prevents context collapse (iterative rewriting eroding critical details over time).
- **Helpful/harmful counters drive retention.** Each rule accrues evidence of value; rules with zero helpful and nonzero harmful evidence are pruning candidates.
- **Architectural invariants are first-class rules.** Package-boundary invariants discovered through analysis (e.g., keeping `core.py` free of orchestration logic) are codified as regression guards with ACE evidence tracking, not left as informal review expectations.
- **Stable service URLs over scattered port literals.** Tools like portless centralize port-to-hostname mapping; instruction files and configs reference stable `.localhost` names instead of hardcoded port numbers.

## Terminology

- **ACE (Agentic Context Engineering)**: Installable Python library and framework where contexts evolve as structured playbooks through Generator/Reflector/Curator LLM pipelines. Published at ICLR 2026; repo at [github.com/ace-agent/ace](https://github.com/ace-agent/ace). ACE has two aspects: (1) the **runtime** (`from ace import ACE`; runs offline/online adaptation loops that automatically evolve playbooks from task execution data), and (2) the **format conventions** (strategy bullets with `helpful/harmful` counters, grow-and-refine updates, curation rules). This task adopts ACE's format conventions as a manual documentation practice. Runtime integration is a stretch goal; see Stretch Goals for the evaluation path.
- **Playbook**: ACE's term for an evolving context document. In this project, each guideline file (`rules/*.md`) is a playbook.
- **Strategy bullet**: A discrete rule or convention in a playbook, tracked with `helpful=N harmful=M` counters per ACE's structured format.
- **ctx7**: MCP server that fetches current upstream library/framework documentation on demand. Replaces static library reference in instruction files.
- **Context pressure**: The token-budget classification (`normal` / `elevated` / `high`) from `lane_prompt.py`'s `_measure_context_utilization()`. Lower instruction-file size directly reduces pressure.
- **Generic library reference**: Content in a guideline file that restates upstream documentation (e.g., "Radix `asChild` passes props to child element"). ctx7 can serve this.
- **Project-specific rule**: Content that cannot be derived from any upstream source (e.g., "use `acx-` class prefix", "Sovereign Sync Layer architecture"). Must stay in-repo.
- **Portless**: Tool that maps services to stable `.localhost` hostnames (e.g., `backend.localhost` instead of `localhost:8000`). Eliminates scattered hardcoded port numbers across config and source files.
- **Observability metrics**: Aggregate measurements derived from JSONL event logs, `handoff.db` state, `mcp-artifacts.db`, and instruction file structure that quantify token efficiency, context pressure trends, FTS5 retrieval effectiveness, and documentation health across a task lifecycle. Periodically surfaced via `make ace-metrics` and optional dashboard integration.
- **Metrics snapshot**: A point-in-time JSON record appended to `.task-state/metrics.jsonl` capturing token burn, context pressure, FTS5 retrieval stats (indexed record counts, not query-frequency), lane health, and ACE bullet aggregates for time-series analysis.
- **ACE autorun**: Automatic execution of ACE reflection detection triggered by orchestration events (post-review finding recording, threshold crossings). Worker and orchestrator daemons log detected rule references to a side file; instruction-file counter updates happen separately via `make ace-reflect` in the orchestrator root (not from daemon context).
- **Reflection hook**: A post-review step in `worker_daemon.py` that scans new findings for rule ID patterns (`[sr-NNN]`, `[rg-NNN]`), appends `{cycle, finding_id, rules: [{rule_id, contradicts}], timestamp}` records to `.task-state/ace_reflect_log.jsonl`, and emits an `ace_reflect_detected` event. Contradiction verdict is stored per rule_id so a finding that references multiple rules with different polarity is represented correctly. It does not edit instruction files. Instruction-file counter updates are applied later by the operator via `make ace-reflect`.

## Current State Analysis

- `instructions.md` already declares ACE self-correction principles (inclusion criteria, self-correction protocol) but these are informal prose; no structured tracking, no reflection cycle, no pruning automation.
- The ACE runtime (`from ace import ACE`) can automate playbook evolution using offline adaptation (batch process historical task data) or online adaptation (live updates during task execution). The `agent-handoff-mcp` database already stores the training signal ACE needs: review findings, test results, decisions, and blockers. Runtime integration adds an LLM dependency and requires a custom `DataProcessor`; it is a stretch goal, not in scope for this task.
- Four guideline files carry significant generic library reference:
  - `RADIX_UI_COMPONENT_GUIDE.md` (~288 lines; ~50% generic: `asChild`, controlled/uncontrolled, a11y checklist, priority tables)
  - `testing-typescript.md` (~181 lines; ~60% generic: `vi.mock` hoisting, `waitFor`, TanStack Query config, MSW)
  - `testing-python.md` (~157 lines; ~40% generic: pytest-asyncio, `AsyncMock`, SQLAlchemy in-memory fixtures)
  - `frontend-guidelines.md` (~201 lines; ~50% generic: React state anti-patterns, hook heuristics, a11y checklist)
- Three files are predominantly project-specific and should not be trimmed: `backend-python-guidelines.md`, `backend-php-guidelines.md`, `testing-php.md`.
- No ctx7 directives exist in any guideline file; zero external doc references beyond static markdown links.
- `.vscode/mcp.json` registers only `altcontext-mcp` (agent-handoff-mcp). No ctx7 registration.
- The `lane_prompt.py` context-pressure system already demonstrates that smaller instruction payloads directly improve agent session quality (fewer sessions starting at "elevated" or "high" pressure).
- Port numbers are scattered across ~37 references in 8+ files (docker-compose, `.env`, PHP controllers, Makefiles, CI workflows, MCP adapter defaults). At least 4 distinct service ports are hardcoded: `5432` (Postgres), `8000` (FastAPI backend), `7860` (archived recognition), `55432` (Docker-mapped Postgres). Portless could centralize these into stable `.localhost` hostnames.
- The `agent-handoff-mcp` split analysis (MCP server architecture review) identified a clean one-directional dependency seam between handoff state (`core.py`) and orchestration modules. The key invariant; keeping `core.py` free of orchestration logic; is currently enforced only through informal code review. This is a candidate for a tracked ACE regression guard.
- The orchestration-hardening and context-retrieval 8.0 tasks have built substantial telemetry infrastructure (per-turn token tracking, context pressure measurement via `_measure_context_utilization()`, JSONL event persistence, FTS5 search over handoff state and artifacts), but no aggregation or trending tooling exists to surface these signals periodically. `dashboard_live.py` shows point-in-time status; there is no end-of-task summary, no time-series view, no documentation health metrics, and no connection between ACE strategy bullets and the observability data that should drive their evolution.
- ACE reflection is currently fully manual: agents must remember to update counters during reviews. No automated pathway exists to detect when a review finding references or contradicts an instruction rule and update counters accordingly. Existing per-turn observability (`_record_observability()` in `worker_daemon.py`) and per-lane health signals (`_check_lane_health()` in `orchestrator_daemon.py`) collect the raw data but do not aggregate it into actionable metrics reports.

## Proposed Solution

Six-phase approach:

1. **ctx7 + portless integration** -- register ctx7 as an MCP server, install and configure portless for stable service URLs, create a tech-stack manifest, add ctx7 directives to guideline files.
2. **Guideline trimming** -- remove generic library reference from the four candidate files, replacing with ctx7 fetch directives. Replace hardcoded port references with portless `.localhost` hostnames where applicable. Keep all project-specific rules.
3. **ACE-structured playbook format** -- formalize the existing ACE self-correction protocol with structured strategy bullets, helpful/harmful tracking metadata, and a documented reflection/curation cycle that agents execute during branch reviews or task completions.
4. **Architectural invariant guards** -- codify package-boundary invariants discovered through architectural analysis as tracked ACE regression guards (e.g., `core.py` must remain free of orchestration logic, orchestration modules must use late-binding imports to avoid load-time coupling).
5. **Observability metrics tooling** -- build a metrics aggregation script that reads JSONL worker/orchestrator logs, `handoff.db`, `mcp-artifacts.db`, and instruction files to produce periodic reports on token efficiency, context pressure trends, FTS5 retrieval stats, lane health, and ACE documentation health. Surface via `make ace-metrics`, optional MCP tool, and dashboard integration. Links to improvements from orchestration-hardening (token burn, context pressure, exhaustion streaks), orchestration-context-retrieval (artifact indexing, FTS5 search), and structured-memory-search (handoff FTS5).
6. **ACE autorun triggers** -- add a post-review hook in `worker_daemon.py` that scans new findings for rule ID references and appends per-rule `{cycle, finding_id, rules: [{rule_id, contradicts}], timestamp}` records to `ace_reflect_log.jsonl`; add an advisory event in `orchestrator_daemon.py` that fires after `dispatch_complete` when unprocessed log entries exceed a configurable threshold, reminding the operator to run `make ace-reflect`; add `make ace-reflect` and `make ace-curation-report` targets for manual counter updates and pruning candidate identification from the orchestrator root.

Phases 0-4 adopt ACE's format conventions (strategy bullets, evidence counters, curation rules) as a manual documentation practice. ctx7 offloads generic library reference; portless eliminates hardcoded port scattering. Phases 5-6 close the feedback loop: Phase 5 surfaces the metrics that validate whether the documentation changes are improving agent outcomes, and Phase 6 automates the ACE reflection cycle that was manual in Phase 3. Full ACE runtime integration remains a stretch goal evaluated after Phase 6 completes.

### Why not install ACE runtime immediately?

ACE's runtime automates what Phases 0-4 do manually, but it requires: (1) a `DataProcessor` implementation that maps handoff.db schema to ACE's train/val/test sample format, (2) LLM API keys and token budget for Generator/Reflector/Curator models, (3) a decision on adaptation mode (offline batch vs online live). Installing the format first lets us validate that the strategy-bullet structure works for this project's rule types before committing to the automation layer. Phase 6's lightweight reflection hooks provide the stepping stone: they automate counter updates using regex-based rule reference detection without requiring the full ACE LLM pipeline. If Phase 6's hooks prove insufficient (e.g., false positive rate >20% on rule reference detection, or counters diverge significantly from expert assessment), the Stretch Goals section describes the full runtime integration path.

## Patterns to Follow

### ctx7 Fetch Directive (header pattern for trimmed files)

```markdown
# Frontend Guidelines (Project Conventions)

> **Library reference**: Use ctx7 to fetch current docs for the libraries listed
> in [maps/tech-stack.md](../maps/tech-stack.md#frontend) before starting work.
> This file covers only project-specific conventions.
```

### ACE Strategy Bullet Format (adapted for instruction files)

```markdown
### Short Rules

<!-- ACE playbook: each rule is a strategy bullet with evidence counters.
     helpful = times this rule prevented a real failure
     harmful = times this rule caused unnecessary friction or was wrong
     Rules with helpful=0 harmful>=2 are pruning candidates.
     Update counters during branch reviews when a rule is relevant. -->

- [sr-001] helpful=3 harmful=0 :: Do not relax compliance/lint scripts to silence violations. Fix the offending code.
- [sr-002] helpful=1 harmful=0 :: Every `composer`/`npm` gate script must succeed on invocation, not just be defined.
- [sr-003] helpful=2 harmful=0 :: **npm** for Node.js (not pnpm). **Composer** for PHP.
```

### Tech Stack Manifest (new file)

```markdown
# Tech Stack by Role

When working in a role, use ctx7 to fetch current documentation
for the listed libraries before starting implementation.

## Backend (Python)

- fastapi
- sqlalchemy (2.0+)
- pgvector
- pydantic (v2)
- pytest / pytest-asyncio
- httpx
- ruff
- alembic

## Frontend (React/TS)

- react (18+)
- @tanstack/react-query (v5)
- @radix-ui/react-\*
- vitest
- @testing-library/react
- vite (5+)
- typescript (5.3+)

## PHP Plugin

- phpunit (10.5+)
- wp-mock
- phpstan (level 8)
- wordpress-rest-api
- phpcs (PSR-12 + WordPress)

## Orchestration

- sqlite3 (FTS5)
- fastmcp
```

### Reflection Cycle (documented in instructions.md)

```markdown
## Document Maintenance (ACE Playbook Evolution)

### Reflection triggers

A reflection cycle runs when:

1. A branch review finding references a rule (update helpful counter)
2. A branch review finding contradicts a rule (update harmful counter)
3. A new failure mode is discovered that no existing rule covers (add new bullet)
4. A library version upgrade invalidates a rule (remove; ctx7 serves current docs)

### Curation rules

- Rules with `helpful=0 harmful>=2` are pruning candidates; delete on next review.
- Rules that restate a linter/config check get deleted immediately (tool is source of truth).
- New rules require a real failure reference (issue, commit, or branch review finding ID).
- Delta updates only; never rewrite a section from scratch (prevents context collapse).
```

### Metrics Snapshot Format (appended to `.task-state/metrics.jsonl`)

```json
{
  "timestamp": "2025-01-15T10:30:00Z",
  "task_ref": "phase-5-retention",
  "token_burn": {
    "total_tokens": 1450000,
    "by_lane": { "backend-domain": 800000, "frontend": 650000 },
    "tokens_per_converged_cycle": 45000
  },
  "context_pressure": {
    "latest_pressure": "normal",
    "elevated_cycle_ratio": 0.15,
    "high_cycle_ratio": 0.02
  },
  "fts5_retrieval": {
    "artifact_sources_indexed": 85,
    "artifact_chunks_fts_count": 340,
    "handoff_record_counts": {
      "decisions": 42,
      "findings": 28,
      "blockers": 3,
      "actions": 15
    }
  },
  "lane_health": {
    "total_scope_violations": 1,
    "max_exhaustion_streak": 2,
    "convergence_rate": 0.78
  },
  "ace_documentation": {
    "total_strategy_bullets": 28,
    "pruning_candidates": 2,
    "total_helpful": 45,
    "total_harmful": 3,
    "instruction_file_lines": 380
  }
}
```

### ACE Reflection Hook (post-review-finding)

```python
# run_detect_rule_references(): called from worker_daemon post-review hook.
# Lives in ace_reflect.py; writes to ace_reflect_log.jsonl; never edits instruction files.
def detect_rule_references(text: str) -> list[str]:
    """Return full rule IDs found in text, e.g. ['[sr-013]', '[rg-014]']."""
    # Non-capturing group so findall() returns full matches, not capture groups.
    rule_pattern = re.compile(r'\[(?:sr|rg)-\d{3}\]')
    return rule_pattern.findall(text)

# ace_apply_counters(): called only from `make ace-reflect` in orchestrator root.
# Edits instruction files with a file lock; never called from daemon context.
def ace_apply_counters(reflect_log: Path, instruction_files: list[Path]) -> None:
    """Apply pending counter increments from reflect log to instruction files."""
    unprocessed = read_unprocessed_entries(reflect_log)
    for entry in unprocessed:
        for rule_ref in entry["rules"]:  # each rule_ref: {rule_id: str, contradicts: bool}
            rule_id = rule_ref["rule_id"]
            counter = "harmful" if rule_ref["contradicts"] else "helpful"
            for path in instruction_files:
                # increment_counter is idempotent: it checks a (finding_id, rule_id, filepath)
                # dedup key in ace_reflect_log.jsonl before writing. Including filepath ensures
                # each mirrored instruction file (instructions.md, CLAUDE.md, GEMINI.md) is
                # updated independently on first run. If a crash occurs mid-loop, the entry
                # stays unprocessed and retry is safe -- already-applied (finding_id, rule_id,
                # filepath) triples are skipped; unprocessed files are updated. mark_processed
                # is called only after ALL rules across ALL files succeed.
                increment_counter(rule_id, counter, path, dedup_key=(entry["finding_id"], rule_id, str(path)))  # file-locked write per file
        mark_processed(reflect_log, entry["finding_id"])
```

## Functions to Change

| File                                                                                    | Function/Section                                                                                                                                | Change                                                                                                                                                                                                                                                                                          |
| --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.vscode/mcp.json`                                                                      | `servers`                                                                                                                                       | Add `ctx7` server registration alongside `altcontext-mcp`                                                                                                                                                                                                                                       |
| `docs/agentic/maps/tech-stack.md`                                                       | (new file)                                                                                                                                      | Create tech-stack manifest mapping roles to ctx7 library identifiers                                                                                                                                                                                                                            |
| `docs/agentic/instructions.md`                                                          | `## Document Maintenance`                                                                                                                       | Upgrade from informal ACE prose to structured playbook evolution protocol with reflection triggers and curation rules                                                                                                                                                                           |
| `docs/agentic/instructions.md`                                                          | `## Role Selection` table                                                                                                                       | Add "Tech Stack (ctx7)" column linking to `maps/tech-stack.md` anchors                                                                                                                                                                                                                          |
| `docs/agentic/instructions.md`                                                          | `### Short Rules`                                                                                                                               | Convert existing rules to ACE strategy bullet format with IDs and evidence counters                                                                                                                                                                                                             |
| `docs/agentic/instructions.md`                                                          | `### Cross-Branch Regression Guards`                                                                                                            | Convert existing guards to ACE strategy bullet format with IDs and evidence counters                                                                                                                                                                                                            |
| `CLAUDE.md`                                                                             | `### Short Rules`                                                                                                                               | Mirror ACE bullet format from `instructions.md` (CLAUDE.md is a copy of instructions.md)                                                                                                                                                                                                        |
| `CLAUDE.md`                                                                             | `### Cross-Branch Regression Guards`                                                                                                            | Mirror ACE bullet format                                                                                                                                                                                                                                                                        |
| `GEMINI.md`                                                                             | `## Role Selection` table                                                                                                                       | Mirror "Tech Stack (ctx7)" column from `instructions.md` (GEMINI.md mirrors CLAUDE.md)                                                                                                                                                                                                          |
| `GEMINI.md`                                                                             | `### Short Rules`                                                                                                                               | Mirror ACE bullet format from `instructions.md`                                                                                                                                                                                                                                                 |
| `GEMINI.md`                                                                             | `### Cross-Branch Regression Guards`                                                                                                            | Mirror ACE bullet format                                                                                                                                                                                                                                                                        |
| `docs/agentic/rules/RADIX_UI_COMPONENT_GUIDE.md`                                        | Generic reference sections (priority tables, `asChild`/controlled/uncontrolled patterns, data attribute styling, generic a11y, generic testing) | Remove those sections; add ctx7 directive header                                                                                                                                                                                                                                                |
| `docs/agentic/rules/testing-typescript.md`                                              | Generic library sections (Vitest hoisting/mock patterns, `waitFor` patterns, TanStack Query config, MSW setup)                                  | Remove those sections; add ctx7 directive header                                                                                                                                                                                                                                                |
| `docs/agentic/rules/testing-python.md`                                                  | Generic pytest-asyncio setup section and Python Fake pattern boilerplate section                                                                | Remove those sections; add ctx7 directive header                                                                                                                                                                                                                                                |
| `docs/agentic/rules/frontend-guidelines.md`                                             | Generic React state/hook anti-patterns section and generic a11y checklist section                                                               | Remove those sections; add ctx7 directive header                                                                                                                                                                                                                                                |
| `docs/agentic/rules/backend-python-guidelines.md`                                       | Header only                                                                                                                                     | Add ctx7 directive header (no content removal)                                                                                                                                                                                                                                                  |
| `docs/agentic/rules/backend-php-guidelines.md`                                          | Header only                                                                                                                                     | Add ctx7 directive header (no content removal)                                                                                                                                                                                                                                                  |
| `docs/agentic/rules/testing-php.md`                                                     | Header only                                                                                                                                     | Add ctx7 directive header (no content removal)                                                                                                                                                                                                                                                  |
| Portless config (new)                                                                   | Service mapping                                                                                                                                 | Create portless configuration mapping service names to ports: `backend.localhost` -> `8000`, `db.localhost` -> `5432`                                                                                                                                                                           |
| `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | `get_default_base_url()`                                                                                                                        | Replace `http://localhost:8000` with portless hostname `http://backend.localhost`                                                                                                                                                                                                               |
| `apps/prototype-description-service/docker-compose.db.yml`                              | `ports`                                                                                                                                         | Document portless mapping; optionally replace `55432:5432` with portless-managed port                                                                                                                                                                                                           |
| `docs/agentic/instructions.md`                                                          | `### Cross-Branch Regression Guards`                                                                                                            | Add `[rg-013]` core.py purity guard and `[rg-014]` late-binding import discipline guard                                                                                                                                                                                                         |
| `scripts/mcp/ace_metrics.py`                                                            | (new file)                                                                                                                                      | Metrics aggregation script: reads JSONL logs, handoff.db, mcp-artifacts.db, instruction files; produces JSON/markdown report                                                                                                                                                                    |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_reflect.py`         | (new file)                                                                                                                                      | ACE reflection hooks: rule reference detection in findings, counter update in instruction files, pruning candidate identification                                                                                                                                                               |
| `Makefile`                                                                              | `ace-metrics`, `ace-reflect`, `ace-curation-report` targets                                                                                     | Add make targets for metrics report generation, manual reflection trigger, and pruning candidate report                                                                                                                                                                                         |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py`       | post-review hook                                                                                                                                | After `review_complete`, scan new findings for rule IDs; append `{cycle, finding_id, rules: [{rule_id, contradicts}], timestamp}` to `.task-state/ace_reflect_log.jsonl` (per-rule polarity; one `contradicts` bool per rule_id); emit `ace_reflect_detected` event; no instruction-file writes |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/orchestrator_daemon.py` | post-dispatch advisory                                                                                                                          | After `dispatch_complete`, count unprocessed `ace_reflect_log.jsonl` entries; if count exceeds threshold (default 5), emit `ace_reflect_pending` advisory event; no instruction-file writes, no direct `ace_apply_counters` call                                                                |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/dashboard_live.py`      | metrics summary row                                                                                                                             | Add optional metrics summary to dashboard output (token efficiency, pressure trend, ACE bullet health)                                                                                                                                                                                          |

## Related Files

| File                                                                            | Note                                                                                                                                                                                                                                                                        |
| ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_prompt.py` | Context-pressure system that benefits from smaller instruction files; verify pressure thresholds still appropriate after trim                                                                                                                                               |
| `docs/agentic/contracts/agent-handoff-mcp.md`                                   | Prompt-Budget Integration section documents pressure thresholds and item caps; update if trim changes assumptions                                                                                                                                                           |
| `docs/agentic/BOOTSTRAP.md`                                                     | MCP server setup section; add ctx7 installation/verification commands                                                                                                                                                                                                       |
| `docs/agentic/rules/branch-review-guide.md`                                     | Branch review process automation: daemon logs rule references found in new findings to `ace_reflect_log.jsonl`; operator runs `make ace-reflect` to apply counter updates for daemon-logged findings; use `ace_reflect_on_findings()` for findings that bypassed the daemon |
| `docs/agentic/rules/planning-review-guide.md`                                   | Planning review should use ctx7 for library version validation instead of relying on stale guideline content                                                                                                                                                                |
| `.codex/config.toml`                                                            | Codex MCP registration; add ctx7 if Codex agents should also use it                                                                                                                                                                                                         |
| `GEMINI.md`                                                                     | Direct modification target in Phases 1, 3, and 6: mirrors `CLAUDE.md` for Role Selection table, ACE bullet format, and Reflection Cycle text updates; tracked in Functions to Change table                                                                                  |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`                      | Verification-only: confirm zero orchestration imports; invariant codified as `[rg-013]`                                                                                                                                                                                     |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/*.py`           | Verification-only: confirm late-binding import discipline; invariant codified as `[rg-014]`                                                                                                                                                                                 |
| `apps/prototype-wp-alt-context/src/admin/class-admin.php`                       | Contains `localhost:8000` fallback warning string; update if portless hostname adopted                                                                                                                                                                                      |
| `apps/prototype-description-service/.env.example`                               | Port references (`PGPORT=5432`); document portless equivalents                                                                                                                                                                                                              |
| ACE repo (`github.com/ace-agent/ace`)                                           | Reference implementation for Generator/Reflector/Curator pipeline; `DataProcessor` interface defines how handoff data maps to ACE samples                                                                                                                                   |
| `logs/worker-daemon/worker-*.jsonl`                                             | Source data for per-lane token burn, context pressure, exhaustion streak metrics (Phase 5 input)                                                                                                                                                                            |
| `logs/daemon/orchestrator.jsonl`                                                | Source data for orchestrator cycle metrics, intake/dispatch stats (Phase 5 input)                                                                                                                                                                                           |
| `.task-state/handoff.db`                                                        | Source for decision/finding/blocker/action counts and velocity metrics (Phase 5 input)                                                                                                                                                                                      |
| `.task-state/mcp-artifacts.db`                                                  | Source for artifact indexing stats: artifact_sources count and artifact_chunks_fts row count (Phase 5 input); no query-frequency counters are persisted at runtime                                                                                                          |
| `.task-state/metrics.jsonl`                                                     | (new) Append-only time-series of metrics snapshots produced by `make ace-metrics` (Phase 5 output)                                                                                                                                                                          |
| `docs/tasks/8.0/orchestration-hardening-task-plan.md`                           | Defines token burn, context pressure, exhaustion streak systems that Phase 5 metrics aggregate                                                                                                                                                                              |
| `docs/tasks/8.0/orchestration-context-retrieval-task-plan.md`                   | Defines artifact index and FTS5 search systems that Phase 5 metrics aggregate                                                                                                                                                                                               |
| `docs/tasks/8.0/structured-memory-search-task-plan.md`                          | Defines `search_handoff` FTS5 system that Phase 5 metrics aggregate                                                                                                                                                                                                         |

## Lane Decomposition (Multi-Agent)

This task spans multiple file ownership domains: documentation (`docs/agentic/`), MCP/editor config (`.vscode/mcp.json`, `.codex/config.toml`), PHP production code (`apps/prototype-wp-alt-context/src/`), service config (`apps/prototype-description-service/docker-compose.db.yml`), orchestration Python code (`packages/agent-handoff-mcp/src/.../orchestration/`), and build tooling (`Makefile`, `scripts/mcp/`). Despite touching these domains, a single-lane approach remains appropriate. Phase 5 creates `ace_metrics.py` (read-only reporting script) and the `ace_reflect.py` stub inside the orchestration package (new shared runtime code that provides `parse_strategy_bullets()` for import by `ace_metrics.py`); Phase 5 is therefore not purely read-only -- it introduces a new file in `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/` and a cross-phase dependency from the metrics script into the reflection module. Phase 6 (`ace_reflect.py`) adds lightweight detection hooks to `worker_daemon.py` and `orchestrator_daemon.py` (rule reference logging only, no instruction-file writes from daemon context) plus a manual `make ace-reflect` step that edits instruction files and must be run from the orchestrator root. The daemon hooks are runtime behavior changes and require review against existing orchestration patterns. PHP production code changes (Phase 1 portless items) should be reviewed against `rules/backend-php-guidelines.md`. Phase 5-6 Python code should be reviewed against `rules/backend-python-guidelines.md`.

---

# Consolidated Checklist

## Completed

- [x] Research ACE framework (ICLR 2026 paper, GitHub repo, project site)
- [x] Audit all 7 guideline files for generic vs project-specific content ratios
- [x] Identify current ACE self-correction protocol in instructions.md
- [x] Inventory existing MCP registrations and ctx7 integration points

## Phase 0: Scaffolding

- [x] Verify ctx7 install method: run `brew info ctx7` to confirm Homebrew formula exists; if not, the MCP config must use npm spawn (`command: npx`, `args: ["-y", "@upstash/context7-mcp"]`) instead of a binary path
- [x] Install ctx7: `brew install ctx7` (or configure npm spawn if Homebrew formula not found -- see step above)
- [x] Verify ctx7 MCP server works: `ctx7 mcp` (stdio transport, if Homebrew) or confirm npx invocation surfaces stdio JSON-RPC
- [x] Verify ctx7 can fetch docs for key libraries: fastapi, radix-ui, vitest, phpunit
- [DEFERRED] Install portless locally (portless integration moved to a dedicated future task; see Phase 1 deferral note)
- [DEFERRED] Configure portless service map
- [DEFERRED] Verify portless resolves configured hostnames
- [x] Create `docs/agentic/maps/tech-stack.md` with role-to-library mapping

## Phase 1: ctx7 + Portless Integration

- [x] Add ctx7 server to `.vscode/mcp.json`
- [x] Add ctx7 server to `.codex/config.toml` (if Codex agents should use it)
- [x] Add ctx7 installation and verification to `docs/agentic/BOOTSTRAP.md`
- [DEFERRED] Add portless installation and service map to `docs/agentic/BOOTSTRAP.md` (portless deferred; BOOTSTRAP.md now documents the localhost service map directly and notes the deferral)
- [x] Add "Tech Stack (ctx7)" column to Role Selection table in `instructions.md`
- [x] Mirror the Role Selection table update in `CLAUDE.md`
- [x] Mirror the Role Selection table update in `GEMINI.md`
- [DEFERRED] Replace `http://localhost:8000` in `class-abstract-recognition-proxy-controller.php` with portless hostname
- [DEFERRED] Update `class-admin.php` fallback warning to reference portless hostname
- [DEFERRED] Document portless service map alongside docker-compose port configuration

> **Portless deferral note (Phase 1):** The portless tool was evaluated but not installed. `portless` requires DNS-level configuration that is environment-specific and not suitable for a shared greenfield project at this stage. The localhost service map is now documented in `BOOTSTRAP.md` directly. PHP fallback URLs remain as `http://localhost:8000`; changing them requires a broader PHP integration pass that should be a separate task with its own rollout plan.

## Phase 2: Guideline Trimming

- [x] `RADIX_UI_COMPONENT_GUIDE.md`: Add ctx7 header; remove generic sections (~144 lines: priority tables, asChild/controlled patterns, data attribute styling, generic a11y, generic testing patterns); keep installed package inventory, wrapper locations, BEM `acx-` naming, i18n `__()` requirement
- [x] `testing-typescript.md`: Add ctx7 header; remove generic sections (~110 lines: Vitest hoisting/doMock docs, waitFor patterns, TanStack Query config, MSW setup); keep provider harness parity, typed builder mandate, integration-lite pattern, afterEach query cancellation, Sovereign Sync test patterns
- [x] `testing-python.md`: Add ctx7 header; remove generic sections (~63 lines: pytest-asyncio setup, AsyncMock boilerplate, SQLAlchemy in-memory fixture patterns); keep FakeClusterRepository pattern, path/query param collision rule, FastAPI dependency_overrides pattern, test directory structure
- [x] `frontend-guidelines.md`: Add ctx7 header; remove generic sections (~100 lines: React state anti-patterns, hook sizing heuristics, generic a11y checklist); keep `acx-` class prefix, `!important` ban, WordPress CSS specificity rules, component size limits, Workbench overlay/URL state patterns
- [DEFERRED] Replace remaining hardcoded `localhost:PORT` references in trimmed guideline files with portless `.localhost` hostnames (portless deferred; localhost references remain as-is)
- [x] `backend-python-guidelines.md`: Add ctx7 header only (no content removal)
- [x] `backend-php-guidelines.md`: Add ctx7 header only (no content removal)
- [x] `testing-php.md`: Add ctx7 header only (no content removal)
- [x] Verify all local cross-references (markdown links between guideline files) still resolve after trimming

## Phase 3: ACE Playbook Format

- [x] Upgrade `instructions.md` Document Maintenance section: replace informal ACE prose with structured playbook evolution protocol (reflection triggers, curation rules, counter update procedures)
- [x] Convert `instructions.md` Short Rules to ACE strategy bullet format (`[sr-NNN] helpful=N harmful=M :: rule text`)
- [x] Convert `instructions.md` Cross-Branch Regression Guards to ACE strategy bullet format (`[rg-NNN] helpful=N harmful=M :: guard text`)
- [x] Assign initial `helpful` counters based on known failure history documented in commit messages and branch review findings (do not fabricate; use `helpful=1` as baseline for rules with known provenance, `helpful=0` for rules without documented incidents)
- [x] Mirror all ACE format changes in `CLAUDE.md`
- [x] Mirror all ACE format changes in `GEMINI.md`
- [x] Update `docs/agentic/rules/branch-review-guide.md` to add an ACE Reflection section noting that rule references in findings are tracked with ACE counters; do NOT include counter-update operator instructions at this phase -- the exact procedure (manual vs automated) will be documented in Phase 6 once the daemon and `make ace-reflect` target are implemented; Phase 6 owns the final operator instruction
- [x] Add `[rg-013] helpful=1 harmful=0 :: core.py must remain pure handoff-state CRUD; no orchestration imports, no subprocess calls, no lock management. Enforce during code review.` to Cross-Branch Regression Guards
- [x] Add `[rg-014] helpful=1 harmful=0 :: Orchestration modules must use late-binding imports (function-level) for agent_handoff_mcp symbols to preserve the clean split seam and avoid load-time coupling.` to Cross-Branch Regression Guards
- [x] Mirror rg-013 and rg-014 in `CLAUDE.md` and `GEMINI.md`

## Phase 4: Verification

- [x] Measure total line count of all modified guideline files before and after; confirm net reduction of ~417 lines (baselines: RADIX 288, testing-typescript 181, testing-python 157, frontend-guidelines 201 = 827 total; additional trimming on 2026-03-22 brought total to ~402 lines, net reduction ~425 lines, exceeding the ~417-line target)
- [x] Verify ctx7 can serve docs for every library listed in `maps/tech-stack.md` (resolved via ctx7 tool 2026-03-22; all major libraries confirmed available; `fastmcp` /prefecthq/fastmcp, `pgvector` /pgvector/pgvector-python; `wp-mock` has no ctx7 coverage -- noted in tech-stack.md with link to upstream GitHub)
- [DEFERRED] Verify portless resolves all configured service hostnames (portless deferred)
- [DEFERRED] Run a representative agent session with the trimmed guidelines to confirm no critical project-specific context was lost (requires a dedicated live-task validation pass beyond this implementation review)
- [x] Confirm `lane_prompt.py` context-pressure behavior is unchanged (no code changes expected; instruction-file size reduction should lower measured pressure in practice)
- [x] Verify `core.py` has zero orchestration imports (grep for `from.*orchestration` in core.py; expect 0 matches)
- [x] Verify ctx7 and altcontext-mcp appear in live Codex harness MCP listing (`codex mcp list` or equivalent in-harness command); `.codex/config.toml` has been updated but live attachment confirmation requires a running Codex session (verified in Codex harness on 2026-03-22)

## Phase 5: Observability Metrics Tooling

- [x] Create metrics CLI entry point with `--task-ref`, `--state-dir`, `--logs-dir`, `--output-format` (json|markdown) arguments (created at `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_metrics.py` as a module invoked via `-m agent_handoff_mcp.orchestration.ace_metrics`; the Functions to Change table listed `scripts/mcp/ace_metrics.py` but the package location was used per the make target and Makefile conventions)
- [x] Implement JSONL log parser: read `logs/worker-daemon/worker-*.jsonl` and `logs/daemon/orchestrator.jsonl`; extract `subagent_turn_observed`, `token_burn_warning`, `exhaustion_streak`, `scope_violation`, `lane_health_changed`, `review_complete` events
- [x] Implement token burn aggregation: total tokens across all lanes, per-lane breakdown from `subagent_turn_observed` events, tokens-per-converged-cycle efficiency (total tokens / count of `review_complete` events where `converged=true`)
- [x] Implement context pressure trending: count cycles at each pressure level (normal/elevated/high) from `context_pressure` events or `_measure_context_utilization` data in observability history; compute `elevated_cycle_ratio` and `high_cycle_ratio`
- [x] Implement FTS5 retrieval stats: query `handoff.db` for total decision/finding/blocker/action record counts via `SELECT COUNT(*) FROM decisions` etc.; query `mcp-artifacts.db` for `artifact_sources` count and `artifact_chunks_fts` row count (the FTS virtual table; there is no separate `artifact_chunks` table); note if indexes are empty (signals retrieval not yet exercised); do not include query-frequency counters -- no query telemetry is persisted by the current runtime
- [x] Implement lane health aggregation: total `scope_violation` events, max `exhaustion_streak` value across lanes, convergence rate (converged review cycles / total review cycles)
- [x] Create `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_reflect.py` stub with `parse_strategy_bullets()` fully implemented (the only function consumed by `ace_metrics.py`); Phase 6 adds `detect_rule_references`, `classify_rule_reference`, `increment_counter`, `identify_pruning_candidates`, `ace_reflect_on_findings`, `ace_apply_counters`, and the `__main__` entry point
- [x] Implement ACE documentation health: call `parse_strategy_bullets(filepath)` from `ace_reflect.py` (imported from `agent_handoff_mcp.orchestration.ace_reflect`) for each instruction file (`instructions.md`, `CLAUDE.md`, `GEMINI.md`); use the non-capturing-group pattern `\[(?:sr|rg)-\d{3}\].*helpful=\d+.*harmful=\d+` to detect and parse ACE bullets; sum `helpful`/`harmful` counters across all files; identify pruning candidates (`helpful=0 harmful>=2`); count total instruction file lines; do not reimplement `parse_strategy_bullets()` inline
- [x] Assemble all metrics into the Metrics Snapshot Format (see Patterns) and append to `.task-state/metrics.jsonl` with ISO 8601 timestamp
- [x] Add markdown report renderer: print human-readable summary to stdout with sections for token efficiency, context health, retrieval activity, lane stability, and documentation fitness
- [x] Add `make ace-metrics` target: `PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) scripts/mcp/ace_metrics.py --task-ref $(TASK) --state-dir .task-state --logs-dir logs --output-format markdown` (requires both `MCP_PYTHON` for interpreter selection and `MCP_PYTHONPATH` for package discovery, since `ace_metrics.py` imports `parse_strategy_bullets()` from `agent_handoff_mcp.orchestration.ace_reflect`)
- [x] Add `make ace-metrics-json` target: same command with `--output-format json`
- [x] Handle missing data gracefully: if log files or databases do not exist (new task, no history), emit zero-valued metrics with a `data_available: false` flag per section rather than failing
- [x] Integrate optional metrics summary line into `dashboard_live.py`: after the lane table, print a one-line metrics summary (total tokens, pressure trend, ACE bullet health) when `--show-metrics` flag is passed

## Phase 6: ACE Autorun Triggers

- [x] Extend `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_reflect.py` (stub created in Phase 5 with `parse_strategy_bullets()`) with the remaining core reflection functions
- [x] Implement `detect_rule_references(text: str) -> list[str]`: scan text for `[sr-NNN]` and `[rg-NNN]` patterns using a non-capturing group (`re.compile(r'\[(?:sr|rg)-\d{3}\]')`) so `findall()` returns full rule IDs like `['[sr-013]', '[rg-014]']`, not capture group stems
- [x] Implement `classify_rule_reference(text: str, rule_id: str) -> bool`: determine whether a finding text contradicts the named rule; check for negation keywords (`violated`, `missing`, `contradicts`, `breaks`, `fails`) in the finding text -- if any are present, return `True` (contradicts); otherwise return `False` (confirms); this heuristic may produce false positives (negation phrases like "was not violated" are not detected; the keyword appears regardless of negation context) and false negatives (synonyms not in the keyword list are missed); ACE runtime integration (Stretch Goal) provides semantic determination
- [x] Verify `parse_strategy_bullets(filepath: Path) -> dict[str, dict]` (fully implemented in Phase 5; verify the contract below matches the Phase 5 implementation before proceeding to `identify_pruning_candidates`): parses an instruction file's ACE bullets into `{rule_id: {helpful: int, harmful: int, text: str, line_number: int}}`
- [x] Implement `increment_counter(rule_id: str, counter: str, filepath: Path, dedup_key: tuple[str, str, str])`: read the file, find the matching bullet line, increment the specified counter, write back; before writing, check that `dedup_key` (`(finding_id, rule_id, filepath)`) is not already recorded as `applied` in `.task-state/ace_reflect_log.jsonl`; if it is, skip without writing (idempotent retry path); if not, write then append the applied record; the per-file granularity of the dedup key ensures all mirrored instruction files (`instructions.md`, `CLAUDE.md`, `GEMINI.md`) receive counter updates on first run; `mark_processed(finding_id)` (called by the caller after all rules across all files succeed) marks the whole entry done as a coarse completion flag, separate from the per-rule-per-file dedup records
- [x] Implement `identify_pruning_candidates(filepath: Path) -> list[dict]`: return rules where `helpful=0` and `harmful>=2`
- [x] Implement `ace_reflect_on_findings(findings: list[dict], instruction_files: list[Path])`: manual batch helper for findings NOT already logged by the daemon; for each finding, calls `detect_rule_references()` to find rule IDs, then `classify_rule_reference(finding_description, rule_id)` per rule to determine polarity, writes `{cycle, finding_id, rules: [{rule_id, contradicts}], timestamp}` records to `ace_reflect_log.jsonl`; then calls `ace_apply_counters(reflect_log, instruction_files)` which processes ALL unprocessed log entries (including any previously daemon-logged entries that were pending before this call); callers must be aware this is a full log flush, not a targeted per-finding apply -- only invoke when ready to process all pending entries; must only be called from the orchestrator root (never from daemon or worker context); this is NOT the standard `make ace-reflect` path -- it exists for one-shot invocation when findings have not gone through a daemon cycle
- [x] Add post-review hook in `worker_daemon.py`: after `review_complete` event, scan new findings for rule ID references using `detect_rule_references()`; for each rule reference found, determine per-rule `contradicts` via `classify_rule_reference(finding_description, rule_id)` (keyword heuristic; see above); append `{cycle, finding_id, rules: [{rule_id, contradicts}], timestamp}` records to `.task-state/ace_reflect_log.jsonl` -- storing contradiction verdict per rule_id so findings that reference multiple rules with different polarity are represented correctly; emit `ace_reflect_detected` JSONL event with `findings_scanned` and `references_found` counts; do NOT call `ace_apply_counters()` or edit instruction files from daemon context (prevents concurrent writes and dirty-worktree churn)
- [x] Add advisory check in `orchestrator_daemon.py`: after `dispatch_complete`, count unprocessed entries in `ace_reflect_log.jsonl`; if count exceeds configurable threshold (default 5), emit `ace_reflect_pending` advisory event reminding the operator to run `make ace-reflect` from the orchestrator root; no direct `ace_apply_counters()` call from daemon context
- [x] Document ownership rule: `ace_apply_counters()` (instruction-file edits) is called only from `make ace-reflect` (`__main__` path) or `ace_reflect_on_findings()` (manual batch helper path); both callers must operate from the orchestrator root; never called from worker daemons or lane worktrees; this prevents concurrent instruction-file edits across multiple agents
- [x] Add `make ace-reflect` target for manual batch reflection: `PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) -m agent_handoff_mcp.orchestration.ace_reflect --task-ref $(TASK) --state-dir .task-state --instruction-files docs/agentic/instructions.md CLAUDE.md GEMINI.md` (requires both `MCP_PYTHON` for interpreter selection and `MCP_PYTHONPATH` for package discovery since ace_reflect.py lives inside the agent_handoff_mcp package); `__main__` calls `ace_apply_counters(reflect_log, instruction_files)` directly to process all unprocessed entries in `.task-state/ace_reflect_log.jsonl` since last recorded reflection timestamp; report updated counters and pruning candidates to stdout; `ace_reflect_on_findings()` is NOT called from this standard path -- it is a separate helper for findings not yet logged by the daemon
- [x] Add `make ace-curation-report` target: run `identify_pruning_candidates()` across all instruction files; output markdown table of candidates with their counter values and rule text
- [x] Update `docs/agentic/rules/branch-review-guide.md` to include automated reflection note: the worker daemon's post-review hook logs `[sr-NNN]` and `[rg-NNN]` rule references from new findings to `ace_reflect_log.jsonl`; run `make ace-reflect` from the orchestrator root to apply counter updates for daemon-logged findings; for findings recorded outside a daemon cycle (e.g., manually via MCP without a running worker daemon), use `ace_reflect_on_findings()` from the orchestrator root to log and apply them in one step
- [x] Update the Reflection Cycle section embedded in `instructions.md` (and mirrored in `CLAUDE.md` and `GEMINI.md`) to replace the manual parentheticals `(update helpful counter)` and `(update harmful counter)` with `(daemon detects and logs automatically; run make ace-reflect from the orchestrator root to apply pending counter updates)`; also update the `<!-- ACE playbook: ... Update counters during branch reviews when a rule is relevant. -->` inline comment in the Short Rules section (installed by Phase 3 alongside the ACE bullet format) to replace that line with a reference to daemon automation and `make ace-reflect`; mirror both changes in `CLAUDE.md` and `GEMINI.md`
- [x] Verify dedup: running `make ace-reflect` twice on the same findings does not double-count (dedup key is `(finding_id, rule_id, filepath)` -- per-file granularity ensures all mirrored instruction files receive counter updates on first run; re-running skips already-applied triples without affecting the updated counters)
- [x] Verify graceful handling: instruction files without ACE bullets, findings without rule references, and missing reflect log all handled without errors

## Stretch Goals

- [x] Add a pre-commit hook or CI check that warns when a guideline file exceeds a token budget (e.g., 2000 tokens per file). Classification: good next implementation candidate.
- [DEFERRED] **ACE runtime evaluation (follow-on after Phase 6)**: install the ACE library (`git clone https://github.com/ace-agent/ace.git && cd ace && uv sync`); implement a `HandoffDataProcessor` mapping handoff.db review findings/decisions/tests to ACE's sample format; run offline adaptation (`mode='offline'`) against accumulated data; compare generated playbook deltas against Phase 6's regex-based counter updates; if materially better, integrate `make ace-adapt` as a periodic batch command and add ACE as a dev dependency in `pyproject.toml`. Note: Phase 6's reflection hooks serve as the lightweight alternative; full runtime is justified only if regex-based detection has >20% false positive rate or counters diverge significantly from expert assessment. Classification: true research follow-on. Deferred: no production users blocked; re-evaluate if regex detection diverges materially.
- [DEFERRED] ACE online adaptation mode: run `ace_system.run(mode='online', ...)` during live task execution, feeding review findings as they arrive; builds on Phase 6's daemon hooks but replaces regex detection with LLM-powered semantic matching. Classification: should be explicitly deferred out of this task.
- [DEFERRED] ACE `use_bulletpoint_analyzer` mode: evaluate whether ACE's built-in bullet-point analyzer produces better strategy bullet structure than manual formatting. Classification: true research follow-on. Deferred: no implementation work required now; revisit when ACE runtime is evaluated.
- [x] Time-series visualization: build a simple chart renderer (matplotlib or terminal sparklines) that reads `.task-state/metrics.jsonl` and shows token burn, context pressure, and convergence rate trends over time. Classification: good next implementation candidate.
- [x] MCP tool `get_metrics_summary(task_ref)`: expose metrics report as an MCP tool so agents can query metrics in-session without terminal access. Classification: good next implementation candidate.
- [x] Per-phase execution time breakdown: extend `_record_observability()` to capture `exec_seconds`, `review_seconds`, `verify_seconds` separately for richer Phase 5 metrics. Classification: good next implementation candidate.

## Success Criteria

- [x] ctx7 registered as MCP server in `.vscode/mcp.json` and verified functional
- [DEFERRED] portless installed and service map configured; at least `backend.localhost` and `db.localhost` resolve
- [x] `maps/tech-stack.md` exists and is linked from the Role Selection table
- [x] Four guideline files trimmed by ~417 lines total (144+110+63+100; generic library reference removed)
- [x] All remaining content in trimmed files is project-specific (no upstream API documentation)
- [x] `instructions.md` Document Maintenance section uses structured ACE playbook evolution protocol
- [x] Short Rules and Cross-Branch Regression Guards use ACE strategy bullet format with IDs and evidence counters
- [x] Cross-Branch Regression Guards include `[rg-013]` (core.py purity) and `[rg-014]` (late-binding import discipline)
- [x] ctx7 directive header present in all 7 guideline files
- [DEFERRED] Hardcoded `localhost:PORT` references replaced with portless hostnames in at least PHP controller and admin warning
- [x] No broken cross-references between guideline files after trimming
- [x] `make ace-metrics` produces a structured report covering token burn, context pressure, FTS5 retrieval, lane health, and ACE documentation health
- [x] `.task-state/metrics.jsonl` is populated with at least one snapshot after running `make ace-metrics`
- [x] Metrics script handles missing data gracefully (new tasks with no history produce zero-valued output, not errors)
- [x] ACE rule reference detection hooks in `worker_daemon.py` log `[sr-NNN]` and `[rg-NNN]` references found in new review findings to `.task-state/ace_reflect_log.jsonl`; `ace_reflect.py` (via `make ace-reflect`) reads those logged references and applies counter updates to instruction files when the operator runs the command from orchestrator root
- [x] Counter updates are idempotent: running `make ace-reflect` twice on the same findings does not double-count
- [x] At least one automatic trigger exists where rule reference detection logs to `ace_reflect_log.jsonl` without manual invocation (post-review hook in worker daemon); counter updates are applied separately and manually via `make ace-reflect`
- [x] `make ace-curation-report` identifies pruning candidates across all instruction files
- [x] Reflection Cycle reflection triggers and ACE playbook inline comment in `instructions.md`, `CLAUDE.md`, and `GEMINI.md` reference daemon automation (`make ace-reflect`) instead of manual counter-update instructions
