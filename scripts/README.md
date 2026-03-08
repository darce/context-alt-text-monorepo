# Monorepo Scripts

Cross-project scripts for the monorepo. App-specific scripts live under each app's own `scripts/` directory.

## Structure

```
scripts/
├── localwp-db.sh          # Connect to LocalWP MySQL (auto-discovers socket)
└── mcp/
    ├── mcp-server.sh       # Agent Handoff MCP launch shim
    └── unified_server.py   # Legacy non-handoff/reference MCP implementation
```

## localwp-db.sh

Connect to the LocalWP MySQL database without needing to know the volatile socket path.

```bash
./scripts/localwp-db.sh                                 # Interactive shell
./scripts/localwp-db.sh -e "SHOW TABLES LIKE '%acx%'"   # Run a query
./scripts/localwp-db.sh -e "SELECT * FROM wp_acx_clusters"
```

Supports `LOCALWP_SOCKET`, `LOCALWP_DB_NAME`, `LOCALWP_DB_USER`, `LOCALWP_DB_PASS` env overrides.

## mcp/

The canonical MCP runtime for handoff state is now the packaged `agent-handoff-mcp` server under [`packages/agent-handoff-mcp/`](/Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp/). Clients should launch the installed `agent-handoff-mcp` binary directly. `mcp/mcp-server.sh` remains a local fallback shim for development and diagnostics.

`unified_server.py` is no longer the handoff runtime. It remains only as legacy/reference code for any future extraction of non-handoff repo-intel workflows.
