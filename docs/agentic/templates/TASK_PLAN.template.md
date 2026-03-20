# Task Plan Template

> Use this template for all implementation plans under `docs/tasks/`.
> See `docs/agentic/instructions.md` §"Consolidated Checklists" for the rules this template enforces.

---

# [TASK_TITLE]

## Problem Statement

[What user-visible behavior needs to change. 2-3 sentences max.]

## Workflow Principles

- [Key behavioral rule that guides implementation decisions]
- [Another principle, e.g., "Confirmed clusters only for suggestion eligibility"]

## Terminology

- **[Term]**: [Definition as used in this task context]

## Current State Analysis

[What works, what's broken, what's missing. Use bullet points.]

- [Component/endpoint] does X but should do Y.
- [Frontend/backend] currently [behavior]. This conflicts with [requirement].

## Proposed Solution

[Narrative description of the approach. Keep it concise — details go in Patterns to Follow.]

## Patterns to Follow

### [Pattern Name]

```python
# Code snippet showing the pattern to implement
```

### [Pattern Name]

```tsx
// Code snippet showing the pattern to implement
```

## Functions to Change

| File | Line | Change |
| --- | --- | --- |
| `path/to/file.py` | 10 | [Specific change description] |
| `path/to/file.ts` | 47 | [Specific change description] |

## Related Files

| File | Note |
| --- | --- |
| `path/to/related.py` | [Why this file is relevant but not directly changed] |

## Lane Decomposition (Multi-Agent)

> Include this section when the task naturally splits into independent backend/frontend/PHP lanes.
> Omit for single-lane tasks that one agent can complete in a single session.
> See `docs/agentic/worktree-codex-playbook.md` for the full operational playbook and `docs/agentic/lane-scoped-context.md` for prompt budget rules.

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `backend-domain` | `apps/prototype-description-service/db/**`, `apps/prototype-description-service/recognition/domain/**` | None | `PYENV_VERSION=description-service pytest recognition/tests/unit/` |
| `backend-http` | `apps/prototype-description-service/recognition/interface_adapters/http/**` | `backend-domain` | `PYENV_VERSION=description-service pytest recognition/tests/unit/` |
| `wp-proxy` | `apps/prototype-wp-alt-context/src/**` | `backend-http` (contract only) | `composer phpunit` |
| `frontend` | `apps/prototype-wp-alt-context/js/**` | `wp-proxy` (contract only) | `npm run test -- --run` |

### Merge Order

[List lanes in dependency order: schema/domain before HTTP, backend contract before WordPress proxy, proxy before frontend.]

### Manifest

Initialize the lane manifest for this task:

```bash
make lane-manifest-init TASK=<task-ref> LANE_IDS='backend-domain backend-http wp-proxy frontend' TASK_PLAN=docs/tasks/<version>/<this-file>.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools (`worker_start_all`, `worker_status`, `worker_stop`) with `backend="codex-subagent"`. The orchestrator daemon dispatches work, intakes merge-ready lanes, and refreshes downstream dependents automatically.
- **Shell fallback**: Use `make lane-open`, `make lane-run`, `make lane-handoff`, and `make lane-intake` from the orchestrator root.

---

# Consolidated Checklist

## Completed

- [ ] [Pre-existing completed work, if any]

## Phase 0: Scaffolding

- [ ] Add interface/method signatures with type hints and docstrings.
- [ ] Add `raise NotImplementedError("TODO: ...")` stubs.
- [ ] Create test files with `@pytest.mark.skip("scaffold")` or `it.todo()` stubs.
- [ ] Update API contracts in `docs/agentic/contracts/` if cross-layer.
- [ ] Verify scaffolds compile: `mypy .` / `npm run typecheck`.

## Phase 1: [Description]

- [ ] [Task 1]
- [ ] [Task 2]

## Phase 2: [Description]

- [ ] [Task 1]
- [ ] [Task 2]

## Phase 3: Tests

- [ ] [Unit test coverage]
- [ ] [Integration test coverage]
- [ ] [Frontend test coverage]

## Stretch Goals

- [ ] [Nice-to-have that won't block completion]

## Success Criteria

- [ ] [Observable outcome that proves the task is done]
- [ ] [Another observable outcome]
