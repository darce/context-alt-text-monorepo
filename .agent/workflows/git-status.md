---
description: Atomic commit suggestions by feature
---

**Purpose**: Analyze changes and suggest atomic commits grouped by feature area.

**When to use**:

- Before committing multiple changes
- Planning commit structure
- Following conventional commits format

**Prerequisites**: Git repository with uncommitted changes

// turbo-all

Analyze unstaged changes and suggest atomic commits grouped by feature:

1. Show git status summary

```bash
git status --short 2>&1 | head -50
```

2. Show changed files by directory

```bash
git diff --stat HEAD 2>&1 | tail -30
```

3. List modified files grouped by app

```bash
echo "=== Backend (Python) ===" && git diff --name-only HEAD -- apps/prototype-description-service/ 2>/dev/null | head -20
echo ""
echo "=== Frontend (TypeScript) ===" && git diff --name-only HEAD -- apps/prototype-wp-alt-context/js/ 2>/dev/null | head -20
echo ""
echo "=== PHP Plugin ===" && git diff --name-only HEAD -- apps/prototype-wp-alt-context/src/ 2>/dev/null | head -20
echo ""
echo "=== Documentation ===" && git diff --name-only HEAD -- docs/ 2>/dev/null | head -20
```

4. Suggest commit message format

```bash
echo ""
echo "=== Suggested Commit Format ==="
echo "Use Conventional Commits: feat|fix|docs|test|refactor|chore(scope): description"
echo ""
echo "Example atomic commits:"
echo "  git add apps/prototype-description-service/recognition/ && git commit -m 'feat(recognition): add new clustering algorithm'"
echo "  git add docs/agentic/ && git commit -m 'docs(agentic): update MCP server documentation'"
```
