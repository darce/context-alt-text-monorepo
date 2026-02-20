# Monorepo Scripts

Cross-project scripts for the monorepo. App-specific scripts live under each app's own `scripts/` directory.

## Structure

```
scripts/
├── localwp-db.sh          # Connect to LocalWP MySQL (auto-discovers socket)
└── mcp/
    ├── mcp-server.sh       # MCP server launch script
    └── unified_server.py   # Unified MCP server for all codebases
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

The MCP (Model Context Protocol) server exposes codebase tools to coding agents. Start it via `mcp/mcp-server.sh`.
