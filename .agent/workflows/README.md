# Agent Workflows (Slash Commands)

Executable slash commands for agentic workflows. Each `.md` file defines a multi-step workflow that agents can invoke.

---

## Compatibility

| Agent / IDE            | Slash Commands | Notes                                                                              |
| ---------------------- | -------------- | ---------------------------------------------------------------------------------- |
| **Gemini for VS Code** | ✅ Native      | Built-in support via `.agent/workflows/`                                           |
| **Claude (Anthropic)** | ⚠️ Manual      | Read workflow files with `read_file`, execute steps via `run_in_terminal`          |
| **GitHub Copilot**     | ⚠️ Manual      | MCP support is version/feature-flag dependent; otherwise read and execute manually |
| **Cursor**             | ⚠️ Manual      | No native `.agent/` support; use as reference                                      |
| **Windsurf (Codeium)** | ⚠️ Manual      | Read workflow files, execute steps                                                 |
| **Codex (OpenAI)**     | ⚠️ Manual      | Can follow workflow patterns if instructed                                         |

> **For non-Gemini agents**: Reference these workflows by reading the `.md` files and executing the bash commands in sequence. The workflows serve as executable documentation regardless of native support.

---

## Access Levels (MCP vs Workflows)

MCP is optional. These workflows still work as manual runbooks when MCP is not available.

| Capability               | MCP-capable client (Gemini for VS Code) | Non-MCP client (Copilot, Claude, Cursor, Windsurf, Codex) |
| ------------------------ | --------------------------------------- | --------------------------------------------------------- |
| `mcp.servers` setting    | Supported                               | Ignored / unknown setting                                 |
| Slash command invocation | Native                                  | Manual (read the `.md`, run commands)                     |
| Workflow execution       | Automatic with turbo annotations        | Manual step-by-step                                       |

---

## Quick Start

```text
# In Gemini for VS Code chat:
/db-reset              # Reset development database
/context-backend       # Load Python backend context
/lint                  # Run all linters
/test-unit             # Run Python unit tests

# For other agents, read the workflow:
read_file .agent/workflows/db-reset.md
# Then execute each step
```

---

## Usage

Use commands like `/db-reset` or `/context-backend` in your agent interactions to trigger the corresponding workflow.

### Example: Cold Start for Backend Work

```text
User: /context-backend
Agent: [Reads backend map, API router, clustering service, runs tests]

User: Fix the UUID error in clustering
Agent: [Has context, can immediately work on the fix]
```

### Example: Debugging Database Issues

```text
User: /db-schema
Agent: [Shows all tables, sizes, row counts]

User: /db-query
Agent: Which query?
User: SELECT * FROM identity_clustering_jobs WHERE status='failed';
Agent: [Runs query, shows results]
```

### Example: Pre-Commit Validation

```text
User: /check-all
Agent: [Runs Python lint, mypy, frontend typecheck, tests, PHPStan]
       ✅ All checks pass - ready to commit

User: /git-status
Agent: [Groups changes by feature, suggests atomic commits]
```

---

## Workflow File Format

```markdown
---
description: Short description shown in command list
---

// turbo-all # Optional: auto-run all steps

1. First step
   \`\`\`bash
   command here
   \`\`\`

2. Second step
   \`\`\`bash
   another command | tail -20
   \`\`\`
```

---

## Turbo Annotations

Control automatic step execution:

| Annotation     | Behavior                               |
| -------------- | -------------------------------------- |
| `// turbo`     | Auto-run the **next** step only        |
| `// turbo-all` | Auto-run **all** steps in the workflow |
| _(none)_       | Pause and wait for user confirmation   |

### When to Use Each

- **`// turbo-all`**: Safe read-only operations (`/context-backend`, `/lint`, `/db-schema`)
- **`// turbo`**: Safe follow-up steps after a potentially dangerous one
- **No annotation**: Destructive operations (`/db-reset` first step, `/db-rollback`)

---

## Available Commands

### Context Loading

| Command             | Description                                           | Turbo |
| ------------------- | ----------------------------------------------------- | ----- |
| `/context-backend`  | Load backend Python context (maps, routers, services) | all   |
| `/context-frontend` | Load frontend React/TS context (components, hooks)    | all   |

### Testing & Validation

| Command             | Description                                   | Turbo   |
| ------------------- | --------------------------------------------- | ------- |
| `/test-unit`        | Run Python unit tests with coverage           | all     |
| `/test-integration` | Run integration tests (requires DB)           | partial |
| `/lint`             | Run all linters (ruff, mypy, eslint, phpstan) | all     |
| `/check-all`        | Full CI check (lint + types + tests)          | partial |

### Database Operations

| Command        | Description                          | Turbo   |
| -------------- | ------------------------------------ | ------- |
| `/db-schema`   | Show database schema and table info  | all     |
| `/db-query`    | Run ad-hoc SQL via db_shell.sh       | -       |
| `/db-migrate`  | Run Alembic database migrations      | partial |
| `/db-rollback` | Rollback last migration              | partial |
| `/db-reset`    | Reset dev database (**DESTRUCTIVE**) | partial |

### Development Helpers

| Command               | Description                           | Turbo |
| --------------------- | ------------------------------------- | ----- |
| `/api-trace`          | Trace endpoint across PHP→Python→TS   | all   |
| `/scaffold`           | Create new service/component skeleton | -     |
| `/git-status`         | Atomic commit suggestions by feature  | all   |
| `/compare-embeddings` | Compare embedding similarities        | -     |
| `/mcp-server`         | Start/stop MCP server for AI agents   | -     |

---

## Creating New Workflows

1. Create a new `.md` file in `.agent/workflows/`
2. Add YAML frontmatter with `description`
3. Number each step with a code block
4. Add turbo annotations as appropriate
5. Update this README's command table

### Template

```markdown
---
description: Brief description (shown in command list)
---

**Purpose**: What this workflow accomplishes.
**When to use**: Situations where this is helpful.
**Prerequisites**: Any setup required.

// turbo-all # or remove for manual confirmation

1. First step description
   \`\`\`bash
   command --with-args | tail -20
   \`\`\`

2. Second step description
   \`\`\`bash
   another-command 2>&1
   \`\`\`
```

---

## Related

- **Agent documentation**: [docs/agentic/](../../docs/agentic/)
- **MCP server**: [scripts/mcp/unified_server.py](../../scripts/mcp/unified_server.py)
- **Bootstrap guide**: [docs/agentic/BOOTSTRAP.md](../../docs/agentic/BOOTSTRAP.md)
