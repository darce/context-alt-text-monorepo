"""
Unified MCP Server for the Context Alt Text Monorepo.

This is a single MCP server that exposes tools for ALL parts of the codebase:
- Python backend (recognition service)
- TypeScript/React frontend
- PHP WordPress plugin

This unified approach allows agents to work across the entire monorepo with a single
MCP connection, enabling cross-boundary tasks like tracing API calls from frontend
through PHP to Python backend.

Run from monorepo root:
    python scripts/mcp/unified_server.py

Or via FastMCP CLI:
    fastmcp run scripts/mcp/unified_server.py
"""

import os
import subprocess
from pathlib import Path

from fastmcp import FastMCP

# Ensure common tools (ripgrep, etc.) are in PATH for VS Code spawned processes
os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")

# Use full path to ripgrep for reliability
RG_PATH = "/opt/homebrew/bin/rg"

# Subprocess timeout for all commands
SUBPROCESS_TIMEOUT = 10  # seconds


def run_cmd(cmd: list[str], cwd: str | None = None, timeout: int = SUBPROCESS_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a command with stdin=DEVNULL to avoid MCP stdio conflicts.
    
    MCP uses stdio for JSON-RPC, so subprocesses must not inherit stdin.
    """
    work_dir = cwd or str(MONOREPO_ROOT)
    return subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=work_dir,
        timeout=timeout,
    )


def run_rg(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run ripgrep with timeout and proper error handling."""
    return run_cmd([RG_PATH] + args, cwd=cwd)


# Initialize server
mcp = FastMCP(
    "ContextAltTextMonorepoMCP",
    instructions="""
    You are connected to the Context Alt Text monorepo MCP server.
    This server provides tools for the entire codebase:
    - Python backend: apps/prototype-description-service/
    - TypeScript frontend: apps/prototype-wp-alt-context/js/
    - PHP plugin: apps/prototype-wp-alt-context/src/
    - Shared contracts: packages/shared-contracts/
    - Documentation: docs/

    Use the appropriate tools to search, navigate, and understand the codebase.
    """,
)

# Path: scripts/mcp/unified_server.py -> parent.parent = monorepo root
MONOREPO_ROOT = Path(__file__).parent.parent.parent.resolve()


# =============================================================================
# Debug Tool
# =============================================================================


@mcp.tool()
def debug_subprocess() -> str:
    """Test subprocess execution timing."""
    import time
    start = time.time()
    proc = subprocess.Popen(
        [RG_PATH, "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = proc.communicate(timeout=5)
    elapsed = time.time() - start
    return f"Time: {elapsed:.3f}s, Output: {stdout.strip()}"


# =============================================================================
# Core Search Tools (Language-Agnostic)
# =============================================================================


@mcp.tool()
def search_code(query: str, language: str | None = None, path: str | None = None) -> str:
    """
    Search the entire monorepo using ripgrep.

    Args:
        query: The text or regex pattern to search for.
        language: Filter by language: 'python', 'typescript', 'php', or None for all.
        path: Restrict search to a specific subdirectory.

    Returns:
        Search results with file paths, line numbers, and matching lines.
    """
    cmd = [
        RG_PATH,
        "--line-number",
        "--no-heading",
        "--max-count", "50",
        # Exclude heavy/archived directories
        "-g", "!node_modules",
        "-g", "!.git",
        "-g", "!vendor",
        "-g", "!*.min.js",
        "-g", "!*.map",
        "-g", "!dist",
        "-g", "!build",
        "-g", "!*.pyc",
        "-g", "!__pycache__",
        "-g", "!*.egg-info",
        "-g", "!archived-*",
        "-g", "!storybook-static",
        "-g", "!*.epub",
        "-g", "!docs/literature",
    ]

    # Language-specific file patterns
    lang_patterns = {
        "python": ["-g", "*.py"],
        "typescript": ["-g", "*.ts", "-g", "*.tsx"],
        "php": ["-g", "*.php"],
    }

    if language and language in lang_patterns:
        cmd.extend(lang_patterns[language])

    cmd.append(query)

    if path:
        cmd.append(path)

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,  # Prevent stdin blocking
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(MONOREPO_ROOT),
            text=True,
        )
        stdout, stderr = proc.communicate(timeout=SUBPROCESS_TIMEOUT)
        if proc.returncode == 0:
            return stdout or "No matches found."
        elif proc.returncode == 1:
            return "No matches found."
        else:
            return f"Error: {stderr}"
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return f"Error: Search timed out. CMD: {' '.join(cmd)}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def find_definition(symbol: str, language: str | None = None) -> str:
    """
    Find where a symbol is defined across the monorepo.

    Args:
        symbol: The name of the symbol to find.
        language: Filter by 'python', 'typescript', 'php', or None for all.

    Returns:
        File paths and line numbers where the symbol is defined.
    """
    results = []

    try:
        if language in (None, "python"):
            # Python: class, def, async def, assignment
            for pattern in [f"^class {symbol}\\b", f"^(async )?def {symbol}\\b", f"^{symbol}\\s*="]:
                res = run_rg(["--line-number", "--no-heading", "-g", "*.py", pattern])
                if res.stdout:
                    results.append(f"Python:\n{res.stdout}")

        if language in (None, "typescript"):
            # TypeScript: function, const, class, interface, type
            for pattern in [
                f"^export (const|function|class|interface|type) {symbol}\\b",
                f"^(const|function|class|interface|type) {symbol}\\b",
            ]:
                res = run_rg(["--line-number", "--no-heading", "-g", "*.ts", "-g", "*.tsx", pattern])
                if res.stdout:
                    results.append(f"TypeScript:\n{res.stdout}")

        if language in (None, "php"):
            # PHP: class, function, interface
            for pattern in [f"^(class|interface|trait) {symbol}\\b", f"^(public |private |protected )?(static )?function {symbol}\\b"]:
                res = run_rg(["--line-number", "--no-heading", "-g", "*.php", pattern])
                if res.stdout:
                    results.append(f"PHP:\n{res.stdout}")

        return "\n".join(results) if results else f"No definition found for '{symbol}'."
    except subprocess.TimeoutExpired:
        return f"Error: Search timed out for '{symbol}'."
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def read_file(file_path: str, start_line: int = 1, end_line: int | None = None) -> str:
    """
    Read a file from the monorepo with line numbers.

    Args:
        file_path: Path relative to monorepo root.
        start_line: First line to read (1-indexed).
        end_line: Last line to read (inclusive).

    Returns:
        File contents with line numbers.
    """
    full_path = MONOREPO_ROOT / file_path
    if not full_path.exists():
        return f"Error: File not found: {file_path}"
    if not full_path.is_file():
        return f"Error: Not a file: {file_path}"

    try:
        lines = full_path.read_text().splitlines()
        end = end_line if end_line else len(lines)
        start = max(1, start_line) - 1
        end = min(end, len(lines))

        numbered_lines = [f"{i + 1:4d}: {line}" for i, line in enumerate(lines[start:end], start=start)]
        return "\n".join(numbered_lines)
    except Exception as e:
        return f"Error reading file: {e}"


@mcp.tool()
def list_directory(dir_path: str = ".") -> str:
    """
    List files and directories in a path.

    Args:
        dir_path: Path relative to monorepo root.

    Returns:
        List of files and directories.
    """
    full_path = MONOREPO_ROOT / dir_path
    if not full_path.exists():
        return f"Error: Directory not found: {dir_path}"
    if not full_path.is_dir():
        return f"Error: Not a directory: {dir_path}"

    items = []
    for item in sorted(full_path.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            items.append(f"[DIR]  {item.name}/")
        else:
            size = item.stat().st_size
            items.append(f"[FILE] {item.name} ({size:,} bytes)")

    return "\n".join(items) if items else "Empty directory."


# =============================================================================
# Context & Documentation Tools
# =============================================================================


@mcp.tool()
def get_context_map(domain: str) -> str:
    """
    Get the context map for a specific domain.

    Args:
        domain: One of 'backend', 'frontend', 'php', 'integration'.

    Returns:
        The content of the relevant context map document.
    """
    context_maps = {
        "backend": MONOREPO_ROOT / "docs" / "agentic" / "maps" / "backend.md",
        "frontend": MONOREPO_ROOT / "docs" / "agentic" / "maps" / "frontend.md",
        "php": MONOREPO_ROOT / "docs" / "agentic" / "maps" / "php-plugin.md",
        "integration": MONOREPO_ROOT / "docs" / "agentic" / "maps" / "integration.md",
    }

    if domain not in context_maps:
        return f"Unknown domain '{domain}'. Valid: {', '.join(context_maps.keys())}"

    map_path = context_maps[domain]
    if not map_path.exists():
        return f"Context map not found: {map_path}"

    return map_path.read_text()


@mcp.tool()
def get_api_contract(contract_name: str = "clustering-api") -> str:
    """
    Get an API contract document.

    Args:
        contract_name: Name of the contract (without .md extension).

    Returns:
        The content of the contract document.
    """
    contract_path = MONOREPO_ROOT / "docs" / "agentic" / "contracts" / f"{contract_name}.md"
    if not contract_path.exists():
        # List available contracts
        contracts_dir = MONOREPO_ROOT / "docs" / "agentic" / "contracts"
        if contracts_dir.exists():
            available = [f.stem for f in contracts_dir.glob("*.md")]
            return f"Contract '{contract_name}' not found. Available: {', '.join(available)}"
        return f"Contract not found: {contract_name}"

    return contract_path.read_text()


@mcp.tool()
def get_instructions() -> str:
    """
    Get the main development instructions document.

    Returns:
        The content of docs/agentic/instructions.md.
    """
    instructions_path = MONOREPO_ROOT / "docs" / "agentic" / "instructions.md"
    if not instructions_path.exists():
        return "Instructions file not found."
    return instructions_path.read_text()


# =============================================================================
# Cross-Boundary Tools
# =============================================================================


@mcp.tool()
def trace_api_endpoint(endpoint: str) -> str:
    """
    Trace an API endpoint across all layers (PHP proxy, Python backend).

    Args:
        endpoint: The endpoint path fragment (e.g., '/clusters', 'scan').

    Returns:
        All references to this endpoint across PHP and Python code.
    """
    results = []

    # Search PHP (WordPress REST routes)
    php_result = run_rg(
        ["--line-number", "--no-heading", "-g", "*.php", endpoint],
        cwd=str(MONOREPO_ROOT / "apps" / "prototype-wp-alt-context"),
    )
    if php_result.stdout:
        results.append(f"PHP (WordPress):\n{php_result.stdout}")

    # Search Python (FastAPI routes)
    py_result = run_rg(
        ["--line-number", "--no-heading", "-g", "*.py", endpoint],
        cwd=str(MONOREPO_ROOT / "apps" / "prototype-description-service"),
    )
    if py_result.stdout:
        results.append(f"Python (FastAPI):\n{py_result.stdout}")

    # Search TypeScript (API calls)
    ts_result = run_rg(
        ["--line-number", "--no-heading", "-g", "*.ts", "-g", "*.tsx", endpoint],
        cwd=str(MONOREPO_ROOT / "apps" / "prototype-wp-alt-context" / "js"),
    )
    if ts_result.stdout:
        results.append(f"TypeScript (Frontend):\n{ts_result.stdout}")

    return "\n".join(results) if results else f"No references found for endpoint '{endpoint}'."


# =============================================================================
# LSP Integration Tools
# =============================================================================


@mcp.tool()
def get_type_info(file_path: str, line: int, character: int, language: str = "typescript") -> str:
    """
    Get type information for a symbol at a specific position using LSP.

    Args:
        file_path: Path relative to monorepo root.
        line: Line number (1-indexed).
        character: Column position (0-indexed).
        language: 'typescript' or 'python'.

    Returns:
        Type information and documentation for the symbol.
    """
    full_path = MONOREPO_ROOT / file_path
    if not full_path.exists():
        return f"File not found: {file_path}"

    if language == "python":
        # Use pyright for Python hover info
        result = run_cmd(
            ["pyright", "--outputjson", str(full_path)],
            cwd=MONOREPO_ROOT,
        )
        if result.returncode == 0:
            return f"Pyright analysis for {file_path}:\n{result.stdout[:2000]}"
        return f"Pyright error: {result.stderr}"

    elif language == "typescript":
        # For TypeScript, use tsc --noEmit to get diagnostics
        result = run_cmd(
            ["npx", "tsc", "--noEmit", "--pretty", str(full_path)],
            cwd=MONOREPO_ROOT / "apps" / "prototype-wp-alt-context",
        )
        if result.returncode == 0:
            return f"TypeScript check passed for {file_path}"
        return f"TypeScript diagnostics:\n{result.stdout}\n{result.stderr}"

    return f"Unsupported language: {language}"


@mcp.tool()
def get_diagnostics(file_path: str) -> str:
    """
    Get linting/type diagnostics for a file.

    Args:
        file_path: Path relative to monorepo root.

    Returns:
        Diagnostic messages (errors, warnings) for the file.
    """
    full_path = MONOREPO_ROOT / file_path
    if not full_path.exists():
        return f"File not found: {file_path}"

    ext = full_path.suffix

    if ext == ".py":
        # Python: ruff + mypy
        ruff_result = run_cmd(
            ["ruff", "check", str(full_path), "--output-format", "text"],
            cwd=MONOREPO_ROOT,
        )
        diagnostics = f"Ruff:\n{ruff_result.stdout or 'No issues'}\n"

        mypy_result = run_cmd(
            ["mypy", str(full_path), "--no-error-summary"],
            cwd=MONOREPO_ROOT,
        )
        diagnostics += f"\nMypy:\n{mypy_result.stdout or 'No issues'}"
        return diagnostics

    elif ext in (".ts", ".tsx"):
        # TypeScript: eslint + tsc
        eslint_result = run_cmd(
            ["npx", "eslint", str(full_path), "--format", "compact"],
            cwd=MONOREPO_ROOT / "apps" / "prototype-wp-alt-context",
        )
        diagnostics = f"ESLint:\n{eslint_result.stdout or 'No issues'}\n"

        tsc_result = run_cmd(
            ["npx", "tsc", "--noEmit", str(full_path)],
            cwd=MONOREPO_ROOT / "apps" / "prototype-wp-alt-context",
        )
        diagnostics += f"\nTypeScript:\n{tsc_result.stdout or tsc_result.stderr or 'No issues'}"
        return diagnostics

    elif ext == ".php":
        # PHP: phpstan
        phpstan_result = run_cmd(
            ["./vendor/bin/phpstan", "analyse", str(full_path), "--no-progress"],
            cwd=MONOREPO_ROOT / "apps" / "prototype-wp-alt-context",
        )
        return f"PHPStan:\n{phpstan_result.stdout or 'No issues'}"

    return f"No diagnostics available for {ext} files."


# =============================================================================
# Semantic Search Tools (Embeddings-Based)
# =============================================================================


@mcp.tool()
def semantic_search(query: str, language: str | None = None, limit: int = 10) -> str:
    """
    Search the codebase semantically using natural language.

    NOTE: This is a scaffolded tool. Full implementation requires:
    1. Pre-computed embeddings stored in a vector database (pgvector)
    2. An embedding model (e.g., text-embedding-3-small)

    Currently falls back to keyword search with fuzzy matching.

    Args:
        query: Natural language query (e.g., "retry logic for authentication").
        language: Filter by 'python', 'typescript', 'php', or None for all.
        limit: Maximum number of results.

    Returns:
        Relevant code snippets ranked by semantic similarity.
    """
    # Fallback: Use ripgrep with word boundaries for now
    # This is a placeholder until embeddings are implemented
    keywords = query.lower().split()

    all_results = []
    for keyword in keywords[:3]:  # Limit to first 3 keywords
        cmd = [RG_PATH, "--line-number", "--no-heading", "-i", "--max-count", "5", keyword]

        lang_patterns = {
            "python": ["-g", "*.py"],
            "typescript": ["-g", "*.ts", "-g", "*.tsx"],
            "php": ["-g", "*.php"],
        }

        if language and language in lang_patterns:
            cmd.extend(lang_patterns[language])

        result = run_cmd(cmd, cwd=MONOREPO_ROOT)
        if result.stdout:
            all_results.append(result.stdout)

    if all_results:
        combined = "\n".join(all_results)
        lines = combined.split("\n")[:limit]
        return (
            "⚠️ Using keyword fallback (embeddings not configured).\n"
            "To enable true semantic search, implement pgvector indexing.\n\n"
            + "\n".join(lines)
        )

    return f"No results found for: {query}"


# =============================================================================
# Frontend-Specific Tools (TypeScript + React)
# =============================================================================


@mcp.tool()
def find_react_component(component_name: str) -> str:
    """
    Find a React component definition in the frontend codebase.

    Args:
        component_name: Name of the component (e.g., 'WorkbenchPage', 'ClusterCard').

    Returns:
        File location and component signature.
    """
    # Search for function components and class components
    patterns = [
        f"export (const|function) {component_name}",
        f"const {component_name}.*React\\.FC",
        f"function {component_name}.*\\(.*\\).*{{",
    ]

    results = []
    for pattern in patterns:
        result = run_rg(
            ["--line-number", "--no-heading", "-g", "*.tsx", pattern],
            cwd=MONOREPO_ROOT / "apps" / "prototype-wp-alt-context" / "js",
        )
        if result.stdout:
            results.append(result.stdout)

    return "\n".join(results) if results else f"Component '{component_name}' not found."


@mcp.tool()
def find_react_hook(hook_name: str) -> str:
    """
    Find a custom React hook definition.

    Args:
        hook_name: Name of the hook (e.g., 'useJobStateMachine', 'useClusters').

    Returns:
        File location and hook signature.
    """
    result = run_rg(
        ["--line-number", "--no-heading", "-g", "*.ts", "-g", "*.tsx", f"export (const|function) {hook_name}"],
        cwd=MONOREPO_ROOT / "apps" / "prototype-wp-alt-context" / "js",
    )
    return result.stdout if result.stdout else f"Hook '{hook_name}' not found."


@mcp.tool()
def list_frontend_tests(component: str | None = None) -> str:
    """
    List frontend test files, optionally filtered by component.

    Args:
        component: Filter tests related to a specific component.

    Returns:
        List of test files.
    """
    test_dir = MONOREPO_ROOT / "apps" / "prototype-wp-alt-context" / "js" / "admin"

    if component:
        result = run_cmd(
            ["find", str(test_dir), "-name", f"*{component}*.test.*", "-o", "-name", f"*{component}*.spec.*"],
        )
        return result.stdout if result.stdout else f"No tests found for '{component}'."

    result = run_cmd(
        ["find", str(test_dir), "-name", "*.test.*", "-o", "-name", "*.spec.*"],
    )
    return result.stdout if result.stdout else "No test files found."


# =============================================================================
# PHP WordPress-Specific Tools
# =============================================================================


@mcp.tool()
def find_wp_action(action_name: str) -> str:
    """
    Find WordPress action/filter hooks in the PHP codebase.

    Args:
        action_name: The action or filter name (e.g., 'init', 'rest_api_init').

    Returns:
        All add_action/add_filter and do_action/apply_filters calls.
    """
    patterns = [
        f"add_action.*['\\\"{action_name}",
        f"add_filter.*['\\\"{action_name}",
        f"do_action.*['\\\"{action_name}",
        f"apply_filters.*['\\\"{action_name}",
    ]

    results = []
    for pattern in patterns:
        result = run_rg(
            ["--line-number", "--no-heading", "-g", "*.php", pattern],
            cwd=MONOREPO_ROOT / "apps" / "prototype-wp-alt-context",
        )
        if result.stdout:
            results.append(result.stdout)

    return "\n".join(results) if results else f"No hooks found for '{action_name}'."


@mcp.tool()
def find_wp_rest_route(route: str) -> str:
    """
    Find WordPress REST API route registrations.

    Args:
        route: The route path or fragment (e.g., 'clusters', 'scan').

    Returns:
        All register_rest_route calls matching the route.
    """
    result = run_rg(
        ["--line-number", "--no-heading", "-A", "5", "-g", "*.php", f"register_rest_route.*{route}"],
        cwd=MONOREPO_ROOT / "apps" / "prototype-wp-alt-context",
    )
    return result.stdout if result.stdout else f"No REST route found for '{route}'."


@mcp.tool()
def find_php_class(class_name: str) -> str:
    """
    Find a PHP class definition.

    Args:
        class_name: Name of the class.

    Returns:
        File location and class declaration.
    """
    result = run_rg(
        ["--line-number", "--no-heading", "-g", "*.php", f"^class {class_name}"],
        cwd=MONOREPO_ROOT / "apps" / "prototype-wp-alt-context",
    )
    return result.stdout if result.stdout else f"Class '{class_name}' not found."


if __name__ == "__main__":
    mcp.run()
