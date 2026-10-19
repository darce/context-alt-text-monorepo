# Agent instructions

## Current billing decision

Before answering or changing accounts, credits, pricing, taxes or payment integration, read [ADR-014](docs/adrs/ADR-014-payment-processor-merchant-of-record-selection.md).

The selected integration is **standard Stripe direct + Clerk**. AltContext handles manual tax calculations and seller obligations. Stripe Managed Payments and merchant-of-record arrangements are excluded. Do not infer current selection or implementation readiness from an old plan title or receipt.

Documentation status is part of the contract: a superseded document must link its replacement prominently before the body. Remove conflicting actionable guidance. Provider selection has one authority; implementation and live acceptance require separate evidence.

## Code discovery

Prefer codebase-memory-mcp graph tools: search_graph, trace_path, get_code_snippet, query_graph and get_architecture. Use text search for literals, configuration, non-code documents or graph coverage gaps.

## Heuristics canon

Use the pinned read-only copy at `/Users/daniel/Development/heuristics-canon-current`. Follow its AGENTS.md, verify relevant release-manifest digests and cite the release version from that manifest. Never edit it or use the maintainer publish checkout as row-text authority.
