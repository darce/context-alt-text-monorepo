---
description: Trace endpoint across all layers (PHP → Python → TS)
---

**Purpose**: Find all implementations of an API endpoint across PHP REST, FastAPI, and TypeScript.

**When to use**:

- Debugging cross-boundary issues
- Understanding full request flow
- Planning API changes

**Prerequisites**: None (uses ripgrep search)

**Usage**: Replace `<endpoint>` with the endpoint path fragment (e.g., `clusters`, `identities`).

Trace an API endpoint across all parts of the codebase. Replace `<endpoint>` with the endpoint path fragment.

// turbo-all

1. Search PHP REST routes

```bash
rg --line-number -g "*.php" "register_rest_route.*<endpoint>|<endpoint>" apps/prototype-wp-alt-context/src/ 2>/dev/null | head -20
```

2. Search FastAPI routes

```bash
rg --line-number -g "*.py" "@router.*<endpoint>|<endpoint>" apps/prototype-description-service/api/ 2>/dev/null | head -20
```

3. Search TypeScript API calls

```bash
rg --line-number -g "*.ts" -g "*.tsx" "<endpoint>" apps/prototype-wp-alt-context/js/ 2>/dev/null | head -20
```

4. Search API contracts

```bash
rg --line-number "<endpoint>" docs/agentic/contracts/ 2>/dev/null | head -10
```
