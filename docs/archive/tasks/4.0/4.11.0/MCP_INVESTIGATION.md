# Investigation: MCP Servers for Local Codebase Querying

## Overview
The **Model Context Protocol (MCP)** provides a standardized way for agents to interface with external resources, including the local filesystem and codebase. Instead of relying on proprietary or ad-hoc tool definitions (like `grep_search` or `view_file` implemented differently by every agent runtime), MCP allows the codebase to expose itself as a server with discoverable **Resources**, **Tools**, and **Prompts**.

## How MCP Helps Query the Codebase

### 1. Standardized Filesystem Access
An MCP Server (like `@modelcontextprotocol/server-filesystem`) can effectively mount local directories as "resources" for the agent.

*   **Capabilities**:
    *   `list_directory`: Agents can discover file structure.
    *   `read_file`: Agents can read content.
    *   **Benefit**: The agent treats the filesystem as a structured API rather than executing raw shell commands, which is safer and less prone to hallucinated flags.

### 2. Semantic Code Search (Custom MCP Servers)
Beyond basic file operations, a custom MCP server can wrap code intelligence tools (like `ripgrep`, `ctags`, or `LSP` language servers) to provide high-level tools.

*   **Example Tool**: `search_symbol_definition(symbol_name)`
*   **Implementation**: A Python script using `FastMCP` wrapping `grep` or an LSP client.
*   **Agent usage**: The agent discovers the `search_symbol_definition` tool and calls it. The server handles the complexity of locating the symbol across files.

### 3. Context Prompts
MCP servers can expose "Prompts" (templates) that help the agent perform common tasks on the codebase.

*   **Example**: A prompt named `review_diff` that automatically loads the `git diff` and relevant file context into the agent's context window.
*   **Benefit**: Reduces "context engineering" effort. The standard "way to review code" is defined once in the server and reused by any agent.

### 4. Dynamic Discovery
Agents can query the MCP server to see what tools are available.
*   If a new tool `find_unused_exports` is added to the server, the agent immediately sees it in the tool list without requiring code changes to the agent itself.

## Implementation Examples

### Connecting to a Filesystem Server (JavaScript/Node)
Using the reference implementation:
```bash
npx -y @modelcontextprotocol/server-filesystem /path/to/codebase
```
This exposes the codebase at `/path/to/codebase` to any MCP-compliant client.

### Creating a Custom "Codebase Intelligence" Server (Python FastMCP)
```python
from fastmcp import FastMCP
import subprocess

mcp = FastMCP("CodebaseIntel")

@mcp.tool()
def search_code(query: str) -> str:
    """Search the codebase using ripgrep"""
    result = subprocess.run(["rg", query], capture_output=True, text=True)
    return result.stdout

if __name__ == "__main__":
    mcp.run()
```
This simple server abstracts the underlying search mechanism (ripgrep) from the agent.

## Recommendation for this Repo
To enhance agentic workflows, we could:
1.  **Run a Filesystem MCP Server**: Mount `apps/` and `packages/` to allow standard file access.
2.  **Develop a "Context Graph" MCP Server**: Create a custom server that exposes the "Context Maps" (`backend.md`, `frontend.md`) as structured resources, allowing agents to query "What is the context for the Recognition Service?" and receive the specific map content.


## 3. LSP (Language Server Protocol) Integration

### Definitions
The **Language Server Protocol (LSP)** is a standard JSON-RPC protocol that decouples IDEs (clients) from language-specific intelligence (servers).
*   **LSP Server**: Provides code intelligence (e.g., `gopls` for Go, `pyright` for Python, `typescript-language-server` for TS).
*   **MCP wrapper**: An MCP server that acts as an *LSP client*, forwarding agent queries to the LSP server and returning the structured results.

### Methodology
To implement LSP support via MCP:
1.  **Spawn LSP Server**: The MCP server starts the language server (e.g., `stdio` process).
2.  **Initialize**: Perform the LSP `initialize` handshake to negotiate capabilities.
3.  **Map Tools**: Expose specific LSP capabilities as MCP tools:
    *   `get_definition(path, line, character)` mapped to `textDocument/definition`
    *   `find_references(path, line, character)` mapped to `textDocument/references`
    *   `get_hover(path, line, character)` mapped to `textDocument/hover`

### Use Cases
*   **Precise Navigation**: Instead of `grep` which returns textual matches, `get_definition` takes the agent exactly to the class definition, even if it's imported under an alias.
*   **Impact Analysis**: `find_references` allows the agent to safely refactor by identifying every usage of a symbol before changing it.
*   **Documentation Lookup**: `get_hover` retrieves docstrings and type signatures without reading the file headers.

## 4. Embedding-Based Semantic Search

### Methodology for Implementation
To implement semantic search for the agent:

1.  **Ingest & Chunking**:
    *   Walk the codebase (ignoring `.gitignore`).
    *   Split files into logical chunks (e.g., functions, classes, or 500-token windows).
    *   *Tools*: `langchain`, `tree-sitter` (for syntax-aware chunking).

2.  **Generate Embeddings**:
    *   Send chunks to an embedding model (e.g., `text-embedding-3-small` or local `all-MiniLM-L6-v2`).
    *   *Result*: A float vector (e.g., 1536 dimensions) representing the code's *meaning*.

3.  **Storage (Vector DB)**:
    *   Store vectors + metadata (file path, line numbers, text content) in a vector database.
    *   *Local Option*: `pgvector` (Postgres extension), `ChromaDB`, or `FAISS`.
    *   *Integration*: Since this project uses PostgreSQL, `pgvector` is the recommended path.

4.  **Expose via MCP**:
    *   Create a tool `search_semantic(query: str, n_results: int = 5)`.
    *   On query: Embed the query string -> Cosine similarity search in DB -> Return top N code snippets.

### Use Cases
*   **Concept Search**: "Find code related to retry logic for basic authentication" (finds code without "retry" or "auth" keywords).
*   **Feature Discovery**: "Where is the user profile picture rendering handled?"
*   **Architecture Onboarding**: "How are events propagated between the frontend and backend?"

## 5. Slash Commands

### Available Commands
Investigation of `.agent/workflows` reveals **no currently configured slash commands** for this workspace.

### Capabilities
If implemented, slash commands would allow users to trigger standardized agent workflows directly (e.g., `/deploy`, `/test-all`, `/scaffold-component`). These are defined as markdown files in `.agent/workflows/`.

---

## 6. Installation & Configuration Guide

This section provides step-by-step instructions to set up MCP servers with LSP integration for this monorepo.

### Prerequisites

```bash
# Node.js (for reference MCP servers)
node --version  # v20+

# Python (for FastMCP and Pyright)
pyenv shell description-service

# Ensure uv or pip is available
uv --version || pip --version
```

---

### 6.1 Backend (Python) — MCP + Pyright LSP

#### Step 1: Install Dependencies via Makefile

> [!IMPORTANT]
> Never use naked `pip install`. All dependencies are managed via `pyproject.toml`.

```bash
cd apps/prototype-description-service
make setup  # Installs fastmcp + all dependencies including face detection
```

#### Step 2: Install Pyright LSP (Global)

Pyright is the recommended LSP for Python type checking.

```bash
npm install -g pyright
```

#### Step 3: Create MCP Server Wrapping Pyright

Create `scripts/mcp_lsp_server.py`:

```python
"""MCP Server exposing Python LSP capabilities via Pyright."""
import subprocess
import json
from fastmcp import FastMCP

mcp = FastMCP("PythonCodeIntel")

@mcp.tool()
def get_definition(file_path: str, line: int, character: int) -> str:
    """Get the definition location for a symbol at the given position."""
    # Call pyright via CLI (simplified; production would use LSP JSON-RPC)
    result = subprocess.run(
        ["pyright", "--outputjson", file_path],
        capture_output=True, text=True, cwd="apps/prototype-description-service"
    )
    return result.stdout

@mcp.tool()
def search_code(query: str) -> str:
    """Search codebase using ripgrep."""
    result = subprocess.run(
        ["rg", "--json", query, "recognition/"],
        capture_output=True, text=True, cwd="apps/prototype-description-service"
    )
    return result.stdout

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8001)
```

#### Step 4: Run the Server

```bash
cd apps/prototype-description-service
python scripts/mcp_lsp_server.py
```

The server is now available at `http://localhost:8001`.

---

### 6.2 Frontend (TypeScript/React) — MCP + TypeScript LSP

#### Step 1: Install Frontend Dependencies

```bash
cd apps/prototype-wp-alt-context
npm install  # Installs all dependencies including TypeScript
```

#### Step 2: Install TypeScript Language Server (Global, Optional)

For direct LSP access (the unified MCP server uses tsc directly):

```bash
npm install -g typescript-language-server typescript
```

#### Step 2: Create MCP Server Wrapping TS LSP

Create `scripts/mcp_ts_server.js`:

```javascript
#!/usr/bin/env node
/**
 * MCP Server exposing TypeScript LSP capabilities.
 * Simplified: runs tsc for diagnostics. Production would use full LSP.
 */
const { spawn } = require("child_process");
const http = require("http");

const PORT = 8002;

http
  .createServer((req, res) => {
    if (req.method === "POST" && req.url === "/tools/get_diagnostics") {
      let body = "";
      req.on("data", (chunk) => (body += chunk));
      req.on("end", () => {
        const { filePath } = JSON.parse(body);
        const tsc = spawn("npx", ["tsc", "--noEmit", filePath], {
          cwd: "apps/prototype-wp-alt-context",
        });
        let output = "";
        tsc.stderr.on("data", (data) => (output += data));
        tsc.stdout.on("data", (data) => (output += data));
        tsc.on("close", () => {
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ diagnostics: output }));
        });
      });
    } else {
      res.writeHead(404);
      res.end();
    }
  })
  .listen(PORT, () => console.log(`TS MCP Server on :${PORT}`));
```

#### Step 3: Run the Server

```bash
node scripts/mcp_ts_server.js
```

---

### 6.3 Filesystem MCP Server (Both Domains)

For basic file operations without custom code:

```bash
# Exposes the entire repo as a filesystem resource
npx -y @modelcontextprotocol/server-filesystem /Users/daniel/Development/context-alt-text-monorepo
```

---

### 6.4 Unified Monorepo MCP Server (Recommended)

A single Python-based MCP server that covers **all** parts of the codebase:

**Location:** `scripts/mcp/unified_server.py`

**17 Tools Available:**

| Category | Tool | Description |
|----------|------|-------------|
| **Core** | `search_code` | Search with language filter (python/typescript/php) |
| | `find_definition` | Find class/function/interface definitions |
| | `read_file` | Read file with line numbers |
| | `list_directory` | List directory contents |
| **Context** | `get_context_map` | Get backend/frontend/php/integration context |
| | `get_api_contract` | Get API contract documentation |
| | `get_instructions` | Get main development instructions |
| **Cross-Boundary** | `trace_api_endpoint` | Trace endpoint across PHP→Python→TS |
| **LSP** | `get_type_info` | Get type info via Pyright/tsc |
| | `get_diagnostics` | Run ruff/mypy/eslint/phpstan on a file |
| **Semantic** | `semantic_search` | Natural language search (keyword fallback) |
| **React/TS** | `find_react_component` | Find React component definition |
| | `find_react_hook` | Find custom hook definition |
| | `list_frontend_tests` | List test files for a component |
| **PHP/WP** | `find_wp_action` | Find WordPress action/filter hooks |
| | `find_wp_rest_route` | Find REST API route registrations |
| | `find_php_class` | Find PHP class definition |

**Run from monorepo root:**

```bash
~/.pyenv/versions/description-service/bin/python scripts/mcp/unified_server.py
```

**Benefits of unified approach:**
- Single MCP connection for cross-boundary tasks
- Consistent tool interface regardless of language
- `trace_api_endpoint` enables end-to-end debugging
- LSP integration for type information and diagnostics

Slash commands are defined as markdown files in `.agent/workflows/`. They optimize agent token usage by encoding multi-step workflows.

## 7. Implemented Slash Commands

| Command | Description | Auto-Run |
|---------|-------------|----------|
| `/context-backend` | Load backend Python context (maps + key files) | ✅ turbo-all |
| `/context-frontend` | Load frontend React/TS context (maps + key files) | ✅ turbo-all |
| `/test-unit` | Run Python unit tests with summary | ✅ turbo-all |
| `/test-integration` | Run integration tests (requires DB via `db_shell.sh`) | Partial |
| `/lint` | All linters (ruff/mypy/eslint/phpstan) | ✅ turbo-all |
| `/check-all` | Full CI validation (uses `make check`) | Partial |
| `/scaffold` | Create new service/component skeleton | Manual |
| `/api-trace` | Trace endpoint across PHP→Python→TS | ✅ turbo-all |
| `/db-reset` | Reset dev database (DESTRUCTIVE) | Partial |
| `/db-migrate` | Run Alembic migrations | Partial |
| `/db-rollback` | Rollback last migration | Manual |
| `/db-query` | Run ad-hoc SQL via `db_shell.sh` | Manual |
| `/db-schema` | Show database schema and table info | ✅ turbo-all |
| `/git-status` | Atomic commit suggestions by feature | ✅ turbo-all |

### Token Optimization Benefits

1. **Context Preloading**: `/context-*` commands load key files upfront, avoiding incremental discovery
2. **Structured Output**: Commands use `tail` and `head` to limit output size
3. **Turbo Annotations**: `// turbo-all` enables auto-execution without user approval
4. **Scope Restriction**: Each command targets specific directories

### Creating New Commands

Create `.agent/workflows/<command-name>.md`:

```markdown
---
description: Short description shown in command list
---
// turbo-all  # Optional: auto-run all steps

1. First step description
\`\`\`bash
command here
\`\`\`

2. Second step
\`\`\`bash
another command | tail -20  # Limit output
\`\`\`
```

---

## References
*   `docs/literature/extracted/Agentic_Design_Patterns.txt` (Chapter 10)
*   [Model Context Protocol Documentation](https://modelcontextprotocol.io/)
*   [Pyright LSP](https://github.com/microsoft/pyright)
*   [TypeScript Language Server](https://github.com/typescript-language-server/typescript-language-server)
