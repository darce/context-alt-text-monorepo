"""
Unified MCP Server for the Context Alt Text Monorepo.

Provides domain-specific tools that Copilot/Pylance cannot offer natively:
- Cross-boundary endpoint tracing (PHP → Python → TypeScript)
- WordPress hook and REST route discovery
- React component/hook lookup
- Monorepo documentation access (context maps, API contracts, instructions)

Tools that duplicate Copilot built-ins (grep_search, read_file, list_dir,
get_errors, semantic_search) or Pylance MCP (type info, diagnostics) have
been intentionally omitted. Use those native tools instead.

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

    This server provides DOMAIN-SPECIFIC tools that complement (not duplicate)
    the host editor's built-in capabilities:

    - Cross-boundary tracing: trace_api_endpoint (PHP → Python → TS)
    - WordPress: find_wp_action, find_wp_rest_route, find_php_class
    - React/TS: find_react_component, find_react_hook, list_frontend_tests
    - Documentation: get_context_map, get_api_contract, get_instructions

    For general-purpose operations, use the host editor's native tools:
    - File reading/searching → Copilot's read_file, grep_search
    - Diagnostics/errors → Copilot's get_errors, Pylance MCP tools
    - Directory listing → Copilot's list_dir
    """,
)

# Path: scripts/mcp/unified_server.py -> parent.parent = monorepo root
MONOREPO_ROOT = Path(__file__).parent.parent.parent.resolve()


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
