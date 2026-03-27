# Branch Review Guide

> **Purpose:** Structured checklist and metrics for reviewing feature branches before merge.
> Checklist items reference canonical rules in [`instructions.md`](../instructions.md).

## Quick Navigation

**Start here:** This file covers universal process, common checklist, severity classification, and report template.

For task plans, epics, roadmaps, ADRs, and other planning documents, use [planning-review-guide.md](planning-review-guide.md) instead of this guide.

**Then load the relevant stack guide(s):**

- Python / FastAPI / SQLAlchemy → [branch-review-python.md](branch-review-python.md)
- TypeScript / React / Vitest → [branch-review-typescript.md](branch-review-typescript.md)
- PHP / WordPress / PHPUnit → [branch-review-php.md](branch-review-php.md)

Load only the guides relevant to files in the branch diff. Most branches touch one or two stacks.

---

## How to Use This Guide

### When

Run this review on every feature branch **before merge to `main`**.
For multi-worktree orchestration in this repo, perform the review from the orchestrator root and log findings into MCP there before routing them to worker lanes.

### Who

The reviewer can be human or agentic. When an agent performs the review:

1. Walk through each checklist section, citing specific files and line numbers
2. Classify findings using the severity guide and categories below
3. Record each finding into MCP handoff via the repo-local handoff server/CLI flow (see MCP Handoff Integration)
4. Do **not** produce a report file unless the user explicitly requests one
5. If the task is split into worktrees, have the orchestrator run `make handoff-dispatch TASK=<task-ref>` after findings are logged so open issues are stamped to the correct lane and delivered through MCP lane messages.

Hard rule for agent responses:

- Do not present a finding in chat unless it has already been recorded in MCP with a stable `finding_id`.
- If a finding is discussed before recording, immediately record it and then reference its `finding_id`.
- Do not write review findings back into task plans, ADRs, or other planning docs. Log them in MCP handoff, then rely on generated `CURRENT_TASK.md` when a task-facing summary is needed.

### Scope

Review only **uncommitted working-directory changes** (`git status` / `git diff --name-only`), not the full branch history against `main`. The goal is to review what will be in the next commit, not re-review already-committed work.

For a full branch audit before merge, use `git diff --name-only main...HEAD` instead.

### Automated Review

This guide is also consumed as prompt input by `review_runner.py` (`make review-run TASK=<task> LANE=<lane>`), which feeds the checklist text to an LLM reviewer. Because the guide serves this dual role (human-readable checklist and machine-readable prompt), structural or wording changes here directly affect automated review fidelity. The orchestrator daemon (`make orchestrator-daemon`) dispatches findings produced by automated reviews to the correct worker lanes via `make handoff-dispatch`.

### Dev Tooling (Lightweight Review)

Files under `scripts/mcp/`, MCP test files, and other dev tooling do **not** require the full checklist treatment. Apply a lightweight review:

- Correctness: does the tool do what it claims?
- Obvious bugs: off-by-one, missing error handling, SQL injection
- Skip: metric thresholds, architecture boundary checks, Protocol typing

Dev tooling findings should still be recorded through the handoff MCP server before they are mentioned in chat, but are never HIGH severity unless they corrupt production data or state.

---

## Review Intake

Before walking the checklist, load only the minimum review packet:

1. the intended change: task plan, scoped request, or stated branch objective
2. the actual diff or working-directory change set being reviewed
3. the boundary contracts, ADRs, and repo rules touched by that change
4. the proof artifacts already produced: tests, type checks, static analysis, runtime checks

Required intake details:

- branch or commit range under review
- intended scope reference
- relevant contracts/ADRs/rules
- verification commands already run, if any
- review mode: normal branch review or release-audit escalation

Do not bulk-load unrelated docs, lane chatter, or historical artifacts unless the branch cannot be reviewed correctly without them.

## Fresh Verification Evidence

Treat any claim that a branch is "done", "fixed", "passing", or "ready" as unproven unless there is fresh verification evidence for the current branch state.

- A review finding is warranted when verification is stale, partial, or unrelated to the behavior being claimed fixed.
- Historical test rows are useful context, but they do not by themselves prove current-branch correctness.
- Prefer deterministic proof on the current branch state: test run, type check, static analysis, runtime-parity check, or equivalent command evidence.

Reviewer prompts:

- What command would actually prove this claim?
- Was that command run on the current branch state?
- Does the output support the claim, or only part of it?
- Is runtime-sensitive behavior being justified only by unit tests?

If the answer is no, treat the claim as a `GAP`; use `HIGH` when the missing proof changes merge or release readiness.

## Common Checklist

These items apply regardless of language. Stack-specific items are in the language guides linked above.

### Correctness

- [ ] **Migration ↔ Model parity** — constraints match between migration and ORM model.
- [ ] **Schema-column parity** — SQL `WHERE`/`JOIN` keys match actual schema columns (no stale key names).
- [ ] **No unreachable code** — dead branches inside conditionals.
- [ ] **No duplicate field declarations** — Pydantic models, dataclasses.
- [ ] **API contract alignment** — response schemas match `docs/agentic/contracts/`. New fields have tests.
- [ ] **Boundary metadata preservation** — adapters/wrappers do not invent `limit`, `offset`, `total`, `data_source`, or similar envelope metadata; every field has a traceable source in the request, upstream payload, or documented fallback.
- [ ] **Assertion intent matches layer** — assertions are used only for internal invariants/unreachable states, never as a substitute for boundary validation.
- [ ] **Runtime dependency integrity** — no local type-only shims masking missing runtime packages; verify new imports with real build/test execution.
- [ ] **PHP runtime autoload parity** — new plugin runtime classes resolve under the real WordPress/Composer load path, not only under the PHPUnit bootstrap fallback autoloader.
- [ ] **Atomic mutation path preserved** — avoid splitting an existing atomic backend write flow into multiple client mutations without explicit architecture sign-off.
- [ ] **Primary control reachability** — primary actions (for example select-all) are reachable from initial zero-state UI.
- [ ] **Stale/offline path remains user-recoverable** — automation flags/defaults cannot remove an explicit manual recovery action.
- [ ] **Interactive timeout parity** — related remote calls use a shared timeout helper and consistent timeout budgets.
- [ ] **Import/restore payload validation** — malformed snapshot shapes fail fast with explicit errors (never silent success).
- [ ] **Provenance preservation** — status/update operations do not overwrite original creator metadata.
- [ ] **Single contract owner per boundary** — only one layer owns shape adaptation (for example backend array -> WordPress envelope). Downstream layers consume the canonical shape instead of carrying duplicate backward-compat fallbacks.

### Code Duplication

- [ ] **Shared test stubs** — Protocol stubs used in 3+ files extracted to shared location.
- [ ] **One canonical fake per protocol** — no divergent fakes across test files.
- [ ] **No duplicate methods** — interfaces have no aliased methods.

### Tests

- [ ] **No permanently skipped tests** — every skip has an issue reference.
- [ ] **No empty test bodies** — `pass`/`...` tests completed or deleted.
- [ ] **No false-positive fakes** — test fakes are configurable, not hardcoded to return `None`/empty.
- [ ] **Single injection strategy** — don't mix `dependency_overrides` and `monkeypatch.setattr`.
- [ ] **Adequate coverage for new components** — render, loading, error, and primary interaction.

### Documentation & Cleanup

- [ ] **No stale comments** — "TODO", "assuming this", "will verify" resolved or removed.
- [ ] **Planning-doc consistency** — "What works", "What's missing", checklist state, and success criteria do not contradict.
- [ ] **ADR terminology alignment** — accepted domain terms are used consistently (no regressions to retired naming).
- [ ] **Command invocability** — documented commands run as written (no broken copy-paste syntax).
- [ ] **No debug/large artifact commits** — logs and generated output files are ignored and excluded from Git.
- [ ] **No duplicate imports** — each symbol imported once per file.
- [ ] **Docstrings complete** — no empty `Raises:` or `Returns:` sections.
- [ ] **Function-level imports justified** — standard deps at module scope unless genuine cold-start reason.

### Code Health (Tech Debt Prevention)

These items prevent the accumulation of structural debt documented in `docs/tasks/tech-debt/refactoring-*.md`.

**Size and responsibility boundaries:**

- [ ] **No god classes/components** -- a single class or component file should not exceed ~400 lines. If a new feature pushes an existing file past this threshold, budget extraction work in the same PR or file a follow-up.
- [ ] **No god components mixing concerns** -- a React component must not combine API fetching, domain logic derivation, and rendering in one body. Extract presentation hooks (`useXPresentation`) and delegate rendering to focused sub-components.
- [ ] **Hook/function parameter count** -- hooks and functions with >8 destructured parameters must group them into typed option objects (`state`, `actions`, `mutations`). Do not add a 9th param to an already-long signature.

**Primitive obsession and enum discipline:**

- [ ] **Domain concepts as types, not raw strings** -- recurring domain values (status, operation type, curation state) must use enums / `as const` objects / PHP backed enums, not inline string literals. New comparisons against string literals (`=== 'completed'`) are only acceptable when imported from a canonical definition.
- [ ] **No duplicate status definitions** -- a single type definition or enum must be the sole source of truth. Do not re-declare equivalent string unions in multiple files.

**Structural duplication:**

- [ ] **Transaction boilerplate not inlined** -- PHP mutation handlers must use `run_transactional(callable)` or equivalent wrapper; do not duplicate START TRANSACTION / COMMIT / ROLLBACK inline.
- [ ] **Transform loops not duplicated** -- if two functions differ only in the transform applied to a loop, extract a shared pipeline or generic builder.

**Conditional complexity:**

- [ ] **Nesting depth <= 3** -- if a conditional block exceeds 3 nesting levels, refactor to guard clauses (fail fast / return early).
- [ ] **Wordy conditionals named** -- boolean expressions with 4+ parts must be extracted into named boolean variables (e.g., `const hasUnresolvedWork = ...`).
- [ ] **No null sentinels for flow control** -- do not use `null` to mean both "no selection" and "dialog closed." Use an explicit boolean or the Null Object / Special Case pattern.

**Design token discipline (CSS/SCSS):**

- [ ] **No ad-hoc font-size literals** -- use `--acx-text-*` scale tokens. If a new size is genuinely needed, add it to `_typography.scss`.
- [ ] **No hardcoded hex gray values** -- use `--acx-gray-*` scale or semantic tokens (`--acx-color-text-muted`, `--acx-color-border`).
- [ ] **No ad-hoc box-shadow** -- use `--acx-shadow-*` elevation tokens. Map component purpose to elevation level (cards = xs, dropdowns = md, toasts = lg, dialogs = xl).
- [ ] **No hardcoded border-radius** -- use `--acx-radius-*` tokens.
- [ ] **Focus rings use shared tokens** -- `--acx-focus-ring` and `--acx-focus-offset`. Do not mix hardcoded outlines with token-based ones across components.
- [ ] **Status indicators pair color with icon** -- color-only status differentiation fails for colorblind users. Every status color (success/error/warning/info) must be accompanied by a distinguishing icon.

### Bug-Finding Heuristics (Universal)

**Variable identity after normalization:** When a function normalizes an input early, trace every subsequent reference to verify the normalized variable is used, never the original.

**Cross-method contract bugs:** When method A transforms data and passes it to method B:

- [ ] Transformation output matches method B's expected input type and format.
- [ ] Error/null returns from B are checked by A.
- [ ] Derivatives computed from the filtered set, not the original unfiltered input.

**Envelope-wrapper sanity check:** When a boundary layer wraps a list payload into an envelope:

- [ ] `limit` and `offset` come from the request or upstream paging contract, never from list length or hardcoded defaults.
- [ ] `total` comes from the upstream contract when available; if it falls back to current page length, that fallback is explicitly documented and correct for the route.
- [ ] Provenance fields such as `data_source`, `projection_status`, or `source` are copied from a real upstream value or set by a documented local authority path, not guessed ad hoc.
- [ ] If the upstream payload unexpectedly arrives in a different shape than the boundary owns (for example an envelope where only a list is valid), the code fails explicitly instead of silently supporting multiple contradictory contracts.

**Boundary value sweep:** For each function accepting numeric or collection inputs, mentally substitute empty, single element, and large (10k+) inputs.

**Retry lifecycle traps:** For visibility/focus/interval retries, verify both sides:

- [ ] Per-cycle retry guards prevent duplicate concurrent attempts.
- [ ] Guard reset happens only on intentional state transitions (for example fresh -> stale), so retries are neither infinite nor permanently disabled.

**Import strictness check:** Feed one malformed import payload variant during review (`snapshot` wrong type or required shape missing) and verify the tool returns `ok: false` with an explicit error.

**Mutable-record provenance:** For lifecycle/status updates, confirm updater context does not erase original creator metadata (`agent`, `branch`, `commit_sha`).

**IDE stale-file guard:** Editor-integrated file-reading tools (`read_file`, `grep_search`) may return cached content after git operations or external writes. VS Code agents should use native `grep_search(...)` as the primary string-search surface when confirming that a function or feature is missing. Codex and other terminal-only agents may use `grep -n '<function_name>' <file>` as the fallback check. Tool-selection discipline matters here: use native IDE search when available, and reserve terminal grep for terminal-only environments. File-length mismatches between local file reads and search output are a strong signal of stale cache.

**False-fix detection (review finding closures):** When an agent (or operator) marks review findings as `fixed`, verify each closure individually:

- [ ] The claimed code change actually exists in the current working tree (grep for the function/variable/log-event by name).
- [ ] Resolution notes reference real file paths and real function names that can be verified with a single string-search command (`grep_search(...)` in VS Code agents; terminal `grep` fallback for Codex/terminal-only agents).
- [ ] Findings closed in rapid succession (3+ in under 60 seconds) are suspect -- each must show independent evidence of the fix.
- [ ] Previously-reopened findings (reopen_count >= 2) require `verification_evidence` containing concrete proof (string-search output, diff snippet, or code excerpt).
- [ ] Plan documents updated alongside bulk closures are cross-checked against the actual code to prevent circular false claims.

The `update_review_finding` MCP tool enforces two structural guards automatically:

1. **Reopen escalation:** Findings reopened >= 2 times cannot be marked `fixed` without a `verification_evidence` parameter containing proof the fix exists.
2. **Batch-close detection:** When 2+ findings for the same task have been fixed within the last 60 seconds, subsequent closures require `verification_evidence`.

Both guards can be satisfied by providing `--verification-evidence` (CLI) or `verification_evidence` (MCP tool) with string-search output, diff excerpts, or code snippets proving the fix. Prefer `grep_search(...)` when the agent has native IDE search tools; use terminal `grep` only as the Codex/terminal-only fallback.

---

## Escalate To Multi-Lens Audit When

Upgrade a normal branch review to a higher-cost release-style audit when the branch touches:

- security or compliance boundaries
- release/deploy paths
- major architecture transitions
- multi-service state machines
- high-risk persistence or migration behavior
- broad UI/UX surfaces with many state branches

When escalating, name the audit lenses explicitly:

- architecture/reliability
- QA/state-matrix
- UX/state-surface
- compliance/claims, when applicable

Normal branch review is still the default. Escalation is for branches where one reviewer pass is not enough to cover the failure surface honestly.

## Finding Categories

| Category        | Icon          | Description                                                             |
| --------------- | ------------- | ----------------------------------------------------------------------- |
| **ANTIPATTERN** | :warning:     | Works but violates patterns, creating maintenance risk                  |
| **DEAD_CODE**   | :wastebasket: | Unreachable code, unused params, duplicate declarations, skipped tests  |
| **COMPLEXITY**  | :tangled:     | Unnecessary duplication, overly complex functions, missing abstractions |
| **GAP**         | :hole:        | Missing functionality, incomplete contracts, missing tests              |

---

## Severity Classification

| Severity   | Criteria                                                                                      | Action                                    |
| ---------- | --------------------------------------------------------------------------------------------- | ----------------------------------------- |
| **HIGH**   | Incorrect behavior, data corruption, type unsafety, or >200 lines unnecessary duplication     | Must fix before merge                     |
| **MEDIUM** | Architecture violations, maintenance burden, defeated type checking, reduced test reliability | Should fix; defer only with justification |
| **LOW**    | Style, minor cleanup, small duplications                                                      | Fix if easy; otherwise next pass          |

---

## Resolving Findings

Review is not complete when findings are merely written down. Each finding needs an explicit lifecycle transition.

- Fixed findings: use `update_review_finding(status="fixed", ...)`.
- Deferred findings: use `update_review_finding(status="deferred", resolution_notes=...)`.
- Wontfix findings: use `update_review_finding(status="wontfix", resolution_notes=...)`.
- Regressed or partially fixed findings: use `reopen_review_finding(...)`.
- `record_decision(...)` may add rationale, but it does not replace the finding status update.

Before declaring the review complete:

1. verify findings were written successfully
2. verify follow-up status transitions are reflected in MCP
3. run `get_review_findings_summary` or equivalent to confirm the final open/deferred state matches the review verdict

## MCP Handoff Integration (MANDATORY for Agents)

After completing the review, every finding **must** be recorded into the MCP handoff database for cross-agent visibility. Do not rely solely on the markdown report.

### Required Execution Surface

For this repo, agents must log review findings through the handoff MCP server from the orchestrator root, not by keeping findings only in chat or a markdown file.
Task plans may update implementation checklist state, but review findings themselves stay in MCP handoff and the generated `CURRENT_TASK.md`, not in the task plan body.

Preferred pattern:

1. Run the review from the orchestrator root worktree.
2. Use the repo-local MCP runtime (`python3 -m agent_handoff_mcp ...`) with explicit runtime args:
   - `--workspace-root <orchestrator-root>`
   - `--state-dir <orchestrator-root>/.task-state`
   - `--current-task-path <orchestrator-root>/CURRENT_TASK.md`
   - `--exports-dir <orchestrator-root>/.task-state/exports`
3. Record each finding with `review-record` before mentioning it in chat.
4. Verify the write with `review-list` or `review-summary`.
5. Record the final review decision with `decision`.
6. If the review creates worker-lane work, dispatch it with `make handoff-dispatch TASK=<task-ref>` or `make review-dispatch TASK=<task-ref>` from root.

Example:

```bash
PYTHONPATH="packages/agent-handoff-mcp/src" python3 -m agent_handoff_mcp \
  --workspace-root /abs/path/to/repo \
  --state-dir /abs/path/to/repo/.task-state \
  --current-task-path /abs/path/to/repo/CURRENT_TASK.md \
  --exports-dir /abs/path/to/repo/.task-state/exports \
  review-record \
  --session <review-session> \
  --finding-id <finding-id> \
  --severity medium \
  --file-path path/to/file.py \
  --line-start 10 \
  --line-end 20 \
  --description "Concrete bug description." \
  --fix "Suggested remediation."
```

### After Each Finding

Call `review-record` / `record_review_finding` with:

| Parameter     | Value                                                                    |
| ------------- | ------------------------------------------------------------------------ |
| `session`     | Current session identifier (e.g., `2026-02-20-copilot-review`)           |
| `finding_id`  | Short ID matching the report (e.g., `H-1`, `M-2`, `L-3`)                 |
| `severity`    | `high`, `medium`, or `low`                                               |
| `file_path`   | Relative path from monorepo root                                         |
| `description` | One-paragraph description with code references                           |
| `details`     | Optional object: `{ "line_start"?: int, "line_end"?: int, "fix"?: str }` |
| `actor`       | Optional object: `{ "agent"?: str, "branch"?: str, "commit_sha"?: str }` |

### After All Findings Recorded

1. Call `review-summary` / `get_review_findings_summary` to confirm severity/status counts for the task.
2. Use `review-list --status all` / `list_review_findings(status="all")` if you need full finding-by-finding verification.
3. Call `decision` / `record_decision` summarizing the review (finding count by severity, session ID).
4. Regenerate `CURRENT_TASK.md` if your workflow depends on it.
5. If this review creates actionable lane work, run `make handoff-dispatch TASK=<task-ref>` from the orchestrator root after logging findings.
6. If this review concludes the task, run `handoff_close_check(enforce=True)` before final handoff.
7. Include `Handoff updated: yes` in the response.

Do not use direct `sqlite3` shell queries for MCP handoff verification when these tools are available.
Do not mention a finding in chat before it exists in MCP handoff with a stable `finding_id`.

### Closing Findings (verification_evidence)

When marking a finding as `fixed`, the `update_review_finding` / `review-update` tool accepts an optional `verification_evidence` parameter (string, max 2000 chars). This field is **required** when:

- The finding has been reopened 2+ times (reopen escalation guard)
- 2+ findings for the same task were already fixed in the last 60 seconds (batch-close guard)

Good evidence: `grep_search(query="function_name", includePattern="path/to/file.py")` output when native IDE search is available, terminal `grep -n 'function_name' path/to/file.py` output for Codex/terminal-only environments, `git diff` excerpts, or inline code snippets proving the fix exists. Bad evidence: restating the resolution notes or referencing the commit SHA alone (the commit guard already covers that).

When either guard rejects the closure, the response includes a `false_fix_guard` object identifying which guard fired and current thresholds.

### Severity Mapping

The MCP `severity` field maps directly to this guide's severity levels:

- `HIGH` -> `high` -- must fix before merge
- `MEDIUM` -> `medium` -- should fix; defer only with justification
- `LOW` -> `low` -- fix if easy; otherwise next pass

---

## ACE Reflection

When recording review findings, note any `[sr-NNN]` or `[rg-NNN]` rule IDs referenced or contradicted by a finding. This is the signal used to evolve instruction-file strategy bullets.

- A finding that **confirms** a rule (the rule prevented a real failure) increments its `helpful` counter.
- A finding that **contradicts** a rule (the rule caused unnecessary friction or was wrong) increments its `harmful` counter.
- Rules accumulate evidence over time; rules with `helpful=0 harmful>=2` become pruning candidates.

### Automated Detection (daemon-cycle)

During a review cycle the **worker daemon** automatically scans new findings for ACE rule references after each `review_complete` event. When references are found:

1. Detection records are appended to `.task-state/ace_reflect_log.jsonl` (fields: `finding_id`, `rule_id`, `contradicts`, `cycle`, `timestamp`).
2. A `ace_reflect_detected` log event is emitted with the record count.
3. **No instruction-file edits are made during the daemon cycle.** Counter updates are intentionally deferred.

When more than 5 entries accumulate in `ace_reflect_log.jsonl`, the **orchestrator daemon** emits an `ace_reflect_pending` advisory warning with the pending count and a hint to run `make ace-reflect`.

### Applying Counter Updates

From the orchestrator root, run:

```bash
make ace-reflect TASK=<task-ref>
```

This calls `ace_reflect.py __main__`, which:

1. Reads all pending entries from `.task-state/ace_reflect_log.jsonl`.
2. Increments the `helpful` or `harmful` counter on the matching bullet in the canonical instruction file (`docs/agentic/instructions.md`). `CLAUDE.md` and `GEMINI.md` are symlinks to the same file; do not list them separately.
3. Records processed keys in a sidecar `.ace_dedup.json` file to prevent double-counting.
4. Prints a summary: `processed=N  incremented=N  skipped=N`.

For findings that occurred outside a daemon cycle (e.g., manual reviews):

```python
from agent_handoff_mcp.orchestration.ace_reflect import ace_reflect_on_findings
# Pass state_dir so the function writes records to the log AND applies counters
ace_reflect_on_findings(findings, instruction_files, state_dir=Path(".task-state"))
```

### Curation Report

To view pruning candidates without making any changes:

```bash
make ace-curation-report
```

This prints all bullets where `helpful=0 and harmful>=2` across all instruction files. Delete or revise those bullets in a focused PR after review.

The counter-update procedure and Reflection triggers are also documented in [../instructions.md](../instructions.md) under **Document Maintenance -- ACE Playbook Evolution**.

---

## Review Report Template

> **Only produce this file when the user explicitly requests a written report.** Findings recorded via `record_review_finding` are the canonical store.

Save to `docs/tasks/<version>/<branch-name>-branch-audit-findings.md`.

```markdown
# Branch Audit — `feature/<branch-name>`

> **Date:** YYYY-MM-DD
> **Scope:** N files changed, +X / −Y lines vs `main`
> **Categories:** ANTIPATTERN · DEAD_CODE · COMPLEXITY · GAP

---

## Summary

| Severity   | Count |
| ---------- | ----- |
| **HIGH**   | N     |
| **MEDIUM** | N     |
| **LOW**    | N     |
| **Total**  | **N** |

---

## Automated Check Results (reported by submitter)

| Check                                   | Result                                |
| --------------------------------------- | ------------------------------------- |
| `make check` (ruff + mypy + pytest)     | :white_check_mark: / :x:              |
| `npm run typecheck`                     | :white_check_mark: / :x:              |
| `npm run test -- --run`                 | :white_check_mark: / :x:              |
| `npm run lint`                          | :white_check_mark: / :x:              |
| `check-architecture-compliance.js`      | :white_check_mark: / :x: (N warnings) |
| `composer phpstan`                      | :white_check_mark: / :x:              |
| Cyclomatic complexity (radon, grade C+) | N functions flagged                   |

---

## HIGH Severity

### H-1 · <Title>

|              |                                            |
| ------------ | ------------------------------------------ |
| **Files**    | `path/to/file.py` LN                       |
| **Category** | ANTIPATTERN / DEAD_CODE / COMPLEXITY / GAP |

<Description with specific code references.>

## MEDIUM Severity

<!-- Same structure -->

## LOW Severity

<!-- Same structure -->

---

## Recommended Fix Order

### Phase 1 — Correctness (before merge)

1. **H-1** — <one-line summary>

### Phase 2 — Robustness (soon after merge)

2. **M-1** — <one-line summary>

### Phase 3 — Maintainability (tech debt backlog)

3. **L-1** — <one-line summary>

---

# Consolidated Checklist

## Phase 1 — Correctness (before merge)

- [ ] **H-1** — <action item>

## Phase 2 — Robustness

- [ ] **M-1** — <action item>

## Phase 3 — Maintainability

- [ ] **L-1** — <action item>

## Success Criteria

- [ ] Zero HIGH findings remaining
- [ ] `make check` passes
- [ ] `npm run typecheck` passes with zero new errors
- [ ] All existing tests continue to pass
- [ ] Branch audit re-run shows no regressions
```
