# Mem0 Comparison and Feature Candidates

> **Date**: 2026-04-06
> **Scope**: Competitive assessment of Mem0 (mem0.ai) vs agent-handoff-mcp, with actionable feature candidates derived from the comparison.

## Summary

Mem0 and agent-handoff-mcp solve fundamentally different problems. Mem0 is a semantic memory layer for personalization ("what does this agent/user know?"). Agent-handoff-mcp is a task state machine for agentic workflows ("where is this task, what decisions were made, is it complete?"). The overlap is narrow — both have search and export — but the feature gap analysis surfaces several concepts worth evaluating for adoption.

## Mem0 Overview

Mem0 (mem0.ai) provides a cloud-hosted semantic memory store with an MCP server and REST API. Core capabilities:

- **Inferred memories**: Feed conversation messages, LLM extracts facts and stores them as discrete memory strings.
- **Scoping dimensions**: `user_id`, `agent_id`, `app_id`, `run_id`, `session_id`, `org_id`, `project_id` — filtering dimensions, not a hierarchy.
- **Four memory layers**: Conversation (ephemeral), Session (minutes-hours), User (long-term), Organizational (shared across agents/teams).
- **Graph memory**: Optional knowledge graph with entity extraction and relationship modeling.
- **9-tool MCP surface**: `add_memory`, `search_memories`, `get_memories`, `get_memory`, `update_memory`, `delete_memory`, `delete_all_memories`, `delete_entities`, `list_entities`.

## Concept Mapping

| agent-handoff-mcp | Mem0 Equivalent | Gap |
|---|---|---|
| Task state (`set_handoff_state`, `update_task_status`) | None | Mem0 has no task lifecycle or workflow state machine |
| Decisions/events (`record_event`) | Partial: `add_memory` | No structured event model with `event_kind`, `actor`, `rationale` |
| Review findings (`review_findings`) | None | No severity, status (open/fixed), or batch recording |
| Artifacts (`artifacts`) | Partial: metadata | No first-class artifact model with labels, MIME types, content indexing |
| Search (`search_handoff`) | `search_memories` | Mem0 search is stronger: semantic + graph + reranking vs FTS5 keyword |
| Export/import | `memory export` (async) | Mem0 supports schema-driven structured export; no direct import endpoint |
| Close checks (`handoff_close_check`) | None | No completeness validation or close guards |
| Archive (`archive_task_state`) | None | Memories are present or deleted; no snapshot/archive concept |
| Session load (`load_session`) | Scoping by `session_id`/`run_id` | Mem0 uses filter dimensions rather than compound queries |
| CURRENT_TASK.json generation | None | No rendered human-readable state mirror |

## Feature Candidates

Features derived from Mem0's API that could realistically improve agent-handoff-mcp, ranked by value and effort.

### Tier 1: Low Effort, Clear Value

#### TTL / Expiration for Records

Mem0 supports `expiration_date` on memories for automatic lifecycle management.

- **What**: Add optional `expires_at` or `ttl_days` to findings, actions, and artifacts. Auto-prune expired records on read or via a periodic sweep.
- **Why**: Stale findings and actions accumulate over time. Currently requires manual `purge` or `wontfix` disposition.
- **Effort**: Low — one column addition, one sweep query.
- **Scope**: `packages/agent-handoff-mcp/`

#### CLI Parity for Compound Tools

Mem0's MCP and REST surfaces are fully mirrored. Agent-handoff-mcp has 2 MCP-only tools (`load_session`, `close_slice`) with no CLI equivalent.

- **What**: Add `session` and `close-slice` CLI subcommands.
- **Why**: Operators debugging state from the terminal cannot use compound tools without MCP.
- **Effort**: Low — add `cli_name` and `cli_args` to existing `ToolEntry` definitions.
- **Scope**: `packages/agent-handoff-mcp/`

### Tier 2: Medium Effort, Conditional Value

#### Webhooks / Event Notifications

Mem0 supports webhooks for memory operations.

- **What**: Emit events (task completed, blocker added, findings recorded) to configured webhook endpoints or local hooks.
- **Why**: Enables external dashboards, Slack notifications, CI triggers on task state changes. Complements Claude Code hooks which are host-specific.
- **Effort**: Medium — needs a notification dispatch layer, endpoint configuration, and retry logic.
- **Scope**: `packages/agent-handoff-mcp/` (core), integration docs

#### Structured Export with Schema

Mem0's export supports Pydantic-schema-defined output transforms.

- **What**: Allow `export_handoff_state` to accept a schema/template that transforms the export into a specific structure (e.g., "export only decisions as a changelog", "export findings as a CSV-compatible shape").
- **Why**: Current export is a full JSON dump. Consumers often want a specific projection.
- **Effort**: Medium — schema validation, transform logic, template system.
- **Scope**: `packages/agent-handoff-mcp/`

#### Entity Scoping Dimensions

Mem0 tags every memory with `user_id`, `agent_id`, `app_id`, `run_id`.

- **What**: Add optional `agent_id` or `workspace_id` scoping to handoff records beyond `task_ref`. Would enable multi-workspace or multi-agent queries without task switching.
- **Why**: Currently all records are scoped to a single workspace's SQLite DB. Cross-workspace queries require export/import.
- **Effort**: Medium — schema change, query filter additions, migration for existing data.
- **Scope**: `packages/agent-handoff-mcp/`

### Tier 3: High Effort, Speculative Value

#### Semantic Search (Vector + Reranking)

Mem0's strongest feature. Vector embeddings + graph-augmented retrieval.

- **What**: Add embedding-based search alongside FTS5 keyword search.
- **Why**: Current `search_handoff` is keyword-only. Semantic search would improve recall for natural-language queries against decision rationales and finding descriptions.
- **Effort**: High — requires embedding model dependency, vector storage, and reranking logic.
- **Scope**: `packages/agent-handoff-mcp/` — would add a runtime dependency (e.g., `sentence-transformers` or API-based embeddings).
- **Evaluation**: Marginal value given the structured nature of handoff data. FTS5 works well for exact keyword matching on decision IDs, task refs, and file paths. Semantic search adds value mainly for free-text rationale fields.

#### Graph Memory / Relationship Extraction

Mem0 extracts entities and relationships from stored content.

- **What**: Build a relationship graph from decisions, findings, and artifacts (e.g., "task AHMCP-7 produced finding H-1 which was fixed by commit e518df89").
- **Why**: Would enable traversal queries like "what decisions led to this finding?" or "what tasks touched this file?".
- **Effort**: High — requires LLM calls on every write or a batch extraction pipeline.
- **Scope**: Not practical for a local-first SQLite tool. Better suited to a hosted service.

#### LLM-Inferred Memory Extraction

Mem0's core differentiator: feed it conversations, get structured facts.

- **What**: Auto-extract key facts from decision rationales and review findings into a condensed memory layer.
- **Why**: Would reduce context loading costs — agents could load a condensed fact set instead of scanning full decision history.
- **Effort**: High — requires LLM dependency, quality tuning, fact deduplication.
- **Scope**: Fundamentally changes the architecture from a ledger to an inference system. Not aligned with agent-handoff-mcp's local-first, deterministic design.

## Conclusion

Mem0 and agent-handoff-mcp are complementary, not competing. Mem0 excels at semantic memory and personalization; agent-handoff-mcp excels at structured workflow state and governance. The most practical features to adopt are **TTL/expiration** (low effort, clear housekeeping value) and **CLI parity for compound tools** (low effort, completeness). Medium-term, **webhooks** and **structured export** are worth evaluating if external integration needs arise.

## CLI vs MCP Surface Parity

Current sync status (for reference):

| Category | Count | Details |
|---|---|---|
| MCP tools with CLI | 15/17 | Full arg mapping, custom dispatch for domain tools |
| MCP-only (no CLI) | 2 | `load_session`, `close_slice` |
| CLI-only (no MCP) | 2 | `artifact-list`, `artifact-terms` — convenience wrappers |
| Special CLI commands | 4 | `serve-stdio`, `serve-http`, `doctor`, `dashboard` |
