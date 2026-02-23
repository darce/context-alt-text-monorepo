---
name: context-alt-text-rules
description: Embody the role of Developer for the Context Alt Text monorepo
---

# Developer Role

You are developing the Context Alt Text monorepo. This is a greenfield project with NO production users and NO data migrations required.

## Core Directives

1.  **Sovereign Read Model**: The WordPress plugin must derive ALL UI state from its own local projection tables (`wp_acx_clusters`, `wp_acx_identity_members`, `wp_acx_sync_state`). DO NOT use the FastAPI backend as a runtime HTTP proxy for read operations.
2.  **Plugin Boundary**: ONLY modify files within the monorepo directories (`apps/prototype-wp-alt-context/`, `apps/prototype-description-service/`, `packages/`, `docs/`, `scripts/`).
3.  **MCP Handoff**: You must coordinate task state using the `context-alt-text-handoff` MCP server. Update `.task-state/handoff.db` when you make decisions, record findings, or add/complete checklist actions.
4.  **No Fabricated Data**: If an endpoint or feature lacks data, surface it as missing/empty. DO NOT fabricate data.
5.  **Curation-First**: User decisions (like assigning a label to a cluster) are ground truth. Overwrite heuristics, never overwrite user curation.

## Technology Stack

*   **Backend**: Python, FastAPI, PosgreSQL, pgvector. Use `pytest`, `mypy`, and `ruff`.
*   **Plugin**: PHP 8.2+, WordPress context. Use `composer test`, `composer phpstan`. Prefix options with `acx_`.
*   **Frontend**: React, TypeScript, Vitest. Use `npm run test`, `npm run typecheck`, `npm run lint`.

## Testing

Tests must be deterministic and fully offline-capable using the `ClusterFacade` and mock data. No network calls or randomness is permitted in the core test suites unless explicitly verifying external API integration.
