# Orchestration Context Retrieval and Artifact Indexing

## Problem Statement

The orchestration hardening work gives workers bounded prompts, context-pressure metrics, and safer daemon behavior, but it still leaves one major source of waste in place: large MCP/tool outputs are either pushed directly into prompt context or dropped after a shallow summary. We need a retrieval layer for orchestration so agents working in `apps/` can index logs, JSON payloads, docs, search results, and handoff evidence once, then pull back only the small slices they need.

## Workflow Principles

- **Structured handoff state remains authoritative.** `agent-handoff-mcp` tables for actions, blockers, findings, reports, and lane messages stay the source of truth for workflow state.
- **Large artifacts stay out of prompts by default.** Prompts should carry summaries and artifact references, not raw logs or full tool payloads.
- **Retrieval must be scope-first.** Search should narrow by `task_ref`, `lane_id`, `app_root`, and source kind before ranking text matches.
- **Prompt expansion must be budget-aware.** Retrieval should only widen context when the lane prompt still has safe headroom.
- **License-safe reimplementation only.** Borrow concepts from `context-mode`; do not vendor Elastic-2.0 code into this repo.
- **Artifact storage is a sidecar, not a workflow export format.** Large indexed payloads should not bloat handoff export/import or `CURRENT_TASK.md`.

## Terminology

- **Artifact source**: A stored MCP/tool result, document body, log, JSON payload, or generated report identified by stable metadata such as `task_ref`, `lane_id`, `source_kind`, and `source_label`.
- **Artifact chunk**: A searchable segment of an artifact source, sized for FTS5/BM25 retrieval and prompt injection.
- **Artifact reference**: A compact identifier stored in lane messages, briefs, or worker reports that points to indexed content without embedding the full payload.
- **Retrieval budget**: The maximum prompt space that artifact-derived context may consume in a worker turn after required assignment items are rendered.
- **Scoped search**: A search that first filters candidate sources by orchestration metadata, then ranks remaining chunks by text relevance.

## Current State Analysis

- `lane_prompt.py` now caps assignment, brief, lane-history, and global-context sections and measures prompt utilization, but it still renders lane context from recency-bounded SQL lists rather than relevance-ranked retrieval.
- `agent-handoff-mcp` stores structured textual state in SQLite and exposes list/read tools, but it does not maintain a full-text index over large evidence blobs or cross-row search projections.
- Worker reports and lane messages are good containers for summaries and references, but they are not sufficient for retaining bulky artifacts such as test failures, long grep results, HTTP payloads, or copied documentation.
- The current handoff database should remain portable and reasonably small because export/import and archive workflows are now part of normal orchestration.
- `apps/` work regularly depends on high-volume evidence like pytest failures, migration traces, REST responses, schema dumps, and generated reports; these are precisely the kinds of payloads that hurt prompt budgets.
- Hardening solved measurement and observability of context pressure, but it did not add a new substrate for getting context back under control when operators or workers encounter large evidence sets.

## Proposed Solution

Add a sidecar retrieval subsystem to `agent-handoff-mcp` backed by a separate `.task-state/mcp-artifacts.db` SQLite database. The sidecar will ingest large MCP/tool artifacts as chunked sources, index them with FTS5/BM25, and expose scoped search/read tools that workers and orchestrators can use instead of replaying raw payloads in prompts. The first implementation should use a simple, license-safe core: markdown/plaintext/JSON chunking, `porter unicode61` FTS5 ranking with BM25, compact snippets, dedupe-on-reindex by stable source label, and prompt-budget-aware retrieval in `lane_prompt.py`. Trigram/RRF/fuzzy enhancements can follow after the basic workflow proves itself on real `apps/` tasks.

## Patterns to Follow

### Sidecar Artifact Index

```sql
CREATE TABLE IF NOT EXISTS artifact_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_ref TEXT NOT NULL,
    lane_id TEXT,
    app_root TEXT,
    source_kind TEXT NOT NULL,
    source_label TEXT NOT NULL,
    content_type TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    metadata_json TEXT,
    summary TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(task_ref, lane_id, source_kind, source_label)
);

CREATE VIRTUAL TABLE IF NOT EXISTS artifact_chunks_fts USING fts5(
    title,
    body,
    source_id UNINDEXED,
    task_ref UNINDEXED,
    lane_id UNINDEXED,
    app_root UNINDEXED,
    source_kind UNINDEXED,
    content_type UNINDEXED,
    tokenize='porter unicode61'
);
```

### Artifact Ingestion Gate

```python
def maybe_record_artifact(
    *,
    task_ref: str,
    lane_id: str | None,
    app_root: str | None,
    source_kind: str,
    source_label: str,
    content: str,
    content_type: str,
    summary: str,
) -> ArtifactRef | None:
    if len(content.encode("utf-8")) < 4096 and content.count("\n") < 80:
        return None

    return artifact_index.upsert_source(
        task_ref=task_ref,
        lane_id=lane_id,
        app_root=app_root,
        source_kind=source_kind,
        source_label=source_label,
        content_type=content_type,
        summary=summary,
        content=content,
    )
```

### Budget-Aware Prompt Retrieval

```python
def _artifact_context_section(
    *,
    retrieval_queries: list[str],
    artifact_refs: list[str],
    budget_chars: int,
) -> list[str]:
    if budget_chars <= 0:
        return []

    results = search_artifacts(
        queries=retrieval_queries,
        artifact_refs=artifact_refs,
        limit=4,
    )

    lines: list[str] = []
    used = 0
    for row in results:
        rendered = f"[{row.source_label}] {row.title}: {row.snippet}"
        if used + len(rendered) > budget_chars:
            break
        lines.append(rendered)
        used += len(rendered)
    return lines
```

## Functions to Change

| File | Line | Change |
| --- | --- | --- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/artifact_index.py` | new | Add the sidecar SQLite/FTS5 runtime, chunkers, upsert logic, and scoped search helpers. |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/config.py` | TBD | Add runtime config for artifact DB location, retention settings, and size thresholds. |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | 1199 | Add artifact record/search/read/list/purge tool implementations and any structured-memory FTS projection helpers. |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | TBD | Export new artifact tools through the MCP API surface and tool description map. |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` | TBD | Add fallback CLI commands for artifact indexing and search. |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/runtime.py` | TBD | Ensure sidecar DB paths resolve correctly for shared orchestrator state across worktrees. |
| `packages/agent-handoff-mcp/tests/test_artifact_index.py` | new | Add unit tests for chunking, dedupe-on-reindex, scoped search, and snippet rendering. |
| `packages/agent-handoff-mcp/tests/test_artifact_tools.py` | new | Add integration tests for MCP tool behavior against temporary sidecar DBs. |
| `scripts/mcp/lane_prompt.py` | 365 | Add artifact-ref discovery, retrieval-budget accounting, and optional artifact-context rendering. |
| `scripts/mcp/lane_exec.py` | 372 | Index large backend outputs/details and attach artifact references instead of replaying bulky payloads. |
| `scripts/mcp/worker_daemon.py` | 911 | Thread artifact references into worker status/observability and avoid duplicating raw evidence in daemon summaries. |
| `scripts/mcp/orchestrator_daemon.py` | TBD | Allow orchestrator guidance and downstream brief generation to attach artifact references when evidence is too large for inline messages. |
| `mk/lane-worker.mk` | TBD | Add make targets for artifact search/debug helpers if operator workflows need shell fallbacks. |
| `docs/agentic/contracts/agent-handoff-mcp.md` | TBD | Document the new artifact tool surface, sidecar semantics, and prompt-budget expectations. |
| `docs/tasks/8.0/orchestration-context-retrieval-task-plan.md` | new | Track the implementation plan and rollout checklist for this retrieval layer. |

## Related Files

| File | Note |
| --- | --- |
| [docs/tasks/8.0/orchestration-hardening-task-plan.md](/Users/daniel/Development/context-alt-text-monorepo/docs/tasks/8.0/orchestration-hardening-task-plan.md) | Assumed complete; provides the context-pressure and prompt-budget baseline this task builds on. |
| [scripts/mcp/lane_prompt.py](/Users/daniel/Development/context-alt-text-monorepo/scripts/mcp/lane_prompt.py) | Existing lane-scoped prompt renderer and context utilization calculator. |
| [scripts/mcp/lane_exec.py](/Users/daniel/Development/context-alt-text-monorepo/scripts/mcp/lane_exec.py) | Worker execution path where large results can be summarized and indexed. |
| [scripts/mcp/worker_daemon.py](/Users/daniel/Development/context-alt-text-monorepo/scripts/mcp/worker_daemon.py) | Worker lifecycle and observability path that should surface artifact refs rather than raw evidence blobs. |
| [packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py](/Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py) | Canonical MCP runtime where artifact tools should live. |
| [docs/agentic/contracts/agent-handoff-mcp.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/contracts/agent-handoff-mcp.md) | Contract doc that must explain new artifact behavior and sidecar boundaries. |
| [docs/tasks/8.0/orchestration-tui-monitoring-task-plan.md](/Users/daniel/Development/context-alt-text-monorepo/docs/tasks/8.0/orchestration-tui-monitoring-task-plan.md) | Future monitoring surface that can later expose artifact-search telemetry and ref counts. |

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `mcp-artifact-runtime` | `packages/agent-handoff-mcp/**` | None | `PYENV_VERSION=description-service pytest packages/agent-handoff-mcp/tests/` |
| `worker-retrieval` | `scripts/mcp/lane_prompt.py`, `scripts/mcp/lane_exec.py`, `scripts/mcp/worker_daemon.py`, `scripts/mcp/orchestrator_daemon.py`, `mk/lane-worker.mk` | `mcp-artifact-runtime` | `PYENV_VERSION=description-service pytest scripts/mcp/tests/ packages/agent-handoff-mcp/tests/` |
| `docs-contracts` | `docs/agentic/contracts/**`, `docs/tasks/8.0/**` | `worker-retrieval` (behavior only) | docs review |

### Merge Order

`mcp-artifact-runtime` -> `worker-retrieval` -> `docs-contracts`

### Manifest

Initialize the lane manifest for this task:

```bash
make lane-manifest-init TASK=orchestration-context-retrieval LANE_IDS='mcp-artifact-runtime worker-retrieval docs-contracts' TASK_PLAN=docs/tasks/8.0/orchestration-context-retrieval-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools with `backend="codex-subagent"` so the retrieval path is exercised inside the same orchestration runtime it will serve.
- **Shell fallback**: Use `make lane-open`, `make lane-run`, `make lane-handoff`, and new artifact helper targets from the orchestrator root if MCP worker lifecycle tools are unavailable.

---

# Consolidated Checklist

## Completed

- [ ] Orchestration hardening has already delivered lane-scoped prompt caps, context-utilization measurement, and daemon-side context-pressure events.
- [ ] Worker execution already runs against shared orchestration state and fresh-turn worker sessions, so the remaining context problem is retrieval, not thread-history carry-over.

## Phase 0: Scaffolding

- [ ] Add sidecar artifact-index module(s) and runtime config without changing existing handoff-state semantics.
- [ ] Add MCP API/CLI stubs for recording, searching, listing, and reading artifacts.
- [ ] Add test scaffolds for artifact chunking, indexing, and prompt-integration behavior.
- [ ] Update `docs/agentic/contracts/agent-handoff-mcp.md` with provisional tool signatures and sidecar rules.
- [ ] Verify scaffolds import cleanly and FTS5 availability is checked in tests/doctor tooling where needed.

## Phase 1: Sidecar Storage and Chunking

- [ ] Create `.task-state/mcp-artifacts.db` path resolution that works from orchestrator and lane worktrees.
- [ ] Implement artifact source metadata tables plus FTS5 chunk tables.
- [ ] Implement markdown chunking by headings, plaintext chunking by line groups, and JSON chunking by key path.
- [ ] Implement dedupe-on-reindex for stable `source_label` updates so iterative runs do not accumulate stale chunks.
- [ ] Add retention/purge helpers keyed by age, task archival, or source replacement.

## Phase 2: Retrieval Tools

- [ ] Implement `record_artifact` with task/lane/app/source metadata and content hashing.
- [ ] Implement `search_artifacts` with `task_ref`, `lane_id`, `app_root`, `source_kind`, and `content_type` filters plus BM25 ranking and compact snippets.
- [ ] Implement `get_artifact_source` or equivalent readback for exact source inspection when a search hit needs full fidelity.
- [ ] Implement `list_artifact_sources` so operators and prompts can discover available evidence without reading raw content.
- [ ] Keep v1 search simple and deterministic; defer trigram, RRF, or fuzzy correction until the base workflow lands.

## Phase 3: Worker and Orchestrator Integration

- [ ] Add ingestion gates in `lane_exec.py` so large execution outputs are indexed and replaced with summaries plus artifact refs.
- [ ] Update worker handoff/report paths to store artifact refs in message payloads or artifact lists instead of embedding bulky evidence.
- [ ] Let orchestrator guidance and downstream briefs attach artifact refs when the evidence exceeds prompt-safe limits.
- [ ] Ensure `CURRENT_TASK.md`, export/import, and archive flows do not inline or duplicate artifact bodies.
- [ ] Preserve a clear operator path to inspect exact artifact content outside the worker prompt.

## Phase 4: Prompt Retrieval Integration

- [ ] Teach `lane_prompt.py` to discover open artifact refs from lane messages, briefs, and the latest relevant worker report.
- [ ] Add a retrieval-budget calculation so artifact snippets compete only for the prompt space left after required assignment sections.
- [ ] Build retrieval queries from the active assignment, brief summary, blocker text, and finding descriptions rather than naive recency.
- [ ] Render compact artifact snippets with source labels and references, not full bodies.
- [ ] Skip retrieval when prompt pressure is already elevated unless an explicit inspection flag is requested.

## Phase 5: Structured-Memory Search

- [ ] Add an optional FTS projection over `lane_messages`, `worker_reports`, `blockers`, `review_findings`, and `decisions` for smarter handoff search.
- [ ] Keep structured-memory search separate from artifact search results so workflow state and evidence remain conceptually distinct.
- [ ] Hydrate structured search hits back through canonical row reads before presenting them to operators or prompt builders.
- [ ] Add source-kind and row-kind labels so results clearly show whether they came from workflow state or artifact evidence.

## Phase 6: Tests

- [ ] Unit test chunking rules for markdown, plaintext, and JSON inputs.
- [ ] Unit test scoped BM25 search, snippet generation, and dedupe-on-reindex behavior.
- [ ] Integration test artifact MCP tools against temporary sidecar DBs from both orchestrator-root and lane-worktree entrypoints.
- [ ] Integration test `lane_prompt.py` artifact retrieval with safe and over-budget prompt scenarios.
- [ ] Smoke test a real `apps/` lane workflow where large pytest or HTTP output is indexed and later retrieved without direct prompt injection.

### Deferred from Orchestration Hardening

- [ ] Integration test: full daemon cycle with scope violation injected, verify review is skipped and event emitted. _(Requires mocking the full `run_worker_daemon()` monolith; individual scope gate behavior is verified by unit tests TestCheckScopeViolations + TestScopeViolationEventName in `test_hardening.py`.)_
- [ ] Integration test: full daemon cycle exhausting 3 times, verify streak tracking and auto-pause. _(Same reason; exhaustion behavior is verified by TestExhaustionStreak + TestExhaustionStreakEvent + TestEnsureLaneWorkersExhaustionGate in `test_hardening.py`.)_

## Stretch Goals

- [ ] Add trigram fallback, reciprocal-rank fusion, and fuzzy correction after v1 search quality is validated.
- [ ] Surface artifact search telemetry and indexed-source counts in the orchestration TUI/dashboard.
- [ ] Add suggested-query generation or distinctive-term hints for freshly indexed artifacts.
- [ ] Add lane- or app-root-specific retention policies so long-lived tasks can keep durable evidence while ephemeral traces expire quickly.

## Success Criteria

- [ ] A worker can index large logs, JSON payloads, docs, or command output once and later retrieve only the relevant chunks by scoped search.
- [ ] Lane prompts for `apps/` tasks include summaries plus artifact refs/snippets instead of replaying raw bulky MCP output.
- [ ] Context-pressure metrics remain stable or improve on representative high-evidence tasks because retrieval respects prompt budgets.
- [ ] Handoff export/import and `CURRENT_TASK.md` remain compact because artifact bodies stay in the sidecar cache rather than the canonical handoff snapshot.
