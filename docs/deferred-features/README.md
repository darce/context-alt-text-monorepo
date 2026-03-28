# Deferred Features

This directory consolidates work that has been explicitly deferred during planning and epic review. Items here are not forgotten; they are intentionally out of scope for the current release cycle and should be revisited when the prerequisites mature.

## Contents

| File                                                                                 | Source epics                                                               | Theme                                                                 |
| ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| [agentic-process-hardening-post-v0.3.0.md](agentic-process-hardening-post-v0.3.0.md) | `agentic-development-process-hardening-epic.md` (v0.3.0)                   | Post-v0.3.0 MCP productization, TUI follow-on, and model-eval backlog |
| [sovereignty-and-compliance.md](sovereignty-and-compliance.md)                       | `recognition-state-reconciliation-and-offline-continuity-epic.md` (v0.2.0) | Tenant sovereignty tiers, encryption, and compliance                  |
| [retention-and-audit-stretch.md](retention-and-audit-stretch.md)                     | `sync-completion-and-retention-hardening-epic.md` (v0.3.0)                 | Retention stretch goals deferred from v0.3.0                          |
| [embedding-search-optimizations.md](embedding-search-optimizations.md)               | Historical MVP follow-on planning                                           | Future vector-index/search-performance roadmap                        |
| [roster-pending-references.md](roster-pending-references.md)                         | Historical roster UX note                                                   | Deferred confirm/reject workflow for auto-matched references          |

## Notes

- Deferred features are design/backlog material, not operating rules. If a document is mainly future roadmap or proposed behavior, it belongs here instead of `docs/agentic/rules/`.

## Inclusion policy

An item belongs here when:

1. It was explicitly marked deferred in an epic or task plan (not merely unfinished or in-progress).
2. Its prerequisite work does not exist yet, or its scope exceeds the current release boundary.
3. It has enough description to be actionable in a future planning session without re-reading the full source epic.

Items are removed from this directory when they are absorbed into an active epic or task plan.
