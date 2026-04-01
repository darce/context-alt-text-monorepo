# Retire Legacy unified_server.py Handoff Surface

**Priority:** Low
**Effort:** ~30-60 minutes
**Risk:** Low

## Current state

`scripts/mcp/unified_server.py` is no longer part of the supported handoff runtime. The live handoff contract is the packaged `agent-handoff-mcp` binary, while `unified_server.py` remains only as legacy repo-intel reference code and a deprecation surface for removed handoff entrypoints.

## Problem

The file still exists in the monorepo, so agents keep encountering it during search and cold-start discovery. Instructions already warn not to use it, but removal is not yet tracked as an explicit cleanup slice.

## Proposed cleanup

- Remove the deprecated handoff-facing surface from `scripts/mcp/unified_server.py` once repo-intel consumers are fully migrated.
- Keep any remaining repo-intel functionality only if it has an explicit owning contract and runtime path.
- Delete obsolete warnings from instructions and related docs after removal lands.

## Exit criteria

- `scripts/mcp/unified_server.py` is either deleted or reduced to an explicitly owned repo-intel runtime with no deprecated handoff entrypoints.
- `docs/agentic/instructions.md` no longer needs handoff deprecation warnings for this file.
- `docs/agentic/contracts/repo-intel-mcp-candidates.md` is updated to reflect the final ownership state.
