---
description: Load backend Python context for recognition service work
---

**Purpose**: Prime agent context with key backend architecture files before starting Python work.

**When to use**:

- Starting a new backend task (cold start)
- Switching from frontend to backend work
- Need to understand clustering/recognition flow

**Prerequisites**: None (read-only)

// turbo-all

Read these files to understand the backend architecture:

1. Read the backend context map

```bash
cat docs/agentic/maps/backend.md
```

2. Read the main API router structure

```bash
head -100 apps/prototype-description-service/api/routers/clusters.py
```

3. Read the clustering service interface

```bash
head -80 apps/prototype-description-service/recognition/application/identity_clustering_service.py
```

4. Check current test status

```bash
cd apps/prototype-description-service && pytest recognition/tests/ --collect-only -q | tail -20
```
