---
description: Load frontend React/TypeScript context for UI work
---

**Purpose**: Prime agent context with key frontend architecture files before starting React/TS work.

**When to use**:

- Starting a new frontend task (cold start)
- Switching from backend to frontend work
- Need to understand workbench UI or job state machine

**Prerequisites**: None (read-only)

// turbo-all

Read these files to understand the frontend architecture:

1. Read the frontend context map

```bash
cat docs/agentic/maps/frontend.md
```

2. Read the main page component structure

```bash
head -100 apps/prototype-wp-alt-context/js/admin/pages/workbench/WorkbenchPage.tsx
```

3. Read the job state machine hook

```bash
head -80 apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachine.ts
```

4. Check TypeScript compilation status

```bash
cd apps/prototype-wp-alt-context && npx tsc --noEmit 2>&1 | tail -20
```
