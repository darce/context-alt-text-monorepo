# Agent Handoff MCP Output State-Keeping Report

> Assessment of why `agent-handoff-mcp` still loses operational state across sessions and agents even though the ledger is durable, and what output-contract changes would make re-entry, parallel-task tracking, and future tool-surface consolidation more reliable.

**Date:** 2026-04-02  
**Scope:** `packages/agent-handoff-mcp`, current MCP contract, `CURRENT_TASK.md` generation, session-load/read outputs, and the existing tool-surface consolidation work.

**Related docs:**
- `docs/tasks/tech-debt/agent-handoff-mcp-tool-surface-context-budget.md`
- `docs/agentic/contracts/agent-handoff-mcp.md`

## Executive Summary

The package does not primarily have a storage problem. It already persists durable state in the handoff database. The failure mode is that the tool outputs do not consistently expose that durable state in a machine-stable way.

Three issues are causing most of the re-entry pain:

1. tool outputs still mix canonical state with rendered artifacts and narrative fields
2. `CURRENT_TASK.md` is carrying too much cross-task and historical content, so agents keep re-consuming presentation output instead of canonical records
3. several write and compound responses report success booleans instead of a reusable mutation envelope with revisions, changed entities, and artifact sync status

The result is predictable:

- agents cannot tell which payload is authoritative when markdown and JSON both exist
- stale outputs are hard to detect because reads rarely expose a stable cursor or revision map
- structural updates are still partly communicated through prose fields such as decision rationale, resolution notes, and reopen reasons
- parallel work during an epic is visible mostly through rendered markdown rather than a compact task-index response designed for rebinds

Yes; cleaning up the output contracts would make further surface reduction possible. But the prerequisite is a stricter response schema, not a blind merge of tools. Once every read and write returns the same structural envelope, the server can safely consolidate several list/mutate surfaces behind parameterized, semi-polymorphic tools without forcing agents back into prose parsing.

## Findings

### F1. Canonical state and rendered state are still mixed together

The server already has a strong canonical store in SQLite, but the exposed read surface still treats rendered markdown as a first-class transport artifact.

Current examples:

- `generate_current_task_md()` writes `CURRENT_TASK.md` by default and can also return the full markdown body inline when `write_file=false`
- `export_handoff_state()` includes `current_task_markdown` by default via `include_markdown=True`
- the contract and README both describe `generate_current_task_md` as a normal generator alongside canonical reads, which encourages callers to treat markdown as session context rather than as a derived artifact

This makes it easy for callers to reload presentation output instead of ledger state. Once that happens, the session is vulnerable to stale renderings, token bloat, and accidental dependence on headings or prose formatting.

**Impact:** Re-entry quality depends on whichever artifact the caller loaded first, not on a single canonical state view.

### F2. `CURRENT_TASK.md` is still being asked to do too much

`CURRENT_TASK.md` now includes:

- a compact dashboard header for other tasks
- active task detail
- cross-task open findings
- deferred findings
- a durable `All Review Findings History` section containing fixed, deferred, and wontfix rows across tasks

That is too much responsibility for a single presentation file.

The biggest problem is not just size. It is semantic drift. `CURRENT_TASK.md` has become a mixed dashboard, history log, and operator handoff brief. That makes it expensive to regenerate and expensive to read. It also creates pressure to keep historical status labels like `[FIXED]` in the markdown render even though those rows already exist in the database and can be queried precisely.

**Important constraint:** do not keep printing fixed handoff issues into `CURRENT_TASK.md`. Fixed, deferred, and wontfix history belongs in query/export surfaces, not in the default operator brief.

**Impact:** token-heavy markdown becomes the de facto memory layer, and agents lose track of which parallel tasks are live versus merely mentioned in history.

### F3. Read responses do not expose enough freshness metadata

The canonical read surfaces are structured, but they do not yet provide a stable freshness contract for multi-agent use.

Examples:

- `get_handoff_state()` returns `active` and section payloads, but not a task-level cursor, section revision map, or payload digest
- `load_session()` combines `get_handoff_state()` and open findings, but the response contains no combined cursor, no child revision metadata, and no indication that the nested `state` and `open_findings` were read against the same logical snapshot
- dashboard data exists, but callers cannot cheaply ask, "What changed since my last rebind?"

Without freshness metadata, a caller cannot distinguish:

- new data from cached data
- incomplete state from intentionally omitted sections
- render drift from canonical-state drift

**Impact:** stale outputs are detected socially or heuristically instead of contractually.

### F4. Structural updates are still encoded partly as prose

The server has a durable schema for findings, blockers, actions, tests, and task state. But several important update paths still rely on prose-heavy fields for structural meaning:

- `record_decision.rationale` is explicitly markdown and frequently carries change summary, verification, and open threads
- `close_slice.rationale` is also markdown and inherits the same pattern
- `update_review_finding()` uses `resolution_notes` and `reopen_reason` as required state-transition context in several branches

Those fields are useful as human notes. They are not sufficient as machine contracts.

When the only durable explanation of a slice is a markdown rationale, downstream agents need to parse prose to answer structural questions such as:

- what entities changed
- whether a task was advanced or only documented
- what verification is still outstanding
- which parallel task or lane was affected

**Impact:** the ledger stores facts, but the meaning of those facts still leaks into prose fields.

### F5. Write responses are too thin for reliable chaining

Several write or compound tools return only a narrow success summary.

Example: `close_slice()` returns booleans like `decision_recorded`, `state_updated`, and `current_task_md_written`, but it does not return:

- the new active revision
- the decision row metadata
- a structured list of changed entities
- the render artifact version/hash/path state beyond a boolean

Likewise, many write responses return the updated row or an `ok` flag but not a standard mutation envelope. That makes tool chaining brittle because every caller has to know each tool's custom success shape.

**Impact:** agents frequently need a follow-up read after every write just to re-establish the canonical state they should already have received.

### F6. The package already has the right direction of travel; the contract is just not applied uniformly

The server already introduced useful compacting patterns:

- `sections` for selective task reads
- `detail="summary"` for truncation without semantic changes
- `fields` projections on search and artifact reads
- `load_session()` as a compound rebind helper

That is the correct design direction. The gap is consistency.

Those shaping controls are strongest on read/search surfaces, while the state/mutation and render outputs still vary widely in how much structure they expose. The package is close to a cleaner polymorphic model, but only if the remaining output contracts become uniform.

**Impact:** the surface feels partially consolidated instead of intentionally composable.

## Recommended Output Contract Changes

### 1. Make every tool return a common response envelope

Every MCP tool should return a top-level envelope with the same core metadata, regardless of entity family.

Suggested required keys:

```json
{
  "ok": true,
  "schema_version": 2,
  "tool": "load_session",
  "generated_at": "2026-04-02T14:42:11Z",
  "scope": {
    "task_ref": "E12-9",
    "lane_id": null,
    "view": "task"
  },
  "freshness": {
    "snapshot_cursor": "task:E12-9:rev:463",
    "task_revision": 463,
    "section_revisions": {
      "handoff_state": 463,
      "review_findings": 128,
      "next_actions": 44,
      "verified_tests": 19
    }
  },
  "data": {},
  "artifacts": [],
  "warnings": []
}
```

This should apply to reads, writes, searches, and generators. The `data` payload can vary by tool; the envelope should not.

### 2. Separate canonical state from rendered artifacts

Rendered outputs should move into an explicit `artifacts` section instead of being inlined into primary payloads by default.

Target behavior:

- `generate_current_task_md()` returns artifact metadata first; markdown body is opt-in
- `export_handoff_state()` defaults to `include_markdown=false`
- `load_session()` never returns markdown
- all render-producing tools expose `artifact_type`, `path`, `written`, `content_hash`, and `content_available`

Suggested artifact shape:

```json
{
  "artifact_type": "current_task_markdown",
  "path": "/repo/CURRENT_TASK.md",
  "written": true,
  "content_hash": "sha256:...",
  "content_available": false
}
```

This keeps markdown available without allowing it to pollute normal session state.

### 3. Keep historical findings out of the default `CURRENT_TASK.md` render

Default `CURRENT_TASK.md` should contain only what an agent needs to resume work quickly:

- active task identity and focus
- compact dashboard of parallel active/recent tasks
- open blockers
- pending actions
- recent decisions
- recent tests
- open findings relevant to active and related tasks

Do not include fixed, deferred, or wontfix findings in the default render. If historical audit context is needed, expose it through:

- `list_review_findings(status=...)`
- `get_handoff_state(sections=..., include_history=true)`
- export or report-specific tools

If a historical render is ever needed, it should be a different artifact class, not the default `CURRENT_TASK.md`.

### 4. Return structured mutation results from all write tools

Every action tool should return a mutation envelope with:

- `entity_family`
- `operation`
- `task_ref`
- `affected_ids`
- `before_revision`
- `after_revision`
- `follow_on_artifacts`
- `notes` for optional prose

Suggested write shape:

```json
{
  "ok": true,
  "mutation": {
    "entity_family": "review_findings",
    "operation": "update",
    "task_ref": "E12-9",
    "affected_ids": [412],
    "before_revision": 463,
    "after_revision": 464
  },
  "data": {
    "finding": {
      "finding_id": "E12-9-F4",
      "status": "fixed"
    }
  },
  "artifacts": [
    {
      "artifact_type": "current_task_markdown",
      "written": true,
      "path": "/repo/CURRENT_TASK.md"
    }
  ],
  "notes": {
    "resolution_summary": "...optional prose..."
  }
}
```

This removes the need for callers to infer the state delta from free-form fields.

### 5. Treat prose as optional notes, not as structural payload

The contract should formally distinguish between:

- machine state
- operator notes

Recommended rule:

- `rationale`, `resolution_notes`, and `reopen_reason` remain allowed as narrative notes
- no workflow should require the caller to parse those fields to know the resulting state transition
- any structural facts currently carried in prose should be duplicated in typed fields

Examples of typed replacements or companions:

- `decision_summary`: `{ "change_kind": "doc", "verification_status": "not_run", "open_threads": 2 }`
- `resolution`: `{ "status_transition": "open->fixed", "verified_commit_sha": "...", "evidence_present": true }`
- `sync`: `{ "current_task_regenerated": true, "artifact_hash": "..." }`

### 6. Add rebind-friendly freshness and diff parameters

The read surface needs a proper resumability contract.

Recommended additions:

- `since_cursor`: return only changed sections or rows since a prior snapshot
- `include_counts=true`: cheap counts even when sections are omitted
- `include_parallel_tasks=true`: compact dashboard rows in `load_session()` without forcing markdown regeneration
- `include_history=false` by default everywhere except explicit audit/export surfaces

This is what would make cross-session and multi-agent re-entry reliable instead of heuristic.

### 7. Add a compact parallel-work index to session loads

The package should stop relying on `CURRENT_TASK.md` as the main multi-task overview.

`load_session()` should return a compact task index by default, for example:

```json
{
  "parallel_tasks": [
    {
      "task_ref": "E12-9",
      "status": "in_progress",
      "last_activity": "2026-04-02 14:42:11",
      "open_blockers": 0,
      "pending_actions": 2,
      "open_findings": 1,
      "task_revision": 463
    }
  ]
}
```

That is enough for agents to know what is live without reading historical markdown.

## Would This Enable Tool Surface Reduction?

Yes; with limits.

The current surface is already partway toward parameterized polymorphism through `sections`, `detail`, and `fields`. If the output contracts are standardized first, several tools can be merged or grouped more safely.

### Good candidates for consolidation

#### A. State reads

Possible target:

- `get_state(scope, sections, detail, fields, since_cursor, include_parallel_tasks, include_history)`

This could absorb most of:

- `get_handoff_state`
- parts of `load_session`
- dashboard-style reads now exposed through `view="dashboard"`

#### B. Record listing

Possible target:

- `list_records(entity, status, severity, review_mode, task_ref, lane_id, detail, fields, limit, offset)`

This could cover several current listing/query tools while preserving explicit filters.

#### C. Record mutation

Possible target:

- `mutate_records(entity, operation, payload, expected_revision)`

This could unify many day-to-day action surfaces if the entity-specific validation remains strict behind the handler.

Examples:

- actions
- blockers
- review findings
- task status transitions

### Tools that should probably remain separate

These still have enough unique semantics that separate tools are justified:

- `close_slice`
- `export_handoff_state`
- `import_handoff_state`
- `archive_task_state`
- artifact indexing/search tools
- decision-id audit tools

### Recommended consolidation posture

Do not aim for one giant generic tool. Aim for a smaller set of semi-polymorphic tool families with uniform envelopes and strong typed validation.

That likely reduces the daily-use surface further without recreating the original monolith's ambiguity.

## Suggested Spec Direction

If this report is turned into a spec, the spec should define:

1. a versioned response envelope shared by every handoff tool
2. a stable freshness model using task and section revisions or cursors
3. artifact metadata rules that keep markdown out of default state payloads
4. default omission of fixed/deferred/wontfix history from `CURRENT_TASK.md`
5. typed mutation result envelopes for every action tool
6. a compact parallel-task index as part of session rebinds
7. the boundary between keep-separate tools and semi-polymorphic tool families

## Bottom Line

The handoff ledger is already durable enough. The main defect is that the output layer still encourages agents to consume rendered markdown and prose-heavy fields as if they were canonical state.

The fix is to make canonical state unmistakable:

- one response envelope everywhere
- explicit freshness metadata
- typed mutation results
- markdown moved to optional artifacts
- no fixed-history dump in default `CURRENT_TASK.md`

Once that is in place, a leaner tool surface becomes realistic. Without it, more polymorphism would only hide the same state-keeping problems behind fewer names.

---

## Critique — Code-Verified Assessment

> Added 2026-04-02 after code-level verification of all findings and recommendations against the actual `packages/agent-handoff-mcp` implementation. Revised same day after owner review.

### Constraints applied to this critique

1. **Greenfield policy.** This project has no production users and no data to preserve. Breaking changes are free. Historic data can be normalized or discarded. No backward-compatibility shims.
2. **Single user.** The only consumer of the MCP surface is the project owner. Agent discovery of tools matters more than stability guarantees for third parties.
3. **Tool surface reduction is an explicit goal.** Fewer tools with parameterized dispatch is preferred over many semantic tools behind visibility profiles.

### What the report gets right

**F2 is the highest-impact finding.** `_collect_all_findings_history()` in `current_task_rendering.py:307-326` runs an unbounded `SELECT * FROM review_findings` across all tasks and statuses. Every `generate_current_task_md` call renders every fixed, deferred, and wontfix finding that has ever existed in the ledger. At current scale (~1,800 findings), this already produces significant token pressure. This grows monotonically and never shrinks. Removing the "All Review Findings History" section from the default render is the single highest-value change in this report and should be implemented first.

**F1 is structurally correct.** The split between `generate_current_task_md` (writes markdown to disk), `export_handoff_state` (embeds markdown by default via `include_markdown=True`), and `load_session` (returns canonical JSON) creates ambiguity about which output is authoritative. Agents that load `CURRENT_TASK.md` on cold start consume presentation state, not canonical state.

**The compound-tool direction is validated.** `load_session` and `close_slice` already prove the pattern works. The context-budget evaluation doc confirms these are the highest-value tools per token cost.

### Where the report overstates the problem

**F5 partially mischaracterizes write tool responses.** The report claims write tools "return only a narrow success summary." Code review shows this is only true for `close_slice` (which returns boolean flags). Most other write tools already return the full inserted/updated entity row:

- `record_decision` → full decision row with all columns (`decisions.py:112-115`)
- `update_review_finding` → full finding row + commit_guard metadata (`review_findings.py:479-496`)
- `set_handoff_state` → full active row including revision number (`handoff_state.py:99-102`)
- `record_review_finding`, `report_blocker`, `record_test_result` → full entity rows

The real gap is narrower than stated: `close_slice` does not return the new revision or decision row. But calling the entire write surface "too thin" overgeneralizes from one compound tool.

**F4 (prose as structural payload) is accurate but mostly a documentation problem.** The `rationale` and `resolution_notes` fields are typed as optional strings in the schema. No code path parses them for structural decisions. The issue is that agent instructions encourage agents to encode structural facts in these fields. The fix is tighter agent instructions and optional typed companion fields, not a schema overhaul.

### Recommendations the report is missing

**R-MISS-1: Cross-task collection queries should be parameterized, not removed.** `_collect_all_open_findings`, `_collect_all_deferred_findings`, and `_collect_all_findings_history` each issue a full table scan. The first two serve a legitimate purpose (showing open/deferred findings from parallel tasks). The fix:

1. Drop `_collect_all_findings_history` from the default render (the report's R4).
2. Cap the cross-task open/deferred sections (e.g., top 5 per task, most recent first).
3. Add a `max_cross_task_findings` parameter to `generate_current_task_md`.

**R-MISS-2: `close_slice` should return the recorded decision row.** This is the single cheapest fix that would eliminate the most common follow-up read. `close_slice` already calls `record_decision` internally — it just discards the return value. Surfacing it in the response costs ~5 lines in `core.py`.

### Tool surface reduction through polymorphic dispatch

The report's original consolidation candidates (A/B/C in §Would This Enable Tool Surface Reduction) proposed the right direction but lacked specifics on enforcement. The context-budget doc warned that "further broad merges would blur semantics more than save tokens" — but that concern assumed the current per-tool parameter schemas would be inlined into mega-tool descriptions, making them just as verbose.

The viable path is different: **server-side schema enforcement per entity family, with compact tool definitions that reference external schema docs rather than inlining all variants.**

The current tool catalog costs ~2,500 tokens per session (28 tools × ~90 tokens each). A polymorphic surface can be significantly cheaper because the tool definition only needs to declare the entity family enum and a generic payload shape — the server validates entity-specific constraints at call time, and agents learn payload shapes from their instructions and prior tool responses, not from the tool definition itself.

#### Why profiles are the wrong solution

The existing `--tool-profile` mechanism (core=16 / extended=28) hides tools instead of removing them. An agent running in `core` mode cannot discover that `export_handoff_state` or `search_artifacts` exist. It cannot decide to use them, request them, or understand error messages that reference them. This creates a worse problem than a large tool catalog: **invisible capabilities that the agent might need but cannot reach.**

One unified surface with fewer, more capable tools is better than two profiles that split capabilities arbitrarily.

#### Proposed unified surface

Target: **28 tools → 12 tools**, one profile, no hidden capabilities.

| New Tool | Absorbs | Dispatch Parameter |
|----------|---------|-------------------|
| `get_state` | `get_handoff_state`, `load_session` | `view`: `task` / `session` / `dashboard`; `sections` for selective reads |
| `list_records` | `list_review_findings`, `list_next_actions`, `list_review_runs`, `get_review_coverage`, `audit_decision_ids` | `entity`: `finding` / `action` / `review_run` / `coverage` / `decision` |
| `record` | `record_decision`, `record_review_finding`, `batch_record_review_findings`, `report_blocker`, `record_test_result`, `record_review_run`, `record_artifact` | `entity`: `decision` / `finding` / `findings_batch` / `blocker` / `test` / `review_run` / `artifact` |
| `update` | `update_review_finding`, `update_next_actions`, `set_handoff_state`, `update_task_status` | `entity`: `finding` / `actions` / `state` / `task_status` |
| `close_slice` | *(stays)* | — |
| `render` | `generate_current_task_md` | — |
| `check` | `handoff_close_check` | — |
| `search` | `search_handoff`, `search_artifacts` | `scope`: `handoff` / `artifacts` |
| `get_artifact` | `get_artifact` | — |
| `purge` | `purge_artifacts` | — |
| `export` | `export_handoff_state` | — |
| `import` | `import_handoff_state`, `archive_task_state` | `operation`: `import` / `archive` |

**Enforcement model:** Each tool handler validates the `entity`/`view`/`scope` parameter against a strict schema map. Invalid entity families or malformed payloads fail fast with a structured error that includes the expected schema. The tool *description* stays compact (~120 tokens) and lists valid entity values; the per-entity payload contract lives in the spec doc, not in the tool definition.

**Token budget estimate:** 12 tools × ~120 tokens ≈ 1,440 tokens per session. Savings: ~1,060 tokens vs current 28-tool surface. Combined with the CURRENT_TASK.md history removal (F2), total per-session savings could reach 2,000+ tokens.

### Response envelope

The report's proposed envelope (R1) is the right structure. With the greenfield constraint, implement it fully in one pass rather than phasing:

```json
{
  "ok": true,
  "schema_version": 2,
  "tool": "<tool_name>",
  "scope": { "task_ref": "...", "entity": "..." },
  "data": {},
  "mutation": null,
  "artifacts": [],
  "warnings": []
}
```

Drop `generated_at` and `freshness` from v2. Add them in v3 if multi-agent contention patterns emerge. Freshness cursors (F3) are deferred — valid concern, premature investment.

The `mutation` key is present only on write responses:

```json
{
  "mutation": {
    "entity": "finding",
    "operation": "update",
    "affected_ids": [412],
    "task_revision": 464
  }
}
```

### Priority ordering for specification work

Based on impact-to-effort ratio, verified against code:

| Priority | Change | Impact | Effort | Trace |
|----------|--------|--------|--------|-------|
| **P0** | Remove "All Review Findings History" from default CURRENT_TASK.md render | Eliminates unbounded token growth per regeneration | ~10 lines in `current_task_rendering.py` | F2 |
| **P0** | Consolidate 28 tools → 12 with polymorphic dispatch | Reduces tool catalog from ~2,500 to ~1,440 tokens; eliminates profile split | Significant but bounded — server handlers already exist | F6, R-A/B/C |
| **P1** | Common response envelope on all tools | Uniform structure for agent parsing; enables mutation tracking | Mechanical across all handlers | F1, F5 |
| **P1** | Cap cross-task deferred findings in CURRENT_TASK.md | Prevents secondary token bloat | ~20 lines | R-MISS-1 |
| **P1** | Return decision row from `close_slice` | Eliminates most common follow-up read | ~5 lines in `core.py` | R-MISS-2 |
| **P2** | Default `export_handoff_state` to `include_markdown=false` | Removes markdown from canonical export | One-line default change | F1 |
| **P2** | Typed companion fields for prose (optional `decision_summary`, `resolution` structs) | Reduces prose parsing pressure | Additive schema change | F4 |
| **P3** | Freshness cursors and `since_cursor` queries | Multi-agent resumability | Significant schema work | F3 |

---

## How to Turn This Into a Specification

### Specification location

`agent-handoff-mcp` is being extracted to `darce/mcp-agent-handoff` (see AHMCP-5). Specs for the handoff package belong in that repo, not in this monorepo. This monorepo's `docs/specs/` is for monorepo-owned surfaces (description service, plugin, etc.).

```
darce/mcp-agent-handoff/              ← extracted repo
  docs/
    specs/
      output-v2.md                    ← this spec (handoff output contract)
  src/
    agent_handoff_mcp/
      ...

context-alt-text-monorepo/            ← this repo
  docs/
    specs/
      recognition-health-v1.md        ← monorepo-owned specs
      ...
    agentic/
      contracts/
        agent-handoff-mcp.md          ← consumer-facing contract, updated after spec lands
```

**Sequencing:** The output-v2 spec can be written and implemented either before or during the AHMCP-5 extraction. If implemented before extraction, the changes land in `packages/agent-handoff-mcp/` and carry over with the snapshot. If implemented after, they land directly in `darce/mcp-agent-handoff`. Either way, the spec document travels with the package.

The consumer-facing contract in this monorepo (`docs/agentic/contracts/agent-handoff-mcp.md`) is updated after the spec is implemented to reflect the new tool surface and response shapes.

### Specification structure

1. **Motivation** — link to this report and the context-budget doc as problem statements
2. **Scope** — which tools and response surfaces are affected
3. **Tool Surface** — the 12-tool unified surface with entity dispatch tables and per-entity payload schemas
4. **Response Envelope** — the common schema all tools return (v2, required and optional fields, before/after examples)
5. **CURRENT_TASK.md Render Contract** — what sections are included by default, what is opt-in, maximum sizes
6. **Mutation Response Contract** — what every write tool must return beyond the entity row
7. **Validation Criteria** — how to verify each change is correct (test commands, expected output shapes)

The spec does not need a migration plan or backward-compatibility section. Greenfield policy: break current behavior, normalize historic data if needed.

---

## General Approach for Generating Specifications from Assessment Reports

### Three-stage process

```
Assessment Report → Specification → Spec Review → Implementation Tasks
```

**Stage 1: Assessment report** (this document)

Identifies problems, validates against code, proposes directions. Written as a critique, not a commitment. Contains:
- Findings with IDs (F1, F2, ...)
- Code-verified evidence (file paths, line numbers, actual response shapes)
- Recommendations with priorities
- A critique section that challenges the findings and adds what was missed

The assessment is done when the owner has reviewed the critique and resolved disagreements. Unresolved items become explicit "deferred" notes, not silent omissions.

**Stage 2: Specification document**

Converts the prioritized subset of recommendations into binding items. Each spec item must have:

- A stable identifier (e.g., `OC-001`)
- Traceability to a finding ID or recommendation in the assessment report
- A concrete before/after example showing the change
- A **runnable** validation command or assertion that proves compliance (verified against current package — not guessed)
- A "done" definition that is testable, not subjective

Rules:
- Not every finding becomes a spec item. Only items that are (a) validated against code, (b) prioritized P0-P1, and (c) achievable without speculative dependencies.
- Separate high-certainty items from architectural bets. High-certainty items (verified code changes, small scope) go into an implementation-ready tier. Architectural bets (large rewrites, unresolved design questions) require an ADR before becoming implementation tasks.
- Each spec item should be implementable in a single PR or a small bounded set of PRs.

**Stage 2.5: Spec review gate** (mandatory before task creation)

The spec must be reviewed before implementation tasks are created. This review caught exactly the kinds of issues that create churn later: invented field names, broken validation commands, and under-specified consolidation models. This gate is now standard for contract and spec work.

No implementation tasks may be created from a spec until:
1. The spec has been reviewed with findings recorded in MCP
2. All review findings are resolved (fixed, deferred with rationale, or wontfix)
3. Validation snippets have been verified against the current package

For architectural items, the review gate applies to the ADR as well — the ADR must be reviewed before the implementation spec is written.

**Stage 3: Implementation tasks**

Derived from the spec, scoped to individual PRs. Each task references spec item IDs. Tasks are tracked through the handoff MCP as normal work items. The spec document is updated with verification evidence as items are completed.

Only implementation-ready spec items (high-certainty tier) become tasks immediately. Architectural items become ADR tasks first, then implementation tasks after the ADR is approved and the spec is revised.

### Where specs live

Specs live with the package they govern:

- **Extracted packages** (`darce/mcp-agent-handoff`): `docs/specs/<topic>-<version>.md` inside the extracted repo
- **Monorepo-owned surfaces** (description service, plugin): `docs/specs/<area>-<topic>-<version>.md` in this monorepo

Examples:
- `darce/mcp-agent-handoff/docs/specs/agent-handoff-mcp-output-contract-v2-spec.md` — handoff output contract spec
- `docs/specs/recognition-health-v1.md` — description service health endpoint spec

Once implemented and verified, the spec's binding items are folded into the relevant contract doc. The spec file stays as a historical record of the design rationale.

### Status

The output-v2 spec has been written at `packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-output-contract-v2-spec.md` (pre-extraction path; travels with AHMCP-5). It contains 7 spec items (OC-001 through OC-007) covering P0-P2 priorities from this report, with concrete before/after code, entity payload schemas, implementation ordering, and a validation script. P3 items (freshness cursors) remain deferred in this report.

**Next step:** Review the spec, then create implementation tasks from it.